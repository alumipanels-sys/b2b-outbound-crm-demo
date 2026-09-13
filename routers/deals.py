"""Deals router — deal pipeline CRUD + funnel statistics."""

import logging
from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy.orm import Session

from database import get_db
from models import Deal, Prospect
from schemas import DealCreate, DealUpdate, DealOut, DealFunnelOut

logger = logging.getLogger(__name__)
router = APIRouter()

DEAL_STAGES = ["Initial contact", "Requirements confirmed", "Quotation sent", "Negotiating", "Won", "Lost"]


@router.get("/funnel", response_model=list[DealFunnelOut])
async def get_funnel(db: Session = Depends(get_db)):
    """Get deal funnel — count + total amount per stage (excluding deleted)."""
    funnel = []
    for stage in DEAL_STAGES:
        deals = (
            db.query(Deal)
            .filter(Deal.stage == stage, Deal.is_deleted == 0)
            .all()
        )
        funnel.append(DealFunnelOut(
            stage=stage,
            count=len(deals),
            total_amount=sum(d.amount or 0 for d in deals),
        ))
    return funnel


@router.get("", response_model=list[DealOut])
async def list_deals(
    stage: str = Query(None),
    prospect_id: int = Query(None),
    db: Session = Depends(get_db),
):
    """List all deals, optionally filtered by stage or prospect."""
    q = db.query(Deal).filter(Deal.is_deleted == 0)
    if stage:
        q = q.filter(Deal.stage == stage)
    if prospect_id:
        q = q.filter(Deal.prospect_id == prospect_id)
    items = q.order_by(Deal.updated_at.desc()).limit(200).all()
    return [DealOut.model_validate(d) for d in items]


@router.get("/{deal_id}", response_model=DealOut)
async def get_deal(deal_id: int, db: Session = Depends(get_db)):
    deal = db.query(Deal).filter(Deal.id == deal_id, Deal.is_deleted == 0).first()
    if not deal:
        raise HTTPException(status_code=404, detail="Deal not found")
    return DealOut.model_validate(deal)


@router.post("", response_model=DealOut)
async def create_deal(data: DealCreate, db: Session = Depends(get_db)):
    """Create a new deal."""
    prospect = db.query(Prospect).filter(
        Prospect.id == data.prospect_id, Prospect.is_deleted == 0
    ).first()
    if not prospect:
        raise HTTPException(status_code=404, detail="Prospect not found")

    deal = Deal(
        prospect_id=data.prospect_id,
        name=data.name,
        amount=data.amount,
        stage=data.stage,
        expected_date=data.expected_date,
        note=data.note,
    )
    db.add(deal)
    db.commit()
    db.refresh(deal)
    logger.info("Deal #%d created: %s for prospect #%d", deal.id, deal.name, data.prospect_id)
    return DealOut.model_validate(deal)


@router.put("/{deal_id}", response_model=DealOut)
async def update_deal(deal_id: int, data: DealUpdate, db: Session = Depends(get_db)):
    """Update a deal. Triggers auto case study generation when stage becomes 'won'."""
    deal = db.query(Deal).filter(Deal.id == deal_id, Deal.is_deleted == 0).first()
    if not deal:
        raise HTTPException(status_code=404, detail="Deal not found")

    old_stage = deal.stage
    update_data = data.model_dump(exclude_unset=True)
    for key, value in update_data.items():
        setattr(deal, key, value)
    deal.updated_at = datetime.utcnow()

    db.commit()
    db.refresh(deal)

    # Trigger auto case study on won
    if deal.stage == "won" and old_stage != "won":
        try:
            import asyncio
            from services.auto_case_study import run_pattern_miner
            asyncio.create_task(run_pattern_miner())
            logger.info("Auto case study triggered for deal #%d (just marked won)", deal.id)
        except Exception as e:
            logger.warning("Failed to trigger auto case study: %s", e)

    return DealOut.model_validate(deal)


@router.delete("/{deal_id}")
async def delete_deal(deal_id: int, db: Session = Depends(get_db)):
    """Soft-delete a deal."""
    deal = db.query(Deal).filter(Deal.id == deal_id, Deal.is_deleted == 0).first()
    if not deal:
        raise HTTPException(status_code=404, detail="Deal not found")
    deal.is_deleted = 1
    db.commit()
    return {"success": True, "message": "Deal moved to trash"}


@router.get("/prospect/{prospect_id}/summary", response_model=dict)
async def get_prospect_deal_summary(prospect_id: int, db: Session = Depends(get_db)):
    """Get deal summary for a prospect — total count, total value, top deals."""
    deals = (
        db.query(Deal)
        .filter(Deal.prospect_id == prospect_id, Deal.is_deleted == 0)
        .order_by(Deal.amount.desc())
        .all()
    )
    active = [d for d in deals if d.stage not in ("Won", "Lost")]
    won = [d for d in deals if d.stage == "Won"]
    return {
        "prospect_id": prospect_id,
        "total_deals": len(deals),
        "active_deals": len(active),
        "won_deals": len(won),
        "total_amount": sum(d.amount or 0 for d in deals),
        "active_amount": sum(d.amount or 0 for d in active),
        "deals": [DealOut.model_validate(d) for d in deals],
    }
