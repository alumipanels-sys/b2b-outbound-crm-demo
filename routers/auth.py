"""Authentication & user management API (stage 3).

Endpoints validate tokens per-request for now; a global middleware
comes in stage 4.
"""

import logging
import random
import time

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, EmailStr
from sqlalchemy.orm import Session

from database import get_db
from models import Tenant, User
from services import auth_service

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/auth", tags=["Auth"])

# ── 密码找回：验证码存内存（单进程本地部署够用），10 分钟有效 ──
_reset_codes: dict[str, dict] = {}
_RESET_CODE_TTL = 600          # 10 分钟
_RESET_CODE_LEN = 6
_RESET_MAX_ATTEMPTS = 5


class SetupOwnerRequest(BaseModel):
    name: str
    email: EmailStr
    password: str


class LoginRequest(BaseModel):
    email: EmailStr
    password: str


class ForgotPasswordRequest(BaseModel):
    email: EmailStr


class ResetPasswordRequest(BaseModel):
    email: EmailStr
    code: str
    password: str


class CreateUserRequest(BaseModel):
    name: str
    email: EmailStr
    password: str
    role: str = "member"


class UpdateUserRequest(BaseModel):
    name: str = None
    email: EmailStr = None
    password: str = None
    role: str = None
    status: str = None
    email_signature: str = None


@router.get("/status")
def auth_status(db: Session = Depends(get_db)):
    """前端判断：系统是否已初始化（已有账号）。无需登录。"""
    from config import DEMO_MODE
    return {"initialized": auth_service.has_users(db), "demo_mode": DEMO_MODE}


def _bearer_token(request: Request) -> str:
    auth = request.headers.get("Authorization", "")
    if auth.startswith("Bearer "):
        return auth[7:].strip()
    return ""


def _current_user(request: Request, db: Session) -> User:
    user = auth_service.validate_token(db, _bearer_token(request))
    if not user:
        raise HTTPException(status_code=401, detail="Please sign in first")
    return user


def get_current_user(request: Request, db: Session = Depends(get_db)) -> User:
    """API dependency: returns the logged-in user.
    首次运行（还没有任何账号）返回引导伪主账号，保证初始化前系统全部可用；
    一旦创建了主账号，所有 API 都必须带有效令牌。"""
    if not auth_service.has_users(db):
        return User(id=None, tenant_id=None, role="owner", name="bootstrap", email="bootstrap")
    return _current_user(request, db)


def _require_owner(user: User) -> None:
    if user.role != "owner":
        raise HTTPException(status_code=403, detail="Only the owner can perform this action")


def _user_out(u: User) -> dict:
    return {
        "id": u.id,
        "name": u.name,
        "email": u.email,
        "role": u.role,
        "status": u.status,
        "email_signature": u.email_signature or "",
        "default_sender": u.default_sender or "",
        "last_login_at": u.last_login_at.isoformat() if u.last_login_at else None,
        "created_at": u.created_at.isoformat() if u.created_at else None,
    }


@router.post("/setup-owner")
def setup_owner(data: SetupOwnerRequest, db: Session = Depends(get_db)):
    """首次运行：创建主账号（仅系统还没有任何账号时可用）。"""
    if auth_service.has_users(db):
        raise HTTPException(status_code=403, detail="System already initialized - sign in from the login page")
    try:
        owner = auth_service.create_owner(db, data.name.strip(), data.email, data.password)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    token = auth_service.issue_token(db, owner)
    from services.license import tenant_needs_activation
    return {
        "token": token,
        "user": _user_out(owner),
        "need_activation": tenant_needs_activation(db, owner.tenant_id),
    }


@router.post("/login")
def login(data: LoginRequest, db: Session = Depends(get_db)):
    user = auth_service.authenticate(db, data.email, data.password)
    if not user:
        raise HTTPException(status_code=401, detail="Incorrect email or password")
    # 试用到期 / 激活码异常 → 拦截登录
    try:
        from services.license import check_tenant_license
        check_tenant_license(db, user.tenant_id)
    except ValueError as e:
        raise HTTPException(status_code=403, detail=f"License error: {e} (contact the vendor for a valid activation code)")
    token = auth_service.issue_token(db, user)
    auth_service.log_audit(db, user, "login", f"user#{user.id}")
    from services.license import tenant_needs_activation
    return {
        "token": token,
        "user": _user_out(user),
        "need_activation": tenant_needs_activation(db, user.tenant_id),
    }


