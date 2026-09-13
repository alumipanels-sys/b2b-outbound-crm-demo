"""First-run setup wizard endpoints."""

import logging

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session

from database import get_db
from models import Prospect, User, SystemSetting
from routers.auth import get_current_user
from services import setup_service
from services.auth_service import log_audit
from services.profile_categories import (
    DEFAULT_PROFILE_CATEGORIES,
    load_profile_categories,
    save_profile_categories,
)

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/setup", tags=["Setup"])

# ── 邮件签名模板（按客户画像 A-E + 通用）──
DEFAULT_SIGNATURES = {
    # A 工程型（技术导向，突出精度/公差/工程师对话）
    "A": "{{USER_NAME}} | Engineering Sales\n{{COMPANY}} - Precision Manufacturer\nISO 9001 Certified | Tight tolerances, batch to batch\nCustom specs | DFM review before production\n{{USER_EMAIL}} | {{WEBSITE}}",
    # B 品牌商（效率导向，突出稳定质量/交期/灵活起订）
    "B": "{{USER_NAME}} | Export Sales\n{{COMPANY}} - OEM Components\nStable quality | Competitive lead time | Flexible MOQ\n{{USER_EMAIL}} | {{WEBSITE}}",
    # C 销售型（新兴市场，突出友好/价值/样品支持）
    "C": "{{USER_NAME}} | International Sales Manager\n{{COMPANY}} - Export Manufacturer\nISO 9001 | Fast sampling | Small batch OK\n{{USER_EMAIL}} | {{WEBSITE}}",
    # D 服务型（直接快速，突出现货/交期/无最小起订）
    "D": "{{USER_NAME}} | Sales\n{{COMPANY}} - Component Supplier\nFast dispatch | Flexible quantities | Quick response\n{{USER_EMAIL}} | {{WEBSITE}}",
    # E 灵活型（维修中心，突出库存广度/任意数量/快速打样）
    "E": "{{USER_NAME}} | Sales Support\n{{COMPANY}} - Manufacturer\nWide range in stock | Any quantity | Fast sampling\n{{USER_EMAIL}} | {{WEBSITE}}",
    # 通用（兜底）
    "DEFAULT": "{{USER_NAME}} | {{COMPANY}}\nISO 9001 Certified | Custom specs OK\n{{USER_EMAIL}} | {{WEBSITE}}",
}
SIGNATURE_KEY_PREFIX = "signature_profile_"


def _load_signatures(db) -> dict:
    """读取签名模板：数据库有覆盖就用数据库的，否则用默认值。"""
    result = dict(DEFAULT_SIGNATURES)
    try:
        rows = db.query(SystemSetting).filter(
            SystemSetting.key.like(SIGNATURE_KEY_PREFIX + "%")
        ).all()
        for r in rows:
            key = r.key[len(SIGNATURE_KEY_PREFIX):]
            if key in result and r.value:
                result[key] = r.value
    except Exception:
        pass
    return result


class SignatureUpdate(BaseModel):
    profile: str
    template: str = ""


@router.get("/signatures")
def get_signatures(db: Session = Depends(get_db),
                   user: User = Depends(get_current_user)):
    """邮件签名模板（按客户画像 A-E + 通用）。"""
    return {"signatures": _load_signatures(db)}


