"""Email service — SMTP sending, IMAP reading, business-hours check, daily limit."""

import asyncio
import json
import logging
import os
import re
import smtplib
import zoneinfo
from datetime import date, datetime, timedelta
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart

from config import (
    SMTP_HOST, SMTP_PORT, SMTP_USER, SMTP_PASS,
    SMTP_HOST_2, SMTP_PORT_2, SMTP_USER_2, SMTP_PASS_2,
    SMTP_HOST_3, SMTP_PORT_3, SMTP_USER_3, SMTP_PASS_3,
    IMAP_HOST, IMAP_PORT, IMAP_USER, IMAP_PASS,
    IMAP_HOST_2, IMAP_PORT_2, IMAP_USER_2, IMAP_PASS_2,
    IMAP_HOST_3, IMAP_PORT_3, IMAP_USER_3, IMAP_PASS_3,
    DAILY_EMAIL_LIMIT, COMPANY_NAME, USER_NAME, USER_EMAIL, WEBSITE,
    APP_DIR,
)
from database import SessionLocal
from models import EmailQueue, DailyEmailStats, Prospect, Interaction, Sequence

logger = logging.getLogger(__name__)


def _norm_charset(charset):
    """清洗邮件头里的 charset：去掉引号/分号参数、转小写。"""
    if not charset:
        return None
    s = str(charset).strip().strip("\"'").lower().split(";")[0].strip()
    return s or None


def decode_mail_bytes(raw, charset=None):
    """按邮件实际编码解码正文/头部字节，避免中文乱码。

    国内中文邮件常用 GB2312/GBK，若一律按 UTF-8 硬解会变成 �。
    规则：优先按声明的 charset 严格解码；声明缺失或失败时，
    自动尝试 UTF-8 / GB18030（GBK 超集）；全部失败才 replace 兜底。
    注意：已被 errors="replace" 处理过的内容无法复原，必须保留原始字节。
    """
    if raw is None:
        return ""
    if isinstance(raw, str):
        return raw
    cs = _norm_charset(charset)
    cs_l = (cs or "").lower()
    if not cs or cs_l in ("us-ascii", "ascii"):
        candidates = ["utf-8", "gb18030"]
    elif cs_l in ("gb2312", "gbk", "gb18030", "gb-2312", "gb_2312"):
        candidates = ["gb18030", "utf-8"]
    elif cs_l in ("utf-8", "utf8", "utf_8"):
        candidates = ["utf-8", "gb18030"]
    elif cs_l in ("iso-8859-1", "latin-1", "latin1", "windows-1252", "cp1252"):
        # 很多邮件把 UTF-8 误标成 latin-1，先把 UTF-8 放前面试
        candidates = ["utf-8", cs, "gb18030"]
    else:
        candidates = [cs, "utf-8", "gb18030"]
    for enc in candidates:
        try:
            return raw.decode(enc)
        except (LookupError, UnicodeDecodeError):
            continue
    try:
        return raw.decode(candidates[0], errors="replace")
    except LookupError:
        return raw.decode("utf-8", errors="replace")


# ═══════════════════════════════════════
#  SMTP Sender — supports dual accounts
# ═══════════════════════════════════════

AVAILABLE_SENDERS = [
    {"key": "primary", "label": f"Work mailbox 1 ({SMTP_USER})", "user": SMTP_USER, "host": SMTP_HOST, "port": SMTP_PORT, "pass": SMTP_PASS},
]
if SMTP_USER_2:
    AVAILABLE_SENDERS.append({"key": "secondary", "label": f"Work mailbox 2 ({SMTP_USER_2})", "user": SMTP_USER_2, "host": SMTP_HOST_2, "port": SMTP_PORT_2, "pass": SMTP_PASS_2})
if SMTP_USER_3:
    AVAILABLE_SENDERS.append({"key": "third", "label": f"Work mailbox 3 ({SMTP_USER_3})", "user": SMTP_USER_3, "host": SMTP_HOST_3, "port": SMTP_PORT_3, "pass": SMTP_PASS_3})


def _seed_email_accounts(db) -> None:
    """首次运行时把 .env 里的旧邮箱配置导入 email_accounts，老数据不丢。"""
    from models import EmailAccount
    if db.query(EmailAccount).count() > 0:
        return
    seeds = [
        ("primary", "Work mailbox 1", SMTP_HOST, SMTP_PORT, SMTP_USER, SMTP_PASS,
         IMAP_HOST, IMAP_PORT, IMAP_USER, IMAP_PASS, 1),
    ]
    if SMTP_USER_2:
        seeds.append(("secondary", "Work mailbox 2", SMTP_HOST_2, SMTP_PORT_2, SMTP_USER_2, SMTP_PASS_2,
                      IMAP_HOST_2, IMAP_PORT_2, IMAP_USER_2, IMAP_PASS_2, 2))
    if SMTP_USER_3:
        seeds.append(("third", "Work mailbox 3", SMTP_HOST_3, SMTP_PORT_3, SMTP_USER_3, SMTP_PASS_3,
                      IMAP_HOST_3, IMAP_PORT_3, IMAP_USER_3, IMAP_PASS_3, 3))
    for key, name, sh, sp, su, spw, ih, ip, iu, ipw, order in seeds:
        db.add(EmailAccount(
            key=key, name=name,
            smtp_host=sh, smtp_port=sp, smtp_user=su, smtp_pass=spw,
            imap_host=ih, imap_port=ip, imap_user=iu, imap_pass=ipw,
            sort_order=order, is_active=1,
        ))
    db.commit()


