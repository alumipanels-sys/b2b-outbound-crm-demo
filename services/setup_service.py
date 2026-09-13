"""First-run setup service — customer configures the system themselves.

Writes configuration into the local .env file (with a timestamped backup),
tests SMTP/IMAP connectivity, and replaces knowledge-base placeholders
like {{COMPANY}} / {{USER_EMAIL}} with the customer's real values.
"""

import asyncio
import logging
import os
import shutil
from datetime import datetime
from pathlib import Path

from dotenv import dotenv_values

logger = logging.getLogger(__name__)

from config import APP_DIR
PROJECT_DIR = APP_DIR
ENV_PATH = PROJECT_DIR / ".env"

# UI field -> .env key
FIELD_MAP = {
    "company": "COMPANY_NAME",
    "user_name": "USER_NAME",
    "user_email": "USER_EMAIL",
    "website": "WEBSITE",
    "gemini_key": "GEMINI_API_KEY",
    "deepseek_key": "DEEPSEEK_API_KEY",
    "openai_key": "OPENAI_API_KEY",
    "https_proxy": "HTTPS_PROXY",
    "smtp_host": "SMTP_HOST",
    "smtp_port": "SMTP_PORT",
    "smtp_user": "SMTP_USER",
    "smtp_pass": "SMTP_PASS",
    "smtp_name": "SMTP_NAME",
    "smtp_2_host": "SMTP_HOST_2",
    "smtp_2_port": "SMTP_PORT_2",
    "smtp_2_user": "SMTP_USER_2",
    "smtp_2_pass": "SMTP_PASS_2",
    "smtp_2_name": "SMTP_NAME_2",
    "smtp_3_host": "SMTP_HOST_3",
    "smtp_3_port": "SMTP_PORT_3",
    "smtp_3_user": "SMTP_USER_3",
    "smtp_3_pass": "SMTP_PASS_3",
    "smtp_3_name": "SMTP_NAME_3",
    "imap_host": "IMAP_HOST",
    "imap_port": "IMAP_PORT",
    "imap_user": "IMAP_USER",
    "imap_pass": "IMAP_PASS",
    "imap_2_host": "IMAP_HOST_2",
    "imap_2_port": "IMAP_PORT_2",
    "imap_2_user": "IMAP_USER_2",
    "imap_2_pass": "IMAP_PASS_2",
    "imap_3_host": "IMAP_HOST_3",
    "imap_3_port": "IMAP_PORT_3",
    "imap_3_user": "IMAP_USER_3",
    "imap_3_pass": "IMAP_PASS_3",
    "serverchan_key": "SERVERCHAN_SENDKEY",
    "daily_limit": "DAILY_EMAIL_LIMIT",
    "email_min_interval": "EMAIL_MIN_INTERVAL_MINUTES",
    "email_max_interval": "EMAIL_MAX_INTERVAL_MINUTES",
    "host": "HOST",
    "app_user": "APP_USER",
    "app_password": "APP_PASSWORD",
    "backup_cloud_dir": "BACKUP_CLOUD_DIR",
    "backup_password": "BACKUP_PASSWORD",
}

# Keys that are sensitive and should never be echoed back in full
SENSITIVE_KEYS = {"GEMINI_API_KEY", "DEEPSEEK_API_KEY", "OPENAI_API_KEY",
                  "SMTP_PASS", "SMTP_PASS_2", "SMTP_PASS_3",
                  "IMAP_PASS", "IMAP_PASS_2", "IMAP_PASS_3",
                  "SERVERCHAN_SENDKEY", "APP_PASSWORD", "BACKUP_PASSWORD"}

PLACEHOLDER_MARKERS = ["你的", "YOUR_", "xxx", "your_", "example"]

# Steps shown in the wizard, in order
STEPS = [
    {"key": "company", "name": "Company info"},
    {"key": "ai", "name": "AI configuration"},
    {"key": "smtp", "name": "Sending mailbox (SMTP)"},
    {"key": "imap", "name": "Receiving mailbox (IMAP)"},
    {"key": "notify", "name": "Notifications (optional)"},
    {"key": "knowledge", "name": "Knowledge base"},
]


def _read_env() -> dict:
    return dotenv_values(str(ENV_PATH)) if ENV_PATH.exists() else {}


def _is_filled(value) -> bool:
    v = (value or "").strip()
    if not v:
        return False
    return not any(m in v for m in PLACEHOLDER_MARKERS)


def _mask(value) -> str:
    v = (value or "").strip()
    if not v:
        return ""
    if len(v) <= 8:
        return "*" * len(v)
    return v[:3] + "*" * (len(v) - 6) + v[-3:]


