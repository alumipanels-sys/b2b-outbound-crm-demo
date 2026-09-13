"""Backup & recovery system — automated daily DB backup + full JSON export/import.



Protects against:

- Laptop failure / hard drive crash

- Accidental database corruption

- Migration to a new machine



Backups are stored in the workspace backup/ directory with timestamps.

"""



import json

import logging

import os

import platform

import shutil

import sqlite3

import uuid

from datetime import datetime, timedelta

from pathlib import Path

from typing import Optional



from fastapi import APIRouter, Depends, UploadFile, File, Form, HTTPException
from fastapi.responses import FileResponse, JSONResponse

from sqlalchemy.orm import Session



from config import DATABASE_URL, APP_DIR
from database import get_db
from models import (
    Prospect,
    Intelligence,

    Interaction,

    Sequence,

    KnowledgeBase,

    EmailQueue,

    Deal,

    SampleEvent,

    SystemSetting,
    DailyEmailStats,
    User,
    BackupRecord,
)
from routers.auth import get_current_user


logger = logging.getLogger(__name__)



router = APIRouter(prefix="/api/backup", tags=["Backup"])



BACKUP_DIR = APP_DIR / "backups"
BACKUP_DIR.mkdir(exist_ok=True)


# 坚果云同步目录 — 冷开发备份自动云端存储
from services.backup_service import (
    ENCRYPTED_SUFFIX,
    NUTSTORE_DIR,
    decrypt_backup_file,
    get_backup_password,
    verify_backup,
)
try:

    NUTSTORE_DIR.mkdir(parents=True, exist_ok=True)

    logger.info("Nutstore backup directory: %s", NUTSTORE_DIR)

except Exception:

    logger.warning("Nutstore directory not available, cloud sync disabled")

    NUTSTORE_DIR = None



DB_PATH = DATABASE_URL.replace("sqlite:///", "")

# 当前系统必需的数据库表：缺表的备份是旧版本，不能用于一键恢复（会损坏系统）
REQUIRED_BACKUP_TABLES = {"users", "tenants", "prospects", "interactions", "knowledge_base"}

# ── helpers ──────────────────────────────────────────────────


def _get_backup_files() -> list[dict]:
    """List all backup files with metadata (from local directory)."""
    files = []
    if not BACKUP_DIR.exists():
        return files
    all_files = list(BACKUP_DIR.glob("*.db")) + list(BACKUP_DIR.glob("*" + ENCRYPTED_SUFFIX))
    for f in sorted(all_files, key=lambda p: p.stat().st_mtime, reverse=True):
        stat = f.stat()
        files.append({
            "filename": f.name,
            "size_bytes": stat.st_size,
            "size_mb": round(stat.st_size / (1024 * 1024), 2),
            "created": datetime.fromtimestamp(stat.st_mtime).isoformat(),
            "encrypted": f.name.endswith(ENCRYPTED_SUFFIX),
        })
    return files


def _backup_counts(path: Path) -> dict:
    """Return lightweight health metadata for a backup DB."""

    conn = sqlite3.connect(str(path))

    try:

        integrity = conn.execute("PRAGMA integrity_check").fetchone()[0]

        tables = {

            "prospects": "SELECT COUNT(*) FROM prospects WHERE is_deleted=0 OR is_deleted IS NULL",

            "sequences": "SELECT COUNT(*) FROM sequences",

            "interactions": "SELECT COUNT(*) FROM interactions",

            "knowledge_base": "SELECT COUNT(*) FROM knowledge_base",

        }

        counts = {}

        for key, sql in tables.items():

            try:

                counts[key] = conn.execute(sql).fetchone()[0]

            except Exception:

                counts[key] = 0

        return {"integrity": integrity, "counts": counts}

    finally:
        conn.close()


def _safe_verify_backup(path: Path) -> dict:
    """同步盘（坚果云等）会锁文件，sqlite 直接打不开 → 先复制到本地临时目录再校验。"""
    tmp = BACKUP_DIR / ("verify_tmp_" + path.name)
    try:
        shutil.copy2(path, tmp)
        return _backup_counts(tmp)
    finally:
        try:
            tmp.unlink(missing_ok=True)
        except Exception:
            pass


