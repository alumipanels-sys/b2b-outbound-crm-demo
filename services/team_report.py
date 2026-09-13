"""每日团队工作汇报 → 老板微信（ServerChan）。"""

import logging
from datetime import date

from models import User
from services.team_service import team_dashboard_stats

logger = logging.getLogger(__name__)


def build_report_text(summary: dict) -> str:
    t = summary["totals"]
    lines = [f"📋 今日团队工作汇报（{summary['date_range']['to']}）"]
    lines.append(f"Sent today {t['sent']} | Replies {t['replies']} | To follow up {t['need_followup']} | New clients {t['new_customers']} | Drafts {t['drafts']}")
    lines.append("")
    for r in summary["rows"]:
        lines.append(
            f"• {r['name']}：发信 {r['sent']} / 回复 {r['replies']} / "
            f"待跟进 {r['need_followup']} / 新增 {r['new_customers']} / 草稿 {r['drafts']}"
        )
    lines.append("")
    lines.append("Open the system → Team dashboard for details; follow up on overdue clients.")
    return "\n".join(lines)


def send_daily_team_report(db=None) -> dict:
    """每天 18:00：把团队工作汇报推送到主账号微信。"""
    close_db = db is None
    if db is None:
        from database import SessionLocal
        db = SessionLocal()
    try:
        from config import SERVERCHAN_SENDKEY
        key = (SERVERCHAN_SENDKEY or "").strip()
        if not key:
            return {"sent": False, "reason": "未配置 SERVERCHAN_SENDKEY"}
        owner = db.query(User).filter(User.role == "owner", User.status == "active").first()
        if not owner:
            return {"sent": False, "reason": "没有主账号"}
        summary = team_dashboard_stats(db, owner.tenant_id, days=1)
        t = summary["totals"]
        title = f"今日团队汇报：发信{t['sent']} 回复{t['replies']} 待跟进{t['need_followup']}"
        desp = build_report_text(summary)
        import requests
        r = requests.post(
            f"https://sctapi.ftqq.com/{key}.send",
            data={"title": title, "desp": desp},
            timeout=10,
            proxies={"http": None, "https": None},
        )
        logger.info("DAILY_TEAM_REPORT: sent=%s status=%s", r.status_code == 0, r.status_code)
        return {"sent": True, "title": title}
    except Exception as e:
        logger.warning("DAILY_TEAM_REPORT failed: %s", e)
        return {"sent": False, "reason": str(e)}
    finally:
        if close_db:
            db.close()