def setup_status() -> dict:
    """Per-step completion status based on the current .env."""
    env = _read_env()
    fields = {}
    for field, env_key in FIELD_MAP.items():
        value = env.get(env_key, "")
        filled = _is_filled(value)
        fields[field] = {
            "filled": filled,
            "value": "" if (filled and env_key in SENSITIVE_KEYS) else (value or ""),
            "masked": _mask(value) if (filled and env_key in SENSITIVE_KEYS) else None,
        }

    def step_done(keys):
        return all(fields.get(k, {}).get("filled") for k in keys)

    kb_done = False
    try:
        from database import SessionLocal
        from services.knowledge_engine import coverage_report
        _db = SessionLocal()
        try:
            kb_done = coverage_report(_db).get("score", 0) >= 65
        finally:
            _db.close()
    except Exception:
        pass

    steps = [
        {"key": "company", "name": "Company info", "done": step_done(["company", "user_name", "user_email", "website"])},
        {"key": "ai", "name": "AI configuration", "done": any(fields.get(k, {}).get("filled") for k in ("gemini_key", "deepseek_key", "openai_key"))},
        {"key": "smtp", "name": "Sending mailbox (SMTP)", "done": step_done(["smtp_host", "smtp_user", "smtp_pass"])},
        {"key": "imap", "name": "Receiving mailbox (IMAP)", "done": step_done(["imap_host", "imap_user", "imap_pass"])},
        {"key": "notify", "name": "Notifications (optional)", "done": _is_filled(env.get("SERVERCHAN_SENDKEY"))},
        {"key": "knowledge", "name": "Knowledge base", "done": kb_done},
    ]
    return {
        "env_path": str(ENV_PATH),
        "steps": steps,
        "fields": fields,
        "completed": all(s["done"] for s in steps[:5]),
    }


def save_values(values: dict) -> dict:
    """Update .env with the given UI fields. Sensitive values never logged."""
    if not ENV_PATH.exists():
        ENV_PATH.write_text("", encoding="utf-8")

    # Backup before writing
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    backup_path = ENV_PATH.with_name(f".env.bak_{ts}")
    shutil.copy2(ENV_PATH, backup_path)

    lines = ENV_PATH.read_text(encoding="utf-8").splitlines()
    updates = {}
    for field, raw in values.items():
        env_key = FIELD_MAP.get(field)
        if not env_key:
            continue
        value = (raw or "").strip()
        updates[env_key] = value

    out = []
    seen = set()
    saved_keys = []
    for line in lines:
        stripped = line.strip()
        if stripped and not stripped.startswith("#") and "=" in stripped:
            key = stripped.split("=", 1)[0].strip()
            if key in updates:
                out.append(f"{key}={updates.pop(key)}")
                seen.add(key)
                saved_keys.append(key)
                continue
        out.append(line)
    for key, value in updates.items():
        if key not in seen:
            out.append(f"{key}={value}")
            saved_keys.append(key)
    ENV_PATH.write_text("\n".join(out) + "\n", encoding="utf-8")
    logger.info("setup: .env updated (%d keys), backup: %s", len(saved_keys), backup_path.name)
    return {"saved": saved_keys, "backup": backup_path.name}


def _smtp_values(fields: dict) -> dict:
    env = _read_env()
    prefix = "smtp_"
    if (fields.get("smtp_2_host") or "").strip():
        prefix = "smtp_2_"
    elif (fields.get("smtp_3_host") or "").strip():
        prefix = "smtp_3_"
    ek = {"smtp_": "SMTP_", "smtp_2_": "SMTP_2_", "smtp_3_": "SMTP_3_"}[prefix]
    return {
        "host": (fields.get(prefix + "host") or "").strip() or env.get(ek + "HOST", ""),
        "port": int((fields.get(prefix + "port") or "").strip() or env.get(ek + "PORT") or 465),
        "user": (fields.get(prefix + "user") or "").strip() or env.get(ek + "USER", ""),
        "pass": (fields.get(prefix + "pass") or "").strip() or env.get(ek + "PASS", ""),
    }


async def test_smtp(fields: dict) -> dict:
    """Login-only SMTP test (never sends mail)."""
    import aiosmtplib
    cfg = _smtp_values(fields)
    if not (cfg["host"] and cfg["user"] and cfg["pass"]):
        return {"ok": False, "error": "Please complete the SMTP configuration"}
    try:
        use_tls = cfg["port"] == 465
        smtp = aiosmtplib.SMTP(hostname=cfg["host"], port=cfg["port"], use_tls=use_tls, timeout=15)
        await smtp.connect()
        if not use_tls:
            await smtp.starttls()
        await smtp.login(cfg["user"], cfg["pass"])
        await smtp.quit()
        return {"ok": True, "message": f"SMTP login successful ({cfg['host']}:{cfg['port']})"}
    except Exception as e:
        return {"ok": False, "error": f"SMTP test failed: {e}"}


