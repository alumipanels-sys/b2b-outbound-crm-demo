"""Audit log API — master account can see what every sub-account did."""

from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from database import get_db
from models import AuditLog, User
from routers.auth import get_current_user

router = APIRouter(prefix="/api/audit", tags=["Audit"])


@router.get("/logs")
def audit_logs(
    user_id: Optional[int] = Query(None),
    action: Optional[str] = Query(None),
    limit: int = Query(100, ge=1, le=500),
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """审计记录：主账号/管理员看本租户全部；成员只能看自己的。"""
    q = db.query(AuditLog)
    if user and user.id:
        if user.role in ("owner", "admin"):
            if user.tenant_id:
                q = q.filter(AuditLog.tenant_id == user.tenant_id)
        else:
            q = q.filter(AuditLog.user_id == user.id)
    if user_id is not None:
        if user.role not in ("owner", "admin"):
            raise HTTPException(status_code=403, detail="You cannot view other users' audit logs")
        q = q.filter(AuditLog.user_id == user_id)
    if action:
        q = q.filter(AuditLog.action == action)
    rows = q.order_by(AuditLog.created_at.desc()).limit(limit).all()
    return {
        "logs": [
            {
                "id": r.id,
                "user_id": r.user_id,
                "action": r.action,
                "target": r.target,
                "detail": r.detail,
                "created_at": r.created_at.isoformat() if r.created_at else None,
            }
            for r in rows
        ]
    }
