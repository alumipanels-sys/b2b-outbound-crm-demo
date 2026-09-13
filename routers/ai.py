"""AI router — scoring, scraping, intelligence analysis, message generation, reply analysis."""

import asyncio
import json
import logging
import re
from datetime import datetime

from fastapi import APIRouter, Body, Depends, HTTPException, Request
from sqlalchemy.orm import Session


# Helper: pick first non-empty, non-None value — unlike `or`, handles 0 and "" correctly
def _pick(d, *keys):
    for k in keys:
        v = d.get(k)
        if v is not None and v != "":
            return v
    return None


############################################################

from database import get_db
from models import Prospect, Intelligence, Interaction, Sequence, KnowledgeBase
from schemas import BatchScoreRequest, GenerateMessageRequest
from services.ai_router import call_skill_1_analysis, call_skill_2_generation, call_simple, get_active_model, set_active_model, get_voice_rules, invalidate_voice_rules, get_signature_for_profile, choose_model, HUMAN_VOICE_RULES
from services.scraper_service import scrape_website, ScrapeError
from services.gemini_service import call_gemini_vision
from services.deepseek_service import _parse_json
from services.reply_signal import apply_reply_signal
from routers.sequences import _stage_label, _stage_interval
from routers.auth import get_current_user
from models import User
from services.auth_service import log_audit

logger = logging.getLogger(__name__)


def _resolve_company_main_prospect(db, company):
    """找公司主记录：优先有决策人的，其次公司公共邮箱，最后最早创建。"""
    rows = db.query(Prospect).filter(
        Prospect.company == company,
        Prospect.is_deleted == 0,
    ).order_by(Prospect.id.asc()).all()
    if not rows:
        return None
    for r in rows:
        if r.decision_maker:
            return r
    for r in rows:
        em = (r.email or "").lower()
        if "info@" in em or "einkauf@" in em or "purchase" in em:
            return r
    return rows[0]


async def _inject_signature_user(request: Request, db: Session = Depends(get_db)):
    """把当前登录用户注入签名上下文，让 AI 用“这个人的签名”而不是公司共用签名。"""
    try:
        from routers.auth import _current_user
        from services.ai_router import set_signature_user
        u = _current_user(request, db)
        set_signature_user(u)
    except Exception:
        pass


router = APIRouter(dependencies=[Depends(_inject_signature_user)])


def _normalize_profile_key(profile_type: str | None) -> str:
    p = (profile_type or "").strip().upper()
    if p.startswith("PROFILE_"):
        p = p[8:]
    return p


def _signature_text_for_profile(profile_type: str | None) -> str:
    return get_signature_for_profile(_normalize_profile_key(profile_type)).strip()


def _ensure_email_signature(body: str | None, profile_type: str | None) -> str:
    text = (body or "").strip()
    if not text:
        return text
    # AI 偶尔会在结尾自己写"Best, [Your Name] [COMPANY]"这类占位署名，
    # 追加真实签名前先清掉，避免重复。
    import re as _re
    for _ in range(3):
        lines = [l.rstrip() for l in text.split("\n")]
        while lines and not lines[-1].strip():
            lines.pop()
        if not lines:
            break
        last = lines[-1].strip()
        placeholder = _re.match(
            r'^(\[.*?\]|your name|your company|姓名|名字|公司名|署名|联系人.*)$',
            last, _re.I,
        )
        signoff = _re.match(
            r'^(best regards?,?|regards?,?|sincerely,?|best,?|thanks,?|thank you,?|顺颂|此致|祝好|谢谢)$',
            last, _re.I,
        )
        if placeholder or signoff:
            lines.pop()
            text = "\n".join(lines).strip()
            continue
        break
    signature = _signature_text_for_profile(profile_type)
    if not signature or signature in text:
        return text
    return text + "\n\n" + signature


@router.post("/chat")
async def ai_chat(payload: dict, db: Session = Depends(get_db)):
    """Simple AI chat endpoint — takes a prompt, returns a reply.
    Used by the inbox reply popup chat panel.
    Supports model_override for per-chat panel model switching.
    Injects get_voice_rules() so all AI outputs (especially emails) sound
    like a real Chinese export sales engineer, not AI-generated copy."""
    prompt = payload.get("prompt", "")
    if not prompt:
        return {"success": False, "error": "prompt is required"}

    # Determine effective model — supports per-chat-panel override
    model_override = payload.get("model_override", "")
    if model_override and model_override in ("auto", "deepseek", "openai", "gemini"):
        used_model = model_override if model_override != "auto" else choose_model("simple")
    else:
        used_model = choose_model("simple")

    # Build the full prompt with voice rules as system context
    prospect_id = payload.get("prospect_id")
    prospect_context = ""
    if prospect_id:
        try:
            p = db.query(Prospect).filter(
                Prospect.id == prospect_id, Prospect.is_deleted == 0
            ).first()
            if p:
                prospect_context = (
                    f"\n\nCLIENT BACKGROUND: {p.company or '?'} | {p.country or '?'} | "
                    f"Profile {p.profile_type or '?'} | Contact: {p.contact or p.decision_maker or 'N/A'}"
                )
                if p.profile_type:
                    prospect_context += f"\n{get_signature_for_profile(p.profile_type)}"
        except Exception:
            pass

    full_prompt = prompt

    try:
        raw = await call_simple(full_prompt, used_model if used_model in ("deepseek", "openai", "gemini") else None)
        return {"success": True, "result": raw, "model": used_model if used_model != "auto" else choose_model("simple")}
    except Exception as exc:
        logger.exception("Chat failed")
        return {"success": False, "error": str(exc)}


# ──────────────────────────────────────────────────────
#  POST /api/ai/analyze-strategy/{prospect_id}
# ──────────────────────────────────────────────────────

@router.post("/analyze-strategy/{prospect_id}")
async def analyze_strategy(prospect_id: int, payload: dict = None, db: Session = Depends(get_db)):
    """Proactive strategy analysis — AI automatically thinks about the best approach.
    Called on page load, no user input needed.
    payload.channel: 'linkedin' | 'whatsapp' | 'email' | 'phone' (required)
    Returns: analysis text + suggested next action."""
    model_override = None
    if payload and isinstance(payload, dict):
        mo = payload.get("model_override")
        if mo in ("deepseek", "openai", "gemini", "auto"):
            model_override = mo
    channel = (payload or {}).get("channel", "email").lower()
    if channel not in ("linkedin", "whatsapp", "email", "phone"):
        return {"success": False, "error": "channel must be linkedin, whatsapp, email, or phone"}

    prospect = db.query(Prospect).filter(
        Prospect.id == prospect_id, Prospect.is_deleted == 0
    ).first()
    if not prospect:
        raise HTTPException(status_code=404, detail="Prospect not found")

    intel = db.query(Intelligence).filter(Intelligence.prospect_id == prospect_id).first()

    # Gather sequences for this channel
    seqs = db.query(Sequence).filter(
        Sequence.prospect_id == prospect_id, Sequence.channel == channel
    ).order_by(Sequence.step_number.asc()).all()

    # Gather recent interactions
    ints = db.query(Interaction).filter(
        Interaction.prospect_id == prospect_id
    ).order_by(Interaction.created_at.desc()).limit(15).all()

    # Build context
    parts = []
    parts.append(f"Company: {prospect.company or 'Unknown'}")
    parts.append(f"Country: {prospect.country or 'Unknown'}")
    parts.append(f"Industry: {prospect.industry or 'Unknown'}")
    parts.append(f"Size: {prospect.size or 'Unknown'}")
    parts.append(f"Contact: {prospect.contact or 'Unknown'} | Title: {prospect.title or 'Unknown'}")
    parts.append(f"Profile: {prospect.profile_type or 'Unknown'}")
    if prospect.ai_score:
        parts.append(f"AI score: {prospect.ai_score}/10, Value: {prospect.value_level or '?'}")
    if prospect.score_reason:
        parts.append(f"Score reason: {prospect.score_reason[:400]}")
    if prospect.red_flags:
        parts.append(f"Risks: {prospect.red_flags[:300]}")
    if prospect.note:
        parts.append(f"Notes: {prospect.note[:300]}")

    if intel:
        if intel.website_key_points:
            parts.append(f"Website highlights: {intel.website_key_points[:400]}")
        if intel.icebreak_angles:
            parts.append(f"Icebreaker angles: {intel.icebreak_angles[:400]}")

    parts.append(f"\n=== {channel} outreach plan ===")
    if seqs:
        for s in seqs:
            status_en = {'pending':'Pending','sent':'Sent','skipped':'Skipped','done':'Done','cancelled':'Cancelled'}.get(s.status, s.status)
            parts.append(f"Step {s.step_number} [{status_en}] Date:{s.scheduled_date or 'Not set'} | Subject:{s.subject or ''}")
            if s.content:
                parts.append(f"  Content summary: {(s.content or '')[:300]}")
    else:
        parts.append("(No steps generated yet)")

    if ints:
        parts.append(f"\n=== Recent interactions ({len(ints)}) ===")
        for ix in ints[:10]:
            direction = '[Client]' if ix.direction == 'inbound' else '[Us]'
            parts.append(f"{direction} {ix.channel or ''}: {(ix.content or ix.subject or '')[:250]}")
    else:
        parts.append("\n(No interaction history)")

    context = '\n'.join(parts)

    prompt = f"""You are a senior export sales strategist at {{COMPANY}} (export manufacturer). Below is the client's full background and current outreach progress.

{context}

Analyze proactively; do not wait for the user to ask. Output:

1. **Current status** — What stage is this client at? Any progress signals? Any red flags to watch?
2. **Strategy suggestion** — On the {channel} channel, what is the most sensible next action and why?
3. **Messaging direction** — Give one concrete angle (in English), including the core selling point and entry angle
4. **Recommended action** — State one clear action (e.g. "after step 2, switch to LinkedIn" or "attach the sample spec PDF with the next email")

Answer in English. Keep it under 300 words, direct and to the point. Sound like a senior salesperson discussing strategy with a colleague."""

    try:
        loop = asyncio.get_event_loop()
        model_param = model_override if model_override in ("deepseek", "openai", "gemini") else None
        raw = await call_simple(prompt, model_param, 0.5, 2048)
        return {"success": True, "analysis": raw, "channel": channel}
    except Exception as exc:
        logger.exception("Strategy analysis failed")
        return {"success": False, "error": str(exc)}


# ── Helper ───────────────────────────────────────────

def _get_or_create_intelligence(prospect_id: int, db: Session) -> Intelligence:
    """Return existing intelligence record or create a new one."""
    intel = db.query(Intelligence).filter(Intelligence.prospect_id == prospect_id).first()
    if not intel:
        intel = Intelligence(prospect_id=prospect_id)
        db.add(intel)
        db.commit()
        db.refresh(intel)
    return intel


def _given_name_of(contact: str, country: str) -> str:
    """Return the given/first name from a contact string (CN pinyin uses the last token)."""
    contact = (contact or "").strip()
    parts = [x for x in re.split(r"[\s,\.]+", contact) if x]
    if not parts:
        return ""
    east = (country or "").upper() in ("CN", "TW", "HK", "MO", "SG", "JP", "KR")
    return parts[-1] if east and len(parts) > 1 else parts[0]


def _tidy_email_layout(text: str) -> str:
    """Normalize email layout: strip stray spaces, compress blank lines,
    enforce first-cold-email order (context -> value/spec -> CTA), and cap length."""
    if not text:
        return text
    text = re.sub(r"[ \t]+", " ", text)
    text = re.sub(r"\n+", " ", text).strip()

    greeting = ""
    m = re.match(r"^(Hi|Hello|Hey|Dear)\s+[^,]+,\s*", text, re.I)
    if m:
        greeting = m.group(0).strip()
        text = text[m.end():]

    text = text.strip()
    if not text:
        return greeting or "Hi there,"

    sentences = [s.strip() for s in re.split(r"(?<=[.!?])\s+", text) if s.strip()]
    cta_idx = None
    for i, s in enumerate(sentences):
        if re.search(r"\?|call|send|worth|happy|sample|catalog|spec", s, re.I):
            cta_idx = i
    if cta_idx is None and sentences:
        cta_idx = len(sentences) - 1

    cta = sentences[cta_idx] if cta_idx is not None else ""
    others = [s for i, s in enumerate(sentences) if i != cta_idx]

    context_first = re.compile(
        r"^(you|your|i (understand|noticed|saw|know|wanted)|if your|given your|"
        r"because your|seeing your|with your|your team|your company)\b",
        re.I,
    )
    self_intro = re.compile(
        r"^(we (are|manufacture|supply|provide|make|export)|we'?re a|our (company|factory|plant)|"
        r"i'?m .*?(from|with)|my name is)\b",
        re.I,
    )
    contexts, values, intros = [], [], []
    for s in others:
        if context_first.match(s):
            contexts.append(s)
        elif self_intro.match(s):
            intros.append(s)
        else:
            values.append(s)

    budget = 76 - len(greeting.split()) - len(cta.split())
    ordered = []
    for s in contexts + values + intros:
        w = len(s.split())
        if budget - w >= 0:
            ordered.append(s)
            budget -= w
    if cta:
        ordered.append(cta)

    if not ordered:
        return greeting or text
    if len(ordered) <= 3:
        body = " ".join(ordered)
    else:
        mid = max(1, len(ordered) - 2)
        body = " ".join(ordered[:mid]) + "\n\n" + " ".join(ordered[mid:])
    return (greeting + "\n\n" if greeting else "") + body


def _prospect_to_dict(p: Prospect, intel: Intelligence | None = None) -> dict:
    """Convert a Prospect ORM object + optional Intelligence to a dict for Gemini."""
    contact = (p.contact or "").strip()
    result = {
        "company": p.company or "",
        "website": p.website or "",
        "country": p.country or "",
        "size": p.size or "",
        "industry": p.industry or "",
        "title": p.title or "",
        "contact": p.contact or "",
        "given_name": _given_name_of(contact, p.country or ""),
        "note": p.note or "",
        "linkedin": p.linkedin or "",
        "profile_type": p.profile_type or "",
        "status": p.status or "",
        "decision_maker": p.decision_maker or "",
        "dm_title": p.dm_title or "",
        "intent_signals": p.intent_signals or "",
    }
    return result


def _intelligence_to_dict(intel: Intelligence | None) -> dict:
    """Convert Intelligence ORM to dict for Gemini."""
    if not intel:
        return {}
    return {
        "website_content": intel.website_content or "",
        "website_key_points": intel.website_key_points or "",
        "linkedin_content": intel.linkedin_content or "",
        "hiring_signals": intel.hiring_signals or "",
        "icebreak_angles": intel.icebreak_angles or "",
    }


def _count_paused_sequences(db: Session, prospect_id: int) -> int:
    """Count how many sequences were paused for this prospect due to hot reply."""
    return db.query(Sequence).filter(
        Sequence.prospect_id == prospect_id,
        Sequence.status == "paused_hot_reply",
    ).count()


# ── DeepSeek connectivity test ──

@router.post("/test-deepseek")
async def test_deepseek():
    """Direct DeepSeek API test — returns full raw response for diagnosis."""
    import httpx
    from config import DEEPSEEK_API_KEY

    headers = {"Authorization": f"Bearer {DEEPSEEK_API_KEY}", "Content-Type": "application/json"}
    body = {"model": "deepseek-v4-pro", "messages": [{"role": "user", "content": "Say hello in 3 words."}], "temperature": 0.1, "max_tokens": 64}

    try:
        with httpx.Client(proxy=None, trust_env=False, timeout=30) as client:
            resp = client.post("https://api.deepseek.com/v1/chat/completions", json=body, headers=headers)
            status = resp.status_code
            text = resp.text[:2000]
            try:
                js = resp.json()
                choice = js.get("choices", [{}])[0] if js.get("choices") else {}
                content = choice.get("message", {}).get("content", "")
            except:
                js = None
                content = ""
            return {"success": True, "http_status": status, "full_body": text, "parsed_content": content, "model_used": js.get("model") if js else None}
    except Exception as e:
        return {"success": False, "error": str(e)}


# ──────────────────────────────────────────────────────
#  POST /api/ai/score/batch
# ──────────────────────────────────────────────────────