def get_available_senders(db=None) -> list[dict]:
    """从数据库读取邮箱账号（客户可自定义添加，不限数量）；表空时用 .env 旧配置兜底。"""
    from models import EmailAccount
    if db is None:
        db2 = SessionLocal()
        try:
            return _senders_from_db(db2)
        finally:
            db2.close()
    return _senders_from_db(db)


def _senders_from_db(db) -> list[dict]:
    from models import EmailAccount
    try:
        _seed_email_accounts(db)
        rows = db.query(EmailAccount).filter(EmailAccount.is_active == 1).order_by(
            EmailAccount.sort_order.asc(), EmailAccount.id.asc()).all()
    except Exception:
        return list(AVAILABLE_SENDERS)
    if not rows:
        return list(AVAILABLE_SENDERS)
    senders = []
    for a in rows:
        key = a.key or ("acc_%d" % a.id)
        user = a.smtp_user or ""
        name = a.name or "Work mailbox"
        senders.append({
            "key": key, "label": "%s (%s)" % (name, user) if user else name,
            "user": user, "host": a.smtp_host or "", "port": a.smtp_port or 465,
            "pass": a.smtp_pass or "", "name": a.smtp_name or name,
            "bound_user_id": a.bound_user_id,
        })
    return senders


def _get_sender(sender_key: str = "primary") -> dict:
    try:
        senders = get_available_senders()
    except Exception:
        senders = AVAILABLE_SENDERS
    for s in senders:
        if s["key"] == sender_key:
            return s
    return senders[0] if senders else {"key": "primary", "label": "", "user": "", "host": "", "port": 465, "pass": ""}


def _sender_binding(key: str) -> int | None:
    """邮箱账号绑定的成员 user_id（系统配置里可设），没有绑定返回 None。"""
    from models import EmailAccount
    try:
        db2 = SessionLocal()
        try:
            acc = db2.query(EmailAccount).filter(EmailAccount.key == key).first()
            if acc and acc.bound_user_id:
                return int(acc.bound_user_id)
        finally:
            db2.close()
    except Exception:
        pass
    return None


def _send_one_sync(to: str, subject: str, body: str, sender_key: str = "primary",
                   attachment_files: str | None = None, owner_user_id: int | None = None) -> tuple[bool, str]:
    import json as _json
    from email.mime.base import MIMEBase
    from email import encoders

    snd = _get_sender(sender_key)
    # 把 {{占位符}} 替换成真实公司信息，避免客户收到 {{USER_NAME}} 之类的字面量
    def _fill(text: str) -> str:
        if not text:
            return text or ""
        uname = USER_NAME or ""
        uemail = USER_EMAIL or SMTP_USER or ""
        if owner_user_id:
            try:
                from models import User
                db2 = SessionLocal()
                try:
                    u = db2.query(User).filter(User.id == owner_user_id).first()
                    if u:
                        uname = u.name or uname
                        uemail = u.email or uemail
                finally:
                    db2.close()
            except Exception:
                pass
        return (text
                .replace("{{USER_NAME}}", uname)
                .replace("{{USER_EMAIL}}", uemail)
                .replace("{{COMPANY}}", COMPANY_NAME or "")
                .replace("{{WEBSITE}}", WEBSITE or "")
                # 兼容单花括号写法 {COMPANY}（AI/模板偶尔输出单括号）
                .replace("{USER_NAME}", uname)
                .replace("{USER_EMAIL}", uemail)
                .replace("{COMPANY}", COMPANY_NAME or "")
                .replace("{WEBSITE}", WEBSITE or ""))
    subject = _fill(subject)
    body = _fill(body)

    # ── 统一以纯文本发送（方案A）──
    # 邮件客户端对 HTML 渲染差异大（QQ/阿里云/Outlook 会挤成一坨），
    # 外贸开发信/跟进信用纯文本最稳：所有客户端显示一致、更不易进垃圾箱。
    # 发送前把 HTML/换行统一转成可读纯文本：
    #   <br>/</p>/</div>/</li> → 换行；标签剥掉；Markdown 链接 → 文字 (网址)；实体反转义。
    plain = body.replace("\r\n", "\n")
    plain = re.sub(r'<br\s*/?>', '\n', plain, flags=re.I)
    plain = re.sub(r'</(p|div|li|tr|h[1-6])>', '\n', plain, flags=re.I)
    plain = re.sub(r'<li[^>]*>', '- ', plain, flags=re.I)
    plain = re.sub(r'<[^>]+>', '', plain)
    plain = re.sub(r'\[([^\]]+)\]\((https?://[^)\s]+)\)', r'\1 (\2)', plain)
    plain = (plain
             .replace("&nbsp;", " ")
             .replace("&amp;", "&")
             .replace("&lt;", "<")
             .replace("&gt;", ">")
             .replace("&quot;", '"')
             .replace("&#39;", "'"))
    plain = re.sub(r'\n{3,}', '\n\n', plain).strip()
    msg_body = MIMEText(plain, "plain", "utf-8")

    msg = MIMEMultipart()
    msg["From"] = snd["user"]
    msg["To"] = to
    msg["Subject"] = subject
    msg.attach(msg_body)

    # ── Attach files ──
    att_list = []
    if attachment_files:
        try: att_list = _json.loads(attachment_files)
        except Exception: pass
    missing_files = []
    for att in att_list:
        fpath = att.get("path", "")
        fname = att.get("filename", "attachment")
        # Resolve path — could be relative to project root
        if not os.path.isabs(fpath):
            fpath = os.path.join(str(APP_DIR), fpath)
        if os.path.isfile(fpath):
            with open(fpath, "rb") as f:
                part = MIMEBase("application", "octet-stream")
                part.set_payload(f.read())
                encoders.encode_base64(part)
                part.add_header("Content-Disposition", f'attachment; filename="{fname}"')
                msg.attach(part)
            logger.info("Attached file: %s (%s bytes)", fname, os.path.getsize(fpath))
        else:
            missing_files.append(fname)
            logger.warning("Attachment file not found: %s", fpath)
    if missing_files:
        return False, "Attachment file missing: " + ", ".join(missing_files)
    try:
        s = smtplib.SMTP_SSL(snd["host"], snd["port"], timeout=15)
        s.login(snd["user"], snd["pass"])
        s.sendmail(snd["user"], [to], msg.as_string())
        s.quit()
        _save_local_eml(to, subject, msg.as_string())  # local backup
        # _sync_to_sent_folder(msg.as_string(), snd["key"])  # 关掉，SMTP 自己会存档到已发件箱
        logger.info("✅ Sent to %s via %s: %s", to, snd["user"], subject)
        return True, ""
    except Exception as e:
        logger.error("❌ SMTP fail to %s via %s: %s", to, snd["user"], e)
        return False, str(e)


