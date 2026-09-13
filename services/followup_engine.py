"""Follow-up Engine — the 培育闭环.

Daily job that scans all active prospects and decides:
1. NO REPLY (0+ days since last outbound, no inbound reply) → draft follow-up, auto-enqueue email
2. HAS INBOUND REPLY (client replied, unanalyzed) → auto-analyze
3. CHANNEL SWITCH (2+ consecutive no-reply outbounds) → suggest LinkedIn or WhatsApp

Uses ai_router.call_simple for AI calls.
"""
import json
import logging
import re
from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo

from sqlalchemy.orm import Session

from config import DAILY_EMAIL_LIMIT
from database import SessionLocal
from services.holiday_calendar import should_skip_cold_outreach, get_holiday_context_for_country
from services.trade_show_calendar import get_show_context_for_prospect, get_show_icebreaker
from models import Prospect, Interaction, EmailQueue, DailyEmailStats, Intelligence, KnowledgeBase
from services.ai_router import call_simple, get_voice_rules, get_signature_for_profile
from services.writing_rules import SPEC_LINE, WRITING_RULES, sanitize_tolerance, sanitize_attachment_language

logger = logging.getLogger(__name__)

# ── Timing rules ──
NO_REPLY_DAYS = 3  # 3天冷静期后才追
MAX_FOLLOW_UPS = 5
CHANNEL_SWITCH_THRESHOLD = 2
# ── Anti-bunching: max prospects per day for next_follow_date ──
MAX_PER_DAY = 4
# ── Best email days: Tue/Wed/Thu in customer's timezone.
BEST_EMAIL_DAYS = {1, 2, 3}  # Python weekday: 0=Mon, 1=Tue, 2=Wed, 3=Thu

# ── Dormant review assignment: AI-varying window instead of flat 30d ──
#     Shortest = higher-value prospects we shouldn't lose sight of
#     Longest  = low-value or no custom specs mentioned
DORMANT_MIN_DAYS = 14
DORMANT_MAX_DAYS = 90


def _next_available_slot(db: Session, preferred: date) -> date:
    """Find the next day with < MAX_PER_DAY prospects already scheduled.
    If preferred date is full, keep advancing until a slot opens.
    Weekends are NOT skipped — next_follow_date is a planning signal, not a send signal.
    Actual email sending is gated by is_business_hours_now() + BEST_EMAIL_DAYS."""
    from sqlalchemy import func as _func
    d = preferred
    max_attempts = 60
    for _ in range(max_attempts):
        count = db.query(_func.count(Prospect.id)).filter(
            Prospect.is_deleted == 0,
            Prospect.next_follow_date == d.isoformat(),
        ).scalar() or 0
        if count < MAX_PER_DAY:
            return d
        d += timedelta(days=1)
    return d  # fallback — should never reach here


def _compute_dormant_review_days(p: Prospect, out_count: int, last_out_date, today: date) -> int:
    """冷却复审节奏：统一 15 天（不分价值/样品状态，简单统一）。"""
    return 15


def _default_review_reason(p: Prospect) -> str:
    """Human-readable reason shown on the Today board when no specific one was set."""
    stage = (p.sales_stage or "").lower()
    if stage == "cooling":
        return "Cooling period — scheduled re-review"
    if (p.email_status or "") == "bounced":
        return "Email bounced — update contact info"
    if not (p.email or p.dm_email):
        return "No email on file — update contact details"
    return "Next follow-up step"


def _get_writing_rules_inline() -> str:
    """Return inline writing rules for AI prompts (no DB dependency)."""
    return SPEC_LINE + "\n\n" + WRITING_RULES


def _days_since(dt):
    if not dt: return 99999
    if isinstance(dt, str):
        try: dt = datetime.fromisoformat(dt.replace("Z", "+00:00"))
        except: return 99999
    delta = datetime.utcnow() - dt.replace(tzinfo=None) if dt.tzinfo else datetime.utcnow() - dt
    return max(0, delta.days)