@router.post("/score/batch")
async def batch_score(payload: BatchScoreRequest, db: Session = Depends(get_db),
                      user: User = Depends(get_current_user)):
    """Score multiple prospects in sequence."""
    # Extract model_override — try both Pydantic model_extra and dict fallback
    model_override = None
    try:
        if hasattr(payload, "model_extra") and payload.model_extra:
            mo = payload.model_extra.get("model_override")
        elif isinstance(payload, dict):
            mo = payload.get("model_override")
        else:
            mo = payload.__dict__.get("model_override")
        if mo in ("deepseek", "openai", "gemini", "auto"):
            model_override = mo
    except Exception:
        pass

    results = []
    scored_count = 0
    for pid in payload.prospect_ids:
        try:
            prospect = db.query(Prospect).filter(
                Prospect.id == pid, Prospect.is_deleted == 0
            ).first()
            if not prospect:
                results.append({"prospect_id": pid, "success": False, "error": "Not found"})
                continue

            intel = db.query(Intelligence).filter(Intelligence.prospect_id == pid).first()
            data = {
                "prospect": _prospect_to_dict(prospect),
                "intelligence": _intelligence_to_dict(intel),
            }

            result = await call_skill_1_analysis("scoring", data, model_override=model_override)

            if "error" not in result:
                scored_count += 1
                score = _pick(result, "totalScore", "aiScore", "ai_score", "score")
                breakdown = _pick(result, "scoreBreakdown", "score_breakdown") or {}
                profile_type = _pick(result, "profileType", "profile_type", "profile") or ""
                score_reason = _pick(result, "scoreSummary", "scoreReason", "score_reason", "reasoning") or ""
                value_level = _pick(result, "valueLevel", "value_level") or ""
                red_flags = _pick(result, "redFlags", "red_flags") or []
                if profile_type and profile_type.upper() in ("A","B","C","D","E","EXCLUDE"):
                    profile_type = profile_type.upper()
                if score is not None:
                    prospect.ai_score = float(score)
                if profile_type:
                    # Only fill if blank — manual classification is authoritative
                    existing = (prospect.profile_type or "").strip()
                    if not existing or existing.lower() == "unknown":
                        prospect.profile_type = profile_type
                        prospect.profile_source = "ai"
                    else:
                        logger.debug("Preserved manual profile_type=%s (AI suggested %s) for #%d",
                                     existing, profile_type, pid)
                        # Even if we keep manual type, still mark the source was overridden by AI at some point
                        # (but don't overwrite existing manual source)
                if breakdown and isinstance(breakdown, dict) and len(breakdown) > 0:
                    prospect.score_breakdown = json.dumps(breakdown, ensure_ascii=False)
                if score_reason:
                    prospect.score_reason = score_reason
                if value_level:
                    prospect.value_level = value_level
                if red_flags:
                    prospect.red_flags = json.dumps(red_flags if isinstance(red_flags, list) else [red_flags], ensure_ascii=False)
                if not value_level and score is not None:
                    s = float(score)
                    prospect.value_level = "HIGH" if s >= 75 else ("MID" if s >= 50 else ("LOW" if s >= 25 else "DEPRIORITIZE"))
                prospect.updated_at = datetime.utcnow()
                prospect.last_edited_at = datetime.utcnow()

            results.append({"prospect_id": pid, "success": "error" not in result, "result": result})
        except Exception as exc:
            results.append({"prospect_id": pid, "success": False, "error": str(exc)})

    db.commit()
    success_count = sum(1 for r in results if r.get("success"))
    return {"scored": success_count, "total": len(results), "results": results}


# ──────────────────────────────────────────────────────
#  POST /api/ai/score/{prospect_id}
# ──────────────────────────────────────────────────────

@router.post("/score/{prospect_id}")
async def score_prospect(prospect_id: int, payload: dict = None, db: Session = Depends(get_db),
                         user: User = Depends(get_current_user)):
    """Score a single prospect — profile type, AI score, value level."""
    prospect = db.query(Prospect).filter(
        Prospect.id == prospect_id, Prospect.is_deleted == 0
    ).first()
    if not prospect:
        raise HTTPException(status_code=404, detail="Prospect not found")

    # Extract model_override from request body
    model_override = None
    if payload and isinstance(payload, dict):
        mo = payload.get("model_override")
        if mo in ("deepseek", "openai", "gemini", "auto"):
            model_override = mo

    intel = db.query(Intelligence).filter(Intelligence.prospect_id == prospect_id).first()

    data = {
        "prospect": _prospect_to_dict(prospect),
        "intelligence": _intelligence_to_dict(intel),
    }

    logger.info("Scoring prospect #%d: %s (model=%s)", prospect_id, prospect.company, model_override or get_active_model())
    try:
        result = await call_skill_1_analysis("scoring", data, model_override=model_override)
    except Exception as e:
        logger.exception("Scoring call exploded")
        return {"success": False, "error": f"AI call exception: {e}"}

    if "error" in result:
        logger.error("Scoring #%d failed: %s", prospect_id, result.get("error", "unknown"))
        raw_preview = str(result.get("raw", ""))[:200]
        return {"success": False, "error": result.get("error", "Unknown") + (" | " + raw_preview if raw_preview else "")}

    # Save results — normalize both DeepSeek and Gemini response formats
    # DeepSeek: {"score": N, "profile": "A|B|C|EXCLUDE", "reasoning": "...", "next_action": "..."}
    # Gemini:   {"totalScore": N, "profileType": "A|B|C|EXCLUDE", "scoreBreakdown": {...}, ...}

    score = _pick(result, "totalScore", "aiScore", "ai_score", "score")
    breakdown = _pick(result, "scoreBreakdown", "score_breakdown") or {}
    profile_type = _pick(result, "profileType", "profile_type", "profile") or ""
    score_reason = _pick(result, "scoreSummary", "scoreReason", "score_reason", "reasoning") or ""
    value_level = _pick(result, "valueLevel", "value_level") or ""
    red_flags = _pick(result, "redFlags", "red_flags") or []
    next_action = _pick(result, "recommendedAction", "recommended_action", "next_action") or ""

    # Normalize profile type value
    if profile_type and profile_type.upper() in ("A","B","C","D","E","EXCLUDE"):
        profile_type = profile_type.upper()
    elif profile_type and profile_type.lower() == "exclude":
        profile_type = "EXCLUDE"
    elif not profile_type:
        profile_type = ""

    # Auto-generate value level from score if missing
    if not value_level and score is not None:
        s = float(score)
        value_level = "HIGH" if s >= 75 else ("MID" if s >= 50 else ("LOW" if s >= 25 else "DEPRIORITIZE"))

    logger.info("Normalized: score=%s, profile=%s, value=%s", score, profile_type, value_level)

    if score is None:
        logger.error("Score missing from result. Available keys: %s, values sample: %s",
                     list(result.keys()), {k: str(v)[:100] for k, v in list(result.items())[:5]})
        return {"success": False, "error": f"AI returned no score. Response keys: {list(result.keys())[:20]}"}

    # Re-fetch fresh from DB to avoid stale-cache issues
    db.refresh(prospect)
    try:
        if score is not None:
            prospect.ai_score = float(score)
        if breakdown and isinstance(breakdown, dict) and len(breakdown) > 0:
            prospect.score_breakdown = json.dumps(breakdown, ensure_ascii=False)
        # Set profile_type (only if blank — manual is authoritative)
        if profile_type and not prospect.profile_type:
            prospect.profile_type = profile_type
            prospect.profile_source = "ai"  # AI filled this blank
        if score_reason:
            prospect.score_reason = score_reason
        if value_level:
            prospect.value_level = value_level
        if red_flags:
            prospect.red_flags = json.dumps(red_flags if isinstance(red_flags, list) else [red_flags], ensure_ascii=False)
        if next_action:
            pass  # stored in score_reason already, skip separate field
        prospect.updated_at = datetime.utcnow()
        prospect.last_edited_at = datetime.utcnow()
        db.commit()
        db.refresh(prospect)
        logger.info("Saved score #%d: score=%s profile=%s value=%s", prospect_id, prospect.ai_score, prospect.profile_type, prospect.value_level)
        try:
            log_audit(db, user, "ai_score", f"prospect#{prospect_id}",
                      f"AI score {prospect.company}: {prospect.ai_score}/{prospect.value_level}")
        except Exception:
            pass
    except Exception as e:
        logger.exception("Failed to save score for #%d", prospect_id)
        db.rollback()

    return {
        "success": True,
        "prospect_id": prospect_id,
        "result": result,
        "model": get_active_model(),
    }


# ──────────────────────────────────────────────────────
#  POST /api/ai/score/batch
# ──────────────────────────────────────────────────────

@router.post("/score/batch")
async def batch_score(payload: BatchScoreRequest, db: Session = Depends(get_db)):
    """Score multiple prospects in sequence."""
    # Extract model_override — try both Pydantic model_extra and dict fallback
    model_override = None
    try:
        if hasattr(payload, "model_extra") and payload.model_extra:
            mo = payload.model_extra.get("model_override")
        elif isinstance(payload, dict):
            mo = payload.get("model_override")
        else:
            mo = payload.__dict__.get("model_override")
        if mo in ("deepseek", "openai", "gemini", "auto"):
            model_override = mo
    except Exception:
        pass

    results = []
    for pid in payload.prospect_ids:
        try:
            prospect = db.query(Prospect).filter(
                Prospect.id == pid, Prospect.is_deleted == 0
            ).first()
            if not prospect:
                results.append({"prospect_id": pid, "success": False, "error": "Not found"})
                continue

            intel = db.query(Intelligence).filter(Intelligence.prospect_id == pid).first()
            data = {
                "prospect": _prospect_to_dict(prospect),
                "intelligence": _intelligence_to_dict(intel),
            }

            result = await call_skill_1_analysis("scoring", data, model_override=model_override)

            if "error" not in result:
                score = _pick(result, "totalScore", "aiScore", "ai_score", "score")
                breakdown = _pick(result, "scoreBreakdown", "score_breakdown") or {}
                profile_type = _pick(result, "profileType", "profile_type", "profile") or ""
                score_reason = _pick(result, "scoreSummary", "scoreReason", "score_reason", "reasoning") or ""
                value_level = _pick(result, "valueLevel", "value_level") or ""
                red_flags = _pick(result, "redFlags", "red_flags") or []
                if profile_type and profile_type.upper() in ("A","B","C","D","E","EXCLUDE"):
                    profile_type = profile_type.upper()
                if score is not None:
                    prospect.ai_score = float(score)
                if profile_type:
                    # Only fill if blank — manual classification is authoritative
                    existing = (prospect.profile_type or "").strip()
                    if not existing or existing.lower() == "unknown":
                        prospect.profile_type = profile_type
                        prospect.profile_source = "ai"
                    else:
                        logger.debug("Preserved manual profile_type=%s (AI suggested %s) for #%d",
                                     existing, profile_type, pid)
                        # Even if we keep manual type, still mark the source was overridden by AI at some point
                        # (but don't overwrite existing manual source)
                if breakdown and isinstance(breakdown, dict) and len(breakdown) > 0:
                    prospect.score_breakdown = json.dumps(breakdown, ensure_ascii=False)
                if score_reason:
                    prospect.score_reason = score_reason
                if value_level:
                    prospect.value_level = value_level
                if red_flags:
                    prospect.red_flags = json.dumps(red_flags if isinstance(red_flags, list) else [red_flags], ensure_ascii=False)
                if not value_level and score is not None:
                    s = float(score)
                    prospect.value_level = "HIGH" if s >= 75 else ("MID" if s >= 50 else ("LOW" if s >= 25 else "DEPRIORITIZE"))
                prospect.updated_at = datetime.utcnow()
                prospect.last_edited_at = datetime.utcnow()

            results.append({"prospect_id": pid, "success": "error" not in result, "result": result})
        except Exception as exc:
            results.append({"prospect_id": pid, "success": False, "error": str(exc)})

    db.commit()
    success_count = sum(1 for r in results if r.get("success"))
    return {"scored": success_count, "total": len(results), "results": results}


# ──────────────────────────────────────────────────────
#  POST /api/ai/analyze-screenshot/{prospect_id}
# ──────────────────────────────────────────────────────

@router.post("/analyze-screenshot/{prospect_id}")
async def analyze_screenshot(prospect_id: int, payload: dict = None, db: Session = Depends(get_db)):
    """Analyze a screenshot (e.g. LinkedIn profile, company website) via Gemini Vision.
    payload.image_b64: base64-encoded image string
    payload.image_type: 'linkedin_profile' | 'company_page' | 'website_screenshot' | 'other'
    Stores the analysis in intelligence.screenshot_analysis field."""
    image_b64 = (payload or {}).get("image_b64", "")
    image_type = (payload or {}).get("image_type", "other")
    model_override = (payload or {}).get("model_override") or None
    if model_override and model_override not in ("gemini", "auto"):
        model_override = None  # vision only supports Gemini; ignore non-vision overrides
    if model_override == "auto":
        model_override = None  # "auto" means use default (Gemini)
    if not image_b64:
        return {"success": False, "error": "image_b64 is required"}

    prospect = db.query(Prospect).filter(
        Prospect.id == prospect_id, Prospect.is_deleted == 0
    ).first()
    if not prospect:
        raise HTTPException(status_code=404, detail="Prospect not found")

    intel = _get_or_create_intelligence(prospect_id, db)

    # Detect mime type from data: prefix if present
    mime_type = "image/png"
    clean_b64 = image_b64
    if image_b64.startswith("data:"):
        m = __import__('re').match(r"data:(image/\w+);base64,(.*)", image_b64)
        if m:
            mime_type = m.group(1)
            clean_b64 = m.group(2)

    type_labels = {
        'linkedin_profile': 'LinkedIn profile screenshot',
        'company_page': 'company page screenshot',
        'website_screenshot': 'website screenshot',
        'other': 'screenshot'
    }
    image_label = type_labels.get(image_type, 'screenshot')

    prompt = f"""You are a B2B sales intelligence analyst. Analyze this {image_label} and extract the key information.

Output in English:
1. **Company / person overview** — key facts visible in the screenshot
2. **Business signals** — anything suggesting product sourcing (what they buy, whether they have an R&D team, any supplier-change mentions)
3. **Contact value** — if it is a LinkedIn profile, judge this person's decision-making weight and an entry angle
4. **Action suggestions** — 1-2 concrete next steps based on the screenshot

Keep it under 250 words. Get straight to the point."""

    try:
        # Check image size — Gemini has payload limits (~20MB, but we cap at 5MB base64 for safety)
        if len(clean_b64) > 5_000_000:
            return {"success": False, "error": "Image too large ("+str(round(len(clean_b64)/1e6,1))+"MB) — please resize the screenshot and retry (PNG cropped to the key area works best)"}
        loop = asyncio.get_event_loop()
        raw = await loop.run_in_executor(None, call_gemini_vision, prompt, clean_b64, mime_type, 0.3, 2048)
        # Store in intelligence
        current = intel.screenshot_analysis or ''
        timestamp = datetime.utcnow().strftime('%Y-%m-%d %H:%M')
        new_entry = f"\n\n[{timestamp}] {image_label} analysis:\n{raw}"
        intel.screenshot_analysis = (current + new_entry)[:10000]
        db.commit()
        return {"success": True, "analysis": raw, "image_type": image_type}
    except Exception as exc:
        err_msg = str(exc)
        # Map known errors to user-friendly messages
        if "Read timed out" in err_msg or "timeout" in err_msg.lower():
            err_msg = "Gemini API timed out — the image may be too large or the network unstable; try a smaller screenshot or retry"
        elif "413" in err_msg or "payload" in err_msg.lower():
            err_msg = "Image too large — please crop or resize the screenshot and retry"
        elif "429" in err_msg or "quota" in err_msg.lower():
            err_msg = "API quota exhausted — please try again later"
        elif "SSL" in err_msg or "ConnectionError" in err_msg or "connect" in err_msg.lower():
            err_msg = "Network connection failed — please check your proxy/VPN"
        logger.exception("Screenshot analysis failed")
        return {"success": False, "error": err_msg}


# ──────────────────────────────────────────────────────
#  POST /api/ai/scrape/{prospect_id}
# ──────────────────────────────────────────────────────

@router.post("/scrape/{prospect_id}")
async def scrape_prospect_website(prospect_id: int, db: Session = Depends(get_db)):
    """Run full OSINT pipeline: scrape website (if URL exists) + Whois + patents + FDA + AI analysis."""
    try:
        prospect = db.query(Prospect).filter(
            Prospect.id == prospect_id, Prospect.is_deleted == 0
        ).first()
        if not prospect:
            raise HTTPException(status_code=404, detail="Prospect not found")

        # Run full refresh pipeline — handles no-website case internally
        from services.auto_intelligence import refresh_single_prospect
        result = await refresh_single_prospect(prospect_id, db)
        if result.get("status") == "ok":
            intel = db.query(Intelligence).filter(Intelligence.prospect_id == prospect_id).first()
            resp = {
                "success": True,
                "prospect_id": prospect_id,
                "has_website": bool(prospect.website and prospect.website.strip()),
                "chars_scraped": len(intel.website_content or "") if intel else 0,
                "preview": (intel.website_content or "")[:500] if intel else "",
                "osint_steps": result.get("steps", []),
                "patent_count": result.get("patent_count", 0),
                "fda_510k_count": result.get("fda_510k_count", 0),
                "domain_age_days": result.get("domain_age_days"),
            }
            if result.get("website_error"):
                resp["website_error"] = result["website_error"]
            return resp
        else:
            return {"success": False, "error": result.get("reason", "Scrape failed")}
    except Exception as exc:
        logger.exception("Scrape + OSINT failed for #%d: %s", prospect_id, exc)
        return {"success": False, "error": str(exc)[:300]}


