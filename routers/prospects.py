"""Prospects router — import, list, detail, update, delete, timeline.

Handles:
- Auto timezone detection from country on import
- Deduplication on (company + email)
"""

import json
import re
import logging
import sqlite3
from datetime import datetime, timedelta
from typing import Optional

from fastapi import APIRouter, Depends, Query, HTTPException
from sqlalchemy.orm import Session
from sqlalchemy import and_, func, case, or_

from config import DATABASE_URL
from database import get_db
from models import Prospect, Interaction, Sequence, EmailQueue, Intelligence, User, AuditLog
from routers.auth import get_current_user
from schemas import (
    ProspectOut,
    ProspectListOut,
    ProspectUpdate,
    ImportResult,
    TimelineItem,
)

logger = logging.getLogger(__name__)
router = APIRouter()


# ── POST /api/prospects/create ─────────────────────
@router.post("/create", response_model=ProspectOut)
async def create_prospect(data: dict, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    """手动添加单个客户。公司名相同的客户会自动归为同公司联系人。"""
    company = (data.get("company") or "").strip()
    if not company:
        raise HTTPException(status_code=400, detail="Company name is required")
    email = (data.get("email") or "").strip()
    if email:
        existing = db.query(Prospect).filter(
            and_(
                Prospect.company == company,
                Prospect.email == email,
                Prospect.is_deleted == 0,
            )
        ).first()
        if existing:
            raise HTTPException(status_code=400, detail=f"Same-company customer with this email already exists: {existing.company}")
    tz = data.get("timezone")
    if not tz:
        tz = _get_timezone(data.get("country") or "") or "Asia/Shanghai"
    prospect = Prospect(
        contact=data.get("contact"),
        company=company,
        website=data.get("website"),
        title=data.get("title"),
        country=data.get("country"),
        size=data.get("size"),
        industry=data.get("industry"),
        phone=data.get("phone"),
        email=email,
        linkedin=data.get("linkedin"),
        note=data.get("note"),
        source=data.get("source"),
        source_channel=data.get("source_channel"),
        development_batch=data.get("development_batch") or data.get("batch"),
        first_touch_channel=data.get("first_touch_channel"),
        timezone=tz,
        parent_company=data.get("parent_company"),
        decision_maker=data.get("decision_maker") or data.get("dm_name"),
        dm_title=data.get("dm_title"),
        dm_linkedin=data.get("dm_linkedin"),
        dm_email=data.get("dm_email"),
        status=data.get("status") or "New",
        sales_stage=data.get("sales_stage") or "new",
        owner_user_id=user.id if user and user.id else None,
        tenant_id=user.tenant_id if user else None,
    )
    db.add(prospect)
    db.commit()
    db.refresh(prospect)
    try:
        from services.auth_service import log_audit
        log_audit(db, user, "create_prospect", f"prospect#{prospect.id}",
                  f"Manually added customer {prospect.company}")
    except Exception:
        pass
    return ProspectOut.model_validate(prospect)


def _scope_query(q, user: User, mine: bool = False):
    """成员只能看到自己负责的客户；主账号/管理员看全部（可加 mine=1 只看自己)。"""
    if user and user.role == "member" and user.id:
        return q.filter(Prospect.owner_user_id == user.id)
    if mine and user and user.id:
        return q.filter(Prospect.owner_user_id == user.id)
    return q


def _find_duplicate_prospect(db, company: str, email: str, contact: str | None = None) -> Prospect | None:
    """同公司不同的人不算重复：同邮箱，或同公司+同联系人（即使邮箱不同)才算同一人。"""
    company = (company or "").strip()
    email = (email or "").strip().lower()
    q = db.query(Prospect).filter(Prospect.is_deleted == 0)
    if email:
        existing = q.filter(func.lower(func.trim(Prospect.email)) == email).first()
        if existing:
            return existing
    if company:
        norm_contact = re.sub(r"[\W_]+", "", (contact or "").lower())
        same_co = q.filter(Prospect.company == company).all()
        if norm_contact:
            for p in same_co:
                if re.sub(r"[\W_]+", "", (p.contact or "").lower()) == norm_contact:
                    return p
    return None


def _ensure_visible(p: Prospect, user: User):
    if user and user.role == "member" and user.id and p.owner_user_id != user.id:
        raise HTTPException(status_code=404, detail="Customer not found or no permission")


def _record_view(db, user: User, p: Prospect):
    """查看痕迹（同一成员同一 days看同一客户只记一条，避免刷屏)。"""
    if not user or not user.id:
        return
    day_start = datetime.utcnow().replace(hour=0, minute=0, second=0, microsecond=0)
    exists = (
        db.query(AuditLog)
        .filter(
            AuditLog.user_id == user.id,
            AuditLog.action == "view_prospect",
            AuditLog.target == f"prospect#{p.id}",
            AuditLog.created_at >= day_start,
        )
        .first()
    )
    if not exists:
        db.add(AuditLog(tenant_id=user.tenant_id, user_id=user.id, action="view_prospect",
                        target=f"prospect#{p.id}", detail=p.company))
        db.commit()


# ── Timezone mapping (country -> IANA timezone + UTC offset) ──
COUNTRY_TZ = {
    "DE": "Europe/Berlin", "AT": "Europe/Vienna", "CH": "Europe/Zurich",
    "FR": "Europe/Paris", "UK": "Europe/London", "GB": "Europe/London",
    "IT": "Europe/Rome", "ES": "Europe/Madrid", "NL": "Europe/Amsterdam",
    "BE": "Europe/Brussels", "PL": "Europe/Warsaw", "CZ": "Europe/Prague",
    "SE": "Europe/Stockholm", "DK": "Europe/Copenhagen", "NO": "Europe/Oslo",
    "FI": "Europe/Helsinki", "IE": "Europe/Dublin", "PT": "Europe/Lisbon",
    "US": "America/New_York", "CA": "America/Toronto",
    "TR": "Europe/Istanbul", "IN": "Asia/Kolkata",
    "JP": "Asia/Tokyo", "KR": "Asia/Seoul", "CN": "Asia/Shanghai",
    "TW": "Asia/Taipei", "HK": "Asia/Hong_Kong", "SG": "Asia/Singapore",
    "AU": "Australia/Sydney", "NZ": "Pacific/Auckland",
    "BR": "America/Sao_Paulo", "MX": "America/Mexico_City",
    "AE": "Asia/Dubai", "SA": "Asia/Riyadh",
    "IL": "Asia/Jerusalem", "ZA": "Africa/Johannesburg",
    "RU": "Europe/Moscow", "LU": "Europe/Luxembourg",
    "RO": "Europe/Bucharest", "BG": "Europe/Sofia", "HR": "Europe/Zagreb",
    "SI": "Europe/Ljubljana", "SK": "Europe/Bratislava", "LT": "Europe/Vilnius",
    "LV": "Europe/Riga", "EE": "Europe/Tallinn", "HU": "Europe/Budapest",
}
UTC_OFFSET = {
    "Europe/Berlin": "UTC+1/+2", "Europe/Vienna": "UTC+1/+2", "Europe/Zurich": "UTC+1/+2",
    "Europe/Paris": "UTC+1/+2", "Europe/London": "UTC+0/+1",
    "Europe/Rome": "UTC+1/+2", "Europe/Madrid": "UTC+1/+2",
    "Europe/Amsterdam": "UTC+1/+2", "Europe/Brussels": "UTC+1/+2",
    "Europe/Warsaw": "UTC+1/+2", "Europe/Prague": "UTC+1/+2",
    "Europe/Stockholm": "UTC+1/+2", "Europe/Copenhagen": "UTC+1/+2",
    "Europe/Oslo": "UTC+1/+2", "Europe/Helsinki": "UTC+2/+3",
    "Europe/Dublin": "UTC+0/+1", "Europe/Lisbon": "UTC+0/+1",
    "America/New_York": "UTC-5/-4", "America/Toronto": "UTC-5/-4",
    "Europe/Istanbul": "UTC+3", "Asia/Kolkata": "UTC+5:30",
    "Asia/Tokyo": "UTC+9", "Asia/Seoul": "UTC+9", "Asia/Shanghai": "UTC+8",
    "Asia/Taipei": "UTC+8", "Asia/Hong_Kong": "UTC+8", "Asia/Singapore": "UTC+8",
    "Australia/Sydney": "UTC+10/+11", "Pacific/Auckland": "UTC+12/+13",
    "America/Sao_Paulo": "UTC-3", "America/Mexico_City": "UTC-6/-5",
    "Asia/Dubai": "UTC+4", "Asia/Riyadh": "UTC+3",
    "Asia/Jerusalem": "UTC+2/+3", "Africa/Johannesburg": "UTC+2",
    "Europe/Moscow": "UTC+3", "Europe/Luxembourg": "UTC+1/+2",
}


def _get_timezone(country: str) -> str | None:
    """Guess timezone from country code. Returns IANA timezone string."""
    if not country:
        return None
    code = country.strip().upper()
    if len(code) > 2:
        for k, v in COUNTRY_TZ.items():
            if k.lower() in code.lower():
                return v
        return None
    return COUNTRY_TZ.get(code)


def _company_main_ids(rows):
    """按公司去重：优先决策人，其次公共邮箱，最后最早创建；返回主记录 id 集合。"""
    def _rank(p):
        if p.decision_maker:
            return 3
        em = (p.email or "").lower()
        if "info@" in em or "einkauf@" in em or "purchase" in em:
            return 2
        return 1
    by_company = {}
    for p in rows:
        comp = (p.company or "").strip()
        if not comp:
            continue
        cur = by_company.get(comp)
        if cur is None or _rank(p) > _rank(cur) or (_rank(p) == _rank(cur) and p.id < cur.id):
            by_company[comp] = p
    return {p.id for p in by_company.values()}


# ── POST /api/prospects/import ──────────────────────
@router.post("/import", response_model=ImportResult)
async def import_prospects(payload: dict, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    customers = payload.get("customers", [])
    imported = 0
    skipped = 0
    errors: list[str] = []
    warnings: list[str] = []

    for idx, cust in enumerate(customers):
        try:
            company = (cust.get("company") or "").strip()
            email = (cust.get("email") or "").strip()
            if not company:
                errors.append(f"Row {idx + 1}: missing company name — skipped")
                skipped += 1
                continue
            existing = _find_duplicate_prospect(db, company, email, cust.get("contact"))
            if existing:
                skipped += 1
                warnings.append(
                f"Row {idx + 1}: same company & contact already exists - {existing.company} / "
                f"{existing.contact or '(no contact)'} ({existing.email or 'no email'}) - skipped"
                )
                continue
            tz = cust.get("timezone")
            if not tz:
                if cust.get("country"):
                    tz = _get_timezone(cust.get("country"))
                if not tz:
                    tz = "Asia/Shanghai"
                if not tz:
                    tz = "Asia/Shanghai"
            prospect = Prospect(
                contact=cust.get("contact"),
                company=company,
                website=cust.get("website"),
                title=cust.get("title"),
                country=cust.get("country"),
                size=cust.get("size"),
                industry=cust.get("industry"),
                phone=cust.get("phone"),
                email=email,
                linkedin=cust.get("linkedin"),
                note=cust.get("note"),
                source=cust.get("source"),
                source_channel=cust.get("source_channel") or cust.get("source"),
                development_batch=cust.get("development_batch") or cust.get("batch"),
                first_touch_channel=cust.get("first_touch_channel"),
                duplicate_checked=1 if cust.get("duplicate_checked") else 0,
                timezone=tz,
                parent_company=cust.get("parent_company"),
                decision_maker=cust.get("decision_maker") or cust.get("dm_name"),
                dm_title=cust.get("dm_title"),
                dm_linkedin=cust.get("dm_linkedin"),
                dm_email=cust.get("dm_email"),
                status=cust.get("status") or "New",
                sales_stage=cust.get("sales_stage") or "new",
            )
            db.add(prospect)
            imported += 1
        except Exception as exc:
            errors.append(f"Row {idx + 1}: {str(exc)}")
            skipped += 1

    db.commit()
    logger.info("Import complete — imported %d, skipped %d", imported, skipped)
    from services.auth_service import log_audit
    log_audit(db, user, "import_prospects", None, f"Imported customers {imported} (skipped {skipped})")
    return ImportResult(imported=imported, skipped=skipped, errors=errors, warnings=warnings)


# ── POST /api/prospects/import-show-list ──────────────────────
@router.post("/import-show-list", response_model=ImportResult)
async def import_show_list(payload: dict, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    """Import from trade show exhibitor CSV, with auto-scoring triggered.
    Same dedup logic as /import but also runs AI scoring on new entries."""
    customers = payload.get("customers", [])
    source = payload.get("source", "Trade Show")
    auto_score = payload.get("auto_score", True)

    imported = 0
    skipped = 0
    errors: list[str] = []
    warnings: list[str] = []
    scored_ids: list[int] = []

    for idx, cust in enumerate(customers):
        try:
            company = (cust.get("company") or "").strip()
            website = (cust.get("website") or "").strip()
            email = (cust.get("email") or "").strip()
            if not company and not website:
                errors.append(f"Row {idx + 1}: no company or website — skipped")
                skipped += 1
                continue
            if email and not re.match(r"^[^@\s]+@[^@\s]+\.[^@\s]+$", email):
                errors.append(f"Row {idx + 1}: Invalid email format: {email[:60]} — skipped")
                skipped += 1
                continue

            # 同公司不同的人不算重复；只有同邮箱或同公司+同联系人才跳过
            existing = _find_duplicate_prospect(db, company, email, cust.get("contact"))
            if existing:
                skipped += 1
                warnings.append(
                f"Row {idx + 1}: same company & contact already exists - {existing.company} / "
                f"{existing.contact or '(no contact)'} ({existing.email or 'no email'}) - skipped"
                )
                continue

            tz = _get_timezone(cust.get("country", "")) or "UTC"

            prospect = Prospect(
                company=company,
                website=website,
                country=cust.get("country"),
                email=email,
                contact=cust.get("contact"),
                title=cust.get("title"),
                industry=cust.get("industry"),
                phone=cust.get("phone"),
                linkedin=cust.get("linkedin"),
                size=cust.get("size"),
                note=(cust.get("note") or "").strip() or f"[Trade show import] {source}",
                source=source,
                source_channel=(cust.get("source_channel") or "").strip() or "Trade Show",
                development_batch=(cust.get("development_batch") or "").strip() or source,
                first_touch_channel="Email",
                timezone=tz,
                status=(cust.get("status") or "").strip() or "New",
                sales_stage=(cust.get("sales_stage") or "").strip() or "new",
                decision_maker=cust.get("decision_maker"),
                dm_title=cust.get("dm_title"),
                dm_email=cust.get("dm_email"),
                dm_linkedin=cust.get("dm_linkedin"),
            )
            db.add(prospect)
            db.flush()  # Get the ID
            imported += 1
            scored_ids.append(prospect.id)
        except Exception as exc:
            errors.append(f"Row {idx + 1}: {str(exc)}")
            skipped += 1

    db.commit()

    # ── Auto-score newly imported prospects ──
    scored = 0
    if auto_score and scored_ids:
        logger.info("Auto-scoring %d new prospects from show import...", len(scored_ids))
        try:
            from routers.ai import score_prospect
            from routers.ai import scrape_prospect_website
            from routers.ai import analyze_intelligence

            for pid in scored_ids:
                try:
                    # Step 1: scrape website if available
                    p = db.query(Prospect).filter(Prospect.id == pid).first()
                    if p and p.website:
                        try:
                            await scrape_prospect_website(pid, db)
                        except Exception:
                            logger.warning("Scrape failed for #%d, continuing with scoring", pid)
                    # Step 2: AI intelligence analysis
                    try:
                        await analyze_intelligence(pid, db)
                    except Exception:
                        logger.warning("Intel analysis failed for #%d", pid)
                    # Step 3: AI scoring
                    await score_prospect(pid, db)
                    scored += 1
                except Exception as e:
                    logger.warning("Auto-score failed for #%d: %s", pid, str(e)[:100])
            logger.info("Auto-scored %d/%d prospects", scored, len(scored_ids))
        except Exception as e:
            logger.warning("Auto-score batch failed: %s", e)

    from services.auth_service import log_audit
    log_audit(db, user, "import_prospects", None, f"Imported customers {imported} (skipped {skipped})")
    return ImportResult(imported=imported, skipped=skipped, errors=errors, scored=scored, warnings=warnings)


# ── GET /api/prospects ──────────────────────────────
@router.get("", response_model=ProspectListOut)
async def list_prospects(
    profile_type: Optional[str] = Query(None),
    profile_source: Optional[str] = Query(None),
    value_level: Optional[str] = Query(None),
    status: Optional[str] = Query(None),
    sales_stage: Optional[str] = Query(None),
    source: Optional[str] = Query(None),
    source_channel: Optional[str] = Query(None),
    development_batch: Optional[str] = Query(None),
    country: Optional[str] = Query(None),
    region: Optional[str] = Query(None),
    search: Optional[str] = Query(None),
    page: int = Query(1, ge=1),
    limit: int = Query(20, ge=1, le=200),
    sort: str = Query("created_at"),
    order: str = Query("desc"),
    mine: Optional[bool] = Query(False),
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """Paginated prospect list with FTS5 search and filters."""
    q = db.query(Prospect).filter(Prospect.is_deleted == 0)
    q = _scope_query(q, user, mine)

    if search and search.strip():
        search_term = search.strip()
        search_term = search_term.replace('"', '""')
        # For email searches, FTS5 tokenizer splits on @/. so phrase match fails.
        # Skip FTS entirely — use LIKE on email/dm_email columns directly.
        if "@" in search_term:
            q = q.filter(
                Prospect.email.contains(search_term) | Prospect.dm_email.contains(search_term)
            )
        else:
            fts_query = " OR ".join(f'"{w}"*' for w in search_term.split() if w)
            if fts_query:
                db_path = DATABASE_URL.replace("sqlite:///", "")
                try:
                    conn = sqlite3.connect(db_path)
                    cur = conn.execute(
                        f'SELECT rowid FROM prospects_fts WHERE prospects_fts MATCH ? ORDER BY rank LIMIT 5000',
                        (fts_query,)
                    )
                    fts_ids = [row[0] for row in cur.fetchall()]
                    conn.close()
                    if fts_ids:
                        q = q.filter(Prospect.id.in_(fts_ids))
                    else:
                        q = q.filter(Prospect.id == -1)
                except Exception:
                    q = q.filter(
                        Prospect.company.contains(search) | Prospect.contact.contains(search)
                    )

    if profile_type:
        q = q.filter(Prospect.profile_type == profile_type)
    if profile_source:
        q = q.filter(Prospect.profile_source == profile_source)
    if value_level:
        q = q.filter(Prospect.value_level == value_level)
    if status:
        q = q.filter(Prospect.status == status)
    if sales_stage:
        if sales_stage == "__follow__":
            today_str = datetime.now().strftime("%Y-%m-%d")
            q = q.filter(
                Prospect.next_follow_date.isnot(None),
                Prospect.next_follow_date <= today_str,
                ~Prospect.sales_stage.in_(["won", "lost", "cooling"]),
            )
        elif sales_stage == "__bounce__":
            q = q.filter(Prospect.email_status == "bounced")
        elif sales_stage == "__sample__":
            q = q.filter(Prospect.sales_stage.in_(["sample_pending", "sample_sent", "testing", "feedback"]))
        elif sales_stage == "__replied__":
            q = q.filter(Prospect.sales_stage.in_(["replied", "interested"]))
        elif sales_stage == "__all__":
            pass
        elif sales_stage == "__today__":
            today_str = datetime.now().strftime("%Y-%m-%d")
            q = q.filter(func.date(Prospect.created_at) == today_str)
        elif sales_stage == "__drafts__":
            # 草稿待发：有draft/pending的EmailQueue但无互动记录且无已发送邮件
            sub_all = [p.id for p in db.query(Prospect).filter(Prospect.is_deleted == 0, ~Prospect.sales_stage.in_(["won", "lost", "cooling"])).all()]
            if sub_all:
                from models import EmailQueue
                draft_ids = set(row[0] for row in db.query(EmailQueue.prospect_id).filter(EmailQueue.prospect_id.in_(sub_all), EmailQueue.status.in_(["draft", "pending"])).distinct().all())
                sent_ids = set(row[0] for row in db.query(EmailQueue.prospect_id).filter(EmailQueue.prospect_id.in_(sub_all), EmailQueue.status == "sent").distinct().all())
                int_ids = set(row[0] for row in db.query(Interaction.prospect_id).filter(Interaction.prospect_id.in_(sub_all)).distinct().all())
                result_ids = [pid for pid in sub_all if pid in draft_ids and pid not in int_ids and pid not in sent_ids]
                if result_ids:
                    q = q.filter(Prospect.id.in_(result_ids))
                else:
                    q = q.filter(Prospect.id == -1)
            else:
                q = q.filter(Prospect.id == -1)
        elif sales_stage == "__waiting__":
            # 待开发：zero interactions AND zero SENT emails (草稿不算触达)，排除已结束/冷却
            sub_all = [p.id for p in db.query(Prospect).filter(Prospect.is_deleted == 0, ~Prospect.sales_stage.in_(["won", "lost", "cooling"])).all()]
            if sub_all:
                int_ids = set(row[0] for row in db.query(Interaction.prospect_id).filter(Interaction.prospect_id.in_(sub_all)).distinct().all())
                from models import EmailQueue
                eq_sent_ids = set(row[0] for row in db.query(EmailQueue.prospect_id).filter(EmailQueue.prospect_id.in_(sub_all), EmailQueue.status == "sent").distinct().all())
                touched_ids = int_ids | eq_sent_ids
                waiting_ids = [pid for pid in sub_all if pid not in touched_ids]
                if waiting_ids:
                    # 非Hiring signal排前面，然后按评分降序
                    q = q.filter(Prospect.id.in_(waiting_ids))
                    # Use raw CASE: source='Hiring signal' goes to bottom
                    q = q.order_by(
                        case((Prospect.source == "Hiring signal", 1), else_=0).asc(),
                        Prospect.ai_score.desc().nullslast()
                    )
                else:
                    q = q.filter(Prospect.id == -1)
            else:
                q = q.filter(Prospect.id == -1)
        elif sales_stage == "__following__":
            sub_all = [p.id for p in db.query(Prospect).filter(Prospect.is_deleted == 0, ~Prospect.sales_stage.in_(["won", "lost", "cooling"])).all()]
            if sub_all:
                int_ids = set(row[0] for row in db.query(Interaction.prospect_id).filter(Interaction.prospect_id.in_(sub_all)).distinct().all())
                following_ids = [pid for pid in sub_all if pid in int_ids]
                if following_ids:
                    q = q.filter(Prospect.id.in_(following_ids))
                else:
                    q = q.filter(Prospect.id == -1)
            else:
                q = q.filter(Prospect.id == -1)
        elif sales_stage == "__need_nfd__":
            # 有互动但没设下次跟进日期，且非退信
            sub_all = [p.id for p in db.query(Prospect).filter(Prospect.is_deleted == 0, ~Prospect.sales_stage.in_(["won", "lost", "cooling"]), Prospect.email_status != "bounced").all()]
            if sub_all:
                int_ids = set(row[0] for row in db.query(Interaction.prospect_id).filter(Interaction.prospect_id.in_(sub_all)).distinct().all())
                nfd_ids = set(row[0] for row in db.query(Prospect.id).filter(Prospect.id.in_(sub_all), Prospect.next_follow_date.isnot(None), Prospect.next_follow_date != "").all())
                need_nfd = [pid for pid in sub_all if pid in int_ids and pid not in nfd_ids]
                if need_nfd:
                    q = q.filter(Prospect.id.in_(need_nfd))
                else:
                    q = q.filter(Prospect.id == -1)
            else:
                q = q.filter(Prospect.id == -1)
        elif sales_stage == "__recent__":
            from datetime import timedelta
            cutoff = (datetime.now() - timedelta(days=30)).strftime("%Y-%m-%d")
            q = q.filter(
                ~Prospect.sales_stage.in_(["won", "lost", "cooling"]),
                Prospect.last_edited_at >= cutoff
            )
        elif sales_stage == "__cooling__":
            from datetime import timedelta
            cutoff = (datetime.now() - timedelta(days=30))
            manual_cooling = [p.id for p in db.query(Prospect).filter(Prospect.is_deleted == 0, Prospect.sales_stage == "cooling").all()]
            sub_all = [p.id for p in db.query(Prospect).filter(Prospect.is_deleted == 0, ~Prospect.sales_stage.in_(["won", "lost", "cooling"])).all()]
            auto_cooling = []
            if sub_all:
                from sqlalchemy import func as _f2
                last_int = dict(
                    db.query(Interaction.prospect_id, _f2.max(Interaction.interacted_at))
                    .filter(Interaction.prospect_id.in_(sub_all))
                    .group_by(Interaction.prospect_id)
                    .all()
                )
                for pid in sub_all:
                    dt = last_int.get(pid)
                    if not dt: continue
                    try:
                        if dt.tzinfo is not None:
                            days_since = (datetime.now(dt.tzinfo) - dt).days
                        else:
                            days_since = (datetime.now() - dt).days
                        if days_since > 30:
                            auto_cooling.append(pid)
                    except Exception:
                        continue
            all_cooling = list(set(manual_cooling + auto_cooling))
            if all_cooling:
                q = q.filter(Prospect.id.in_(all_cooling))
            else:
                q = q.filter(Prospect.id == -1)
        else:
            q = q.filter(Prospect.sales_stage == sales_stage)
    if source:
        q = q.filter(Prospect.source == source)
    if source_channel:
        q = q.filter(Prospect.source_channel == source_channel)
    if development_batch:
        q = q.filter(Prospect.development_batch == development_batch)
    if country:
        q = q.filter(Prospect.country == country)
    if region:
        from sqlalchemy import or_
        from services.regions import ALL_KNOWN_COUNTRIES, region_countries
        region = region.strip().lower()
        if region == "other":
            q = q.filter(
                or_(
                    Prospect.country.is_(None),
                    Prospect.country == "",
                    ~Prospect.country.in_(ALL_KNOWN_COUNTRIES),
                )
            )
        else:
            countries = region_countries(region)
            if countries:
                q = q.filter(Prospect.country.in_(countries))

    if sales_stage == "__waiting__":
        # 排序已在 filter 段设置（非招聘优先 → 评分降序)，这里只做分页
        offset = (page - 1) * limit
        items = q.offset(offset).limit(limit).all()
        total = q.count()
    elif sales_stage == "__following__":
        # Following up：按下次跟进日期排序（最近的在前)
        q = q.order_by(Prospect.next_follow_date.asc())
        offset = (page - 1) * limit
        items = q.offset(offset).limit(limit).all()
        total = q.count()
    else:
        if sort == "last_sent":
            # 按最近发信时间排序（最新在前)，用于“已发开发信”池
            from models import EmailQueue
            last_sent = (
                db.query(EmailQueue.prospect_id,
                         func.max(EmailQueue.sent_at).label("max_sent"))
                .filter(EmailQueue.status == "sent")
                .group_by(EmailQueue.prospect_id)
                .subquery()
            )
            q = q.outerjoin(last_sent, last_sent.c.prospect_id == Prospect.id)
            if order == "asc":
                q = q.order_by(last_sent.c.max_sent.asc().nulls_last())
            else:
                q = q.order_by(last_sent.c.max_sent.desc().nulls_last())
        else:
            # 「最近修改」池默认按最近修改时间倒序，避免新改的客户沉底
            if sales_stage == "__recent__" and sort in ("created_at", ""):
                order_col = Prospect.last_edited_at
            else:
                order_col = getattr(Prospect, sort, Prospect.created_at)
            if order == "asc":
                q = q.order_by(order_col.asc())
            else:
                q = q.order_by(order_col.desc())
        offset = (page - 1) * limit
        items = q.offset(offset).limit(limit).all()
        total = q.count()

    if items:
        item_ids = [p.id for p in items]
        int_counts = dict(
            db.query(Interaction.prospect_id, func.count(Interaction.id))
            .filter(Interaction.prospect_id.in_(item_ids))
            .group_by(Interaction.prospect_id)
            .all()
        )
        for p in items:
            p.interaction_count = int_counts.get(p.id, 0)

    return ProspectListOut(
        items=[ProspectOut.model_validate(p) for p in items],
        total=total,
        page=page,
        limit=limit,
    )


# ── GET /api/prospects/stats ─────────────────────────────

@router.get("/stats")
async def prospect_stats(db: Session = Depends(get_db)):
    """Return overview counts for the list page header."""
    all_p = db.query(Prospect).filter(Prospect.is_deleted == 0).all()
    main_ids = _company_main_ids(all_p)
    company_rows = {}
    for p in all_p:
        comp = (p.company or "").strip()
        if comp:
            company_rows.setdefault(comp, []).append(p)

    main_p = [p for p in all_p if p.id in main_ids]

    def _rows(p):
        comp = (p.company or "").strip()
        return company_rows.get(comp, [p]) if comp else [p]

    def _company_stage(p):
        for r in _rows(p):
            st = (r.sales_stage or "new")
            if st != "new":
                return st
        return (p.sales_stage or "new")

    def count(stage): return len([p for p in main_p if _company_stage(p) == stage])

    today_str = datetime.now().strftime("%Y-%m-%d")
    need_follow = [
        p for p in all_p
        if p.id in main_ids
        and any(
            (r.next_follow_date or "").strip() and r.next_follow_date[:10] <= today_str
            for r in _rows(p)
        )
        and _company_stage(p) not in ("won", "lost", "cooling")
    ]
    today_new = 0
    for p in main_p:
        try:
            created_dates = [r.created_at for r in _rows(p) if r.created_at]
            if created_dates and min(created_dates).strftime("%Y-%m-%d") == today_str:
                today_new += 1
        except Exception:
            pass

    interaction_counts = dict(
        db.query(Interaction.prospect_id, func.count(Interaction.id))
        .filter(Interaction.prospect_id.in_([p.id for p in all_p]))
        .group_by(Interaction.prospect_id)
        .all()
    )
    from sqlalchemy import func as _f
    last_int_dates = dict(
        db.query(Interaction.prospect_id, _f.max(Interaction.interacted_at))
        .filter(Interaction.prospect_id.in_([p.id for p in all_p]))
        .group_by(Interaction.prospect_id)
        .all()
    )
    def _last_int_days(p):
        dt = last_int_dates.get(p.id)
        if not dt: return 999
        try:
            if dt.tzinfo is not None:
                return (datetime.now(dt.tzinfo) - dt).days
            else:
                return (datetime.now() - dt).days
        except Exception:
            return 999

    from models import EmailQueue
    eq_counts = dict(
        db.query(EmailQueue.prospect_id, func.count(EmailQueue.id))
        .filter(EmailQueue.prospect_id.in_([p.id for p in all_p]), EmailQueue.status == "sent")
        .group_by(EmailQueue.prospect_id)
        .all()
    )
    eq_draft_counts = dict(
        db.query(EmailQueue.prospect_id, func.count(EmailQueue.id))
        .filter(EmailQueue.prospect_id.in_([p.id for p in all_p]), EmailQueue.status.in_(["draft", "pending"]))
        .group_by(EmailQueue.prospect_id)
        .all()
    )

    pool_waiting = 0
    pool_following = 0
    pool_today_new = 0
    pool_need_nfd = 0
    pool_drafts = 0
    for p in all_p:
        if p.id not in main_ids:
            continue
        rows = _rows(p)
        ic = sum(interaction_counts.get(r.id, 0) for r in rows)
        ec = sum(eq_counts.get(r.id, 0) for r in rows)
        dc = sum(eq_draft_counts.get(r.id, 0) for r in rows)
        has_touch = ic > 0 or ec > 0
        if not has_touch and _company_stage(p) not in ("won", "lost", "cooling"):
            pool_waiting += 1
            try:
                created_dates = [r.created_at for r in rows if r.created_at]
                if created_dates and min(created_dates).strftime("%Y-%m-%d") == today_str:
                    pool_today_new += 1
            except Exception:
                pass
        if ic > 0:
            if _company_stage(p) not in ("won", "lost", "cooling"):
                pool_following += 1
        # 草稿待发：有EQ草稿但无互动且未真正发送过
        if dc > 0 and ic == 0 and ec == 0:
            if _company_stage(p) not in ("won", "lost", "cooling"):
                pool_drafts += 1
        # 缺下次跟进日期：有互动但没设 nfd，且非退信
        if ic > 0 and not any((r.next_follow_date or "").strip() for r in rows):
            if _company_stage(p) not in ("won", "lost", "cooling") and not any(r.email_status == "bounced" for r in rows):
                pool_need_nfd += 1

    return {
        "total": len(main_p),
        "new": count("new"),
        "today_new": today_new,
        "touched": count("touched"),
        "connected": count("connected"),
        "replied": count("replied"),
        "interested": count("interested"),
        "sample_active": count("sample_pending") + count("sample_sent") + count("testing") + count("feedback"),
        "trial": count("trial_order"),
        "won": count("won"),
        "lost": count("lost"),
        "need_follow": len(need_follow),
        "bounced": len([p for p in main_p if any(r.email_status == "bounced" for r in _rows(p))]),
        "recent_modified": len([p for p in main_p if _company_stage(p) not in ("won", "lost", "cooling") and any(r.last_edited_at and (datetime.now() - r.last_edited_at).days <= 30 for r in _rows(p))]),
        "cooling": len([p for p in main_p if _company_stage(p) == "cooling" or (any(interaction_counts.get(r.id, 0) > 0 for r in _rows(p)) and min((_last_int_days(r) for r in _rows(p)), default=999) > 30 and _company_stage(p) not in ("won", "lost", "cooling"))]),
        "pool_waiting": pool_waiting,
        "pool_following": pool_following,
        "source_breakdown": {s: c for s, c in db.query(Prospect.source, func.count(Prospect.id)).filter(Prospect.is_deleted == 0, Prospect.source is not None, Prospect.source != "").group_by(Prospect.source).all() if s},
        "pool_today_new": pool_today_new,
        "pool_need_nfd": pool_need_nfd,
        "pool_drafts": pool_drafts,
    }




# ── GET /api/prospects/daily-plan ────────────────────────
# Insert between the /stats endpoint return and /reminders

@router.get("/daily-plan")
async def get_daily_plan(db: Session = Depends(get_db)):
    """Return today's task plan: overdue follow-ups, due today, and 3 new outreach targets."""
    today_str = datetime.now().strftime("%Y-%m-%d")
    all_p = db.query(Prospect).filter(Prospect.is_deleted == 0).all()
    all_ids = [p.id for p in all_p]
    main_ids = _company_main_ids(all_p)
    company_rows = {}
    for p in all_p:
        comp = (p.company or "").strip()
        if comp:
            company_rows.setdefault(comp, []).append(p)

    # 公司级跟进：同一家公司任何人到期都算公司到期，取最早日期。
    company_min_nfd = {}
    for comp, rows in company_rows.items():
        dates = [
            str(r.next_follow_date or "").strip()[:10]
            for r in rows
            if r.is_deleted == 0 and (r.next_follow_date or "").strip()
        ]
        dates = [d for d in dates if re.match(r"^\d{4}-\d{2}-\d{2}$", d)]
        if dates:
            company_min_nfd[comp] = min(dates)

    int_counts = dict(db.query(Interaction.prospect_id, func.count(Interaction.id))
        .filter(Interaction.prospect_id.in_(all_ids)).group_by(Interaction.prospect_id).all())
    outbound_map = dict(db.query(Interaction.prospect_id, func.count(Interaction.id))
        .filter(Interaction.prospect_id.in_(all_ids), Interaction.direction == "outbound").group_by(Interaction.prospect_id).all())
    inbound_map = dict(db.query(Interaction.prospect_id, func.count(Interaction.id))
        .filter(Interaction.prospect_id.in_(all_ids), Interaction.direction == "inbound").group_by(Interaction.prospect_id).all())
    from models import EmailQueue, Sequence
    eq_ids = set(row[0] for row in db.query(EmailQueue.prospect_id)
        .filter(EmailQueue.prospect_id.in_(all_ids), EmailQueue.status == "draft").distinct().all())
    seq_ids = set(row[0] for row in db.query(Sequence.prospect_id)
        .filter(Sequence.prospect_id.in_(all_ids)).distinct().all())
    eq_sent_ids = set(row[0] for row in db.query(EmailQueue.prospect_id)
        .filter(EmailQueue.prospect_id.in_(all_ids), EmailQueue.status == "sent").distinct().all())

    def _is_fresh(p):
        """True if this prospect has never been touched — no interactions, no sequences, no SENT emails, no follow-up date."""
        comp = (p.company or "").strip()
        rows = company_rows.get(comp, [p]) if comp else [p]
        for r in rows:
            ss = r.sales_stage or ""
            if ss not in ("", "new", "unknown"):
                return False
            if int_counts.get(r.id, 0) > 0:
                return False
            if (r.next_follow_date or "").strip():
                return False
            if r.id in seq_ids:
                return False
            if r.id in eq_sent_ids:
                return False
        return True

    def _mk_item(p):
        comp = (p.company or "").strip()
        rows = company_rows.get(comp, [p]) if comp else [p]
        min_nfd = company_min_nfd.get(comp)
        reason = ""
        if comp and min_nfd:
            for r in rows:
                if str(r.next_follow_date or "").strip()[:10] == min_nfd:
                    reason = r.next_follow_reason or ""
                    break
        return {
            "id": p.id, "company": p.company or "", "contact": p.contact or "",
            "country": p.country or "", "sales_stage": p.sales_stage or "new",
            "first_touch_channel": p.first_touch_channel or "email",
            "outbound_count": sum(outbound_map.get(r.id, 0) for r in rows),
            "inbound_count": sum(inbound_map.get(r.id, 0) for r in rows),
            "value_level": p.value_level or "",
            "profile_type": p.profile_type or "",
            "overdue_days": 0,
            "next_follow_date": company_min_nfd.get(comp, p.next_follow_date or ""),
            "next_follow_reason": reason or (p.next_follow_reason or ""),
        }

    overdue = []
    due_today = []
    # upcoming: next 30 days by date — dict of {date_str: [items]}
    upcoming = {}
    today_dt = datetime.now().replace(hour=0, minute=0, second=0, microsecond=0)
    for p in all_p:
        if (p.company or "").strip() and p.id not in main_ids:
            continue
        # 与客户列表口径统一：冷却客户不进每日跟进（有独立“冷却复审”区)
        if (p.sales_stage or "new") in ("won", "lost", "cooling"):
            continue
        nfd = (p.next_follow_date or "").strip()
        comp = (p.company or "").strip()
        if comp and comp in company_min_nfd:
            nfd = company_min_nfd[comp]
        if not nfd:
            # 未接触过的新客户 → 留在等待开发池（每 days由"今日新开发"抽 3 个)，
            # 不按"今 days到期"计入，避免与"今日新开发"重复。
            if _is_fresh(p):
                continue
            # 已接触过但漏设跟进日期的 → 兜底按今 days到期进计划，防止漏跟。
            nfd = today_str
        item = _mk_item(p)
        try:
            nfd_dt = datetime.strptime(nfd[:10], "%Y-%m-%d")
        except Exception:
            continue
        days_until = (nfd_dt - today_dt).days
        item["is_cooling"] = (p.sales_stage == "cooling")
        item["is_bounced"] = (p.email_status == "bounced")
        if days_until < 0:
            item["overdue_days"] = -days_until
            overdue.append(item)
        elif days_until == 0:
            due_today.append(item)
        else:
            item["days_until"] = days_until
            item["nfd_date"] = nfd[:10]
            date_key = nfd[:10]
            if date_key not in upcoming:
                upcoming[date_key] = []
            upcoming[date_key].append(item)

    overdue.sort(key=lambda x: -(x.get("overdue_days", 0)))
    due_today.sort(key=lambda x: x.get("next_follow_date", ""))
    # 冷却客户单独列出（不算进 今日/逾期 数字，但工作台可见，便于复审)
    cooling_due = []
    for p in all_p:
        if (p.company or "").strip() and p.id not in main_ids:
            continue
        if (p.sales_stage or "new") != "cooling":
            continue
        nfd = (p.next_follow_date or "").strip()
        try:
            nfd_dt = datetime.strptime(nfd[:10], "%Y-%m-%d")
        except Exception:
            continue
        cadence = 15
        days_since = (today_dt - nfd_dt).days
        if days_since < 0 or days_since % cadence != 0:
            continue  # 非复审日不刷，冷却客户不每日提醒
        item = _mk_item(p)
        item["is_cooling"] = True
        item["overdue_days"] = days_since
        item["next_follow_date"] = nfd[:10]
        cooling_due.append(item)
    cooling_due.sort(key=lambda x: -x.get("overdue_days", 0))
    # sort upcoming keys, keep as ordered dict for frontend
    upcoming_sorted = [{"date": k, "days_until": (datetime.strptime(k, "%Y-%m-%d") - today_dt).days, "items": v} for k, v in sorted(upcoming.items())]

    # New outreach: 3 per day from German trade-show prospects, cleared daily.
    # Stale locks from previous days are released so every day starts with a
    # fresh pool; developed prospects leave the pool through _is_fresh().

    def _to_item(p):
        return {
            "id": p.id, "company": p.company or "", "contact": p.contact or "",
            "country": p.country or "", "value_level": p.value_level or "",
            "profile_type": p.profile_type or "", "ai_score": p.ai_score or 0,
            "industry": p.industry or "", "size": p.size or "",
            "linkedin": p.linkedin or "", "email": p.email or "",
            "note": p.note or "",
            "has_draft": p.id in eq_ids,
            "first_touch_channel": p.first_touch_channel or "email",
        }

    # 已开发过的（有计划/已接触/有排期)自动释放今日锁，不再进“今日新开发”
    stale_locked = [p for p in all_p if (p.new_outreach_date or "").strip() == today_str and not _is_fresh(p)]
    for p in stale_locked:
        p.new_outreach_date = ""
        db.add(p)
    if stale_locked:
        db.commit()

    # Step 1: already locked for today — keep only still-fresh prospects, exclude Hiring signal
    locked = [p for p in all_p
              if (p.new_outreach_date or "").strip() == today_str
              and _is_fresh(p)
              and (p.source or "") != "Hiring signal"]
    locked.sort(key=lambda p: -((p.ai_score or 0) + (200 if (p.profile_type or "") == "A" else 0) + (1000 if (p.value_level or "") == "HIGH" else 0)))
    new_outreach = [_to_item(p) for p in locked[:3]]

    # Also unmark Hiring signal that were locked
    hiring_locked = [p for p in all_p if (p.new_outreach_date or "").strip() == today_str and (p.source or "") == "Hiring signal"]
    for p in hiring_locked:
        p.new_outreach_date = ""
        db.add(p)

    # Step 2: fill remaining slots from fresh pool — EXCLUDE Hiring signal, never fallback
    need = 3 - len(new_outreach)
    if need > 0:
        locked_ids = {p.id for p in locked}
        pool = [p for p in all_p if _is_fresh(p) and p.id not in locked_ids and (p.source or "") != "Hiring signal"]
        # Rank: HIGH value > A profile > high ai_score
        def _rank_p(p):
            s = 0
            if (p.value_level or "") == "HIGH":
                s += 1000
            s += p.ai_score or 0
            if (p.profile_type or "") == "A":
                s += 200
            return -s
        pool.sort(key=_rank_p)
        for p in pool[:need]:
            p.new_outreach_date = today_str
            db.add(p)
            new_outreach.append(_to_item(p))
        if need > 0 and pool:
            db.commit()
    if hiring_locked:
        db.commit()

    return {
        "today_date": today_str,
        "overdue_count": len(overdue),
        "due_today_count": len(due_today),
        "upcoming_dates": len(upcoming_sorted),
        "new_outreach_count": len(new_outreach),
        "cooling_due_count": len(cooling_due),
        "overdue": overdue,
        "due_today": due_today,
        "upcoming": upcoming_sorted,
        "new_outreach": new_outreach,
        "cooling_due": cooling_due,
    }

# ── GET /api/prospects/reminders ────────────────────────

@router.get("/reminders")
async def get_reminders(db: Session = Depends(get_db)):
    """Return all non-deleted prospects that have a next_follow_date set.
    Cooling customers are returned separately so the frontend can render
    them in their own review zone."""
    try:
        results = (
            db.query(Prospect)
            .filter(
                Prospect.is_deleted == 0,
                Prospect.next_follow_date.isnot(None),
                Prospect.next_follow_date != "",
            )
            .order_by(Prospect.next_follow_date.asc())
            .all()
        )

        # 同一家公司只保留主记录进跟进任务，避免同一公司多人重复跳出
        def _main_rank(r):
            if r.decision_maker:
                return 3
            em = (r.email or "").lower()
            if "info@" in em or "einkauf@" in em or "purchase" in em:
                return 2
            return 1

        company_main = {}
        for p in results:
            comp = (p.company or "").strip()
            if not comp:
                continue
            if comp not in company_main:
                company_main[comp] = p
                continue
            cur = company_main[comp]
            if _main_rank(p) > _main_rank(cur) or (_main_rank(p) == _main_rank(cur) and p.id < cur.id):
                company_main[comp] = p
        main_ids = {p.id for p in company_main.values()}
        today_str = datetime.utcnow().strftime("%Y-%m-%d")
        items = []
        cooling_items = []
        # 真实样品事件才给“样品推进”权重，避免备注带“样品”二字就误判
        active_sample_ids = set()
        try:
            from models import SampleEvent
            active_sample_ids = set(
                r[0]
                for r in db.query(SampleEvent.prospect_id).filter(
                    SampleEvent.stage.in_(["requested", "sent", "received", "testing", "feedback"])
                ).all()
            )
        except Exception:
            pass
        for p in results:
            if (p.company or "").strip() and p.id not in main_ids:
                continue
            days_diff = None
            try:
                from datetime import date as _date
                rd = _date.fromisoformat(p.next_follow_date[:10])
                td = _date.fromisoformat(today_str)
                days_diff = (rd - td).days
            except (ValueError, TypeError):
                pass
            note = p.reminder_note or ""
            sample_active = p.id in active_sample_ids or (p.sample_status or "") in ("requested", "sent", "received", "testing", "feedback")
            sample_boost = 35 if sample_active else 0
            hot_boost = 25 if any(x in note for x in ("热回复", "样品", "报价", "地址", "试单", "hot reply", "sample", "quote", "address", "trial order")) else 0
            # 急：逾期/今 days/近期只占小头；重要：样品/热信号/高价值/AI高分占大头
            overdue_boost = 20 if days_diff is not None and days_diff < 0 else 0
            today_boost = 15 if days_diff == 0 else 0
            soon_boost = max(0, 10 - (days_diff or 0) * 2) if days_diff is not None and days_diff > 0 else 0
            score_boost = min(int(p.ai_score or 0), 20)
            value_boost = {"HIGH": 20, "MID": 10, "LOW": 5}.get((p.value_level or "").upper(), 0)
            priority_score = overdue_boost + today_boost + soon_boost + sample_boost + hot_boost + score_boost + value_boost
            priority_reason = []
            if sample_boost:
                priority_reason.append("Sample push")
            if hot_boost:
                priority_reason.append("Hot signal")
            if overdue_boost:
                priority_reason.append("Overdue")
            elif today_boost:
                priority_reason.append("Due today")
            elif soon_boost:
                priority_reason.append("Due soon")
            if (p.ai_score or 0) >= 75:
                priority_reason.append("High-score client")

            entry = {
                "id": p.id,
                "company": p.company,
                "country": p.country,
                "contact": p.contact,
                "status": p.status,
                "sales_stage": p.sales_stage,
                "next_follow_date": p.next_follow_date,
                "reminder_note": note,
                "days_until": days_diff,
                "ai_score": p.ai_score,
                "value_level": p.value_level,
                "profile_type": p.profile_type, "profile_source": p.profile_source or "ai",
                "sample_status": p.sample_status,
                "priority_score": priority_score,
                "priority_reason": " / ".join(priority_reason),
            }
            if (p.sales_stage or "") == "cooling":
                cooling_items.append(entry)
            else:
                items.append(entry)
        items.sort(key=lambda r: (-(r.get("priority_score") or 0), r.get("days_until") if r.get("days_until") is not None else 9999))
        top_actions = items[:10]
        cooling_items.sort(key=lambda r: r.get("days_until") if r.get("days_until") is not None else 9999)
        return {"success": True, "reminders": items, "cooling_reminders": cooling_items, "top_actions": top_actions, "total": len(items)}
    except Exception as exc:
        logger.exception("List reminders failed")
        return {"success": False, "error": str(exc)}


# ── GET /api/prospects/{id} ─────────────────────────
@router.get("/{prospect_id:int}", response_model=ProspectOut)
async def get_prospect(prospect_id: int, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    p = db.query(Prospect).filter(
        Prospect.id == prospect_id, Prospect.is_deleted == 0
    ).first()
    if not p:
        raise HTTPException(status_code=404, detail="Prospect not found")
    _ensure_visible(p, user)
    _record_view(db, user, p)
    p.interaction_count = db.query(func.count(Interaction.id)).filter(
        Interaction.prospect_id == prospect_id
    ).scalar() or 0
    return ProspectOut.model_validate(p)


# ── GET /api/prospects/{id}/colleagues ─────────────
@router.get("/{prospect_id}/colleagues")
async def get_colleagues(prospect_id: int, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    """同公司联系人：同一家公司多个人不算重复，按决策链线索归组显示。
    匹配规则：公司名相同（忽略大小写/空格)，或 parent_company 相同。"""
    p = db.query(Prospect).filter(
        Prospect.id == prospect_id, Prospect.is_deleted == 0
    ).first()
    if not p:
        raise HTTPException(status_code=404, detail="Prospect not found")
    _ensure_visible(p, user)

    company = (p.company or "").strip()
    parent = (p.parent_company or "").strip()
    if not company and not parent:
        return {"prospect_id": prospect_id, "company": p.company, "colleagues": []}

    conds = []
    if company:
        conds.append(func.lower(func.trim(Prospect.company)) == company.lower())
    if parent:
        conds.append(func.lower(func.trim(Prospect.parent_company)) == parent.lower())

    q = (
        db.query(Prospect)
        .filter(Prospect.is_deleted == 0, Prospect.id != prospect_id, or_(*conds))
        .order_by(func.coalesce(Prospect.ai_score, -1).desc(), Prospect.updated_at.desc())
        .limit(50)
    )
    colleagues = []
    for c in q.all():
        try:
            _ensure_visible(c, user)
        except HTTPException:
            continue
        colleagues.append({
            "id": c.id,
            "company": c.company,
            "contact": c.contact,
            "title": c.title,
            "decision_maker": c.decision_maker,
            "email": c.email,
            "phone": c.phone,
            "linkedin": c.linkedin,
            "linkedin_status": c.linkedin_status,
            "sales_stage": c.sales_stage,
            "status": c.status,
            "next_follow_date": c.next_follow_date,
            "source_channel": c.source_channel,
            "development_batch": c.development_batch,
            "ai_score": c.ai_score,
        })
    return {"prospect_id": prospect_id, "company": p.company, "colleagues": colleagues}


# ── PUT /api/prospects/{id} ─────────────────────────
@router.put("/{prospect_id}", response_model=ProspectOut)
async def update_prospect(
    prospect_id: int, data: ProspectUpdate, db: Session = Depends(get_db), user: User = Depends(get_current_user)
):
    p = db.query(Prospect).filter(
        Prospect.id == prospect_id, Prospect.is_deleted == 0
    ).first()
    if not p:
        raise HTTPException(status_code=404, detail="Prospect not found")
    _ensure_visible(p, user)

    _updates = data.model_dump(exclude_unset=True)
    # 手动跟进备注变化 → 自动沉淀为互动记录（历史可查，进客户详情/公司时间线)
    _old_note = str(p.reminder_note or "").strip()
    _new_note = str(_updates.get("reminder_note") or "").strip()
    if "reminder_note" in _updates and _new_note and _new_note != _old_note and not _new_note.startswith("["):
        db.add(Interaction(
            tenant_id=p.tenant_id,
            owner_user_id=user.id,
            prospect_id=p.id,
            direction="outbound",
            channel="note",
            content=_new_note,
            interacted_at=datetime.utcnow(),
        ))

    for key, val in _updates.items():
        setattr(p, key, val)
    # 状态进入 试单/成交/Lost/冷却 后，自动移出跟进任务（清空下次跟进日期)
    if "sales_stage" in data.model_dump(exclude_unset=True) and (p.sales_stage or "") in ("won", "lost", "trial_order", "cooling"):
        p.next_follow_date = None
    if "profile_type" in data.model_dump(exclude_unset=True):
        p.profile_source = "manual"
    if any(k in data.model_dump(exclude_unset=True)
            for k in ("profile_type", "value_level", "sales_stage")):
        p.profile_source = "manual"

    p.last_edited_at = datetime.utcnow()
    db.commit()
    db.refresh(p)
    from services.auth_service import log_audit
    log_audit(db, user, "update_prospect", f"prospect#{p.id}", p.company)
    return ProspectOut.model_validate(p)


# ── PUT /api/prospects/{id}/intent-signals ───────────────
INTENT_SIGNAL_TYPES = {"hiring", "trade_show", "import_change", "referral"}


@router.put("/{prospect_id}/intent-signals")
async def update_intent_signals(prospect_id: int, payload: dict,
                                db: Session = Depends(get_db),
                                user: User = Depends(get_current_user)):
    """Save manual intent signals (招聘扩产 / 展会接触 / 进口异动 / 老客户介绍).
    AI scoring reads these to prioritize — signals override profile-only matching."""
    p = db.query(Prospect).filter(
        Prospect.id == prospect_id, Prospect.is_deleted == 0
    ).first()
    if not p:
        raise HTTPException(status_code=404, detail="Customer not found")
    _ensure_visible(p, user)

    from datetime import date as _date
    signals = payload.get("signals") or []
    cleaned = []
    for s in signals:
        if not isinstance(s, dict):
            continue
        st = str(s.get("type") or "").strip()
        if st not in INTENT_SIGNAL_TYPES:
            continue
        note = str(s.get("note") or "").strip()
        at = str(s.get("at") or _date.today().isoformat())[:10]
        cleaned.append({"type": st, "note": note, "at": at})

    p.intent_signals = json.dumps(cleaned, ensure_ascii=False) if cleaned else ""
    p.last_edited_at = datetime.utcnow()
    db.commit()
    db.refresh(p)
    try:
        from services.auth_service import log_audit
        log_audit(db, user, "update_intent_signals", f"prospect#{p.id}",
                  f"Intent signals for {p.company}: {p.intent_signals[:120]}")
    except Exception:
        pass
    return ProspectOut.model_validate(p)


# ── 公司级跟进完成：谁当前到期就清谁的日期，公司自动切到下一 days ──
@router.post("/{prospect_id}/complete-followup")
async def complete_company_followup(prospect_id: int, payload: dict = None,
                                    db: Session = Depends(get_db),
                                    user: User = Depends(get_current_user)):
    p = db.query(Prospect).filter(
        Prospect.id == prospect_id, Prospect.is_deleted == 0
    ).first()
    if not p:
        raise HTTPException(status_code=404, detail="Customer not found")
    _ensure_visible(p, user)

    colleagues = db.query(Prospect).filter(
        Prospect.company == (p.company or "").strip(),
        Prospect.is_deleted == 0,
    ).all()
    all_rows = []
    seen = set()
    for r in [p] + colleagues:
        if r.id in seen:
            continue
        seen.add(r.id)
        all_rows.append(r)

    def _valid_dates(rows):
        out = []
        for r in rows:
            d = str(r.next_follow_date or "").strip()[:10]
            if re.match(r"^\d{4}-\d{2}-\d{2}$", d):
                out.append(d)
        return out

    dates = _valid_dates(all_rows)
    if not dates:
        return {"success": True, "updated": 0, "remaining_next_follow_date": ""}

    target = min(dates)
    updated = 0
    advance_days = 0
    if payload and isinstance(payload, dict):
        try:
            advance_days = int(payload.get("advance_days", 0) or 0)
        except Exception:
            advance_days = 0
    for r in all_rows:
        if str(r.next_follow_date or "").strip()[:10] == target:
            if advance_days > 0:
                from datetime import timedelta as _td
                nd = datetime.utcnow() + _td(days=advance_days)
                while nd.weekday() >= 5:
                    nd += _td(days=1)
                r.next_follow_date = nd.date().isoformat()
                r.reminder_note = "[Manual] Follow-up done"
                r.next_follow_reason = f"Follow-up done — next review in {advance_days} days"
            else:
                if (r.sales_stage or "") == "cooling":
                    from datetime import timedelta as _td2
                    cadence = 15
                    nd2 = datetime.utcnow() + _td2(days=cadence)
                    r.next_follow_date = nd2.date().isoformat()
                    r.reminder_note = f"[Auto] Cooling review complete; next review in {cadence} days"
                    r.next_follow_reason = f"Cooling review complete — next review in {cadence} days"
                else:
                    r.next_follow_date = ""
                    r.reminder_note = ""
                    r.next_follow_reason = ""
            r.last_edited_at = datetime.utcnow()
            updated += 1
    db.commit()

    remaining_dates = _valid_dates(all_rows)
    remaining = min(remaining_dates) if remaining_dates else ""
    return {
        "success": True,
        "updated": updated,
        "remaining_next_follow_date": remaining,
    }


# ── DELETE /api/prospects/{id} ─────────────────────────
@router.delete("/{prospect_id}")
async def delete_prospect(prospect_id: int, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    p = db.query(Prospect).filter(
        Prospect.id == prospect_id, Prospect.is_deleted == 0
    ).first()
    if not p:
        raise HTTPException(status_code=404, detail="Prospect not found")
    _ensure_visible(p, user)
    p.is_deleted = 1
    p.last_edited_at = datetime.utcnow()
    db.commit()
    from services.auth_service import log_audit
    log_audit(db, user, "delete_prospect", f"prospect#{p.id}", p.company)
    return {"success": True, "deleted_id": prospect_id}


# ── 客户分配（主账号/管理员 → 子账号，含离职交接)──
@router.post("/{prospect_id}/assign")
async def assign_prospect(prospect_id: int, payload: dict, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    if user.role not in ("owner", "admin"):
        raise HTTPException(status_code=403, detail="Only the owner/admin can assign customers")
    p = db.query(Prospect).filter(Prospect.id == prospect_id, Prospect.is_deleted == 0).first()
    if not p:
        raise HTTPException(status_code=404, detail="Customer not found")
    owner_id = payload.get("owner_user_id")
    if owner_id is not None:
        target = db.query(User).filter(
            User.id == int(owner_id),
            User.tenant_id == user.tenant_id,
            User.status == "active",
        ).first()
        if not target:
            raise HTTPException(status_code=400, detail="Target member not found or disabled")
    p.owner_user_id = int(owner_id) if owner_id is not None else None
    p.last_edited_at = datetime.utcnow()
    db.commit()
    from services.auth_service import log_audit
    log_audit(db, user, "assign_prospect", f"prospect#{p.id}", f"Assigned to member #{p.owner_user_id}" if p.owner_user_id else "Assignment removed")
    return {"ok": True, "prospect_id": prospect_id, "owner_user_id": p.owner_user_id}


@router.post("/assign-batch")
async def assign_batch_prospects(payload: dict, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    if user.role not in ("owner", "admin"):
        raise HTTPException(status_code=403, detail="Only the owner/admin can assign customers")
    ids = payload.get("prospect_ids", [])
    if not ids:
        return {"ok": False, "error": "prospect_ids is empty"}
    owner_id = payload.get("owner_user_id")
    if owner_id is not None:
        target = db.query(User).filter(
            User.id == int(owner_id),
            User.tenant_id == user.tenant_id,
            User.status == "active",
        ).first()
        if not target:
            raise HTTPException(status_code=400, detail="Target member not found or disabled")
    updated = db.query(Prospect).filter(Prospect.id.in_(ids), Prospect.is_deleted == 0).update(
        {Prospect.owner_user_id: int(owner_id) if owner_id is not None else None},
        synchronize_session=False,
    )
    db.commit()
    return {"ok": True, "updated": updated}


# ── POST /api/prospects/batch-score ────────────────────
@router.post("/batch-score")
async def batch_score_prospects(payload: dict, db: Session = Depends(get_db),
                                user: User = Depends(get_current_user)):
    """Score multiple prospects in batch."""
    ids = payload.get("prospect_ids", [])
    if not ids:
        return {"success": False, "error": "No prospect_ids provided"}
    
    from routers.ai import score_prospect
    
    scored = 0
    errors = []
    for pid in ids:
        try:
            await score_prospect(pid, db=db, user=user)
            scored += 1
        except Exception as e:
            errors.append(f"#{pid}: {str(e)[:80]}")
    
    return {"success": True, "scored": scored, "total": len(ids), "errors": errors}


# ── POST /api/prospects/batch-update ───────────────────
@router.post("/batch-update")
async def batch_update_prospects(payload: dict, db: Session = Depends(get_db)):
    """Batch update status, sales_stage, or profile fields."""
    ids = payload.get("ids", [])
    updates = payload.get("updates", {})
    if not ids or not updates:
        return {"success": False, "error": "ids and updates required"}
    
    allowed = {"status", "sales_stage", "profile_type", "value_level", "next_follow_date", "reminder_note", "email_status"}
    filtered = {k: v for k, v in updates.items() if k in allowed}
    if not filtered:
        return {"success": False, "error": "No valid update fields"}
    
    filtered["last_edited_at"] = datetime.utcnow()
    updated = db.query(Prospect).filter(
        Prospect.id.in_(ids), Prospect.is_deleted == 0
    ).update(filtered, synchronize_session=False)
    db.commit()
    
    return {"success": True, "updated": updated}


# ── GET /api/prospects/stats/summary ────────────────────
@router.get("/stats/summary")
async def prospect_stats_summary(db: Session = Depends(get_db)):
    """Return aggregate stats: total active, by stage, by profile, untouched count."""
    active = db.query(Prospect).filter(
        Prospect.is_deleted == 0
    ).all()
    
    total = len(active)
    
    by_stage = {}
    by_profile = {}
    untouched = 0
    
    for p in active:
        stage = p.sales_stage or "unknown"
        by_stage[stage] = by_stage.get(stage, 0) + 1
        
        pt = p.profile_type or "?"
        by_profile[pt] = by_profile.get(pt, 0) + 1
        
        # Untouched = no interactions, no email queue items, no sequences
        from models import Interaction, EmailQueue, Sequence
        has_interactions = db.query(Interaction).filter(
            Interaction.prospect_id == p.id
        ).count()
        has_emails = db.query(EmailQueue).filter(
            EmailQueue.prospect_id == p.id
        ).count()
        has_sequences = db.query(Sequence).filter(
            Sequence.prospect_id == p.id
        ).count()
        if not has_interactions and not has_emails and not has_sequences:
            untouched += 1
    
    return {
        "total_active": total,
        "by_sales_stage": by_stage,
        "by_profile_type": by_profile,
        "untouched": untouched,
    }


# ── GET /api/prospects/export ───────────────────────────
@router.get("/export")
async def export_prospects(
    status: str | None = None,
    profile_type: str | None = None,
    db: Session = Depends(get_db),
):
    """Export prospects as JSON for backup or external use."""
    q = db.query(Prospect).filter(Prospect.is_deleted == 0)
    if status:
        q = q.filter(Prospect.status == status)
    if profile_type:
        q = q.filter(Prospect.profile_type == profile_type)
    
    items = q.order_by(Prospect.id.desc()).all()
    return {
        "total": len(items),
        "customers": [ProspectOut.model_validate(p).model_dump() for p in items],
    }




# ── POST /api/prospects/{id}/verify-email ──────────────────
@router.post("/{prospect_id}/verify-email")
async def verify_email_single(prospect_id: int, db: Session = Depends(get_db)):
    """Verify a single prospect's email address."""
    from services.email_verifier import verify_email
    from datetime import datetime as dt

    p = db.query(Prospect).filter(Prospect.id == prospect_id, Prospect.is_deleted == 0).first()
    if not p:
        raise HTTPException(404, "Customer not found")
    email = (p.email or "").strip()
    if not email or "@" not in email:
        return {"success": False, "error": "No valid email address"}

    try:
        r = verify_email(email, smtp=True, timeout=8)
        verdict = r.get("verdict", "unknown")
        p.email_verdict = verdict
        p.email_verification_detail = json.dumps(r, ensure_ascii=False)
        p.email_verified_at = dt.utcnow()
        p.email_verified = 1 if verdict == "valid" else (-1 if verdict == "invalid" else 0)
        db.commit()
        return {"success": True, "result": r}
    except Exception as e:
        return {"success": False, "error": str(e)[:200]}


# ── POST /api/prospects/verify-emails ─────────────────────
@router.post("/verify-emails")
async def verify_emails(
    ids: list[int] = [],
    all_unsure: bool = False,
    db: Session = Depends(get_db),
):
    """Verify email addresses for selected prospects (or all that haven't been verified).
    Uses: syntax → MX record → SMTP handshake (full check, takes ~3-8s per email).
    """
    from services.email_verifier import verify_email
    from datetime import datetime as dt

    if all_unsure:
        prospects = db.query(Prospect).filter(
            Prospect.is_deleted == 0,
            (Prospect.email_verified == 0) | (Prospect.email_verified.is_(None)),
            Prospect.email.isnot(None),
            Prospect.email != "",
        ).all()
    elif ids:
        prospects = db.query(Prospect).filter(
            Prospect.id.in_(ids),
            Prospect.is_deleted == 0,
        ).all()
    else:
        return {"success": False, "error": "Provide ids or set all_unsure=true"}

    results = []
    for p in prospects:
        email = (p.email or "").strip()
        if not email or "@" not in email:
            continue
        try:
            r = verify_email(email, smtp=True, timeout=8)
            verdict = r.get("verdict", "unknown")
            p.email_verdict = verdict
            p.email_verification_detail = json.dumps(r, ensure_ascii=False)
            p.email_verified_at = dt.utcnow()
            p.email_verified = 1 if verdict == "valid" else (-1 if verdict == "invalid" else 0)
            results.append({
                "id": p.id,
                "company": p.company,
                "email": email,
                "verdict": verdict,
                "score": r.get("overall_score", 0),
                "detail": r.get("recommendation", ""),
            })
        except Exception as e:
            results.append({
                "id": p.id,
                "company": p.company,
                "email": email,
                "verdict": "error",
                "score": 0,
                "detail": str(e)[:200],
            })

    db.commit()

    valid_count = sum(1 for x in results if x["verdict"] == "valid")
    invalid_count = sum(1 for x in results if x["verdict"] == "invalid")
    return {
        "success": True,
        "total": len(results),
        "valid": valid_count,
        "risky": sum(1 for x in results if x["verdict"] == "risky"),
        "invalid": invalid_count,
        "unknown": sum(1 for x in results if x["verdict"] not in ("valid", "risky", "invalid")),
        "results": results,
    }
