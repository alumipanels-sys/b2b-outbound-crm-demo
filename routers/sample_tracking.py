"""Sample tracking: event log, reminders, AI prompts, sample funnel, and logistics tracking."""

from __future__ import annotations

import asyncio
import logging
from datetime import date, datetime, timedelta

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from database import get_db
from models import EmailQueue, Prospect, SampleEvent
from schemas import SampleEventCreate, SampleEventOut, SampleEventUpdate
from services.ai_router import call_simple_sync as call_simple, get_signature_for_profile

logger = logging.getLogger(__name__)
router = APIRouter()


STAGE_LABELS = {
    "requested": "Address given / awaiting dispatch",
    "sent": "Sent",
    "received": "Received by customer",
    "testing": "Testing",
    "feedback": "Feedback received",
    "trial_order": "Converted to trial order",
    "completed": "Completed",
    "dead": "Sample lost / failed",
}

STAGE_ORDER = ["requested", "sent", "received", "testing", "feedback", "trial_order", "completed"]

STAGE_REMINDER = {
    "requested": (2, "Sample awaiting dispatch - confirm specs / quantity"),
    "sent": (5, "Sample shipped - track the parcel"),
    "received": (3, "Sample received - confirm it arrived intact"),
    "testing": (7, "Sample under testing - check progress"),
    "feedback": (2, "Customer gave feedback - reply promptly"),
    "trial_order": (5, "Moving to trial order - confirm specs and lead time"),
}


def _tracking_url(carrier, tracking_number):
    c = (carrier or "").strip().lower()
    t = (tracking_number or "").strip()
    if not t:
        return None
    if "dhl" in c:
        return "https://www.dhl.com/global-en/home/tracking/tracking-express.html?submit=1&tracking-id=" + t
    if "fedex" in c:
        return "https://www.fedex.com/fedextrack/?trknbr=" + t
    if "ups" in c:
        return "https://www.ups.com/track?tracknum=" + t
    return None


def _sample_email_subject(prospect, stage):
    company = prospect.company or "your team"
    mapping = {
        "requested": "Sample details for " + company,
        "sent": "Sample shipment update - " + company,
        "received": "Checking sample delivery - " + company,
        "testing": "Quick check on sample testing - " + company,
        "feedback": "Re: sample feedback - " + company,
        "trial_order": "Next step after sample testing - " + company,
    }
    return mapping.get(stage, "Sample follow-up - " + company)


def _sample_email_body(prospect, event):
    name = prospect.contact or prospect.decision_maker or "there"
    carrier = event.carrier or "the courier"
    tracking = event.tracking_number or ""
    tracking_url = event.tracking_url or _tracking_url(event.carrier, tracking)
    arrival = event.expected_arrival or ""
    purpose = event.test_purpose or "the quality check"
    note = event.note or ""
    sig = get_signature_for_profile(prospect.profile_type).strip().splitlines()

    if event.stage == "sent":
        parts = ["Hi " + name + ",", "", "Just a quick update: the sample pieces have been shipped out.", ""]
        if tracking:
            parts.append("Tracking: " + carrier + " " + tracking)
        if tracking_url:
            parts.append("Tracking link: " + tracking_url)
        if arrival:
            parts.append("Estimated arrival: " + arrival)
        if note:
            parts.append("")
            parts.append("Sample note: " + note)
        parts.extend([
            "",
            "Once they arrive, your bench team can check the centration, edge clarity and assembly feel against your current batch.",
            "No rush to reply now. Just wanted to make sure the shipping details are easy for your team to find.",
            "",
            "Best regards,",
        ])
        parts.extend(sig)
        return "\n".join(parts)

    if event.stage == "received":
        parts = [
            "Hi " + name + ",",
            "",
            "It looks like the samples should have arrived by now.",
            "Could you help confirm whether everything reached your team in good condition?",
            "",
            "When your technicians start " + purpose + ", I would be glad to support if they have any question about dimensions, alignment or edge clarity.",
            "",
            "Best regards,",
        ]
        parts.extend(sig)
        return "\n".join(parts)

    if event.stage == "testing":
        parts = [
            "Hi " + name + ",",
            "",
            "Just checking in on the sample testing.",
            "Have your technicians had a chance to compare the pieces for " + purpose + "?",
            "",
            "No pressure at all. Even a short note on what looks good or what does not fit your bench process would be very helpful for us.",
            "",
            "Best regards,",
        ]
        parts.extend(sig)
        return "\n".join(parts)

    if event.stage == "feedback":
        parts = [
            "Hi " + name + ",",
            "",
            "Thanks for the feedback on the samples.",
            "My understanding is: " + (note or "your team has started reviewing the result."),
            "",
            "I will check this with our production side and come back with a practical next step.",
            "",
            "Best regards,",
        ]
        parts.extend(sig)
        return "\n".join(parts)

    if event.stage == "trial_order":
        parts = [
            "Hi " + name + ",",
            "",
            "Glad the sample check moved in the right direction.",
            "For the next small trial order, could you confirm the exact sizes, quantities and any packaging requirement your team prefers?",
            "",
            "Once I have that, I can prepare a clear PI with lead time for your review.",
            "",
            "Best regards,",
        ]
        parts.extend(sig)
        return "\n".join(parts)

    parts = [
        "Hi " + name + ",",
        "",
        "Thanks again for considering the sample test.",
        "Could you confirm the exact sizes, quantity and shipping address so I can keep the sample shipment moving?",
        "",
        "Best regards,",
    ]
    parts.extend(sig)
    return "\n".join(parts)


