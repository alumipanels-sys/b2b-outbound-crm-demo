"""Team work stats — shared by the team dashboard and the daily WeChat report."""

from datetime import date, datetime, timedelta

from sqlalchemy.orm import Session

from models import AuditLog, Deal, EmailQueue, Interaction, Prospect, User
from services.reply_metrics import is_bounce_interaction

SENSITIVE_AUDIT_ACTIONS = {"delete_prospect", "user_export", "user_restore"}
WON_STAGES = {"Won", "won", "WON", "成交"}
CLOSED_STAGES = WON_STAGES | {"Lost", "lost"}


def team_dashboard_stats(db: Session, tenant_id: int, days: int = 1) -> dict:
    """顶级监工视角：每个成员的客户池状态 + 工作产出 + 敏感操作（退信不算回复）。"""
    today = date.today().isoformat()
    start = (datetime.utcnow() - timedelta(days=days - 1)).replace(hour=0, minute=0, second=0, microsecond=0)

    members = (
        db.query(User)
        .filter(User.tenant_id == tenant_id, User.status == "active")
        .order_by(User.id.asc())
        .all()
    )

    prospects = db.query(Prospect).filter(Prospect.is_deleted == 0).all()
    interactions = db.query(Interaction).all()
    queues = db.query(EmailQueue).all()
    deals = db.query(Deal).filter(Deal.is_deleted == 0).all()
    audits = db.query(AuditLog).all()

    outbound_pids = {ix.prospect_id for ix in interactions if ix.direction == "outbound"}
    real_inbound_pids = {
        ix.prospect_id for ix in interactions
        if ix.direction == "inbound" and not is_bounce_interaction(ix)
    }
    int_pids = outbound_pids | real_inbound_pids

    totals = {
        "prospects": 0, "not_started": 0, "following": 0,
        "need_followup": 0, "sent": 0, "replies": 0, "reply_rate": 0.0,
        "replied_customers": 0, "touched_customers": 0,
        "new_customers": 0, "imports": 0, "drafts": 0, "deals": 0, "won": 0, "sensitive": 0,
    }
    rows = []

    import re as _re

    def _import_count_for(uid):
        n = 0
        for a in audits:
            if a.user_id == uid and a.action == "import_prospects" \
                    and a.created_at and a.created_at >= start:
                m = _re.search(r"导入客户 (\d+) 个", a.detail or "")
                if m:
                    n += int(m.group(1))
        return n

    def _stats(uid, name, role):
        owned = [p for p in prospects if p.owner_user_id == uid]
        owned_ids = {p.id for p in owned}
        touched = owned_ids & outbound_pids
        replied = owned_ids & real_inbound_pids
        reply_rate = round(len(replied) / len(touched) * 100, 1) if touched else 0.0

        sent = sum(1 for q in queues if q.owner_user_id == uid and q.status == "sent"
                   and q.sent_at and q.sent_at >= start)
        replies = sum(1 for ix in interactions if ix.owner_user_id == uid
                      and ix.direction == "inbound" and not is_bounce_interaction(ix)
                      and ix.interacted_at and ix.interacted_at >= start)
        need = sum(1 for p in owned if p.next_follow_date and p.next_follow_date <= today
                   and (p.sales_stage or "") not in ("lost", "cooling"))
        new_c = sum(1 for p in owned if p.created_at and p.created_at >= start)
        drafts = sum(1 for q in queues if q.owner_user_id == uid and q.status == "draft")
        member_deals = sum(1 for d in deals
                           if (d.owner_user_id == uid or d.prospect_id in owned_ids)
                           and (d.stage or "") not in CLOSED_STAGES)
        won = sum(1 for d in deals
                  if (d.owner_user_id == uid or d.prospect_id in owned_ids)
                  and (d.stage or "").strip() in WON_STAGES)
        sensitive = sum(1 for a in audits if a.user_id == uid
                        and a.action in SENSITIVE_AUDIT_ACTIONS
                        and a.created_at and a.created_at >= start)
        imports = _import_count_for(uid)
        not_started = sum(1 for p in owned if p.id not in int_pids
                          and (p.sales_stage or "") not in ("won", "lost", "cooling"))
        following = sum(1 for p in owned if p.id in int_pids
                        and (p.sales_stage or "") not in ("won", "lost", "cooling"))

        return {
            "user_id": uid, "name": name, "role": role,
            "prospects": len(owned), "not_started": not_started, "following": following,
            "need_followup": need, "sent": sent, "replies": replies, "reply_rate": reply_rate,
            "replied_customers": len(replied), "touched_customers": len(touched),
            "new_customers": new_c, "imports": imports, "drafts": drafts,
            "deals": member_deals, "won": won, "sensitive": sensitive,
        }

    for m in members:
        s = _stats(m.id, m.name, m.role)
        rows.append(s)
        for k in totals:
            if k not in ("reply_rate", "replied_customers", "touched_customers"):
                totals[k] += s[k]

    # 未分配客户池（老板最该先看到：客户资源还没人管）
    unassigned = [p for p in prospects if p.owner_user_id is None]
    if unassigned:
        uids = {p.id for p in unassigned}
        u_need = sum(1 for p in unassigned if p.next_follow_date and p.next_follow_date <= today
                     and (p.sales_stage or "") not in ("lost", "cooling"))
        u_not_started = sum(1 for p in unassigned if p.id not in int_pids
                            and (p.sales_stage or "") not in ("won", "lost", "cooling"))
        u_following = sum(1 for p in unassigned if p.id in int_pids
                          and (p.sales_stage or "") not in ("won", "lost", "cooling"))
        rows.append({
            "user_id": None, "name": "未分配", "role": "-",
            "prospects": len(unassigned), "not_started": u_not_started, "following": u_following,
            "need_followup": u_need, "sent": 0, "replies": 0, "reply_rate": 0.0,
            "replied_customers": 0, "touched_customers": 0,
            "new_customers": 0, "imports": 0, "drafts": 0, "deals": 0, "won": 0, "sensitive": 0,
        })
        totals["prospects"] += len(unassigned)
        totals["not_started"] += u_not_started
        totals["following"] += u_following
        totals["need_followup"] += u_need

    _tmp_touched = sum(r["touched_customers"] for r in rows if r["user_id"] is not None)
    _tmp_replied = sum(r["replied_customers"] for r in rows if r["user_id"] is not None)
    totals["replied_customers"] = _tmp_replied
    totals["touched_customers"] = _tmp_touched
    totals["reply_rate"] = round(_tmp_replied / _tmp_touched * 100, 1) if _tmp_touched else 0.0

    return {
        "days": days,
        "date_range": {"from": start.date().isoformat(), "to": today},
        "rows": rows,
        "totals": totals,
    }