def _save_local_eml(to: str, subject: str, raw: str):
    """Save a local .eml copy as proof of send — can be opened in any mail client."""
    try:
        archive_dir = os.path.join(str(APP_DIR), "sent_archive")
        os.makedirs(archive_dir, exist_ok=True)
        ts = datetime.utcnow().strftime("%Y%m%d_%H%M%S")
        safe_to = re.sub(r'[^a-zA-Z0-9@._-]', '_', to)[:40]
        safe_subject = re.sub(r'[^a-zA-Z0-9一-鿿 _-]', '', subject)[:40]
        fname = f"{ts}_{safe_to}_{safe_subject}.eml"
        fpath = os.path.join(archive_dir, fname)
        with open(fpath, "w", encoding="utf-8") as f:
            f.write(raw)
        logger.info("📁 Archived: %s", fname)
    except Exception as e:
        logger.warning("Could not save local .eml: %s", e)


def _sync_to_sent_folder(raw_message: str, sender_key: str = "primary"):
    """IMAP APPEND a copy of the sent message to the Sent folder of the sender's mailbox,
    so it appears in webmail and syncs across devices."""
    import imaplib
    from datetime import datetime, timezone
    try:
        # Pick the right IMAP credentials per sender
        if sender_key == "secondary" and IMAP_USER_2:
            imap_host = IMAP_HOST_2
            imap_port = IMAP_PORT_2
            imap_user = IMAP_USER_2
            imap_pass = IMAP_PASS_2
        elif sender_key == "third" and IMAP_USER_3:
            imap_host = IMAP_HOST_3
            imap_port = IMAP_PORT_3
            imap_user = IMAP_USER_3
            imap_pass = IMAP_PASS_3
        else:
            imap_host = IMAP_HOST
            imap_port = IMAP_PORT
            imap_user = IMAP_USER
            imap_pass = IMAP_PASS

        mail = imaplib.IMAP4_SSL(imap_host, imap_port, timeout=15)
        mail.login(imap_user, imap_pass)
        sent_folder = _find_sent_folder(mail)
        dt = datetime.now(timezone.utc)
        mail.append(sent_folder, "\\Seen", imaplib.Time2Internaldate(dt), raw_message.encode("utf-8"))
        mail.logout()
        logger.debug("Synced to Sent folder (%s): %s", imap_host, sent_folder)
    except Exception as e:
        logger.warning("Could not sync to Sent folder (%s): %s", sender_key, e)


def _find_sent_folder(mail) -> str:
    """Find the Sent folder in case ZOHO names it differently by language."""
    import imaplib
    candidates = ["Sent", "Sent Messages", "Gesendet", "已发送"]
    try:
        status, folders = mail.list()
        if status == "OK":
            for line in folders:
                decoded = line.decode("utf-8", errors="replace")
                for c in candidates:
                    if c.lower() in decoded.lower():
                        folder_name = decoded.rsplit('"/" ', 1)[-1].strip().strip('"')
                        return folder_name
    except Exception:
        pass
    return "Sent"


async def send_email(to: str, subject: str, body: str, sender_key: str = "primary") -> bool:
    loop = asyncio.get_event_loop()
    ok, _ = await loop.run_in_executor(None, _send_one_sync, to, subject, body, sender_key)
    return ok


# ═══════════════════════════════════════
#  Business Hours Check
# ═══════════════════════════════════════

def is_business_hours_now(prospect: Prospect) -> tuple[bool, str]:
    tz_str = (prospect.timezone or "").strip()
    if not tz_str:
        return True, "no timezone — send anyway"
    try:
        tz = zoneinfo.ZoneInfo(tz_str)
        now = datetime.now(tz)
        wd = now.weekday()
        hr = now.hour
        if wd >= 5:
            return False, f"weekend in {tz_str} ({now:%a %H:%M})"
        if 9 <= hr <= 17:
            return True, f"business hours: {now:%a %H:%M} in {tz_str}"
        return False, f"outside 9 AM - 5 PM in {tz_str} (local {now:%H:%M})"
    except Exception:
        return True, f"unknown tz {tz_str} — send anyway"