# ──────────────────────────────────────────────────────
#  POST /api/ai/quality-check
# ──────────────────────────────────────────────────────

@router.post("/quality-check")
async def email_quality_check(payload: dict = None, db: Session = Depends(get_db)):
    """Multi-model cold-email quality check (DeepSeek + Gemini).
    Each model scores the email 0-100; results returned for side-by-side review."""
    payload = payload or {}
    subject = str(payload.get("subject") or "")
    body = str(payload.get("body") or "")
    if not body.strip():
        return {"success": False, "error": "Email body is empty"}
    prospect = None
    pid = payload.get("prospect_id")
    if pid:
        try:
            prospect = db.query(Prospect).filter(
                Prospect.id == int(pid), Prospect.is_deleted == 0
            ).first()
        except Exception:
            prospect = None
    from services.email_quality import quality_check_email
    result = await quality_check_email(subject, body, prospect)
    result["success"] = True
    return result


# ──────────────────────────────────────────────────────
#  POST /api/ai/analyze-intelligence/{prospect_id}
# ──────────────────────────────────────────────────────

@router.post("/analyze-intelligence/{prospect_id}")
async def analyze_intelligence(prospect_id: int, db: Session = Depends(get_db)):
    """
    Analyze scraped website content + LinkedIn content to extract:
    - website_key_points (Gemini-extracted key insights)
    - hiring_signals (if hiring_content is provided)
    - icebreak_angles (3-5 personalized outreach angles)
    """
    prospect = db.query(Prospect).filter(
        Prospect.id == prospect_id, Prospect.is_deleted == 0
    ).first()
    if not prospect:
        raise HTTPException(status_code=404, detail="Prospect not found")

    intel = _get_or_create_intelligence(prospect_id, db)

    # ── Extract key points from website content ──
    if intel.website_content:
        extract_prompt = f"""Extract 5-8 key business facts from this website content. Focus on: what they do, products/services, target customers, capabilities, size, regions served. Return ONLY a JSON array of strings.

Website content:
{intel.website_content[:4000]}"""

        try:
            loop = asyncio.get_event_loop()
            raw = await call_simple(extract_prompt, None, 0.3, 2048)
            # Strip markdown code fences
            if "```" in raw:
                import re
                m = re.search(r"```(?:json)?\s*\n?(.*?)\n?```", raw, re.DOTALL)
                raw = m.group(1).strip() if m else raw
            key_points = json.loads(raw)
            if isinstance(key_points, list):
                intel.website_key_points = json.dumps(key_points, ensure_ascii=False)
        except Exception as exc:
            logger.warning("Key-point extraction failed: %s", exc)

    # ── Hiring signals ──
    if intel.hiring_content:
        hiring_prompt = f"""Analyze this job posting / career page content. Identify if they are hiring for: purchasing / sales, engineering, manufacturing, or R&D roles. Return ONLY a JSON array of strings describing each relevant signal found. If no signals, return [].

Content:
{intel.hiring_content[:3000]}"""

        try:
            loop = asyncio.get_event_loop()
            raw = await call_simple(hiring_prompt, None, 0.3, 2048)
            # Strip markdown code fences
            if "```" in raw:
                import re
                m = re.search(r"```(?:json)?\s*\n?(.*?)\n?```", raw, re.DOTALL)
                raw = m.group(1).strip() if m else raw
            signals = json.loads(raw)
            if isinstance(signals, list):
                intel.hiring_signals = json.dumps(signals, ensure_ascii=False)
        except Exception as exc:
            logger.warning("Hiring signal extraction failed: %s", exc)

    # ── Generate icebreaker angles ──
    all_content_parts = []
    if intel.website_key_points:
        all_content_parts.append(f"Website key points:\n{intel.website_key_points}")
    if intel.linkedin_content:
        all_content_parts.append(f"LinkedIn profile:\n{intel.linkedin_content[:1000]}")
    if intel.hiring_signals:
        all_content_parts.append(f"Hiring signals:\n{intel.hiring_signals}")

    if all_content_parts:
        angle_prompt = f"""Based on the following intelligence about a prospect company, generate 3-5 personalized outreach/icebreaker angles that a salesperson from {{COMPANY}} could use. Each angle should be specific, reference real details, and explain WHY it would work.

Return ONLY a JSON array of objects, each with: "angle" (the approach), "why" (why it should resonate).

Intelligence:
{chr(10).join(all_content_parts)}

Company: {prospect.company}
Country: {prospect.country or 'Unknown'}"""

        try:
            loop = asyncio.get_event_loop()
            raw = await call_simple(angle_prompt, None, 0.5, 3072)
            # Strip markdown code fences
            if "```" in raw:
                import re
                m = re.search(r"```(?:json)?\s*\n?(.*?)\n?```", raw, re.DOTALL)
                raw = m.group(1).strip() if m else raw
            angles = json.loads(raw)
            if isinstance(angles, list):
                intel.icebreak_angles = json.dumps(angles, ensure_ascii=False)
        except Exception as exc:
            logger.warning("Icebreaker generation failed: %s", exc)

    # ── Who decides? 找决策人 ──
    try:
        info_for_dm = (intel.website_key_points or intel.website_content or "")[:2500]
        if info_for_dm:
            dm_prompt = (
                f"Based on this company's information, identify WHO most likely makes or influences "
                f"equipment/purchase decisions and their role.\nCompany: {prospect.company}\n"
                f"Info:\n{info_for_dm}\n"
                'Return ONLY JSON: {"name":"...","title":"...","role":"boss|purchasing|production|engineering|technical|unknown","linkedin_hint":"..."}'
            )
            loop = asyncio.get_event_loop()
            raw = await call_simple(dm_prompt, None, 0.3, 1024)
            if "```" in raw:
                import re
                m = re.search(r"```(?:json)?\s*\n?(.*?)\n?```", raw, re.DOTALL)
                raw = m.group(1).strip() if m else raw
            dm = json.loads(raw)
            role_map = {"boss": "Owner/Boss", "purchasing": "Purchasing", "production": "Production",
                        "engineering": "Engineering", "technical": "Technical", "unknown": "Unknown"}
            name = str(dm.get("name", "") or "").strip()
            title = str(dm.get("title", "") or "").strip()
            role_key = str(dm.get("role", "") or "unknown").lower()
            if name:
                prospect.decision_maker = name
            if title:
                prospect.dm_title = title
            prospect.decision_role = role_map.get(role_key, role_key or "Unknown")
            db.commit()
    except Exception as exc:
        logger.warning("Decision-maker extraction failed: %s", exc)

    intel.analyzed_at = datetime.utcnow()
    intel.updated_at = datetime.utcnow()
    db.commit()
    db.refresh(intel)

    return {
        "success": True,
        "prospect_id": prospect_id,
        "website_key_points": json.loads(intel.website_key_points) if intel.website_key_points else [],
        "hiring_signals": json.loads(intel.hiring_signals) if intel.hiring_signals else [],
        "icebreak_angles": json.loads(intel.icebreak_angles) if intel.icebreak_angles else [],
    }

# ── Auto-Intelligence endpoints ────────────────────────

@router.post("/auto-intel/{prospect_id}")
async def trigger_auto_intel_single(prospect_id: int, db: Session = Depends(get_db)):
    """Manually trigger the auto-intelligence pipeline for one prospect."""
    from services.auto_intelligence import refresh_single_prospect
    try:
        result = await refresh_single_prospect(prospect_id, db)
        return {"success": True, **result}
    except Exception as exc:
        logger.exception("Manual auto-intel failed for #%d", prospect_id)
        return {"success": False, "error": str(exc)}


@router.post("/auto-intel/batch")
async def trigger_auto_intel_batch(db: Session = Depends(get_db)):
    """Manually trigger auto-intelligence for ALL due prospects right now."""
    from services.auto_intelligence import run_auto_intelligence
    import asyncio as _asyncio
    try:
        loop = _asyncio.get_event_loop()
        await loop.run_in_executor(None, run_auto_intelligence)
        return {"success": True, "message": "Auto-intelligence run completed"}
    except Exception as exc:
        logger.exception("Batch auto-intel failed")
        return {"success": False, "error": str(exc)}


# ──────────────────────────────────────────────────────
#  POST /api/ai/generate-message/{prospect_id}
# ──────────────────────────────────────────────────────

@router.post("/generate-message/{prospect_id}")
async def generate_message(
    prospect_id: int,
    payload: GenerateMessageRequest,
    db: Session = Depends(get_db),
):
    """Generate a personalized outreach message (LinkedIn or email)."""
    model_override = payload.model_override if payload.model_override in ("deepseek", "openai", "gemini", "auto") else None

    prospect = db.query(Prospect).filter(
        Prospect.id == prospect_id, Prospect.is_deleted == 0
    ).first()
    if not prospect:
        # Allow unmatched or deleted prospects — generate reply from email context
        logger.info("Generating message for unmatched prospect (prospect_id=%d)", prospect_id)
        prospect_dict = {"company": "unknown", "website": "", "country": "", "size": "", "industry": "", "title": "", "contact": "", "given_name": "", "note": "", "linkedin": "", "profile_type": "", "status": "", "decision_maker": "", "dm_title": ""}
        intel_dict = {}
        prev_interactions = []
    else:
        intel = db.query(Intelligence).filter(Intelligence.prospect_id == prospect_id).first()
        prospect_dict = _prospect_to_dict(prospect)
        intel_dict = _intelligence_to_dict(intel)
        prev_interactions = []
    # 回复类（跟进 / 询盘报价回复）必须加载完整往来历史，AI 才有上下文；
    # 只有首封冷开发（cold_email）不加载历史。
    if payload.message_type != "cold_email":
        prev = (
            db.query(Interaction)
            .filter(Interaction.prospect_id == prospect_id)
            .order_by(Interaction.interacted_at.desc())
            .limit(15)
            .all()
        )
        prev_interactions = [
            {
                "direction": p.direction,
                "channel": p.channel,
                "content": p.content,
                "subject": p.subject,
                "reply_intent": p.reply_intent,
            }
            for p in prev
        ]
        # 已完成的开发计划步骤也加进上下文
        seq_history = (
            db.query(Sequence)
            .filter(Sequence.prospect_id == prospect_id, Sequence.status == "done")
            .order_by(Sequence.executed_at.desc())
            .limit(5)
            .all()
        )
        for s in seq_history:
            prev_interactions.append({
                "direction": "outbound",
                "channel": s.channel,
                "content": s.content,
                "subject": s.subject,
            })

    data = {
        "prospect": prospect_dict,
        "intelligence": intel_dict,
        "tone": payload.tone,
        "additional_context": payload.additional_context or "",
        "previous_interactions": prev_interactions,
    }

    logger.info(
        "Generating %s message for prospect #%d: %s",
        payload.message_type, prospect_id, prospect_dict.get('company','unknown'),
    )
    result = await call_skill_2_generation(payload.message_type, data, model_override=model_override)
    logger.info("Generate result for #%d: success=%s error=%s", prospect_id, "error" not in result, result.get("error",""))

    # Greeting normalization: force "Hi {given name}," not the full name.
    body_out = result.get("body")
    if prospect and body_out:
        given = _given_name_of(prospect.contact or "", prospect.country or "")
        lead = body_out.lstrip()
        if not re.match(r"^(Hi|Dear|Hello|Hey)\b", lead, re.I):
            body_out = ("Hi " + (given or "there") + ", " + lead)
        elif given:
            body_out = re.sub(r"^Hi\s+[^,]+,\s*", "Hi " + given + ", ", body_out, count=1)
        result["body"] = _tidy_email_layout(body_out)

    return {
        "success": "error" not in result,
        "prospect_id": prospect_id,
        "message_type": payload.message_type,
        "error": result.get("error") if "error" in result else None,
        "result": result,
    }


@router.post("/revise-message/{prospect_id}")
async def revise_message(
    prospect_id: int,
    payload: dict,
    db: Session = Depends(get_db),
):
    prospect = db.query(Prospect).filter(
        Prospect.id == prospect_id, Prospect.is_deleted == 0
    ).first()
    if not prospect:
        # Allow unmatched or deleted prospects for revise
        logger.info("Revising message for unmatched prospect (prospect_id=%d)", prospect_id)
        prospect = type('obj', (object,), {
            'id': prospect_id, 'company': '', 'website': '', 'country': '', 'size': '', 'industry': '',
            'title': '', 'contact': '', 'note': '', 'linkedin': '', 'profile_type': '',
            'status': '', 'decision_maker': '', 'dm_title': '',
        })()
        intel = None
    else:
        intel = db.query(Intelligence).filter(Intelligence.prospect_id == prospect_id).first()

    # Extract model_override
    model_override = None
    if payload and isinstance(payload, dict):
        mo = payload.get("model_override")
        if mo in ("deepseek", "openai", "gemini", "auto"):
            model_override = mo

    current_body = payload.get("current_body", "")
    current_subject = payload.get("current_subject", "")
    instruction = payload.get("instruction", "")
    message_type = payload.get("message_type", "cold_email")
    tone = payload.get("tone", "formal")

    # Use lightweight call_simple for revision requests — no need for the heavy
    # skill_2 prompt with prospect intelligence, trade shows, profile strategies, etc.
    prompt = f"""You are revising an email draft. Follow the instruction below.

INSTRUCTION:
{instruction}

CURRENT DRAFT:
Subject: {current_subject}

{current_body}

Return ONLY the revised email body as clean HTML. Do NOT include markdown fences.
Do NOT add explanations, greetings like "here is the revised version", or any text before or after the HTML."""

    logger.info("Revising %s for #%d: %s", message_type, prospect_id, instruction[:80])
    raw = await call_simple(prompt, model_override, 0.3, 4096)

    # Clean up markdown fences if present
    raw = raw.strip()
    for fence in ("```html", "```HTML", "```", "'''html", "'''"):
        if raw.startswith(fence):
            raw = raw[len(fence):].strip()
        if raw.endswith(fence.strip()):
            raw = raw[:-len(fence.strip())].strip()

    return {
        "success": True,
        "prospect_id": prospect_id,
        "message_type": message_type,
        "result": {"body": raw},
    }


# ──────────────────────────────────────────────────────
#  POST /api/ai/analyze-reply/{interaction_id}
# ──────────────────────────────────────────────────────

