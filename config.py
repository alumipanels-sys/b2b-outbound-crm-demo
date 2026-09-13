"""Application configuration — reads from .env file."""

import os
import sys
from pathlib import Path

from dotenv import load_dotenv

# ── 运行目录识别 ─────────────────────────────────────────────
# 源码模式：项目根目录（__file__ 所在处）
# 打包模式：exe 所在目录 —— 数据（.env / 数据库 / 附件 / 备份）永远在 exe 旁边，
#           客户可自由备份、迁移、换电脑，且更新 exe 时数据不受影响。
def _app_dir() -> Path:
    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve().parent
    return Path(__file__).resolve().parent


APP_DIR = _app_dir()

# Load .env from APP_DIR (exe 旁边 / 项目根), not from CWD
_ENV_PATH = APP_DIR / ".env"
# 防御 BOM：用记事本/部分工具保存 .env 可能写入隐藏的 BOM 字节，
# 会导致第一个键名（如 IMAP_USER_2）读不到，邮箱配置悄悄失效。
# dotenv 不会自动跳过 BOM，这里显式剥离后再加载。
if _ENV_PATH.exists():
    _raw = _ENV_PATH.read_bytes()
    if _raw.startswith(b"\xef\xbb\xbf"):
        try:
            _ENV_PATH.write_bytes(_raw[3:])
            import logging as _logging
            _logging.getLogger(__name__).warning("Removed hidden BOM from the start of .env")
        except Exception:
            pass
load_dotenv(_ENV_PATH)

def _env_int(key: str, default: int) -> int:
    """Read an int env var safely (empty string -> default)."""
    try:
        value = os.getenv(key, "")
        return int(value) if value.strip() else default
    except (TypeError, ValueError):
        return default

# ── Gemini ────────────────────────────────────────────
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY", "")

# ── DeepSeek ──────────────────────────────────────────
DEEPSEEK_API_KEY = os.getenv("DEEPSEEK_API_KEY", "")

OPENAI_API_KEY = os.getenv("OPENAI_API_KEY", "")
OPENAI_MODEL = os.getenv("OPENAI_MODEL", "gpt-5.5")

# ── Company identity (filled via the setup wizard) ──────────
COMPANY_NAME = os.getenv("COMPANY_NAME", "{{COMPANY}}")
USER_NAME = os.getenv("USER_NAME", "Your Name")
USER_EMAIL = os.getenv("USER_EMAIL", "your-email@company.com")
WEBSITE = os.getenv("WEBSITE", "www.yourcompany.com")
SMTP_NAME = os.getenv("SMTP_NAME", COMPANY_NAME)

# ── Proxy (required for Gemini in China) ─────────────────
GEMINI_PROXY = os.getenv("HTTPS_PROXY", "") or os.getenv("HTTP_PROXY", "")

# ── SMTP (ZOHO) ──────────────────────────────────────
SMTP_HOST = os.getenv("SMTP_HOST", "smtp.gmail.com")
SMTP_PORT = _env_int("SMTP_PORT", 465)
SMTP_USER = os.getenv("SMTP_USER", "your-email@company.com")
SMTP_PASS = os.getenv("SMTP_PASS", "")

# ── second sender mailbox ─────────────────────────────────
SMTP_HOST_2 = os.getenv("SMTP_HOST_2", "smtp.gmail.com")
SMTP_PORT_2 = _env_int("SMTP_PORT_2", 465)
SMTP_USER_2 = os.getenv("SMTP_USER_2", "")
SMTP_PASS_2 = os.getenv("SMTP_PASS_2", "")
SMTP_NAME_2 = os.getenv("SMTP_NAME_2", "{{COMPANY}}")

# ── third sender mailbox (群发) ──────────────────────
SMTP_HOST_3 = os.getenv("SMTP_HOST_3", "smtp.gmail.com")
SMTP_PORT_3 = _env_int("SMTP_PORT_3", 465)
SMTP_USER_3 = os.getenv("SMTP_USER_3", "")
SMTP_PASS_3 = os.getenv("SMTP_PASS_3", "")
SMTP_NAME_3 = os.getenv("SMTP_NAME_3", "{{COMPANY}}")