@router.put("/signatures")
def update_signature(
    data: SignatureUpdate,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """保存某个画像的邮件签名模板（仅主账号/管理员）。"""
    if user.role not in ("owner", "admin"):
        raise HTTPException(status_code=403, detail="Only the owner/admin can configure the system")
    profile = (data.profile or "").strip().upper()
    if profile not in DEFAULT_SIGNATURES:
        raise HTTPException(status_code=400, detail="Invalid profile type")
    key = SIGNATURE_KEY_PREFIX + profile
    row = db.query(SystemSetting).filter(SystemSetting.key == key).first()
    if row:
        row.value = data.template
    else:
        db.add(SystemSetting(key=key, value=data.template))
    db.commit()
    log_audit(db, user, "kb_update", None, f"Updated email signature for profile {profile}")
    return {"ok": True, "signatures": _load_signatures(db)}


class SaveRequest(BaseModel):
    values: dict


class TestMailRequest(BaseModel):
    values: dict


class CompanyRequest(BaseModel):
    company: str = None
    user_name: str = None
    user_email: str = None
    website: str = None


class ProfileCategoryRequest(BaseModel):
    label: str


def _owner_only(user: User = Depends(get_current_user)) -> User:
    if user.role not in ("owner", "admin"):
        raise HTTPException(status_code=403, detail="Only the owner/admin can configure the system")
    return user


@router.get("/profile-categories")
def get_profile_categories(db: Session = Depends(get_db)):
    """客户画像分类列表：默认 A-E + 客户自定义（每个行业自己维护）。"""
    return {"categories": load_profile_categories(db)}


@router.get("/demo-mode")
def demo_mode():
    """是否演示版（前端据此显示“重置演示数据”按钮）。"""
    from config import DEMO_MODE
    return {"enabled": DEMO_MODE}


@router.post("/demo-reset")
def demo_reset(db: Session = Depends(get_db),
               user: User = Depends(_owner_only)):
    """一键重置演示数据（仅 DEMO_MODE=true 的版本可用）。"""
    from config import DEMO_MODE
    if not DEMO_MODE:
        raise HTTPException(status_code=404, detail="This version does not support demo-data reset")
    from services.demo_seed import reset_demo_data
    result = reset_demo_data(db)
    log_audit(db, user, "kb_update", None, "One-click demo-data reset")
    return result


@router.post("/profile-categories")
def add_profile_category(data: ProfileCategoryRequest, db: Session = Depends(get_db),
                         user: User = Depends(get_current_user)):
    label = (data.label or "").strip()
    if not label:
        raise HTTPException(status_code=400, detail="Category name cannot be empty")
    cats = load_profile_categories(db)
    n = 1
    while any(c.get("key") == "C%d" % n for c in cats):
        n += 1
    cats.append({"key": "C%d" % n, "label": label, "custom": True})
    save_profile_categories(db, cats)
    return {"categories": cats}


@router.put("/profile-categories/{key}")
def rename_profile_category(key: str, data: ProfileCategoryRequest,
                            db: Session = Depends(get_db),
                            user: User = Depends(get_current_user)):
    label = (data.label or "").strip()
    if not label:
        raise HTTPException(status_code=400, detail="Category name cannot be empty")
    cats = load_profile_categories(db)
    for c in cats:
        if c.get("key") == key:
            c["label"] = label
            save_profile_categories(db, cats)
            return {"categories": cats}
    raise HTTPException(status_code=404, detail="Category not found")


@router.delete("/profile-categories/{key}")
def delete_profile_category(key: str, db: Session = Depends(get_db),
                            user: User = Depends(get_current_user)):
    cats = load_profile_categories(db)
    if not any(c.get("key") == key for c in cats):
        raise HTTPException(status_code=404, detail="Category not found")
    used = db.query(Prospect).filter(
        Prospect.profile_type == key, Prospect.is_deleted == 0
    ).count()
    if used:
        raise HTTPException(
            status_code=400,
            detail="This category is used by %d customers and cannot be deleted — rename it instead" % used,
        )
    cats = [c for c in cats if c.get("key") != key]
    save_profile_categories(db, cats)
    return {"categories": cats}


@router.get("/status")
def status():
    return setup_service.setup_status()


@router.post("/save")
def save(data: SaveRequest, user: User = Depends(_owner_only)):
    return setup_service.save_values(data.values)


@router.post("/test-smtp")
async def test_smtp(data: TestMailRequest, user: User = Depends(_owner_only)):
    return await setup_service.test_smtp(data.values)


@router.post("/test-imap")
async def test_imap(data: TestMailRequest, user: User = Depends(_owner_only)):
    return await setup_service.test_imap(data.values)


@router.post("/test-ai")
async def test_ai(data: TestMailRequest, user: User = Depends(_owner_only)):
    """Test whichever AI providers are configured (form values or saved .env)."""
    return await setup_service.test_ai(data.values)


@router.post("/self-check")
async def self_check(user: User = Depends(_owner_only)):
    """One-click backend self-check: DB / scheduler / AI / SMTP / IMAP / KB / backup."""
    return await setup_service.self_check()


@router.post("/apply-company")
def apply_company(data: CompanyRequest, db: Session = Depends(get_db),
                  user: User = Depends(_owner_only)):
    """Save company info AND replace {{...}} placeholders in the knowledge base."""
    saved = setup_service.save_values({
        "company": data.company,
        "user_name": data.user_name,
        "user_email": data.user_email,
        "website": data.website,
    })
    replaced = setup_service.apply_company_info(
        db,
        company=data.company,
        user_email=data.user_email,
        website=data.website,
        user_name=data.user_name,
    )
    placeholders = setup_service.check_placeholders(db)
    return {"saved": saved, "replaced": replaced, "remaining_placeholders": placeholders}


@router.get("/placeholders")
def placeholders(db: Session = Depends(get_db)):
    return setup_service.check_placeholders(db)
