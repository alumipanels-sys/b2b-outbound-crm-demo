# -*- coding: utf-8 -*-
"""客户画像分类公共读写：默认 A-E + 客户自定义（每个行业自己维护）。"""
import json

from models import SystemSetting

DEFAULT_PROFILE_CATEGORIES = [
    {"key": "A", "label": "A - High-value account"},
    {"key": "B", "label": "B - OEM / integrator"},
    {"key": "C", "label": "C - Emerging-market brand"},
    {"key": "D", "label": "D - Niche-market assembler"},
    {"key": "E", "label": "E - Repair / service"},
]


def load_profile_categories(db):
    row = db.query(SystemSetting).filter(SystemSetting.key == "profile_categories").first()
    if not row:
        return [dict(c) for c in DEFAULT_PROFILE_CATEGORIES]
    try:
        cats = json.loads(row.value)
        if isinstance(cats, list) and cats:
            return cats
    except Exception:
        pass
    return [dict(c) for c in DEFAULT_PROFILE_CATEGORIES]


def save_profile_categories(db, cats):
    row = db.query(SystemSetting).filter(SystemSetting.key == "profile_categories").first()
    val = json.dumps(cats, ensure_ascii=False)
    if row:
        row.value = val
    else:
        db.add(SystemSetting(key="profile_categories", value=val))
    db.commit()
