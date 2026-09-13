"""Knowledge base router — CRUD for knowledge entries + virtual skill prompts."""
import logging
import json
import io
from datetime import datetime

from fastapi import APIRouter, Depends, File, HTTPException, Query, UploadFile
from sqlalchemy.orm import Session

from database import get_db
from models import KnowledgeBase, KnowledgeGap, SystemSetting, User
from schemas import (
    KnowledgeClassifyRequest,
    KnowledgeCreate,
    KnowledgeDraftRequest,
    KnowledgeGapCreate,
    KnowledgeGapResolve,
    KnowledgeOut,
    ProfileCoachRequest,
    KnowledgeSuggestRequest,
    KnowledgeUpdate,
)
from services import knowledge_engine
from services.profile_categories import load_profile_categories
from routers.auth import get_current_user
from services.auth_service import log_audit

logger = logging.getLogger(__name__)
router = APIRouter()

# Virtual entries: skill prompts always available regardless of DB state
VIRTUAL_SKILL_ENTRIES = []


@router.get("/templates")
def list_kb_templates():
    """知识库搭建：行业模板列表（汽配/机械/电子/五金/通用）。"""
    from services.kb_templates import list_templates
    return {"templates": list_templates()}


@router.post("/apply-template")
def apply_kb_template(industry: str, db: Session = Depends(get_db),
                      user: User = Depends(get_current_user)):
    """一键应用行业模板：只为缺失类别生成骨架，不覆盖客户已填内容。"""
    from services.kb_templates import get_template
    tpl = get_template((industry or "").strip())
    if not tpl:
        raise HTTPException(status_code=400, detail="Unknown industry template")
    existing_cats = {
        k.category for k in db.query(KnowledgeBase)
        .filter(KnowledgeBase.is_active == 1)
        .all()
    }
    added = 0
    for cat, title, content in tpl["entries"]:
        if cat in existing_cats:
            continue
        db.add(KnowledgeBase(tenant_id=user.tenant_id, category=cat, title=title,
                             content=content, source="template",
                             confidence="medium", is_active=1))
        added += 1
    db.commit()
    log_audit(db, user, "kb_template", None,
              f"Applied industry template: {tpl['label']} ({added} entries added)")
    return {"ok": True, "added": added, "industry": tpl["label"]}


def _extract_text(raw: bytes, ext: str) -> str:
    """从 docx/pdf/xlsx/txt/md 中提取文本。"""
    if ext == "docx":
        from docx import Document
        doc = Document(io.BytesIO(raw))
        parts = [p.text for p in doc.paragraphs if p.text.strip()]
        for table in doc.tables:
            for row in table.rows:
                cells = [c.text.strip() for c in row.cells if c.text.strip()]
                if cells:
                    parts.append(" | ".join(cells))
        return "\n".join(parts)
    if ext == "xlsx":
        from openpyxl import load_workbook
        wb = load_workbook(io.BytesIO(raw), read_only=True, data_only=True)
        parts = []
        for ws in wb.worksheets:
            for row in ws.iter_rows(values_only=True):
                vals = [str(v).strip() for v in row if v is not None and str(v).strip()]
                if vals:
                    parts.append(" | ".join(vals))
        return "\n".join(parts)
    if ext == "pdf":
        from PyPDF2 import PdfReader
        reader = PdfReader(io.BytesIO(raw))
        parts = [page.extract_text() or "" for page in reader.pages]
        return "\n".join(parts)
    # txt / md / csv
    return raw.decode("utf-8", errors="replace")