async def test_imap(fields: dict) -> dict:
    import aioimaplib
    env = _read_env()
    prefix = "imap_"
    if (fields.get("imap_2_host") or "").strip():
        prefix = "imap_2_"
    elif (fields.get("imap_3_host") or "").strip():
        prefix = "imap_3_"
    ek = {"imap_": "IMAP_", "imap_2_": "IMAP_2_", "imap_3_": "IMAP_3_"}[prefix]
    host = (fields.get(prefix + "host") or "").strip() or env.get(ek + "HOST", "")
    port = int((fields.get(prefix + "port") or "").strip() or env.get(ek + "PORT") or 993)
    user = (fields.get(prefix + "user") or "").strip() or env.get(ek + "USER", "")
    pwd = (fields.get(prefix + "pass") or "").strip() or env.get(ek + "PASS", "")
    if not (host and user and pwd):
        return {"ok": False, "error": "Please complete the IMAP configuration"}
    try:
        imap = aioimaplib.IMAP4_SSL(host=host, port=port, timeout=15)
        await imap.wait_hello_from_server()
        await imap.login(user, pwd)
        await imap.logout()
        return {"ok": True, "message": f"IMAP login successful ({host}:{port})"}
    except Exception as e:
        return {"ok": False, "error": f"IMAP test failed: {e}"}


async def _test_gemini(key: str, proxy: str) -> dict:
    import httpx
    url = f"https://generativelanguage.googleapis.com/v1beta/models/gemini-2.5-flash:generateContent?key={key}"
    body = {"contents": [{"parts": [{"text": "Reply with exactly: OK"}]}]}
    try:
        async with httpx.AsyncClient(timeout=20, proxy=proxy or None) as client:
            resp = await client.post(url, json=body)
        if resp.status_code == 200:
            return {"ok": True, "message": "Gemini connection successful"}
        return {"ok": False, "error": f"HTTP {resp.status_code}: {resp.text[:200]}"}
    except Exception as e:
        return {"ok": False, "error": f"Gemini test failed: {e}"}


async def _test_deepseek(key: str) -> dict:
    import httpx
    try:
        async with httpx.AsyncClient(timeout=20) as client:
            resp = await client.post(
                "https://api.deepseek.com/chat/completions",
                headers={"Authorization": f"Bearer {key}"},
                json={"model": "deepseek-chat", "messages": [{"role": "user", "content": "Reply with exactly: OK"}], "max_tokens": 8},
            )
        if resp.status_code == 200:
            return {"ok": True, "message": "DeepSeek connection successful"}
        return {"ok": False, "error": f"HTTP {resp.status_code}: {resp.text[:200]}"}
    except Exception as e:
        return {"ok": False, "error": f"DeepSeek test failed: {e}"}


async def _test_openai(key: str) -> dict:
    import httpx
    try:
        async with httpx.AsyncClient(timeout=20) as client:
            resp = await client.post(
                "https://api.openai.com/v1/chat/completions",
                headers={"Authorization": f"Bearer {key}"},
                json={"model": "gpt-4o-mini", "messages": [{"role": "user", "content": "Reply with exactly: OK"}], "max_tokens": 8},
            )
        if resp.status_code == 200:
            return {"ok": True, "message": "OpenAI connection successful"}
        return {"ok": False, "error": f"HTTP {resp.status_code}: {resp.text[:200]}"}
    except Exception as e:
        return {"ok": False, "error": f"OpenAI test failed: {e}"}


async def test_ai(values: dict) -> dict:
    """Test whichever AI providers the customer configured (form values take
    priority, saved .env used as fallback). One provider is enough."""
    from services.ai_router import _key_usable
    env = _read_env()

    def _v(field, env_key):
        v = (values.get(field) or "").strip()
        return v if v else (env.get(env_key) or "").strip()

    gemini_key = _v("gemini_key", "GEMINI_API_KEY")
    deepseek_key = _v("deepseek_key", "DEEPSEEK_API_KEY")
    openai_key = _v("openai_key", "OPENAI_API_KEY")
    proxy = _v("https_proxy", "HTTPS_PROXY") or _v("https_proxy", "HTTP_PROXY")

    providers = {}
    if _key_usable(gemini_key):
        providers["gemini"] = await _test_gemini(gemini_key, proxy)
    if _key_usable(deepseek_key):
        providers["deepseek"] = await _test_deepseek(deepseek_key)
    if _key_usable(openai_key):
        providers["openai"] = await _test_openai(openai_key)
    if not providers:
        return {"ok": False, "error": "Please enter at least one API key (any of Gemini / DeepSeek / OpenAI)"}
    return {"ok": all(r["ok"] for r in providers.values()), "providers": providers}