def _last_outbound_date(interactions):
    for ix in reversed(interactions):
        if ix.direction == "outbound": return _naive(ix.interacted_at)
    return None


def _last_inbound_date(interactions):
    for ix in reversed(interactions):
        if ix.direction == "inbound": return _naive(ix.interacted_at)
    return None


def _naive(dt):
    """Strip timezone so stored datetimes compare cleanly regardless of tzinfo."""
    if dt is None:
        return None
    if hasattr(dt, 'tzinfo') and dt.tzinfo is not None:
        return dt.replace(tzinfo=None)
    return dt


def _count_outbound_since_last_inbound(interactions):
    count = 0
    for ix in reversed(interactions):
        if ix.direction == "inbound": break
        count += 1
    return count


def _pick_next_channel(last_channel, country, consecutive_no_reply):
    if consecutive_no_reply >= CHANNEL_SWITCH_THRESHOLD:
        if last_channel == "email":
            if country and country.upper() in ("IN","TR","IR","AE","SA","PK","EG","BR"):
                return "whatsapp"
            return "linkedin"
        elif last_channel == "linkedin":
            if country and country.upper() in ("IN","TR","AE","SA","PK"):
                return "whatsapp"
            return "email"
        elif last_channel == "whatsapp":
            return "email"
    return "email"


def _build_context(prospect, interactions, intel):
    parts = [
        f"Client: {prospect.company or '?'} | Country: {prospect.country or '?'}",
        f"Profile: {prospect.profile_type or '?'} | Score: {prospect.ai_score or '?'}/10",
        f"Industry: {prospect.industry or '?'} | Size: {prospect.size or '?'}",
    ]
    if intel and intel.website_key_points:
        parts.append(f"Website: {intel.website_key_points[:300]}")
    if intel and intel.icebreak_angles:
        parts.append(f"Icebreaker angles: {intel.icebreak_angles[:300]}")
    if interactions:
        parts.append(f"\nInteraction history ({len(interactions)}):")
        for ix in interactions[-10:]:
            dtag = "[Client]" if ix.direction == "inbound" else "[Us]"
            ts = str(ix.interacted_at)[:16] if ix.interacted_at else "?"
            text = (ix.content or ix.subject or "")[:150]
            parts.append(f"  {dtag} {ts} {ix.channel}: {text}")

    # ── 知识库：查找同行业/同画像的成功案例 ──
    _inject_case_studies(prospect, parts)

    # ── 展会：最近的行业展会信息 ──
    try:
        show_ctx = get_show_context_for_prospect(
            country=prospect.country,
            industry=prospect.industry,
            profile_type=prospect.profile_type,
        )
        if show_ctx and "No major trade shows" not in show_ctx:
            parts.append(f"\nIndustry trade shows:\n{show_ctx}")
            icebreaker = get_show_icebreaker(
                country=prospect.country,
                industry=prospect.industry,
                profile_type=prospect.profile_type,
            )
            if icebreaker:
                parts.append(f"\nTrade-show icebreaker angle: {icebreaker}")
    except Exception:
        pass

    # ── 假期提醒 ──
    try:
        holiday_note = get_holiday_context_for_country(
            (prospect.country or ""), date.today()
        )
        if holiday_note and "No major holidays" not in holiday_note:
            parts.append(f"\nHoliday notice: {holiday_note}")
    except Exception:
        pass

    return "\n".join(parts)