@router.post("/import-file")
async def import_knowledge_file(
    file: UploadFile = File(...),
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """上传产品手册/报价单等资料，AI 提取知识条目（先返回，不直接入库）。"""
    name = (file.filename or "file").rsplit(".", 1)
    ext = name[-1].lower() if len(name) > 1 else "txt"
    if ext not in ("docx", "pdf", "xlsx", "txt", "md", "csv"):
        raise HTTPException(status_code=400, detail="Supported formats: docx / pdf / xlsx / txt / md")
    raw = await file.read()
    if len(raw) > 4 * 1024 * 1024:
        raise HTTPException(status_code=400, detail="File too large — please keep it under 4MB")
    try:
        text = _extract_text(raw, ext)
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"File parsing failed: {e}")
    text = (text or "").strip()
    if len(text) < 20:
        raise HTTPException(status_code=400, detail="No readable text found in the file (it may be a scan without an OCR layer)")

    prompt = (
        "You are the knowledge-base organizer for an export sales company. Below is text extracted from an uploaded document. "
        "Organize it into knowledge-base entries and output only a JSON array — no explanations.\n"
        "Entry format: {\"category\":\"product|profile|guidelines|forbidden|pricing|voice|case_study\","
        "\"title\":\"English title\",\"content\":\"English content (structured, with concrete data)\",\"tags\":\"comma-separated keywords\"}.\n"
        "Split each topic into its own entry (e.g. product specs, certifications, quality commitments, lead time, pricing, and target customers as separate entries). "
        "Output at most 12 entries; do not invent anything for categories with insufficient information.\n\nDocument text:\n"
        + text[:14000]
    )
    from services.ai_router import call_simple
    from services.deepseek_service import _parse_json
    try:
        import asyncio
        loop = asyncio.get_event_loop()
        raw_out = await call_simple(prompt, None, 0.3, 2400)
        # 优先完整解析（AI 可能输出 JSON 数组）；_parse_json 只取第一个对象
        import re as _re
        _clean = _re.sub(r"```(?:json)?\s*", "", (raw_out or "").strip()).strip()
        try:
            _parsed = json.loads(_clean)
        except Exception:
            _parsed = _parse_json(raw_out)
        items = _parsed if isinstance(_parsed, list) else ([_parsed] if isinstance(_parsed, dict) else [])
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"AI extraction failed: {e}")

    clean = []
    allowed = {"product", "profile", "guidelines", "forbidden", "pricing", "voice", "case_study"}
    for it in items[:12]:
        cat = str(it.get("category", "")).strip()
        title = str(it.get("title", "")).strip()
        content = str(it.get("content", "")).strip()
        if cat not in allowed or not title or not content:
            continue
        clean.append({
            "category": cat, "title": title, "content": content,
            "tags": str(it.get("tags", "")).strip(),
        })
    if not clean:
        raise HTTPException(status_code=502, detail="AI could not extract any valid entries from the document")
    return {"ok": True, "filename": file.filename, "items": clean}


def _load_virtual_skill_entries():
    global VIRTUAL_SKILL_ENTRIES
    if VIRTUAL_SKILL_ENTRIES:
        return
    try:
        from skills.skill_1_analysis import SKILL_1_SYSTEM_PROMPT
        from skills.skill_2_generation import SKILL_2_SYSTEM_PROMPT
        VIRTUAL_SKILL_ENTRIES = [
            {
                "id": -1,
                "category": "system_prompt",
                "title": "AI Skill 1 — Analysis / Scoring / Reply Intent",
                "content": SKILL_1_SYSTEM_PROMPT,
                "tags": '["scoring","email","linkedin","strategy"]',
                "is_active": 1,
                "source_url": None,
                "created_at": "2026-06-19T00:00:00",
                "updated_at": "2026-06-19T00:00:00",
                "_virtual": True,
            },
            {
                "id": -2,
                "category": "system_prompt",
                "title": "AI Skill 2 — Message Generation (LinkedIn / Email)",
                "content": SKILL_2_SYSTEM_PROMPT,
                "tags": '["scoring","email","linkedin","strategy"]',
                "is_active": 1,
                "source_url": None,
                "created_at": "2026-06-19T00:00:00",
                "updated_at": "2026-06-19T00:00:00",
                "_virtual": True,
            },
        ]
    except Exception as e:
        logger.warning("Could not load skill prompts: %s", e)


