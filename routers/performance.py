"""Performance dashboard for strategic cold-outreach management."""

from __future__ import annotations

from collections import defaultdict
from datetime import date, datetime, timedelta
from statistics import mean
from typing import Iterable

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from database import get_db
from models import Deal, EmailQueue, Interaction, Prospect, Sequence, User
from routers.auth import get_current_user
from services.reply_metrics import is_bounce_interaction

router = APIRouter()


@router.get("/review")
def review_report(days: int = Query(30, ge=1, le=365), db: Session = Depends(get_db),
                  user: User = Depends(get_current_user)):
    """复盘报表：按来源渠道 / 行业统计发信、回复、回复率、成交、成交率。"""
    if user.role not in ("owner", "admin"):
            raise HTTPException(status_code=403, detail="Only the owner/admin can view the review")
    start = datetime.utcnow() - timedelta(days=days)
    prospects = {p.id: p for p in db.query(Prospect).filter(Prospect.is_deleted == 0).all()}
    outbound = db.query(Interaction).filter(Interaction.direction == "outbound", Interaction.interacted_at >= start).all()
    inbound = [i for i in
               db.query(Interaction).filter(Interaction.direction == "inbound", Interaction.interacted_at >= start).all()
               if not is_bounce_interaction(i)]
    won_ids = {d.prospect_id for d in db.query(Deal).filter(Deal.stage == "Won").all()}

    def _agg(key_fn):
        rows = defaultdict(lambda: {"sent": 0, "replies": 0, "won": 0})
        for i in outbound:
            p = prospects.get(i.prospect_id)
            if p:
                rows[key_fn(p)]["sent"] += 1
        for i in inbound:
            p = prospects.get(i.prospect_id)
            if p:
                rows[key_fn(p)]["replies"] += 1
        for pid in won_ids:
            p = prospects.get(pid)
            if p:
                rows[key_fn(p)]["won"] += 1
        result = []
        for k, v in rows.items():
            v["reply_rate"] = round(v["replies"] / v["sent"] * 100, 1) if v["sent"] else 0
            v["won_rate"] = round(v["won"] / v["sent"] * 100, 1) if v["sent"] else 0
            result.append({"key": k, **v})
        return sorted(result, key=lambda x: -x["sent"])

    return {
        "days": days,
        "by_channel": _agg(lambda p: p.source_channel or "Unknown"),
        "by_industry": _agg(lambda p: p.industry or "Unknown"),
    }


FUNNEL_STAGES = ["New", "Following up", "Replied", "Won", "Lost"]
ACTIONABLE_INTENTS = {"INFORMATION_REQUEST", "PRICING", "SAMPLE", "QUALIFICATION", "COOPERATION", "REFERRAL", "HOT_LEAD"}


def _dt(value) -> datetime | None:
    if not value:
        return None
    if isinstance(value, datetime):
        return value.replace(tzinfo=None)
    if isinstance(value, date):
        return datetime(value.year, value.month, value.day)
    if isinstance(value, str):
        try:
            return datetime.fromisoformat(value.replace("Z", "+00:00")).replace(tzinfo=None)
        except Exception:
            return None
    return None


def _date_key(value, period: str) -> str | None:
    dt = _dt(value)
    if not dt:
        return None
    if period == "month":
        return dt.strftime("%Y-%m")
    start = dt.date() - timedelta(days=dt.weekday())
    return start.isoformat()


def _pct(n: int | float, d: int | float) -> float:
    return round((n / d * 100), 1) if d else 0.0


def _safe_profile(p: str | None) -> str:
    return (p or "Not profiled").strip() or "Not profiled"


def _first_dt(items: Iterable[datetime | None]) -> datetime | None:
    vals = [x for x in items if x]
    return min(vals) if vals else None