def _inject_case_studies(prospect, parts: list):
    """Find relevant case studies AND micro-tactics from knowledge base and append to context for AI."""
    try:
        from models import KnowledgeBase

        db2 = SessionLocal()
        entries = db2.query(KnowledgeBase).filter(
            KnowledgeBase.category.in_(["case_study", "tactic"]),
            KnowledgeBase.is_active == 1,
        ).all()
        db2.close()

        if not entries:
            return

        profile = (prospect.profile_type or "").strip()
        industry = (prospect.industry or "").strip()
        stage = (prospect.stage or "").strip()

        cases = []
        tactics = []
        for e in entries:
            tags = json.loads(e.tags) if e.tags else []
            tag_match = profile in tags or industry in tags or stage in tags
            title_match = (
                (profile and profile.lower() in (e.title or "").lower()) or
                (industry and industry.lower() in (e.title or "").lower())
            )
            if e.category == "case_study":
                if tag_match or title_match:
                    cases.append(e)
                elif len(cases) < 1:
                    cases.append(e)
            elif e.category == "tactic":
                if tag_match or title_match:
                    tactics.append(e)
                elif len(tactics) < 2:
                    tactics.append(e)

        if cases:
            parts.append(f"\n=== Similar-client success cases ({len(cases)}) ===")
            for c in cases[:2]:
                parts.append(f"\nCase: {c.title}\n{c.content[:400]}")
                if c.tags:
                    parts.append(f"Tags: {c.tags}")

        if tactics:
            parts.append(f"\n=== Proven tactics ({len(tactics)}) ===")
            for t in tactics[:4]:
                parts.append(f"\nTactic: {t.title}\n{t.content[:300]}")
    except Exception:
        pass


async def _ai_draft(context, reason, prospect, interactions=None, consecutive_no_reply=0, channel="email"):
    """AI drafts a follow-up email with full chain context.

    context: built from _build_context (customer profile, history summaries, intel)
    interactions: full Interaction list for cold-followup chain awareness
    consecutive_no_reply: how many outbounds since last inbound reply
    channel: current channel being drafted for
    """
    # ── Build cold-followup chain context for depth ──
    chain_context = ""
    if interactions and consecutive_no_reply >= 1:
        chain_parts = []
        chain_parts.append(f"\n=== Full follow-up chain ({len(interactions)} interactions, {consecutive_no_reply} no-reply) ===")
        # Show full outbound content, inbound truncated to key signals
        for ix in interactions[-10:]:
            dtag = "[Client]" if ix.direction == "inbound" else "[Us]"
            ts = str(ix.interacted_at)[:16] if ix.interacted_at else "?"
            ch = ix.channel or "?"
            if ix.direction == "outbound":
                full_text = (ix.content or ix.subject or "")[:400]
                chain_parts.append(f"  {dtag} {ts} {ch}: {full_text}")
            else:
                text = (ix.content or ix.subject or "")[:200]
                intent = ix.reply_intent or ""
                signals = ix.key_signals or ""
                extra = f" [intent:{intent}]" if intent else ""
                if signals:
                    extra += f" [signals:{signals[:100]}]"
                chain_parts.append(f"  {dtag} {ts} {ch}: {text}{extra}")
        if channel != "email":
            chain_parts.append(f"\nNote: this is a {channel} message (not email) — do not add a signature.")
        chain_context = "\n".join(chain_parts)

    prompt = (
        "You are the export sales AI at {{COMPANY}} (export manufacturer).\n\n"
        + "=== PRODUCT SPECS AND WRITING RULES ===\n"
        + _get_writing_rules_inline() + "\n\n"
        + f"=== CLIENT BACKGROUND ===\n{context}\n\n"
        + f"Follow-up reason: {reason} | Contact: {prospect.contact or prospect.decision_maker or 'N/A'}"
        + chain_context + "\n\n"
        + get_voice_rules() + "\n\n"
        + "EMAIL SIGNATURE TO USE:\n"
        + get_signature_for_profile(prospect.profile_type) + "\n\n"
        + "=== WRITING REQUIREMENTS ===\n"
        + "1. Do not repeat the content or angle of the last email — if last time was about lead time, this time use quality or a new spec.\n"
        + "2. Give one new information point per follow-up: industry trend, technical detail, trade-show news, or a case.\n"
        + "3. If you have followed up more than 3 times with no reply, keep the tone lighter and shorter — no pressure.\n"
        + "4. Cold follow-up emails must stay under 120 words.\n"
        + "Write a professional follow-up email in English. Return JSON: {\"subject\":\"...\",\"body\":\"...\",\"suggested_date\":\"YYYY-MM-DD\"}"
    )
    try:
        raw = await call_simple(prompt, model_override="deepseek", temperature=0.7, max_tokens=2048)
        clean = sanitize_tolerance(raw.strip())
        clean = sanitize_attachment_language(clean)
        m = re.search(r"\{[\s\S]*\}", clean)
        if m: clean = m.group(0)
        data = json.loads(clean)
        return data if isinstance(data, dict) and "body" in data else None
    except Exception as e:
        logger.warning("AI draft failed: %s", e)
        return None


