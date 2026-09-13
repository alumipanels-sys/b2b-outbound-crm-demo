"""Email queue router — timezone-aware queuing, rate-limit stats, IMAP trigger."""

import json
import logging
import os
import random
import re
import uuid
from datetime import datetime, date, timedelta, timezone
from zoneinfo import ZoneInfo

from fastapi import APIRouter, Depends, HTTPException, UploadFile, File
from sqlalchemy import or_
from sqlalchemy.orm import Session

from database import get_db
from models import EmailAccount, EmailQueue, DailyEmailStats, Prospect, Sequence, Interaction, SystemSetting, User
from config import DAILY_EMAIL_LIMIT, APP_DIR
from schemas import EmailQueueCreate, EmailQueueOut, EmailStatsOut
from routers.auth import get_current_user
from services.email_service import check_daily_limit, decode_mail_bytes, is_business_hours_now, get_next_send_time

logger = logging.getLogger(__name__)
router = APIRouter()


def _add_business_days(start: date, n: int) -> date:
    """从 start 往后数 n 个工作日（跳过周六周日），返回目标日期。"""
    d = start
    added = 0
    while added < n:
        d += timedelta(days=1)
        if d.weekday() < 5:
            added += 1
    return d


def _auto_complete_new_outreach(prospect_id: int, db):
    """If this prospect was in today's new outreach pool, auto-complete:
    clear new_outreach_date, mark touched, set 3-day follow-up."""
    from datetime import date as _date
    p = db.query(Prospect).filter(Prospect.id == prospect_id).first()
    if not p:
        return
    no_date = (p.new_outreach_date or "").strip()
    if not no_date:
        return  # not a new outreach prospect, nothing to do
    p.new_outreach_date = ""
    if (p.sales_stage or "new") == "new":
        p.sales_stage = "touched"
    next_f = _add_business_days(_date.today(), 3)
    p.next_follow_date = next_f.isoformat()
    p.reminder_note = f"[New outreach] first email sent — follow up {next_f.isoformat()}"
    db.commit()
    logger.info("Auto-completed new outreach for prospect #%d", prospect_id)


def _next_day_send_time(prospect: Prospect | None):
    """Move overflowed sends to the next business morning."""
    if not prospect or not (prospect.timezone or "").strip():
        return datetime.utcnow() + timedelta(days=1)
    try:
        tz = ZoneInfo((prospect.timezone or "").strip())
        local = datetime.now(tz) + timedelta(days=1)
        while local.weekday() >= 5:
            local += timedelta(days=1)
        target = datetime(local.year, local.month, local.day, 9, 15, tzinfo=tz)
        return target.astimezone(timezone.utc).replace(tzinfo=None)
    except Exception:
        return datetime.utcnow() + timedelta(days=1)


@router.post("/queue", response_model=EmailQueueOut)
async def queue_email(payload: EmailQueueCreate, db: Session = Depends(get_db),
                      user: User = Depends(get_current_user)):
    """Create an email draft by default.

    AI and automation may create hundreds of drafts, but nothing is sendable
    until a human explicitly approves the draft into pending status.
    """
    prospect = db.query(Prospect).filter(Prospect.id == payload.prospect_id).first()
    if not prospect:
        if payload.prospect_id == 0:
            # Allow unmatched inbox replies — keep as draft without prospect.
            pass
        else:
            raise HTTPException(status_code=404, detail="Prospect not found")

    # 成员只能用自己绑定的邮箱发信；主账号/管理员可以用任意邮箱
    if user and user.role == "member":
        from services.email_service import get_available_senders
        bound = None
        for s in get_available_senders(db):
            if s.get("bound_user_id") == user.id:
                bound = s["key"]
                break
        if not bound:
            raise HTTPException(
                status_code=403,
                detail="You do not have a sending mailbox bound yet — ask the owner to bind one in System Settings → Email Accounts",
            )
        payload.sender_key = bound

    # 记住该客户最近使用的发件邮箱（下次给这个客户发信默认用它，防止选错）
    if prospect:
        sender_key_final = getattr(payload, "sender_key", "primary") or "primary"
        try:
            if prospect.sender_key != sender_key_final:
                prospect.sender_key = sender_key_final
                db.add(prospect)
        except Exception:
            pass

    # Honor explicit status if passed (e.g. "pending" for auto-send from dev plan)
    final_status = payload.status if payload.status and payload.status != "draft" else "draft"
    eq = EmailQueue(
        prospect_id=payload.prospect_id,
        sequence_id=payload.sequence_id,
        to_email=payload.to_email,
        subject=payload.subject,
        body=payload.body,
        status=final_status,
        sender_key=getattr(payload, "sender_key", "primary") or "primary",
        owner_user_id=user.id if user and user.id else None,
    )
    if payload.attachment_files:
        eq.attachment_files = payload.attachment_files

    if payload.scheduled_at:
        eq.scheduled_at = payload.scheduled_at
    elif final_status == "pending" and payload.sequence_id:
        # Auto-send: use the sequence step's scheduled_date as the send time
        seq = db.query(Sequence).filter(Sequence.id == payload.sequence_id).first()
        if seq and seq.scheduled_date:
            try:
                eq.scheduled_at = datetime.strptime(seq.scheduled_date[:10], "%Y-%m-%d").replace(hour=9, minute=15)
            except (ValueError, TypeError):
                pass
    if not eq.scheduled_at and final_status == "pending":
        eq.scheduled_at = datetime.utcnow() + timedelta(minutes=5)

    logger.info("Email draft created for review: %s", payload.to_email)

    db.add(eq)
    if prospect and prospect.id:
        # 存草稿/定时发送后自动填“下次跟进”（3 个工作日后，可手动改）。
        # 只有客户还没有未来跟进日期时才自动排，避免覆盖你手动排好的计划。
        from datetime import date as _date, timedelta as _td
        existing_nfd = (prospect.next_follow_date or "").strip()[:10]
        try:
            has_future = existing_nfd and _date.fromisoformat(existing_nfd) > _date.today()
        except ValueError:
            has_future = False
        if not has_future:
            nd = _add_business_days(_date.today(), 3)
            prospect.next_follow_date = nd.isoformat()
            prospect.reminder_note = f"[Draft] saved to drafts — follow up {nd.isoformat()}" if final_status == "draft" else f"[Queue] scheduled to send — follow up {nd.isoformat()}"
        db.add(prospect)
    db.commit()
    db.refresh(eq)
    try:
        from services.auth_service import log_audit
        log_audit(db, user, "email_draft", f"prospect#{payload.prospect_id}",
                  f"Created {'draft' if final_status == 'draft' else 'queued'} email: {(payload.subject or '')[:80]}")
    except Exception:
        pass
    return EmailQueueOut.model_validate(eq)


