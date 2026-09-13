# -*- coding: utf-8 -*-
"""回复率口径公共函数：退信一律不算真实回复。"""


def is_bounce_interaction(ix) -> bool:
    """判断一条 inbound 互动是否为退信（自动检测写入）。"""
    try:
        if (ix.reply_intent or "") in ("bounce", "退信"):
            return True
        if "[Auto-detected] Mail bounce" in (ix.content or "") or "[自动检测] 邮件退信" in (ix.content or ""):
            return True
    except Exception:
        pass
    return False
