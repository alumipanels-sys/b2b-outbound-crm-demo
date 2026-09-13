"""Sequences router — multi-channel follow-up sequence management."""

import logging
import traceback
from datetime import datetime, date, timedelta

from fastapi import APIRouter, Depends, HTTPException, Body, Request
from sqlalchemy.orm import Session

from database import get_db
from models import Sequence, Prospect, Interaction
from schemas import SequenceOut, SequenceCreate, SequenceUpdate
from services.company_sync import sync_company_main

logger = logging.getLogger(__name__)
router = APIRouter()


# ── 动作驱动的下次跟踪引擎 ──────────────────────────────
# 不再机械地按 step_number 推天数，而是根据"你做了什么 + 结果如何"来推。
#
# 动作定义：
#   email_sent     — 邮件已发出
#   email_bounced  — 邮件退信
#   linkedin_invite — LinkedIn 加好友请求已发送（等通过）
#   linkedin_connected — LinkedIn 好友已通过
#   linkedin_msg   — LinkedIn 发了消息
#   whatsapp_sent  — WhatsApp 已发
#   whatsapp_read  — WhatsApp 已读未回
#   phone_called   — 电话已打（未通）
#   phone_talked   — 电话已通话
#   replied_positive — 客户回复积极
#   replied_neutral  — 客户回复中性/官腔
#   replied_negative — 客户回复拒绝
#   no_reply       — 无回复（超时）
#
# 输出：(next_action_label, next_days)
#   next_action_label 是中文自然语言，比如 "LinkedIn 已加好友 → 3天后发破冰消息"
#   next_days 是建议间隔

ACTION_RHYTHM = {
    # (action, channel) → (label_suffix, days)
    ("email_sent",     "email"):    ("Email sent → send product materials", 5),
    ("email_bounced",  "email"):    ("Email bounced → switch channel", 0),
    ("linkedin_invite","linkedin"): ("LinkedIn request pending approval", 3),
    ("linkedin_connected","linkedin"): ("LinkedIn connected → send icebreaker", 1),
    ("linkedin_msg",   "linkedin"): ("LinkedIn message sent → wait for reply", 5),
    ("whatsapp_sent",  "whatsapp"): ("WhatsApp sent → wait for reply", 3),
    ("whatsapp_read",  "whatsapp"): ("WhatsApp read, no reply → follow up", 5),
    ("phone_called",   "phone"):    ("Call unanswered → switch to email/WhatsApp", 1),
    ("phone_talked",   "phone"):    ("Call completed → confirm by email", 1),
    ("replied_positive", ""):       ("Positive reply → send quote/materials", 1),
    ("replied_neutral",  ""):       ("Formal/non-committal reply → send sample proof", 3),
    ("replied_negative", ""):       ("Client declined → retry with a new angle", 14),
    ("no_reply",         ""):       ("No reply → switch channel or angle", 7),
}

def _action_label(action: str, channel: str, days: int) -> str:
    """Generate a natural-language reminder label."""
    entry = ACTION_RHYTHM.get((action, channel)) or ACTION_RHYTHM.get((action, ""))
    if entry:
        suffix = entry[0]
        return f"{suffix} · in {days} days"
    return f"Next follow-up · in {days} days"

def _action_interval(action: str, channel: str, country: str = "") -> int:
    """根据动作返回下次跟踪的建议间隔天数."""
    entry = ACTION_RHYTHM.get((action, channel)) or ACTION_RHYTHM.get((action, ""))
    days = entry[1] if entry else 7

    # 中东客户多等2天
    if country and country.upper() in ("AE", "SA", "TR", "QA", "KW", "OM", "BH", "EG", "IR", "IQ", "JO", "LB", "SY", "YE"):
        days += 2
    return days


# Backward-compatible aliases for any existing importer
def _stage_label(step_number: int) -> str:
    return f"Stage {step_number}"

def _stage_interval(step_number: int, channel: str, country: str = "") -> int:
    return _action_interval(f"{channel}_sent", channel, country)


# ── API Endpoints ────────────────────────────────────