@router.get("/queue", response_model=list[EmailQueueOut])
async def get_queue(status: str | None = None, prospect_id: int | None = None, db: Session = Depends(get_db)):
    """View email queue, optionally filtered by status and/or prospect_id."""
    q = db.query(EmailQueue).order_by(EmailQueue.created_at.desc())
    if status:
        q = q.filter(EmailQueue.status == status)
    if prospect_id is not None:
        q = q.filter(EmailQueue.prospect_id == prospect_id)
    items = q.limit(200).all()
    results = []
    for i in items:
        out = EmailQueueOut.model_validate(i)
        if i.prospect_id and i.prospect_id > 0:
            p = db.query(Prospect).filter(Prospect.id == i.prospect_id).first()
            if p:
                out.company = p.company + (" (client deleted)" if p.is_deleted else "")
                out.timezone = p.timezone
            else:
                out.company = "(client record no longer exists)"
        results.append(out)
    return results


@router.post("/queue/{queue_id}/cancel", response_model=EmailQueueOut)
async def cancel_queued_email(queue_id: int, db: Session = Depends(get_db)):
    """Cancel a pending or draft email in the queue."""
    eq = db.query(EmailQueue).filter(EmailQueue.id == queue_id).first()
    if not eq:
        raise HTTPException(status_code=404, detail="Email queue item not found")
    if eq.status not in ("pending", "draft"):
        raise HTTPException(status_code=400, detail=f"Cannot cancel email with status '{eq.status}'")

    eq.status = "cancelled"
    db.commit()
    db.refresh(eq)
    return EmailQueueOut.model_validate(eq)


@router.delete("/queue/{queue_id}")
async def delete_queued_email(queue_id: int, db: Session = Depends(get_db)):
    """Permanently delete a draft / pending / cancelled email from the queue."""
    eq = db.query(EmailQueue).filter(EmailQueue.id == queue_id).first()
    if not eq:
        raise HTTPException(status_code=404, detail="Email queue item not found")
    if eq.status not in ("draft", "cancelled", "pending"):
        raise HTTPException(status_code=400, detail=f"Cannot delete email with status '{eq.status}'")

    db.delete(eq)
    db.commit()
    return {"success": True, "deleted_id": queue_id, "message": "Email permanently deleted"}


