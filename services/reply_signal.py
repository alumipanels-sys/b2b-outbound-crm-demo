"""Deterministic reply signal handling for cold-outreach closure.

AI can add nuance, but obvious B2B buying/sample signals should be caught by
rules first so opportunities do not depend on a model call.
"""

from __future__ import annotations

import logging
import re
from datetime import date, timedelta

from sqlalchemy.orm import Session

from models import Interaction, Prospect, SampleEvent, Sequence

logger = logging.getLogger(__name__)


STREET_RE = re.compile(
    r"\b\d{1,6}\s+[A-Za-z0-9 .'-]+(?:street|st|avenue|ave|road|rd|drive|dr|lane|ln|blvd|boulevard|way|court|ct|circle|cir|parkway|pkwy|place|pl|terrace|ter)\b",
    re.IGNORECASE,
)
US_CITY_STATE_ZIP_RE = re.compile(r"\b[A-Za-z .'-]+,\s*[A-Z]{2}\s+\d{5}(?:-\d{4})?\b")
US_STATE_ZIP_RE = re.compile(r"\b[A-Za-z .'-]+\s+(?:AL|AK|AZ|AR|CA|CO|CT|DE|FL|GA|HI|IA|ID|IL|IN|KS|KY|LA|MA|MD|ME|MI|MN|MO|MS|MT|NC|ND|NE|NH|NJ|NM|NV|NY|OH|OK|OR|PA|RI|SC|SD|TN|TX|UT|VA|VT|WA|WI|WV|WY)\s+\d{5}(?:-\d{4})?\b")
POSTAL_RE = re.compile(r"\b(?:zip|postal code|postcode)\s*[:#]?\s*[A-Za-z0-9 -]{4,12}\b", re.IGNORECASE)
UNIT_RE = re.compile(r"\b(?:unit|suite|ste|apt|apartment|room|rm|floor|fl|building|bldg)\s*[#-]?\s*[A-Za-z0-9-]+\b", re.IGNORECASE)


def _looks_like_shipping_address(raw: str) -> bool:
    low = raw.lower()
    if any(
        phrase in low
        for phrase in (
            "shipping address",
            "ship to",
            "send it to",
            "deliver to",
            "mailing address",
        )
    ):
        return True
    if STREET_RE.search(raw) or US_CITY_STATE_ZIP_RE.search(raw) or US_STATE_ZIP_RE.search(raw):
        return True
    if UNIT_RE.search(raw) and (POSTAL_RE.search(raw) or re.search(r"\b\d{5}(?:-\d{4})?\b", raw)):
        return True
    lines = [line.strip() for line in raw.splitlines() if line.strip()]
    numeric_lines = sum(1 for line in lines if re.search(r"\d", line))
    return len(lines) >= 2 and numeric_lines >= 2 and re.search(r"\b\d{5}(?:-\d{4})?\b", raw) is not None


def detect_reply_signal(text: str | None) -> dict:
    raw = text or ""
    low = raw.lower()
    signals: list[str] = []
    intent = ""
    action = ""
    priority = 0

    has_address = _looks_like_shipping_address(raw)
    sample_words = any(
        phrase in low
        for phrase in (
            "sample",
            "samples",
            "send a few",
            "ship a few",
            "ship them",
            "send them",
            "test against",
            "bench test",
            "want to test",
            "try it",
            "try them",
        )
    )
    quote_words = any(phrase in low for phrase in ("quote", "quotation", "price", "pricing", "cost", "rfq"))
    interest_words = any(
        phrase in low
        for phrase in (
            "yes",
            "tell me about it",
            "sounds good",
            "interested",
            "send me",
            "please send",
            "go ahead",
            "sure",
            "ok",
            "okay",
        )
    )
    technical_words = any(
        phrase in low
        for phrase in (
            "spec",
            "specification",
            "tolerance",
            "quality",
            "certification",
            "certificate",
            "lead time",
            "material",
            "custom",
        )
    )

    if sample_words:
        intent = "SAMPLE"
        signals.append("Client mentioned samples/testing")
        action = "Confirm sample specs, quantity, shipping address and testing purpose."
        priority = 85
    elif has_address and not quote_words:
        intent = "SAMPLE_ADDRESS"
        signals.append("Client provided a sample shipping address")
        action = "Create a sample-to-send task, confirm specs/quantity, and add the tracking number after dispatch."
        priority = 95
    elif quote_words:
        intent = "QUOTE_REQUEST"
        signals.append("Client may be asking for a quote")
        action = "Confirm specs, quantity, lead time and use case, then send a formal quotation or proposal."
        priority = 80
    elif interest_words and technical_words:
        intent = "HOT_LEAD"
        signals.append("Client showed interest in a technical topic")
        action = "Explain your advantage around the pain point and move toward sample testing or spec confirmation."
        priority = 75
    elif interest_words:
        intent = "HOT_LEAD"
        signals.append("Client replied positively")
        action = "Ask about their specific needs and try to get samples, drawings or specs."
        priority = 65

    return {
        "intent": intent,
        "signals": signals,
        "action": action,
        "priority": priority,
        "has_address": has_address,
        "has_sample_signal": bool(has_address or sample_words),
        "has_quote_signal": quote_words,
    }