def _get_next_business_time(prospect, is_cold: bool = True):
    tz_str = (prospect.timezone or "").strip()
    tz = None
    if tz_str:
        try:
            tz = ZoneInfo(tz_str)
        except Exception:
            # Try interpreting as UTC+/-N offset format
            import re as _tzre
            m = _tzre.match(r'^UTC([+-]\d{1,2})$', tz_str.upper())
            if m:
                try:
                    offset_h = int(m.group(1))
                    from datetime import timezone as _dt_tz, timedelta as _dt_td
                    tz = _dt_tz(_dt_td(hours=offset_h))
                except Exception:
                    tz = ZoneInfo("UTC")
            else:
                tz = ZoneInfo("UTC")
    if not tz:
        tz = ZoneInfo("UTC")
    try:
        now = datetime.now(tz)
    except Exception:
        tz = ZoneInfo("UTC")
        now = datetime.now(tz)

    wd = now.weekday()
    country = (getattr(prospect, "country", "") or "").strip().upper()

    def _is_bad_send_day(d, cold: bool) -> tuple:
        if d.weekday() >= 5:
            return True, "weekend"
        # d may be datetime or date — convert to date for calendar comparison
        d_date = d.date() if hasattr(d, 'date') else d
        skip, reason = should_skip_cold_outreach(d_date, country)
        if skip and cold:
            return True, reason
        if skip and not cold:
            from services.holiday_calendar import is_fixed_holiday
            if is_fixed_holiday(d_date):
                return True, reason
        return False, ""

    if is_cold:
        for offset in range(30):
            candidate = now + timedelta(days=offset)
            cwd = candidate.weekday()
            if cwd not in (1, 2, 3):
                continue
            skip, reason = _is_bad_send_day(candidate, cold=True)
            if skip:
                logger.debug("Cold skip %s: %s", candidate.date(), reason)
                continue
            import random as _rnd
            target = candidate.replace(hour=_rnd.randint(9, 11), minute=_rnd.randint(0, 59), second=0, microsecond=0)
            # Fix: candidate already has tz, keep it — don't lose tzinfo
            if hasattr(candidate, 'tzinfo') and candidate.tzinfo is not None:
                try:
                    target = datetime.combine(candidate.date(), target.time().replace(tzinfo=None), tzinfo=candidate.tzinfo)
                except Exception:
                    pass
            break
        else:
            import random as _rnd2
            target = now + timedelta(days=30)
            while target.weekday() >= 5:
                target += timedelta(days=1)
            target = target.replace(hour=_rnd2.randint(9, 11), minute=_rnd2.randint(0, 59), second=0, microsecond=0)
            # Fix: now already has tz, keep it
            if hasattr(now, 'tzinfo') and now.tzinfo is not None:
                try:
                    target = datetime.combine(target.date(), target.time().replace(tzinfo=None), tzinfo=now.tzinfo)
                except Exception:
                    pass
    else:
        for offset in range(14):
            candidate = now + timedelta(days=offset) if offset > 0 else now
            cwd = candidate.weekday()
            if cwd >= 5:
                continue
            from services.holiday_calendar import is_fixed_holiday
            if is_fixed_holiday(candidate):
                logger.debug("Warm skip %s: fixed holiday", candidate.date())
                continue
            import random as _rnd_warm
            if offset == 0 and now.hour < 9:
                target = candidate.replace(hour=_rnd_warm.randint(9, 11), minute=_rnd_warm.randint(0, 59), second=0, microsecond=0)
            elif offset == 0 and now.hour >= 18:
                continue
            elif offset == 0:
                target = candidate.replace(hour=now.hour + 1, minute=_rnd_warm.randint(0, 59), second=0, microsecond=0)
            else:
                target = candidate.replace(hour=_rnd_warm.randint(9, 11), minute=_rnd_warm.randint(0, 59), second=0, microsecond=0)
            # Fix: candidate already has tz, keep it
            if hasattr(candidate, 'tzinfo') and candidate.tzinfo is not None:
                try:
                    target = datetime.combine(candidate.date(), target.time().replace(tzinfo=None), tzinfo=candidate.tzinfo)
                except Exception:
                    pass
            break
        else:
            import random as _rnd_warm2
            target = (now + timedelta(days=14)).replace(hour=_rnd_warm2.randint(9, 11), minute=_rnd_warm2.randint(0, 59), second=0, microsecond=0)
            # Fix: now already has tz, keep it
            if hasattr(now, 'tzinfo') and now.tzinfo is not None:
                try:
                    target = datetime.combine(target.date(), target.time().replace(tzinfo=None), tzinfo=now.tzinfo)
                except Exception:
                    pass

    return target.astimezone(ZoneInfo("UTC")).replace(tzinfo=None)


