"""Support helpers — one-click diagnostic export for faster issue triage."""

import logging
from datetime import datetime
from pathlib import Path

from fastapi import APIRouter, Depends
from fastapi.responses import JSONResponse
from sqlalchemy.orm import Session

from config import DATABASE_URL, VERSION
from database import get_db
from models import User
from routers.auth import get_current_user

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/support", tags=["Support"])


@router.get("/diagnostic")
def diagnostic(db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    """打包一份诊断信息（版本/自检/最近日志），客户发给卖家即可定位问题。"""
    import os
    import sqlite3

    info = {
        "version": VERSION,
        "generated_at": datetime.now().isoformat(),
        "user": user.email if user and user.email else None,
    }

    # 数据库完整性
    try:
        db_path = DATABASE_URL.replace("sqlite:///", "")
        if os.path.exists(db_path):
            conn = sqlite3.connect(db_path)
            info["database"] = conn.execute("PRAGMA integrity_check").fetchone()[0]
            conn.close()
        else:
            info["database"] = "missing"
    except Exception as e:
        info["database"] = f"error: {e}"

    # 调度器
    try:
        from services.scheduler_service import _scheduler
        info["scheduler"] = "running" if (_scheduler is not None and _scheduler.running) else "stopped"
    except Exception as e:
        info["scheduler"] = f"error: {e}"

    # 最近备份
    try:
        from services.backup_service import latest_backup_info
        lb = latest_backup_info()
        info["latest_backup"] = {
            "file": lb["filename"] if lb else None,
            "integrity": lb["integrity"] if lb else None,
        }
    except Exception as e:
        info["latest_backup"] = f"error: {e}"

    # 知识库健康度
    try:
        from services.knowledge_engine import coverage_report
        info["knowledge_score"] = coverage_report(db)["score"]
    except Exception as e:
        info["knowledge_score"] = f"error: {e}"

    # 最近日志（不包含 .env 内容）
    from config import APP_DIR
    project = APP_DIR
    logs = {}
    for name in ("auto_runner.log", "backup.log"):
        p = project / name
        if p.exists():
            try:
                lines = p.read_text(encoding="utf-8", errors="replace").splitlines()
                logs[name] = lines[-40:]
            except Exception:
                logs[name] = []
    info["logs"] = logs

    return JSONResponse(info)
