"""Unified backup service for B2B Outbound OS.

Single source of truth for database + attachment backups. Used by:
- routers/backup.py (manual backup / status / restore)
- services/scheduler_service.py (every 4h + on start)
- auto_runner.py (daily backup task)
- backup_daily.py (Windows scheduled task)

Every backup is verified with PRAGMA integrity_check before it is reported
as successful. Attachments are snapshotted into a zip when non-empty.
"""

import logging
import os
import platform
import shutil
import sqlite3
import zipfile
from datetime import datetime, timedelta
from pathlib import Path

from config import DATABASE_URL, APP_DIR

logger = logging.getLogger(__name__)

PROJECT_DIR = APP_DIR
BACKUP_DIR = PROJECT_DIR / "backups"
ATTACHMENTS_DIR = PROJECT_DIR / "attachments"

_IS_MAC = platform.system() == "Darwin"
from config import BACKUP_CLOUD_DIR
if BACKUP_CLOUD_DIR.strip():
    NUTSTORE_DIR = Path(BACKUP_CLOUD_DIR.strip())
else:
    # 云端同步只在该版本自己配置了目录时启用；不填 = 不启用（避免多个版本共用同一路径）
    NUTSTORE_DIR = None

BACKUP_KEEP_DAYS = 30
BACKUP_KEEP_LATEST = 30
ENCRYPTED_SUFFIX = ".db.enc"
_ENC_MAGIC = b"CDENC1"

DB_PATH = DATABASE_URL.replace("sqlite:///", "")
if not os.path.isabs(DB_PATH):
    DB_PATH = str(PROJECT_DIR / DB_PATH)


def _timestamp() -> str:
    return datetime.now().strftime("%Y%m%d_%H%M%S")


_BACKUP_PASSWORD_CACHE = None


def get_backup_password() -> str:
    """备份密码：优先用 .env 里配置的；没配置就自动生成并写入 .env（本进程内缓存，密码稳定）。"""
    global _BACKUP_PASSWORD_CACHE
    if _BACKUP_PASSWORD_CACHE:
        return _BACKUP_PASSWORD_CACHE
    from config import BACKUP_PASSWORD
    pwd = (BACKUP_PASSWORD or "").strip()
    if not pwd:
        import secrets
        pwd = secrets.token_urlsafe(24)
        env_path = PROJECT_DIR / ".env"
        try:
            lines = env_path.read_text(encoding="utf-8").splitlines() if env_path.exists() else []
            replaced = False
            out = []
            for line in lines:
                if line.strip().startswith("BACKUP_PASSWORD="):
                    out.append("BACKUP_PASSWORD=" + pwd)
                    replaced = True
                else:
                    out.append(line)
            if not replaced:
                out.append("BACKUP_PASSWORD=" + pwd)
            env_path.write_text("\n".join(out) + "\n", encoding="utf-8")
            logger.info("BACKUP_PASSWORD auto-generated and persisted to .env")
        except Exception as e:
            logger.warning("BACKUP_PASSWORD persist failed: %s", e)
    _BACKUP_PASSWORD_CACHE = pwd
    return pwd


def verify_backup(path: Path) -> dict:
    """Open a backup file and return integrity + row counts."""
    result = {"integrity": "unknown", "counts": {}}
    if not path.exists() or path.stat().st_size == 0:
        result["integrity"] = "missing_or_empty"
        return result
    if str(path).endswith(ENCRYPTED_SUFFIX):
        result["integrity"] = "encrypted"
        result["encrypted"] = True
        return result
    try:
        head = path.open("rb").read(7)
        if head == _ENC_MAGIC:
            result["integrity"] = "encrypted"
            result["encrypted"] = True
            return result
    except Exception:
        pass
    try:
        conn = sqlite3.connect(str(path))
        try:
            row = conn.execute("PRAGMA integrity_check").fetchone()
            result["integrity"] = row[0] if row else "unknown"
            if result["integrity"] == "ok":
                for table, sql in {
                    "prospects": "SELECT COUNT(*) FROM prospects WHERE is_deleted=0 OR is_deleted IS NULL",
                    "sequences": "SELECT COUNT(*) FROM sequences",
                    "interactions": "SELECT COUNT(*) FROM interactions",
                    "knowledge_base": "SELECT COUNT(*) FROM knowledge_base",
                }.items():
                    try:
                        result["counts"][table] = conn.execute(sql).fetchone()[0]
                    except Exception:
                        result["counts"][table] = 0
        finally:
            conn.close()
    except Exception as e:
        result["integrity"] = f"error: {e}"
    return result