def _backup_compatible(path: Path) -> bool:
    """备份是否包含当前版本必需的数据库表（旧版备份缺 users/tenants 会破坏系统）。"""
    try:
        conn = sqlite3.connect(str(path), timeout=3)
        try:
            tables = {r[0] for r in conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table'")}
            return REQUIRED_BACKUP_TABLES.issubset(tables)
        finally:
            conn.close()
    except Exception:
        return False


def _backup_candidates(limit: int = 20) -> list[dict]:
    """Scan local/cloud backups and return restore candidates with health info."""
    seen = set()
    candidates = []
    for directory, source in [(BACKUP_DIR, "local"), (NUTSTORE_DIR, "cloud")]:
        if not directory or not directory.exists():
            continue
        all_files = list(directory.glob("*.db")) + list(directory.glob("*" + ENCRYPTED_SUFFIX))
        for path in sorted(all_files, key=lambda p: p.stat().st_mtime, reverse=True):
            real = str(path.resolve())
            if real in seen:
                continue
            seen.add(real)
            try:
                encrypted = path.name.endswith(ENCRYPTED_SUFFIX)
                tmp_path = None
                if encrypted:
                    # 解密到临时文件再校验，恢复时用同一个密码
                    tmp_path = BACKUP_DIR / ("restore_tmp_" + path.stem + ".db")
                    decrypt_backup_file(path, tmp_path, get_backup_password())
                    meta = _backup_counts(tmp_path)
                    compatible = _backup_compatible(tmp_path)
                else:
                    # 同步盘会锁文件，先复制到本地临时目录再校验
                    meta = _safe_verify_backup(path)
                    compatible = _backup_compatible(path)
                if tmp_path:
                    try:
                        tmp_path.unlink(missing_ok=True)
                    except Exception:
                        pass
                stat = path.stat()
                candidates.append({
                    "filename": path.name,
                    "path": str(path),
                    "source": source,
                    "size_bytes": stat.st_size,

                    "size_mb": round(stat.st_size / (1024 * 1024), 2),

                    "created": datetime.fromtimestamp(stat.st_mtime).isoformat(),
                    "integrity": meta["integrity"],
                    "counts": meta["counts"],
                    "encrypted": encrypted,
                    "compatible": compatible,
                })
            except Exception as exc:
                logger.warning("Invalid backup skipped: %s (%s)", path, exc)
    candidates.sort(

        key=lambda x: (

            x["integrity"] == "ok",

            x["counts"].get("prospects", 0),

            x["created"],

            x["size_bytes"],

        ),

        reverse=True,

    )

    return candidates[:limit]



def _backup_to_path(dst_path: Path) -> dict:

    """Copy the SQLite DB to a specific path using SQLite backup API (safe online copy)."""

    src = sqlite3.connect(DB_PATH)

    dst = sqlite3.connect(str(dst_path))

    try:

        src.backup(dst)

        size_mb = round(dst_path.stat().st_size / (1024 * 1024), 2)

        return {"path": str(dst_path), "size_mb": size_mb, "status": "ok"}

    except Exception as exc:

        logger.exception("Backup to %s failed", dst_path)

        return {"error": str(exc)}

    finally:

        src.close()

        dst.close()



def _run_backup() -> dict:
    """Run the unified backup: DB (local + cloud) + attachments snapshot."""
    from services.backup_service import run_backup
    return run_backup()


BACKUP_KEEP_DAYS = 14

BACKUP_KEEP_LATEST = 20



def _cleanup_old_backups(keep_days: int = BACKUP_KEEP_DAYS, keep_latest: int = BACKUP_KEEP_LATEST):

    """Remove very old backups and cap file count per backup directory."""

    cutoff = datetime.now() - timedelta(days=keep_days)

    for directory in [BACKUP_DIR, NUTSTORE_DIR]:

        if not directory:

            continue

        removed = 0

        backup_files = sorted(directory.glob("*.db"), key=lambda p: p.stat().st_mtime, reverse=True)

        keep_set = set(backup_files[:keep_latest])

        for f in backup_files:

            mtime = datetime.fromtimestamp(f.stat().st_mtime)

            if f not in keep_set and mtime < cutoff:

                f.unlink()

                removed += 1

        if removed:

            logger.info("Cleaned up %d old backup(s) from %s", removed, directory)



# ── API endpoints ───────────────────────────────────────────



@router.get("/db")

def download_db_backup():

    """Download a fresh copy of the database right now."""

    # Create temp backup file

    ts = datetime.now().strftime("%Y%m%d_%H%M%S")

    temp_path = BACKUP_DIR / f"download_{ts}.db"

    src = sqlite3.connect(DB_PATH)

    dst = sqlite3.connect(str(temp_path))

    try:

        src.backup(dst)

    finally:

        src.close()

        dst.close()

    return FileResponse(

        path=str(temp_path),

        media_type="application/octet-stream",

        filename=f"backup_{ts}.db",

    )





@router.post("/export")
def export_full_json(db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    """Export ALL data as a single JSON file — portable, human-readable,

    can be re-imported on any machine."""



    def model_to_dict(obj):

        d = {}

        for c in obj.__table__.columns:

            val = getattr(obj, c.name)

            if isinstance(val, datetime):

                val = val.isoformat()

            d[c.name] = val

        return d



    data = {

        "export_info": {

            "version": "1.0",

            "exported_at": datetime.now().isoformat(),

            "app": "B2B Outbound OS",
            "record_counts": {},

        },

        "prospects": [model_to_dict(p) for p in db.query(Prospect).all()],

        "intelligence": [model_to_dict(i) for i in db.query(Intelligence).all()],

        "sequences": [model_to_dict(s) for s in db.query(Sequence).all()],

        "interactions": [model_to_dict(i) for i in db.query(Interaction).order_by(Interaction.created_at.asc()).all()],

        "knowledge_base": [model_to_dict(k) for k in db.query(KnowledgeBase).all()],

        "email_queue": [model_to_dict(e) for e in db.query(EmailQueue).all()],

        "deals": [model_to_dict(d) for d in db.query(Deal).all()],

        "sample_events": [model_to_dict(s) for s in db.query(SampleEvent).all()],

        "system_settings": [model_to_dict(s) for s in db.query(SystemSetting).all()],

        "daily_email_stats": [model_to_dict(s) for s in db.query(DailyEmailStats).all()],

    }



    data["export_info"]["record_counts"] = {

        k: len(v) for k, v in data.items() if k != "export_info"

    }



    # Save to file

    ts = datetime.now().strftime("%Y%m%d_%H%M%S")

    export_path = BACKUP_DIR / f"export_{ts}.json"

    with open(export_path, "w", encoding="utf-8") as f:

        json.dump(data, f, ensure_ascii=False, indent=2)



    logger.info("Full JSON export: %s", data["export_info"]["record_counts"])
    from services.backup_service import record_backup
    record_backup(db, "user_export", export_path, user_id=user.id if user and user.id else None,
                  tenant_id=user.tenant_id if user and user.id else None)

    return FileResponse(
        path=str(export_path),

        media_type="application/json",

        filename=f"export_{ts}.json",

    )





@router.post("/import")

async def import_json(file: UploadFile = File(...), db: Session = Depends(get_db)):

    """Import from a JSON export file. Existing records with matching IDs

    are updated; new records are inserted. This is a MERGE, not a wipe."""



    content = await file.read()

    try:

        data = json.loads(content)

    except json.JSONDecodeError as e:

        return JSONResponse({"error": f"Invalid JSON: {e}"}, status_code=400)



    if "export_info" not in data:

        return JSONResponse({"error": "Invalid B2B Outbound OS export file (missing export_info)"}, status_code=400)


    results = {"imported": {}, "errors": []}



    table_map = {

        "prospects": Prospect,

        "intelligence": Intelligence,

        "interactions": Interaction,

        "sequences": Sequence,

        "knowledge_base": KnowledgeBase,

        "email_queue": EmailQueue,

        "deals": Deal,

        "sample_events": SampleEvent,

        "system_settings": SystemSetting,

        "daily_email_stats": DailyEmailStats,

    }



    # Import in dependency order (prospects first, then interactions that reference them)

    import_order = [

        "prospects",

        "intelligence",

        "sequences",

        "knowledge_base",

        "interactions",

        "email_queue",

        "deals",

        "sample_events",

        "system_settings",

        "daily_email_stats",

    ]



    for key in import_order:

        ModelClass = table_map.get(key)

        if not ModelClass or key not in data:

            continue

        records = data[key]

        count_updated = 0

        count_inserted = 0

        for record in records:

            try:

                rid = record.get("id")

                if rid:

                    existing = db.query(ModelClass).filter(ModelClass.id == rid).first()

                    if existing:

                        for col_name, val in record.items():

                            if col_name != "id" and hasattr(existing, col_name):

                                setattr(existing, col_name, val)

                        count_updated += 1

                    else:

                        # Remove id to let auto-increment handle it (or keep for fixed refs like knowledge_base)

                        clean = {k: v for k, v in record.items() if k != "id" or key == "knowledge_base"}

                        db.add(ModelClass(**clean))

                        count_inserted += 1

                else:

                    db.add(ModelClass(**{k: v for k, v in record.items() if k != "id"}))

                    count_inserted += 1

            except Exception as e:

                results["errors"].append(f"{key} id={record.get('id', '?')}: {e}")

        db.commit()

        results["imported"][key] = {"updated": count_updated, "inserted": count_inserted}



    logger.info("Import completed: %s", results["imported"])

    return results





@router.get("/status")

def backup_status():
    """Show backup directory status — local, cloud, database."""
    files = _get_backup_files()
    total_size = sum(f["size_bytes"] for f in files)


    # Cloud status (include encrypted backups)
    cloud_files = []
    if NUTSTORE_DIR and NUTSTORE_DIR.exists():
        all_cloud = list(NUTSTORE_DIR.glob("*.db")) + list(NUTSTORE_DIR.glob("*" + ENCRYPTED_SUFFIX))
        for f in sorted(all_cloud, key=lambda p: p.stat().st_mtime, reverse=True):
            stat = f.stat()
            cloud_files.append({
                "filename": f.name,
                "size_mb": round(stat.st_size / (1024 * 1024), 2),
                "created": datetime.fromtimestamp(stat.st_mtime).isoformat(),
                "encrypted": f.name.endswith(ENCRYPTED_SUFFIX),
            })

    # 最近备份健康检查（本地 + 云端）
    recent = []
    for directory, source in [(BACKUP_DIR, "local"), (NUTSTORE_DIR, "cloud")]:
        if not directory or not directory.exists():
            continue
        all_b = list(directory.glob("*.db")) + list(directory.glob("*" + ENCRYPTED_SUFFIX))
        for f in sorted(all_b, key=lambda p: p.stat().st_mtime, reverse=True)[:4]:
            enc = f.name.endswith(ENCRYPTED_SUFFIX)
            v = verify_backup(f) if enc else _safe_verify_backup(f)
            recent.append({
                "filename": f.name,
                "source": source,
                "encrypted": enc,
                "integrity": v.get("integrity"),
                "created": datetime.fromtimestamp(f.stat().st_mtime).isoformat(),
            })
    recent.sort(key=lambda x: x["created"], reverse=True)
    recent = recent[:6]


    # Check if DB exists and its size

    db_size_mb = 0

    db_path = Path(DB_PATH)

    if db_path.exists():

        db_size_mb = round(db_path.stat().st_size / (1024 * 1024), 2)



    return {

        "database": {

            "path": str(db_path),

            "size_mb": db_size_mb,

            "exists": db_path.exists(),

        },

        "local_backups": {

            "directory": str(BACKUP_DIR),

            "count": len(files),

            "total_size_mb": round(total_size / (1024 * 1024), 2),

            "latest": files[0] if files else None,

        },

        "cloud_backups": {

            "directory": str(NUTSTORE_DIR) if NUTSTORE_DIR else None,

            "enabled": NUTSTORE_DIR is not None,

            "count": len(cloud_files),

            "latest": cloud_files[0] if cloud_files else None,

        },

        "retention": {
            "keep_days": BACKUP_KEEP_DAYS,
            "keep_latest_per_location": BACKUP_KEEP_LATEST,
        },
        "encryption": {
            "enabled": bool(get_backup_password()),
            "method": "AES-256-GCM (key stored only in the local .env)",
        },
        "recent_backups": recent,
    }




@router.get("/candidates")

def restore_candidates():

    """List safe restore candidates before overwriting the current DB."""

    return {"candidates": _backup_candidates(limit=20)}





@router.post("/run")
def trigger_backup(db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    """Manually trigger a database backup right now."""
    _cleanup_old_backups()
    result = _run_backup()
    from services.backup_service import record_backup
    for label in ("local", "cloud"):
        r = result.get(label) or {}
        if r.get("status") == "ok":
            record_backup(db, "db_full", r.get("path", ""), r.get("size_mb"), r.get("integrity"),
                          user_id=user.id if user and user.id else None,
                          tenant_id=user.tenant_id if user and user.id else None)
    return result




@router.post("/restore-best")
def restore_best_backup(user: User = Depends(get_current_user)):
    """One-click restore: find the backup with the most prospects and restore it.
    Steps:
    1. Scan all backup directories (local + Nutstore cloud)
    2. Pick the backup with the most active prospects (只选当前版本结构兼容的备份)
    3. Safety-copy current DB to .before_restore
    4. Overwrite current DB with best backup
    5. Return counts so frontend can confirm
    """
    if user.role not in ("owner", "admin"):
            raise HTTPException(status_code=403, detail="Only the owner/admin can restore data")
    import sqlite3

    candidates = [
        c for c in _backup_candidates(limit=50)
        if c["integrity"] == "ok" and c.get("compatible")
        and c["counts"].get("prospects", 0) > 0
    ]

    if not candidates:
        return {"success": False, "error": "No recoverable backup found (compatible structure with customer data)"}


    # Current DB status

    cur_count = 0

    try:

        cdb = sqlite3.connect(DB_PATH)

        cur_count = cdb.execute("SELECT COUNT(*) FROM prospects WHERE is_deleted=0").fetchone()[0]

        cdb.close()

    except Exception:

        pass



    best = candidates[0]

    best_path = best["path"]

    best_name = best["filename"]

    best_count = best["counts"].get("prospects", 0)



    if cur_count >= best_count:

        return {

            "success": False,

            "error": f"Current database already has {cur_count} records, no worse than the best backup ({best_count}); nothing to restore",
            "current_count": cur_count,

            "best_count": best_count,

        }



    # Safety copy

    safety_path = Path(DB_PATH).with_suffix(".before_restore")

    try:

        shutil.copy2(DB_PATH, safety_path)

        logger.info("Safety copy to %s", safety_path)

    except Exception as e:

        return {"success": False, "error": f"Could not create a safety backup: {e}"}


    # Restore（加密备份先解密到临时文件，再覆盖；不落明文到备份目录之外）
    try:
        if best.get("encrypted"):
            tmp_restore = BACKUP_DIR / ("restore_now_" + best_name)
            decrypt_backup_file(Path(best_path), tmp_restore, get_backup_password())
            shutil.copy2(tmp_restore, DB_PATH)
            try:
                tmp_restore.unlink(missing_ok=True)
            except Exception:
                pass
        else:
            shutil.copy2(best_path, DB_PATH)
        logger.info("Restored from %s (%d prospects)", best_name, best_count)
    except Exception as e:
        return {"success": False, "error": f"Restore write failed: {e}"}

    # Verify
    vdb = sqlite3.connect(DB_PATH)
    final_count = vdb.execute("SELECT COUNT(*) FROM prospects WHERE is_deleted=0").fetchone()[0]
    integrity = vdb.execute("PRAGMA integrity_check").fetchone()[0]
    vdb.close()

    return {
        "success": True,
        "restored_from": best_name,
        "previous_count": cur_count,
        "restored_count": final_count,
        "integrity": integrity,
        "safety_copy": str(safety_path),
        "candidate": best,
    }


@router.get("/records")
def backup_records(kind: str | None = None, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    """备份记录：主账号/管理员看本租户全部；成员只看自己触发的。"""
    q = db.query(BackupRecord)
    if user and user.id:
        if user.role in ("owner", "admin"):
            if user.tenant_id:
                q = q.filter(BackupRecord.tenant_id == user.tenant_id)
        else:
            q = q.filter(BackupRecord.user_id == user.id)
    if kind:
        q = q.filter(BackupRecord.kind == kind)
    rows = q.order_by(BackupRecord.created_at.desc()).limit(200).all()
    return {
        "records": [
            {
                "id": r.id,
                "kind": r.kind,
                "file_path": r.file_path,
                "size_mb": r.size_mb,
                "integrity": r.integrity,
                "user_id": r.user_id,
                "created_at": r.created_at.isoformat() if r.created_at else None,
            }
            for r in rows
        ]
    }


@router.get("/user-export")
def user_export(user_id: Optional[int] = None, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    """导出某个子账号负责的全部客户数据（含互动/序列/商机/样品）。
    主账号/管理员可指定 user_id；成员不指定时导出自己的。"""
    target_id = user_id if user_id is not None else (user.id if user else None)
    if user and user.id and user_id is not None and user.role not in ("owner", "admin"):
        raise HTTPException(status_code=403, detail="You cannot export another member's data")
    if not target_id:
        raise HTTPException(status_code=400, detail="Missing user")
    if user and user.id and user_id is not None:
        target = db.query(User).filter(User.id == user_id, User.tenant_id == user.tenant_id).first()
        if not target:
            raise HTTPException(status_code=404, detail="Member not found")

    def model_to_dict(obj):
        d = {}
        for c in obj.__table__.columns:
            val = getattr(obj, c.name)
            if isinstance(val, datetime):
                val = val.isoformat()
            d[c.name] = val
        return d

    prospects = db.query(Prospect).filter(Prospect.owner_user_id == target_id, Prospect.is_deleted == 0).all()
    pids = [p.id for p in prospects]
    data = {
        "export_info": {
            "version": "1.0",
            "exported_at": datetime.now().isoformat(),
            "app": "B2B Outbound OS",
            "kind": "user_export",
            "user_id": target_id,
            "prospect_count": len(prospects),
        },
        "prospects": [model_to_dict(p) for p in prospects],
        "intelligence": [model_to_dict(i) for i in db.query(Intelligence).filter(Intelligence.prospect_id.in_(pids)).all()] if pids else [],
        "interactions": [model_to_dict(i) for i in db.query(Interaction).filter(Interaction.prospect_id.in_(pids)).all()] if pids else [],
        "sequences": [model_to_dict(s) for s in db.query(Sequence).filter(Sequence.prospect_id.in_(pids)).all()] if pids else [],
        "deals": [model_to_dict(d) for d in db.query(Deal).filter(Deal.prospect_id.in_(pids)).all()] if pids else [],
        "sample_events": [model_to_dict(s) for s in db.query(SampleEvent).filter(SampleEvent.prospect_id.in_(pids)).all()] if pids else [],
        "email_queue": [model_to_dict(e) for e in db.query(EmailQueue).filter(EmailQueue.prospect_id.in_(pids)).all()] if pids else [],
    }
    ts = datetime.now().strftime("%Y%m%d_%H%M%S_%f")
    export_path = BACKUP_DIR / f"user_export_{target_id}_{ts}.json"
    with open(export_path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)

    from services.backup_service import record_backup
    record_backup(db, "user_export", export_path, user_id=user.id if user and user.id else target_id,
                  tenant_id=user.tenant_id if user and user.id else None)
    from services.auth_service import log_audit
    log_audit(db, user, "user_export", f"user#{target_id}", "Exported sub-account data")

    return FileResponse(
        path=str(export_path),
        media_type="application/json",
        filename=f"user_export_{target_id}_{ts}.json",
    )


@router.post("/user-restore")
async def user_restore(
    file: UploadFile = File(...),
    target_user_id: Optional[int] = Form(None),
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """把子账号导出文件恢复/合并回系统（交接闭环）。
    主账号/管理员可指定恢复到哪个成员；成员只能恢复给自己。
    按 ID 合并：已存在的客户更新，不存在的插入，归属统一到目标成员。"""
    if not user or not user.id:
        raise HTTPException(status_code=401, detail="Please log in first")
    target_id = target_user_id or user.id
    if user.role not in ("owner", "admin") and target_user_id is not None and target_user_id != user.id:
        raise HTTPException(status_code=403, detail="You cannot restore data under another member")
    if target_user_id is not None:
        target = db.query(User).filter(User.id == target_user_id, User.tenant_id == user.tenant_id).first()
        if not target:
            raise HTTPException(status_code=404, detail="Target member not found")

    content = await file.read()
    try:
        data = json.loads(content)
    except json.JSONDecodeError:
        raise HTTPException(status_code=400, detail="File is not valid JSON")
    if data.get("export_info", {}).get("kind") != "user_export":
        raise HTTPException(status_code=400, detail="Not a sub-account export file (missing user_export marker)")

    def _apply_fields(obj, record: dict):
        for k, v in record.items():
            if k != "id" and hasattr(obj, k):
                setattr(obj, k, _coerce_datetime(v))

    def _coerce_datetime(v):
        if isinstance(v, str):
            try:
                return datetime.fromisoformat(v.replace("Z", "+00:00"))
            except ValueError:
                return v
        return v

    mapping = {}
    updated = inserted = 0
    for p in data.get("prospects", []):
        rid = p.get("id")
        existing = db.query(Prospect).filter(Prospect.id == rid).first() if rid else None
        if existing:
            _apply_fields(existing, p)
            existing.owner_user_id = target_id
            updated += 1
            mapping[rid] = rid
        else:
            clean = {k: _coerce_datetime(v) for k, v in p.items() if k != "id"}
            clean["owner_user_id"] = target_id
            if user.tenant_id:
                clean["tenant_id"] = user.tenant_id
            np = Prospect(**clean)
            db.add(np)
            db.flush()
            mapping[rid] = np.id
            inserted += 1

    related = {
        "intelligence": Intelligence,
        "interactions": Interaction,
        "sequences": Sequence,
        "deals": Deal,
        "sample_events": SampleEvent,
        "email_queue": EmailQueue,
    }
    for key, Model in related.items():
        for rec in data.get(key, []):
            new_pid = mapping.get(rec.get("prospect_id"))
            if new_pid is None:
                continue
            rid = rec.get("id")
            existing = db.query(Model).filter(Model.id == rid).first() if rid else None
            if existing:
                _apply_fields(existing, rec)
            else:
                clean = {k: _coerce_datetime(v) for k, v in rec.items() if k != "id"}
                clean["prospect_id"] = new_pid
                db.add(Model(**clean))

    db.commit()
    from services.auth_service import log_audit
    log_audit(db, user, "user_restore", f"user#{target_id}", f"Restored sub-account data: {inserted} added / {updated} updated")
    return {"success": True, "prospects": {"updated": updated, "inserted": inserted}}


# ── Auto-backup on startup ───────────────────────────────────


def startup_backup():

    """Run a backup on server start, cleanup old ones."""

    try:

        _cleanup_old_backups()

        result = _run_backup()

        logger.info("Startup backup: %s", result)

    except Exception as exc:

        logger.warning("Startup backup skipped: %s", exc)