@router.put("/queue/{queue_id}")
async def update_queued_email(queue_id: int, payload: dict, db: Session = Depends(get_db)):
    """Edit a draft/pending email, or approve a draft into the pending queue."""
    eq = db.query(EmailQueue).filter(EmailQueue.id == queue_id).first()
    if not eq:
        raise HTTPException(status_code=404, detail="Email queue item not found")
    if eq.status not in ("draft", "pending"):
        raise HTTPException(status_code=400, detail=f"Cannot edit email with status '{eq.status}'")

    from datetime import datetime as _dt

    if "subject" in payload and payload["subject"]:
        eq.subject = payload["subject"]
    if "body" in payload and payload["body"]:
        eq.body = payload["body"]
    if "sender_key" in payload and payload["sender_key"]:
        eq.sender_key = payload["sender_key"]
    if "scheduled_at" in payload and payload["scheduled_at"]:
        try:
            eq.scheduled_at = _dt.fromisoformat(payload["scheduled_at"])
        except Exception:
            pass
    if "status" in payload and payload["status"]:
        if eq.status in ("draft",) and payload["status"] == "pending":
            if not eq.to_email:
                raise HTTPException(status_code=400, detail="Cannot approve email without recipient.")
            eq.status = "pending"
            # 保留用户已设定的发送时间（本次请求带的，或之前已保存的）；
            # 只有草稿还没有发送时间时才自动计算，避免覆盖用户选的未来日期。
            if not payload.get("scheduled_at") and not eq.scheduled_at:
                try:
                    p = db.query(Prospect).filter(Prospect.id == eq.prospect_id).first()
                    # 发送时间只按客户时区的下一个工作日 9-11 点算，
                    # 绝不拿“下次跟进日期”(next_follow_date)当发送时间——那是提醒日期，不是发送日期。
                    next_time = get_next_send_time(p) if p else None
                    eq.scheduled_at = next_time if next_time else datetime.utcnow()
                except Exception:
                    eq.scheduled_at = datetime.utcnow()
            eq.daily_send_date = (eq.scheduled_at.strftime("%Y-%m-%d")
                                  if eq.scheduled_at else _dt.utcnow().strftime("%Y-%m-%d"))

    # ── Sync back to linked sequence step if exists ──
    if eq.sequence_id:
        seq = db.query(Sequence).filter(Sequence.id == eq.sequence_id).first()
        if seq:
            changed = False
            if "subject" in payload and payload["subject"] and seq.channel == "email":
                seq.subject = payload["subject"]
                changed = True
            if "body" in payload and payload["body"]:
                seq.content = payload["body"]
                changed = True
            if "scheduled_at" in payload and payload["scheduled_at"]:
                try:
                    d = _dt.fromisoformat(payload["scheduled_at"])
                    seq.scheduled_date = d.strftime("%Y-%m-%d")
                    changed = True
                except Exception:
                    pass
            if changed:
                logger.info("Synced email queue #%d changes to sequence #%d", eq.id, seq.id)
    db.commit()
    db.refresh(eq)
    return EmailQueueOut.model_validate(eq)


@router.post("/send-one/{queue_id}")
async def send_one_email(queue_id: int, db: Session = Depends(get_db)):
    """Send a single pending email immediately via SMTP."""
    from services.email_service import _send_one_sync

    eq = db.query(EmailQueue).filter(EmailQueue.id == queue_id).first()
    if not eq:
        raise HTTPException(status_code=404, detail="Email queue item not found")
    if eq.status not in ("pending",):
        raise HTTPException(status_code=400, detail=f"Cannot send email with status '{eq.status}'")

    from services.writing_rules import self_intro_opening_warning
    quality_warning = self_intro_opening_warning(eq.body, eq.subject)
    if quality_warning:
        raise HTTPException(status_code=400, detail=quality_warning)

    sent_count, remaining = check_daily_limit()
    if remaining <= 0:
        prospect = db.query(Prospect).filter(Prospect.id == eq.prospect_id).first()
        eq.scheduled_at = _next_day_send_time(prospect)
        db.commit()
        return {
            "success": True,
            "queued_for_later": True,
            "message": f"Daily email limit reached ({sent_count}/{DAILY_EMAIL_LIMIT}); kept pending for later send.",
        }

    ok, err = _send_one_sync(eq.to_email, eq.subject, eq.body, eq.sender_key or "primary", attachment_files=eq.attachment_files, owner_user_id=eq.owner_user_id)
    if ok:
        eq.status = "sent"
        eq.sent_at = datetime.utcnow()
        eq.daily_send_date = date.today().isoformat()
        # update stats
        today_str = date.today().isoformat()
        stats = db.query(DailyEmailStats).filter(DailyEmailStats.date == today_str).first()
        if not stats:
            stats = DailyEmailStats(date=today_str, sent_count=1, limit_count=DAILY_EMAIL_LIMIT)
            db.add(stats)
        else:
            stats.sent_count += 1
        db.commit()
        # Record outbound interaction so follow-up engine knows this email was sent
        try:
            from services.email_service import _record_interaction
            _record_interaction(eq.prospect_id, eq.to_email, eq.subject, eq.body)
        except Exception:
            pass
        # Auto-finish linked sequence step
        try:
            from services.email_service import _finish_sequence_step
            _finish_sequence_step(eq)
        except Exception:
            pass
        # Auto-complete: if this was a new outreach, clear new_outreach_date & set follow-up
        _auto_complete_new_outreach(eq.prospect_id, db)
        return {"success": True, "message": f"Sent to {eq.to_email}"}
    else:
        eq.status = "failed"
        eq.last_error = (err or "unknown")[:500]
        db.commit()
        raise HTTPException(status_code=500, detail=f"SMTP failed: {err}")


@router.get("/stats/today", response_model=EmailStatsOut)
async def todays_stats(db: Session = Depends(get_db)):
    """Get today's email sending statistics."""
    today_str = date.today().isoformat()
    stats = db.query(DailyEmailStats).filter(DailyEmailStats.date == today_str).first()
    if not stats:
        return EmailStatsOut(date=today_str, sent_count=0, limit_count=DAILY_EMAIL_LIMIT, remaining=DAILY_EMAIL_LIMIT)

    remaining = max(0, DAILY_EMAIL_LIMIT - stats.sent_count)
    return EmailStatsOut(
        date=stats.date,
        sent_count=stats.sent_count,
        limit_count=DAILY_EMAIL_LIMIT,
        remaining=remaining,
    )


