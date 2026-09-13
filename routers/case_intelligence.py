"""CASE intelligence router.

Turns existing successful case-study knowledge into operational cold-outreach
signals: structured case cards, dashboard metrics, and prospect-to-case matches.
"""

from __future__ import annotations

import json
import logging
import re
from collections import Counter, defaultdict

logger = logging.getLogger(__name__)
from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from database import get_db
from models import EmailQueue, Interaction, KnowledgeBase, Prospect, Sequence

router = APIRouter()


CHANNEL_ALIASES = {
    "email": ("email", "cold email", "mail"),
    "linkedin": ("linkedin", "connection", "cold message", "dm"),
    "whatsapp": ("whatsapp", "wa"),
    "phone": ("phone", "call", "zoom"),
}

OUTCOME_KEYWORDS = {
    "won": ("won", "成交", "purchase order", "paid", "order"),
    "sample": ("sample", "样品", "sample shipping", "sample sent", "寄样"),
    "meeting": ("zoom", "meeting", "call", "factory tour", "看厂"),
    "reply": ("reply", "replied", "回复", "successful reply"),
}

PROFILE_RE = re.compile(r"\bProfile[_\s-]?([ABCDE])\b", re.IGNORECASE)


def _loads_tags(raw: str | None) -> list[str]:
    if not raw:
        return []
    try:
        data = json.loads(raw)
        if isinstance(data, list):
            return [str(x).strip() for x in data if str(x).strip()]
    except Exception:
        pass
    return [x.strip() for x in raw.split(",") if x.strip()]


def _norm(value: str | None) -> str:
    return (value or "").strip().lower()


def _contains_any(text: str, needles: tuple[str, ...]) -> bool:
    low = text.lower()
    return any(n.lower() in low for n in needles)


def _has_won_signal(text: str) -> bool:
    low = text.lower()
    if re.search(r"\b(po|paid|won|order|purchase order)\b", low):
        return True
    return any(word in text for word in ("成交", "采购订单", "付款", "已下单", "订单确认"))


def _extract_profile(tags: list[str], text: str) -> str | None:
    for tag in tags:
        m = PROFILE_RE.search(tag)
        if m:
            return m.group(1).upper()
    m = PROFILE_RE.search(text)
    return m.group(1).upper() if m else None


def _extract_channels(tags: list[str], text: str) -> list[str]:
    blob = " ".join(tags) + " " + text
    found = []
    for channel, aliases in CHANNEL_ALIASES.items():
        if _contains_any(blob, aliases):
            found.append(channel)
    return found or ["email"]


def _extract_outcomes(tags: list[str], text: str) -> list[str]:
    blob = " ".join(tags) + " " + text
    found = []
    for outcome, words in OUTCOME_KEYWORDS.items():
        if outcome == "won":
            tag_blob = " ".join(tags)
            if _has_won_signal(tag_blob):
                found.append(outcome)
            continue
        if _contains_any(blob, words):
            found.append(outcome)
    return found or ["reply"]


def _extract_region(tags: list[str], text: str) -> str | None:
    region_words = [
        "germany",
        "deutschland",
        "usa",
        "united states",
        "florida",
        "europe",
        "switzerland",
        "austria",
        "turkey",
        "india",
        "middle east",
        "德国",
        "美国",
        "欧洲",
        "瑞士",
        "奥地利",
    ]
    blob = " ".join(tags) + " " + text
    low = blob.lower()
    for word in region_words:
        if word.lower() in low:
            return word
    return None


def _extract_playbook(content: str) -> list[str]:
    lines = [line.strip(" -#*\t") for line in content.splitlines()]
    useful = []
    markers = (
        "trigger",
        "strategy",
        "playbook",
        "lesson",
        "key",
        "tactic",
        "follow",
        "channel",
        "切入",
        "策略",
        "战术",
        "经验",
        "关键",
        "复用",
        "教训",
    )
    for line in lines:
        if 18 <= len(line) <= 180 and _contains_any(line, markers):
            useful.append(line)
        if len(useful) >= 5:
            break
    if useful:
        return useful
    sentences = re.split(r"(?<=[.!?。！？])\s+", content.replace("\n", " "))
    return [s.strip()[:180] for s in sentences if len(s.strip()) > 40][:4]


