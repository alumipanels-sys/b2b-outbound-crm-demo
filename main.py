"""B2B Outbound OS — self-hosted export sales system. FastAPI application entry point."""


import logging
import os
import shutil
import socket
import sqlite3
import sys
import subprocess
import traceback
from datetime import datetime
from pathlib import Path
from contextlib import asynccontextmanager


from fastapi import FastAPI, Request

from fastapi.staticfiles import StaticFiles

from fastapi.middleware.cors import CORSMiddleware

from fastapi.responses import JSONResponse


# Ensure this app directory is importable even with embedded Python setups
# (embedded Python uses a ._pth file and does not add the script directory).
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))


from database import engine, init_knowledge_base, init_fts5

from models import Base

from services.scheduler_service import start_scheduler, shutdown_scheduler
from config import APP_DIR

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(name)s: %(message)s")
logger = logging.getLogger(__name__)


# ═══════════════════════════════════════════════════════════

#  Stability Layer 1: Auto-recover from a corrupted database

# ═══════════════════════════════════════════════════════════



def _check_db_integrity(db_path: str) -> bool:

    """True if the database passes PRAGMA integrity_check."""

    try:

        conn = sqlite3.connect(db_path)

        result = conn.execute("PRAGMA integrity_check").fetchone()

        conn.close()

        ok = result[0].lower() == "ok"

        if not ok:

            logger.warning("DB integrity check: %s", result[0])

        return ok

    except Exception as e:

        logger.warning("DB integrity check failed to run: %s", e)

        return False





def _find_latest_backup(backup_dir):

    """Find the newest valid backup .db in the backup directory."""

    candidates = sorted(backup_dir.glob("backup_*.db"))

    for p in reversed(candidates):

        if p.stat().st_size > 100 * 1024:  # skip empty / tiny

            return p

    return None





def _recover_db():
    """If DB is corrupted, replace it with the latest backup."""
    from config import DATABASE_URL
    db_path = DATABASE_URL.replace("sqlite:///", "")
    project_dir = APP_DIR


    if _check_db_integrity(db_path):

        return



    logger.critical("⚠️  DATABASE IS CORRUPTED — attempting auto-recovery ...")

    now = datetime.now().strftime("%Y%m%d_%H%M%S")

    corrupt_snapshot = db_path + f".corrupted_{now}"



    try:

        shutil.copy2(db_path, corrupt_snapshot)

        logger.info("Corrupted DB saved as: %s", corrupt_snapshot)

    except Exception as e:

        logger.error("Failed to snapshot corrupted DB: %s", e)



    backup = None
    for search_dir in [
        project_dir / "backups",
    ]:
        if search_dir.exists():
            backup = _find_latest_backup(search_dir)
            if backup:
                break


    if not backup:

        logger.critical("❌ No backup found — cannot auto-recover. Service will start anyway.")

        return



    try:

        shutil.copy2(str(backup), db_path)

        for suffix in ("-wal", "-shm"):

            p = db_path + suffix

            if os.path.exists(p):

                os.remove(p)

        logger.info("✅ Recovered from: %s (%s MB)", backup.name, round(backup.stat().st_size / 1024**2, 1))

    except Exception as e:

        logger.critical("❌ Recovery copy failed: %s", e)





# ═══════════════════════════════════════════════════════════

#  Stability Layer 2: Kill old process holding the app port
# ═══════════════════════════════════════════════════════════



def _free_port(port: int):
    """Check whether the app port is already in use by this project.
    Only kills the owner if its command line looks like uvicorn/main.py,
    so unrelated services on the same port are never touched."""
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    try:
        sock.bind(("0.0.0.0", port))
        sock.close()
        return
    except OSError:
        sock.close()
        logger.warning("Port %s already in use — checking owner ...", port)


    try:

        result = subprocess.run(

            ["netstat", "-ano"],

            capture_output=True, text=True, timeout=10,

        )

        pid = None

        for line in result.stdout.splitlines():

            if f":{port}" in line and "LISTENING" in line:
                parts = line.strip().split()
                pid = parts[-1]
                break
        if pid and pid.isdigit() and _is_project_process(pid):
            subprocess.run(["taskkill", "/f", "/pid", pid], capture_output=True, timeout=10)
            logger.info("✅ Killed old process PID %s on port %s", pid, port)
        else:
            logger.warning("Port %s owner (PID %s) is not this project — not killed", port, pid or "unknown")
    except Exception as e:
        logger.warning("Failed to free port %s: %s", port, e)