@router.post("/analyze-reply/{interaction_id}")
async def analyze_reply(interaction_id: int, payload: dict = None, db: Session = Depends(get_db)):
    """Analyze an inbound customer reply and suggest next action."""
    # Extract model_override
    model_override = None
    if payload and isinstance(payload, dict):
        mo = payload.get("model_override")
        if mo in ("deepseek", "openai", "gemini", "auto"):
            model_override = mo

    interaction = db.query(Interaction).filter(Interaction.id == interaction_id).first()
    if not interaction:
        raise HTTPException(status_code=404, detail="Interaction not found")

    if interaction.direction != "inbound":
        return {"success": False, "error": "Can only analyze inbound replies"}

    # 防线：内容明显像“我方发出的开发信/跟进消息”时，不要当成客户回复来分析
    _SELF_MSG_HINTS = [
        "just bumping this up",
        "bumping this up",
        "saw your profile",
        "i am reaching out",
        "i am writing",
        "i wrote to",
        "we specialize",
        "we are a supplier of",
        "i wanted to follow up",
        "if you guys happen to",
    ]
    _low_content = (interaction.content or "").lower()
    if any(h in _low_content for h in _SELF_MSG_HINTS):
        interaction.reply_intent = ""
        interaction.key_signals = json.dumps([], ensure_ascii=False)
        interaction.ai_suggested_action = "This looks like a message sent by us, not a client reply; please confirm whether the interaction direction was recorded incorrectly."
        db.commit()
        return {
            "success": True,
            "interaction_id": interaction_id,
            "result": {
                "replyIntent": "",
                "warning": "This looks like a message we sent, not a client reply; no client-intent analysis was performed.",
            },
        }

    # 防线：休假/自动回复（Automatische Antwort / Out of office 等）不是真实回复，
    # 不能按 REJECTION 或正常客户回复处理，直接标记为延迟跟进。
    _AUTO_REPLY_SUBJECT_HINTS = [
        "automatische antwort",
        "automatic reply",
        "autoreply",
        "auto reply",
        "out of office",
        "out-of-office",
        "abwesenheit",
        "urlaub",
    ]
    _AUTO_REPLY_BODY_HINTS = [
        "automatische antwort",
        "automatic reply",
        "autoreply",
        "auto reply",
        "out of office",
        "not in the office",
        "nicht im büro",
        "nicht im buero",
        "bin momentan nicht erreichbar",
        "erst am",
        "wieder erreichbar",
        "will not be read",
        "not be read",
        "away from the office",
        "on holiday",
        "on vacation",
        "im urlaub",
        "abwesenheitsnotiz",
    ]
    _subject_low = (interaction.subject or "").lower()
    _body_low = (interaction.content or "").lower()
    _is_auto_reply = any(h in _subject_low for h in _AUTO_REPLY_SUBJECT_HINTS) or any(
        h in _body_low for h in _AUTO_REPLY_BODY_HINTS
    )
    if _is_auto_reply:
        interaction.reply_intent = "OUT_OF_OFFICE"
        interaction.sentiment_score = 0
        interaction.key_signals = json.dumps(["Auto-reply / out-of-office notice, not a human reply"], ensure_ascii=False)
        interaction.ai_suggested_action = (
            "The client is on holiday/auto-reply; do not send repeats. Extract the return date mentioned "
            "in the email and follow up 2-3 business days after they return; meanwhile prepare a backup touch on LinkedIn."
        )
        interaction.ai_suggested_channel = "email"
        interaction.ai_suggested_timing = ""
        interaction.ai_draft_suggestion = ""
        db.commit()
        return {
            "success": True,
            "interaction_id": interaction_id,
            "result": {
                "replyIntent": "OUT_OF_OFFICE",
                "warning": "Detected holiday/auto-reply; treated as a delayed follow-up, not a rejection.",
            },
        }

    prospect = db.query(Prospect).filter(Prospect.id == interaction.prospect_id).first()
    if not prospect:
        # Allow unmatched inbound emails — use generic prospect info
        prospect = type('obj', (object,), {
            'id': 0,
            'company': interaction.email_from or 'Unknown',
            'website': '',
            'country': '',
            'size': '',
            'industry': '',
            'title': '',
            'contact': '',
            'note': '',
            'linkedin': '',
            'profile_type': '',
            'status': '',
            'decision_maker': '',
            'dm_title': '',
        })()

    data = {
        "prospect": _prospect_to_dict(prospect),
        "interaction": {
            "subject": interaction.subject or "",
            "content": interaction.content or "",
        },
    }

    logger.info("Analyzing reply for interaction #%d", interaction_id)
    result = await call_skill_1_analysis("reply_analysis", data, model_override=model_override)
    logger.info("Reply analysis #%d raw result: %s", interaction_id, json.dumps(result, ensure_ascii=False, default=str)[:500])

    if "error" in result:
        logger.error("Reply analysis #%d failed: %s", interaction_id, result.get("error", "unknown"))
        raw_preview = str(result.get("raw", ""))[:300]
        return {"success": False, "error": result.get("error", "Unknown") + (" | raw: " + raw_preview if raw_preview else "")}

    # Save AI analysis back to interaction — handle field name variants + fallback to raw text
    interaction.reply_intent = (
        result.get("replyIntent") or result.get("reply_intent") or
        result.get("intent") or ""
    )
    interaction.sentiment_score = int(
        result.get("sentimentScore") or result.get("sentiment_score") or
        result.get("sentiment") or 0
    )
    interaction.key_signals = json.dumps(
        result.get("keySignals") or result.get("key_signals") or result.get("signals") or [],
        ensure_ascii=False
    )
    interaction.ai_suggested_action = (
        result.get("suggestedNextAction") or result.get("suggested_next_action") or
        result.get("nextAction") or result.get("suggestedNextStep") or ""
    )
    interaction.ai_suggested_channel = (
        result.get("suggestedChannel") or result.get("suggested_channel") or
        result.get("channel") or ""
    )
    interaction.ai_suggested_timing = (
        result.get("suggestedTiming") or result.get("suggested_timing") or
        result.get("timing") or ""
    )
    interaction.ai_draft_suggestion = (
        result.get("draftSuggestion") or result.get("draft_suggestion") or
        result.get("draft") or ""
    )
    signal = apply_reply_signal(db, interaction, prospect)
    if signal.get("intent"):
        result.setdefault("replyIntent", interaction.reply_intent)
        result.setdefault("suggestedNextAction", interaction.ai_suggested_action)
        result["systemSignal"] = signal
        result["is_hot_reply"] = signal["intent"] in ("SAMPLE_ADDRESS", "SAMPLE", "QUOTE_REQUEST", "HOT_LEAD")
        result["cold_seq_paused"] = _count_paused_sequences(db, prospect.id)
    logger.info("Reply analysis #%d saved: intent=%s sent=%s action=%s timing=%s draft=%s",
                interaction_id, interaction.reply_intent, interaction.sentiment_score,
                (interaction.ai_suggested_action or "")[:80],
                (interaction.ai_suggested_timing or "")[:40],
                (interaction.ai_draft_suggestion or "")[:40])
    db.commit()

    return {
        "success": True,
        "interaction_id": interaction_id,
        "result": result,
    }


# ──────────────────────────────────────────────────────
#  POST /api/ai/brainstorm-reply-approaches/{prospect_id}
# ──────────────────────────────────────────────────────

@router.post("/brainstorm-reply-approaches/{prospect_id}")
async def brainstorm_reply_approaches(prospect_id: int, payload: dict = None, db: Session = Depends(get_db)):
    """Analyze full conversation history and suggest 3-4 reply approaches."""
    # Extract model_override
    model_override = None
    if payload and isinstance(payload, dict):
        mo = payload.get("model_override")
        if mo in ("deepseek", "openai", "gemini", "auto"):
            model_override = mo

    prospect = db.query(Prospect).filter(
        Prospect.id == prospect_id, Prospect.is_deleted == 0
    ).first()
    if not prospect:
        raise HTTPException(status_code=404, detail="Prospect not found")

    # Gather full conversation history
    interactions = (
        db.query(Interaction)
        .filter(Interaction.prospect_id == prospect_id)
        .order_by(Interaction.interacted_at.asc())
        .limit(30)
        .all()
    )
    seqs = (
        db.query(Sequence)
        .filter(Sequence.prospect_id == prospect_id)
        .order_by(Sequence.executed_at.asc())
        .limit(20)
        .all()
    )

    history_parts = []
    for s in seqs:
        label = f"[{s.channel}] " + (s.content or "")[:120]
        history_parts.append(f"- OUTBOUND (seq #{s.id}): {label}")
    for i in interactions:
        label = f"[{i.channel}] Subject: {i.subject or '(none)'} | {i.content or ''}"
        label = label[:200]
        history_parts.append(f"- {i.direction.upper()}: {label}")

    history_text = "\n".join(history_parts) if history_parts else "(no history yet)"

    prompt = (
        "You are an export sales AI for {{COMPANY}}.\n\n"
        f"Company: {prospect.company or 'Unknown'}\n"
        f"Country: {prospect.country or 'Unknown'}\n"
        f"Profile: {prospect.profile_type or 'Unknown'}\n"
        f"Status: {prospect.status or 'Unknown'}\n\n"
        "=== FULL CONVERSATION HISTORY ===\n"
        f"{history_text}\n\n"
        + HUMAN_VOICE_RULES + "\n\n"
        + "EMAIL SIGNATURE TO USE:\n"
        + get_signature_for_profile(prospect.profile_type) + "\n\n"
        "=== TASK ===\n"
        "Based on the conversation history above, suggest 3-4 distinct reply approaches.\n"
        "Each approach should have a different angle (e.g. pricing, technical, check-in, value-add).\n"
        "Return ONLY valid JSON in this exact format:\n"
        "{\n"
        '  "approaches": [\n'
        '    {\n'
        '      "label": "Short label (e.g. Product Spec Follow-up)",\n'
        '      "angle": "Why this angle — 1 sentence",\n'
        '      "tone": "warm|technical|formal|human",\n'
        '      "keyPoints": ["point1", "point2"],\n'
        '      "suggestedSubject": "email subject line",\n'
        '      "openingLine": "First sentence of the reply"\n'
        '    }\n'
        '  ]\n'
        "}\n"
        "IMPORTANT: All content in English. Output only JSON, no markdown fences."
    )

    logger.info("Brainstorming reply approaches for prospect #%d", prospect_id)
    try:
        loop = asyncio.get_event_loop()
        model_param = model_override if model_override in ("deepseek", "openai", "gemini") else None
        raw = await call_simple(prompt, model_param, 0.7, 2048)
        result = _parse_json(raw)
        if "error" in result:
            logger.error("Brainstorm parse failed: %s", result.get("error", ""))
            return {"success": False, "error": "AI returned unparseable response", "raw": raw[:500]}
        approaches = result.get("approaches", [])
        if not isinstance(approaches, list) or len(approaches) < 1:
            # fallback: wrap the entire result as one approach
            approaches = [{"label": "Suggested Reply", "angle": str(result), "tone": "warm", "keyPoints": [], "suggestedSubject": "", "openingLine": ""}]
        return {"success": True, "prospect_id": prospect_id, "approaches": approaches, "history_preview": history_text[:800]}
    except Exception as exc:
        logger.exception("Brainstorm failed")
        return {"success": False, "error": str(exc)}


# ──────────────────────────────────────────────────────
#  POST /api/ai/suggest-sequence/{prospect_id}
# ──────────────────────────────────────────────────────

@router.post("/suggest-sequence/{prospect_id}")
async def suggest_sequence(prospect_id: int, payload: dict = None, db: Session = Depends(get_db)):
    """Generate the NEXT step of a nurture sequence for a specific channel.
    payload.channel: 'linkedin' | 'whatsapp' | 'email' (required)
    payload.days_from_now: optional int, overrides the default (step1=0, step2+=3). User-set date takes priority.
    Only generates step 1 (or step N+1). Does NOT delete existing steps — accumulates."""
    channel = (payload or {}).get("channel", "").lower()
    user_days = (payload or {}).get("days_from_now")  # optional user override
    # Extract model_override
    model_override = None
    if payload and isinstance(payload, dict):
        mo = payload.get("model_override")
        if mo in ("deepseek", "openai", "gemini", "auto"):
            model_override = mo
    if channel not in ("linkedin", "whatsapp", "email", "phone"):
        return {"success": False, "error": "channel is required: linkedin, whatsapp, email, or phone"}

    prospect = db.query(Prospect).filter(
        Prospect.id == prospect_id, Prospect.is_deleted == 0
    ).first()
    if not prospect:
        raise HTTPException(status_code=404, detail="Prospect not found")

    intel = db.query(Intelligence).filter(Intelligence.prospect_id == prospect_id).first()

    # 同公司联系人：生成多人开发计划时让 AI 知道目标是谁
    colleagues = db.query(Prospect).filter(
        Prospect.company == prospect.company,
        Prospect.is_deleted == 0,
    ).order_by(Prospect.id.asc()).all()
    people_lines = [
        f"{c.contact or 'Unknown contact'} | {c.title or 'Unknown title'} | {(c.email or '').strip() or 'No email'}"
        for c in colleagues
    ]

    # Determine next step number — append to existing, don't delete
    existing_seqs = db.query(Sequence).filter(
        Sequence.prospect_id == prospect_id, Sequence.channel == channel
    ).order_by(Sequence.step_number.desc()).all()

    last_step_num = existing_seqs[0].step_number if existing_seqs else 0
    next_step_num = last_step_num + 1
    has_pending_on_channel = any(s.status == "pending" for s in existing_seqs)

    profile = prospect.profile_type or "Unknown"
    country = prospect.country or "Unknown"
    company = prospect.company or "Unknown"

    # Build context — same as before
    context_parts = []
    context_parts.append(f"Client: {company} | Country: {country} | Industry: {prospect.industry or 'Unknown'} | Size: {prospect.size or 'Unknown'}")
    context_parts.append(f"Contact: {prospect.contact or 'Unknown'} | Title: {prospect.title or 'Unknown'}")

    if prospect.score_reason:
        context_parts.append(f"AI score analysis: {prospect.score_reason[:500]}")
    if prospect.red_flags:
        context_parts.append(f"Red flags / risks: {prospect.red_flags[:300]}")
    if prospect.ai_score:
        context_parts.append(f"Overall score: {prospect.ai_score}/10, Value tier: {prospect.value_level or 'Unknown'}")

    if prospect.decision_maker:
        context_parts.append(f"Key decision maker: {prospect.decision_maker}, Title: {prospect.dm_title or ''}")
    if people_lines:
        context_parts.append(f"Same-company contacts / decision chain: {'; '.join(people_lines)}")

    if intel:
        if intel.website_key_points:
            context_parts.append(f"Website insights: {intel.website_key_points[:400]}")
        if intel.hiring_signals:
            context_parts.append(f"Hiring signals (reflect company direction): {intel.hiring_signals[:300]}")
        if intel.icebreak_angles:
            context_parts.append(f"Icebreaker angles: {intel.icebreak_angles[:400]}")
        if intel.linkedin_content and channel == "linkedin":
            context_parts.append(f"LinkedIn page content: {intel.linkedin_content[:800]}")

    # Interaction history — CRITICAL for step N+1 context
    interactions_history = db.query(Interaction).filter(
        Interaction.prospect_id == prospect_id
    ).order_by(Interaction.interacted_at.desc()).limit(5).all()
    if interactions_history:
        context_parts.append("Recent interactions:")
        for ix in interactions_history:
            dtag = "[Client→]" if ix.direction == "inbound" else "[Us→]"
            ctx = f"{dtag} {ix.channel}: {(ix.content or ix.subject or '')[:150]}"
            context_parts.append(ctx)

    # Previous steps on THIS channel — feed to AI so it knows what was already said
    if existing_seqs:
        context_parts.append(f"\n=== Steps already executed/generated on this channel ===")
        for s in sorted(existing_seqs, key=lambda x: x.step_number):
            status_tag = "✓" if s.status == "done" else "✗"
            context_parts.append(f"Step {s.step_number} [{s.channel}] {status_tag}: {(s.content or s.subject or '')[:200]}")

    try:
        kb_product = db.query(KnowledgeBase).filter(
            KnowledgeBase.category == "product",
            KnowledgeBase.is_active == 1
        ).first()
        kb_profile_info = db.query(KnowledgeBase).filter(
            KnowledgeBase.title.ilike("%profile%"),
            KnowledgeBase.is_active == 1
        ).first()
        if kb_product:
            context_parts.append(f"Product capabilities: {kb_product.content[:400]}")
        if kb_profile_info:
            context_parts.append(f"Company positioning: {kb_profile_info.content[:400]}")
    except Exception:
        pass

    # Stage-based rhythm: later steps = wider intervals + different value type
    if user_days is not None:
        days_from_now = user_days
    else:
        days_from_now = 0 if (next_step_num == 1 or not has_pending_on_channel) else _stage_interval(next_step_num, channel, prospect.country or "")
    stage_label = _stage_label(next_step_num)

    # ── Channel cooling detection: warn if this channel has consecutive no-reply ──
    channel_warning = None
    if next_step_num > 1:
        # Count consecutive outbound steps on this channel since last inbound
        consecutive_no_reply = 0
        for ix in reversed(interactions_history):
            if ix.direction == "inbound":
                break
            if ix.channel == channel:
                consecutive_no_reply += 1
        if consecutive_no_reply >= 2:
            # Suggest alternative channels
            alt_channels = []
            if channel != "email": alt_channels.append("email")
            if channel != "linkedin": alt_channels.append("linkedin")
            if channel != "whatsapp": alt_channels.append("whatsapp")
            alt_str = ", ".join(alt_channels)
            channel_warning = f"⚠️ This client has had {consecutive_no_reply} consecutive no-reply steps on {channel}; consider switching to {alt_str}. This message is still generated for {channel} — decide yourself whether to adjust."

    intel_section = "\n".join(context_parts)

    prompt = (
        f'You are an export sales strategist at {{COMPANY}}. Before writing, think step by step.\n\n'
        f'BACKGROUND:\n'
        f'Client: {company} | Profile {profile} | Country: {country} | Industry: {prospect.industry or "Unknown"} | Size: {prospect.size or "Unknown"}\n'
        f'Contact: {prospect.contact or "Unknown"} | Title: {prospect.title or "Unknown"}\n\n'
        f'=== CURRENT STAGE ===\n'
        f'Step {next_step_num} on {channel}. Stage: {stage_label}\n'
        f'Days from now until this goes out: {days_from_now} days.\n\n'
        f'{intel_section}\n\n'
        f'=== REASONING PHASE (think step by step, output in the "thinking" field) ===\n'
        f'1. PAIN POINT ANALYSIS: Based on Profile {profile} and this specific company\'s context (industry, size, hiring signals, website), what are their TOP 2 operational pain points? Be specific — don\'t just say "needs our product". Think: are they struggling with supplier consistency? Cost pressure from their buyers? Long lead times from their current region? Custom-spec availability?\n\n'
        f'2. VALUE MATCH: Which specific capability from the customer knowledge base directly solves each pain point? Use concrete facts only (no invented specs). Match THE RIGHT fact to THE RIGHT pain point — don\'t list everything.\n\n'
        f"3. ENTRY ANGLE — Stage Instructions:\n"
        f"Current stage: {stage_label}\n"
        f"If step 1 (Light Touch): Confirm spec feasibility — ask a specific technical question about their specs, do NOT ask about price or budget. If LinkedIn, connection request ≤300 chars.\n"
        f"If step 2 (Process Proof): Share one concrete quality evidence — a real photo, a test report excerpt, a tolerance achievement. Do NOT ask 'are you interested'. Let the evidence speak.\n"
        f"If step 3 (Industry Trust): Share one recent update — new ISO cert, new equipment, an exhibition you attended. Frame it as 'thought you\'d find this useful', not self-promotion.\n"
        f"If step 4 (Sampling Invite): Invite them to send a drawing for a sample run. Say 'custom specs + accuracy report included'. Never say 'free sample' — say 'we\'ll produce to your drawing and include the inspection data'.\n"
        f"If step 5+ (Dormant Maintenance): Do NOT mention products or follow-up. Share one industry news item or technology trend. End with 'no pressure, just sharing'. Keep it under 4 sentences.\n"
        f"CRITICAL: NEVER write 'any update?', 'did you receive?', 'checking in', 'following up', 'just checking', 'reaching out again'. Every message must deliver standalone value — the client should feel they learned something, not that they owe you a reply.\n\n"
        f"Do NOT write any sign-off/signature/company name/email or placeholder at the end (the system automatically appends the real signature).\n\n"
        f"MINDSET (senior export sales principles):\n"
        f"- Silence ≠ rejection. It means hesitation, and the client hasn't seen a must-buy reason yet. Your job is not to wait — it's to help them find that reason.\n"
        f"- 'I'll take a look' means 'I haven't seen why I should buy.' Don't wait. Send cases, data, proof of results others got from your product.\n"
        f"- If the client went silent after several steps, do NOT chase. They're not ready yet — and your pressure won't change that. Let them go quiet. When they think of you again, you're still there, still professional, still not desperate.\n"
        f"- Price is the threshold. Reliability is the moat. Clients will pay a premium for professionalism and service — especially in precision manufacturing where one bad batch kills trust.\n\n"
        f'4. TONE & STRUCTURE: {channel} requires: '
        + ('LinkedIn — connection request ≤300 chars. Professional friendly, no pitch in step 1. InMail (step 2+): warm, reference their role, offer value in 2-3 short paragraphs.' if channel == 'linkedin' else
           'WhatsApp — casual warm, under 4 sentences. Introduce yourself, one value point, ask a soft question.' if channel == 'whatsapp' else
        'Email — 5-part structure: ①Open with their context or one direct technical question (never a self-introduction) ②One-line company positioning only if needed: category + origin + manufacturing attribute (e.g. "China-based precision component manufacturer"); no founding year, area, slogans ③Our value that matters to THEM ④Low-friction CTA ⑤Brief close. Formal for EU, warm for Middle East/Asia.')
        + f"\nCountry-specific: {country} — {'European — be direct, fact-based, no flattery. Short sentences.' if country and country.upper() in ('DE','AT','CH','NL','DK','SE','NO','FI','UK','FR','BE','IT','ES') else 'Middle East/Asia — warm relationship tone, mention certifications, be slightly more personal.' if country and country.upper() in ('AE','SA','TR','IN','PK','IR','EG','QA','KW','OM','ID','MY','VN','TH') else 'Adapt to local business culture.'}\n\n"
        f'{HUMAN_VOICE_RULES}\n\n'
        f'EMAIL SIGNATURE TO USE:\n{get_signature_for_profile(prospect.profile_type)}\n\n'
        f'OUTPUT FORMAT — Return ONLY a single JSON object (no markdown, no extra text):\n'
        '{{'
        '"thinking":"[Your 4-step reasoning in English: pain_point → value_match → entry_angle → tone_choice. Keep under 300 chars.]",'
        '"step_number":' + str(next_step_num) + ','
        '"channel":"' + channel + '",'
        '"subject":"...",'
        '"content":"...",'
        '"tone":"formal|warm|casual",'
        '"to_email":"(if this step should go to another contact in the same company, put their exact email; otherwise leave empty)",'
        '"days_from_now":' + str(days_from_now) + ','
        '"strategy":"one-line English summary of the entry angle"'
        '}}'
    )

    try:
        loop = asyncio.get_event_loop()
        model_param = model_override if model_override in ("deepseek", "openai", "gemini") else "deepseek"
        raw = await call_simple(prompt, model_param, 0.7, 4096)
        import traceback as _tb
        # If AI call itself failed (returned empty or error string)
        if not raw or not isinstance(raw, str) or raw.strip().startswith("Error") or len(raw.strip()) < 10:
            logger.error("AI call returned invalid response: %s", repr(raw)[:200])
            return {"success": False, "error": f"AI call failed — empty or error response", "raw": str(raw)[:300]}
        logger.info("Sequence raw AI response (first 300): %s", (raw or "")[:300])
        clean = raw.strip()
        # Strip markdown code fences
        clean = re.sub(r"```(?:json)?\s*", "", clean).replace("```", "").strip()
        # Find the outermost { ... } that contains "step_number"
        step = None
        # Strategy: find "step_number" then match the enclosing braces
        sn_pos = clean.find('"step_number"')
        if sn_pos >= 0:
            # Find the opening brace before step_number
            brace_start = clean.rfind('{', 0, sn_pos)
            if brace_start >= 0:
                # Count braces from brace_start to find the matching closing brace
                depth = 0
                brace_end = -1
                for i in range(brace_start, len(clean)):
                    if clean[i] == '{':
                        depth += 1
                    elif clean[i] == '}':
                        depth -= 1
                        if depth == 0:
                            brace_end = i
                            break
                if brace_end >= 0:
                    json_str = clean[brace_start:brace_end + 1]
                    try:
                        step = json.loads(json_str)
                    except json.JSONDecodeError as je:
                        logger.warning("JSON parse failed at pos %d: %s", je.pos, json_str[max(0,je.pos-50):je.pos+50])
                        step = None
        if step is None:
            # Fallback: try each { ... } block from the end
            for m in reversed(list(re.finditer(r"\{[^{}]*\}", clean))):
                try:
                    step = json.loads(m.group())
                    if isinstance(step, dict) and "step_number" in step:
                        break
                    step = None
                except json.JSONDecodeError:
                    pass
        if step is None or not isinstance(step, dict):
            return {"success": False, "error": "AI returned non-object", "raw": raw[:500], "clean": clean[:500]}

        from datetime import date, timedelta
        today = date.today()
        days = int(step.get("days_from_now", days_from_now))
        scheduled = today + timedelta(days=max(days, 0))
        while scheduled.weekday() >= 5:
            scheduled += timedelta(days=1)

        generated_content = str(step.get("content", ""))
        if channel == "email":
            generated_content = _ensure_email_signature(generated_content, prospect.profile_type)

        seq = Sequence(
            prospect_id=prospect_id,
            step_number=next_step_num,
            channel=str(step.get("channel", channel)),
            scheduled_date=scheduled.isoformat(),
            scheduled_time="09:00",
            content=generated_content,
            subject=str(step.get("subject", "")),
            tone=str(step.get("tone", "warm")),
            to_email=str(step.get("to_email", "") or ""),
        )
        db.add(seq)
        db.commit()
        db.refresh(seq)
        logger.info("Generated step %d for #%d on channel %s", seq.step_number, prospect_id, channel)

        return {
            "success": True,
            "prospect_id": prospect_id,
            "step_number": seq.step_number,
            "channel": seq.channel,
            "scheduled_date": seq.scheduled_date,
            "subject": seq.subject,
            "to_email": seq.to_email,
            "content_preview": (seq.content or "")[:200],
            "thinking": step.get("thinking", ""),
            "strategy": step.get("strategy", ""),
            "warning": channel_warning,
        }

    except Exception as exc:
        logger.exception("Sequence generation failed for prospect #%d", prospect_id)
        return {"success": False, "error": str(exc), "details": getattr(exc, 'doc', str(exc))}


