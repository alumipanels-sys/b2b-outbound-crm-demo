"""EPScheduler background tasks — email queue processor + IMAP checker + daily reminders."""

import asyncio
import logging

logger = logging.getLogger(__name__)

# ── Timeout guards (seconds) — prevents one stuck task from blocking the scheduler thread ──
TIMEOUT_EMAIL_QUEUE = 120
TIMEOUT_IMAP_CHECK = 60
TIMEOUT_FOLLOWUP_ENGINE = 300
TIMEOUT_COOLING_VALUE_SHARE = 300

# ── Shared event-loop helper — creates a fresh loop, runs with timeout, and cleans up ──
def _run_async(coro, timeout: int, label: str):
    """Run an async coroutine in a freshly-created event loop with a timeout.
    Unlike new_event_loop().run_until_complete(), this properly closes the loop
    so file descriptors and loop-internal resources are freed."""
    try:
        return asyncio.run(asyncio.wait_for(coro, timeout=timeout))
    except asyncio.TimeoutError:
        logger.error("%s timed out after %ds", label, timeout)
    except Exception as exc:
        logger.error("%s failed: %s", label, exc)

try:
    from apscheduler.schedulers.background import BackgroundScheduler
    from apscheduler.triggers.interval import IntervalTrigger
    from apscheduler.triggers.cron import CronTrigger
    _scheduler = BackgroundScheduler()
    SCHEDULER_READY = True
except ImportError:
    _scheduler = None
    SCHEDULER_READY = False


def start_scheduler():
    if not SCHEDULER_READY:
        logger.warning("APScheduler not available — background tasks disabled")
        return

    from services.email_service import process_email_queue

    _scheduler.add_job(
        _process_email_queue_wrapper,
        IntervalTrigger(minutes=3),
        id="process-email-queue",
        replace_existing=True,
    )
    _scheduler.add_job(
        _check_replies_wrapper,
        IntervalTrigger(minutes=3),
        id="check-imap-replies",
        replace_existing=True,
    )
    _scheduler.add_job(
        _check_todays_sequences,
        CronTrigger(hour=9, minute=0),
        id="daily-sequence-check",
        replace_existing=True,
    )
    _scheduler.add_job(
        _followup_engine_wrapper,
        CronTrigger(hour=7, minute=0),
        id="daily-followup-engine",
        replace_existing=True,
    )
    _scheduler.add_job(
        _reminder_notify_wrapper,
        CronTrigger(hour=9, minute=5),
        id="daily-followup-reminder",
        replace_existing=True,
    )
    # followup engine now only assigns nfd — no auto-drafting. 销售从今日计划人工审核。
    _scheduler.add_job(
        _auto_intel_wrapper,
        CronTrigger(hour=2, minute=0),
        id="auto-intelligence-refresh",
        replace_existing=True,
    )
    _scheduler.add_job(
        _cooling_value_share_wrapper,
        CronTrigger(day=1, hour=10, minute=0),
        id="monthly-cooling-value-share",
        replace_existing=True,
    )
    _scheduler.add_job(
        _kb_health_wrapper,
        CronTrigger(day_of_week="mon", hour=10, minute=0),
        id="weekly-kb-health",
        replace_existing=True,
    )
    _scheduler.add_job(
        _daily_team_report_wrapper,
        CronTrigger(hour=18, minute=0),
        id="daily-team-report",
        replace_existing=True,
    )

    # Backup fires immediately on service start, then every 4 hours.
    # Much more reliable than a single 23:00 cron — even if the computer
    # is off at midnight, backup runs next time the service starts.
    _scheduler.add_job(
        _backup_wrapper,
        IntervalTrigger(hours=4),
        id="daily-backup-interval",
        replace_existing=True,
    )
    logger.info("Backup: will run now + every 4 hours")
    
    _scheduler.start()
    logger.info("Scheduler started: backup (every 4h, immediate on start), email queue (3min), IMAP (3min), daily seq check (9:00), followup engine (nfd-only, 7:00), followup reminder (9:05, with cooling period), auto-intel (2:00), cooling value-share (monthly 1st 10:00), kb-health (weekly Mon 10:00), team-report (daily 18:00)")