@router.get("/gaps")
async def next_step_gaps(db: Session = Depends(get_db)):
    """Scan all active prospects and find channels where:
    - The last step is status='done'
    - No next step exists (no higher step_number)
    - The done step's scheduled_date is in the past
    Returns list of {prospect_id, company, channel, last_step_num, last_done_date}."""
    today = date.today()
    all_p = (
        db.query(Prospect)
        .filter(Prospect.is_deleted == 0, ~Prospect.sales_stage.in_(["won", "lost"]))
        .all()
    )
    # Only consider prospects that have at least one sequence step (exclude pure new)
    seq_ids = set(
        row[0] for row in db.query(Sequence.prospect_id).filter(Sequence.prospect_id.in_([p.id for p in all_p])).distinct().all()
    )
    active = [p for p in all_p if p.id in seq_ids]
    gaps = []
    for p in active:
        seqs = (
            db.query(Sequence)
            .filter(Sequence.prospect_id == p.id)
            .order_by(Sequence.step_number.asc())
            .all()
        )
        by_channel = {}
        for s in seqs:
            by_channel.setdefault(s.channel, []).append(s)

        for ch, ch_seqs in by_channel.items():
            ch_seqs.sort(key=lambda x: x.step_number)
            last_step = ch_seqs[-1]
            if last_step.status != "done":
                continue
            has_next = any(
                s.step_number > last_step.step_number for s in ch_seqs
            )
            if has_next:
                continue
            try:
                if last_step.scheduled_date and last_step.scheduled_date.strip():
                    done_date = date.fromisoformat(last_step.scheduled_date[:10])
                else:
                    done_date = date(2000, 1, 1)  # treat empty as ancient — it's missing
            except (ValueError, TypeError):
                done_date = date(2000, 1, 1)
            if done_date >= today:
                continue

            gaps.append({
                "prospect_id": p.id,
                "company": p.company,
                "contact": p.contact,
                "country": p.country,
                "channel": ch,
                "last_step_num": last_step.step_number,
                "last_done_date": (last_step.scheduled_date or "")[:10],
                "last_content_preview": (last_step.content or "")[:100],
            })

    gaps.sort(key=lambda g: g["last_done_date"])
    return gaps


@router.get("/today")
async def todays_sequences(db: Session = Depends(get_db)):
    """Get emails actually queued to send TODAY (from email_queue, status=pending),
    with prospect info + send time. This reflects the real outbox instead of
    counting dev-plan steps that may or may not have been queued yet."""
    today = datetime.now().strftime("%Y-%m-%d")
    from models import EmailQueue
    items = (
        db.query(EmailQueue)
        .filter(
            EmailQueue.status == "pending",
            EmailQueue.scheduled_at.isnot(None),
        )
        .order_by(EmailQueue.scheduled_at.asc())
        .all()
    )
    result = []
    for eq in items:
        sched = eq.scheduled_at
        # 只显示"今天"要发的（本地日期比较）
        if isinstance(sched, datetime):
            sched_date = sched.strftime("%Y-%m-%d")
        elif isinstance(sched, str):
            sched_date = sched[:10]
        else:
            sched_date = ""
        if sched_date != today:
            continue
        prospect = db.query(Prospect).filter(Prospect.id == eq.prospect_id).first()
        if not prospect or prospect.is_deleted:
            continue  # 客户已删除/不存在，不再展示其旧跟进步骤
        step_number = 1
        if eq.sequence_id:
            seq = db.query(Sequence).filter(Sequence.id == eq.sequence_id).first()
            if seq:
                step_number = seq.step_number or 1
        result.append({
            "id": eq.id,
            "prospect_id": eq.prospect_id,
            "company": prospect.company,
            "contact": prospect.contact,
            "email": prospect.email or prospect.dm_email,
            "country": prospect.country,
            "timezone": prospect.timezone,
            "channel": "email",
            "step_number": step_number,
            "subject": eq.subject or "",
            "content": eq.body or "",
            "scheduled_at": sched.isoformat() if hasattr(sched, "isoformat") else str(sched),
            "is_overdue": False,
        })
    return result


@router.get("/{prospect_id}", response_model=list[SequenceOut])
async def get_sequences(prospect_id: int, db: Session = Depends(get_db)):
    """Get all sequence steps for a prospect, ordered by step_number."""
    prospect = db.query(Prospect).filter(
        Prospect.id == prospect_id, Prospect.is_deleted == 0
    ).first()
    if not prospect:
        raise HTTPException(status_code=404, detail="Prospect not found")

    seqs = (
        db.query(Sequence)
        .filter(Sequence.prospect_id == prospect_id)
        .order_by(Sequence.step_number.asc())
        .all()
    )
    return [SequenceOut.model_validate(s) for s in seqs]