def _derive_key(password: str, salt: bytes) -> bytes:
    from cryptography.hazmat.primitives import hashes
    from cryptography.hazmat.primitives.kdf.pbkdf2 import PBKDF2HMAC
    kdf = PBKDF2HMAC(algorithm=hashes.SHA256(), length=32, salt=salt, iterations=200_000)
    return kdf.derive(password.encode("utf-8"))


def encrypt_bytes(data: bytes, password: str) -> bytes:
    from cryptography.hazmat.primitives.ciphers.aead import AESGCM
    salt = os.urandom(16)
    key = _derive_key(password, salt)
    nonce = os.urandom(12)
    ct = AESGCM(key).encrypt(nonce, data, None)
    return _ENC_MAGIC + salt + nonce + ct


def decrypt_bytes(data: bytes, password: str) -> bytes:
    if not data.startswith(_ENC_MAGIC):
        raise ValueError("Not a valid encrypted backup file (missing CDENC1 header)")
    salt = data[len(_ENC_MAGIC):len(_ENC_MAGIC) + 16]
    nonce = data[len(_ENC_MAGIC) + 16:len(_ENC_MAGIC) + 28]
    ct = data[len(_ENC_MAGIC) + 28:]
    from cryptography.hazmat.primitives.ciphers.aead import AESGCM
    key = _derive_key(password, salt)
    return AESGCM(key).decrypt(nonce, ct, None)


def encrypt_backup_file(src_path: Path, dst_path: Path, password: str) -> dict:
    data = src_path.read_bytes()
    enc = encrypt_bytes(data, password)
    dst_path.write_bytes(enc)
    return {"path": str(dst_path), "size_mb": round(dst_path.stat().st_size / (1024 * 1024), 2), "encrypted": True}


def decrypt_backup_file(src_path: Path, dst_path: Path, password: str) -> dict:
    data = src_path.read_bytes()
    plain = decrypt_bytes(data, password)
    dst_path.write_bytes(plain)
    return {"path": str(dst_path), "size_mb": round(dst_path.stat().st_size / (1024 * 1024), 2)}


def _backup_encrypted(src_path: str, dst_path: Path, password: str) -> dict:
    """Safe-copy DB, encrypt it, then verify by decrypting + integrity check."""
    tmp = dst_path.with_name(dst_path.name + ".tmp")
    verify_tmp = dst_path.with_name(dst_path.name + ".verify")
    try:
        base = backup_database(src_path, tmp)
        if base["status"] != "ok":
            return {"status": "failed", "error": "plaintext copy failed", "integrity": base["integrity"]}
        enc = encrypt_backup_file(tmp, dst_path, password)
        decrypt_backup_file(dst_path, verify_tmp, password)
        check = verify_backup(verify_tmp)
        ok = check["integrity"] == "ok"
        return {
            "path": str(dst_path),
            "size_mb": enc["size_mb"],
            "encrypted": True,
            "integrity": check["integrity"],
            "status": "ok" if ok else "failed",
        }
    except Exception as e:
        logger.error("ENCRYPTED_BACKUP_ERROR: %s", e)
        return {"status": "failed", "error": str(e), "encrypted": True}
    finally:
        for p in (tmp, verify_tmp):
            try:
                p.unlink(missing_ok=True)
            except Exception:
                pass


def backup_database(src_path: str, dst_path: Path) -> dict:
    """SQLite online safe-copy + integrity verification of the copy."""
    src = sqlite3.connect(src_path)
    dst = sqlite3.connect(str(dst_path))
    try:
        src.backup(dst)
    finally:
        src.close()
        dst.close()

    check = verify_backup(dst_path)
    return {
        "path": str(dst_path),
        "size_mb": round(dst_path.stat().st_size / (1024 * 1024), 2),
        "integrity": check["integrity"],
        "status": "ok" if check["integrity"] == "ok" else "failed",
    }


def snapshot_attachments(dst_dir: Path, ts: str) -> dict:
    """Zip attachments/ into dst_dir if it contains files."""
    if not ATTACHMENTS_DIR.exists():
        return {"status": "skipped", "reason": "no attachments dir"}
    files = [f for f in ATTACHMENTS_DIR.iterdir() if f.is_file()]
    if not files:
        return {"status": "skipped", "reason": "attachments empty"}
    try:
        dst_dir.mkdir(parents=True, exist_ok=True)
        zip_path = dst_dir / f"attachments_{ts}.zip"
        with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as zf:
            for f in files:
                zf.write(f, arcname=f.name)
        return {
            "status": "ok",
            "path": str(zip_path),
            "files": len(files),
            "size_mb": round(zip_path.stat().st_size / (1024 * 1024), 2),
        }
    except Exception as e:
        logger.error("ATTACHMENTS_BACKUP_ERROR: %s", e)
        return {"status": "failed", "error": str(e)}