async def run_cooling_value_share(max_per_run=30):
    """Monthly value-sharing for cooling customers."""
    logger.info("=== Cooling value-share engine starting ===")
    db = SessionLocal()
    try:
        from datetime import timedelta
        from sqlalchemy import func as _f3

        today = date.today()
        today_str = today.isoformat()

        manual_cooling = db.query(Prospect).filter(
            Prospect.is_deleted == 0,
            Prospect.sales_stage == "cooling",
        ).all()

        sub_all = db.query(Prospect).filter(
            Prospect.is_deleted == 0,
            ~Prospect.sales_stage.in_(["won", "lost", "cooling"]),
        ).all()

        if sub_all:
            sub_ids = [p.id for p in sub_all]
            last_int_map = dict(
                db.query(Interaction.prospect_id, _f3.max(Interaction.interacted_at))
                .filter(Interaction.prospect_id.in_(sub_ids))
                .group_by(Interaction.prospect_id)
                .all()
            )
            int_counts = dict(
                db.query(Interaction.prospect_id, _f3.count(Interaction.id))
                .filter(Interaction.prospect_id.in_(sub_ids))
                .group_by(Interaction.prospect_id)
                .all()
            )
        else:
            last_int_map = {}
            int_counts = {}

        auto_cooling = []
        for p in sub_all:
            dt = last_int_map.get(p.id)
            if not dt: continue
            ic = int_counts.get(p.id, 0)
            if ic == 0: continue
            try:
                if dt.tzinfo is not None:
                    days_since = (datetime.now(dt.tzinfo) - dt).days
                else:
                    days_since = (datetime.now() - dt).days
                if days_since > 30:
                    auto_cooling.append(p)
            except Exception:
                continue

        all_cooling = list({p.id: p for p in manual_cooling + auto_cooling}.values())
        logger.info("Cooling value-share: %d manual + %d auto = %d total",
                     len(manual_cooling), len(auto_cooling), len(all_cooling))

        drafted = 0
        for p in all_cooling[:max_per_run]:
            if not (p.email or p.dm_email):
                continue

            existing = db.query(EmailQueue).filter(
                EmailQueue.prospect_id == p.id,
                EmailQueue.status.in_(["draft", "pending"]),
            ).first()
            if existing:
                continue

            interactions = db.query(Interaction).filter(
                Interaction.prospect_id == p.id
            ).order_by(Interaction.interacted_at.asc()).all()
            intel = db.query(Intelligence).filter(Intelligence.prospect_id == p.id).first()

            ctx = _build_context(p, interactions, intel)
            draft = await _ai_value_share(ctx, p)

            if draft and draft.get("body"):
                subject = draft.get("subject", f"Thought you might find this interesting")
                body = draft["body"]

                from datetime import datetime as dt_module, timedelta as td_module
                now_local = dt_module.now()
                days_until_tuesday = (1 - now_local.weekday()) % 7
                if days_until_tuesday == 0 and now_local.hour >= 10:
                    days_until_tuesday = 7
                next_tuesday = now_local + td_module(days=days_until_tuesday)
                next_dt = next_tuesday.replace(hour=10, minute=15, second=0, microsecond=0)

                eq = EmailQueue(
                    prospect_id=p.id,
                    to_email=p.email or p.dm_email or "",
                    subject=f"[Value Share] {subject[:150]}",
                    body=body,
                    status="draft",
                    scheduled_at=next_dt,
                    daily_send_date=today_str,
                )
                db.add(eq)
                drafted += 1
                logger.info("✅ Value-share drafted for cooling #%d %s", p.id, p.company)

        db.commit()
        logger.info("=== Cooling value-share done: %d drafted ===", drafted)

    except Exception as exc:
        logger.exception("Cooling value-share failed")
        db.rollback()
    finally:
        db.close()