@router.post("/{prospect_id}", response_model=SequenceOut)
async def create_sequence_step(
    prospect_id: int,
    data: SequenceCreate,
    db: Session = Depends(get_db),
):
    """Add a new follow-up sequence step."""
    prospect = db.query(Prospect).filter(
        Prospect.id == prospect_id, Prospect.is_deleted == 0
    ).first()
    if not prospect:
        raise HTTPException(status_code=404, detail="Prospect not found")

    seq = Sequence(
        prospect_id=prospect_id,
        step_number=data.step_number,
        channel=data.channel,
        scheduled_date=data.scheduled_date,
        scheduled_time=data.scheduled_time,
        content=data.content,
        subject=data.subject,
        tone=data.tone,
        to_email=data.to_email,
        is_company_plan=data.is_company_plan or 0,
    )
    db.add(seq)
    db.commit()
    db.refresh(seq)
    return SequenceOut.model_validate(seq)


@router.put("/{seq_id}", response_model=SequenceOut)
async def update_sequence_step(
    seq_id: int,
    data: SequenceUpdate,
    db: Session = Depends(get_db),
):
    """Update a sequence step. Also auto-calculates the next follow-up date
    for the prospect based on the step's stage, channel, and country."""
    seq = db.query(Sequence).filter(Sequence.id == seq_id).first()
    if not seq:
        raise HTTPException(status_code=404, detail="Sequence step not found")

    for key, val in data.model_dump(exclude_unset=True).items():
        setattr(seq, key, val)
    seq.updated_at = datetime.utcnow()

    db.commit()
    db.refresh(seq)
    return SequenceOut.model_validate(seq)