@router.get("/stats/performance")
async def email_performance_stats(db: Session = Depends(get_db)):
    """Return email performance breakdown: sent/reply counts by profile type,
    overall reply rate, and 7-day reply window."""
    from collections import defaultdict
    from datetime import timedelta as _td

    # All sent emails joined with prospect profile
    sent_rows = db.query(EmailQueue, Prospect.profile_type).join(
        Prospect, EmailQueue.prospect_id == Prospect.id
    ).filter(EmailQueue.status == "sent").all()

    # All inbound interactions（排除退信：退信不算真实回复）
    inbound_rows = db.query(Interaction.prospect_id, Interaction.interacted_at).filter(
        Interaction.direction == "inbound",
            or_(Interaction.reply_intent.is_(None), Interaction.reply_intent != "bounce"),
            or_(Interaction.content.is_(None), ~Interaction.content.like("%[Auto-detected] Mail bounce%")),
    ).all()

    # Map prospect_id → earliest inbound date (for "replied" check)
    inbound_by_pid = {}
    for pid, dt in inbound_rows:
        if dt and hasattr(dt, 'tzinfo') and dt.tzinfo is not None:
            dt = dt.replace(tzinfo=None)
        if pid not in inbound_by_pid or (dt and inbound_by_pid[pid] is None):
            inbound_by_pid[pid] = dt
        elif dt and inbound_by_pid[pid] and dt < inbound_by_pid[pid]:
            inbound_by_pid[pid] = dt

    # Per-profile aggregation（回复率按“客户”口径：真实回复客户 / 已触达客户）
    profile_stats = defaultdict(lambda: {"sent": 0, "contacted": set(), "replied": set(), "replied_7d": set()})
    for eq, profile_type in sent_rows:
        pt = profile_type or "?"
        profile_stats[pt]["sent"] += 1
        profile_stats[pt]["contacted"].add(eq.prospect_id)
        # Check if this prospect ever replied
        if eq.prospect_id in inbound_by_pid:
            profile_stats[pt]["replied"].add(eq.prospect_id)
            # Check if reply came within 7 days of send
            in_dt = inbound_by_pid[eq.prospect_id]
            if eq.sent_at and in_dt and in_dt <= eq.sent_at + _td(days=7):
                profile_stats[pt]["replied_7d"].add(eq.prospect_id)

    total_sent = sum(v["sent"] for v in profile_stats.values())
    all_contacted = set()
    all_replied = set()
    all_replied_7d = set()
    for v in profile_stats.values():
        all_contacted |= v["contacted"]
        all_replied |= v["replied"]
        all_replied_7d |= v["replied_7d"]

    def _pct(n, d):
        return round(n / d * 100, 1) if d else 0.0

    profiles = []
    for pt, v in sorted(profile_stats.items(), key=lambda x: -x[1]["sent"]):
        profiles.append({
            "profile": pt,
            "sent": v["sent"],
            "contacted": len(v["contacted"]),
            "replied": len(v["replied"]),
            "replied_7d": len(v["replied_7d"]),
            "reply_rate": _pct(len(v["replied"]), len(v["contacted"])),
        })

    return {
        "overview": {
            "total_sent": total_sent,
            "contacted_customers": len(all_contacted),
            "total_replied": len(all_replied),
            "replied_within_7d": len(all_replied_7d),
            "reply_rate": _pct(len(all_replied), len(all_contacted)),
        },
        "profiles": profiles,
    }


@router.post("/send-ready")
async def send_ready_emails(db: Session = Depends(get_db)):
    """Process all 'pending' emails — actually send via SMTP."""
    from services.email_service import _send_one_sync

    sent = 0
    skipped = []
    failed = []
    today_str = date.today().isoformat()

    pending = (
        db.query(EmailQueue)
        .filter(EmailQueue.status == "pending")
        .order_by(EmailQueue.scheduled_at.asc())
        .limit(20)
        .all()
    )

    for eq in pending:
        from services.writing_rules import self_intro_opening_warning
        quality_warning = self_intro_opening_warning(eq.body, eq.subject)
        if quality_warning:
            skipped.append(f"{eq.to_email}: {quality_warning}")
            continue

        prospect = db.query(Prospect).filter(Prospect.id == eq.prospect_id).first()

        can_send = True
        reason = "no prospect — send anyway"
        if prospect:
            can_send, reason = is_business_hours_now(prospect)

        if not can_send:
            skipped.append(f"{eq.to_email}: {reason} (will still send — manual trigger override)")
            # Don't skip on manual trigger — send anyway

        # Actually send via SMTP
        ok, err = _send_one_sync(eq.to_email, eq.subject, eq.body, eq.sender_key or "primary", attachment_files=eq.attachment_files, owner_user_id=eq.owner_user_id)
        if ok:
            eq.status = "sent"
            eq.sent_at = datetime.utcnow()
            eq.daily_send_date = today_str

            stats = db.query(DailyEmailStats).filter(DailyEmailStats.date == today_str).first()
            if not stats:
                stats = DailyEmailStats(date=today_str, sent_count=1, limit_count=DAILY_EMAIL_LIMIT)
                db.add(stats)
            else:
                stats.sent_count += 1

            sent += 1
            logger.info("Sent email to %s: %s", eq.to_email, eq.subject)
            # Record outbound interaction
            try:
                from services.email_service import _record_interaction
                _record_interaction(eq.prospect_id, eq.to_email, eq.subject, eq.body)
            except Exception:
                pass
            # Auto-complete: if new outreach, clear new_outreach_date & set follow-up
            _auto_complete_new_outreach(eq.prospect_id, db)
        else:
            eq.status = "failed"
            eq.last_error = err[:500] if err else "unknown"
            failed.append(f"{eq.to_email}: {err}")
            logger.error("Failed to send to %s: %s", eq.to_email, err)

    db.commit()
    return {
        "sent": sent,
        "skipped": len(skipped),
        "failed": len(failed),
        "skipped_reasons": skipped[:10],
        "failed_reasons": failed[:10],
        "message": f"Sent {sent}, skipped {len(skipped)} (manual trigger: all pending sent regardless of business hours), failed {len(failed)}"
    }