def cleanup_old_backups(keep_days: int = BACKUP_KEEP_DAYS, keep_latest: int = BACKUP_KEEP_LATEST):
    """Remove backups older than keep_days, always keeping the newest N."""
    cutoff = datetime.now() - timedelta(days=keep_days)
    for directory in [BACKUP_DIR, NUTSTORE_DIR]:
        if not directory or not directory.exists():
            continue
        try:
            backups = sorted(
                [p for p in directory.iterdir() if p.name.startswith("backup_") and (p.name.endswith(".db") or p.name.endswith(ENCRYPTED_SUFFIX))],
                key=lambda p: p.stat().st_mtime, reverse=True,
            )
            keep = set(backups[:keep_latest])
            removed = 0
            for f in backups:
                mtime = datetime.fromtimestamp(f.stat().st_mtime)
                if f not in keep and mtime < cutoff:
                    f.unlink()
                    removed += 1
            if removed:
                logger.info("BACKUP_CLEANUP: removed %d old backup(s) from %s", removed, directory)
        except Exception as e:
            logger.warning("BACKUP_CLEANUP_ERROR: %s", e)


def run_backup(include_attachments: bool = True) -> dict:
    """Run a full backup: DB -> local + cloud, attachments -> local zip."""
    if not os.path.exists(DB_PATH):
        logger.error("BACKUP_SKIP: database file not found: %s", DB_PATH)
        return {"status": "skipped", "reason": "database file not found"}

    ts = _timestamp()
    filename = f"backup_{ts}"
    results = {"status": "ok", "filename": filename, "local": None, "cloud": None, "attachments": None}
    password = get_backup_password()

    for dst_dir, label in [(BACKUP_DIR, "local"), (NUTSTORE_DIR, "cloud")]:
        if label == "cloud" and not NUTSTORE_DIR:
            continue
        try:
            dst_dir.mkdir(parents=True, exist_ok=True)
            if password:
                fname = filename + ENCRYPTED_SUFFIX
                r = _backup_encrypted(DB_PATH, dst_dir / fname, password)
                logger.info("BACKUP_%s_ENCRYPTED: %s (%.2f MB, integrity=%s)", label.upper(), fname, r.get("size_mb", 0), r.get("integrity"))
            else:
                fname = filename + ".db"
                r = backup_database(DB_PATH, dst_dir / fname)
                logger.info("BACKUP_%s: %s (%.2f MB, integrity=%s)", label.upper(), fname, r["size_mb"], r["integrity"])
            results[label] = r
            if r["status"] != "ok":
                results["status"] = "degraded"
        except Exception as e:
            logger.error("BACKUP_%s_ERROR: %s", label.upper(), e)
            results[label] = {"status": "failed", "error": str(e)}
            results["status"] = "degraded"

    if include_attachments:
        results["attachments"] = snapshot_attachments(BACKUP_DIR, ts)
    if password and results.get("local") and results["local"].get("encrypted"):
        results["encrypted"] = True

    cleanup_old_backups()
    return results


def latest_backup_info() -> dict:
    """Newest verified backup across local + cloud."""
    candidates = []
    for directory, source in [(BACKUP_DIR, "local"), (NUTSTORE_DIR, "cloud")]:
        if not directory or not directory.exists():
            continue
        files = sorted(
            [p for p in directory.iterdir() if p.name.startswith("backup_") and (p.name.endswith(".db") or p.name.endswith(ENCRYPTED_SUFFIX))],
            key=lambda x: x.stat().st_mtime, reverse=True,
        )
        for p in files[:3]:
            v = verify_backup(p)
            candidates.append({
                "filename": p.name,
                "path": str(p),
                "source": source,
                "size_mb": round(p.stat().st_size / (1024 * 1024), 2),
                "created": datetime.fromtimestamp(p.stat().st_mtime).isoformat(),
                **v,
            })
    candidates.sort(key=lambda x: (x["integrity"] == "ok", x["created"]), reverse=True)
    return candidates[0] if candidates else None


def record_backup(db, kind: str, file_path, size_mb=None, integrity=None, user_id=None, tenant_id=None) -> bool:
    """Record a backup/export in backup_records (who backed up what)."""
    from models import BackupRecord
    try:
        p = Path(str(file_path))
        if size_mb is None:
            size_mb = round(p.stat().st_size / (1024 * 1024), 2) if p.exists() else 0
        db.add(BackupRecord(
            kind=kind,
            file_path=str(p),
            size_mb=size_mb or 0,
            integrity=integrity or "ok",
            user_id=user_id,
            tenant_id=tenant_id,
        ))
        db.commit()
        return True
    except Exception as e:
        logger.warning("record_backup failed: %s", e)
        db.rollback()
        return False