# ── IMAP (ZOHO) ──────────────────────────────────────
IMAP_HOST = os.getenv("IMAP_HOST", "imap.gmail.com")
IMAP_PORT = _env_int("IMAP_PORT", 993)
IMAP_USER = os.getenv("IMAP_USER", "your-email@company.com")
IMAP_PASS = os.getenv("IMAP_PASS", "")

IMAP_HOST_2 = os.getenv("IMAP_HOST_2", "imap.gmail.com")
IMAP_PORT_2 = _env_int("IMAP_PORT_2", 993)
IMAP_USER_2 = os.getenv("IMAP_USER_2", "")
IMAP_PASS_2 = os.getenv("IMAP_PASS_2", "")

# ── third IMAP mailbox (群发收信) ────────────────────
IMAP_HOST_3 = os.getenv("IMAP_HOST_3", "imap.gmail.com")
IMAP_PORT_3 = _env_int("IMAP_PORT_3", 993)
IMAP_USER_3 = os.getenv("IMAP_USER_3", "")
IMAP_PASS_3 = os.getenv("IMAP_PASS_3", "")

# ── WeChat notification (ServerChan) ───────────────────
SERVERCHAN_SENDKEY = os.getenv("SERVERCHAN_SENDKEY", "")

# 备份加密密码（可选）。设置后，同步到坚果云/云端的备份会加密存储，
# 本地备份保持明文便于快速恢复。请牢记密码，丢失后云端备份无法解密。
BACKUP_PASSWORD = os.getenv("BACKUP_PASSWORD", "")

# 演示模式：仅演示版开启，用于“一键重置演示数据”，防止误清个人/交付版
DEMO_MODE = os.getenv("DEMO_MODE", "false").lower() in ("1", "true", "yes")

# 强制激活：未激活时只能进激活页，其他功能锁定。
# 开源版默认不锁（留空/false 即自由使用）；
# 正式商业交付时，在 .env 写 REQUIRE_LICENSE=true 启用激活码锁。
_req_license = os.getenv("REQUIRE_LICENSE", "").strip().lower()
REQUIRE_LICENSE = _req_license in ("1", "true", "yes")

# 云端备份目录（可选）。留空则用默认（本机用户目录下的坚果云）。
# 客户可在「系统配置」填写自己的云盘目录，如 D:\备份\ColdDev
BACKUP_CLOUD_DIR = os.getenv("BACKUP_CLOUD_DIR", "")

# Server binding / operation mode
HOST = os.getenv("HOST", "0.0.0.0")  # use 127.0.0.1 for local-only access
PORT = _env_int("PORT", 8010)        # 默认 8010，避免与旧系统 8000 冲突
DEBUG = os.getenv("DEBUG", "false").lower() in ("1", "true", "yes")

# Optional Basic Auth. If both are set, the web app requires login.
# Strongly recommended when HOST != 127.0.0.1.
APP_USER = os.getenv("APP_USER", "")
APP_PASSWORD = os.getenv("APP_PASSWORD", "")

# ── 版本与在线更新 ──
VERSION = os.getenv("APP_VERSION", "1.0.0")
# 更新清单地址（可选）：指向你托管的 update.json，如
#   https://raw.githubusercontent.com/你的用户名/仓库/main/update.json
UPDATE_URL = os.getenv("UPDATE_URL", "")

# ── Email rate-limiting ──────────────────────────────
DAILY_EMAIL_LIMIT = _env_int("DAILY_EMAIL_LIMIT", 30)
# Timezone scheduling: respect recipient timezone (skip if not business hours)
# Set to false to always send immediately regardless of recipient timezone
TIMEZONE_SCHEDULING = os.getenv("TIMEZONE_SCHEDULING", "true").lower() in ("1", "true", "yes")
EMAIL_MIN_INTERVAL_MINUTES = _env_int("EMAIL_MIN_INTERVAL_MINUTES", 30)
EMAIL_MAX_INTERVAL_MINUTES = _env_int("EMAIL_MAX_INTERVAL_MINUTES", 90)

# Database — 绝对路径锁定到 APP_DIR，避免 CWD 变化导致 sqlite 找不到库
DATABASE_URL = os.getenv("DATABASE_URL", "sqlite:///prospect.db")
if DATABASE_URL.startswith("sqlite:///") and not DATABASE_URL.startswith("sqlite:////"):
    rel = DATABASE_URL.replace("sqlite:///", "")
    _abs = APP_DIR / rel
    DATABASE_URL = "sqlite:///" + str(_abs)