def _create_sample_email_draft(db, prospect, event):
    to_email = prospect.email or prospect.dm_email or ""
    if event.stage not in ("requested", "sent", "received", "testing", "feedback", "trial_order"):
        return None
    if not to_email:
        return None
    subject = _sample_email_subject(prospect, event.stage)
    existing = (
        db.query(EmailQueue)
        .filter(
            EmailQueue.prospect_id == prospect.id,
            EmailQueue.status.in_(["draft", "pending"]),
            EmailQueue.subject == subject,
        )
        .first()
    )
    if existing:
        event.followup_draft_id = existing.id
        return existing
    draft = EmailQueue(
        prospect_id=prospect.id,
        to_email=to_email,
        subject=subject,
        body=_sample_email_body(prospect, event),
        status="draft",
        scheduled_at=datetime.utcnow(),
        daily_send_date=date.today().isoformat(),
    )
    db.add(draft)
    db.flush()
    event.followup_draft_id = draft.id
    return draft


def _generate_followup_prompt(prospect, stage, note, prev_note):
    company = prospect.company or "client"
    prompts = {
        "requested": "Client " + company + " sample is in pending-ship stage.",
        "sent": "Sample shipped to " + company + ". Share tracking and ETA. Note: " + note,
        "received": "Sample delivered to " + company + ". Confirm receipt and ask about testing timeline.",
        "testing": "Sample testing at " + company + ". Check progress, offer support. " + prev_note,
        "feedback": "Client " + company + " gave feedback: " + note,
        "trial_order": "Sample passed, " + company + " entering trial order stage.",
        "completed": "Sample process completed for " + company + ".",
    }
    return prompts.get(stage, "Sample stage: " + stage)


def _auto_set_reminder(db, prospect, stage, event_date, expected_arrival):
    if stage not in STAGE_REMINDER:
        return
    offset_days, note_prefix = STAGE_REMINDER[stage]
    if stage == "sent" and expected_arrival:
        prospect.next_follow_date = expected_arrival
        prospect.reminder_note = "[Sample] " + note_prefix + " (ETA " + expected_arrival + ")"
        return
    base = date.today()
    if event_date:
        try:
            base = date.fromisoformat(event_date[:10])
        except (ValueError, TypeError):
            pass
    target = base + timedelta(days=offset_days)
    # Anti-bunching: find next available slot
    from services.followup_engine import _next_available_slot
    slot = _next_available_slot(db, target)
    prospect.next_follow_date = slot.isoformat()
    prospect.reminder_note = "[Sample] " + note_prefix


def _sync_prospect_from_event(db, prospect, event):
    prospect.sample_status = event.stage
    stage_map = {
        "requested": "sample_pending",
        "sent": "sample_sent",
        "received": "testing",
        "testing": "testing",
        "feedback": "feedback",
        "trial_order": "trial_order",
        "completed": "won",
        "dead": "lost",
    }
    if event.stage in stage_map:
        prospect.sales_stage = stage_map[event.stage]
    if event.stage == "sent" and event.event_date:
        prospect.sample_sent_date = event.event_date
    if event.stage in ("feedback", "trial_order", "completed", "dead") and event.note:
        prospect.sample_feedback = event.note
    _auto_set_reminder(db, prospect, event.stage, event.event_date, event.expected_arrival)
    prospect.reminder_updated_at = datetime.utcnow()
    prospect.updated_at = datetime.utcnow()
    prospect.last_edited_at = datetime.utcnow()