def get_next_send_time(prospect: Prospect):
    import random as _random
    tz_str = (prospect.timezone or "").strip()
    if not tz_str:
        return None
    try:
        tz = zoneinfo.ZoneInfo(tz_str)
        now = datetime.now(tz)
        if now.weekday() >= 5 or now.hour >= 17:
            d = 1
            if now.weekday() == 5: d = 2
            elif now.weekday() == 4 and now.hour >= 17: d = 3
            elif now.weekday() == 6: d = 1
            next_d = (now + timedelta(days=d)).date()
        else:
            next_d = now.date()
        # Spread across 9:00-11:30, random minute 0-59
        # Each prospect gets a unique minute — never all at :15
        hour = 9 + _random.randint(0, 5)  # 9-14 → but clamp to 9-11 below
        if hour > 11:
            hour = 9 + ((hour - 9) % 3)  # remap 12-14 back to 9-11
        minute = _random.randint(0, 59)
        return datetime(next_d.year, next_d.month, next_d.day, hour, minute, tzinfo=tz)
    except Exception:
        return None


# ═══════════════════════════════════════
#  Daily Limit
# ═══════════════════════════════════════

def check_daily_limit() -> tuple[int, int]:
    db = SessionLocal()
    try:
        today_str = date.today().isoformat()
        s = db.query(DailyEmailStats).filter(DailyEmailStats.date == today_str).first()
        if not s:
            return 0, DAILY_EMAIL_LIMIT
        return s.sent_count, max(0, DAILY_EMAIL_LIMIT - s.sent_count)
    finally:
        db.close()


# ═══════════════════════════════════════
#  Queue Processor
# ═══════════════════════════════════════

async def process_email_queue():
    db = SessionLocal()
    try:
        today_str = date.today().isoformat()
        now = datetime.utcnow()

        s = db.query(DailyEmailStats).filter(DailyEmailStats.date == today_str).first()
        if not s:
            s = DailyEmailStats(date=today_str, sent_count=0, limit_count=DAILY_EMAIL_LIMIT)
            db.add(s)
            db.flush()

        remaining = DAILY_EMAIL_LIMIT - s.sent_count
        if remaining <= 0:
            logger.info("Daily limit reached (%d/%d)", s.sent_count, DAILY_EMAIL_LIMIT)
            return

        pending = (
            db.query(EmailQueue)
            .filter(EmailQueue.status == "pending", EmailQueue.scheduled_at <= now)
            .order_by(EmailQueue.scheduled_at.asc())
            .limit(remaining + 5)
            .all()
        )

        sent = 0
        for eq in pending:
            if sent >= remaining:
                break
            prospect = db.query(Prospect).filter(Prospect.id == eq.prospect_id).first()
            if prospect is not None and prospect.is_deleted:
                eq.status = "cancelled"
                eq.last_error = "Client deleted — send auto-cancelled"
                continue
            if prospect:
                can, reason = is_business_hours_now(prospect)
                if not can:
                    nt = get_next_send_time(prospect)
                    if nt:
                        eq.scheduled_at = nt
                        logger.debug("Re-scheduled %s → %s (%s)", eq.to_email, nt, reason)
                        continue

            ok, err = _send_one_sync(eq.to_email, eq.subject, eq.body, eq.sender_key or "primary", attachment_files=eq.attachment_files, owner_user_id=eq.owner_user_id)
            if ok:
                eq.status = "sent"
                eq.sent_at = datetime.utcnow()
                eq.daily_send_date = today_str
                s.sent_count += 1
                sent += 1
                _record_interaction(eq.prospect_id, eq.to_email, eq.subject, eq.body)  # auto-record
                _finish_sequence_step(eq)  # auto-mark sequence step done
                try:
                    from services.auth_service import log_audit
                    from models import User as _User
                    _u = db.query(_User).filter(_User.id == eq.owner_user_id).first() if eq.owner_user_id else None
                    log_audit(db, _u, "send_email", f"prospect#{eq.prospect_id}",
                              f"Sent email to {eq.to_email}: {(eq.subject or '')[:80]}")
                except Exception:
                    pass
                # Spread sends: random 90-240s between each email to avoid Zoho rate limits
                import random as _rand, time as _time
                _time.sleep(_rand.randint(90, 240))
            else:
                eq.status = "failed"
                eq.last_error = err[:500]
                eq.retry_count = (eq.retry_count or 0) + 1

        db.commit()
        if sent > 0:
            logger.info("📬 Processed %d emails", sent)
    except Exception as e:
        db.rollback()
        logger.exception("process_email_queue failed")
    finally:
        db.close()


def _record_interaction(prospect_id: int, to_email: str, subject: str, body: str):
    """Create an outbound interaction record for the email just sent.
    Tags with active methodology IDs for feedback-loop attribution."""
    try:
        db2 = SessionLocal()
        meta = None
        try:
            from services.gemini_service import get_active_methodology_ids
            mids = get_active_methodology_ids()
            if mids:
                import json
                meta = json.dumps(mids)
        except Exception:
            pass

        i = Interaction(
            prospect_id=prospect_id,
            direction="outbound",
            channel="email",
            subject=subject,
            content=body[:5000] if body else "",
            generation_meta=meta,
        )
        db2.add(i)
        db2.commit()
        db2.close()
    except Exception:
        pass