# ──────────────────────────────────────────────────────
#  POST /api/ai/suggest-company-sequence/{prospect_id}
# ──────────────────────────────────────────────────────

@router.post("/suggest-company-sequence/{prospect_id}")
async def suggest_company_sequence(prospect_id: int, payload: dict = None, db: Session = Depends(get_db)):
    """Generate a company-level multi-contact outreach plan: order contacts by decision chain.
    Steps are attached to the company main record; each step uses to_email to target one contact."""
    model_override = None
    if payload and isinstance(payload, dict):
        mo = payload.get("model_override")
        if mo in ("deepseek", "openai", "gemini", "auto"):
            model_override = mo

    prospect = db.query(Prospect).filter(
        Prospect.id == prospect_id, Prospect.is_deleted == 0
    ).first()
    if not prospect:
        raise HTTPException(status_code=404, detail="Prospect not found")

    main = _resolve_company_main_prospect(db, prospect.company)
    if main and main.id != prospect_id:
        logger.info("Company plan redirected from #%d to main #%d", prospect_id, main.id)
        prospect = main
        prospect_id = main.id

    colleagues = db.query(Prospect).filter(
        Prospect.company == prospect.company,
        Prospect.is_deleted == 0,
    ).order_by(Prospect.id.asc()).all()
    if not colleagues:
        return {"success": False, "error": "No available contacts for this company"}

    # 公司级计划是“替换式”：重新生成前清掉旧的公司计划，避免重复堆积
    company_ids = [p.id for p in colleagues]
    old_company_steps = db.query(Sequence).filter(
        Sequence.prospect_id.in_(company_ids),
        Sequence.is_company_plan == 1,
    ).all()
    for s in old_company_steps:
        db.delete(s)
    db.commit()

    people_lines = []
    for i, c in enumerate(colleagues, 1):
        em = (c.email or "").strip()
        people_lines.append(
            f"{i}. {c.contact or 'Unknown contact'} | {c.title or 'Unknown title'} | {em or 'No email'}"
        )

    intel = db.query(Intelligence).filter(Intelligence.prospect_id == prospect_id).first()
    context_parts = [
        f"Company: {prospect.company} | Country: {prospect.country or 'Unknown'} | "
        f"Industry: {prospect.industry or 'Unknown'} | Size: {prospect.size or 'Unknown'}"
    ]
    context_parts.append("Same-company contact list:\n" + "\n".join(people_lines))
    if prospect.score_reason:
        context_parts.append(f"AI score analysis: {prospect.score_reason[:500]}")
    if prospect.red_flags:
        context_parts.append(f"Red flags / risks: {prospect.red_flags[:300]}")
    if intel and intel.website_key_points:
        context_parts.append(f"Website insights: {intel.website_key_points[:400]}")

    existing_seqs = db.query(Sequence).filter(
        Sequence.prospect_id == prospect_id
    ).order_by(Sequence.step_number.asc()).all()
    if existing_seqs:
        context_parts.append("Existing outreach-plan steps:")
        for s in existing_seqs:
            target = s.to_email or prospect.email or "this client"
            context_parts.append(
                f"- Step {s.step_number} [{s.channel}] -> {target}: "
                f"{(s.subject or s.content or '')[:120]}"
            )

    prompt = (
        f"You are an export sales strategist at {{COMPANY}}.\n"
        f"Create a complete COMPANY-LEVEL cold outreach plan for this prospect.\n\n"
        f"CONTEXT:\n" + "\n".join(context_parts) + "\n\n"
        f"RULES:\n"
        f"1. Order steps by realistic decision chain: first light-touch to the business/commercial "
        f"person with a personal email, then backup person, then purchasing/general mailbox, "
        f"then the top decision maker as long-term (phone/LinkedIn if no email).\n"
        f"2. Each step must target ONE person/address from the list above; set to_email to their "
        f"EXACT email (or empty if they have no email, and use channel phone or linkedin).\n"
        f"3. Email content in English, concise and professional, 3-5 short paragraphs; "
        f"no fluff, no 'any update'. NEVER open with self-introduction "
        f"(e.g. 'I am <name> from', 'We manufacture', 'Our company').\n"
        f"4. Return ONLY a JSON array (no markdown). Each item: "
        f'{{"step_number":1,"target_name":"...","to_email":"...","channel":"email|phone|linkedin",'
        f'"subject":"...","content":"...","tone":"formal|warm","days_from_now":0,'
        f'"strategy":"one-line summary"}}.\n'
        f"5. Generate 3-6 steps total with a natural cadence: first touch day 0, short follow-up "
        f"day 3, email day 5, phone day 7, soft social/linkedin touch day 14; adapt to the "
        f"available contacts and channels but never skip a person already contacted.\n"
        f"6. Escalation must move STRICTLY FORWARD through distinct people/channels. Never repeat "
        f"a person already contacted. The final step, if needed, is a phone call to the highest-level "
        f"person not yet reached by another channel; if everyone has been tried, end with a "
        f"'pause and wait' step instead of repeating anyone.\n"
        f"7. Only the first step uses days_from_now=0; later steps use the cadence above and "
        f"target a DIFFERENT person or channel.\n"
    )

    try:
        loop = asyncio.get_event_loop()
        model_param = model_override if model_override in ("deepseek", "openai", "gemini") else "deepseek"
        raw = await call_simple(prompt, model_param, 0.7, 8192)
        if not raw or not isinstance(raw, str) or raw.strip().startswith("Error") or len(raw.strip()) < 10:
            return {"success": False, "error": "AI call failed — empty or error response", "raw": str(raw)[:300]}
        clean = raw.strip()
        clean = re.sub(r"```(?:json)?\s*", "", clean).replace("```", "").strip()
        start = clean.find("[")
        end = clean.rfind("]")
        if start < 0 or end <= start:
            return {"success": False, "error": "AI did not return a JSON array", "raw": raw[:500]}
        steps = json.loads(clean[start:end + 1])
        if not isinstance(steps, list) or not steps:
            return {"success": False, "error": "AI returned empty plan", "raw": raw[:500]}

        # 服务端强制校验：同一联系人只能出现一次；无目标的通用邮件/领英步骤跳过；
        # 电话步骤最多保留一条，防止计划绕回开头或重复轰炸
        seen_people = set()
        clean_steps = []
        phone_count = 0
        for item in steps:
            if not isinstance(item, dict):
                continue
            em = str(item.get("to_email") or "").strip().lower()
            name = str(item.get("target_name") or "").strip()
            ch = str(item.get("channel") or "email").lower()
            keys = []
            if em:
                keys.append(em)
            if name:
                keys.append(name.lower())
            if not keys:
                if ch == "phone":
                    phone_count += 1
                    if phone_count > 1:
                        continue
                else:
                    continue
                clean_steps.append(item)
                continue
            if any(k in seen_people for k in keys):
                continue
            for k in keys:
                seen_people.add(k)
            clean_steps.append(item)
        if not clean_steps:
            return {"success": False, "error": "AI plan has no usable targets", "raw": raw[:500]}
        steps = clean_steps

        from datetime import date, timedelta
        created = []
        for idx, item in enumerate(steps, 1):
            channel = str(item.get("channel", "email")).lower()
            if channel not in ("email", "phone", "linkedin", "whatsapp"):
                channel = "email"
            days = int(item.get("days_from_now", idx - 1) or idx - 1)
            scheduled = date.today() + timedelta(days=max(days, 0))
            while scheduled.weekday() >= 5:
                scheduled += timedelta(days=1)
            content = str(item.get("content", "") or "")
            if channel == "email":
                content = _ensure_email_signature(content, prospect.profile_type)
            seq = Sequence(
                prospect_id=prospect_id,
                step_number=idx,
                channel=channel,
                scheduled_date=scheduled.isoformat() if idx == 1 else None,
                scheduled_time="09:00",
                content=content,
                subject=str(item.get("subject", "") or ""),
                tone=str(item.get("tone", "formal")),
                to_email=str(item.get("to_email", "") or ""),
                is_company_plan=1,
            )
            db.add(seq)
            created.append(seq)
        db.commit()
        for s in created:
            db.refresh(s)
        if created:
            prospect.next_follow_date = created[0].scheduled_date
            prospect.reminder_note = "[Plan] Step 1 pending send"
            db.commit()
        return {
            "success": True,
            "prospect_id": prospect_id,
            "main_prospect_id": prospect_id,
            "count": len(created),
            "created": [
                {
                    "id": s.id,
                    "step_number": s.step_number,
                    "channel": s.channel,
                    "subject": s.subject,
                    "to_email": s.to_email,
                    "scheduled_date": s.scheduled_date,
                }
                for s in sorted(created, key=lambda x: x.step_number)
            ],
        }
    except Exception as exc:
        logger.exception("Company sequence generation failed for prospect #%d", prospect_id)
        return {"success": False, "error": str(exc)}


# ──────────────────────────────────────────────────────
#  POST /api/ai/analyze-decision-chain/{prospect_id}
# ──────────────────────────────────────────────────────