async def self_check() -> dict:
    """One-click backend self-check: DB, scheduler, AI, SMTP, IMAP, KB, backup."""
    import sqlite3
    results = {}

    try:
        from config import DATABASE_URL
        db_path = DATABASE_URL.replace("sqlite:///", "")
        if os.path.exists(db_path):
            conn = sqlite3.connect(db_path)
            row = conn.execute("PRAGMA integrity_check").fetchone()
            conn.close()
            results["database"] = {"ok": row[0] == "ok", "detail": row[0] if row else "unknown"}
        else:
            results["database"] = {"ok": False, "detail": "Database file not found"}
    except Exception as e:
        results["database"] = {"ok": False, "error": str(e)}

    try:
        from services.scheduler_service import _scheduler
        results["scheduler"] = {"ok": _scheduler is not None and bool(_scheduler.running), "detail": "Scheduler running" if (_scheduler is not None and _scheduler.running) else "Scheduler not running"}
    except Exception as e:
        results["scheduler"] = {"ok": False, "error": str(e)}

    results["ai"] = await test_ai({})

    env = _read_env()
    results["smtp"] = await test_smtp({
        "smtp_host": env.get("SMTP_HOST", ""),
        "smtp_port": env.get("SMTP_PORT", "465"),
        "smtp_user": env.get("SMTP_USER", ""),
        "smtp_pass": env.get("SMTP_PASS", ""),
    })
    results["imap"] = await test_imap({
        "imap_host": env.get("IMAP_HOST", ""),
        "imap_port": env.get("IMAP_PORT", "993"),
        "imap_user": env.get("IMAP_USER", ""),
        "imap_pass": env.get("IMAP_PASS", ""),
    })

    try:
        from database import SessionLocal
        from services.knowledge_engine import coverage_report
        _db = SessionLocal()
        try:
            cov = coverage_report(_db)
        finally:
            _db.close()
        results["knowledge"] = {"ok": cov["score"] >= 65, "detail": f"{cov['score']}/100"}
    except Exception as e:
        results["knowledge"] = {"ok": False, "error": str(e)}

    try:
        from services.backup_service import latest_backup_info
        lb = latest_backup_info()
        results["backup"] = {
            "ok": bool(lb and lb.get("integrity") == "ok"),
            "detail": (lb or {}).get("filename") or "No backup yet",
        }
    except Exception as e:
        results["backup"] = {"ok": False, "error": str(e)}

    ok = all(r.get("ok") is True for r in results.values())
    return {"ok": ok, "results": results}


def apply_company_info(db, company: str = None, user_email: str = None, website: str = None, user_name: str = None) -> dict:
    """Replace {{COMPANY}} / {{USER_EMAIL}} / {{WEBSITE}} / {{USER_NAME}}
    placeholders in the knowledge base with the customer's real values."""
    from models import KnowledgeBase

    replacements = {
        "{{COMPANY}}": (company or "").strip(),
        "{{USER_EMAIL}}": (user_email or "").strip(),
        "{{WEBSITE}}": (website or "").strip(),
        "{{USER_NAME}}": (user_name or "").strip(),
    }
    replacements = {k: v for k, v in replacements.items() if v}
    if not replacements:
        return {"updated": 0}

    rows = db.query(KnowledgeBase).filter(KnowledgeBase.is_active == 1).all()
    changed = 0
    for kb in rows:
        new_content = kb.content
        new_title = kb.title
        new_tags = kb.tags or ""
        for token, value in replacements.items():
            new_content = (new_content or "").replace(token, value)
            new_title = (new_title or "").replace(token, value)
            new_tags = (new_tags or "").replace(token, value)
        if new_content != kb.content or new_title != kb.title or new_tags != kb.tags:
            kb.content = new_content
            kb.title = new_title
            kb.tags = new_tags
            changed += 1
    if changed:
        db.commit()
    return {"updated": changed, "replacements": list(replacements.keys())}


def check_placeholders(db) -> dict:
    """Scan knowledge base for remaining {{...}} placeholders."""
    from models import KnowledgeBase

    rows = db.query(KnowledgeBase).filter(KnowledgeBase.is_active == 1).all()
    found = []
    import re
    for kb in rows:
        text = (kb.content or "") + (kb.title or "")
        for m in re.findall(r"\{\{[^}]+\}\}", text):
            found.append({"knowledge_id": kb.id, "title": kb.title, "token": m})
    return {"count": len(found), "tokens": sorted(set(f["token"] for f in found))}