def _is_project_process(pid: str) -> bool:
    """Return True if the process command line looks like this app (uvicorn/main.py)."""
    try:
        out = subprocess.run(
            ["wmic", "process", "where", f"ProcessId={pid}", "get", "CommandLine", "/value"],
            capture_output=True, text=True, timeout=10,
        )
        cl = (out.stdout or "") + (out.stderr or "")
        if getattr(sys, "frozen", False):
            exe_name = Path(sys.executable).name.lower()
            return exe_name in cl.lower()
        return ("main.py" in cl) or ("uvicorn" in cl)
    except Exception:
        return False



# ── Schema migration — safe, idempotent, with safety-net UPDATEs ──



def _migrate_schema(conn):
    """Apply any missing columns to existing tables. After every ALTER,
    immediately UPDATE existing rows so default values are never left NULL
    for query-critical columns like is_deleted."""

    # ── quote_history 表 ──
    try:
        qcols = [r[1] for r in conn.execute("PRAGMA table_info(quote_history)").fetchall()]
    except Exception:
        qcols = []
    if qcols and 'direction' not in qcols:
        logger.info("Adding new column: quote_history.direction")
        conn.execute("ALTER TABLE quote_history ADD COLUMN direction TEXT")
        conn.execute("UPDATE quote_history SET direction = 'quote' WHERE direction IS NULL")
        conn.commit()

    # ── intelligence 表：对话全景字段 ──
    try:
        icols = [r[1] for r in conn.execute("PRAGMA table_info(intelligence)").fetchall()]
    except Exception:
        icols = []
    if icols and 'dialogue_panorama' not in icols:
        logger.info("Adding new columns: intelligence.dialogue_panorama / _at")
        conn.execute("ALTER TABLE intelligence ADD COLUMN dialogue_panorama TEXT")
        conn.execute("ALTER TABLE intelligence ADD COLUMN dialogue_panorama_at DATETIME")
        conn.commit()

    # ── Prospects table ──
    pcols = [r[1] for r in conn.execute("PRAGMA table_info(prospects)").fetchall()]


    if 'linkedin_status' not in pcols:

        logger.info("Adding new column: linkedin_status")

        conn.execute("ALTER TABLE prospects ADD COLUMN linkedin_status TEXT")

        conn.execute("UPDATE prospects SET linkedin_status = 'not_connected' WHERE linkedin_status IS NULL")

        conn.commit()



    if 'last_edited_at' not in pcols:

        logger.info("Adding new column: last_edited_at")

        conn.execute("ALTER TABLE prospects ADD COLUMN last_edited_at DATETIME")

        conn.commit()



    if 'email_verified' not in pcols:

        logger.info("Adding email verification columns")

        conn.execute("ALTER TABLE prospects ADD COLUMN email_verified INTEGER DEFAULT 0")

        conn.execute("ALTER TABLE prospects ADD COLUMN email_verified_at DATETIME")

        conn.execute("ALTER TABLE prospects ADD COLUMN email_verification_detail TEXT")

        conn.execute("UPDATE prospects SET email_verified = 0 WHERE email_verified IS NULL")

        conn.commit()



    if 'email_verdict' not in pcols:

        logger.info("Adding new column: email_verdict")

        conn.execute("ALTER TABLE prospects ADD COLUMN email_verdict TEXT")

        conn.commit()



    if 'hunter_data' not in pcols:

        logger.info("Adding new column: hunter_data")

        conn.execute("ALTER TABLE prospects ADD COLUMN hunter_data TEXT")

        conn.commit()



    if 'new_outreach_date' not in pcols:

        logger.info("Adding new column: new_outreach_date")

        conn.execute("ALTER TABLE prospects ADD COLUMN new_outreach_date TEXT")

        conn.commit()



    if 'reminder_note' not in pcols:

        logger.info("Adding new column: reminder_note + reminder_updated_at")

        conn.execute("ALTER TABLE prospects ADD COLUMN reminder_note TEXT")

        conn.execute("ALTER TABLE prospects ADD COLUMN reminder_updated_at DATETIME")

        conn.commit()



        if 'risk_score' not in pcols:
            logger.info("Adding new column: risk_score (0-100 risk rating)")
            conn.execute("ALTER TABLE prospects ADD COLUMN risk_score FLOAT")
            conn.commit()

    for col_name, col_type, default_sql in [
        ("source_channel", "TEXT", None),
        ("development_batch", "TEXT", None),
        ("linkedin_batch", "TEXT", None),
        ("first_touch_channel", "TEXT", None),
        ("duplicate_checked", "INTEGER", "0"),
        ("sales_stage", "TEXT", "'new'"),
    ]:
        if col_name not in pcols:
            logger.info("Adding new column to prospects: %s", col_name)
            conn.execute(f"ALTER TABLE prospects ADD COLUMN {col_name} {col_type}")
            if default_sql is not None:
                conn.execute(f"UPDATE prospects SET {col_name} = {default_sql} WHERE {col_name} IS NULL")
            conn.commit()

    if 'sender_key' not in pcols:
        logger.info("Adding new column: sender_key (per-prospect default sender)")
        conn.execute("ALTER TABLE prospects ADD COLUMN sender_key TEXT")
        conn.commit()

    if 'next_follow_reason' not in pcols:
        logger.info("Adding new column: next_follow_reason")
        conn.execute("ALTER TABLE prospects ADD COLUMN next_follow_reason TEXT")
        conn.commit()

    # ── Sequences: 修复开发计划乱序（同客户同渠道按 id 重新编号 1..N）──
    # 旧的 AI 生成可能写入错误 step_number，导致"第3步"跳到上面。
    # 每次启动幂等修复：按 (prospect_id, channel) 分组，按 id（创建顺序）重排。
    try:
        scols = [r[1] for r in conn.execute("PRAGMA table_info(sequences)").fetchall()]
        if "step_number" in scols and "channel" in scols:
            seq_rows = conn.execute(
                "SELECT id, prospect_id, channel, step_number FROM sequences "
                "ORDER BY prospect_id, channel, id"
            ).fetchall()
            cur_key = None
            idx = 0
            fixed = 0
            for rid, pid, ch, num in seq_rows:
                key = (pid, ch)
                if key != cur_key:
                    cur_key = key
                    idx = 1
                if num != idx:
                    conn.execute("UPDATE sequences SET step_number=? WHERE id=?", (idx, rid))
                    fixed += 1
                idx += 1
            if fixed:
                conn.commit()
                logger.info("Sequences renumbered: %d steps fixed (per prospect+channel by id)", fixed)
        # 补公司级开发计划字段（老库升级用）：to_email / is_company_plan
        if "to_email" not in scols:
            logger.info("Adding new column: sequences.to_email")
            conn.execute("ALTER TABLE sequences ADD COLUMN to_email TEXT")
            conn.commit()
        if "is_company_plan" not in scols:
            logger.info("Adding new column: sequences.is_company_plan")
            conn.execute("ALTER TABLE sequences ADD COLUMN is_company_plan INTEGER DEFAULT 0")
            conn.commit()
    except Exception:
        pass

    if 'decision_role' not in pcols:
        logger.info("Adding new column to prospects: decision_role")
        conn.execute("ALTER TABLE prospects ADD COLUMN decision_role TEXT")
        conn.commit()
    if 'intent_signals' not in pcols:
        logger.info("Adding new column to prospects: intent_signals")
        conn.execute("ALTER TABLE prospects ADD COLUMN intent_signals TEXT")
        conn.commit()

    # Any new string/text columns that need non-NULL defaults for existing rows
    # should follow the pattern above: ALTER → UPDATE → COMMIT



    # ── Intelligence table ──

    try:

        icols = [r[1] for r in conn.execute("PRAGMA table_info(intelligence)").fetchall()]

        for col_name, col_type in [

            ("website_key_points_prev", "TEXT"),

            ("change_flags", "TEXT"),

            ("last_auto_scraped_at", "DATETIME"),

            ("screenshot_analysis", "TEXT"),

            ("domain_registered_at", "DATETIME"),

            ("domain_expires_at", "DATETIME"),

            ("domain_registrar", "TEXT"),

            ("osint_report", "TEXT"),

            ("osint_checked_at", "DATETIME"),

        ]:

            if col_name not in icols:

                logger.info("Adding new column to intelligence: %s", col_name)

                conn.execute(f"ALTER TABLE intelligence ADD COLUMN {col_name} {col_type}")

        conn.commit()

    except Exception:

        pass  # intelligence table might not exist yet



    # ── Sample events table ──

    try:

        scols = [r[1] for r in conn.execute("PRAGMA table_info(sample_events)").fetchall()]

        for col_name, col_type in [

            ("carrier", "TEXT"),

            ("tracking_url", "TEXT"),

            ("logistics_status", "TEXT"),

            ("signed_date", "TEXT"),

            ("followup_draft_id", "INTEGER"),

            ("notified_at", "TEXT"),

            ("notified_channel", "TEXT"),

        ]:

            if col_name not in scols:

                logger.info("Adding new column to sample_events: %s", col_name)

                conn.execute(f"ALTER TABLE sample_events ADD COLUMN {col_name} {col_type}")

        conn.commit()

    except Exception:

        pass  # sample_events table might not exist yet



    # ── Interactions table ──

    try:

        icols_int = [r[1] for r in conn.execute("PRAGMA table_info(interactions)").fetchall()]

        if 'generation_meta' not in icols_int:

            logger.info("Adding new column to interactions: generation_meta")

            conn.execute("ALTER TABLE interactions ADD COLUMN generation_meta TEXT")

        if 'is_read' not in icols_int:

            logger.info("Adding new column to interactions: is_read")

            conn.execute("ALTER TABLE interactions ADD COLUMN is_read INTEGER DEFAULT 0")

            conn.execute("UPDATE interactions SET is_read = 0 WHERE is_read IS NULL")

        conn.commit()

    except Exception:

        pass  # interactions table might not exist yet



    # ── Email queue table ──

    try:

        eqcols = [r[1] for r in conn.execute("PRAGMA table_info(email_queue)").fetchall()]

        if 'sender_key' not in eqcols:

            logger.info("Adding new column to email_queue: sender_key")

            conn.execute("ALTER TABLE email_queue ADD COLUMN sender_key TEXT DEFAULT 'primary'")

            conn.execute("UPDATE email_queue SET sender_key = 'primary' WHERE sender_key IS NULL")

        if 'attachment_files' not in eqcols:

            logger.info("Adding new column to email_queue: attachment_files")

            conn.execute("ALTER TABLE email_queue ADD COLUMN attachment_files TEXT")

        if 'sent_at' not in eqcols:

            logger.info("Adding new column to email_queue: sent_at")

            conn.execute("ALTER TABLE email_queue ADD COLUMN sent_at DATETIME")

        conn.commit()

    except Exception:
        pass  # email_queue table might not exist yet

    # ── Knowledge base: self-evolution columns ──────
    try:
        kbcols = [r[1] for r in conn.execute("PRAGMA table_info(knowledge_base)").fetchall()]
        if 'source' not in kbcols:
            logger.info("Adding new column to knowledge_base: source")
            conn.execute("ALTER TABLE knowledge_base ADD COLUMN source TEXT DEFAULT 'manual'")
        if 'confidence' not in kbcols:
            logger.info("Adding new column to knowledge_base: confidence")
            conn.execute("ALTER TABLE knowledge_base ADD COLUMN confidence TEXT DEFAULT 'medium'")
        conn.commit()
    except Exception:
        pass  # knowledge_base table might not exist yet

    # ── Multi-user ownership columns (idempotent) ──────
    try:
        from services.tenant_migrate import apply_tenant_columns
        apply_tenant_columns(conn)
    except Exception as e:
        logger.warning("Tenant columns migration failed: %s", e)

    # ── Users: 个人邮件签名（每个员工可不同）──
    try:
        ucols = [r[1] for r in conn.execute("PRAGMA table_info(users)").fetchall()]
        if 'email_signature' not in ucols:
            logger.info("Adding new column to users: email_signature")
            conn.execute("ALTER TABLE users ADD COLUMN email_signature TEXT")
            conn.commit()
        if 'default_sender' not in ucols:
            logger.info("Adding new column to users: default_sender")
            conn.execute("ALTER TABLE users ADD COLUMN default_sender TEXT")
            conn.commit()
    except Exception:
        pass  # users table might not exist yet

    # ── CRITICAL SAFETY NET ──
    # is_deleted=0 is THE query filter for all prospect list views.

    # If migration left any row with is_deleted=NULL, prospects disappear.

    # This runs on EVERY startup — cheap, idempotent, catches every edge case.

    fixed = conn.execute(

        "UPDATE prospects SET is_deleted = 0 WHERE is_deleted IS NULL"

    ).rowcount

    if fixed:

        logger.warning("SAFETY NET: fixed %d prospects with is_deleted=NULL → 0", fixed)



    # Also ensure no rows have is_deleted=1 that shouldn't

    # (only run if >95% of rows are deleted — pathological case)

    total = conn.execute("SELECT COUNT(*) FROM prospects").fetchone()[0]

    deleted = conn.execute("SELECT COUNT(*) FROM prospects WHERE is_deleted = 1").fetchone()[0]

    if total > 0 and deleted > total * 0.95:

        logger.warning("SAFETY NET: %d/%d prospects are soft-deleted — recovering all", deleted, total)

        conn.execute("UPDATE prospects SET is_deleted = 0 WHERE is_deleted = 1")

        conn.commit()



    conn.commit()