@router.post("/{seq_id}/execute")
async def execute_sequence_step(
    seq_id: int,
    db: Session = Depends(get_db),
    request: Request = None,
):
    """Mark a sequence step as done and auto-create an outbound interaction record.
    Also updates linkedin_status when LinkedIn sequence steps execute:
    - Step 1 (connection request) → sets linkedin_status to 'pending'
    Returns {id, prospect_id, status, interaction_id}."""
    import json

    seq = db.query(Sequence).filter(Sequence.id == seq_id).first()
    if not seq:
        raise HTTPException(status_code=404, detail="Sequence step not found")

    # Parse body — use raw Request to avoid Body() silent failure
    payload = {}
    if request:
        try:
            raw = await request.body()
            if raw:
                payload = json.loads(raw.decode())
        except Exception:
            pass

    outcome_val = payload.get("status") or payload.get("outcome") or "done"
    outcome_note_val = payload.get("outcome_note", "") or ""

    seq.status = "done"
    seq.outcome = outcome_val
    seq.outcome_note = outcome_note_val
    seq.executed_at = datetime.utcnow()
    seq.updated_at = datetime.utcnow()

    # Auto-create an outbound interaction record so the timeline has context
    gen_meta = None
    try:
        from services.gemini_service import get_active_methodology_ids
        mids = get_active_methodology_ids()
        if mids:
            gen_meta = json.dumps(mids)
    except Exception:
        pass

    logger.info(f"execute_sequence_step seq_id={seq_id} prospect_id={seq.prospect_id} channel={seq.channel} step={seq.step_number}")

    body = {"outcome": outcome_val, "outcome_note": outcome_note_val}
    logger.info(f"execute_sequence_step seq_id={seq_id} ch={seq.channel} step={seq.step_number} pid={seq.prospect_id} body={body}")

    intx = Interaction(
        prospect_id=seq.prospect_id,
        channel=seq.channel,
        direction="outbound",
        subject=seq.subject or "",
        content=seq.content or "",
        interacted_at=datetime.utcnow(),
        generation_meta=gen_meta,
    )
    db.add(intx)

    # LinkedIn sequence: step 1 = connection request → mark linkedin_status as pending
    prospect = db.query(Prospect).filter(Prospect.id == seq.prospect_id).first()
    if prospect:
        if not prospect.first_touch_channel:
            prospect.first_touch_channel = seq.channel
        if not prospect.sales_stage or prospect.sales_stage == "new":
            prospect.sales_stage = "touched"
        if seq.channel == "linkedin":
            # always set linkedin_status to pending when executing a LinkedIn step
            if prospect.linkedin_status and prospect.linkedin_status not in ('not_connected', 'pending'):
                pass  # don't step backward from messaged/replied
            else:
                prospect.linkedin_status = "pending"
            # only change sales_stage if currently new/touched
            prospect.sales_stage = "connected"

        # ── Action-driven next follow-up ─────────────────
        # Figure out what actually happened, then schedule accordingly.
        # LinkedIn step 1 = connection request sent (may be step_number > 1 if
        # this is the first LinkedIn step after email failures).
        action = f"{seq.channel}_sent"
        if seq.channel == "linkedin":
            # 默认按“破冰消息已发”处理；只有明确是加好友请求才按邀请节奏
            prev_linkedin = (
                db.query(Sequence)
                .filter(
                    Sequence.prospect_id == seq.prospect_id,
                    Sequence.channel == "linkedin",
                    Sequence.status == "done",
                    Sequence.id != seq.id,
                )
                .first()
            )
            linkedin_kind = str(payload.get("linkedin_kind") or payload.get("outcome_note") or "").lower()
            if "invite" in linkedin_kind or "connect" in linkedin_kind:
                action = "linkedin_invite"
            elif prev_linkedin:
                action = "linkedin_msg"
            else:
                action = "linkedin_msg"  # 默认：发的是破冰消息/InMail
        elif seq.channel == "email":
            action = "email_sent"

        logger.info(f"  → action resolved: {action}, prospect #{prospect.id} next_follow_date before: {prospect.next_follow_date}")
        try:
            days = _action_interval(action, seq.channel, prospect.country or "")
        except Exception as e2:
            logger.error(f"Action engine failed for #{prospect.id} action={action}: {traceback.format_exc()}")
            days = 3  # safe fallback
        today = date.today()
        next_date = today + timedelta(days=days)
        label = _action_label(action, seq.channel, days)
        prospect.next_follow_date = next_date.isoformat()
        prospect.reminder_note = f"[Auto] {label}"
        prospect.reminder_updated_at = datetime.utcnow()
        prospect.updated_at = datetime.utcnow()  # force touch for recent_modified counter
        prospect.last_edited_at = datetime.utcnow()
        sync_company_main(db, prospect)
        logger.info(f"Auto next_follow for #{prospect.id} ({prospect.company}): action={action} ch={seq.channel} → {next_date.isoformat()} ({days}d) [{label}]")
        try:
            logger.info(f"  ... prospect status before commit: status={prospect.status}, next_follow_date={prospect.next_follow_date}, reminder_note={prospect.reminder_note}")
        except Exception:
            pass

        db.add(prospect)

    else:
        # edge case: prospect not found, but still commit sequence/ interaction
        logger.warning(f"execute_sequence_step: prospect {seq.prospect_id} not found for seq {seq_id}")

    try:
        db.commit()
    except Exception as e3:
        logger.error(f"commit failed: {traceback.format_exc()}")
        raise
    # Log commit result
    try:
        p2 = db.query(Prospect).filter(Prospect.id == seq.prospect_id).first()
        if p2:
            logger.info(f"  ... commit verified: prospect #{p2.id} next_follow_date={p2.next_follow_date} reminder={p2.reminder_note}")
    except Exception:
        pass
    db.refresh(intx)
    db.refresh(seq)

    # 完成后自动给下一个待执行步骤排日期（未发送前不预排）
    try:
        q = db.query(Sequence).filter(
            Sequence.prospect_id == seq.prospect_id,
            Sequence.status == "pending",
            Sequence.id != seq.id,
        )
        if not seq.is_company_plan:
            q = q.filter(Sequence.channel == seq.channel)
        next_step = q.order_by(Sequence.step_number.asc()).first()
        if next_step:
            nd = date.today() + timedelta(days=3)
            while nd.weekday() >= 5:
                nd += timedelta(days=1)
            next_step.scheduled_date = nd.isoformat()
            db.commit()
            logger.info("Auto-scheduled next step #%d → %s", next_step.id, next_step.scheduled_date)
    except Exception:
        pass

    return {
        "id": seq.id,
        "prospect_id": seq.prospect_id,
        "status": "done",
        "interaction_id": intx.id,
    }