def _sanitize_tolerance(text: str) -> str:
    """Alias for the shared utility in writing_rules."""
    from services.writing_rules import sanitize_tolerance, sanitize_attachment_language
    return sanitize_attachment_language(sanitize_tolerance(text))


def _case_to_card(case: KnowledgeBase) -> dict[str, Any]:
    tags = _loads_tags(case.tags)
    content = case.content or ""
    profile = _extract_profile(tags, content)
    channels = _extract_channels(tags, content)
    outcomes = _extract_outcomes(tags, content)
    region = _extract_region(tags, content)
    strength = 45
    if "won" in outcomes:
        strength += 25
    if "sample" in outcomes:
        strength += 15
    if len(channels) >= 2:
        strength += 10
    if profile:
        strength += 5
    return {
        "id": case.id,
        "title": case.title,
        "tags": tags,
        "profile": profile,
        "region": region,
        "channels": channels,
        "outcomes": outcomes,
        "strength_score": min(strength, 100),
        "playbook": _extract_playbook(content),
        "preview": content.replace("\n", " ")[:420],
        "content_length": len(content),
    }


def _list_case_cards(db: Session) -> list[dict[str, Any]]:
    rows = (
        db.query(KnowledgeBase)
        .filter(KnowledgeBase.category == "case_study", KnowledgeBase.is_active == 1)
        .order_by(KnowledgeBase.id.asc())
        .all()
    )
    return [_case_to_card(row) for row in rows]


def _pct(num: int, den: int) -> float:
    return round((num / den * 100), 1) if den else 0.0


def _channel_key(channel: str | None) -> str:
    raw = _norm(channel)
    if "linked" in raw:
        return "linkedin"
    if "whatsapp" in raw or raw == "wa":
        return "whatsapp"
    if "phone" in raw or "call" in raw:
        return "phone"
    if "email" in raw or "mail" in raw:
        return "email"
    return raw or "unknown"


def _dashboard_stats(db: Session) -> dict[str, Any]:
    prospects = db.query(Prospect).filter(Prospect.is_deleted == 0).all()
    interactions = db.query(Interaction).all()
    sequences = db.query(Sequence).all()
    email_queue = db.query(EmailQueue).all()

    prospect_by_id = {p.id: p for p in prospects}
    active_count = len(prospects)
    profiled_count = sum(1 for p in prospects if (p.profile_type or "").strip() not in ("", "Unknown"))
    high_count = sum(1 for p in prospects if (p.value_level or "").upper() == "HIGH")
    follow_count = sum(1 for p in prospects if (p.next_follow_date or "").strip())

    outbound = [ix for ix in interactions if ix.direction == "outbound"]
    inbound = [ix for ix in interactions if ix.direction == "inbound"]
    outbound_prospects = {ix.prospect_id for ix in outbound}
    from services.reply_metrics import is_bounce_interaction
    real_inbound = [ix for ix in inbound if not is_bounce_interaction(ix)]
    inbound_prospects = {ix.prospect_id for ix in real_inbound}
    bounced_prospects = {ix.prospect_id for ix in inbound if is_bounce_interaction(ix)}

    channel_rows = []
    all_channels = sorted({_channel_key(ix.channel) for ix in interactions} | {_channel_key(s.channel) for s in sequences})
    for channel in all_channels:
        ch_out = [ix for ix in outbound if _channel_key(ix.channel) == channel]
        ch_in = [ix for ix in real_inbound if _channel_key(ix.channel) == channel]
        ch_out_p = {ix.prospect_id for ix in ch_out}
        ch_in_p = {ix.prospect_id for ix in ch_in}
        channel_rows.append(
            {
                "channel": channel,
                "outbound": len(ch_out),
                "inbound": len(ch_in),
                "contacted_prospects": len(ch_out_p),
                "replied_prospects": len(ch_in_p),
                "reply_rate": _pct(len(ch_in_p), len(ch_out_p)),
            }
        )
    channel_rows.sort(key=lambda x: (x["reply_rate"], x["outbound"]), reverse=True)

    profile_rows = []
    profile_counts = Counter((p.profile_type or "blank") for p in prospects)
    for profile, total in sorted(profile_counts.items(), key=lambda x: (-x[1], x[0])):
        ids = {p.id for p in prospects if (p.profile_type or "blank") == profile}
        contacted = ids & outbound_prospects
        replied = ids & inbound_prospects
        profile_rows.append(
            {
                "profile": profile,
                "prospects": total,
                "contacted": len(contacted),
                "replied": len(replied),
                "reply_rate": _pct(len(replied), len(contacted)),
            }
        )

    reply_intents = Counter((ix.reply_intent or "unclassified") for ix in inbound)
    case_cards = _list_case_cards(db)
    cases_by_profile = Counter(card.get("profile") or "unknown" for card in case_cards)
    cases_by_outcome = Counter(outcome for card in case_cards for outcome in card.get("outcomes", []))
    pending_sequences = sum(1 for s in sequences if (s.status or "pending") == "pending")
    sent_emails = sum(1 for e in email_queue if (e.status or "") == "sent")

    gaps = []
    if active_count and profiled_count < active_count:
        gaps.append({"type": "profile_gap", "label": "Unprofiled prospects", "count": active_count - profiled_count})
    unclassified = reply_intents.get("unclassified", 0) + reply_intents.get("", 0)
    if unclassified:
        gaps.append({"type": "reply_intent_gap", "label": "Inbound replies without intent", "count": unclassified})
    if not case_cards:
        gaps.append({"type": "case_gap", "label": "No reusable success cases", "count": 0})

    return {
        "overview": {
            "active_prospects": active_count,
            "profiled_prospects": profiled_count,
            "profiled_rate": _pct(profiled_count, active_count),
            "high_value_prospects": high_count,
            "followup_scheduled": follow_count,
            "outbound_interactions": len(outbound),
            "inbound_interactions": len(real_inbound),
            "contacted_prospects": len(outbound_prospects),
            "replied_prospects": len(inbound_prospects),
            "prospect_reply_rate": _pct(len(inbound_prospects), len(outbound_prospects)),
            "bounced_prospects": len(bounced_prospects),
            "bounce_rate": _pct(len(bounced_prospects), len(outbound_prospects)),
            "pending_sequences": pending_sequences,
            "sent_emails": sent_emails,
            "case_studies": len(case_cards),
        },
        "channels": channel_rows,
        "profiles": profile_rows,
        "reply_intents": dict(reply_intents),
        "cases_by_profile": dict(cases_by_profile),
        "cases_by_outcome": dict(cases_by_outcome),
        "gaps": gaps,
    }