async def _ai_value_share(context, prospect):
    """AI generates a soft-touch value-sharing email."""
    prompt = (
        'You are the export sales AI at {{COMPANY}} (export manufacturer).\n\n'
        'Task: write a value-sharing email for a long-silent client.\n\n'
        + '=== PRODUCT SPECS AND WRITING RULES ===\n'
        + _get_writing_rules_inline() + '\n\n'
        + '=== CLIENT BACKGROUND ===\n'
        + context + '\n\n'
        '=== EMAIL REQUIREMENTS ===\n'
        '1. This is NOT a sales email — do not push products or make commercial offers.\n'
        '2. Share one short, useful industry insight: an industry trend, a relevant trade-show update, '
        'a new technology, or a new application in their sector.\n'
        '3. Keep the tone light and natural, like a friend sharing an article. Do not say "our company" or "our product".\n'
        '4. Keep it short: 3-4 sentences, under 100 words.\n'
        '5. The subject line should sound human and natural (not clickbait).\n'
        '6. Write in English with a natural international-business tone (clear and professional, not over-polished).\n'
        '7. No call to action — no "Let me know if you are interested" or '
        '"Looking forward to hearing from you" type lines.\n'
        '8. Use this signature:\n'
        + get_signature_for_profile(prospect.profile_type) + '\n\n'
        'Return JSON: {"subject":"...","body":"..."}'
    )
    try:
        raw = await call_simple(prompt, model_override="deepseek", temperature=0.8, max_tokens=1536)
        clean = sanitize_tolerance(raw.strip())
        clean = sanitize_attachment_language(clean)
        m = re.search(r"\{[\s\S]*\}", clean)
        if m: clean = m.group(0)
        data = json.loads(clean)
        return data if isinstance(data, dict) and "body" in data else None
    except Exception as e:
        logger.warning("AI value-share draft failed: %s", e)
        return None


