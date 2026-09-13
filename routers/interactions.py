"""Interactions router — contact records + AI analysis.

This is the AUDIT TRAIL for every customer touchpoint.
Every outbound message (email, LinkedIn, phone, WhatsApp) and
every inbound reply is logged here for full conversation context.
"""

import logging
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy.orm import Session

from database import get_db
from models import Interaction, Prospect
from schemas import InteractionOut
from services.reply_signal import apply_reply_signal
from services.company_sync import sync_company_main

logger = logging.getLogger(__name__)
router = APIRouter()


@router.get("/inbox", response_model=list[InteractionOut])
async def get_inbox(
    limit: int = Query(50, ge=1, le=500),
    q: str | None = Query(None, description="按发件人/主题/内容/客户搜索"),
    db: Session = Depends(get_db),
):
    """Get all inbound interactions (replies), newest first."""
    query = db.query(Interaction).filter(
        Interaction.direction == "inbound",
        Interaction.channel.notin_(["note", "other"]),
    )
    if q:
        like = f"%{q.strip()}%"
        query = query.filter(
            (Interaction.email_from.ilike(like))
            | (Interaction.subject.ilike(like))
            | (Interaction.content.ilike(like))
        )
    items = query.order_by(Interaction.interacted_at.desc()).limit(limit).all()
    result = []
    for i in items:
        out = InteractionOut.model_validate(i)
        if i.prospect_id:
            p = db.query(Prospect).filter(Prospect.id == i.prospect_id).first()
            if p:
                out.company = p.company
                if p.is_deleted:
                    continue  # 客户已删除，收件箱不再展示
            else:
                continue  # 客户记录已不存在
        result.append(out)
    return result


# ── Request body for creating interactions ──
class InteractionCreate(BaseModel):
    prospect_id: int
    direction: str  # "outbound" or "inbound"
    channel: str    # "email", "linkedin", "phone", "whatsapp"
    subject: str | None = None
    content: str | None = None
    sequence_id: int | None = None
    interacted_at: str | None = None  # ISO date string for custom date


@router.post("", response_model=InteractionOut)
async def create_interaction(data: InteractionCreate, db: Session = Depends(get_db)):
    """Create an interaction record (our outbound message or customer inbound reply)."""
    if data.direction not in ("inbound", "outbound"):
        raise HTTPException(status_code=400, detail="direction must be inbound or outbound")

    prospect = db.query(Prospect).filter(Prospect.id == data.prospect_id, Prospect.is_deleted == 0).first()
    if not prospect:
        raise HTTPException(status_code=404, detail="Prospect not found")

    interaction = Interaction(
        prospect_id=data.prospect_id,
        direction=data.direction,
        channel=data.channel,
        subject=data.subject,
        content=data.content,
        sequence_id=data.sequence_id,
    )
    if data.interacted_at:
        try:
            interaction.interacted_at = datetime.fromisoformat(data.interacted_at)
        except Exception:
            interaction.interacted_at = datetime.now(timezone.utc)
    else:
        interaction.interacted_at = datetime.now(timezone.utc)
    db.add(interaction)
    db.flush()
    if data.direction == "inbound":
        apply_reply_signal(db, interaction, prospect)

    from datetime import date, timedelta
    from routers.sequences import _action_interval, _action_label

    ch = data.channel or "email"
    if data.direction == "outbound":
        action = f"{ch}_sent"
    else:
        intent = (interaction.reply_intent or "").upper()
        if intent in (
            "HOT_LEAD", "SAMPLE", "SAMPLE_ADDRESS", "QUOTE_REQUEST", "PRICING",
            "INFORMATION_REQUEST", "COOPERATION", "POSITIVE_ENGAGEMENT", "MEETING", "REFERRAL",
        ):
            action = "replied_positive"
        elif intent in ("NEGATIVE", "REJECTION", "NO_INTEREST"):
            action = "replied_negative"
        else:
            action = "replied_neutral"

    days = _action_interval(action, ch, (prospect.country or ""))
    next_date = date.today() + timedelta(days=days)
    label = _action_label(action, ch, days)
    prospect.next_follow_date = next_date.isoformat()
    prospect.reminder_note = f"[Auto] {label}"
    prospect.reminder_updated_at = datetime.utcnow()
    prospect.updated_at = datetime.utcnow()
    prospect.last_edited_at = datetime.utcnow()
    sync_company_main(db, prospect)
    db.add(prospect)

    db.commit()
    db.refresh(interaction)
    logger.info("Interaction #%d recorded: %s %s for prospect #%d",
                interaction.id, data.direction, data.channel, data.prospect_id)
    return InteractionOut.model_validate(interaction)


@router.put("/inbox/{interaction_id}/read", response_model=dict)
async def mark_inbox_read(interaction_id: int, db: Session = Depends(get_db)):
    """Mark an inbox interaction as read."""
    interaction = db.query(Interaction).filter(Interaction.id == interaction_id).first()
    if not interaction:
        raise HTTPException(status_code=404, detail="Interaction not found")
    interaction.is_read = 1
    db.commit()
    return {"success": True, "id": interaction_id}


