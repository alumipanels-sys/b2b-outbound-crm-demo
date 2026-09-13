"""Operational automation endpoints for cold outreach.

This router productizes two loops that already exist in pieces:
- prospect intelligence refresh coverage and manual/batch runs
- inbound reply analysis closure and next-follow-up scheduling
"""

from __future__ import annotations

import asyncio
from datetime import datetime, timezone
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from database import get_db
from models import EmailQueue, Intelligence, Interaction, Prospect, User
from routers.auth import get_current_user
from services.auto_intelligence import CADENCE, _needs_refresh, refresh_single_prospect

router = APIRouter()


@router.get("/team-dashboard")
def team_dashboard(days: int = Query(1, ge=1, le=30), db: Session = Depends(get_db),
                   user: User = Depends(get_current_user)):
    """团队工作看板：每个子账号每天发了多少信、收到多少回复、还有多少客户待跟进。"""
    if user.role not in ("owner", "admin"):
            raise HTTPException(status_code=403, detail="Only the owner/admin can view the team dashboard")
    from services.team_service import team_dashboard_stats
    return team_dashboard_stats(db, user.tenant_id, days=days)


@router.get("/team-targets")
def team_targets(db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    """每日目标考核：老板看全员周进度；成员看自己（今日工作台复用）。纯展示、不限制发送。"""
    from services.target_service import team_target_stats, member_week_progress
    if user.role in ("owner", "admin"):
        return team_target_stats(db, user.tenant_id)
    return member_week_progress(db, user.tenant_id, user.id)


@router.put("/team-targets/{user_id}")
def set_team_target(user_id: int, target: int, db: Session = Depends(get_db),
                    user: User = Depends(get_current_user)):
    """老板设置某成员的每日目标（无硬拦截，仅数字合法性兜底）。"""
    if user.role not in ("owner", "admin"):
            raise HTTPException(status_code=403, detail="Only the owner/admin can set targets")
    from services.target_service import set_target
    t = set_target(db, user.tenant_id, user_id, target)
    from services.auth_service import log_audit
    try:
        log_audit(db, user, "update_target", f"user#{user_id}", f"Daily target changed to {t.target_per_day}")
    except Exception:
        pass
    return {"ok": True, "target_per_day": t.target_per_day}


def _has_text(value: str | None) -> bool:
    return bool((value or "").strip())


def _intel_status(prospect: Prospect, intel: Intelligence | None) -> dict[str, Any]:
    has_website = _has_text(prospect.website)
    last = intel.last_auto_scraped_at if intel else None
    due = has_website and _needs_refresh(prospect, intel)
    profile = prospect.profile_type or "C"
    return {
        "prospect_id": prospect.id,
        "company": prospect.company,
        "country": prospect.country,
        "profile_type": prospect.profile_type,
        "value_level": prospect.value_level,
        "website": prospect.website,
        "has_website": has_website,
        "last_auto_scraped_at": last.isoformat() if last else None,
        "cadence_days": CADENCE.get(profile, 10),
        "due": due,
        "website_key_points": bool(intel and _has_text(intel.website_key_points)),
        "icebreak_angles": bool(intel and _has_text(intel.icebreak_angles)),
        "hiring_signals": bool(intel and _has_text(intel.hiring_signals)),
        "osint_report": bool(intel and _has_text(intel.osint_report)),
        "change_flags": intel.change_flags if intel else None,
    }


@router.get("/intelligence/status")
async def intelligence_status(db: Session = Depends(get_db)):
    prospects = db.query(Prospect).filter(Prospect.is_deleted == 0).all()
    intel_by_pid = {i.prospect_id: i for i in db.query(Intelligence).all()}
    rows = [_intel_status(p, intel_by_pid.get(p.id)) for p in prospects]
    website_rows = [r for r in rows if r["has_website"]]
    key_rows = [r for r in rows if r["website_key_points"]]
    ice_rows = [r for r in rows if r["icebreak_angles"]]
    hiring_rows = [r for r in rows if r["hiring_signals"]]
    osint_rows = [r for r in rows if r["osint_report"]]
    due_rows = [r for r in rows if r["due"]]
    never_rows = [r for r in rows if r["has_website"] and not r["last_auto_scraped_at"]]
    return {
        "overview": {
            "active_prospects": len(rows),
            "with_website": len(website_rows),
            "website_coverage_rate": round(len(website_rows) / max(len(rows), 1) * 100, 1),
            "with_key_points": len(key_rows),
            "key_point_rate": round(len(key_rows) / max(len(website_rows), 1) * 100, 1),
            "with_icebreakers": len(ice_rows),
            "icebreaker_rate": round(len(ice_rows) / max(len(website_rows), 1) * 100, 1),
            "with_hiring_signals": len(hiring_rows),
            "hiring_signal_rate": round(len(hiring_rows) / max(len(website_rows), 1) * 100, 1),
            "with_osint": len(osint_rows),
            "osint_rate": round(len(osint_rows) / max(len(website_rows), 1) * 100, 1),
            "due_refresh": len(due_rows),
            "never_scraped": len(never_rows),
        },
        "due": sorted(due_rows, key=lambda r: (r["last_auto_scraped_at"] or "", r["profile_type"] or ""))[:100],
        "rows": rows[:300],
    }


@router.post("/intelligence/refresh/{prospect_id}")
async def refresh_intelligence_one(prospect_id: int, db: Session = Depends(get_db)):
    result = await refresh_single_prospect(prospect_id, db)
    return {"success": result.get("status") == "ok", **result}


@router.post("/intelligence/refresh-due")
async def refresh_intelligence_due(
    limit: int = Query(5, ge=1, le=30),
    db: Session = Depends(get_db),
):
    prospects = (
        db.query(Prospect)
        .filter(Prospect.is_deleted == 0, Prospect.website.isnot(None), Prospect.website != "")
        .order_by(Prospect.ai_score.desc().nullslast(), Prospect.id.asc())
        .all()
    )
    due = []
    for p in prospects:
        intel = db.query(Intelligence).filter(Intelligence.prospect_id == p.id).first()
        if _needs_refresh(p, intel):
            due.append(p)
        if len(due) >= limit:
            break

    results = []
    for p in due:
        results.append(await refresh_single_prospect(p.id, db))
        await asyncio.sleep(0.2)

    return {"success": True, "processed": len(results), "results": results}


def _normalize_timing(value: str | None) -> str | None:
    text = (value or "").lower()
    if any(k in text for k in ["now", "today", "24", "asap", "immediate", "马上", "今天"]):
        return datetime.utcnow().date().isoformat()
    if any(k in text for k in ["tomorrow", "明天"]):
        from datetime import timedelta

        return (datetime.utcnow().date() + timedelta(days=1)).isoformat()
    if any(k in text for k in ["week", "7", "一周"]):
        from datetime import timedelta

        return (datetime.utcnow().date() + timedelta(days=7)).isoformat()
    return None


async def _close_reply(interaction: Interaction, db: Session, force: bool = False) -> dict[str, Any]:
    if interaction.direction != "inbound":
        return {"interaction_id": interaction.id, "success": False, "error": "not inbound"}
    if interaction.reply_intent and not force:
        return {"interaction_id": interaction.id, "success": True, "skipped": True, "intent": interaction.reply_intent}

    from routers.ai import analyze_reply

    analyzed = await analyze_reply(interaction.id, payload=None, db=db)
    if not analyzed.get("success"):
        return {"interaction_id": interaction.id, "success": False, "error": analyzed.get("error")}

    db.refresh(interaction)
    prospect = db.query(Prospect).filter(Prospect.id == interaction.prospect_id, Prospect.is_deleted == 0).first()
    if prospect:
        prospect.status = "Replied"
        prospect.sales_stage = "replied"  # 同步阶段，让列表排序和筛选生效
        suggested_date = _normalize_timing(interaction.ai_suggested_timing)
        if suggested_date:
            prospect.next_follow_date = suggested_date
        if interaction.ai_suggested_action:
            prospect.reminder_note = interaction.ai_suggested_action[:500]
        prospect.last_edited_at = datetime.utcnow()
        from services.company_sync import sync_company_main
        sync_company_main(db, prospect)
        db.commit()

    return {
        "interaction_id": interaction.id,
        "success": True,
        "prospect_id": interaction.prospect_id,
        "intent": interaction.reply_intent,
        "suggested_action": interaction.ai_suggested_action,
        "suggested_channel": interaction.ai_suggested_channel,
        "suggested_timing": interaction.ai_suggested_timing,
        "next_follow_date": prospect.next_follow_date if prospect else None,
    }


def _safe_sort_key(x):
    """Sort key that normalizes naive/aware datetimes to avoid TypeError."""
    dt = x.interacted_at
    if dt is None:
        return datetime.min.replace(tzinfo=timezone.utc)
    if dt.tzinfo is None:
        return dt.replace(tzinfo=timezone.utc)
    return dt


@router.get("/replies/status")
async def replies_status(db: Session = Depends(get_db)):
    inbound = db.query(Interaction).filter(Interaction.direction == "inbound").all()
    unclosed = [i for i in inbound if not _has_text(i.reply_intent)]
    hot = [
        i
        for i in inbound
        if (i.reply_intent or "").upper()
        in ("HOT_LEAD", "SAMPLE", "PRICING", "INFORMATION_REQUEST", "COOPERATION")
    ]
    return {
        "overview": {
            "inbound_replies": len(inbound),
            "analyzed": len(inbound) - len(unclosed),
            "unclosed": len(unclosed),
            "analysis_rate": round((len(inbound) - len(unclosed)) / max(len(inbound), 1) * 100, 1),
            "hot_or_actionable": len(hot),
        },
        "unclosed": [
            {
                "id": i.id,
                "prospect_id": i.prospect_id,
                "from": i.email_from,
                "subject": i.subject,
                "channel": i.channel,
                "interacted_at": i.interacted_at.isoformat() if i.interacted_at else None,
                "preview": (i.content or "")[:180],
            }
            for i in sorted(unclosed, key=_safe_sort_key, reverse=True)[:100]
        ],
    }


@router.post("/replies/close/{interaction_id}")
async def close_reply_one(
    interaction_id: int,
    force: bool = Query(False),
    db: Session = Depends(get_db),
):
    interaction = db.query(Interaction).filter(Interaction.id == interaction_id).first()
    if not interaction:
        return {"success": False, "error": "interaction not found"}
    return await _close_reply(interaction, db, force=force)


@router.post("/replies/close-unclosed")
async def close_unclosed_replies(
    limit: int = Query(10, ge=1, le=50),
    db: Session = Depends(get_db),
):
    rows = (
        db.query(Interaction)
        .filter(Interaction.direction == "inbound")
        .order_by(Interaction.interacted_at.desc())
        .limit(500)
        .all()
    )
    # 跳过已有 reply_intent 和退信的
    targets = [i for i in rows if not _has_text(i.reply_intent) and i.reply_intent not in ("bounce", "退信")][:limit]
    results = []
    for interaction in targets:
        try:
            results.append(await _close_reply(interaction, db, force=False))
        except Exception as exc:
            logger.error("close_unclosed failed for interaction %s: %s", interaction.id, exc)
            results.append({"interaction_id": interaction.id, "success": False, "error": str(exc)})
    return {"success": True, "processed": len(results), "results": results}


@router.get("/trade-shows/status")
async def trade_shows_status():
    from services.trade_show_calendar import CACHE_PATH, get_trade_show_catalog, get_upcoming_shows

    shows = get_trade_show_catalog()
    upcoming = get_upcoming_shows(days_ahead=180)
    cache = {}
    if CACHE_PATH.exists():
        try:
            import json
            cache = json.loads(CACHE_PATH.read_text(encoding="utf-8"))
        except Exception:
            cache = {}
    source_rows = cache.get("shows", {}) if isinstance(cache, dict) else {}
    verified = [s for s in source_rows.values() if s.get("status") == "verified"]
    source_errors = [s for s in source_rows.values() if s.get("status") == "source_error"]

    return {
        "success": True,
        "cache_path": str(CACHE_PATH),
        "cache_updated_at": cache.get("updated_at"),
        "total_seed_shows": len(shows),
        "verified_sources": len(verified),
        "source_errors": len(source_errors),
        "upcoming_180_days": [
            {
                "name": s["name"],
                "location": s["location"],
                "date_range": f"{s['dates'][0].isoformat()} to {s['dates'][1].isoformat()}",
                "priority": s["priority"],
                "source_status": s.get("source_status"),
                "source_url": s.get("source_url"),
            }
            for s in upcoming[:20]
        ],
    }


@router.get("/trade-shows/prospect/{prospect_id}")
async def trade_show_signals_for_prospect(prospect_id: int, db: Session = Depends(get_db)):
    from services.trade_show_calendar import get_prospect_trade_show_signals, get_show_icebreaker

    prospect = db.query(Prospect).filter(Prospect.id == prospect_id, Prospect.is_deleted == 0).first()
    if not prospect:
        return {"success": False, "error": "prospect not found"}

    signals = get_prospect_trade_show_signals(
        country=prospect.country,
        industry=prospect.industry,
        profile_type=prospect.profile_type,
        limit=5,
    )
    icebreaker = get_show_icebreaker(
        country=prospect.country,
        industry=prospect.industry,
        profile_type=prospect.profile_type,
    )
    return {
        "success": True,
        "prospect": {
            "id": prospect.id,
            "company": prospect.company,
            "country": prospect.country,
            "industry": prospect.industry,
            "profile_type": prospect.profile_type,
        },
        "icebreaker": icebreaker,
        "signals": [
            {
                "name": s["name"],
                "location": s["location"],
                "date_range": s["date_range"],
                "priority": s["priority"],
                "fit_score": s["fit_score"],
                "phase": s["phase_label"],
                "timing_angle": s["timing_angle"],
                "source_url": s.get("source_url"),
            }
            for s in sorted(signals, key=lambda s: s["fit_score"], reverse=True)[:20]
        ],
        "confidence": "high" if len(signals) >= 3 else "medium" if signals else "low",
    }