@router.get("/hours/{prospect_id}")
async def check_hours(prospect_id: int, db: Session = Depends(get_db)):
    """Check if it's currently business hours for a prospect."""
    prospect = db.query(Prospect).filter(Prospect.id == prospect_id).first()
    if not prospect:
        raise HTTPException(status_code=404, detail="Prospect not found")

    can_send, reason = is_business_hours_now(prospect)
    next_time = get_next_send_time(prospect)
    return {
        "can_send_now": can_send,
        "reason": reason,
        "timezone": prospect.timezone,
        "country": prospect.country,
        "next_send_time": str(next_time) if next_time else "immediate",
    }


@router.post("/fetch-replies")
async def trigger_fetch_replies():
    """Manually trigger IMAP fetch for new replies."""
    from services.email_service import fetch_new_replies

    results = await fetch_new_replies()
    # Write auto-fetch status so the frontend can skip redundant fetches
    try:
        with open(AUTO_FETCH_STATUS_FILE, "w") as f:
            json.dump({"last_run": datetime.utcnow().isoformat()}, f)
    except Exception:
        pass
    return {"success": True, "new_replies": len(results), "items": results}
# ── Auto-fetch status endpoint ──

AUTO_FETCH_STATUS_FILE = os.path.join(str(APP_DIR), ".auto_fetch_status.json")

@router.get("/auto-fetch-status")
async def auto_fetch_status():
    """Return whether a fetch-replies was recently run, so the frontend can skip duplicate fetches."""
    try:
        with open(AUTO_FETCH_STATUS_FILE, "r") as f:
            data = json.load(f)
        last_run = data.get("last_run", "")
        if last_run:
            dt = datetime.fromisoformat(last_run)
            elapsed = (datetime.utcnow() - dt).total_seconds()
            return {"recently_run": elapsed < 240, "last_run": last_run, "elapsed_seconds": round(elapsed, 1)}
    except Exception:
        pass
    return {"recently_run": False, "last_run": None, "elapsed_seconds": None}


@router.post("/diagnose-bounces")
async def diagnose_bounces():
    """Direct Zoho IMAP scan — list ALL bounce-like emails in ALL folders.
    Runs in executor thread to not block async event loop."""
    import imaplib
    import email
    from email.header import decode_header
    import asyncio

    def _scan():
        _MONTHS_EN = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"]
        since_dt = datetime.utcnow() - timedelta(days=7)
        since = f"{since_dt.day:02d}-{_MONTHS_EN[since_dt.month - 1]}-{since_dt.year}"

        BOUNCE_KWS = [
            "undeliverable", "undelivered", "mail delivery failed", "delivery failure",
            "returned mail", "postmaster", "mailer-daemon", "delivery status",
            "failed delivery", "could not be delivered", "bounced", "not delivered",
            "address not found", "does not exist", "550 5.1", "user unknown",
        ]

        folders_checked = []
        bounces_found = []
        total = 0

        mail = imaplib.IMAP4_SSL("imap.zoho.com", 993, timeout=30)
        mail.login("{{USER_EMAIL}}", "2fdjyeKbngVh")

        status, flist = mail.list()
        folder_names = []
        for f in flist:
            m = re.search(r'"/"\s+"?(.+?)"?$', f.decode())
            if m: folder_names.append(m.group(1))

        for folder in folder_names:
            try:
                mail.select(f'"{folder}"')
            except Exception:
                continue
            status, data = mail.search(None, f'(SINCE "{since}")')
            if status != "OK" or not data[0]:
                continue
            nums = data[0].split()
            folders_checked.append({"name": folder, "count": len(nums)})
            for num in nums[-200:]:
                total += 1
                try:
                    status2, msg_data = mail.fetch(num, "(RFC822)")
                    if status2 != "OK": continue
                    raw = msg_data[0][1] if isinstance(msg_data[0], tuple) else None
                    if not raw: continue
                    msg = email.message_from_bytes(raw)
                    from_addr = msg.get("From", "")
                    subject = msg.get("Subject", "")
                    decoded_subj = ""
                    for part, enc in decode_header(subject):
                        if isinstance(part, bytes):
                            decoded_subj += decode_mail_bytes(part, enc)
                        else:
                            decoded_subj += str(part)
                    m = re.search(r'<(.+?)>', from_addr)
                    sender = m.group(1).strip().lower() if m else from_addr.strip().lower()
                    body = ""
                    if msg.is_multipart():
                        for part in msg.walk():
                            if part.get_content_type() == "text/plain":
                                try: body = decode_mail_bytes(part.get_payload(decode=True), part.get_content_charset())
                                except: pass
                                break
                    else:
                        try: body = decode_mail_bytes(msg.get_payload(decode=True), msg.get_content_charset())
                        except: pass
                    combined = f"{decoded_subj.lower()} {sender.lower()}"
                    is_bounce = any(kw in combined or kw in body.lower() for kw in BOUNCE_KWS)
                    if is_bounce:
                        bounces_found.append({
                            "folder": folder,
                            "subject": decoded_subj[:200],
                            "from": sender[:120],
                            "body_preview": body[:600],
                        })
                except Exception:
                    continue
        mail.logout()

        return {
            "total_checked": total,
            "bounce_count": len(bounces_found),
            "folders": folders_checked,
            "bounces": bounces_found,
        }

    try:
        loop = asyncio.get_event_loop()
        result = await loop.run_in_executor(None, _scan)
        return {"success": True, **result}
    except Exception as e:
        logger.exception("diagnose-bounces failed")
        return {"success": False, "error": str(e)}