@router.get("")
async def list_knowledge(
    tags: str | None = Query(None),
    category: str | None = Query(None),
    db: Session = Depends(get_db),
):
    """Get all knowledge entries + skill prompts, optionally filtered."""
    _load_virtual_skill_entries()

    # DB entries
    items = []
    try:
        # 系统核心 Skill 提示词（AI 评分/回复/生成逻辑）对客户隐藏，防止核心逻辑泄露
        q = db.query(KnowledgeBase).filter(
            KnowledgeBase.is_active == 1,
            ~KnowledgeBase.title.contains("Skill"),
        )
        if category and category != "system_prompt":
            q = q.filter(KnowledgeBase.category == category)
        if tags:
            q = q.filter(KnowledgeBase.tags.contains(tags))
        db_items = q.order_by(KnowledgeBase.created_at.desc()).all()
        for k in db_items:
            d = KnowledgeOut.model_validate(k).model_dump()
            d["_virtual"] = False
            items.append(d)
    except Exception as e:
        logger.warning("DB query failed, serving virtual entries only: %s", e)

    # Virtual skill entries (always show if no category filter or filtering system_prompt)
    if not category or category == "system_prompt":
        for ve in VIRTUAL_SKILL_ENTRIES:
            title = ve["title"]
            if any(k.get("title") == title for k in items):
                continue  # DB already has a real copy
            if not tags or (ve["tags"] and tags in ve["tags"]):
                items.append(ve)

    return items


@router.post("")
async def create_knowledge(data: KnowledgeCreate, db: Session = Depends(get_db),
                           user: User = Depends(get_current_user)):
    """Add a new knowledge entry. Tags are auto-generated if left blank."""

    # Merge with existing real entry if editing a system_prompt
    if data.category == "system_prompt":
        virtual_titles = [
            "AI Skill 1 — Analysis / Scoring / Reply Intent",
            "AI Skill 2 — Message Generation (LinkedIn / Email)",
        ]
        if data.title in virtual_titles:
            existing = db.query(KnowledgeBase).filter(
                KnowledgeBase.title == data.title,
                KnowledgeBase.is_active == 1,
            ).first()
            if existing:
                if data.content:
                    existing.content = data.content
                existing.tags = data.tags
                existing.source_url = data.source_url
                db.commit()
                db.refresh(existing)
                return KnowledgeOut.model_validate(existing)

    # Auto-generate tags if user left them blank — fire-and-forget, don't block save
    _auto_tag_result = None
    if not data.tags and data.content:
        import threading
        _need_tag = True
    else:
        _need_tag = False

    kb = KnowledgeBase(
        category=data.category,
        title=data.title,
        content=data.content,
        tags=data.tags,
        source_url=data.source_url,
        is_active=data.is_active,
        source=data.source or "manual",
        confidence=data.confidence or "medium",
    )
    db.add(kb)
    db.commit()
    db.refresh(kb)
    log_audit(db, user, "kb_update", f"kb#{kb.id}", f"Added knowledge entry: {kb.title}")

    if _need_tag:
        _kb_id = kb.id
        _cat, _title, _content = data.category, data.title, data.content
        threading.Thread(
            target=_background_auto_tag,
            args=(_kb_id, _cat, _title, _content),
            daemon=True,
        ).start()

    return KnowledgeOut.model_validate(kb)


