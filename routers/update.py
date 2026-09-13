"""Online update check — pulls a version manifest you host (e.g. Gitee Pages)."""

import logging
import re

from fastapi import APIRouter

from config import UPDATE_URL, VERSION

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/update", tags=["Update"])


def _version_parts(v: str):
    return [int(x) for x in re.findall(r"\d+", str(v))]


def is_newer(latest: str, current: str) -> bool:
    return _version_parts(latest) > _version_parts(current)


@router.get("/check")
async def check_update():
    """返回当前版本 + 远程清单里的最新版本（UPDATE_URL 未配置则禁用）。"""
    if not UPDATE_URL:
        return {"enabled": False, "current": VERSION}
    try:
        import httpx
        async with httpx.AsyncClient(timeout=10, follow_redirects=True) as client:
            r = await client.get(UPDATE_URL)
            data = r.json()
        latest = str(data.get("version", "")).strip()
        return {
            "enabled": True,
            "current": VERSION,
            "latest": latest,
            "has_update": bool(latest) and is_newer(latest, VERSION),
            "url": data.get("url"),
            "notes": data.get("notes", ""),
        }
    except Exception as e:
        logger.warning("update check failed: %s", e)
        return {"enabled": True, "current": VERSION, "error": str(e)}