def _finish_sequence_step(eq):
    """After email sent, auto-mark the linked sequence step as done
    and push next_follow_date forward with progressive interval based on
    outbound count since last inbound reply."""
    from datetime import date, timedelta
    try:
        db2 = SessionLocal()
        # Mark sequence step done
        if eq.sequence_id:
            seq = db2.query(Sequence).filter(Sequence.id == eq.sequence_id).first()
            if seq and seq.status == "pending":
                seq.status = "done"
                seq.executed_at = datetime.utcnow()
                seq.updated_at = datetime.utcnow()
                logger.info("Auto-marked sequence #%d as done (email #%d sent)", seq.id, eq.id)

        # Push next_follow_date forward with progressive interval
        prospect = db2.query(Prospect).filter(Prospect.id == eq.prospect_id).first()
        if prospect:
            today = date.today()

            # ── Progressive follow-up interval ──
            # Count outbounds since last inbound to determine how deep we are in cold follow-up.
            # 1st follow-up → +3d, 2nd → +5d, 3rd → +7d, 4th+ → +10d
            outbound_count = 0
            all_ix = db2.query(Interaction).filter(
                Interaction.prospect_id == eq.prospect_id
            ).order_by(Interaction.interacted_at.desc()).all()
            for ix in all_ix:
                if ix.direction == "inbound":
                    break
                outbound_count += 1

            # Progressive interval map: 1→3d, 2→5d, 3→7d, 4+→10d
            PROGRESSIVE_INTERVALS = {1: 3, 2: 5, 3: 7}
            interval_days = PROGRESSIVE_INTERVALS.get(outbound_count, 10)

            next_date = today + timedelta(days=interval_days)
            # ── 与开发计划排期对齐：如果该客户已有排期更晚的 pending 步骤，
            #    以开发计划的排期为准，避免 next_follow_date 被推得太近导致误报逾期。──
            try:
                later_step = (
                    db2.query(Sequence)
                    .filter(
                        Sequence.prospect_id == eq.prospect_id,
                        Sequence.status == "pending",
                        Sequence.scheduled_date.isnot(None),
                        Sequence.scheduled_date > next_date.isoformat(),
                    )
                    .order_by(Sequence.scheduled_date.asc())
                    .first()
                )
                if later_step:
                    try:
                        later_dt = date.fromisoformat(str(later_step.scheduled_date)[:10])
                        if later_dt > next_date:
                            next_date = later_dt
                            logger.info("next_follow_date aligned to dev-plan step #%d → %s", later_step.id, next_date)
                    except Exception:
                        pass
            except Exception as exc:
                logger.warning("dev-plan alignment failed: %s", exc)
            prospect.next_follow_date = next_date.isoformat()
            prospect.reminder_note = f"[Auto] email #{outbound_count} sent → suggested follow-up {next_date}"
            prospect.reminder_updated_at = datetime.utcnow()
            prospect.last_edited_at = datetime.utcnow()
            logger.info("Auto-scheduled next_follow_date for prospect #%d: %s (+%dd, outbound #%d)", prospect.id, next_date, interval_days, outbound_count)

        db2.commit()
        db2.close()
    except Exception as e:
        logger.warning("_finish_sequence_step failed: %s", e)


# ═══════════════════════════════════════
#  IMAP Reader
# ═══════════════════════════════════════

def _match_dm_email(db, from_addr: str):
    """dm_email 列可能存多个邮箱（逗号/分号/空格分隔），逐一精确匹配。"""
    from models import Prospect
    addr = (from_addr or "").strip().lower()
    if not addr:
        return None
    rows = db.query(Prospect).filter(
        Prospect.dm_email != None,
        Prospect.dm_email != "",
    ).all()
    for p in rows:
        for piece in re.split(r"[,;，；\s]+", p.dm_email or ""):
            if piece.strip().lower() == addr:
                return p
    return None