@router.post("/classify")
async def classify_knowledge(data: KnowledgeClassifyRequest,
                             user: User = Depends(get_current_user)):
    """AI 分类整理：人工先手写内容，AI 只建议类别/标题/标签，不改写正文。"""
    content = (data.content or "").strip()
    if not content:
        raise HTTPException(status_code=400, detail="Please write the content first, then ask the AI to classify it")

    from services.ai_router import call_simple
    title_hint = (data.title or "").strip()
    cat_hint = (data.category or "").strip()
    prompt = (
        "You are the knowledge-base classifier for an export customer-development system. A user has written a knowledge entry by hand; "
        "classify it ONLY — do not rewrite or expand the body content.\n\n"
        "Available categories (return exactly one of these keys):\n"
        "- product: Product specs\n"
        "- profile: Company positioning\n"
        "- forbidden: Do's and don'ts\n"
        "- guidelines: Strategy guidelines\n"
        "- case_study: Case study\n"
        "- system_prompt: System prompt (AI behavior control)\n\n"
        "Title already filled by user: " + (title_hint or "(empty)") + "\n"
        "Category already selected by user: " + (cat_hint or "(empty)") + "\n"
        "Body content:\n" + content[:2500] + "\n\n"
        "Return only one JSON object (no markdown fences, no other text):\n"
        '{"category":"product","title":"short clear title","tags":["tag1","tag2","tag3"],"suggestions":["suggestion1","suggestion2"]}\n'
        "Requirements:\n"
        "1. category must be one of the 6 keys above; pick the obvious one if the content clearly fits, "
        "otherwise keep the user's chosen category; when unsure, choose guidelines.\n"
        "2. title should summarize the entry in one short phrase (under 30 words); reuse the user's title if provided and suitable.\n"
        "3. tags: generate 3-6 English tags (lowercase) useful for search, e.g. tolerances, lead-time, Germany, pricing.\n"
        "4. suggestions: give 2-4 improvement suggestions for the body (suggestions only — do not rewrite it), "
        "e.g. add certifications/specs/quantities/lead time, make casual wording more formal, add target-customer context, or restructure for easier retrieval."
    )
    try:
        raw = await call_simple(prompt, temperature=0.2, max_tokens=512)
    except Exception as exc:
        raise HTTPException(status_code=502, detail="AI call failed: " + str(exc))

    import re as _re
    if "```" in raw:
        m = _re.search(r"```(?:json)?\s*\n?(.*?)\n?```", raw, _re.DOTALL)
        raw = m.group(1).strip() if m else raw
    try:
        result = json.loads(raw)
    except Exception:
        raise HTTPException(status_code=502, detail="AI response could not be parsed — please retry")

    valid_cats = {"product", "profile", "forbidden", "guidelines", "case_study", "system_prompt"}
    cat = str(result.get("category") or cat_hint or "guidelines").strip()
    if cat not in valid_cats:
        cat = cat_hint if cat_hint in valid_cats else "guidelines"
    title = str(result.get("title") or title_hint or "").strip()[:60]
    tags = result.get("tags")
    if not isinstance(tags, list):
        tags = []
    tags = [str(t).strip() for t in tags if str(t).strip()][:6]
    sugs = result.get("suggestions")
    if not isinstance(sugs, list):
        sugs = []
    sugs = [str(s).strip() for s in sugs if str(s).strip()][:4]
    return {"success": True, "result": {"category": cat, "title": title, "tags": tags, "suggestions": sugs}}


def _background_auto_tag(kb_id: int, category: str, title: str, content: str):
    """Attempt auto-tagging via Gemini in background. Silently fails if Gemini unavailable."""
    from database import SessionLocal as SL
    try:
        tags_json = _auto_tag(category, title, content)
        if not tags_json:
            return
        db2 = SL()
        try:
            kb = db2.query(KnowledgeBase).filter(KnowledgeBase.id == kb_id).first()
            if kb:
                kb.tags = tags_json
                db2.commit()
                logger.info("Auto-tagged kb #%d", kb_id)
        finally:
            db2.close()
    except Exception:
        pass  # Never break the user experience


