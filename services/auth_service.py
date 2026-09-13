"""Authentication service — multi-user account system.

Stage 2: password hashing, session tokens, first-run bootstrap.
API endpoints and middleware come in later stages.
"""

import hashlib
import hmac
import secrets
from datetime import datetime, timedelta

from sqlalchemy.orm import Session

from models import AuditLog, AuthSession, Tenant, User

SESSION_DAYS = 30
PBKDF2_ITERATIONS = 200_000


def hash_password(password: str) -> str:
    salt = secrets.token_hex(16)
    digest = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), bytes.fromhex(salt), PBKDF2_ITERATIONS)
    return f"{salt}${digest.hex()}"


def verify_password(password: str, stored: str) -> bool:
    try:
        salt, expected = stored.split("$", 1)
        digest = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), bytes.fromhex(salt), PBKDF2_ITERATIONS)
        return hmac.compare_digest(digest.hex(), expected)
    except Exception:
        return False


def has_users(db: Session) -> bool:
    return db.query(User).count() > 0


def create_owner(db: Session, name: str, email: str, password: str) -> User:
    """Create the first tenant + owner. Only allowed when no users exist."""
    if has_users(db):
        raise ValueError("System already initialized — cannot create the owner again")
    if len(password) < 6:
        raise ValueError("Password must be at least 6 characters")
    tenant = Tenant(name=name, plan="single", max_users=1)
    db.add(tenant)
    db.flush()
    user = User(
        tenant_id=tenant.id,
        role="owner",
        name=name,
        email=email.lower().strip(),
        password_hash=hash_password(password),
    )
    db.add(user)
    db.commit()
    db.refresh(user)
    log_audit(db, user, "create_owner", f"user#{user.id}", f"Created owner account {user.email}")
    return user


def authenticate(db: Session, email: str, password: str) -> User | None:
    user = db.query(User).filter(User.email == email.lower().strip(), User.status == "active").first()
    if not user or not verify_password(password, user.password_hash):
        return None
    user.last_login_at = datetime.utcnow()
    db.commit()
    return user


def issue_token(db: Session, user: User) -> str:
    token = secrets.token_urlsafe(32)
    db.add(AuthSession(
        user_id=user.id,
        token_hash=_hash_token(token),
        expires_at=datetime.utcnow() + timedelta(days=SESSION_DAYS),
    ))
    db.commit()
    return token


def validate_token(db: Session, token: str) -> User | None:
    if not token:
        return None
    session = db.query(AuthSession).filter(AuthSession.token_hash == _hash_token(token)).first()
    if not session:
        return None
    if session.expires_at < datetime.utcnow():
        db.delete(session)
        db.commit()
        return None
    return db.query(User).filter(User.id == session.user_id, User.status == "active").first()


def revoke_token(db: Session, token: str) -> None:
    session = db.query(AuthSession).filter(AuthSession.token_hash == _hash_token(token)).first()
    if session:
        db.delete(session)
        db.commit()


def log_audit(db: Session, user: User | None, action: str, target: str = None, detail: str = None) -> None:
    try:
        db.add(AuditLog(
            tenant_id=user.tenant_id if user else None,
            user_id=user.id if user else None,
            action=action,
            target=target,
            detail=detail,
        ))
        db.commit()
    except Exception:
        db.rollback()


def _hash_token(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def request_allowed(path: str, auth_header: str, db: Session) -> bool:
    """Global API auth check for the HTTP middleware.

    Rules:
    - Non-API paths (frontend/static) are always open
    - /api/health, /api/auth/login, /api/auth/setup-owner are always open
    - First run (no users yet): everything open, so setup wizard works
    - Otherwise: valid bearer token required
    """
    if not path.startswith("/api/"):
        return True
    if path == "/api/health" or path == "/api/update/check" or path.startswith("/api/auth/login") or path.startswith("/api/auth/setup-owner") or path.startswith("/api/auth/forgot-password") or path.startswith("/api/auth/reset-password") or path == "/api/auth/status":
        return True
    if not has_users(db):
        return True
    token = auth_header[7:].strip() if auth_header.startswith("Bearer ") else ""
    user = validate_token(db, token)
    if user is None:
        return False
    # 交付版未激活：只允许激活页相关接口，业务接口全部锁定
    try:
        from services.license import tenant_needs_activation
        if tenant_needs_activation(db, user.tenant_id):
            allowed_unactivated = (
                path.startswith("/api/license/")
                or path == "/api/auth/me"
                or path == "/api/auth/logout"
                or path == "/api/auth/status"
            )
            return allowed_unactivated
    except Exception:
        return False
    # 试用到期 / 激活码失效 → 拒绝（防止会话期内绕过到期限制）
    try:
        from services.license import check_tenant_license
        check_tenant_license(db, user.tenant_id)
    except Exception:
        return False
    return True