async def fetch_new_replies() -> list:
    """
    Connect to IMAP, fetch recent emails, match sender to prospects,
    auto-create inbound interactions. Uses email_message_id for dedup.
    Extracts attachments and saves them to local files.
    """
    import imaplib
    import email
    from email.header import decode_header

    new_replies = []

    try:
        loop = asyncio.get_event_loop()
        raw_results = await loop.run_in_executor(None, _imap_fetch_sync)
        if not raw_results:
            return []

        db = SessionLocal()
        try:
            for msg_data, bound_user_id in raw_results:
                msg = email.message_from_bytes(msg_data)
                msg_id = msg.get("Message-ID", "").strip()
                if not msg_id:
                    continue

                existing = db.query(Interaction).filter(
                    Interaction.email_message_id == msg_id
                ).first()
                if existing:
                    continue

                from_addr = msg.get("From", "")
                m = re.search(r'<(.+?)>', from_addr)
                if m:
                    from_addr = m.group(1)
                from_addr = from_addr.strip().lower()

                subject = msg.get("Subject", "")
                decoded_parts = decode_header(subject)
                subject = ""
                for part, enc in decoded_parts:
                    if isinstance(part, bytes):
                        subject += decode_mail_bytes(part, enc)
                    else:
                        subject += str(part)
                subject = subject.strip()

                msg_date = msg.get("Date", "")
                email_date = None
                try:
                    from email.utils import parsedate_to_datetime
                    email_date = parsedate_to_datetime(msg_date)
                except Exception:
                    email_date = datetime.utcnow()

                body = ""
                html_body = ""
                attachments = []
                if msg.is_multipart():
                    for part in msg.walk():
                        ct = part.get_content_type()
                        disp = part.get_content_disposition() or ""
                        if disp and "attachment" in disp.lower():
                            filename = part.get_filename()
                            if filename:
                                decoded_fn = decode_header(filename)
                                filename = ""
                                for fn_part, enc in decoded_fn:
                                    if isinstance(fn_part, bytes):
                                        filename += decode_mail_bytes(fn_part, enc)
                                    else:
                                        filename += str(fn_part)
                                file_bytes = part.get_payload(decode=True)
                                attachments.append((filename, file_bytes))
                        elif ct.startswith("image/") and (part.get_filename() or part.get("Content-ID", "")):
                            # 内嵌图片（inline）也保存，客户常把回执/截图以 cid 图片发过来
                            filename = part.get_filename()
                            if not filename:
                                cid = str(part.get("Content-ID", "") or "").strip("<>")
                                ext = {"image/png": ".png", "image/jpeg": ".jpg", "image/gif": ".gif", "image/webp": ".webp"}.get(ct, ".img")
                                filename = (cid.replace("@", "_").replace("/", "_") or f"inline_{len(attachments)}") + ext
                            file_bytes = part.get_payload(decode=True)
                            attachments.append((filename, file_bytes))
                        elif ct == "text/plain" and not body:
                            try:
                                body = decode_mail_bytes(part.get_payload(decode=True), part.get_content_charset())
                            except Exception:
                                body = part.get_payload()
                        elif ct == "text/html" and not html_body:
                            try:
                                html_body = decode_mail_bytes(part.get_payload(decode=True), part.get_content_charset())
                            except Exception:
                                html_body = part.get_payload()
                else:
                    try:
                        body = decode_mail_bytes(msg.get_payload(decode=True), msg.get_content_charset())
                    except Exception:
                        body = msg.get_payload()

                if not body and html_body:
                    from re import sub as _html_sub, DOTALL as _DOTALL
                    body = _html_sub(r'<style[^>]*>.*?</style>', '', html_body, flags=_DOTALL)
                    body = _html_sub(r'<[^>]+>', ' ', body)
                    body = _html_sub(r'\s+', ' ', body).strip()

                # If still no body but has attachments, note it
                if not body and attachments:
                    body = "[No text, attachments only] " + ", ".join(fn for fn, _ in attachments)

                # Save attachments to local files
                attachment_files = []
                if attachments:
                    import os as _os
                    att_dir = _os.path.join(str(APP_DIR), "attachments")
                    _os.makedirs(att_dir, exist_ok=True)
                    ts = datetime.utcnow().strftime("%Y%m%d_%H%M%S")
                    for i, (fn, fb) in enumerate(attachments):
                        safe_fn = f"{ts}_{i}_{fn}"
                        att_path = _os.path.join(att_dir, safe_fn)
                        with open(att_path, "wb") as f:
                            f.write(fb)
                        attachment_files.append({"filename": fn, "path": f"attachments/{safe_fn}", "size": len(fb)})

                # ── Bounce detection ──────────────────────
                is_bounce = _detect_bounce(subject, from_addr, body or "")
                if is_bounce:
                    bounced_email = _extract_bounced_email(subject or "", body or "")
                    logger.warning("BOUNCE detected: %s → bounced address: %s", from_addr, bounced_email)
                    if bounced_email:
                        bp = db.query(Prospect).filter(
                            Prospect.email == bounced_email
                        ).first()
                        if not bp:
                            bp = _match_dm_email(db, bounced_email)
                        if bp:
                            bp.email_status = "bounced"
                            bp.last_edited_at = datetime.utcnow()
                            db.add(Interaction(
                                prospect_id=bp.id,
                                direction="inbound",
                                channel="email",
                                content=f"[Auto-detected] Mail bounce — {subject[:100]}",
                                subject=f"Bounce: {subject[:100]}",
                                email_message_id=msg_id,
                                email_from=from_addr,
                                email_received_at=datetime.utcnow(),
                                reply_intent="bounce",
                            ))
                            logger.info("BOUNCE: marked %s (%s) as bounced", bp.company, bp.email)
                            # ── WeChat notification ──
                            try:
                                from tools.health_check import serverchan
                                serverchan(
                                    "📮 Bounce warning (B2B Outbound OS)",
                                    f"Client: {bp.company}\nEmail: {bounced_email}\nSubject: {subject[:100]}\nTime: {datetime.utcnow().strftime('%m/%d %H:%M')}\nSuggestion: contact via LinkedIn/WhatsApp instead"
                                )
                            except Exception:
                                pass
                    continue  # Don't create a normal interaction for bounces

                # ── Normal reply matching ─────────────────

                prospect = db.query(Prospect).filter(
                    Prospect.email == from_addr
                ).first()
                if not prospect:
                    prospect = _match_dm_email(db, from_addr)

                interaction = Interaction(
                    prospect_id=prospect.id if prospect else 0,
                    direction="inbound",
                    channel="email",
                    content=body[:5000] if body else "",
                    subject=subject,
                    email_message_id=msg_id,
                    email_from=from_addr,
                    email_received_at=email_date,
                    interacted_at=email_date,
                    attachment_files=json.dumps(attachment_files, ensure_ascii=False) if attachment_files else None,
                    owner_user_id=bound_user_id,
                )
                if prospect and bound_user_id and not prospect.owner_user_id:
                    prospect.owner_user_id = bound_user_id
                if attachment_files:
                    att_line = "\n\n[Attachments] " + ", ".join(
                        f"{a['filename']} ({a['size']:,}B)" for a in attachment_files
                    )
                    remaining = 5000 - len(interaction.content) - len(att_line)
                    if remaining > 0:
                        interaction.content = interaction.content + att_line
                db.add(interaction)
                db.flush()
                try:
                    if prospect:
                        from routers.ops import _close_reply
                        await _close_reply(interaction, db, force=False)
                except Exception as exc:
                    logger.warning("Reply auto-closure failed for message %s: %s", msg_id, exc)
                new_replies.append({
                    "from": from_addr,
                    "subject": subject[:100],
                    "matched": prospect.company if prospect else "unknown",
                })

            db.commit()
            if new_replies:
                logger.info("IMAP: imported %d new replies", len(new_replies))
                # 后台异步：对刚入库的互动做 AI 报价提取（不阻塞收信主流程）
                _spawn_quote_extract(db, new_replies)

        finally:
            db.close()

    except Exception as exc:
        logger.exception("IMAP fetch failed: %s", exc)

    return new_replies