def _auto_tag(category: str, title: str, content: str) -> str:
    """Use Gemini to generate relevant Chinese/English tags from the knowledge content.
    Returns a JSON array string like '["公差","交期","认证"]'.
    """
    from services.ai_router import call_simple_sync as call_simple

    prompt = """You are tagging a knowledge base entry for a B2B export sales engine.

Category: """ + category + """
Title: """ + title + """

Content:
""" + content[:2000] + """

Generate 3-6 English tags (lowercase) that describe what this entry is about. Tags are used for search, so include:
- Technical terms mentioned (e.g. tolerance, lead-time, certification)
- Customer regions if relevant (e.g. germany, usa, eu)
- Use case (e.g. negotiation, pricing, sampling, lead-time)

Return ONLY a JSON array of strings, nothing else. Example: ["tolerance","lead-time","germany"]"""

    raw = call_simple(prompt, temperature=0.3, max_tokens=256)
    # Strip markdown fences
    import re
    if "```" in raw:
        m = re.search(r"```(?:json)?\s*\n?(.*?)\n?```", raw, re.DOTALL)
        raw = m.group(1).strip() if m else raw
    tags = json.loads(raw)
    if isinstance(tags, list) and all(isinstance(t, str) for t in tags):
        return json.dumps(tags, ensure_ascii=False)
    return None


@router.put("/{kb_id}")
async def update_knowledge(kb_id: int, data: KnowledgeUpdate, db: Session = Depends(get_db),
                           user: User = Depends(get_current_user)):
    """Update a knowledge entry. Virtual IDs get auto-created as real entries."""
    if kb_id < 0:
        # Virtual entry — create it as a real DB entry
        _load_virtual_skill_entries()
        ve = next((v for v in VIRTUAL_SKILL_ENTRIES if v["id"] == kb_id), None)
        if not ve:
            raise HTTPException(status_code=404, detail="Virtual entry not found")
        kb = KnowledgeBase(
            category=data.category or ve["category"],
            title=data.title or ve["title"],
            content=data.content or ve["content"],
            tags=data.tags or ve["tags"],
            source_url=data.source_url,
            is_active=data.is_active if data.is_active is not None else 1,
        )
        db.add(kb)
        db.commit()
        db.refresh(kb)
        return KnowledgeOut.model_validate(kb)

    kb = db.query(KnowledgeBase).filter(KnowledgeBase.id == kb_id).first()
    if not kb:
        raise HTTPException(status_code=404, detail="Knowledge entry not found")

    # Auto-tag if tags explicitly cleared — fire-and-forget background
    if data.tags is not None and not data.tags and (data.content or kb.content):
        _kb_id_up = kb.id
        _cat_up = data.category or kb.category
        _title_up = data.title or kb.title
        _content_up = data.content or kb.content
        import threading
        threading.Thread(
            target=_background_auto_tag,
            args=(_kb_id_up, _cat_up, _title_up, _content_up),
            daemon=True,
        ).start()

    for key, val in data.model_dump(exclude_unset=True).items():
        setattr(kb, key, val)
    knowledge_engine.save_history(db, kb)  # snapshot before edit
    kb.updated_at = datetime.utcnow()
    db.commit()
    db.refresh(kb)
    log_audit(db, user, "kb_update", f"kb#{kb.id}", f"Modified knowledge entry: {kb.title}")
    return KnowledgeOut.model_validate(kb)


@router.delete("/{kb_id}")
async def delete_knowledge(kb_id: int, db: Session = Depends(get_db),
                           user: User = Depends(get_current_user)):
    """Soft-delete a knowledge entry. Virtual entries can't be deleted."""
    if kb_id < 0:
        return {"ok": True, "virtual": True}
    kb = db.query(KnowledgeBase).filter(KnowledgeBase.id == kb_id).first()
    if not kb:
        raise HTTPException(status_code=404, detail="Knowledge entry not found")
    kb.is_active = 0
    kb.updated_at = datetime.utcnow()
    db.commit()
    log_audit(db, user, "kb_update", f"kb#{kb_id}", f"Deleted knowledge entry: {kb.title}")
    return {"ok": True}


# ── Self-evolution: coverage & gaps ─────────────────────────

@router.get("/coverage")
async def coverage(db: Session = Depends(get_db)):
    """Knowledge health: per-category coverage score + open gaps."""
    return knowledge_engine.coverage_report(db)