@router.post("/forgot-password")
async def forgot_password(data: ForgotPasswordRequest, db: Session = Depends(get_db)):
    """忘记密码：给注册邮箱发 6 位验证码（10 分钟内有效）。"""
    email = data.email.lower().strip()
    user = db.query(User).filter(User.email == email, User.status == "active").first()
    # 邮箱不存在也返回成功，避免暴露账号是否存在
    if not user:
        return {"ok": True, "sent": False}

    # 防刷：同一邮箱 60 秒内只能发一次
    now = time.time()
    existing = _reset_codes.get(email)
    if existing and now - existing.get("created", 0) < 60:
        remain = int(60 - (now - existing["created"]))
        raise HTTPException(status_code=429, detail=f"Code sent; try again in {remain} seconds")

    code = "".join(str(random.randint(0, 9)) for _ in range(_RESET_CODE_LEN))
    _reset_codes[email] = {
        "code": code,
        "created": now,
        "attempts": 0,
    }

    subject = "B2B Outbound OS - password reset code"
    body = (
        f"Hello {user.name or ''},\n\n"
        f"You are resetting your B2B Outbound OS password. Your verification code is: {code}\n\n"
        f"The code is valid for 10 minutes. Do not share it.\n"
        f"If this was not you, ignore this email."
    )
    try:
        from services.email_service import send_email
        ok = await send_email(email, subject, body)
        if not ok:
            _reset_codes.pop(email, None)
            raise HTTPException(status_code=500, detail="Email sending failed; check the sending mailbox in System Settings")
    except HTTPException:
        raise
    except Exception as e:
        _reset_codes.pop(email, None)
        logger.error("forgot-password email failed: %s", e)
        raise HTTPException(status_code=500, detail="Email sending failed; try again later")

    return {"ok": True, "sent": True}


@router.post("/reset-password")
def reset_password(data: ResetPasswordRequest, db: Session = Depends(get_db)):
    """用验证码重置密码。"""
    email = data.email.lower().strip()
    entry = _reset_codes.get(email)
    if not entry:
        raise HTTPException(status_code=400, detail="Code is invalid or expired - request a new one")
    if time.time() - entry["created"] > _RESET_CODE_TTL:
        _reset_codes.pop(email, None)
        raise HTTPException(status_code=400, detail="Code expired - request a new one")
    if entry["attempts"] >= _RESET_MAX_ATTEMPTS:
        _reset_codes.pop(email, None)
        raise HTTPException(status_code=400, detail="Too many attempts - request a new code")
    if data.code.strip() != entry["code"]:
        entry["attempts"] += 1
        raise HTTPException(status_code=400, detail="Incorrect code")
    if len(data.password) < 6:
        raise HTTPException(status_code=400, detail="New password must be at least 6 characters")

    user = db.query(User).filter(User.email == email, User.status == "active").first()
    if not user:
        _reset_codes.pop(email, None)
        raise HTTPException(status_code=400, detail="Account does not exist or is disabled")

    user.password_hash = auth_service.hash_password(data.password)
    db.commit()
    auth_service.log_audit(db, user, "reset_password", f"user#{user.id}", "Password reset with email code")
    _reset_codes.pop(email, None)
    return {"ok": True}


@router.post("/logout")
def logout(request: Request, db: Session = Depends(get_db)):
    auth_service.revoke_token(db, _bearer_token(request))
    return {"ok": True}


@router.get("/me")
def me(request: Request, db: Session = Depends(get_db)):
    user = _current_user(request, db)
    from services.license import tenant_needs_activation
    return {"user": _user_out(user), "need_activation": tenant_needs_activation(db, user.tenant_id)}


@router.get("/users")
def list_users(request: Request, db: Session = Depends(get_db)):
    user = _current_user(request, db)
    if user.role not in ("owner", "admin"):
        raise HTTPException(status_code=403, detail="No permission to view member list")
    rows = db.query(User).filter(User.tenant_id == user.tenant_id, User.status != "deleted").order_by(User.id.asc()).all()
    return {"users": [_user_out(u) for u in rows]}


class DefaultSenderRequest(BaseModel):
    sender_key: str = ""