def shutdown_scheduler():
    if _scheduler:
        _scheduler.shutdown(wait=False)
        logger.info("Scheduler shut down")


def _process_email_queue_wrapper():
    from services.email_service import process_email_queue
    _run_async(process_email_queue(), TIMEOUT_EMAIL_QUEUE, "Email queue processor")


def _followup_engine_wrapper():
    from services.followup_engine import run_followup_engine
    _run_async(run_followup_engine(max_per_run=5), TIMEOUT_FOLLOWUP_ENGINE, "Follow-up engine")


def _reminder_notify_wrapper():
    """每日跟进提醒（Server酱推微信 + 桌面通知兜底）。
    扫描 next_follow_date 已过期/今天/本周的客户（含冷却客户），每天只推一次。"""
    try:
        from auto_runner import run_reminder_notify
        run_reminder_notify()
    except Exception as exc:
        logger.error("daily followup reminder failed: %s", exc)


def _auto_intel_wrapper():
    """Sync wrapper that runs the auto-intelligence refresh loop."""
    try:
        from services.auto_intelligence import run_auto_intelligence
        run_auto_intelligence()
    except Exception as exc:
        logger.error("Auto-intelligence wrapper failed: %s", exc)


def _cooling_value_share_wrapper():
    from services.followup_engine import run_cooling_value_share
    _run_async(run_cooling_value_share(max_per_run=30), TIMEOUT_COOLING_VALUE_SHARE, "Cooling value-share")


def _kb_health_wrapper():
    """Weekly knowledge base health check + auto-gap recording."""
    try:
        from services.knowledge_engine import run_kb_health_check
        result = run_kb_health_check()
        logger.info("KB_HEALTH_WRAPPER: %s", result)
    except Exception as exc:
        logger.error("KB_HEALTH_WRAPPER failed: %s", exc)


def _daily_team_report_wrapper():
    """每日 18:00：团队工作汇报推送老板微信。"""
    try:
        from services.team_report import send_daily_team_report
        result = send_daily_team_report()
        logger.info("DAILY_TEAM_REPORT_WRAPPER: %s", result)
    except Exception as exc:
        logger.error("DAILY_TEAM_REPORT_WRAPPER failed: %s", exc)


def _backup_wrapper():
    """Daily DB backup to local backups/ + Nutstore cloud dir. Runs at 23:00."""
    import os
    from pathlib import Path
    from datetime import datetime, timedelta

    try:
        from services.backup_service import BACKUP_DIR, run_backup

        # Dedupe: if there's already a backup within the last 6 hours, skip.
        # This prevents duplicate backups on frequent service restarts.
        now_dt = datetime.now()
        for d in [BACKUP_DIR]:
            try:
                for bf in sorted(d.glob("backup_*.db"), reverse=True):
                    mtime = datetime.fromtimestamp(bf.stat().st_mtime)
                    if (now_dt - mtime).total_seconds() < 3 * 3600:
                        logger.info("BACKUP_SKIP: recent backup found (%s), skipping", bf.name)
                        return
                    break  # only check the newest file
            except Exception:
                pass

        result = run_backup()
        logger.info("BACKUP_RESULT: status=%s local=%s cloud=%s attachments=%s",
                    result.get("status"),
                    (result.get("local") or {}).get("integrity"),
                    (result.get("cloud") or {}).get("integrity"),
                    (result.get("attachments") or {}).get("status"))
        try:
            from database import SessionLocal
            from services.backup_service import record_backup
            _db = SessionLocal()
            try:
                for label in ("local", "cloud"):
                    r = result.get(label) or {}
                    if r.get("status") == "ok":
                        record_backup(_db, "db_full", r.get("path", ""), r.get("size_mb"), r.get("integrity"))
            finally:
                _db.close()
        except Exception as e:
            logger.warning("BACKUP_RECORD_ERROR: %s", e)

    except Exception as e:
        logger.error("BACKUP_ERROR: %s", e)