@router.get("/gaps")
async def list_gaps(
    status: str | None = Query(None, pattern="^(open|resolved|ignored)$"),
    db: Session = Depends(get_db),
):
    q = db.query(KnowledgeGap)
    if status:
        q = q.filter(KnowledgeGap.status == status)
    rows = q.order_by(KnowledgeGap.created_at.asc()).all()
    return [
        {
            "id": g.id,
            "category": g.category,
            "question": g.question,
            "reason": g.reason,
            "source": g.source,
            "status": g.status,
            "note": g.note,
            "created_at": g.created_at.isoformat() if g.created_at else None,
            "resolved_at": g.resolved_at.isoformat() if g.resolved_at else None,
        }
        for g in rows
    ]


@router.post("/gaps")
async def create_gap(data: KnowledgeGapCreate, db: Session = Depends(get_db)):
    added = knowledge_engine.ensure_gap(db, data.category, data.question, data.reason, source=data.source)
    return {"added": added}


@router.post("/gaps/{gap_id}/resolve")
async def resolve_gap(gap_id: int, data: KnowledgeGapResolve = None, db: Session = Depends(get_db)):
    gap = db.query(KnowledgeGap).filter(KnowledgeGap.id == gap_id).first()
    if not gap:
        raise HTTPException(status_code=404, detail="Gap not found")
    gap.status = "resolved"
    gap.resolved_at = datetime.utcnow()
    gap.note = data.note if data else None
    db.commit()
    return {"ok": True}


@router.post("/gaps/{gap_id}/ignore")
async def ignore_gap(gap_id: int, data: KnowledgeGapResolve = None, db: Session = Depends(get_db)):
    gap = db.query(KnowledgeGap).filter(KnowledgeGap.id == gap_id).first()
    if not gap:
        raise HTTPException(status_code=404, detail="Gap not found")
    gap.status = "ignored"
    gap.resolved_at = datetime.utcnow()
    gap.note = data.note if data else "Manually ignored"
    db.commit()
    return {"ok": True}


@router.post("/suggest")
async def suggest(data: KnowledgeSuggestRequest = None, db: Session = Depends(get_db)):
    """AI suggests the next questions the customer should answer."""
    limit = data.limit if data else 5
    return {"questions": knowledge_engine.suggest_questions(db, limit=limit)}


@router.post("/draft")
async def draft(data: KnowledgeDraftRequest, db: Session = Depends(get_db)):
    """AI polishes raw customer input into a ready-to-save knowledge entry."""
    return knowledge_engine.generate_draft(db, data.category, data.raw, data.title_hint)


@router.get("/profile-coach")
async def profile_coach_questions(db: Session = Depends(get_db)):
    """客户画像教练：引导问题 + 教学说明（框架 = 用户自定义的画像分类）。"""
    coach = knowledge_engine.PROFILE_COACH
    cats = load_profile_categories(db)
    framework = []
    total = len(cats)
    for idx, c in enumerate(cats):
        tier = str(idx + 1)
        if idx == 0:
            example = "Highest priority: clearest demand, highest order value, strongest repeat purchase"
        elif idx == total - 1:
            example = "Lowest priority: still worth contacting, but no proactive investment"
        elif idx == 1:
            example = "Second priority: slightly weaker in size or repeat purchase, still worth proactive outreach"
        else:
            example = "Middle tier: opportunity exists but needs nurturing"
        framework.append({"tier": tier, "who": c.get("label", ""), "example": example})
    questions = []
    for q in coach["questions"]:
        q2 = dict(q)
        if q.get("key") == "priority":
            labels = ", ".join(str(c.get("label", "")) for c in cats)
            q2["hint"] = "Sort customers into your profile tiers by priority: " + labels + " (fill the tiers you have; note any that don't apply)"
        questions.append(q2)
    framework_note = (
        "Below are your custom customer-profile tiers (adjust them in System Settings → Customer Profile Tiers). "
        "They are ordered by priority from top to bottom: tier 1 is developed first."
    )
    return {"intro": coach["intro"], "framework_note": framework_note,
            "roles": coach.get("roles", []),
            "framework": framework, "questions": questions}


