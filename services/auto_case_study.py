"""
Continuous Pattern Miner — 持续从互动中挖掘可复用战术，不再只等成交。

每个周期（跟随 auto_runner 30min 节奏）扫描近期互动，提取"微模式"：
  1. 回复冷邮的主题/开头句式 → cold_email_pattern
  2. LinkedIn DM 触发 Zoom 的语言 → linkedin_zoom_trigger
  3. WhatsApp 重激活的成功时机/语气 → whatsapp_reengage
  4. 付款摩擦化解的话术 → payment_deescalation
  5. 渠道切换信号 → channel_switch_signal
  6. 成交案例 → full_case_study（只在 deal won 时生成）

所有模式写入 knowledge_base，在跟进起草和评分时自动注入上下文。
"""
import json
import logging
from datetime import datetime, timedelta
from pathlib import Path
import sys

from config import APP_DIR
PROJECT_DIR = APP_DIR
sys.path.insert(0, str(PROJECT_DIR))

from database import SessionLocal
from models import Prospect, Interaction, Deal, KnowledgeBase
from services.ai_router import call_simple_sync as call_simple

logger = logging.getLogger("pattern_miner")
logger.setLevel(logging.INFO)
if not logger.handlers:
    h = logging.StreamHandler()
    h.setFormatter(logging.Formatter("%(asctime)s [miner] %(message)s"))
    logger.addHandler(h)


# ══════════════════════════════════════════════════════════════════
#  Phase 1: Signal Detection — 找"正向信号"互动
# ══════════════════════════════════════════════════════════════════

def _find_recent_signals(days=7):
    """Scan recent inbound interactions for positive signals.

    Returns list of (prospect, signal_interaction, paired_outbound_interaction).
    Each entry represents: our message → their positive response.
    """
    db = SessionLocal()
    try:
        cutoff = datetime.utcnow() - timedelta(days=days)

        # Get all recent inbound interactions
        recent_in = (
            db.query(Interaction)
            .filter(
                Interaction.interacted_at >= cutoff,
                Interaction.direction == "inbound",
            )
            .order_by(Interaction.interacted_at.desc())
            .all()
        )

        signals = []
        seen_prospects = set()

        for ix in recent_in:
            pid = ix.prospect_id
            if pid in seen_prospects:
                continue

            prospect = db.query(Prospect).filter(Prospect.id == pid, Prospect.is_deleted == 0).first()
            if not prospect:
                continue

            # Find the most recent outbound BEFORE this inbound (our message that triggered it)
            our_msg = (
                db.query(Interaction)
                .filter(
                    Interaction.prospect_id == pid,
                    Interaction.direction == "outbound",
                    Interaction.interacted_at < ix.interacted_at,
                )
                .order_by(Interaction.interacted_at.desc())
                .first()
            )

            if not our_msg:
                continue

            # Classify the signal
            signal_type = _classify_signal(ix, our_msg, prospect)
            if signal_type:
                seen_prospects.add(pid)
                signals.append({
                    "prospect": {
                        "company": prospect.company_name or "",
                        "profile_type": prospect.profile_type or "",
                        "industry": prospect.industry or "",
                        "country": prospect.country or "",
                        "stage": prospect.stage or "",
                    },
                    "signal_type": signal_type,
                    "our_action": {
                        "channel": our_msg.channel or "unknown",
                        "date": str(our_msg.interacted_at)[:16] if our_msg.interacted_at else "?",
                        "content": (our_msg.subject or "")[:200] + "\n" + (our_msg.content or "")[:500],
                    },
                    "their_response": {
                        "channel": ix.channel or "unknown",
                        "date": str(ix.interacted_at)[:16] if ix.interacted_at else "?",
                        "content": (ix.subject or "")[:200] + "\n" + (ix.content or "")[:500],
                    },
                    "time_gap_hours": round(
                        (ix.interacted_at - our_msg.interacted_at).total_seconds() / 3600, 1
                    ) if (ix.interacted_at and our_msg.interacted_at) else 0,
                })

        return signals
    finally:
        db.close()