async def run_followup_engine(max_per_run=999):
    """Scan ALL active prospects. Every one gets a next_follow_date — zero escape.

    Four tiers:
      Tier 1 — Draft today: 3-30d no-reply follow-up, first-touch, reply response, periodic check-in
      Tier 2 — In pipeline: already has draft/pending email, or no email address → skip wiring
      Tier 3 — Dormant: 5+ consecutive no-reply → auto-cooling + mark re-review date
      Tier 4 — Missing schedule: has interactions but no nfd → auto-set next business day

    Guarantee: after this runs, every active (non-won/lost/cooling) prospect has a next_follow_date.
    """
    logger.info("=== Follow-up engine (v3 — full coverage) starting ===")
    db = SessionLocal()
    try:
        today = date.today()
        today_str = today.isoformat()

        stats = db.query(DailyEmailStats).filter(DailyEmailStats.date == today_str).first()
        if not stats:
            stats = DailyEmailStats(date=today_str, sent_count=0, limit_count=DAILY_EMAIL_LIMIT)
            db.add(stats)
            db.flush()

        remaining = DAILY_EMAIL_LIMIT - stats.sent_count
        logger.info("Follow-up engine: %d/%d sent today, %d remaining — target: draft %d emails",
                    stats.sent_count, DAILY_EMAIL_LIMIT, remaining, min(remaining, 30))

        active = db.query(Prospect).filter(
            Prospect.is_deleted == 0,
            Prospect.profile_type != "EXCLUDE",
            ~Prospect.sales_stage.in_(["won", "lost"]),
        ).all()

        logger.info("Follow-up engine: %d active prospects (excl. won/lost/EXCLUDE)", len(active))

        # ── Pre-load all interactions for all active prospects ──
        active_ids = [p.id for p in active]
        all_interactions = {}
        all_last_outbound = {}
        all_last_inbound = {}
        all_outbound_count_since_inbound = {}
        if active_ids:
            from sqlalchemy import func as _f_preload
            rows = db.query(Interaction).filter(
                Interaction.prospect_id.in_(active_ids)
            ).order_by(Interaction.interacted_at.asc()).all()
            for pid in active_ids:
                all_interactions[pid] = []
            for ix in rows:
                all_interactions[ix.prospect_id].append(ix)
            for pid in active_ids:
                ixs = all_interactions[pid]
                all_last_outbound[pid] = _last_outbound_date(ixs)
                all_last_inbound[pid] = _last_inbound_date(ixs)
                all_outbound_count_since_inbound[pid] = _count_outbound_since_last_inbound(ixs)

        # ── Pre-load existing draft/pending emails ──
        existing_drafts = set()
        if active_ids:
            from sqlalchemy import func as _f_eq
            rows = db.query(EmailQueue.prospect_id).filter(
                EmailQueue.prospect_id.in_(active_ids),
                EmailQueue.status.in_(["draft", "pending"]),
            ).distinct().all()
            existing_drafts = set(r[0] for r in rows)

        queued = 0
        dormant_count = 0
        patched_count = 0
        skipped_fresh = 0
        skipped_no_email = 0
        skipped_pipeline = 0
        skipped_rest_days = 0

        for p in active:
            pid = p.id
            interactions = all_interactions.get(pid, [])
            last_out = all_last_outbound.get(pid)
            last_in = all_last_inbound.get(pid)
            out_count = all_outbound_count_since_inbound.get(pid, 0)

            # ── Tier 2 guard: skip if already in pipeline, but still ensure nfd exists ──

            if pid in existing_drafts:
                # Already has draft/pending — no need to draft again, but ensure nfd exists
                skipped_pipeline += 1
                if not (p.next_follow_date or "").strip():
                    nfd = _next_available_slot(db, today + timedelta(days=1))
                    p.next_follow_date = nfd.isoformat()
                p.last_edited_at = datetime.utcnow()
                continue

            # ── Fresh prospect (never touched) → stays in the waiting pool ──
            #     These are picked 3/day by "今日新开发"; assigning nfd today would
            #     push them into "今日待跟进" and drop them from the fresh pool.
            if not interactions:
                skipped_fresh += 1
                continue

            # ── No email address — assign nfd but skip drafting ──
            if not (p.email or p.dm_email):
                if not (p.next_follow_date or "").strip():
                    p.next_follow_date = _next_available_slot(db, today).isoformat()
                p.last_edited_at = datetime.utcnow()
                skipped_no_email += 1
                continue

            # ── Bounced email — assign nfd for visibility, but don't generate email ──
            if (p.email_status or "") == "bounced":
                if not (p.next_follow_date or "").strip():
                    p.next_follow_date = _next_available_slot(db, today).isoformat()
                p.last_edited_at = datetime.utcnow()
                skipped_pipeline += 1
                continue

            # ── Cooling — still in the engine for nfd, but don't auto-draft ──
            if (p.sales_stage or "") == "cooling":
                if not (p.next_follow_date or "").strip():
                    p.next_follow_date = _next_available_slot(db, today).isoformat()
                p.last_edited_at = datetime.utcnow()
                continue

            # ── Tier 3: 5+ consecutive no-reply → dormant, needs human re-review ──
            if last_out and not last_in and out_count >= MAX_FOLLOW_UPS:
                # AI-assigned re-review date based on history patterns
                re_review_days = _compute_dormant_review_days(p, out_count, last_out, today)
                base_nfd = today + timedelta(days=re_review_days)
                nfd = _next_available_slot(db, base_nfd)
                p.sales_stage = "cooling"
                p.next_follow_date = nfd.isoformat()
                p.reminder_note = f"[Auto] {out_count} follow-ups with no reply — auto-cooled on {today_str} · re-review in {re_review_days} days"
                p.next_follow_reason = f"{out_count} follow-ups with no reply — re-review in {re_review_days} days"
                p.last_edited_at = datetime.utcnow()
                dormant_count += 1
                logger.info("🧊 Dormant: #%d %s — %d consecutive no-reply → cooling, re-review in %dd (%s)",
                            pid, p.company, out_count, re_review_days, p.next_follow_date)
                continue

            # ── Tier 1: Determine which date to assign for next_follow_date ──
            #     NO auto-drafting! 销售从今日计划人工审核。
            #     Only assign nfd — 起草由销售从计划页手动触发。
            reason = None

            if last_out and not last_in:
                days_since_out = _days_since(last_out)
                if days_since_out < NO_REPLY_DAYS:
                    skipped_rest_days += 1
                    continue  # Still in rest period
                reason = f"Follow-up #{out_count+1} (no reply in {days_since_out} days)"
            elif last_in and last_out and last_in > last_out:
                days_since_in = _days_since(last_in)
                if 0 < days_since_in <= 5:
                    reason = f"Client replied on {last_in.strftime('%m/%d')} — draft a response"
                else:
                    reason = f"Periodic follow-up ({days_since_in} days since last reply)"
            elif not last_out:
                reason = "First outreach email"
            else:
                reason = "Regular follow-up"

            # ── Assign nfd only — NO auto-draft ──
            if not (p.next_follow_date or "").strip():
                p.next_follow_date = _next_available_slot(db, today).isoformat()
            if reason:
                p.next_follow_reason = reason
            p.last_edited_at = datetime.utcnow()
            queued += 1
            logger.info("📅 Scheduled #%d %s → nfd=%s | reason=%s", pid, p.company, p.next_follow_date, reason)

        # ── Tier 4: Auto-patch missing next_follow_date for ALL remaining active prospects ──
        for p in active:
            if p.id in existing_drafts:
                continue  # already handled in Tier 2
            if not all_interactions.get(p.id):
                continue  # fresh prospect stays in waiting pool (picked by 今日新开发)
            if not (p.next_follow_date or "").strip():
                # Set to next available day (anti-bunching)
                patch_dt = _next_available_slot(db, today + timedelta(days=1))
                p.next_follow_date = patch_dt.isoformat()
                p.last_edited_at = datetime.utcnow()
                patched_count += 1
                logger.info("📅 Patched missing nfd for #%d %s → %s", p.id, p.company, p.next_follow_date)

        # ── Ensure every scheduled prospect shows a readable reason on the board ──
        for p in active:
            if (p.next_follow_date or "").strip() and not (p.next_follow_reason or "").strip():
                p.next_follow_reason = _default_review_reason(p)

        db.commit()
        logger.info("=== Follow-up engine v3 done ===")
        logger.info("  Tier 1 nfd assigned: %d", queued)
        logger.info("  Tier 2 skipped: pipeline=%d no-email=%d", skipped_pipeline, skipped_no_email)
        logger.info("  Tier 3 dormant (→cooling): %d", dormant_count)
        logger.info("  Tier 4 patched missing nfd: %d", patched_count)
        logger.info("  Fresh (kept in waiting pool): %d", skipped_fresh)
        logger.info("  Other skipped: rest_days=%d", skipped_rest_days)

    except Exception as exc:
        logger.exception("Follow-up engine failed")
        db.rollback()
    finally:
        db.close()