@router.post("/profile-coach")
async def profile_coach(data: ProfileCoachRequest, db: Session = Depends(get_db),
                        user: User = Depends(get_current_user)):
    """AI 根据客户回答生成客户画像与策略草稿。"""
    draft = knowledge_engine.generate_profile_draft(db, data.answers)
    log_audit(db, user, "kb_update", None, f"Generated profile-coach draft: {draft['title']}")
    return draft


@router.post("/profile-review")
async def profile_review(db: Session = Depends(get_db),
                         user: User = Depends(get_current_user)):
    """数据驱动的画像体检：按画像分类统计真实表现，AI 归纳修订建议并记入缺口。"""
    suggestions = knowledge_engine.profile_performance_review(db)
    return {"ok": True, "suggestions": suggestions}


@router.post("/from-case")
async def from_case(limit: int = Query(3, ge=1, le=6), db: Session = Depends(get_db)):
    """Learn reusable knowledge from real outcomes (won / sample / positive)."""
    return {"candidates": knowledge_engine.extract_candidates(db, limit=limit)}


# ── Onboarding wizard progress ──────────────────────────────

def _get_setting(db: Session, key: str, default: str = "") -> str:
    row = db.query(SystemSetting).filter(SystemSetting.key == key).first()
    return row.value if row else default


def _set_setting(db: Session, key: str, value: str):
    row = db.query(SystemSetting).filter(SystemSetting.key == key).first()
    if row:
        row.value = value
        row.updated_at = datetime.utcnow()
    else:
        db.add(SystemSetting(key=key, value=value))
    db.commit()


@router.get("/onboarding")
async def onboarding_status(db: Session = Depends(get_db)):
    import json as _json
    raw = _get_setting(db, "kb_onboarding_steps", "{}")
    try:
        steps = _json.loads(raw)
    except Exception:
        steps = {}
    complete = _get_setting(db, "kb_onboarding_complete", "false").lower() == "true"
    return {
        "steps": {
            cat: {"name": meta["name"], "done": bool(steps.get(cat))}
            for cat, meta in knowledge_engine.ESSENTIAL_CATEGORIES.items()
        },
        "complete": complete,
    }


@router.post("/onboarding/step")
async def onboarding_step(payload: dict, db: Session = Depends(get_db)):
    import json as _json
    cat = str(payload.get("category", ""))
    done = bool(payload.get("done", True))
    if cat not in knowledge_engine.ESSENTIAL_CATEGORIES:
        raise HTTPException(status_code=400, detail="Unknown category")
    raw = _get_setting(db, "kb_onboarding_steps", "{}")
    try:
        steps = _json.loads(raw)
    except Exception:
        steps = {}
    steps[cat] = done
    _set_setting(db, "kb_onboarding_steps", _json.dumps(steps, ensure_ascii=False))
    return {"ok": True, "steps": steps}


@router.post("/onboarding/complete")
async def onboarding_complete(db: Session = Depends(get_db)):
    _set_setting(db, "kb_onboarding_complete", "true")
    return {"ok": True, "complete": True}


# ── Version history & rollback ──────────────────────────────

@router.get("/{kb_id}/history")
async def kb_history(kb_id: int, db: Session = Depends(get_db)):
    return {"history": knowledge_engine.history_for(db, kb_id)}


@router.post("/{kb_id}/restore/{history_id}")
async def kb_restore(kb_id: int, history_id: int, db: Session = Depends(get_db)):
    ok = knowledge_engine.restore_version(db, kb_id, history_id)
    if not ok:
        raise HTTPException(status_code=404, detail="Version not found")
    kb = db.query(KnowledgeBase).filter(KnowledgeBase.id == kb_id).first()
    return KnowledgeOut.model_validate(kb)