@router.post("/analyze-decision-chain/{prospect_id}")
async def analyze_decision_chain(prospect_id: int, payload: dict = None, db: Session = Depends(get_db)):
    """When a company has several contacts and the decision maker is unknown, use the LLM to analyze the decision chain and outreach order."""
    model_override = None
    if payload and isinstance(payload, dict):
        mo = payload.get("model_override")
        if mo in ("deepseek", "openai", "gemini", "auto"):
            model_override = mo

    prospect = db.query(Prospect).filter(
        Prospect.id == prospect_id, Prospect.is_deleted == 0
    ).first()
    if not prospect:
        raise HTTPException(status_code=404, detail="Prospect not found")

    main = _resolve_company_main_prospect(db, prospect.company)
    if main and main.id != prospect_id:
        logger.info("Decision chain analysis redirected from #%d to main #%d", prospect_id, main.id)
        prospect = main
        prospect_id = main.id

    colleagues = db.query(Prospect).filter(
        Prospect.company == prospect.company,
        Prospect.is_deleted == 0,
    ).order_by(Prospect.id.asc()).all()
    if len(colleagues) < 1:
        return {"success": False, "error": "This company has no contacts yet — add contacts before analyzing"}

    contact_lines = []
    for c in colleagues:
        em = (c.email or "").strip()
        li = (c.linkedin or "").strip()
        contact_lines.append(
            f"- #{c.id} {c.contact or 'Unknown contact'} | Title: {c.title or 'Unknown'} | "
            f"Email: {em or 'None'} | LinkedIn: {li or 'None'} | Score: {c.ai_score or '-'} {c.value_level or ''}"
        )

    intel = db.query(Intelligence).filter(Intelligence.prospect_id == prospect_id).first()
    intel_parts = []
    if prospect.score_reason:
        intel_parts.append(f"AI score analysis: {prospect.score_reason[:500]}")
    if intel and intel.website_key_points:
        intel_parts.append(f"Website insights: {intel.website_key_points[:400]}")
    if intel and intel.hiring_signals:
        intel_parts.append(f"Hiring signals: {intel.hiring_signals[:300]}")

    prompt = (
        f"You are a B2B export sales strategist at {{COMPANY}}. The goal is cold development of "
        f"a new OEM customer. We have several contacts at the same company but do NOT know who is "
        f"the real decision maker.\n\n"
        f"COMPANY:\nCompany: {prospect.company} | Country: {prospect.country or 'Unknown'} | "
        f"Industry: {prospect.industry or 'Unknown'} | Size: {prospect.size or 'Unknown'}\n\n"
        f"CONTACTS:\n" + "\n".join(contact_lines) + "\n\n"
        f"INTELLIGENCE:\n" + ("\n".join(intel_parts) if intel_parts else "No additional intelligence") + "\n\n"
        f"ANALYZE (think step by step, write the reasoning in English inside 'thinking'):\n"
        f"1. For each contact, infer their role and whether they can make or influence the buying "
        f"decision (owner/GM > department head > commercial/assistant > generic mailbox).\n"
        f"2. Who is the most likely decision maker? Who should be contacted FIRST (often the "
        f"commercial/business person who can route internally), who is backup, who is final escalation?\n"
        f"3. Explain the escalation logic clearly: each step must move to a DIFFERENT person/channel, "
        f"never go back to someone already contacted.\n\n"
        f"OUTPUT ONLY JSON (no markdown):\n"
        f'{{"thinking":"...","summary":"brief English conclusion: who decides and who to contact first","decision_maker_guess":"Name",'
        f'"decision_maker_reason":"...","contact_order":[{{"name":"...","prospect_id":123,'
        f'"role":"executor/decision-maker/purchasing/general mailbox","channel":"email|linkedin|phone","email":"...or empty",'
        f'"reason":"..."}}],"escalation_logic":"...","risk":"..."}}'
    )

    try:
        loop = asyncio.get_event_loop()
        model_param = model_override if model_override in ("deepseek", "openai", "gemini") else "deepseek"
        raw = await call_simple(prompt, model_param, 0.6, 4096)
        if not raw or not isinstance(raw, str) or raw.strip().startswith("Error") or len(raw.strip()) < 10:
            return {"success": False, "error": "AI call failed — empty or error response", "raw": str(raw)[:300]}
        clean = raw.strip()
        clean = re.sub(r"```(?:json)?\s*", "", clean).replace("```", "").strip()
        parsed = _parse_json(clean)
        if not parsed or not isinstance(parsed, dict):
            return {"success": False, "error": "AI returned non-object", "raw": raw[:500]}
        return {"success": True, "prospect_id": prospect_id, "analysis": parsed}
    except Exception as exc:
        logger.exception("Decision chain analysis failed for prospect #%d", prospect_id)
        return {"success": False, "error": str(exc)}


# ──────────────────────────────────────────────────────
#  POST /api/ai/generate-company-plan-from-analysis/{prospect_id}
# ──────────────────────────────────────────────────────

@router.post("/generate-company-plan-from-analysis/{prospect_id}")
async def generate_company_plan_from_analysis(prospect_id: int, payload: dict = None, db: Session = Depends(get_db)):
    """Strictly generate the company plan from the AI decision-chain analysis (contact_order), auto-deduplicated, no going back."""
    prospect = db.query(Prospect).filter(
        Prospect.id == prospect_id, Prospect.is_deleted == 0
    ).first()
    if not prospect:
        raise HTTPException(status_code=404, detail="Prospect not found")

    main = _resolve_company_main_prospect(db, prospect.company)
    if main and main.id != prospect_id:
        logger.info("Company plan generation redirected from #%d to main #%d", prospect_id, main.id)
        prospect = main
        prospect_id = main.id

    order = ((payload or {}).get("contact_order") or [])
    if not isinstance(order, list) or not order:
        return {"success": False, "error": "Missing decision-chain analysis result contact_order"}

    # 公司计划是替换式：生成前清掉旧计划
    company_ids = [p.id for p in db.query(Prospect).filter(
        Prospect.company == prospect.company,
        Prospect.is_deleted == 0,
    ).all()]
    old = db.query(Sequence).filter(
        Sequence.prospect_id.in_(company_ids),
        Sequence.is_company_plan == 1,
    ).all()
    for s in old:
        db.delete(s)
    db.commit()

    from datetime import date, timedelta
    seen = set()
    email_candidates = []
    non_email_candidates = []
    for item in order:
        if not isinstance(item, dict):
            continue
        em = str(item.get("email") or "").strip()
        name = str(item.get("name") or "").strip()
        pid = item.get("prospect_id")
        keys = []
        if em:
            keys.append(em.lower())
        if pid:
            keys.append("pid:" + str(pid))
        if name:
            keys.append(name)
        if not keys or any(k in seen for k in keys):
            continue
        for k in keys:
            seen.add(k)
        channel = str(item.get("channel") or "").lower()
        if channel not in ("email", "linkedin", "phone", "whatsapp"):
            channel = "email"
        entry = {"email": em, "name": name, "pid": pid, "channel": channel}
        if em:
            email_candidates.append(entry)
        else:
            non_email_candidates.append(entry)

    # 标准触达：最多 3 封邮件 + 1 步升级（领英/电话）
    if not email_candidates and non_email_candidates:
        email_candidates = non_email_candidates[:1]
        non_email_candidates = non_email_candidates[1:]
    plan_entries = email_candidates[:3]
    if non_email_candidates:
        plan_entries.append(non_email_candidates[0])

    created = []
    for idx, entry in enumerate(plan_entries, 1):
        em = entry["email"]
        name = entry["name"]
        channel = entry["channel"]
        if em and channel != "email":
            channel = "email"  # 有邮箱优先发邮件，凑足三封触达
        if channel == "email" and not em:
            channel = "linkedin"

        days = (idx - 1) * 4
        d = date.today() + timedelta(days=days)
        while d.weekday() >= 5:
            d += timedelta(days=1)

        if channel == "email":
            subject = f"Supply options for {prospect.company}?"
            greeting = f"Hi {name}," if name and name != "Unknown contact" else "Hi there,"
            content = (
                f"{greeting}\n\n"
                f"In your production programs, does batch-to-batch consistency of incoming "
                f"components ever cause extra rework or delays?\n\n"
                f"We are a component manufacturer that holds tight tolerances across every "
                f"production batch. Happy to send our spec sheet if useful.\n\n"
            )
            content = _ensure_email_signature(content, prospect.profile_type)
        elif channel == "linkedin":
            subject = "Introduction - our manufacturing capabilities"
            content = (
                f"LinkedIn to {name or 'contact'}: introduce our company as a precision component manufacturer; "
                f"ask if {prospect.company} is open to reviewing a new supplier for its production programs."
            )
        elif channel == "phone":
            subject = ""
            content = (
                f"Phone {name or prospect.company}: mention we already contacted them by email/LinkedIn, "
                f"and ask for 5 minutes to confirm whether a component supply partnership is worth exploring."
            )
        else:
            subject = ""
            content = f"{channel} {name or ''}: introduce our precision component manufacturing capabilities and invite an evaluation."

        seq = Sequence(
            prospect_id=prospect_id,
            step_number=idx,
            channel=channel,
            scheduled_date=d.isoformat() if idx == 1 else None,
            scheduled_time="09:00",
            content=content,
            subject=subject,
            tone="formal",
            to_email=em,
            is_company_plan=1,
        )
        db.add(seq)
        created.append(seq)

    if not created:
        return {"success": False, "error": "The analysis result contains no usable contacts"}
    db.commit()
    for s in created:
        db.refresh(s)
    if created:
        prospect.next_follow_date = created[0].scheduled_date
        prospect.reminder_note = "[Plan] Step 1 pending send"
        db.commit()
    return {
        "success": True,
        "prospect_id": prospect_id,
        "main_prospect_id": prospect_id,
        "count": len(created),
        "created": [
            {
                "id": s.id,
                "step_number": s.step_number,
                "channel": s.channel,
                "to_email": s.to_email,
                "scheduled_date": s.scheduled_date,
            }
            for s in sorted(created, key=lambda x: x.step_number)
        ],
    }


# ──────────────────────────────────────────────────────
#  POST /api/ai/generate-proposal/{prospect_id}
# ──────────────────────────────────────────────────────

@router.post("/generate-proposal/{prospect_id}")
async def generate_proposal(prospect_id: int, payload: dict = None, db: Session = Depends(get_db)):
    """Generate a structured cooperation proposal — not just a price,
    but a full solution-style quotation with specs, packaging, lead time, sample policy,
    payment terms, selling points, and channel fit.
    """
    prospect = db.query(Prospect).filter(
        Prospect.id == prospect_id, Prospect.is_deleted == 0
    ).first()
    if not prospect:
        raise HTTPException(status_code=404, detail="Prospect not found")

    intel = db.query(Intelligence).filter(Intelligence.prospect_id == prospect_id).first()

    # Pull product knowledge from DB
    product_context = ""
    try:
        from models import KnowledgeBase
        entries = db.query(KnowledgeBase).filter(
            KnowledgeBase.is_active == 1,
            KnowledgeBase.category == "product",
        ).all()
        if entries:
            product_context = "\n\n".join([f"## {e.title}\n{e.content}" for e in entries])
    except Exception:
        pass

    # Gather recent interactions for context
    interactions = (
        db.query(Interaction)
        .filter(Interaction.prospect_id == prospect_id)
        .order_by(Interaction.interacted_at.desc())
        .limit(10)
        .all()
    )
    conv_context = ""
    if interactions:
        conv_parts = []
        for ix in interactions:
            dtag = "[Client]" if ix.direction == "inbound" else "[Us]"
            conv_parts.append(f"{dtag} {ix.channel}: {(ix.content or ix.subject or '')[:200]}")
        conv_context = "\n".join(reversed(conv_parts))

    # Client-specific context from payload
    spec_note = (payload or {}).get("spec_note", "")
    target_price = (payload or {}).get("target_price", "")
    # Extract model_override
    model_override = None
    if payload and isinstance(payload, dict):
        mo = payload.get("model_override")
        if mo in ("deepseek", "openai", "gemini", "auto"):
            model_override = mo

    prompt = f"""You are an export sales specialist for {{COMPANY}}.

## CLIENT PROFILE
Company: {prospect.company or 'N/A'}
Country: {prospect.country or 'N/A'}
Profile: {prospect.profile_type or 'Unknown'}
Contact: {prospect.contact or prospect.decision_maker or 'N/A'}

## PRODUCT KNOWLEDGE
{product_context[:3000] or '{{COMPANY}}: no product knowledge entered yet — use your general manufacturing knowledge and stay generic.'}

## CONVERSATION CONTEXT
{conv_context or 'New client — no prior interactions.'}

## CUSTOM NOTES
{spec_note or 'No special requirements noted.'}
Target price indication: {target_price or 'Not specified — suggest based on typical pricing.'}

{HUMAN_VOICE_RULES}

EMAIL SIGNATURE TO USE:
{get_signature_for_profile(prospect.profile_type)}

## TASK
Generate a complete structured cooperation proposal. This is NOT just a price quote — it must include all 8 sections below.

Return ONLY valid JSON:
{{
  "subject": "Proposal: {{COMPANY}} Precision Products for {prospect.company or 'Your Company'}",
  "proposal_title": "Cooperation Proposal",
  "sections": {{
    "1_specs": "Product specifications — dimensions, tolerances, materials, finish, coatings. Be specific with numbers.",
    "2_packaging": "Packaging details — individual wrapping, tray quantity, outer carton, protection level.",
    "3_lead_time": "Lead time breakdown — stock items, sampling batch, production batch. Include realistic ranges.",
    "4_sample_policy": "Sample policy — free samples or paid, quantity limit, shipping terms, evaluation period.",
    "5_payment_terms": "Payment terms — T/T, L/C, deposit %, balance timing. Standard and negotiable options.",
    "6_key_selling_points": "3-5 selling points specific to this client's profile and country. Why choose us over competitors.",
    "7_channel_fit": "How this product fits their market channel — distributor, OEM assembly, direct brand, repair network.",
    "8_next_step": "Clear, single next step. Call to schedule DFM review, send formal quotation after drawing review, etc."
  }},
  "total_estimated_value": "Estimated order value range in EUR (e.g. €5,000-15,000 per batch)",
  "notes": "Any caveats, recommendations, or things to confirm with client before proceeding."
}}

CRITICAL: All section content must be in English (export sales language). Subject line in English. Output only JSON.
"""

    logger.info("Generating proposal for prospect #%d: %s", prospect_id, prospect.company)
    try:
        loop = asyncio.get_event_loop()
        model_param = model_override if model_override in ("deepseek", "openai", "gemini") else "deepseek"
        raw = await call_simple(prompt, model_param, 0.7, 4096)
        result = _parse_json(raw)
        if "error" in result:
            logger.error("Proposal parse failed: %s", result.get("error", ""))
            return {"success": False, "error": "AI returned unparseable response", "raw": raw[:500]}
        logger.info("Proposal generated for #%d: sections=%s", prospect_id, list(result.get("sections", {}).keys()))
        return {"success": True, "prospect_id": prospect_id, "proposal": result}
    except Exception as exc:
        logger.exception("Proposal generation failed")
        return {"success": False, "error": str(exc)}


# ──────────────────────────────────────────────────────
#  Model switcher endpoints
# ──────────────────────────────────────────────────────

@router.get("/model")
async def get_model():
    """Get the currently active AI model."""
    try:
        from services.openai_service import has_openai_config
        openai_configured = has_openai_config()
    except Exception:
        openai_configured = False
    return {
        "success": True,
        "active_model": get_active_model(),
        "effective_default": choose_model("simple"),
        "openai_configured": openai_configured,
    }


@router.post("/model")
async def switch_model(payload: dict):
    """Switch AI model mode. payload: {"model": "auto" | "deepseek" | "openai" | "gemini"}"""
    model = payload.get("model", "").strip().lower()
    ok = set_active_model(model)
    if ok:
        return {"success": True, "active_model": model, "effective_default": choose_model("simple")}
    return {"success": False, "error": f"Invalid model '{model}'. Use auto, deepseek, openai, or gemini."}


# ──────────────────────────────────────────────────────
#  POST /api/ai/run-followup-engine
# ──────────────────────────────────────────────────────