def _spawn_quote_extract(db, new_replies):
    """收集本次新入库互动的 id，交给线程池做报价提取。
    new_replies 里没有 interaction id，这里直接从 interactions 表按时间倒序取最新 N 条
    已归属客户的 inbound 记录（有 prospect_id 的），避免重复处理。"""
    try:
        from models import Interaction
        recent = (
            db.query(Interaction)
            .filter(
                Interaction.direction == "inbound",
                Interaction.prospect_id.isnot(None),
                Interaction.prospect_id > 0,
            )
            .order_by(Interaction.id.desc())
            .limit(len(new_replies) * 2 + 5)
            .all()
        )
        ids = [i.id for i in recent]
        if not ids:
            return
        # 收集涉及的客户 ID（去重），用于收信后自动刷新对话全景
        pids = list({i.prospect_id for i in recent if i.prospect_id})
        import threading

        def _run():
            from services.quote_extractor import extract_quote_from_interaction
            for iid in ids:
                try:
                    extract_quote_from_interaction(iid)
                except Exception as exc:
                    logger.warning("quote extract bg failed (inter %s): %s", iid, exc)
            # 新邮件入库后自动刷新这些客户的对话全景（后台，不阻塞收信）
            from services.quote_extractor import generate_dialogue_panorama
            for pid in pids:
                try:
                    # 节流：同一客户 30 分钟内已自动刷新过则跳过（手动刷新不受限）
                    from models import Intelligence
                    from datetime import datetime as _dt, timedelta as _td
                    _db2 = SessionLocal()
                    try:
                        _intel = _db2.query(Intelligence).filter(Intelligence.prospect_id == pid).first()
                        if _intel and _intel.dialogue_panorama_at:
                            if _dt.utcnow() - _intel.dialogue_panorama_at < _td(minutes=30):
                                logger.info("Panorama throttle: prospect %s refreshed <30min ago, skip", pid)
                                continue
                    finally:
                        _db2.close()
                    r = generate_dialogue_panorama(pid)
                    logger.info("Auto panorama refresh prospect %s: success=%s", pid, r.get("success"))
                except Exception as exc:
                    logger.warning("auto panorama refresh failed (prospect %s): %s", pid, exc)

        threading.Thread(target=_run, daemon=True).start()
    except Exception as exc:
        logger.warning("quote extract spawn failed: %s", exc)


def _imap_fetch_sync():
    """Synchronous IMAP fetch — run in executor thread.
    Searches recent inbox emails (last 7 days, max 100). Dedup is handled
    by Message-ID so we never double-import. 遍历所有启用的邮箱账号（可自定义，不限数量）。"""
    import imaplib
    from datetime import datetime, timedelta
    from models import EmailAccount
    try:
        _db = SessionLocal()
        try:
            _seed_email_accounts(_db)
            _rows = _db.query(EmailAccount).filter(EmailAccount.is_active == 1).all()
        finally:
            _db.close()
    except Exception:
        _rows = []
    accounts = []
    for a in _rows:
        imap_user = a.imap_user or ""
        imap_pass = a.imap_pass or ""
        imap_host = a.imap_host or ""
        if not imap_host:
            continue
        # 数据库里 imap_user 为空时，回退到 .env 的旧配置（防止配置更新后收不到信）
        if not imap_user:
            key = a.key or ("acc_%d" % a.id)
            if key == "primary" and IMAP_USER:
                imap_user, imap_pass, imap_host = IMAP_USER, IMAP_PASS, IMAP_HOST
            elif key == "secondary" and IMAP_USER_2:
                imap_user, imap_pass, imap_host = IMAP_USER_2, IMAP_PASS_2, IMAP_HOST_2
            elif key == "third" and IMAP_USER_3:
                imap_user, imap_pass, imap_host = IMAP_USER_3, IMAP_PASS_3, IMAP_HOST_3
        if imap_host and imap_user:
            accounts.append((a.key or ("acc_%d" % a.id), imap_host,
                             a.imap_port or 993, imap_user, imap_pass))
    if not accounts:
        # 兜底：.env 旧配置
        accounts = [("primary", IMAP_HOST, IMAP_PORT, IMAP_USER, IMAP_PASS)]
        if IMAP_HOST_2 and IMAP_USER_2:
            accounts.append(("secondary", IMAP_HOST_2, IMAP_PORT_2, IMAP_USER_2, IMAP_PASS_2))
        if IMAP_HOST_3 and IMAP_USER_3:
            accounts.append(("third", IMAP_HOST_3, IMAP_PORT_3, IMAP_USER_3, IMAP_PASS_3))
    results = []
    meta_list = []  # (msg_bytes, bound_user_id) — 每个邮箱账号的归属用户
    # Force English month abbreviations — strftime("%b") is locale-dependent,
    # and on Chinese Windows it produces "7月" instead of "Jul", which breaks
    # IMAP SINCE search entirely (server returns empty or error).
    _MONTHS_EN = ["Jan", "Feb", "Mar", "Apr", "May", "Jun",
                  "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"]
    _now = datetime.utcnow()
    since_dt = _now - timedelta(days=3)
    since_date = f"{since_dt.day:02d}-{_MONTHS_EN[since_dt.month - 1]}-{since_dt.year}"
    for key, host, port, user, pwd in accounts:
        bound_user_id = _sender_binding(key)
        try:
            mail = imaplib.IMAP4_SSL(host, port, timeout=20)
            mail._encoding = "utf-8"   # 阿里企业邮箱响应可能含中文，默认 ascii 会崩
            mail.login(user, pwd)
            # Check both INBOX and Spam/Junk folders — Zoho often moves bounces to Spam
            for folder in ["INBOX", "[Gmail]/Spam", "Junk", "Spam"]:
                try:
                    sel = mail.select(folder)
                    if sel[0] != "OK":
                        continue  # folder does not exist — skip it, don't abort the account
                except Exception:
                    continue
                try:
                    status, data = mail.search(None, f'(SINCE "{since_date}")')
                except Exception:
                    continue
                if status == "OK" and data[0]:
                    msg_ids = data[0].split()
                    # Last 100 within the window — fast even on large mailboxes
                    for num in msg_ids[-100:]:
                        try:
                            status2, msg_data = mail.fetch(num, "(RFC822)")
                            if status2 == "OK" and msg_data[0]:
                                results.append(msg_data[0][1])
                                meta_list.append((msg_data[0][1], bound_user_id))
                        except Exception:
                            continue
            mail.logout()
        except Exception as exc:
            logger.error("IMAP sync error (%s): %s", host, exc)
    logger.info("IMAP: fetched %d emails (since %s)", len(results), since_date)
    return meta_list