@router.get("/senders")
async def list_senders(db: Session = Depends(get_db)):
    """List available email sender accounts (含绑定的成员)."""
    from services.email_service import get_available_senders
    return [{"key": s["key"], "label": s["label"], "email": s["user"],
             "bound_user_id": s.get("bound_user_id")} for s in get_available_senders(db)]


@router.post("/sender-bindings")
async def save_sender_bindings(payload: dict, db: Session = Depends(get_db),
                               user: User = Depends(get_current_user)):
    """主账号给每个邮箱绑定业务员：{"bindings": {"primary": 2, "secondary": "", "third": 3}}"""
    if user.role not in ("owner", "admin"):
        raise HTTPException(status_code=403, detail="Only the owner/admin can configure mailbox bindings")
    bindings = payload.get("bindings") or {}
    for key, uid in bindings.items():
        acc = db.query(EmailAccount).filter(EmailAccount.key == key).first()
        if not acc:
            continue
        acc.bound_user_id = int(uid) if str(uid or "").strip() else None
    db.commit()
    return {"ok": True}


@router.post("/accounts")
async def create_email_account(payload: dict, db: Session = Depends(get_db),
                               user: User = Depends(get_current_user)):
    """客户自定义添加邮箱账号（不限数量）。"""
    if user.role not in ("owner", "admin"):
        raise HTTPException(status_code=403, detail="Only the owner/admin can add email accounts")
    acc = EmailAccount(
        name=str(payload.get("name") or "").strip() or "Work mailbox",
        smtp_host=str(payload.get("smtp_host") or "").strip(),
        smtp_port=int(payload.get("smtp_port") or 465),
        smtp_user=str(payload.get("smtp_user") or "").strip(),
        smtp_pass=str(payload.get("smtp_pass") or "").strip(),
        smtp_name=str(payload.get("smtp_name") or "").strip(),
        imap_host=str(payload.get("imap_host") or "").strip(),
        imap_port=int(payload.get("imap_port") or 993),
        imap_user=str(payload.get("imap_user") or "").strip(),
        imap_pass=str(payload.get("imap_pass") or "").strip(),
        bound_user_id=int(payload["bound_user_id"]) if payload.get("bound_user_id") else None,
        is_active=1,
    )
    db.add(acc)
    db.flush()
    if not acc.key:
        acc.key = "acc_%d" % acc.id
    db.commit()
    db.refresh(acc)
    return {"ok": True, "id": acc.id, "key": acc.key}


@router.get("/accounts")
async def list_email_accounts(db: Session = Depends(get_db),
                              user: User = Depends(get_current_user)):
    """邮箱账号完整列表（含配置，密码脱敏）。只有主账号/管理员可看。"""
    if user.role not in ("owner", "admin"):
        raise HTTPException(status_code=403, detail="Only the owner/admin can view mailbox configuration")
    from services.email_service import _seed_email_accounts
    _seed_email_accounts(db)
    rows = db.query(EmailAccount).order_by(
        EmailAccount.sort_order.asc(), EmailAccount.id.asc()).all()
    return [{
        "id": a.id, "key": a.key, "name": a.name,
        "smtp_host": a.smtp_host, "smtp_port": a.smtp_port, "smtp_user": a.smtp_user,
        "smtp_pass": "****" if a.smtp_pass else "",
        "smtp_name": a.smtp_name,
        "imap_host": a.imap_host, "imap_port": a.imap_port, "imap_user": a.imap_user,
        "imap_pass": "****" if a.imap_pass else "",
        "bound_user_id": a.bound_user_id, "is_active": a.is_active,
    } for a in rows]