@router.post("/default-sender")
def set_default_sender(data: DefaultSenderRequest, request: Request, db: Session = Depends(get_db)):
    """设置当前账号的默认发件邮箱（第一次选择后固定，防止手滑选错邮箱）。"""
    user = _current_user(request, db)
    key = (data.sender_key or "").strip()
    if key:
        from models import EmailAccount
        acc = db.query(EmailAccount).filter(EmailAccount.key == key).first()
        if not acc:
            raise HTTPException(status_code=400, detail="Mailbox account does not exist")
    user.default_sender = key or None
    db.commit()
    return {"user": _user_out(user)}


@router.post("/users")
def create_user(request: Request, data: CreateUserRequest, db: Session = Depends(get_db)):
    """主账号添加子账号（按账号数上限校验）。"""
    owner = _current_user(request, db)
    _require_owner(owner)
    if data.role not in ("owner", "admin", "member"):
        raise HTTPException(status_code=400, detail="Invalid role")
    if db.query(User).filter(User.email == data.email.lower().strip()).first():
        raise HTTPException(status_code=400, detail="This email already exists")

    tenant = db.query(Tenant).filter(Tenant.id == owner.tenant_id).first()
    current_count = db.query(User).filter(User.tenant_id == owner.tenant_id).count()
    if tenant and tenant.max_users and current_count >= tenant.max_users:
        raise HTTPException(status_code=400, detail=f"Account limit reached ({tenant.max_users} accounts) - cannot add more")

    try:
        new_user = User(
            tenant_id=owner.tenant_id,
            role=data.role,
            name=data.name.strip(),
            email=data.email.lower().strip(),
            password_hash=auth_service.hash_password(data.password),
        )
        db.add(new_user)
        db.commit()
        db.refresh(new_user)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    auth_service.log_audit(db, owner, "create_user", f"user#{new_user.id}", f"Added member {new_user.email}（{new_user.role}）")
    return {"user": _user_out(new_user)}


@router.patch("/users/{user_id}")
def update_user(user_id: int, request: Request, data: UpdateUserRequest, db: Session = Depends(get_db)):
    """主账号修改子账号（改名/重置密码/改角色/停用）。"""
    owner = _current_user(request, db)
    _require_owner(owner)
    target = db.query(User).filter(User.id == user_id, User.tenant_id == owner.tenant_id).first()
    if not target:
        raise HTTPException(status_code=404, detail="User not found")
    if target.id == owner.id:
        raise HTTPException(status_code=400, detail="You cannot edit your own account")

    if data.name is not None:
        target.name = data.name.strip()
    if data.email is not None:
        if db.query(User).filter(User.email == data.email.lower().strip(), User.id != target.id).first():
            raise HTTPException(status_code=400, detail="This email already exists")
        target.email = data.email.lower().strip()
    if data.password:
        if len(data.password) < 6:
            raise HTTPException(status_code=400, detail="Password must be at least 6 characters")
        target.password_hash = auth_service.hash_password(data.password)
    if data.role is not None:
        if data.role not in ("owner", "admin", "member"):
            raise HTTPException(status_code=400, detail="Invalid role")
        target.role = data.role
    if data.status is not None:
        if data.status not in ("active", "disabled"):
            raise HTTPException(status_code=400, detail="Invalid status")
        target.status = data.status
    if data.email_signature is not None:
        target.email_signature = data.email_signature.strip()
    db.commit()
    db.refresh(target)
    auth_service.log_audit(db, owner, "update_user", f"user#{target.id}", f"Updated member {target.email}")
    return {"user": _user_out(target)}


@router.delete("/users/{user_id}")
def delete_user(user_id: int, request: Request, db: Session = Depends(get_db)):
    """主账号删除子账号（软删除为 deleted，保留其数据以便审计/交接）。"""
    owner = _current_user(request, db)
    _require_owner(owner)
    target = db.query(User).filter(User.id == user_id, User.tenant_id == owner.tenant_id).first()
    if not target:
        raise HTTPException(status_code=404, detail="User not found")
    if target.id == owner.id:
        raise HTTPException(status_code=400, detail="You cannot delete your own account")
    target.status = "deleted"
    db.commit()
    auth_service.log_audit(db, owner, "delete_user", f"user#{target.id}", f"Deleted member {target.email}")
    return {"ok": True}