def _event_to_dict(ev):
    return {
        "id": ev.id, "prospect_id": ev.prospect_id,
        "stage": ev.stage or "", "note": ev.note or "",
        "event_date": ev.event_date or "", "carrier": ev.carrier or "",
        "tracking_number": ev.tracking_number or "",
        "tracking_url": ev.tracking_url or "",
        "logistics_status": ev.logistics_status or "",
        "expected_arrival": ev.expected_arrival or "",
        "signed_date": ev.signed_date or "",
        "test_purpose": ev.test_purpose or "",
        "client_deadline": ev.client_deadline or "",
        "ai_followup_prompt": ev.ai_followup_prompt or "",
        "followup_draft_id": ev.followup_draft_id,
        "notified_at": ev.notified_at or "",
        "notified_channel": ev.notified_channel or "",
        "created_at": str(ev.created_at) if ev.created_at else "",
    }


# -- Funnel --
@router.get("/funnel")
def sample_funnel(db: Session = Depends(get_db)):
    prospects = db.query(Prospect).filter(Prospect.is_deleted == 0).all()
    prospect_by_id = {p.id: p for p in prospects}
    events = db.query(SampleEvent).order_by(SampleEvent.created_at.asc()).all()

    latest_by_pid = {}
    history_by_pid = {}
    for ev in events:
        if ev.prospect_id not in prospect_by_id:
            continue
        history_by_pid.setdefault(ev.prospect_id, []).append(ev)
        latest_by_pid[ev.prospect_id] = ev

    counts = {s: 0 for s in STAGE_ORDER}
    counts["dead"] = 0
    cards = []
    today = date.today()
    for pid, ev in latest_by_pid.items():
        p = prospect_by_id[pid]
        stage = ev.stage or "requested"
        counts[stage] = counts.get(stage, 0) + 1
        days_until = None
        if p.next_follow_date:
            try:
                days_until = (date.fromisoformat(p.next_follow_date[:10]) - today).days
            except Exception:
                pass
        cards.append({
            "prospect_id": pid,
            "company": p.company,
            "contact": p.contact,
            "country": p.country,
            "stage": stage,
            "stage_label": STAGE_LABELS.get(stage, stage),
            "event_date": ev.event_date,
            "tracking_number": ev.tracking_number,
            "expected_arrival": ev.expected_arrival,
            "next_follow_date": p.next_follow_date,
            "reminder_note": p.reminder_note,
            "days_until": days_until,
            "event_count": len(history_by_pid.get(pid, [])),
        })

    cards.sort(key=lambda r: (r["days_until"] is None, r["days_until"] if r["days_until"] is not None else 9999))
    funnel = [
        {"stage": s, "label": STAGE_LABELS.get(s, s), "count": counts.get(s, 0)}
        for s in [*STAGE_ORDER, "dead"]
    ]
    return {"success": True, "funnel": funnel, "cards": cards, "total": len(cards)}


# -- CRUD --
@router.get("/{prospect_id}")
def list_sample_events(prospect_id: int, db: Session = Depends(get_db)):
    try:
        prospect = db.query(Prospect).filter(Prospect.id == prospect_id, Prospect.is_deleted == 0).first()
        if not prospect:
            raise HTTPException(status_code=404, detail="Prospect not found")
        events = db.query(SampleEvent).filter(
            SampleEvent.prospect_id == prospect_id
        ).order_by(SampleEvent.created_at.asc()).all()
        return [_event_to_dict(ev) for ev in events]
    except HTTPException:
        raise
    except Exception as e:
        logger.exception("list_sample_events failed")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/{prospect_id}")
def create_sample_event(prospect_id: int, payload: SampleEventCreate, db: Session = Depends(get_db)):
    try:
        prospect = db.query(Prospect).filter(Prospect.id == prospect_id, Prospect.is_deleted == 0).first()
        if not prospect:
            raise HTTPException(status_code=404, detail="Prospect not found")

        prev = (
            db.query(SampleEvent)
            .filter(SampleEvent.prospect_id == prospect_id)
            .order_by(SampleEvent.created_at.desc())
            .first()
        )
        prev_note = (prev.note or "") if prev else ""
        event = SampleEvent(
            prospect_id=prospect_id,
            stage=payload.stage,
            note=payload.note,
            event_date=payload.event_date or datetime.now().strftime("%Y-%m-%d"),
            carrier=payload.carrier,
            tracking_number=payload.tracking_number,
            tracking_url=payload.tracking_url or _tracking_url(payload.carrier, payload.tracking_number),
            logistics_status=payload.logistics_status,
            expected_arrival=payload.expected_arrival,
            signed_date=payload.signed_date,
            test_purpose=payload.test_purpose,
            client_deadline=payload.client_deadline,
            ai_followup_prompt=_generate_followup_prompt(prospect, payload.stage, payload.note or "", prev_note),
        )
        db.add(event)
        try:
            _sync_prospect_from_event(db, prospect, event)
        except Exception as se:
            logger.warning("_sync_prospect non-fatal: %s", se)
        try:
            _create_sample_email_draft(db, prospect, event)
        except Exception as de:
            logger.warning("_create_draft non-fatal: %s", de)
        db.commit()
        db.refresh(event)
        logger.info("Sample event #%d stage=%s", event.id, event.stage)
        return _event_to_dict(event)
    except Exception as e:
        db.rollback()
        logger.exception("create_sample_event failed")
        raise HTTPException(status_code=500, detail="Create failed: " + str(e))


