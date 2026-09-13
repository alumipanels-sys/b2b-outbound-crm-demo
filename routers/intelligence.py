"""Intelligence router — manage prospect intelligence data."""

import logging
from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from database import get_db
from models import Intelligence, Prospect
from schemas import IntelligenceOut, IntelligenceUpdate

logger = logging.getLogger(__name__)
router = APIRouter()


@router.get("/{prospect_id}", response_model=IntelligenceOut)
async def get_intelligence(prospect_id: int, db: Session = Depends(get_db)):
    """Get intelligence record for a prospect (creates one if none exists)."""
    prospect = db.query(Prospect).filter(
        Prospect.id == prospect_id, Prospect.is_deleted == 0
    ).first()
    if not prospect:
        raise HTTPException(status_code=404, detail="Prospect not found")

    intel = db.query(Intelligence).filter(Intelligence.prospect_id == prospect_id).first()
    if not intel:
        intel = Intelligence(prospect_id=prospect_id)
        db.add(intel)
        db.commit()
        db.refresh(intel)

    return IntelligenceOut.model_validate(intel)


@router.put("/{prospect_id}", response_model=IntelligenceOut)
async def update_intelligence(
    prospect_id: int,
    data: IntelligenceUpdate,
    db: Session = Depends(get_db),
):
    """Update intelligence fields (website content, LinkedIn, hiring content)."""
    prospect = db.query(Prospect).filter(
        Prospect.id == prospect_id, Prospect.is_deleted == 0
    ).first()
    if not prospect:
        raise HTTPException(status_code=404, detail="Prospect not found")

    intel = db.query(Intelligence).filter(Intelligence.prospect_id == prospect_id).first()
    if not intel:
        intel = Intelligence(prospect_id=prospect_id)
        db.add(intel)

    if data.website_content is not None:
        intel.website_content = data.website_content
    if data.linkedin_content is not None:
        intel.linkedin_content = data.linkedin_content
        intel.linkedin_pasted_at = datetime.utcnow()
    if data.hiring_content is not None:
        intel.hiring_content = data.hiring_content
    if data.screenshot_analysis is not None:
        intel.screenshot_analysis = data.screenshot_analysis

    intel.updated_at = datetime.utcnow()
    db.commit()
    db.refresh(intel)
    return IntelligenceOut.model_validate(intel)
