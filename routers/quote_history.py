"""报价历史 API — 按客户查看/维护 AI 提取的报价时间线。"""

import logging
from datetime import datetime
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy.orm import Session

from database import get_db
from models import Prospect, QuoteHistory, Interaction, Intelligence
from routers.auth import get_current_user
from schemas import QuoteHistoryOut, QuoteHistoryUpdate

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/quote-history", tags=["Quote History"])


def _to_out(qh: QuoteHistory, db: Session) -> QuoteHistoryOut:
    source_content = None
    if qh.source_id:
        try:
            ix = db.query(Interaction).filter(Interaction.id == qh.source_id).first()
            if ix:
                source_content = (ix.content or "")[:8000]
        except Exception:
            pass
    return QuoteHistoryOut(
        id=qh.id,
        prospect_id=qh.prospect_id,
        direction=qh.direction or "quote",
        source_type=qh.source_type,
        source_id=qh.source_id,
        source_subject=qh.source_subject,
        source_content=source_content,
        quote_date=qh.quote_date,
        product=qh.product,
        spec=qh.spec,
        qty=qh.qty,
        unit_price=qh.unit_price,
        total=qh.total,
        currency=qh.currency,
        terms=qh.terms,
        summary=qh.summary,
        ai_extracted=qh.ai_extracted,
        created_at=qh.created_at,
    )


@router.get("", response_model=list[QuoteHistoryOut])
def list_quotes(
    prospect_id: int = Query(..., description="客户 ID"),
    db: Session = Depends(get_db),
    user=Depends(get_current_user),
):
    """某客户的报价历史，按日期倒序。"""
    prospect = db.query(Prospect).filter(
        Prospect.id == prospect_id, Prospect.is_deleted == 0
    ).first()
    if not prospect:
        raise HTTPException(status_code=404, detail="Client not found")
    items = (
        db.query(QuoteHistory)
        .filter(QuoteHistory.prospect_id == prospect_id, QuoteHistory.is_deleted == 0)
        .order_by(QuoteHistory.quote_date.desc(), QuoteHistory.id.desc())
        .all()
    )
    return [_to_out(q, db) for q in items]


@router.post("", response_model=QuoteHistoryOut)
def create_quote(
    payload: QuoteHistoryUpdate,
    db: Session = Depends(get_db),
    user=Depends(get_current_user),
):
    """手工新增一条报价记录（或确认 AI 草稿后修正）。"""
    prospect = db.query(Prospect).filter(
        Prospect.id == payload.prospect_id, Prospect.is_deleted == 0
    ).first()
    if not prospect:
        raise HTTPException(status_code=404, detail="Client not found")
    qh = QuoteHistory(
        tenant_id=prospect.tenant_id,
        owner_user_id=user.id if user else prospect.owner_user_id,
        prospect_id=payload.prospect_id,
        direction=payload.direction or "quote",
        source_type=payload.source_type or "manual",
        source_id=payload.source_id,
        source_subject=payload.source_subject,
        quote_date=payload.quote_date or datetime.utcnow().strftime("%Y-%m-%d"),
        product=payload.product or "",
        spec=payload.spec or "",
        qty=payload.qty or "",
        unit_price=payload.unit_price or "",
        total=payload.total or "",
        currency=payload.currency or "",
        terms=payload.terms or "",
        summary=payload.summary or "",
        ai_extracted=0,
    )
    db.add(qh)
    db.commit()
    db.refresh(qh)
    return _to_out(qh, db)


@router.put("/{quote_id}", response_model=QuoteHistoryOut)
def update_quote(
    quote_id: int,
    payload: QuoteHistoryUpdate,
    db: Session = Depends(get_db),
    user=Depends(get_current_user),
):
    """修正一条报价记录（人工确认 AI 草稿，或改错）。"""
    qh = db.query(QuoteHistory).filter(
        QuoteHistory.id == quote_id, QuoteHistory.is_deleted == 0
    ).first()
    if not qh:
        raise HTTPException(status_code=404, detail="Quote record not found")
    for field in ("direction", "quote_date", "product", "spec", "qty", "unit_price",
                  "total", "currency", "terms", "summary", "source_subject"):
        val = getattr(payload, field, None)
        if val is not None:
            setattr(qh, field, val)
    qh.ai_extracted = 0  # 人工确认
    db.commit()
    db.refresh(qh)
    return _to_out(qh, db)


@router.delete("/{quote_id}", response_model=dict)
def delete_quote(
    quote_id: int,
    db: Session = Depends(get_db),
    user=Depends(get_current_user),
):
    qh = db.query(QuoteHistory).filter(QuoteHistory.id == quote_id).first()
    if not qh:
        raise HTTPException(status_code=404, detail="Quote record not found")
    qh.is_deleted = 1
    db.commit()
    return {"success": True, "id": quote_id}


@router.post("/extract", response_model=dict)
def trigger_extract(
    prospect_id: int = Query(...),
    db: Session = Depends(get_db),
    user=Depends(get_current_user),
):
    """手动触发 AI 提取该客户的报价历史（扫描最近 40 条互动）。"""
    from services.quote_extractor import extract_quotes_for_prospect
    added = extract_quotes_for_prospect(prospect_id)
    return {"success": True, "added": added}


@router.get("/panorama", response_model=dict)
def get_panorama(
    prospect_id: int = Query(...),
    db: Session = Depends(get_db),
    user=Depends(get_current_user),
):
    """读取该客户的对话全景分析（如已生成）。"""
    intel = (
        db.query(Intelligence)
        .filter(Intelligence.prospect_id == prospect_id)
        .first()
    )
    if not intel or not intel.dialogue_panorama:
        return {"exists": False, "report": None, "generated_at": None}
    try:
        import json as _json
        report = _json.loads(intel.dialogue_panorama)
    except Exception:
        report = None
    return {
        "exists": True,
        "report": report,
        "generated_at": intel.dialogue_panorama_at.isoformat() if intel.dialogue_panorama_at else None,
    }


@router.post("/panorama", response_model=dict)
def generate_panorama(
    prospect_id: int = Query(...),
    db: Session = Depends(get_db),
    user=Depends(get_current_user),
):
    """生成（或刷新）该客户的对话全景分析。"""
    from services.quote_extractor import generate_dialogue_panorama
    return generate_dialogue_panorama(prospect_id)