@router.put("/{prospect_id}/{event_id}")
def update_sample_event(prospect_id: int, event_id: int, payload: SampleEventUpdate, db: Session = Depends(get_db)):
    try:
        event = (
            db.query(SampleEvent)
            .filter(SampleEvent.id == event_id, SampleEvent.prospect_id == prospect_id)
            .first()
        )
        if not event:
            raise HTTPException(status_code=404, detail="Sample event not found")

        fields = (
            "stage", "note", "event_date", "carrier", "tracking_number",
            "tracking_url", "logistics_status", "expected_arrival",
            "signed_date", "test_purpose", "client_deadline",
            "ai_followup_prompt", "notified_at", "notified_channel",
        )
        for key in fields:
            value = getattr(payload, key)
            if value is not None:
                setattr(event, key, value)
        if not event.tracking_url:
            event.tracking_url = _tracking_url(event.carrier, event.tracking_number)

        prospect = db.query(Prospect).filter(Prospect.id == prospect_id).first()
        if prospect:
            try:
                _sync_prospect_from_event(db, prospect, event)
            except Exception as se:
                logger.warning("_sync_prospect non-fatal: %s", se)
            try:
                _create_sample_email_draft(db, prospect, event)
            except Exception as de:
                logger.warning("_create_draft non-fatal: %s", de)

        db.commit()
        db.refresh(event)
        return _event_to_dict(event)
    except Exception as e:
        db.rollback()
        logger.exception("update_sample_event failed")
        raise HTTPException(status_code=500, detail="Update failed: " + str(e))


@router.delete("/{prospect_id}/{event_id}")
def delete_sample_event(prospect_id: int, event_id: int, db: Session = Depends(get_db)):
    event = (
        db.query(SampleEvent)
        .filter(SampleEvent.id == event_id, SampleEvent.prospect_id == prospect_id)
        .first()
    )
    if not event:
        raise HTTPException(status_code=404, detail="Sample event not found")
    db.delete(event)
    db.commit()
    return {"success": True, "deleted": event_id}


# -- AI Prompt Generation --
@router.post("/{prospect_id}/generate-prompt")
async def generate_ai_prompt(prospect_id: int, payload: dict, db: Session = Depends(get_db)):
    prospect = db.query(Prospect).filter(Prospect.id == prospect_id, Prospect.is_deleted == 0).first()
    if not prospect:
        raise HTTPException(status_code=404, detail="Prospect not found")

    stage = payload.get("stage", "sent")
    note = payload.get("note", "") or ""
    carrier = payload.get("carrier", "") or ""
    tracking = payload.get("tracking_number", "") or ""
    tracking_url = payload.get("tracking_url") or _tracking_url(carrier, tracking) or ""
    company = prospect.company or "client"
    stage_label = STAGE_LABELS.get(stage, stage)

    system = "You are a foreign trade follow-up expert. "
    system += "Client: " + company + " Stage: " + stage_label + ". "
    system += "Write a professional follow-up message in Chinese. "
    if note:
        system += "Additional info: " + note + ". "
    if carrier and tracking:
        system += "Carrier: " + carrier + " Tracking: " + tracking + ". "
    if tracking_url:
        system += "Tracking URL: " + tracking_url + ". "
    system += "Return plain text only."

    try:
        loop = asyncio.get_event_loop()
        result = await loop.run_in_executor(None, call_simple, system, 0.5, 1024)
        return {"success": True, "prompt": result.strip()}
    except Exception as exc:
        logger.exception("AI prompt generation failed")
        return {"success": False, "error": str(exc)}


# -- Logistics Tracking --
@router.post("/check-tracking")
def check_tracking_status(db: Session = Depends(get_db)):
    try:
        from services.tracking_checker import run_check
        result = run_check()
        return {"success": True, "checked": result.get("checked",0), "updated": result.get("updated",0)}
    except Exception as e:
        logger.exception("check_tracking_status failed")
        raise HTTPException(status_code=500, detail=str(e))