@router.post("/followup/{prospect_id}")
async def smart_followup_single(prospect_id: int, db: Session = Depends(get_db)):
    """Single-client smart followup: analyse interaction history, draft email, queue it."""
    from datetime import date as _date
    from services.followup_engine import _build_context, _ai_draft, _get_next_business_time
    from models import EmailQueue as _EQ, Interaction as _I, Intelligence as _Intel, Sequence as _Seq

    p = db.query(Prospect).filter(Prospect.id == prospect_id, Prospect.is_deleted == 0).first()
    if not p:
        raise HTTPException(status_code=404, detail="Prospect not found")
    if not (p.email or p.dm_email):
        return {"success": False, "error": "Client has no email — cannot generate a follow-up email"}

    ints = db.query(_I).filter(_I.prospect_id == p.id).order_by(_I.interacted_at.asc()).all()
    intel = db.query(_Intel).filter(_Intel.prospect_id == p.id).first()

    # Reason
    from services.followup_engine import _last_outbound_date, _last_inbound_date, _days_since, _count_outbound_since_last_inbound
    last_out = _last_outbound_date(ints)
    last_in = _last_inbound_date(ints)
    if last_out and not last_in:
        days = _days_since(last_out)
        out_count = _count_outbound_since_last_inbound(ints)
        reason = f"Follow-up #{out_count+1} (no reply in {days} days)"
    elif last_in and last_out and last_in > last_out:
        reason = f"Client replied on {last_in.strftime('%m/%d')} — needs a response"
    else:
        reason = "Regular follow-up"

    ctx = _build_context(p, ints, intel)
    draft = _ai_draft(ctx, reason, p)

    if not draft or not draft.get("body"):
        return {"success": False, "error": "AI failed to produce valid content — please retry"}

    subject = draft.get("subject", f"Follow-up — {p.company or 'Check-in'}")
    suggested_date = draft.get("suggested_date", "")

    # ── Create Sequence step in 开发计划 FIRST (visible in drawer, editable) ──
    last_seq = db.query(_Seq).filter(_Seq.prospect_id == p.id).order_by(_Seq.step_number.desc()).first()
    next_step = (last_seq.step_number + 1) if last_seq else 1
    new_seq = _Seq(
        prospect_id=p.id,
        step_number=next_step,
        channel="email",
        scheduled_date=suggested_date or _date.today().isoformat(),
        status="pending",
        subject=f"[Smart follow-up] {subject[:120]}",
        content=draft["body"],
    )
    db.add(new_seq)
    db.flush()

    # ── Create EmailQueue DRAFT (not pending — user reviews in 开发计划 first) ──
    eq = _EQ(
        prospect_id=p.id,
        to_email=p.email or p.dm_email or "",
        subject=f"[Auto] " + (f"[Suggested {suggested_date}] " if suggested_date else "") + subject[:140],
        body=draft["body"],
        status="draft",
        scheduled_at=_get_next_business_time(p),
        daily_send_date=_date.today().isoformat(),
        sequence_id=new_seq.id,
    )
    db.add(eq)
    db.commit()
    db.refresh(eq)
    db.refresh(new_seq)

    return {
        "success": True,
        "queue_id": eq.id,
        "sequence_id": new_seq.id,
        "subject": eq.subject,
        "suggested_date": suggested_date,
        "body": draft["body"],
        "status": "draft",
        "body_preview": eq.body[:200],
    }


@router.post("/followup-batch-preview")
async def followup_batch_preview(db: Session = Depends(get_db)):
    """Batch scan: return a list of who needs followup WITHOUT drafting anything."""
    from models import Interaction as _I, Intelligence as _Intel, EmailQueue as _EQ
    from services.followup_engine import _last_outbound_date, _last_inbound_date, _days_since, _count_outbound_since_last_inbound, NO_REPLY_DAYS

    active = db.query(Prospect).filter(
        Prospect.is_deleted == 0,
        Prospect.profile_type != "EXCLUDE",
        Prospect.status.in_(["New", "Following up", "Replied"]),
    ).all()

    preview = []
    for p in active:
        if not (p.email or p.dm_email):
            continue
        existing = db.query(_EQ).filter(_EQ.prospect_id == p.id, _EQ.status == "pending").first()
        if existing:
            continue

        ints = db.query(_I).filter(_I.prospect_id == p.id).order_by(_I.interacted_at.asc()).all()
        last_out = _last_outbound_date(ints)
        last_in = _last_inbound_date(ints)

        if last_out and not last_in:
            days = _days_since(last_out)
            out_count = _count_outbound_since_last_inbound(ints)
            if days >= NO_REPLY_DAYS and out_count < 5:
                preview.append({
                    "prospect_id": p.id,
                    "company": p.company or "",
                    "email": p.email or p.dm_email or "",
                    "reason": f"Follow-up #{out_count+1} (no reply in {days} days)",
                    "last_outbound": str(last_out)[:16] if last_out else "",
                })
        elif last_in and last_out and last_in > last_out:
            days = _days_since(last_in)
            if 0 < days <= 7:
                preview.append({
                    "prospect_id": p.id,
                    "company": p.company or "",
                    "email": p.email or p.dm_email or "",
                    "reason": f"Client replied ({days} days ago) — needs a response",
                    "last_outbound": str(last_out)[:16] if last_out else "",
                    "last_inbound": str(last_in)[:16] if last_in else "",
                })
        elif not last_out and not last_in:
            preview.append({
                "prospect_id": p.id,
                "company": p.company or "",
                "email": p.email or p.dm_email or "",
                "reason": "New client, no interactions yet",
                "last_outbound": "",
            })

    return {"success": True, "total": len(preview), "preview": preview}


@router.post("/followup-batch-generate")
async def followup_batch_generate(payload: dict, db: Session = Depends(get_db)):
    """Generate followup drafts for selected prospects (from batch preview)."""
    prospect_ids = payload.get("prospect_ids", [])
    if not prospect_ids:
        return {"success": False, "error": "No clients selected"}

    from datetime import date as _date
    from services.followup_engine import _build_context, _ai_draft, _get_next_business_time, \
        _last_outbound_date, _last_inbound_date, _days_since, _count_outbound_since_last_inbound
    from models import EmailQueue as _EQ, Interaction as _I, Intelligence as _Intel

    results = []
    for pid in prospect_ids:
        p = db.query(Prospect).filter(Prospect.id == pid).first()
        if not p:
            results.append({"prospect_id": pid, "ok": False, "error": "Not found"})
            continue
        if not (p.email or p.dm_email):
            results.append({"prospect_id": pid, "ok": False, "error": "No email"})
            continue

        existing = db.query(_EQ).filter(_EQ.prospect_id == pid, _EQ.status == "pending").first()
        if existing:
            results.append({"prospect_id": pid, "ok": False, "error": "Pending draft already exists"})
            continue

        ints = db.query(_I).filter(_I.prospect_id == pid).order_by(_I.interacted_at.asc()).all()
        intel = db.query(_Intel).filter(_Intel.prospect_id == pid).first()
        last_out = _last_outbound_date(ints)
        last_in = _last_inbound_date(ints)

        if last_out and not last_in:
            reason = f"Follow-up #{_count_outbound_since_last_inbound(ints)+1} (no reply in {_days_since(last_out)} days)"
        elif last_in and last_out and last_in > last_out:
            reason = "Client replied — needs a response"
        else:
            reason = "Regular follow-up"

        ctx = _build_context(p, ints, intel)
        draft = _ai_draft(ctx, reason, p)

        if not draft or not draft.get("body"):
            results.append({"prospect_id": pid, "ok": False, "error": "AI returned empty"})
            continue

        subject = draft.get("subject", f"Follow-up — {p.company or ''}")
        suggested_date = draft.get("suggested_date", "")
        eq = _EQ(
            prospect_id=pid,
            to_email=p.email or p.dm_email or "",
            subject=f"[Auto] " + (f"[Suggested {suggested_date}] " if suggested_date else "") + subject[:140],
            body=draft["body"],
            status="pending",
            scheduled_at=_get_next_business_time(p),
            daily_send_date=_date.today().isoformat(),
        )
        db.add(eq)
        results.append({"prospect_id": pid, "ok": True, "subject": eq.subject})

    db.commit()
    try:
        log_audit(db, user, "ai_score", None, f"Batch AI scoring: {scored_count}/{len(payload.prospect_ids)} clients scored")
    except Exception:
        pass
    return {"success": True, "results": results}


# ──────────────────────────────────────────────────────
#  POST /api/ai/hiring-scout
#  主动获客：搜招聘 → 提取公司 → AI 过滤 → 自动入库评分
# ──────────────────────────────────────────────────────

@router.post("/hiring-scout")
async def hiring_scout(payload: dict = None, db: Session = Depends(get_db)):
    """Search for optical-industry job postings in target countries,
    extract company names, AI-filter and enrich, auto-import new prospects.

    Optional payload.countries: list of country codes to target (default: all active regions)
    Returns {total_searched, total_imported, by_country: [{country, imported, skipped, errors}]}
    """
    from services.hiring_scout import run_hiring_scout
    countries = (payload or {}).get("countries")
    result = await run_hiring_scout(countries=countries)
    return result


# ──────────────────────────────────────────────────────
#  POST /api/ai/hiring-scout/{prospect_id}
#  单客户招聘搜索 — 搜指定客户公司的最新招聘动态 (by prospect ID)
# ──────────────────────────────────────────────────────

@router.post("/hiring-scout/{prospect_id}")
async def hiring_scout_by_prospect(prospect_id: int, db: Session = Depends(get_db)):
    """Search for a specific customer's job postings. Saves signals to intelligence."""
    from services.hiring_scout import search_company_hiring

    prospect = db.query(Prospect).filter(
        Prospect.id == prospect_id, Prospect.is_deleted == 0
    ).first()
    if not prospect:
        raise HTTPException(status_code=404, detail="Prospect not found")

    result = search_company_hiring(
        company=prospect.company or "",
        country=prospect.country or "",
    )

    # If signals found, save to intelligence
    if result.get("has_signals") and result.get("analysis"):
        intel = db.query(Intelligence).filter(
            Intelligence.prospect_id == prospect_id
        ).first()

        if intel:
            signal_lines = []
            for s in result["analysis"]:
                signal_lines.append(f"• {s.get('role', '?')} [{s.get('confidence', 'medium')}]: {s.get('relevance', '')}")
            new_signals = "\n".join(signal_lines)
            date_header = f"[Hiring scout {datetime.now().strftime('%Y-%m-%d')}]"
            if intel.hiring_signals:
                intel.hiring_signals = (intel.hiring_signals or "") + "\n\n" + date_header + "\n" + new_signals
            else:
                intel.hiring_signals = date_header + "\n" + new_signals
            intel.hiring_content = json.dumps([r.get("title", "") for r in result.get("results", [])])
            db.commit()
            logger.info("Saved hiring signals for #%d (%s): %d signals", prospect_id, prospect.company, len(result["analysis"]))

    return result


@router.post("/suggest-followup/{prospect_id}")
async def suggest_followup(prospect_id: int, db: Session = Depends(get_db)):
    """AI reads all interactions and suggests next follow-up date + reason."""
    prospect = db.query(Prospect).filter(
        Prospect.id == prospect_id, Prospect.is_deleted == 0
    ).first()
    if not prospect:
        raise HTTPException(status_code=404, detail="Prospect not found")

    if (prospect.sales_stage == "sample_pending" or prospect.sample_status == "requested") and prospect.next_follow_date:
        return {
            "success": True,
            "suggested_date": prospect.next_follow_date,
            "reason": prospect.reminder_note or "Sample ready to send — confirm specs first and arrange dispatch.",
            "applied": True,
            "rule_locked": True,
        }

    interactions = (
        db.query(Interaction)
        .filter(Interaction.prospect_id == prospect_id)
        .order_by(Interaction.interacted_at.asc())
        .limit(30)
        .all()
    )

    ctx = [f"Client: {prospect.company or '?'} | {prospect.country or '?'} | Industry: {prospect.industry or '?'}"]
    ctx.append(f"Status: {prospect.status or 'New'} | Profile: {prospect.profile_type or '?'} | Score: {prospect.ai_score or '?'}")
    if prospect.next_follow_date:
        ctx.append(f"Current next_follow_date: {prospect.next_follow_date}")

    # ── 客户情报：让跟进理由有真凭实据 ──
    intel = db.query(Intelligence).filter(Intelligence.prospect_id == prospect_id).first()
    if intel:
        if intel.website_key_points:
            ctx.append(f"Website signals: {intel.website_key_points[:800]}")
        if intel.icebreak_angles:
            ctx.append(f"Icebreaker angles: {intel.icebreak_angles[:800]}")
        if intel.hiring_signals:
            ctx.append(f"Hiring signals: {intel.hiring_signals[:400]}")
        if intel.linkedin_content:
            ctx.append(f"LinkedIn content: {intel.linkedin_content[:500]}")
        if intel.osint_report:
            ctx.append(f"OSINT: {intel.osint_report[:400]}")

    # ── 公司知识库：产品/画像/案例，让理由贴合你自己的业务 ──
    try:
        from services.gemini_service import build_knowledge_context
        kb = build_knowledge_context("followup")
        if kb:
            ctx.append(f"\nCompany knowledge base (products, positioning, ideal profile, cases):\n{kb[:1800]}")
    except Exception:
        pass

    if interactions:
        ctx.append("\nRecent interactions (mixed channels, newest last):")
        for ix in interactions[-20:]:
            dtag = "[IN]" if ix.direction == "inbound" else "[OUT]"
            dstr = str(ix.interacted_at)[:10] if ix.interacted_at else "?"
            ctx.append(f"{dtag} {dstr} via {ix.channel}: {(ix.content or ix.subject or '')[:300]}")
    else:
        ctx.append("No interactions yet — brand new client, first cold outreach.")

    ctx.append(f"\nToday is {datetime.now().strftime('%Y-%m-%d')}.")
    ctx.append("Based on the FULL interaction context above, suggest three things:")
    ctx.append("1. The optimal next follow-up date")
    ctx.append("2. WHICH CHANNEL to use — pick the one most likely to get a response given the context")
    ctx.append("")
    ctx.append("CHANNEL SELECTION RULES (MUST follow):")
    ctx.append("- If previous email got no reply → try LinkedIn or WhatsApp next")
    ctx.append("- If they replied on WhatsApp → stay on WhatsApp")
    ctx.append("- If they said 'call me' or phone number is prominent → use phone")
    ctx.append("- LinkedIn connection accepted but cold → start with LinkedIn message")
    ctx.append("- European clients → email preferred; Middle East/India → WhatsApp preferred")
    ctx.append("- After 2+ no-reply emails → switch channel, don't keep piling emails")
    ctx.append("")
    ctx.append("DATE RULES:")
    ctx.append("- New client (no interactions) → 1-3 days from today")
    ctx.append("- Warm conversation (specs, pricing) → 3-5 days")
    ctx.append("- 'send quote next week' → 7 days")
    ctx.append("- 'will check internally' → 10-14 days")
    ctx.append("- Rejected → 30+ days")
    ctx.append("- No reply on last message → 3-5 days, consider channel switch")
    ctx.append("- Negotiating → 2-4 days")
    ctx.append("\nReply ONLY a JSON object:")
    ctx.append('{"next_follow_date":"YYYY-MM-DD","channel":"email|linkedin|phone|whatsapp","reason":"reason in English"}')
    ctx.append("REASON REQUIREMENTS (important): write a vivid, concrete reason in English, 2-3 sentences.")
    ctx.append("- MUST cite real, verifiable signals: e.g. specific content from recent interactions, website/linkedin/hiring signals above, or sample/deal stage.")
    ctx.append("- MUST tie in this company's own products/strengths from the knowledge base (e.g. certification, specs, case) so it sounds like a real salesperson.")
    ctx.append("- NO generic filler like 'keep following up' or 'build relationship' without evidence.")

    try:
        loop = asyncio.get_event_loop()
        raw = await call_simple("\n".join(ctx), None, 0.3, 256)
        logger.info("AI suggest-followup raw: %s", raw[:300])
        data = _parse_json(raw)
        logger.info("AI suggest-followup parsed: %s", data)
    except Exception as e:
        logger.exception("Suggest followup AI call failed")
        return {"success": True, "suggested_date": None, "reason": "AI call failed: "+str(e)[:80], "applied": False}

    suggested = data.get("next_follow_date")
    reason = data.get("reason", "")
    suggested_channel = data.get("channel", "")
    logger.info("AI suggest-followup parsed: date=%s channel=%s reason=%s", suggested, suggested_channel, reason)

    new_seq_id = None
    if suggested:
        prospect.next_follow_date = suggested
        prospect.last_edited_at = datetime.utcnow()
        db.commit()
        db.refresh(prospect)
        logger.info("AI follow-up set for #%d → %s: %s", prospect_id, suggested, reason)

        # Auto-create a pending sequence step for the suggested follow-up date.
        last_seq = (
            db.query(Sequence)
            .filter(Sequence.prospect_id == prospect_id)
            .order_by(Sequence.step_number.desc())
            .first()
        )
        next_step = (last_seq.step_number + 1) if last_seq else 1

        # Use AI-suggested channel if valid, otherwise fall back to last used channel
        valid_channels = {"email", "linkedin", "phone", "whatsapp"}
        if suggested_channel and suggested_channel.lower() in valid_channels:
            channel = suggested_channel.lower()
        else:
            channel = last_seq.channel if last_seq else "email"
        logger.info("Next follow-up channel: %s (AI suggested: %s)", channel, suggested_channel)

        # Determine subject prefix from reason
        prefix = "Follow-up"
        if "no reply" in reason.lower() or "未回复" in reason:
            prefix = "No-reply follow-up"
        elif "sample" in reason.lower() or "样品" in reason:
            prefix = "Sample follow-up"
        elif "quote" in reason.lower() or "报价" in reason:
            prefix = "Quotation follow-up"
        elif "内部" in reason or "internally" in reason.lower():
            prefix = "Check-in"
        elif "negot" in reason.lower() or "谈判" in reason:
            prefix = "Negotiation update"

        new_step = Sequence(
            prospect_id=prospect_id,
            step_number=next_step,
            channel=channel,
            scheduled_date=suggested,
            status="pending",
            subject=f"[AI Scheduled] {prefix} via {channel} — {prospect.company or 'Prospect'}",
            content="",  # will be filled by the daily scheduler on that date
        )
        db.add(new_step)
        db.commit()
        db.refresh(new_step)
        new_seq_id = new_step.id
        logger.info("Auto-created sequence step #%d for %s on %s (channel: %s)", new_seq_id, prospect.company, suggested, channel)

        return {"success": True, "suggested_date": suggested, "channel": channel, "reason": reason, "applied": True, "sequence_id": new_seq_id}

    return {"success": True, "suggested_date": None, "reason": reason or "AI could not determine", "applied": False, "sequence_id": None}