@router.post("/accounts/{account_id}/test")
async def test_email_account(account_id: int, db: Session = Depends(get_db),
                             user: User = Depends(get_current_user)):
    """测试某个邮箱账号的 SMTP/IMAP 连接。"""
    if user.role not in ("owner", "admin"):
        raise HTTPException(status_code=403, detail="Only the owner/admin can test email accounts")
    acc = db.query(EmailAccount).filter(EmailAccount.id == account_id).first()
    if not acc:
        raise HTTPException(status_code=404, detail="Email account not found")
    from services import setup_service
    results = {}
    if acc.smtp_host and acc.smtp_user:
        try:
            results["smtp"] = await setup_service.test_smtp({
                "smtp_host": acc.smtp_host, "smtp_port": str(acc.smtp_port or 465),
                "smtp_user": acc.smtp_user, "smtp_pass": acc.smtp_pass,
            })
        except Exception as e:
            results["smtp"] = {"ok": False, "error": str(e)[:120]}
    if acc.imap_host and acc.imap_user:
        try:
            results["imap"] = await setup_service.test_imap({
                "imap_host": acc.imap_host, "imap_port": str(acc.imap_port or 993),
                "imap_user": acc.imap_user, "imap_pass": acc.imap_pass,
            })
        except Exception as e:
            results["imap"] = {"ok": False, "error": str(e)[:120]}
    ok = bool(results) and all(r.get("ok") for r in results.values())
    return {"ok": ok, "results": results}


@router.put("/accounts/{account_id}")
async def update_email_account(account_id: int, payload: dict, db: Session = Depends(get_db),
                               user: User = Depends(get_current_user)):
    if user.role not in ("owner", "admin"):
        raise HTTPException(status_code=403, detail="Only the owner/admin can modify email accounts")
    acc = db.query(EmailAccount).filter(EmailAccount.id == account_id).first()
    if not acc:
        raise HTTPException(status_code=404, detail="Email account not found")
    for f in ("name", "smtp_host", "smtp_user", "smtp_pass", "smtp_name",
              "imap_host", "imap_user", "imap_pass"):
        if f in payload:
            setattr(acc, f, str(payload[f] or "").strip())
    if "smtp_port" in payload and payload["smtp_port"]:
        acc.smtp_port = int(payload["smtp_port"])
    if "imap_port" in payload and payload["imap_port"]:
        acc.imap_port = int(payload["imap_port"])
    if "bound_user_id" in payload:
        acc.bound_user_id = int(payload["bound_user_id"]) if payload["bound_user_id"] else None
    if "is_active" in payload:
        acc.is_active = 1 if payload["is_active"] else 0
    db.commit()
    return {"ok": True}


@router.delete("/accounts/{account_id}")
async def delete_email_account(account_id: int, db: Session = Depends(get_db),
                               user: User = Depends(get_current_user)):
    if user.role not in ("owner", "admin"):
        raise HTTPException(status_code=403, detail="Only the owner/admin can delete email accounts")
    acc = db.query(EmailAccount).filter(EmailAccount.id == account_id).first()
    if not acc:
        raise HTTPException(status_code=404, detail="Email account not found")
    db.delete(acc)
    db.commit()
    return {"ok": True}