def ensure_sample_task(
    db: Session,
    prospect: Prospect,
    source_text: str | None,
    source_interaction_id: int | None = None,
) -> SampleEvent | None:
    signal = detect_reply_signal(source_text)
    if signal["intent"] not in ("SAMPLE", "SAMPLE_ADDRESS"):
        return None

    existing = (
        db.query(SampleEvent)
        .filter(
            SampleEvent.prospect_id == prospect.id,
            SampleEvent.stage.in_(["requested", "sent", "received", "testing"]),
        )
        .order_by(SampleEvent.created_at.desc())
        .first()
    )
    if existing:
        prospect.sample_status = existing.stage
        try:
            from routers.sample_tracking import _create_sample_email_draft
            _create_sample_email_draft(db, prospect, existing)
        except Exception:
            pass
        return existing

    today = date.today().isoformat()
    note_parts = ["System detected a sample opportunity from the client reply."]
    if signal["has_address"]:
        note_parts.append("The client appears to have provided a shipping address.")
    if source_text:
        note_parts.append("Original text: " + source_text.strip()[:800])
    if source_interaction_id:
        note_parts.append(f"Source interaction ID: {source_interaction_id}")

    event = SampleEvent(
        prospect_id=prospect.id,
        stage="requested",
        note="\n".join(note_parts),
        event_date=today,
        test_purpose="确认样品规格、数量、寄送地址和测试目的。",
        ai_followup_prompt="客户出现样品/地址信号。请确认规格、数量、寄送地址和测试目的；寄出后补快递单号并更新为“已寄出”。",
    )
    db.add(event)
    try:
        from routers.sample_tracking import _create_sample_email_draft
        _create_sample_email_draft(db, prospect, event)
    except Exception:
        pass

    prospect.sample_status = "requested"
    prospect.next_follow_date = (date.today() + timedelta(days=1)).isoformat()
    prospect.reminder_note = "[样品] 客户出现样品/寄样地址信号，确认规格并安排寄出。"
    from datetime import datetime
    prospect.last_edited_at = datetime.utcnow()
    return event


def apply_reply_signal(
    db: Session,
    interaction: Interaction,
    prospect: Prospect,
    commit: bool = False,
) -> dict:
    signal = detect_reply_signal(interaction.content)
    if not signal["intent"]:
        return signal

    if not interaction.reply_intent:
        interaction.reply_intent = signal["intent"]
    if not interaction.ai_suggested_action:
        interaction.ai_suggested_action = signal["action"]
    if not interaction.ai_suggested_channel:
        interaction.ai_suggested_channel = interaction.channel or "linkedin"
    if not interaction.ai_suggested_timing:
        interaction.ai_suggested_timing = "今天处理" if signal["priority"] >= 80 else "1-2天内处理"

    # ── Hot signal → pause ALL cold-dev sequences ──
    hot_intents = {"SAMPLE_ADDRESS", "SAMPLE", "QUOTE_REQUEST", "HOT_LEAD"}
    if signal["intent"] in hot_intents:
        _pause_cold_sequences(db, prospect, signal)

    if signal["has_sample_signal"]:
        ensure_sample_task(db, prospect, interaction.content, interaction.id)
        prospect.sales_stage = "sample_pending"
    elif signal["has_quote_signal"]:
        prospect.sales_stage = "interested"
        prospect.next_follow_date = (date.today() + timedelta(days=1)).isoformat()
        prospect.reminder_note = "[热回复·待回复] 客户可能在询价，确认规格/数量/交期后推进报价。"
    elif signal["priority"] >= 65:
        prospect.sales_stage = "interested"
        prospect.next_follow_date = (date.today() + timedelta(days=1)).isoformat()
        prospect.reminder_note = "[热回复·待回复] " + signal["action"]
    elif signal["priority"] >= 40 and (not prospect.sales_stage or prospect.sales_stage in ("new", "touched", "connected")):
        prospect.sales_stage = "replied"

    from datetime import datetime
    prospect.last_edited_at = datetime.utcnow()

    if commit:
        db.commit()
        db.refresh(interaction)
    return signal


def _pause_cold_sequences(db: Session, prospect: Prospect, signal: dict) -> int:
    """Auto-pause all pending/cold-dev sequences when a hot reply signal is detected.
    The customer has engaged — stop pushing cold outreach, shift to reply mode."""
    paused = (
        db.query(Sequence)
        .filter(
            Sequence.prospect_id == prospect.id,
            Sequence.status == "pending",
        )
        .update({"status": "paused_hot_reply", "outcome_note": "系统自动Paused：检测到热信号 " + signal["intent"] + "，请优先在邮件管理中回复客户。"},
                synchronize_session=False)
    )
    if paused:
        logger.info("Paused %d cold sequences for prospect #%d (%s) — hot reply: %s",
                    paused, prospect.id, prospect.company, signal["intent"])
    return paused
