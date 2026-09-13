"""License (activation code) for B2B Outbound OS — offline RSA-signed.

License key format:  base64url(payload_json) + "." + base64url(rsa_signature)

Payload variants:
  - Full / permanent license: {company, max_users, plan, issued}
  - Time-limited license (legacy format, runs from the issue date): {company, max_users, plan, issued, expires}
  - Trial license (two deadlines): {company, max_users, plan, issued, trial_days, activate_by}
      * activate_by: the key must be activated before this date, otherwise it becomes void
      * trial_days:  after successful activation the trial runs for N days, counted from the activation date

Verification uses the embedded PUBLIC key; only the seller holds the private
key (tools/license_private.pem) used by tools/make_license.py to issue keys.
"""

import base64
import json
from datetime import date
from pathlib import Path

from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import padding
from config import APP_DIR

PUBLIC_KEY_PEM = b"""-----BEGIN PUBLIC KEY-----
MIIBIjANBgkqhkiG9w0BAQEFAAOCAQ8AMIIBCgKCAQEAlPLyORh3fSHNdFD6E7IV
VHKn3+P9WT9epKeXJe9VkgJLs0VYENhwcd0ypGUuwAxs37MsqRUT9089BmzVVb26
ZJGVC+KUYyTXsKAvUQ4f2DiWP+ey4r7dlkvr6K3sJ9WV/VyexWNu77wM4Zat4/Yv
pA9iYLCJiG0/E6dIALN3r2auZ85OKSyj338fDQ5Kk4xJ+j5mKRLXNxF9zpd53Fr7
Uu/q0D7YtFkCs50zXD+KK30Fa4VY1CfeBV482mYH0Gq2JQSGdls6wZD9YdrJHIew
4EE6ZMCf6EyPtN6KpEwMYSIHpXiPvDzt3rgwlBzkIm2VqMxfhmKHVQxqrCrEgTux
3QIDAQAB
-----END PUBLIC KEY-----
"""

PRIVATE_KEY_PATH = APP_DIR / "tools" / "license_private.pem"


def _b64e(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).decode().rstrip("=")


def _b64d(text: str) -> bytes:
    return base64.urlsafe_b64decode(text + "=" * (-len(text) % 4))


def generate_license(company: str, max_users: int, plan: str = "single", expires: str = None,
                     trial_days: int = None, activate_by: str = None) -> str:
    """Issue a license key (seller-side). Requires tools/license_private.pem."""
    if not PRIVATE_KEY_PATH.exists():
        raise FileNotFoundError("Missing private key file tools/license_private.pem — cannot sign activation codes")
    priv = serialization.load_pem_private_key(PRIVATE_KEY_PATH.read_bytes(), password=None)
    payload = {
        "company": company,
        "max_users": int(max_users),
        "plan": plan,
        "issued": date.today().isoformat(),
    }
    if expires:
        payload["expires"] = expires
    if trial_days:
        payload["trial_days"] = int(trial_days)
    if activate_by:
        payload["activate_by"] = activate_by
    body = _b64e(json.dumps(payload, ensure_ascii=False).encode("utf-8"))
    sig = priv.sign(body.encode("utf-8"), padding.PKCS1v15(), hashes.SHA256())
    return body + "." + _b64e(sig)


def validate_license(key: str) -> dict:
    """Verify a license key locally. Returns payload dict or raises ValueError."""
    if not key or "." not in key:
        raise ValueError("Activation code format is invalid")
    body, sig = key.split(".", 1)
    pub = serialization.load_pem_public_key(PUBLIC_KEY_PEM)
    try:
        pub.verify(_b64d(sig), body.encode("utf-8"), padding.PKCS1v15(), hashes.SHA256())
    except InvalidSignature:
        raise ValueError("Activation code is invalid (signature mismatch)")
    except Exception:
        raise ValueError("Activation code could not be parsed")
    try:
        payload = json.loads(_b64d(body).decode("utf-8"))
    except Exception:
        raise ValueError("Activation code content is corrupted")
    if not payload.get("company") or not payload.get("max_users"):
        raise ValueError("Activation code is missing required information")
    # Legacy format: fixed expiry date counted from the issue date
    if payload.get("expires"):
        try:
            exp = date.fromisoformat(payload["expires"])
        except ValueError:
            raise ValueError("Activation code validity format is invalid")
        if exp < date.today():
            raise ValueError(f"Activation code has expired ({exp})")
    return payload


def check_tenant_license(db, tenant_id):
    """Return license status for a tenant, or raise ValueError if invalid/expired."""
    from models import Tenant
    if not tenant_id:
        return {"activated": False}
    tenant = db.query(Tenant).filter(Tenant.id == tenant_id).first()
    if not tenant or not tenant.license_key:
        return {"activated": False}
    payload = validate_license(tenant.license_key)  # raises ValueError if expired/invalid
    # Trial key: trial_days counted from activated_at after activation
    if payload.get("trial_days"):
        if not tenant.activated_at:
            # Bound but never activated (inconsistent state) -> treat as not activated
            return {"activated": False, "reason": "not_activated", "trial_days": payload["trial_days"]}
        from datetime import datetime, timedelta
        expires_at = tenant.activated_at + timedelta(days=int(payload["trial_days"]))
        if datetime.utcnow() > expires_at:
            raise ValueError(f"Trial expired ({expires_at.date()}) — please purchase an official activation code")
        return {
            "activated": True, "valid": True,
            "expires": expires_at.date().isoformat(),
            "max_users": payload["max_users"],
            "plan": payload["plan"],
            "trial": True,
        }
    # Full license / legacy format
    if payload.get("expires"):
        return {
            "activated": True, "valid": True,
            "expires": payload["expires"],
            "max_users": payload["max_users"],
            "plan": payload["plan"],
        }
    # Perpetual (one-time purchase)
    return {
        "activated": True, "valid": True,
        "expires": None,
        "max_users": payload["max_users"],
        "plan": payload["plan"],
    }


def tenant_needs_activation(db, tenant_id) -> bool:
    """True when REQUIRE_LICENSE=true (full build) and the tenant is not activated
    -> after login only the activation page is reachable."""
    from config import REQUIRE_LICENSE
    if not REQUIRE_LICENSE:
        return False
    if not tenant_id:
        return True
    from models import Tenant
    tenant = db.query(Tenant).filter(Tenant.id == tenant_id).first()
    if not tenant or not tenant.license_key:
        return True
    try:
        payload = validate_license(tenant.license_key)
    except ValueError:
        return True
    # Trial key bound but never activated -> the activation flow must be completed
    if payload.get("trial_days") and not tenant.activated_at:
        return True
    return False