@router.post("/backfill-bounces")
async def backfill_bounces(db: Session = Depends(get_db)):
    """一次性回溯：直接从 Zoho IMAP 扫描前30天的退信，
    导入到 Interaction + 标记客户 email_status=bounced。
    后续正常 IMAP 抓取已修复，新退信不会再漏。"""
    import imaplib
    import email as em
    from email.header import decode_header
    import re as _re
    import asyncio

    def _imap_scan():
        _MONTHS_EN = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"]
        since_dt = datetime.utcnow() - timedelta(days=30)
        since = f"{since_dt.day:02d}-{_MONTHS_EN[since_dt.month - 1]}-{since_dt.year}"

        BOUNCE_SENDERS = ["mailer-daemon", "postmaster"]

        mail = imaplib.IMAP4_SSL("imap.zoho.com", 993, timeout=30)
        mail.login("{{USER_EMAIL}}", "2fdjyeKbngVh")

        status, flist = mail.list()
        folder_names = []
        for f in flist:
            m = _re.search(r'"/"\s+"?(.+?)"?$', f.decode())
            if m:
                folder_names.append(m.group(1))

        raw_bounces = []
        seen_msgids = set()

        for folder in folder_names:
            try:
                mail.select(f'"{folder}"')
            except Exception:
                continue
            status, data = mail.search(None, f'(SINCE "{since}")')
            if status != "OK" or not data[0]:
                continue
            nums = data[0].split()
            for num in nums:
                try:
                    status2, msg_data = mail.fetch(num, "(RFC822)")
                    if status2 != "OK" or not msg_data[0]:
                        continue
                    raw = msg_data[0][1] if isinstance(msg_data[0], tuple) else None
                    if not raw:
                        continue
                    msg = em.message_from_bytes(raw)
                    msg_id = msg.get("Message-ID", "").strip()
                    if not msg_id or msg_id in seen_msgids:
                        continue
                    seen_msgids.add(msg_id)

                    from_addr = msg.get("From", "")
                    m2 = _re.search(r'<(.+?)>', from_addr)
                    sender = m2.group(1).strip().lower() if m2 else from_addr.strip().lower()

                    if not any(bs in sender for bs in BOUNCE_SENDERS):
                        continue

                    subject = msg.get("Subject", "")
                    decoded_subj = ""
                    for part, enc in decode_header(subject):
                        if isinstance(part, bytes):
                            decoded_subj += decode_mail_bytes(part, enc)
                        else:
                            decoded_subj += str(part)
                    decoded_subj = decoded_subj.strip()

                    body = ""
                    if msg.is_multipart():
                        for part in msg.walk():
                            if part.get_content_type() == "text/plain":
                                try:
                                    body = decode_mail_bytes(part.get_payload(decode=True), part.get_content_charset())
                                except Exception:
                                    pass
                                break
                    else:
                        try:
                            body = decode_mail_bytes(msg.get_payload(decode=True), msg.get_content_charset())
                        except Exception:
                            pass

                    raw_bounces.append({
                        "msg_id": msg_id,
                        "folder": folder,
                        "subject": decoded_subj,
                        "sender": sender,
                        "body": body,
                        "date": msg.get("Date", ""),
                    })
                except Exception:
                    continue
        mail.logout()
        return raw_bounces

    try:
        loop = asyncio.get_event_loop()
        raw_bounces = await loop.run_in_executor(None, _imap_scan)
    except Exception as e:
        logger.exception("backfill-bounces IMAP scan failed")
        return {"success": False, "error": str(e)}

    # ── Import into DB ──
    results = []
    imported_count = 0

    for rb in raw_bounces:
        msg_id = rb["msg_id"]

        # Dedup: skip if already in Interaction table
        existing = db.query(Interaction).filter(
            Interaction.email_message_id == msg_id
        ).first()
        if existing:
            # If existing but not marked as bounce, fix it
            if existing.reply_intent != "bounce":
                existing.reply_intent = "bounce"
                existing.subject = f"Bounce: {rb['subject'][:200]}"
                db.add(existing)
                imported_count += 1
            continue

        # Extract bounced email from body
        body_text = rb["body"] + " " + rb["subject"]
        bounced_email = None
        for pattern in [
            r'([\w\.\-_]+@[\w\.\-_]+).*?(?:ERROR CODE|does not exist|user unknown|not found|couldn\'t be delivered|wasn\'t found)',
            r'([\w\.\-_]+@[\w\.\-_]+).*?(?:550|553|556|512)',
            r"Failed to deliver to\s+'?([\w\.\-_]+@[\w\.\-_]+)",
            r'Your message to\s+([\w\.\-_]+@[\w\.\-_]+)',
            r'original message.*?<([\w\.\-_]+@[\w\.\-_]+)>',
        ]:
            m = _re.search(pattern, body_text, _re.IGNORECASE)
            if m:
                bounced_email = m.group(1).lower()
                break

        bp = None
        if bounced_email:
            bp = db.query(Prospect).filter(
                Prospect.email == bounced_email,
                Prospect.is_deleted == 0,
            ).first()
            if not bp:
                from services.email_service import _match_dm_email
                bp = _match_dm_email(db, bounced_email)

        if bp:
            bp.email_status = "bounced"
            bp.last_edited_at = datetime.utcnow()
            db.add(Interaction(
                prospect_id=bp.id,
                direction="inbound",
                channel="email",
                content=f"[Backfill bounce] {rb['body'][:3000]}",
                subject=f"Bounce: {rb['subject'][:200]}",
                email_message_id=msg_id,
                email_from=rb["sender"],
                email_received_at=datetime.utcnow(),
                reply_intent="bounce",
            ))
            imported_count += 1
            results.append({
                "company": bp.company,
                "bounced_email": bounced_email,
                "subject": rb["subject"][:100],
            })
        else:
            results.append({
                "company": None,
                "bounced_email": bounced_email,
                "subject": rb["subject"][:100],
                "note": "No matching client found",
            })

    db.commit()
    return {
        "success": True,
        "imap_total": len(raw_bounces),
        "imported": imported_count,
        "matched": sum(1 for r in results if r.get("company")),
        "results": results,
    }


# ── Attachment upload endpoint ──

ATTACHMENTS_DIR = os.path.join(str(APP_DIR), "attachments")

@router.post("/upload-attachments")
async def upload_attachments(files: list[UploadFile] = File(...)):
    """Upload one or more files to attach to an outgoing email draft.
    Returns a JSON array suitable for the attachment_files column."""
    os.makedirs(ATTACHMENTS_DIR, exist_ok=True)
    uploaded = []
    for f in files:
        safe_name = f"{uuid.uuid4().hex[:8]}_{f.filename}"
        dest = os.path.join(ATTACHMENTS_DIR, safe_name)
        content = await f.read()
        with open(dest, "wb") as out:
            out.write(content)
        uploaded.append({
            "filename": f.filename,
            "path": f"attachments/{safe_name}",
            "size": len(content),
        })
        logger.info("Uploaded attachment: %s -> %s (%d bytes)", f.filename, safe_name, len(content))
    return {"success": True, "files": uploaded}
