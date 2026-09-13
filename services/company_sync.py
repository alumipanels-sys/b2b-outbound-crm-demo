# -*- coding: utf-8 -*-
"""公司级同步：联系人的跟进动作自动同步到公司主记录。"""

from datetime import datetime, timezone

from models import Prospect


def get_company_main(db, company):
    """找公司主记录：优先决策人，其次公共邮箱，最后最早创建。"""
    if not (company or "").strip():
        return None
    rows = (
        db.query(Prospect)
        .filter(Prospect.company == company, Prospect.is_deleted == 0)
        .order_by(Prospect.id.asc())
        .all()
    )
    if not rows:
        return None
    for r in rows:
        if r.decision_maker:
            return r
    for r in rows:
        em = (r.email or "").lower()
        if "info@" in em or "einkauf@" in em or "purchase" in em:
            return r
    return rows[0]


def sync_company_main(db, prospect):
    """把刚发生跟进动作的联系人状态同步到公司主记录。"""
    if not prospect or not (prospect.company or "").strip():
        return None
    main = get_company_main(db, prospect.company)
    if not main or main.id == prospect.id:
        return main
    main.next_follow_date = prospect.next_follow_date
    main.reminder_note = prospect.reminder_note
    main.reminder_updated_at = prospect.reminder_updated_at or datetime.now(timezone.utc)
    main.sales_stage = prospect.sales_stage
    main.status = prospect.status
    main.last_edited_at = datetime.now(timezone.utc)
    db.add(main)
    return main