@asynccontextmanager

async def lifespan(app: FastAPI):

    """Application startup / shutdown lifecycle."""

    logger.info("Creating database tables ...")

    import sqlite3, os

    _recover_db()

    from config import DATABASE_URL

    db_path = DATABASE_URL.replace("sqlite:///", "")

    db_exists = os.path.exists(db_path)



    if db_exists:

        try:

            conn = sqlite3.connect(db_path)

            _migrate_schema(conn)

            conn.close()

        except Exception as e:

            logger.warning("Schema migration failed: %s", e)



    Base.metadata.create_all(bind=engine)

    init_knowledge_base()

    init_fts5()

    start_scheduler()

    # Startup backup removed — too many restarts during dev = backup spam.

    # Daily backup handled by auto_runner.py (Windows Task Scheduler).

    from config import PORT
    logger.info("B2B Outbound OS started - http://localhost:%s", PORT)
    yield

    shutdown_scheduler()

    logger.info("B2B Outbound OS shut down.")




app = FastAPI(
    title="B2B Outbound OS — Self-Hosted Outbound CRM",
    version=__import__("config").VERSION,
    description="B2B Outbound OS: a self-hosted system for planning, sending, and tracking proactive export-sales outreach.",
    lifespan=lifespan,
)

# CORS - the frontend is served from the same origin, so restrict to self.
app.add_middleware(
    CORSMiddleware,
    allow_origins=[],
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ── Auth middleware: first run open, then login required ──
@app.middleware("http")
async def auth_middleware(request: Request, call_next):
    from database import SessionLocal
    from services import auth_service

    db = SessionLocal()
    try:
        allowed = auth_service.request_allowed(request.url.path, request.headers.get("Authorization", ""), db)
    finally:
        db.close()
    if not allowed:
        return JSONResponse(
            status_code=401,
    content={"detail": "Please sign in first"},
            headers={"WWW-Authenticate": "Bearer"},
        )
    return await call_next(request)

# ── Global exception handler — catch ALL unhandled errors and return to frontend ──
@app.middleware("http")
async def catch_all_exceptions(request: Request, call_next):
    try:

        response = await call_next(request)

        # Kill caching for JS/CSS so browser always loads latest after edits

        # Also kill caching for API responses so GET always returns fresh data

        # (browser may cache GET responses, causing "saved but old data shown" bugs)

        if request.url.path.endswith(('.js', '.css', '.html')) or request.url.path.startswith('/api/'):

            response.headers['Cache-Control'] = 'no-cache, no-store, must-revalidate'

            response.headers['Pragma'] = 'no-cache'

            response.headers['Expires'] = '0'

        return response

    except Exception as exc:
        tb = traceback.format_exc()
        logger.error("Unhandled exception on %s %s:\n%s", request.method, request.url.path, tb)
        from config import DEBUG
        detail = f"Internal server error: {type(exc).__name__} — {exc}" if DEBUG else "Internal server error"
        return JSONResponse(
            status_code=500,
            content={"detail": detail}
        )


# ── Health check for monitoring / uptime ──
@app.get("/api/health")
def health_check():
    import sqlite3
    from config import DATABASE_URL
    from services.scheduler_service import _scheduler

    db_path = DATABASE_URL.replace("sqlite:///", "")
    db = {"exists": os.path.exists(db_path), "integrity": "missing"}
    if os.path.exists(db_path):
        try:
            conn = sqlite3.connect(db_path)
            row = conn.execute("PRAGMA integrity_check").fetchone()
            conn.close()
            db["integrity"] = row[0] if row else "unknown"
        except Exception as e:
            db["integrity"] = f"error: {e}"

    scheduler = "running" if (_scheduler is not None and _scheduler.running) else "stopped"
    backup_dir = os.path.join(str(APP_DIR), "backups")
    latest_backup = None
    try:
        files = sorted(
            (os.path.join(backup_dir, f) for f in os.listdir(backup_dir) if f.startswith("backup_") and f.endswith(".db")),
            key=os.path.getmtime, reverse=True,
        )
        if files:
            latest_backup = os.path.basename(files[0])
    except Exception:
        pass

    ok = db["exists"] and db["integrity"] == "ok" and scheduler == "running"
    return {
        "status": "ok" if ok else "degraded",
        "version": __import__("config").VERSION,
        "database": db,
        "scheduler": scheduler,
        "latest_backup": latest_backup,
    }

# API Routers
from routers import prospects, intelligence, sequences, interactions, email_queue, ai, knowledge, deals, backup, sample_tracking, case_intelligence, ops, performance, setup, auth, audit, license, update, support
from routers import quote_history as quote_history_router


app.include_router(prospects.router, prefix="/api/prospects", tags=["Prospects"])

app.include_router(intelligence.router, prefix="/api/intelligence", tags=["Intelligence"])

app.include_router(sequences.router, prefix="/api/sequences", tags=["Sequences"])

app.include_router(interactions.router, prefix="/api/interactions", tags=["Interactions"])

app.include_router(email_queue.router, prefix="/api/email", tags=["Email Queue"])

app.include_router(ai.router, prefix="/api/ai", tags=["AI"])

app.include_router(knowledge.router, prefix="/api/knowledge", tags=["Knowledge Base"])

app.include_router(case_intelligence.router, prefix="/api/case-intel", tags=["CASE Intelligence"])

app.include_router(ops.router, prefix="/api/ops", tags=["Operations"])

app.include_router(performance.router, prefix="/api/performance", tags=["Performance"])
app.include_router(setup.router)
app.include_router(auth.router)
app.include_router(audit.router)
app.include_router(license.router)
app.include_router(update.router)
app.include_router(support.router)
app.include_router(deals.router, prefix="/api/deals", tags=["Deals"])

app.include_router(backup.router, tags=["Backup"])

app.include_router(sample_tracking.router, prefix="/api/sample-tracking", tags=["Sample Tracking"])
app.include_router(quote_history_router.router)


# Sell Export — registered via a separate helper (uses custom endpoint builder)

from routers.sell_export import register_sell_export_router

register_sell_export_router(app)



# Frontend SPA
import os
if getattr(sys, "frozen", False):
    # 打包模式：前端资源打进 exe 内部（_MEIPASS），数据目录在 exe 旁边
    import importlib.resources as _res
    frontend_dir = os.path.join(getattr(sys, "_MEIPASS", str(APP_DIR)), "frontend")
else:
    frontend_dir = os.path.join(str(APP_DIR), "frontend")
attachments_dir = os.path.join(str(APP_DIR), "attachments")
os.makedirs(attachments_dir, exist_ok=True)
app.mount("/attachments", StaticFiles(directory=attachments_dir), name="attachments")
app.mount("/", StaticFiles(directory=frontend_dir, html=True), name="frontend")




from config import PORT
_free_port(PORT)

if __name__ == "__main__":
    import uvicorn
    from config import HOST
    uvicorn.run(app, host=HOST, port=PORT)