def _check_replies_wrapper():
    _run_async(_check_replies(), TIMEOUT_IMAP_CHECK, "IMAP reply checker")

async def _check_replies():
    """Fetch new emails via IMAP and auto-analyze inbound replies."""
    try:
        from services.email_service import fetch_new_replies
        results = await fetch_new_replies()
        if results:
            logger.info("IMAP: %d new replies imported", len(results))
    except Exception as exc:
        logger.error("IMAP check failed: %s", exc)


def _check_todays_sequences():
    """Check today's pending sequence steps — for each step, auto-generate
    an AI email draft + follow-up suggestion and store as a reminder."""

    from database import SessionLocal
    from models import Sequence, Prospect, Interaction
    from datetime import date
    from services.ai_router import call_simple_sync as call_simple

    today = date.today().isoformat()
    db = SessionLocal()
    step_count = 0

    try:
        pending_steps = (
            db.query(Sequence)
            .filter(Sequence.scheduled_date == today, Sequence.status == "pending")
            .all()
        )

        for step in pending_steps:
            prospect = db.query(Prospect).filter(Prospect.id == step.prospect_id).first()
            if not prospect:
                continue

            # Guard: if content already exists and was user-edited (not an auto draft),
            # don't overwrite it. User-edited content won't start with "[AI Draft]".
            has_user_content = step.content and step.content.strip() and not step.content.strip().startswith("[AI Draft]")
            if has_user_content and step.subject and not step.subject.startswith("[AI Draft]"):
                logger.info("Skipping step #%s (%s) — already has user-edited content, not overwriting", step.id, prospect.company)
                continue

            # Gather recent context
            interactions = (
                db.query(Interaction)
                .filter(Interaction.prospect_id == step.prospect_id)
                .order_by(Interaction.interacted_at.desc())
                .limit(5)
                .all()
            )

            # Build AI prompt
            ctx_parts = [f"TASK: Write a {step.channel} follow-up for {prospect.company or 'Unknown'} ({prospect.country or ''})."]
            ctx_parts.append(f"Profile: {prospect.profile_type or 'Unknown'}. Status: {prospect.status or 'New'}.")
            ctx_parts.append(f"Step #{step.step_number}, channel: {step.channel}.")
            if interactions:
                ctx_parts.append("Recent context:")
                for ix in interactions:
                    dtag = "[IN]" if ix.direction == "inbound" else "[OUT]"
                    ctx_parts.append(f"{dtag} {ix.channel}: {(ix.content or ix.subject or '')[:200]}")
            ctx_parts.append("Return valid JSON: {'subject':'...','body':'...'}")
            prompt = "\n".join(ctx_parts)

            try:
                raw = call_simple(prompt, 0.5, 2048)
                if raw:
                    import json as _json, re as _re
                    clean = raw.strip()
                    if "```" in clean:
                        clean = _re.sub(r"```(?:json)?\s*", "", clean).replace("```", "").strip()
                    data = _json.loads(clean)
                    step.subject = "[AI Draft] " + (data.get("subject") or step.subject or "Follow-up").replace("[AI Scheduled] ", "").replace("[AI Draft] ", "")
                    step.content = data.get("body", step.content or "")
                    db.commit()
                    logger.info("Auto-generated draft for step #%s (%s)", step.id, prospect.company)
            except Exception:
                logger.warning("Auto-draft generation failed for step #%s", step.id)

        step_count = len(pending_steps)
    except Exception as exc:
        logger.error("Sequence check failed: %s", exc)
    finally:
        db.close()
        logger.info("Daily sequence check: %d steps processed", step_count)