def _classify_signal(inbound, outbound, prospect) -> str | None:
    """Classify what kind of positive signal this inbound represents."""
    content = ((inbound.content or "") + " " + (inbound.subject or "")).lower()
    our_content = ((outbound.content or "") + " " + (outbound.subject or "")).lower()
    channel = (inbound.channel or "").lower()

    # 1. Zoom / video call request
    if any(w in content for w in ["zoom", "video call", "video chat", "teams call", "meet.google"]):
        return "zoom_trigger"

    # 2. Payment / invoice confirmation
    if any(w in content for w in ["payment", "paid", "invoice", "wire", "transfer", "swift"]):
        if any(w in content for w in ["sent", "confirmed", "attached", "on the way", "cleared"]):
            return "payment_progress"

    # 3. Sample request / shipping address given
    if any(w in content for w in ["sample", "shipping address", "ship to", "test"]):
        return "sample_interest"

    # 4. Cold email reply — ANY reply to an initial cold reach
    if (inbound.interacted_at and outbound.interacted_at):
        # If first interaction, or very early in sequence
        prev_count = _count_prior_interactions(inbound.prospect_id, inbound.interacted_at)
        if prev_count <= 2 and channel == "email":
            return "cold_email_reply"

    # 5. LinkedIn DM reply to cold reach
    if prev_count <= 2 and channel in ("linkedin", "whatsapp"):
        return "cold_social_reply"

    # 6. Re-engagement after silence (>14 days gap)
    if (inbound.interacted_at and outbound.interacted_at):
        gap = (outbound.interacted_at - inbound.interacted_at).total_seconds()
        prev_outbound = _find_prev_outbound(inbound.prospect_id, outbound.interacted_at)
        if prev_outbound and inbound.interacted_at:
            silence = (outbound.interacted_at - prev_outbound.interacted_at).total_seconds()
            if silence > 14 * 86400:
                return "reengage_after_silence"

    # 7. Objection resolution — they were skeptical, now positive
    if any(w in our_content for w in ["manufacturer", "factory", "direct", "middleman", "reseller"]):
        if any(w in content for w in ["great", "thank", "appreciate", "good", "please"]):
            return "trust_objection_resolved"

    return None


def _count_prior_interactions(prospect_id: int, before_time) -> int:
    db = SessionLocal()
    try:
        return db.query(Interaction).filter(
            Interaction.prospect_id == prospect_id,
            Interaction.interacted_at < before_time,
        ).count()
    finally:
        db.close()


def _find_prev_outbound(prospect_id: int, before_time):
    db = SessionLocal()
    try:
        return db.query(Interaction).filter(
            Interaction.prospect_id == prospect_id,
            Interaction.direction == "outbound",
            Interaction.interacted_at < before_time,
        ).order_by(Interaction.interacted_at.desc()).first()
    finally:
        db.close()


# ══════════════════════════════════════════════════════════════════
#  Phase 2: Pattern Extraction — AI 分析"为什么这个动作有效"
# ══════════════════════════════════════════════════════════════════

PATTERN_EXTRACTION_PROMPT = """You are the sales strategy AI for {{COMPANY}}. Below is a real interaction record:

[OUR MESSAGE] (what we sent to the customer)
Channel: {channel}
Content: {our_content}

[CUSTOMER REPLY]
Content: {their_content}
Reply gap: {gap_hours} hours

Customer profile:
Company: {company}
Profile type: {profile_type}
Industry: {industry}
Country: {country}
Stage: {stage}

Analyze: **which specific element of our message triggered the customer's positive response?**

Directly identify from the original text:
1. Which sentence or phrase most likely triggered the reply? (quote the original)
2. What tactic does it belong to? (spec-driven / trust building / action guidance / light follow-up / other)
3. Which customer profiles does this strategy fit?
4. [CORE] Distill it into a reusable template of up to 150 words in the form: "If you face [scenario], try writing [message template]".
5. Give this pattern 3-5 tags.

Return strict JSON (no markdown code blocks):
{{"trigger_element": "quoted key sentence from the original", "tactic_name": "tactic name", "applicable_profiles": ["Profile_X"], "template": "reusable message template with a short English explanation and example", "tags": ["tag1", "tag2", "tag3"]}}"""