# ── Bounce detection helpers ──────────────────────────────

BOUNCE_SUBJECT_KEYWORDS = [
    "undeliverable", "undelivered", "mail delivery failed", "delivery failure",
    "returned mail", "postmaster", "mailer-daemon",
    "delivery status notification", "failed delivery",
    "could not be delivered", "message not delivered",
    "undelivered mail", "returned to sender",
    "退信", "无法送达", "发送失败", "退回",
]

BOUNCE_SENDER_KEYWORDS = [
    "mailer-daemon", "postmaster", "mail delivery",
    "noreply", "no-reply", "auto-reply@",
]

BOUNCE_REASON_PATTERNS = [
    (r'([\w\.\-_]+@[\w\.\-_]+).*?does\s+not\s+exist', "Email does not exist"),
    (r'([\w\.\-_]+@[\w\.\-_]+).*?user\s+unknown', "User unknown"),
    (r'([\w\.\-_]+@[\w\.\-_]+).*?mailbox\s+full', "Mailbox full"),
    (r'([\w\.\-_]+@[\w\.\-_]+).*?over\s+quota', "Over quota"),
    (r'([\w\.\-_]+@[\w\.\-_]+).*?blocked', "Blocked"),
    (r'([\w\.\-_]+@[\w\.\-_]+).*?spam', "Marked as spam"),
    (r'[<]?([\w\.\-_]+@[\w\.\-_]+)[>]?', None),  # fallback: any email in body
]


BOUNCE_BODY_KEYWORDS = [
    "undeliverable", "undelivered", "mail delivery failed", "delivery failed",
    "delivery status notification", "failed delivery", "returned to sender",
    "could not be delivered", "message not delivered", "undelivered mail",
    "cannot be delivered", "no such user", "user unknown", "invalid address",
    "address not found", "mailbox full", "over quota", "unknown recipient",
    "550 5.1.1", "550 5.1.0", "550 5.7", "553 5.1",
    "退信", "无法送达", "发送失败", "无法投递", "退回",
]

def _detect_bounce(subject: str, from_addr: str, body: str) -> bool:
    """Check if an inbound email looks like a bounce / delivery failure.

    Subject / sender keywords are strong signals (bounce servers use them).
    Body-only detection requires MULTIPLE strong delivery-failure markers,
    or a single SMTP error code / Chinese bounce word. A single common word
    like "recipient" (legal footer of EU corporate emails) must NOT trigger.
    """
    combined = f"{subject.lower()} {from_addr.lower()}"
    for kw in BOUNCE_SUBJECT_KEYWORDS:
        if kw in combined:
            return True
    for kw in BOUNCE_SENDER_KEYWORDS:
        if kw in combined:
            return True
    body_lower = body.lower()
    hits = sum(1 for kw in BOUNCE_BODY_KEYWORDS if kw in body_lower)
    if hits >= 2:
        return True
    for kw in ("550 5.", "5.1.1", "5.1.0", "退信", "无法送达", "发送失败",
               "无法投递", "undeliverable", "delivery status notification"):
        if kw in body_lower:
            return True
    return False


def _extract_bounced_email(subject: str, body: str) -> str | None:
    """Try to extract the original recipient email from a bounce message."""
    import re
    text = f"{subject} {body}"
    for pattern, reason in BOUNCE_REASON_PATTERNS:
        m = re.search(pattern, text, re.IGNORECASE)
        if m and m.group(1) and '@' in m.group(1):
            return m.group(1).lower()
    return None