def _match_case(prospect: Prospect, card: dict[str, Any]) -> dict[str, Any]:
    score = 0
    reasons = []
    profile = (prospect.profile_type or "").strip().upper()
    country = _norm(prospect.country)
    industry = _norm(prospect.industry)
    note = _norm(prospect.note)
    company_blob = " ".join([_norm(prospect.company), industry, note])
    tags_low = [_norm(t) for t in card.get("tags", [])]
    preview = _norm(card.get("preview"))

    if profile and card.get("profile") == profile:
        score += 35
        reasons.append(f"same Profile {profile}")
    if country and any(country in t or t in country for t in tags_low if len(t) >= 2):
        score += 18
        reasons.append("same country/region signal")
    if country and country in preview:
        score += 12
        reasons.append("case text mentions the same market")
    for token in re.split(r"[\s,/;|()\-]+", company_blob):
        token = token.strip()
        if len(token) >= 5 and (token in preview or token in " ".join(tags_low)):
            score += 8
            reasons.append(f"shared keyword: {token}")
            break
    if prospect.linkedin and "linkedin" in card.get("channels", []):
        score += 8
        reasons.append("LinkedIn path available")
    if prospect.email and "email" in card.get("channels", []):
        score += 6
        reasons.append("email path available")
    if "won" in card.get("outcomes", []):
        score += 8
        reasons.append("case reached order")
    elif "sample" in card.get("outcomes", []):
        score += 5
        reasons.append("case reached sample stage")

    return {
        **card,
        "match_score": min(score, 100),
        "match_reasons": reasons[:5] or ["general reusable cold-outreach case"],
    }


@router.get("/cases")
async def list_cases(db: Session = Depends(get_db)):
    return {"cases": _list_case_cards(db)}


@router.get("/dashboard")
async def dashboard(db: Session = Depends(get_db)):
    return {**_dashboard_stats(db), "cases": _list_case_cards(db)}