@router.get("/dashboard")
async def performance_dashboard(
    period: str = Query("week", pattern="^(week|month)$"),
    db: Session = Depends(get_db),
):
    prospects = db.query(Prospect).filter(Prospect.is_deleted == 0).all()
    interactions = db.query(Interaction).all()
    deals = db.query(Deal).filter(Deal.is_deleted == 0).all()
    queues = db.query(EmailQueue).all()
    sequences = db.query(Sequence).all()

    active_prospects = [p for p in prospects if (p.profile_type or "") != "EXCLUDE"]
    prospect_by_id = {p.id: p for p in prospects}

    inbound_by_pid = defaultdict(list)
    outbound_by_pid = defaultdict(list)
    interactions_by_pid = defaultdict(list)
    for ix in interactions:
        interactions_by_pid[ix.prospect_id].append(ix)
        if ix.direction == "inbound":
            if not is_bounce_interaction(ix):
                inbound_by_pid[ix.prospect_id].append(ix)
        elif ix.direction == "outbound":
            outbound_by_pid[ix.prospect_id].append(ix)

    won_deal_pids = {
        d.prospect_id for d in deals
        if (d.stage or "").strip() in {"Won", "won", "WON", "成交"}
    }

    total_deal_amount = sum((d.amount or 0) for d in deals)
    won_amount = sum((d.amount or 0) for d in deals if d.prospect_id in won_deal_pids)

    funnel_counts = {stage: 0 for stage in FUNNEL_STAGES}
    for p in active_prospects:
        status = (p.status or "").strip()
        if p.id in won_deal_pids or status == "Won":
            funnel_counts["Won"] += 1
        elif status == "Lost":
            funnel_counts["Lost"] += 1
        elif p.id in inbound_by_pid or status == "Replied":
            funnel_counts["Replied"] += 1
        elif status == "Following up" or p.id in outbound_by_pid:
            funnel_counts["Following up"] += 1
        else:
            funnel_counts["New"] += 1

    funnel = []
    previous = None
    total_active = len(active_prospects)
    for stage in FUNNEL_STAGES:
        count = funnel_counts.get(stage, 0)
        funnel.append({
            "stage": stage,
            "count": count,
            "share": _pct(count, total_active),
            "conversion_from_previous": _pct(count, previous) if previous is not None else 100.0,
        })
        previous = count

    outbound = [ix for ix in interactions if ix.direction == "outbound"]
    inbound = [ix for ix in interactions if ix.direction == "inbound"]
    real_inbound = [ix for ix in inbound if not is_bounce_interaction(ix)]
    touched_pids = {ix.prospect_id for ix in outbound}
    replied_pids = {ix.prospect_id for ix in real_inbound}
    bounced_pids = {ix.prospect_id for ix in inbound if is_bounce_interaction(ix)}
    actionable_replies = [
        ix for ix in real_inbound
        if (ix.reply_intent or "").upper() in ACTIONABLE_INTENTS
    ]

    trend_map = defaultdict(lambda: {"outbound": 0, "inbound": 0, "email_sent": 0, "sequences_done": 0})
    for ix in interactions:
        key = _date_key(ix.interacted_at or ix.created_at, period)
        if not key:
            continue
        if ix.direction == "outbound":
            trend_map[key]["outbound"] += 1
        elif ix.direction == "inbound" and not is_bounce_interaction(ix):
            trend_map[key]["inbound"] += 1
    for q in queues:
        if q.status != "sent":
            continue
        key = _date_key(q.sent_at or q.created_at, period)
        if key:
            trend_map[key]["email_sent"] += 1
    for s in sequences:
        if s.status not in {"done", "sent"}:
            continue
        key = _date_key(s.executed_at or s.updated_at, period)
        if key:
            trend_map[key]["sequences_done"] += 1

    today = date.today()
    buckets = []
    if period == "month":
        cursor = date(today.year, today.month, 1)
        for _ in range(5):
            if cursor.month == 1:
                cursor = date(cursor.year - 1, 12, 1)
            else:
                cursor = date(cursor.year, cursor.month - 1, 1)
        for _ in range(6):
            key = cursor.strftime("%Y-%m")
            buckets.append(key)
            if cursor.month == 12:
                cursor = date(cursor.year + 1, 1, 1)
            else:
                cursor = date(cursor.year, cursor.month + 1, 1)
    else:
        start = today - timedelta(days=today.weekday()) - timedelta(weeks=7)
        buckets = [(start + timedelta(weeks=i)).isoformat() for i in range(8)]

    trends = []
    for key in buckets:
        row = trend_map[key]
        trends.append({
            "period": key,
            "outbound": row["outbound"],
            "inbound": row["inbound"],
            "email_sent": row["email_sent"],
            "sequences_done": row["sequences_done"],
            "reply_rate": _pct(row["inbound"], row["outbound"]),
        })

    profile_rows = []
    for profile in sorted({_safe_profile(p.profile_type) for p in active_prospects}):
        group = [p for p in active_prospects if _safe_profile(p.profile_type) == profile]
        group_ids = {p.id for p in group}
        contacted = len(group_ids & touched_pids)
        replied = len(group_ids & replied_pids)
        won = len(group_ids & won_deal_pids)

        reply_days = []
        won_days = []
        for pid in group_ids:
            first_out = _first_dt(_dt(ix.interacted_at or ix.created_at) for ix in outbound_by_pid.get(pid, []))
            first_in = _first_dt(_dt(ix.interacted_at or ix.created_at) for ix in inbound_by_pid.get(pid, []))
            if first_out and first_in and first_in >= first_out:
                reply_days.append((first_in - first_out).days)
            won_dates = [_dt(d.updated_at or d.created_at) for d in deals if d.prospect_id == pid and d.prospect_id in won_deal_pids]
            first_won = _first_dt(won_dates)
            if first_out and first_won and first_won >= first_out:
                won_days.append((first_won - first_out).days)

        profile_rows.append({
            "profile": profile,
            "prospects": len(group),
            "contacted": contacted,
            "replied": replied,
            "won": won,
            "reply_rate": _pct(replied, contacted),
            "won_rate": _pct(won, contacted),
            "avg_days_to_reply": round(mean(reply_days), 1) if reply_days else None,
            "avg_days_to_won": round(mean(won_days), 1) if won_days else None,
        })

    profile_rows.sort(key=lambda r: (-(r["contacted"] or 0), r["profile"]))

    channel_rows = []
    channels = sorted({(ix.channel or "unknown") for ix in interactions})
    for ch in channels:
        out = [ix for ix in outbound if (ix.channel or "unknown") == ch]
        inb = [ix for ix in real_inbound if (ix.channel or "unknown") == ch]
        out_pids = {ix.prospect_id for ix in out}
        in_pids = {ix.prospect_id for ix in inb}
        channel_rows.append({
            "channel": ch,
            "outbound": len(out),
            "inbound": len(inb),
            "contacted_prospects": len(out_pids),
            "replied_prospects": len(in_pids),
            "reply_rate": _pct(len(in_pids), len(out_pids)),
        })
    channel_rows.sort(key=lambda r: (-r["outbound"], r["channel"]))

    # ── Methodology effectiveness (feedback loop) ──
    methodology_rows = []
    from models import KnowledgeBase
    method_entries = {e.id: e.title for e in db.query(KnowledgeBase.id, KnowledgeBase.title).filter(
        KnowledgeBase.category == "methodology", KnowledgeBase.is_active == 1
    ).all()}

    # Build outbound→inbound by PID for attribution
    ob_by_pid = defaultdict(list)
    ib_by_pid = defaultdict(list)
    for ix in interactions:
        if not ix.prospect_id:
            pass
        elif ix.direction == "outbound":
            ob_by_pid[ix.prospect_id].append(ix)
        elif ix.direction == "inbound" and not is_bounce_interaction(ix):
            ib_by_pid[ix.prospect_id].append(ix)

    for mid, mname in sorted(method_entries.items(), key=lambda kv: kv[1]):
        mid_str = str(mid)
        out_mid = [ix for ix_list in ob_by_pid.values() for ix in ix_list
                    if ix.generation_meta and mid_str in (ix.generation_meta or "")]
        if not out_mid:
            continue
        out_pids = {ix.prospect_id for ix in out_mid}
        replied = 0
        sample_pids = set()
        won_pids = set()
        for pid in out_pids:
            inb_list = ib_by_pid.get(pid, [])
            out_list = [ix for ix in out_mid if ix.prospect_id == pid]
            out_dates = [_dt(ix.interacted_at or ix.created_at) for ix in out_list]
            out_first = min([d for d in out_dates if d], default=None)
            if out_first:
                in_after = [ix for ix in inb_list
                            if (d := _dt(ix.interacted_at or ix.created_at)) and d >= out_first]
                if in_after:
                    replied += 1
            pdeals = [d for d in deals if d.prospect_id == pid]
            if any((d.stage or "").strip() in {"Won", "won", "WON"} for d in pdeals):
                won_pids.add(pid)
            for p in prospects:
                if p.id == pid and p.sample_status and p.sample_status != "none":
                    sample_pids.add(pid)

        methodology_rows.append({
            "methodology_id": mid,
            "title": mname,
            "outbound_count": len(out_mid),
            "prospect_count": len(out_pids),
            "replied_count": replied,
            "reply_rate": _pct(replied, len(out_pids)),
            "sample_count": len(sample_pids),
            "won_count": len(won_pids),
            "won_rate": _pct(len(won_pids), len(out_pids)),
        })

    return {
        "success": True,
        "period": period,
        "overview": {
            "active_prospects": total_active,
            "contacted_prospects": len(touched_pids),
            "replied_prospects": len(replied_pids),
            "reply_rate": _pct(len(replied_pids), len(touched_pids)),
            "bounced_prospects": len(bounced_pids),
            "bounce_rate": _pct(len(bounced_pids), len(touched_pids)),
            "actionable_replies": len(actionable_replies),
            "won_prospects": len(won_deal_pids),
            "won_rate": _pct(len(won_deal_pids), len(touched_pids)),
            "open_deals": len([d for d in deals if d.prospect_id not in won_deal_pids and (d.stage or "") != "Lost"]),
            "total_deal_amount": round(total_deal_amount, 2),
            "won_amount": round(won_amount, 2),
        },
        "funnel": funnel,
        "trends": trends,
        "profiles": profile_rows,
        "channels": channel_rows,
        "methodologies": methodology_rows,
    }
