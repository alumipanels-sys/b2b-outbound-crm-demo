# -*- coding: utf-8 -*-
"""每日目标：新客户触达统计（周二/三/四周考核）+ 老板目标管理。

口径：触达 = 该客户第一封已发送的开发信；一个客户只算一次，后续跟进不算；
      退信也计数（不搞额外规矩）。考核日固定为周二、周三、周四。
      纯展示督促，不限制任何发送。
"""
from datetime import date, datetime, timedelta

from sqlalchemy.orm import Session

from models import DailyTarget, EmailQueue, User

BEST_SEND_DAYS = (1, 2, 3)  # Python weekday: 0=Mon, 1=Tue, 2=Wed, 3=Thu
WEEKDAY_EN = {0: "Mon", 1: "Tue", 2: "Wed", 3: "Thu", 4: "Fri", 5: "Sat", 6: "Sun"}


def get_target(db: Session, tenant_id: int, user_id: int, default: int = 3) -> DailyTarget:
    """读取成员目标；没有记录时返回默认目标（不写入）。"""
    t = db.query(DailyTarget).filter(DailyTarget.user_id == user_id).first()
    if t is None:
        t = DailyTarget(tenant_id=tenant_id, user_id=user_id, target_per_day=default)
    return t


def set_target(db: Session, tenant_id: int, user_id: int, target_per_day: int) -> DailyTarget:
    """老板设置目标。只做数字合法性兜底（1~99），不设硬拦截；风险靠前端提示。"""
    target = max(1, min(int(target_per_day), 99))
    t = db.query(DailyTarget).filter(DailyTarget.user_id == user_id).first()
    if t is None:
        t = DailyTarget(tenant_id=tenant_id, user_id=user_id, target_per_day=target)
        db.add(t)
    else:
        t.target_per_day = target
    db.commit()
    db.refresh(t)
    return t


def _first_touches(db: Session, user_id: int, start_dt: datetime | None = None,
                   end_dt: datetime | None = None) -> dict:
    """某成员的时间段内每个客户第一封已发送邮件；返回 {prospect_id: sent_at}。

    退信也计数。日期口径与现有统计一致：sent_at 为 naive UTC，按 UTC 自然日切分。
    """
    q = db.query(EmailQueue).filter(
        EmailQueue.owner_user_id == user_id,
        EmailQueue.status == "sent",
        EmailQueue.sent_at.isnot(None),
    )
    if start_dt is not None:
        q = q.filter(EmailQueue.sent_at >= start_dt)
    if end_dt is not None:
        q = q.filter(EmailQueue.sent_at < end_dt)

    first: dict = {}
    for r in q.all():
        pid = r.prospect_id
        if pid not in first or r.sent_at < first[pid]:
            first[pid] = r.sent_at
    return first


def touch_series(db: Session, user_id: int, start_dt: datetime, end_dt: datetime) -> dict:
    """时间段内每天的新触达数，{YYYY-MM-DD: n}。"""
    first = _first_touches(db, user_id, start_dt, end_dt)
    out: dict = {}
    for sent_at in first.values():
        ds = sent_at.date().isoformat()
        out[ds] = out.get(ds, 0) + 1
    return out


def _first_scheduled(db: Session, user_id: int, start_dt: datetime, end_dt: datetime) -> dict:
    """时间段内已排程（待发送）的每个客户第一封开发信；返回 {prospect_id: scheduled_at}。

    提前干活的体现：业务员周一写好开发信排程到周二/三/四，系统按客户工作日自动发出，
    这部分算“已安排触达”。已实际发送过的客户不再重复计数。
    """
    q = db.query(EmailQueue).filter(
        EmailQueue.owner_user_id == user_id,
        EmailQueue.status == "pending",
        EmailQueue.scheduled_at.isnot(None),
    )
    if start_dt is not None:
        q = q.filter(EmailQueue.scheduled_at >= start_dt)
    if end_dt is not None:
        q = q.filter(EmailQueue.scheduled_at < end_dt)

    first: dict = {}
    for r in q.all():
        pid = r.prospect_id
        if pid not in first or r.scheduled_at < first[pid]:
            first[pid] = r.scheduled_at
    return first


def _week_bounds(today: date | None = None):
    """本周一 00:00 → 下周一 00:00（naive UTC 口径，与现有统计一致）。"""
    today = today or date.today()
    monday = today - timedelta(days=today.weekday())
    start = datetime(monday.year, monday.month, monday.day)
    return start, start + timedelta(days=7), monday


def member_week_progress(db: Session, tenant_id: int, user_id: int) -> dict:
    """单个成员的周目标进度：周一到今天逐日明细 + 本周汇总。"""
    t = get_target(db, tenant_id, user_id)
    start, end, monday = _week_bounds()
    series = touch_series(db, user_id, start, end)
    # 提前排程（待发送、已安排到本周发信日）也算本周进度
    scheduled = _first_scheduled(db, user_id, start, end)
    sent_pids = set(_first_touches(db, user_id, start, end).keys())
    scheduled = {pid: ts for pid, ts in scheduled.items() if pid not in sent_pids}
    today = date.today()

    days = []
    total = 0
    for i in range(7):
        d = monday + timedelta(days=i)
        if d > today:
            break
        is_send_day = d.weekday() in BEST_SEND_DAYS
        cnt = series.get(d.isoformat(), 0)
        total += cnt
        days.append({
            "date": d.isoformat(),
            "weekday_en": WEEKDAY_EN[d.weekday()],
            # kept so older front-ends that read weekday_cn still work
            "weekday_cn": WEEKDAY_EN[d.weekday()],
            "is_send_day": is_send_day,
            "target": t.target_per_day if is_send_day else 0,
            "touched": cnt,
            "done": cnt >= t.target_per_day if is_send_day else None,
        })

    weekly_target = t.target_per_day * len(BEST_SEND_DAYS)
    week_total = total + len(scheduled)
    return {
        "target_per_day": t.target_per_day,
        "weekly_target": weekly_target,
        "week_touched": total,
        "week_scheduled": len(scheduled),
        "weekly_done": week_total >= weekly_target,
        "remaining": max(0, weekly_target - week_total),
        "monday": monday.isoformat(),
        "days": days,
    }


def team_target_stats(db: Session, tenant_id: int) -> dict:
    """老板团队看板：所有活跃成员 + 各自周目标进度。"""
    members = (
        db.query(User)
        .filter(User.tenant_id == tenant_id, User.status == "active")
        .order_by(User.id.asc())
        .all()
    )
    rows = []
    for m in members:
        prog = member_week_progress(db, tenant_id, m.id)
        prog["user_id"] = m.id
        prog["name"] = m.name
        prog["role"] = m.role
        rows.append(prog)

    return {
        "send_days": [WEEKDAY_EN[w] for w in BEST_SEND_DAYS],
        "monday": _week_bounds()[2].isoformat(),
        "rows": rows,
    }