@router.put("/inbox/batch-read", response_model=dict)
async def batch_mark_read(payload: dict, db: Session = Depends(get_db)):
    """Batch mark inbox interactions as read or unread."""
    ids = payload.get("ids") or []
    is_read = int(payload.get("is_read", 1))
    if not isinstance(ids, list) or not ids:
        raise HTTPException(status_code=400, detail="ids must be a non-empty list")
    updated = (
        db.query(Interaction)
        .filter(Interaction.id.in_(ids))
        .update({"is_read": is_read}, synchronize_session=False)
    )
    db.commit()
    return {"success": True, "updated": updated, "is_read": is_read}


# ── 公司时间线：合并同一家公司所有联系人的互动记录 ──
@router.get("/company/{prospect_id}", response_model=list[dict])
async def get_company_timeline(prospect_id: int, db: Session = Depends(get_db)):
    """Return all interaction records for a company, tagged by contact name, oldest first."""
    prospect = db.query(Prospect).filter(
        Prospect.id == prospect_id, Prospect.is_deleted == 0
    ).first()
    if not prospect:
        raise HTTPException(status_code=404, detail="Prospect not found")

    colleagues = db.query(Prospect).filter(
        Prospect.company == (prospect.company or "").strip(),
        Prospect.is_deleted == 0,
    ).all()
    ids = [c.id for c in colleagues] or [-1]
    contact_map = {c.id: ((c.contact or "").strip() or c.company) for c in colleagues}

    rows = (
        db.query(Interaction)
        .filter(Interaction.prospect_id.in_(ids))
        .order_by(Interaction.interacted_at.asc(), Interaction.id.asc())
        .all()
    )
    result = []
    for i in rows:
        d = InteractionOut.model_validate(i).model_dump()
        d["contact"] = contact_map.get(i.prospect_id, "")
        result.append(d)
    return result


@router.get("/{prospect_id}", response_model=list[InteractionOut])
async def get_interactions(
    prospect_id: int,
    reviewed: int | None = Query(None),
    db: Session = Depends(get_db),
):
    """Get all interactions for a prospect, newest first."""
    prospect = db.query(Prospect).filter(
        Prospect.id == prospect_id, Prospect.is_deleted == 0
    ).first()
    if not prospect:
        raise HTTPException(status_code=404, detail="Prospect not found")

    q = db.query(Interaction).filter(Interaction.prospect_id == prospect_id)
    if reviewed is not None:
        q = q.filter(Interaction.human_reviewed == reviewed)

    items = q.order_by(Interaction.interacted_at.desc()).limit(50).all()
    return [InteractionOut.model_validate(i) for i in items]


@router.get("/{prospect_id}/context", response_model=dict)
async def get_conversation_context(prospect_id: int, db: Session = Depends(get_db)):
    """Get the full conversation context."""
    prospect = db.query(Prospect).filter(
        Prospect.id == prospect_id, Prospect.is_deleted == 0
    ).first()
    if not prospect:
        raise HTTPException(status_code=404, detail="Prospect not found")

    interactions = (
        db.query(Interaction)
        .filter(Interaction.prospect_id == prospect_id)
        .order_by(Interaction.interacted_at.asc())
        .limit(50)
        .all()
    )

    context = []
    for i in interactions:
        context.append({
            "date": str(i.interacted_at) if i.interacted_at else "unknown",
            "direction": i.direction,
            "channel": i.channel,
            "subject": i.subject,
            "content_preview": (i.content or "")[:200],
            "reply_intent": i.reply_intent,
            "ai_suggested_action": i.ai_suggested_action,
        })

    return {
        "prospect_id": prospect_id,
        "total_touchpoints": len(context),
        "conversation": context,
    }


@router.put("/{interaction_id}/review", response_model=InteractionOut)
async def review_interaction(
    interaction_id: int,
    decision: str = "",
    db: Session = Depends(get_db),
):
    """Mark an interaction as human-reviewed with optional decision note."""
    interaction = db.query(Interaction).filter(Interaction.id == interaction_id).first()
    if not interaction:
        raise HTTPException(status_code=404, detail="Interaction not found")

    interaction.human_reviewed = 1
    interaction.human_decision = decision
    db.commit()
    db.refresh(interaction)
    return InteractionOut.model_validate(interaction)


@router.delete("/{interaction_id}")
async def delete_interaction(interaction_id: int, db: Session = Depends(get_db)):
    """Hard-delete a single interaction record."""
    interaction = db.query(Interaction).filter(Interaction.id == interaction_id).first()
    if not interaction:
        raise HTTPException(status_code=404, detail="Interaction not found")
    db.delete(interaction)
    db.commit()
    return {"success": True, "deleted": interaction_id}