def _extract_pattern(signal: dict) -> dict | None:
    """Feed one signal to AI, get back a reusable pattern."""
    p = signal["prospect"]
    prompt = PATTERN_EXTRACTION_PROMPT.format(
        channel=signal["our_action"]["channel"],
        our_content=signal["our_action"]["content"][:800],
        their_content=signal["their_response"]["content"][:600],
        gap_hours=signal["time_gap_hours"],
        company=p["company"],
        profile_type=p["profile_type"],
        industry=p["industry"],
        country=p["country"],
        stage=p["stage"],
    )

    try:
        raw = call_simple(prompt, temperature=0.5, max_tokens=1024)
        clean = raw.strip()
        # Extract JSON
        import re
        m = re.search(r"\{[\s\S]*\}", clean)
        if m:
            return json.loads(m.group(0))
        return None
    except Exception as e:
        logger.warning(f"Pattern extraction failed: {e}")
        return None


# ══════════════════════════════════════════════════════════════════
#  Phase 3: Dedup & Save — 避免重复模式
# ══════════════════════════════════════════════════════════════════

def _save_pattern(signal: dict, pattern: dict):
    """Save extracted pattern to knowledge_base if not duplicate."""
    db = SessionLocal()
    try:
        tactic_name = pattern.get("tactic_name", "unknown")
        company = signal["prospect"]["company"][:30]

        # Check if a similar pattern already exists
        exists = db.query(KnowledgeBase).filter(
            KnowledgeBase.category == "tactic",
            KnowledgeBase.title.contains(tactic_name[:20]),
            KnowledgeBase.is_active == 1,
        ).first()

        if exists:
            # Update: add this company as evidence
            logger.info(f"Pattern '{tactic_name}' already exists, adding evidence from {company}")
            return

        # Build structured content
        content = f"""## Tactic: {pattern.get('tactic_name', '')}

**Trigger**: {pattern.get('trigger_element', '')}

**Applies to profiles**: {', '.join(pattern.get('applicable_profiles', []))}

**Source**: {company} ({signal['prospect']['country']}, {signal['prospect']['industry']})

**Our message (excerpt)**:
{signal['our_action']['content'][:400]}

**Client response (excerpt)**:
{signal['their_response']['content'][:300]}

**Reply gap**: {signal['time_gap_hours']} hours

**Reusable template**:
{pattern.get('template', '')}"""

        tags = pattern.get("tags", []) + [
            signal["prospect"]["profile_type"],
            signal["prospect"]["country"],
            signal["signal_type"],
            "auto-mined",
        ]

        entry = KnowledgeBase(
            category="tactic",
            title=f"Tactic: {tactic_name} (from {company})",
            content=content,
            tags=json.dumps(tags, ensure_ascii=False),
            is_active=1,
        )
        db.add(entry)
        db.commit()
        logger.info(f"✓ New tactic saved: {tactic_name} (from {company})")
    except Exception as e:
        db.rollback()
        logger.error(f"Failed to save pattern: {e}")
    finally:
        db.close()


# ══════════════════════════════════════════════════════════════════
#  Phase 4: Deal Won → 完整案例（保留）
# ══════════════════════════════════════════════════════════════════

def _find_newly_won_deals() -> list:
    db = SessionLocal()
    try:
        deals = db.query(Deal).filter(Deal.stage == "won").order_by(Deal.updated_at.desc()).limit(5).all()
        new = []
        for d in deals:
            prospect = db.query(Prospect).filter(Prospect.id == d.prospect_id).first()
            if not prospect:
                continue
            company = (prospect.company_name or "").strip()[:20]
            exists = db.query(KnowledgeBase).filter(
                KnowledgeBase.category == "case_study",
                KnowledgeBase.title.contains(company),
            ).first()
            if not exists:
                new.append((d, prospect))
        return new
    finally:
        db.close()


def _generate_full_case(prospect_info: dict, timeline: list, deal_summary: list) -> str | None:
    if not timeline or len(timeline) < 3:
        return None
    context_parts = [
        f"### Client info\n{json.dumps(prospect_info, ensure_ascii=False, indent=2)}",
        f"\n### Deal info\n{json.dumps(deal_summary, ensure_ascii=False, indent=2)}",
        f"\n### Full interaction timeline ({len(timeline)})",
    ]
    for t in timeline[-200:]:
        d = "[Client → us]" if t["direction"] == "inbound" else "[Us → client]"
        context_parts.append(f"{t['date']} {d} {t['channel']}: {t['content'][:300]}")

    prompt = (
        "You are the sales strategy analyst at {{COMPANY}}. Analyze this won client's full timeline and write a learning case.\n"
        "Structure: customer profile → conversion path → key success factors → reusable strategy → tags.\n"
        "Write in English.\n\n" + "\n".join(context_parts)
    )
    try:
        raw = call_simple(prompt, 0.7, 4096)
        return raw.strip() if raw and len(raw) > 200 else None
    except Exception as e:
        logger.warning(f"Full case generation failed: {e}")
        return None


