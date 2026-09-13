"""License (activation code) API."""

import logging
from datetime import date, datetime

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session

from database import get_db
from models import Tenant, User
from routers.auth import get_current_user
from services import license as license_service

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/license", tags=["License"])


class ActivateRequest(BaseModel):
    license_key: str


@router.get("/status")
def license_status(db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    if not user or not user.tenant_id:
        return {"activated": False, "error": "No owner account has been created yet"}
    tenant = db.query(Tenant).filter(Tenant.id == user.tenant_id).first()
    if not tenant:
        return {"activated": False, "error": "Tenant not found"}

    info = {
        "activated": bool(tenant.license_key),
        "company": tenant.name,
        "plan": tenant.plan,
        "max_users": tenant.max_users,
        "valid": None,
    }
    if tenant.license_key:
        try:
            payload = license_service.validate_license(tenant.license_key)
            info["valid"] = True
            info["license_company"] = payload["company"]
            info["license_max_users"] = payload["max_users"]
            info["license_plan"] = payload["plan"]
            info["expires"] = payload.get("expires")
            info["trial_days"] = payload.get("trial_days")
            if payload.get("trial_days"):
                if not tenant.activated_at:
                    info["activated"] = False
                    info["reason"] = "not_activated"
                    info["activate_by"] = payload.get("activate_by")
                else:
                    from datetime import timedelta
                    exp = tenant.activated_at + timedelta(days=int(payload["trial_days"]))
                    info["expires"] = exp.date().isoformat()
        except ValueError as e:
            info["valid"] = False
            info["error"] = str(e)
    return info


@router.post("/activate")
def activate(data: ActivateRequest, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    if user.role != "owner":
            raise HTTPException(status_code=403, detail="Only the owner can activate")
    tenant = db.query(Tenant).filter(Tenant.id == user.tenant_id).first()
    if not tenant:
        raise HTTPException(status_code=404, detail="Tenant not found")
    try:
        payload = license_service.validate_license(data.license_key.strip())
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))

    # 双期限体验码：激活窗口校验（签发后 N 天内必须激活）
    if payload.get("activate_by"):
        try:
            deadline = date.fromisoformat(payload["activate_by"])
        except ValueError:
            raise HTTPException(status_code=400, detail="Activation code window format is invalid")
        if deadline < date.today():
            raise HTTPException(status_code=400, detail=f"Activation code window has expired (activate before {deadline}) — please request a new trial code")

    tenant.name = payload["company"]
    tenant.plan = payload["plan"]
    tenant.max_users = payload["max_users"]
    tenant.license_key = data.license_key.strip()
    if tenant.activated_at is None:
        tenant.activated_at = datetime.utcnow()
        from datetime import timedelta
        if payload.get("trial_days"):
            tenant.expires_at = tenant.activated_at + timedelta(days=int(payload["trial_days"]))
        else:
            tenant.expires_at = None  # 永久买断
    tenant.status = "active"
    db.commit()

    from services.auth_service import log_audit
    log_audit(db, user, "activate_license", f"tenant#{tenant.id}",
              f"Activated {payload['company']}: {payload['max_users']} users, plan {payload['plan']}")
    return {
        "ok": True,
        "company": tenant.name,
        "plan": tenant.plan,
        "max_users": tenant.max_users,
        "expires": payload.get("expires"),
        "trial_days": payload.get("trial_days"),
        "activated_at": tenant.activated_at.isoformat() if tenant.activated_at else None,
    }