# ──────────────────────────────────────────────────────
#  POST /api/ai/cold-dev-handoff/{prospect_id}
#  冷开发完成 → AI判断换渠道 → 自动生成下一步
# ──────────────────────────────────────────────────────

@router.post("/cold-dev-handoff/{prospect_id}")
async def cold_dev_handoff(prospect_id: int, db: Session = Depends(get_db)):
    """Triggered after last cold-dev sequence step is completed.
    Checks: all sequences done? any inbound reply?
    AI decides: keep email or switch to LinkedIn/WhatsApp.
    Auto-creates the next step. Never auto-sends — always human review."""
    from datetime import date as _date
    from services.followup_engine import _build_context, _ai_draft, _get_next_business_time, _pick_next_channel, _count_outbound_since_last_inbound, CHANNEL_SWITCH_THRESHOLD

    p = db.query(Prospect).filter(Prospect.id == prospect_id, Prospect.is_deleted == 0).first()
    if not p:
        raise HTTPException(status_code=404, detail="Prospect not found")

    # Check: all sequences done?
    all_seqs = db.query(Sequence).filter(Sequence.prospect_id == prospect_id).all()
    pending_seqs = [s for s in all_seqs if s.status == "pending"]
    if pending_seqs:
        return {
            "success": False,
            "handoff_applies": False,
            "reason": f"{len(pending_seqs)} step(s) not yet completed — cold development is not finished",
            "pending_steps": [{"id": s.id, "step": s.step_number, "channel": s.channel} for s in pending_seqs],
        }

    if not all_seqs:
        return {"success": False, "handoff_applies": False, "reason": "This client has no outreach plan"}

    # Check: any inbound interactions?
    interactions = db.query(Interaction).filter(
        Interaction.prospect_id == prospect_id
    ).order_by(Interaction.interacted_at.asc()).all()

    inbound_count = sum(1 for i in interactions if i.direction == "inbound")
    if inbound_count > 0:
        return {
            "success": False,
            "handoff_applies": False,
            "reason": "Client already has inbound interactions; cold development switched to smart-follow-up mode. Use the Interactions tab or the smart-follow-up button",
            "inbound_count": inbound_count,
        }

    # ── Cold dev complete, no replies → AI handoff ──
    # Determine last used channels and which channel the 3 steps were on
    done_channels = list(set(s.channel for s in all_seqs if s.status in ("done", "skipped")))
    last_channel = all_seqs[-1].channel if all_seqs else "email"
    outbound_count = _count_outbound_since_last_inbound(interactions)

    # Get intelligence for context
    intel = db.query(Intelligence).filter(Intelligence.prospect_id == prospect_id).first()

    # Summarize what was already sent
    seq_summary = []
    for s in all_seqs:
        status_tag = "✓" if s.status == "done" else "✗"
        snippet = (s.content or s.subject or "")[:120]
        seq_summary.append(f"Step {s.step_number} [{s.channel}] {status_tag}: {snippet}")

    ctx = _build_context(p, interactions, intel)
    handoff_prompt = (
        "You are the export sales strategy AI at {{COMPANY}} (export manufacturer).\n\n"
        f"=== CLIENT BACKGROUND ===\n{ctx}\n\n"
        f"=== COLD DEVELOPMENT STATUS ===\n"
        f"{len(all_seqs)} cold-development step(s) completed, all sent via {', '.join(done_channels) or last_channel}, with no reply.\n"
        + "\n".join(seq_summary) + "\n\n"
        + HUMAN_VOICE_RULES + "\n\n"
        + "EMAIL SIGNATURE TO USE:\n"
        + get_signature_for_profile(p.profile_type) + "\n\n"
        "=== TASK ===\n"
        "This client finished the cold-development stage with no reply. Do three things:\n"
        "1. Decide: keep using the same channel (" + last_channel + ") or switch?\n"
        "   - European clients: email → LinkedIn\n"
        "   - Middle East/India: email → WhatsApp (if a phone number exists)\n"
        "   - If the first 3 steps already switched channels with no response, the problem may be the person or timing, not the channel\n"
        f"   - Client country: {p.country or 'Unknown'}. Available contacts: "
        + (("LinkedIn: " + p.linkedin) if p.linkedin else "")
        + (" | WhatsApp/Phone: " + p.phone if p.phone else "")
        + (" | Email: " + (p.email or p.dm_email or "")) + "\n"
        "2. Draft the next message (in English, using your recommended channel).\n"
        "3. Give a short English reason explaining why this channel and this content.\n\n"
        "Return JSON: {\"next_channel\": \"email|linkedin|whatsapp|phone\", "
        "\"subject\": \"email subject (email only)\", \"body\": \"message content\", "
        "\"days_from_now\": 3, \"reason_cn\": \"English reason\"}"
    )

    try:
        loop = asyncio.get_event_loop()
        raw = await call_simple(handoff_prompt, None, 0.7, 2048)
        clean = raw.strip()
        m = re.search(r"\{[\s\S]*\}", clean)
        if m:
            clean = m.group(0)
        decision = json.loads(clean)
    except Exception as e:
        logger.exception("Cold-dev handoff AI parse failed for #%d", prospect_id)
        # Fallback: deterministic channel switch logic
        country = p.country or ""
        decision = {
            "next_channel": _pick_next_channel(last_channel, country, CHANNEL_SWITCH_THRESHOLD),
            "body": (
                f"Hi {p.contact or 'there'}, just checking in - we sent some info about {{COMPANY}} earlier. "
                "Would be happy to discuss your requirements when you have a moment."
                f"{get_signature_for_profile(p.profile_type)}"
            ),
            "subject": f"Quick check-in — {p.company or '{{COMPANY}}'}",
            "days_from_now": 3,
            "reason_cn": "AI parsing failed — using the default channel-switch strategy",
        }

    next_channel = decision.get("next_channel", "email")
    body = decision.get("body", "")
    subject = decision.get("subject", "")
    days_from_now = int(decision.get("days_from_now", 3))
    reason_cn = decision.get("reason_cn", "")

    # Calculate next step number
    last_step = max(s.step_number for s in all_seqs)
    from datetime import date, timedelta
    next_date = (date.today() + timedelta(days=days_from_now)).isoformat()

    # Create the next sequence step
    new_step = Sequence(
        prospect_id=prospect_id,
        step_number=last_step + 1,
        channel=next_channel,
        scheduled_date=next_date,
        status="pending",
        subject=f"[Cold dev → Smart follow-up] {subject[:120]}" if subject else f"[Cold dev → Smart follow-up] {next_channel} outreach",
        content=body,
    )
    db.add(new_step)

    # If next channel is email and content exists, also queue it (pending, human review)
    email_queued = False
    if next_channel == "email" and body:
        to_addr = p.email or p.dm_email or ""
        if to_addr:
            eq = EmailQueue(
                prospect_id=p.id,
                to_email=to_addr,
                subject=f"[Cold Outreach] {subject[:140]}" if subject else f"[Cold Outreach] Follow-up — {p.company or 'Check-in'}",
                body=body,
                status="draft",
                scheduled_at=_get_next_business_time(p),
                daily_send_date=_date.today().isoformat(),
                sequence_id=new_step.id,
            )
            db.add(eq)
            email_queued = True

    # Mark old cancelled sequences as "graduated to smart followup"
    for s in all_seqs:
        if s.status == "cancelled":
            s.outcome_note = (s.outcome_note or "") + " | Entered smart-follow-up phase"

    db.commit()
    db.refresh(new_step)

    return {
        "success": True,
        "handoff_applies": True,
        "last_channel": last_channel,
        "next_channel": next_channel,
        "reason_cn": reason_cn,
        "days_from_now": days_from_now,
        "next_date": next_date,
        "sequence_id": new_step.id,
        "step_number": new_step.step_number,
        "email_queued": email_queued,
        "body_preview": body[:200],
    }


# ──────────────────────────────────────────────────────
#  POST /api/ai/polish
#  AI润色 — in-place revision of existing draft text
# ──────────────────────────────────────────────────────

@router.post("/polish")
async def polish_text(payload: dict, db: Session = Depends(get_db)):
    """AI polishes/润色 existing draft text based on user instruction.
    payload: {text, instruction, prospect_id?}
    Returns: {success, polished, subject?}
    This is the AI润色 button in 开发计划 tab — users tell AI what to change about a draft."""
    # Extract model_override
    model_override = None
    if payload and isinstance(payload, dict):
        mo = payload.get("model_override")
        if mo in ("deepseek", "openai", "gemini", "auto"):
            model_override = mo

    text = (payload.get("text") or "").strip()
    instruction = (payload.get("instruction") or "").strip()
    prospect_id = payload.get("prospect_id")

    if not text:
        return {"success": False, "error": "text is required"}
    if not instruction:
        return {"success": False, "error": "instruction is required"}

    # Build minimal prospect context if available
    ctx_header = ""
    p = None
    if prospect_id:
        try:
            p = db.query(Prospect).filter(Prospect.id == prospect_id, Prospect.is_deleted == 0).first()
            if p:
                ctx_header = (
                    f"Customer: {p.company or '?'} | {p.country or '?'} | {p.industry or '?'} | "
                    f"Profile {p.profile_type or '?'} | Contact: {p.contact or p.decision_maker or 'N/A'}\n"
                )
                if p.score_reason:
                    ctx_header += f"AI score: {p.score_reason[:200]}\n"
        except Exception:
            pass

    # Check: does the text contain a subject line on its own? We handle both email and linkedin/whatsapp
    # If it starts with "Subject:" or the user is editing within email context, try to preserve subject separately
    prompt = (
        "You are the export sales copywriting AI at {{COMPANY}}. Below is an existing outreach draft that the user wants modified.\n\n"
        + (ctx_header if ctx_header else "")
        + HUMAN_VOICE_RULES + "\n\n"
        + (("EMAIL SIGNATURE TO USE:\n" + get_signature_for_profile(p.profile_type if p else None) + "\n\n") if prospect_id else "")
        + f"=== ORIGINAL DRAFT ===\n{text}\n\n"
        + f"=== REVISION REQUEST ===\n{instruction}\n\n"
        + "Polish the draft per the request. Keep the original structure and information density; adjust only what the user asked.\n"
        + 'If it is an email (has Subject), return JSON: {"subject":"...","body":"..."}\n'
        + 'If it is another channel such as LinkedIn or WhatsApp, return JSON: {"body":"..."}\n'
        + "Return the JSON directly with no markdown fences."
    )

    try:
        loop = asyncio.get_event_loop()
        model_param = model_override if model_override in ("deepseek", "openai", "gemini") else None
        raw = await call_simple(prompt, model_param, 0.5, 2048)
        if not raw or not isinstance(raw, str) or raw.strip().startswith("Error") or len(raw.strip()) < 5:
            return {"success": False, "error": "AI call returned invalid response", "raw": str(raw)[:200]}

        result = {}
        clean = raw.strip()
        if "```" in clean:
            clean = re.sub(r"```(?:json)?\s*", "", clean).replace("```", "").strip()
        try:
            result = json.loads(clean)
        except json.JSONDecodeError:
            # Try to extract JSON object
            m = re.search(r'\{[^{}]*\}', clean)
            if m:
                try:
                    result = json.loads(m.group())
                except json.JSONDecodeError:
                    pass
        if isinstance(result, dict) and ("subject" in result or "body" in result):
            return {"success": True, "result": result, "model_used": model_param or "gemini"}
        return {"success": True, "result": {"body": raw.strip()}, "raw": raw[:300]}
    except Exception as exc:
        logger.exception("Revise message failed")
        return {"success": False, "error": str(exc)}


# ──────────────────────────────────────────────────────
#  POST /api/ai/import-parse — 粘贴任意内容，AI 提取客户
# ──────────────────────────────────────────────────────
def _extract_customers_from_ai(raw: str) -> list:
    """从 AI 输出里抠出客户 JSON 数组（兼容围栏/前后文字/尾逗号）。"""
    if not raw:
        return []
    import re as _re
    t = _re.sub(r"```(?:json)?\s*", "", raw).replace("```", "").strip()
    s, e = t.find("["), t.rfind("]")
    if 0 <= s < e:
        cand = t[s : e + 1]
        try:
            return json.loads(cand)
        except Exception:
            try:
                return json.loads(_re.sub(r",\s*(?=[}\]])", "", cand))
            except Exception:
                pass
    out = []
    for m in _re.finditer(r"\{[^{}]*\}", t):
        try:
            obj = json.loads(_re.sub(r",\s*(?=[}\]])", "", m.group()))
            if isinstance(obj, dict):
                out.append(obj)
        except Exception:
            pass
    return out


@router.post("/import-parse")
async def import_ai_parse(payload: dict = None, db: Session = Depends(get_db),
                          user: User = Depends(get_current_user)):
    """不管用户粘贴什么（表格/JSON/网页/聊天记录/乱文本），AI 都提取成客户清单。"""
    text = str((payload or {}).get("text", "") or "")[:30000]
    if not text.strip():
        return {"customers": [], "error": "Content is empty — please paste something first"}

    prompt = (
        "You are a customer-list cleanup assistant for an export sales system. Below is messy content a user pasted; "
        "it can come from spreadsheets, web pages, JSON, email lists, chat logs, trade-show lists, Sales Navigator, or any other format.\n"
        "Extract every potential customer and output a strict JSON array. Each element contains these fields:\n"
        "company (company name), contact (contact person), title (job title), email, "
        "country, website, industry, phone, "
        "linkedin (LinkedIn URL), source_channel (customer source), note (remarks/other useful info), "
        "size (company size), timezone, development_batch (outreach batch), "
        "decision_maker (decision-maker name), dm_title (decision-maker title), dm_email (decision-maker email), "
        "dm_linkedin (decision-maker LinkedIn), status (fixed value \"New\"), sales_stage (fixed value \"new\").\n"
        "Rules:\n"
        "- Only fill information that actually appears in the source. Do not guess, invent, or imagine; leave missing fields as empty strings.\n"
        "- company must be as accurate as possible: use the exact name if present; if only an email domain exists, infer the company name from the domain "
        "(e.g. ff-med.com → FF-Med) and add a note saying \"company name inferred from email domain, to confirm\"; "
        "if nothing is available, leave company empty and mark the note \"company name to confirm\".\n"
        "- Never put URLs, emails, or phone numbers into company; email must be a valid email format.\n"
        "- Restore escaped emails such as \\@, [at], (at) to a normal @, and remove extra backslashes and spaces.\n"
        "- Fill decision_maker / dm_* only when the source clearly identifies a decision maker, founder, general manager, or owner, "
        "or when those fields already exist in the source JSON; otherwise leave empty.\n"
        "- source_channel must be one of: LinkedIn / Email / Google / Google Maps / Trade Show / "
        "Industry directory / Referral / Website / WhatsApp / Existing customer / Other (use the Chinese equivalent if the pasted content is Chinese: "
        "展会 / 行业名录 / 客户介绍 / 老客户); leave empty if the source does not say.\n"
        "- When the same company has multiple contacts, output multiple entries with the same company.\n"
        "- Skip items that cannot be recognized as customers at all.\n"
        "- Output only the JSON array itself — no explanations and no code fences.\n\n"
        "Pasted content:\n" + text
    )
    try:
        from services.ai_router import call_simple_sync
        raw = call_simple_sync(prompt, temperature=0.1, max_tokens=4096)
    except Exception as exc:
        return {"customers": [], "error": f"AI call failed: {exc}"}

    customers = _extract_customers_from_ai(raw)
    cleaned = []
    _FULL_FIELDS = (
        "company", "contact", "title", "email", "country", "website", "industry",
        "phone", "linkedin", "source_channel", "note", "size", "timezone",
        "development_batch", "decision_maker", "dm_title", "dm_email",
        "dm_linkedin", "status", "sales_stage",
    )
    import re as _re2
    for c in customers:
        if not isinstance(c, dict):
            continue
        row = {}
        for k in _FULL_FIELDS:
            row[k] = str(c.get(k, "") or "").strip()
        email = _re2.sub(r"\s+", "", row["email"]).replace("\\@", "@").replace("[at]", "@").replace("(at)", "@")
        if email and not _re2.match(r"^[^@\s]+@[^@\s]+\.[^@\s]+$", email):
            row["note"] = ((row["note"] + "; ") if row["note"] else "") + f"email to confirm: {email}"
            email = ""
        row["email"] = email
        if row["company"] or row["email"] or row["website"]:
            cleaned.append(row)
    if not cleaned:
        return {"customers": [], "error": "AI did not identify any customers — please check the pasted content"}
    return {"customers": cleaned, "raw_length": len(text)}