@router.post("/{seq_id}/skip", response_model=SequenceOut)
async def skip_sequence_step(
    seq_id: int,
    reason: str = "",
    db: Session = Depends(get_db),
):
    """Skip a sequence step."""
    seq = db.query(Sequence).filter(Sequence.id == seq_id).first()
    if not seq:
        raise HTTPException(status_code=404, detail="Sequence step not found")

    seq.status = "skipped"
    seq.outcome_note = reason or "Skipped"
    seq.updated_at = datetime.utcnow()
    db.commit()
    db.refresh(seq)
    return SequenceOut.model_validate(seq)


@router.post("/{seq_id}/delete")
async def delete_sequence_step(
    seq_id: int,
    db: Session = Depends(get_db),
):
    """Permanently delete a sequence step and any linked email queue items."""
    from models import EmailQueue
    seq = db.query(Sequence).filter(Sequence.id == seq_id).first()
    if not seq:
        raise HTTPException(status_code=404, detail="Sequence step not found")

    # 删除关联的邮件队列项（草稿/待发/已取消直接删；已发送保留为历史）
    linked_emails = db.query(EmailQueue).filter(EmailQueue.sequence_id == seq_id).all()
    for eq in linked_emails:
        if eq.status in ("draft", "cancelled", "pending"):
            db.delete(eq)

    db.delete(seq)
    db.commit()
    logger.info("Deleted sequence step #%d (prospect #%d), cleaned up %d linked emails", seq_id, seq.prospect_id, len(linked_emails))
    return {"success": True, "deleted_id": seq_id, "linked_emails_cleaned": len(linked_emails), "message": "Sequence step permanently deleted"}


@router.post("/cleanup-extra-steps")
async def cleanup_extra_steps(db: Session = Depends(get_db)):
    """Remove all step 2+ that have status='pending' (leftover from old 3-step generation).
    Keeps only step 1 per channel, plus any steps with status='done'/'skipped'.
    Returns {deleted: count}."""
    extra = (
        db.query(Sequence)
        .filter(
            Sequence.step_number > 1,
            Sequence.status == "pending",
        )
        .all()
    )
    deleted = 0
    for s in extra:
        db.delete(s)
        deleted += 1
    db.commit()
    logger.info("Cleaned up %d extra pending steps (keeping step 1 + done/skipped)", deleted)
    return {"success": True, "deleted": deleted, "message": f"Removed {deleted} extra pending steps"}


@router.post("/{seq_id}/queue-email")
async def queue_email_from_sequence(seq_id: int, db: Session = Depends(get_db)):
    """Take a sequence step's draft content and queue it as a pending email."""
    from models import EmailQueue
    from services.email_service import get_next_send_time

    seq = db.query(Sequence).filter(Sequence.id == seq_id).first()
    if not seq:
        raise HTTPException(status_code=404, detail="Sequence step not found")
    if seq.channel != "email":
        raise HTTPException(status_code=400, detail=f"Step channel is '{seq.channel}', not 'email'")

    prospect = db.query(Prospect).filter(Prospect.id == seq.prospect_id).first()
    if not prospect:
        raise HTTPException(status_code=404, detail="Prospect not found")
    if not prospect.email and not prospect.dm_email:
        raise HTTPException(status_code=400, detail="Prospect has no email address")

    to_addr = seq.to_email or prospect.email or prospect.dm_email
    subject = seq.subject or f"Follow-up: {prospect.company}"
    body = seq.content or ""

    # Calculate business-hours send time
    scheduled = get_next_send_time(prospect) or datetime.utcnow()

    eq = EmailQueue(
        prospect_id=prospect.id,
        sequence_id=seq.id,
        to_email=to_addr,
        subject=subject,
        body=body,
        status="draft",
        scheduled_at=scheduled,
        daily_send_date=date.today().isoformat(),
    )
    db.add(eq)

    # Mark sequence step as pending-scheduled so it doesn't re-queue
    seq.status = "pending"
    db.commit()
    db.refresh(eq)
    logger.info("Queued email from sequence #%d for %s → %s at %s", seq.id, prospect.company, to_addr, scheduled.isoformat())
    return {
        "success": True,
        "queue_id": eq.id,
        "to": to_addr,
        "scheduled_at": scheduled.isoformat(),
        "message": f"Email queued to {to_addr}, scheduled for {scheduled.strftime('%Y-%m-%d %H:%M UTC')}"
    }