def _save_full_case(prospect_info: dict, content: str):
    db = SessionLocal()
    try:
        company = prospect_info.get("company", "Unknown")
        exists = db.query(KnowledgeBase).filter(
            KnowledgeBase.title.contains(company[:20]),
            KnowledgeBase.category == "case_study",
        ).first()
        if exists:
            return
        entry = KnowledgeBase(
            category="case_study",
            title=f"{company} — Won-case analysis (auto-generated {datetime.now().strftime('%Y-%m-%d')})",
            content=content,
            tags=json.dumps([prospect_info.get("profile_type", ""), prospect_info.get("country", ""), "won", "auto-generated"], ensure_ascii=False),
            is_active=1,
        )
        db.add(entry)
        db.commit()
        logger.info(f"✓ Full case study saved: {company}")
    except Exception as e:
        db.rollback()
        logger.error(f"Failed to save full case: {e}")
    finally:
        db.close()


def _build_prospect_info(prospect) -> dict:
    return {
        "company": prospect.company_name or "",
        "contact": prospect.contact or prospect.decision_maker or "",
        "profile_type": prospect.profile_type or "",
        "industry": prospect.industry or "",
        "country": prospect.country or "",
    }


def _build_timeline(prospect_id: int) -> list:
    db = SessionLocal()
    try:
        interactions = db.query(Interaction).filter(
            Interaction.prospect_id == prospect_id,
        ).order_by(Interaction.interacted_at.asc()).all()
        return [{
            "date": str(ix.interacted_at)[:16] if ix.interacted_at else "?",
            "direction": "inbound" if ix.direction == "inbound" else "outbound",
            "channel": ix.channel or "unknown",
            "content": (ix.content or ix.subject or "")[:500],
        } for ix in interactions]
    finally:
        db.close()


def _build_deal_summary(prospect_id: int) -> list:
    db = SessionLocal()
    try:
        deals = db.query(Deal).filter(Deal.prospect_id == prospect_id, Deal.is_deleted == 0).all()
        return [{"name": d.name or "", "stage": d.stage or "", "value": str(d.value or ""),
                 "po_number": d.po_number or ""} for d in deals]
    finally:
        db.close()


# ══════════════════════════════════════════════════════════════════
#  Main: 每周期调用
# ══════════════════════════════════════════════════════════════════

async def run_pattern_miner():
    """Main entry — called by auto_runner each cycle.

    1. Scan recent signals → extract micro-patterns
    2. Check for newly won deals → generate full case studies
    """
    logger.info("Pattern miner cycle starting")

    # ── Micro-patterns from recent signals ──
    try:
        signals = _find_recent_signals(days=7)
        logger.info(f"Found {len(signals)} positive signal(s) in last 7 days")

        extracted = 0
        for sig in signals[:10]:  # Max 10 per cycle to control AI cost
            # Skip if we've already mined this prospect's signal recently
            pattern = _extract_pattern(sig)
            if pattern:
                _save_pattern(sig, pattern)
                extracted += 1

        if extracted:
            logger.info(f"Extracted {extracted} new micro-pattern(s)")
    except Exception as e:
        logger.error(f"Micro-pattern mining error: {e}")

    # ── Full case studies from won deals ──
    try:
        new_deals = _find_newly_won_deals()
        if new_deals:
            logger.info(f"Found {len(new_deals)} won deal(s) needing case study")
            for deal, prospect in new_deals:
                info = _build_prospect_info(prospect)
                timeline = _build_timeline(prospect.id)
                deal_summary = _build_deal_summary(prospect.id)
                content = _generate_full_case(info, timeline, deal_summary)
                if content:
                    _save_full_case(info, content)
    except Exception as e:
        logger.error(f"Full case study error: {e}")

    logger.info("Pattern miner cycle complete")


if __name__ == "__main__":
    import asyncio
    asyncio.run(run_pattern_miner())