@router.get("/prospect/{prospect_id}/matches")
async def prospect_matches(prospect_id: int, db: Session = Depends(get_db)):
    prospect = db.query(Prospect).filter(Prospect.id == prospect_id, Prospect.is_deleted == 0).first()
    if not prospect:
        raise HTTPException(status_code=404, detail="Prospect not found")
    matches = [_match_case(prospect, card) for card in _list_case_cards(db)]
    matches.sort(key=lambda x: (x["match_score"], x["strength_score"]), reverse=True)
    return {
        "prospect_id": prospect_id,
        "company": prospect.company,
        "matches": matches[:5],
    }


# ══════════════════════════════════════════════════════════════════
#  Copy Generator — 用户选案例 → AI 基于案例生成话术
# ══════════════════════════════════════════════════════════════════

from pydantic import BaseModel


class GenerateCopyRequest(BaseModel):
    prospect_id: int
    case_ids: list[int]
    channel: str = "email"   # email / linkedin / whatsapp
    tone_note: str | None = None
    model: str | None = None  # "deepseek" / "openai" / "gemini" / None=auto


@router.post("/generate-copy")
async def generate_copy(req: GenerateCopyRequest, db: Session = Depends(get_db)):
    """Generate outreach copy grounded in user-selected case studies.

    1. Load prospect profile + recent interactions
    2. Load selected cases (full content from knowledge_base)
    3. Build a prompt that mandates referencing the cases
    4. Call AI, parse JSON response
    """
    # ── 1. Load prospect ──
    prospect = db.query(Prospect).filter(
        Prospect.id == req.prospect_id, Prospect.is_deleted == 0
    ).first()
    if not prospect:
        raise HTTPException(status_code=404, detail="Prospect not found")

    # ── 2. Load selected cases ──
    if not req.case_ids or len(req.case_ids) > 5:
        raise HTTPException(status_code=400, detail="case_ids: 1-5 required")

    selected_cases = (
        db.query(KnowledgeBase)
        .filter(
            KnowledgeBase.id.in_(req.case_ids),
            KnowledgeBase.category == "case_study",
            KnowledgeBase.is_active == 1,
        )
        .all()
    )

    if not selected_cases:
        raise HTTPException(status_code=404, detail="No valid cases found for these IDs")

    # ── 3. Load recent interactions ──
    recent_ix = (
        db.query(Interaction)
        .filter(Interaction.prospect_id == req.prospect_id)
        .order_by(Interaction.interacted_at.desc())
        .limit(10)
        .all()
    )

    # ── 4. Build prospect snapshot ──
    profile = (prospect.profile_type or "Unknown").strip()
    country = (prospect.country or "Unknown").strip()
    industry = (prospect.industry or "").strip()
    company = (prospect.company or "").strip()
    note = (prospect.note or "").strip()
    contact = (prospect.contact or prospect.decision_maker or "").strip()

    summary_parts = [f"Company: {company}"]
    if contact:
        summary_parts.append(f"Contact: {contact}")
    summary_parts.append(f"Country: {country}")
    summary_parts.append(f"Profile: {profile}")
    if industry:
        summary_parts.append(f"Industry: {industry}")
    if note:
        summary_parts.append(f"Notes: {note[:400]}")
    prospect_summary = "\n".join(summary_parts)

    # Interaction history
    ix_lines = []
    for ix in reversed(recent_ix):
        d = "[客户→我方]" if ix.direction == "inbound" else "[我方→客户]"
        ch = ix.channel or "unknown"
        content = (ix.content or ix.subject or "")[:300]
        date = str(ix.interacted_at)[:16] if ix.interacted_at else "?"
        if content.strip():
            ix_lines.append(f"{date} {d} ({ch}): {content}")
    ix_text = "\n".join(ix_lines) if ix_lines else "(no interactions yet)"

    # ── 5. Build case contexts ──
    case_contexts = []
    for i, c in enumerate(selected_cases, 1):
        content = (c.content or "")[:1500]  # cap per case
        case_contexts.append(
            f"=== CASE {i}: {c.title} ===\n{content}\n"
        )
    cases_text = "\n\n".join(case_contexts)

    # ── 5.5 Load product specs AND writing rules via shared module ──
    from services.writing_rules import get_spec_and_rules
    spec_and_rules = get_spec_and_rules(db)

    # ── 6. Tone guidance ──
    country_lower = country.lower()
    if any(w in country_lower for w in ("germany", "deutschland", "german", "austria", "swiss", "switzerland", "europe")):
        tone_guide = "professional, technically precise, data-driven. German buyers respect engineering detail, not sales fluff."
    elif any(w in country_lower for w in ("usa", "united states", "america", "canada")):
        tone_guide = "direct, efficient, value-first. American buyers want the bottom line quickly."
    elif any(w in country_lower for w in ("middle east", "uae", "dubai", "saudi", "qatar", "kuwait", "oman", "turkey", "iran", "iraq")):
        tone_guide = "respectful, relationship-oriented, patient. Middle Eastern buyers value trust and personal connection."
    elif any(w in country_lower for w in ("taiwan", "china", "japan", "korea")):
        tone_guide = "polite, detail-oriented, partnership-focused. Asian buyers value reliability and long-term thinking."
    else:
        tone_guide = "professional, direct, clear."

    tone_note_extra = f"\nAdditional tone instruction: {req.tone_note}" if req.tone_note else ""

    # ── 7. Build prompt ──
    prompt = f"""You are writing a {req.channel} outreach message for {{COMPANY}} (the company described in the knowledge base below).

⚠️ SPEC RULE — READ THIS FIRST: Never invent or rely on your training data for product specs. The ONLY valid product facts are in the knowledge base provided at the end of this prompt. Never copy spec values from case studies — they may be outdated. If the knowledge base lacks a needed fact, do not guess; omit it.

TARGET PROSPECT:
{prospect_summary}

INTERACTION HISTORY:
{ix_text}

SUCCESSFUL CASE STUDIES TO REFERENCE (borrow structure and tactics — NEVER copy their Numbers):
{cases_text}

CASE-REFERENCE RULES:
1. Borrow specific phrases and tactics from the cases above — do NOT invent generic sales language.
2. Adapt the borrowed phrases to this specific prospect's context (country, profile, industry).
3. CRITICAL: NEVER copy tolerance numbers, dimensions, or any spec values from the case studies. ALWAYS use the knowledge base specs provided at the end of this prompt. The case numbers may be outdated — specs are the single source of truth.

TONE: {tone_guide}{tone_note_extra}

{spec_and_rules}

⚠️ FINAL REMINDER: Use ONLY the knowledge base specs. Never invent numbers. Check your output now.

Return strict JSON (no markdown code block):
{{"subject": "email subject or empty for non-email", "body": "the full message text", "sources": [{{"case_title": "...", "reference_line": "the specific phrase you borrowed from this case"}}], "reasoning": "brief explanation (Chinese) of why you wrote it this way"}}"""

    # ── 8. Call AI ──
    from services.ai_router import call_simple

    try:
        logger.info("generate-copy: calling AI for prospect %d, cases=%s, channel=%s, prompt_len=%d",
                     req.prospect_id, req.case_ids, req.channel, len(prompt))
        raw = await call_simple(prompt, model_override=req.model, temperature=0.6, max_tokens=2048)
        logger.info("generate-copy: AI returned %d chars", len(raw) if raw else 0)
        clean = raw.strip()

        # ── Post-processing: physically strip wrong tolerances ──
        clean = _sanitize_tolerance(clean)

        # Try to extract JSON from response
        m = re.search(r"\{[\s\S]*\}", clean)
        if m:
            result = json.loads(m.group(0))
            return {
                "prospect_id": req.prospect_id,
                "channel": req.channel,
                "selected_cases": [{"id": c.id, "title": c.title} for c in selected_cases],
                "draft": {
                    "subject": result.get("subject", ""),
                    "body": result.get("body", ""),
                    "sources": result.get("sources", []),
                },
                "reasoning": result.get("reasoning", ""),
            }
        else:
            # Fallback: return raw text (still sanitize tolerances)
            clean_fallback = _sanitize_tolerance(raw)
            return {
                "prospect_id": req.prospect_id,
                "channel": req.channel,
                "selected_cases": [{"id": c.id, "title": c.title} for c in selected_cases],
                "draft": {"subject": "", "body": clean_fallback, "sources": []},
                "reasoning": "AI returned non-JSON response, raw text shown.",
                "raw": clean_fallback,
            }
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"AI generation failed: {str(e)}")
