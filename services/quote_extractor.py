"""AI 报价/询盘提取服务 — 从邮件/互动记录中自动识别并结构化归档。

工作方式：
  - inbound（客户来信）→ 识别"询盘"（要报价/问价格/要规格）
  - outbound（我方发信）→ 识别"报价"（我方报出的价格）
  两者都写入 quote_history，按客户归档成时间线。

设计原则：AI 提取的只是草稿（ai_extracted=1），业务员在客户详情里可
一键确认/修正；修正后 ai_extracted=0，视为人工确认的记录。
"""

import json
import logging
from datetime import datetime

from database import SessionLocal
from models import Prospect, Interaction, QuoteHistory, Intelligence
from services.ai_router import call_simple_sync

logger = logging.getLogger(__name__)

# 报价触发关键词（我方发信方向）
TRIGGER_KEYWORDS = (
    "quote", "quotation", "price", "pricing", "offer", "usd", "eur",
    "cny", "rmb", "$", "€", "报价", "价格", "单价", "美金", "欧元",
)

# 询盘触发关键词（客户来信方向）
INQUIRY_KEYWORDS = (
    "quote", "quotation", "price", "pricing", "offer", "cost", "spec",
    "moq", "lead time", "delivery time", "catalog", "sample",
    "询价", "报价", "价格", "规格", "起订量", "交期", "样品",
)

EXTRACT_PROMPT_QUOTE = """You are an export quote recording assistant. Below is an email we sent (or a thread containing our outgoing messages).
Decide whether it contains a price quote given to the customer.

Rules:
1. If there is no clear price information, return {{"has_quote": false}}
2. If there is, return JSON (no extra text):
{{
  "has_quote": true,
  "quote_date": "YYYY-MM-DD (email date, or today if absent)",
  "product": "product / item name (if multiple models, list every one completely, separated by ' / ', e.g. Model A / Model B / Model C)",
  "spec": "specification (if multiple models, list the full spec of each model, one per line or separated by ' / ')",
  "qty": "quantity (e.g. 500 pcs; empty if not stated)",
  "unit_price": "unit price (e.g. $8.00, keep the original wording; for multiple models use 'Model A $8 / Model B $12')",
  "total": "total amount (e.g. $4000; empty if not stated)",
  "currency": "currency (USD/EUR/CNY, uppercase)",
  "terms": "payment terms / lead time / remarks (e.g. FOB, 30% deposit, 4 weeks; empty if not stated)",
  "summary": "English summary (2-3 sentences): what was quoted, how many models, the approximate total, and to whom"
}}

Email subject: {subject}
Email date: {date}
Email content:
{content}
"""


EXTRACT_PROMPT_INQUIRY = """You are an export inquiry recording assistant. Below is an email sent by a customer.
Decide whether the customer is making an inquiry (asking for a quote, price, spec sheet, quantity / lead time / MOQ).

Rules:
1. If it is only ordinary communication (order status, shipment, small talk, thanks etc.), return {{"has_inquiry": false}}
2. If it is an inquiry, return JSON (no extra text):
{{
  "has_inquiry": true,
  "inquiry_date": "YYYY-MM-DD (email date, or today if absent)",
  "product": "product / item name the customer asks about (if multiple models, list every one completely, separated by ' / ')",
  "spec": "specifications / models requested (if multiple, list the full spec of each, one per line or separated by ' / ')",
  "qty": "quantity mentioned (e.g. 500 pcs; empty if not stated)",
  "target_price": "target / expected price mentioned (empty if not stated)",
  "terms": "other requirements mentioned (lead time / certification / packaging etc.; empty if not stated)",
  "summary": "English summary (2-3 sentences): what the customer is asking about, how many models, quantity, and whether price / lead time requirements were mentioned"
}}

Email subject: {subject}
Email date: {date}
Email content:
{content}
"""


PANORAMA_PROMPT = """You are a senior export sales analyst. Below is the full email history with one customer over a period (oldest to newest).
Treat it as one ongoing conversation and produce a full "customer dialogue panorama" in English JSON (no extra text):

{{
  "overview": "demand overview: what the customer is really buying, which specs, approximate quantity, buying context (2-3 sentences)",
  "products": [
    {{"name": "product / model (must be the exact name that appears in the emails)", "spec": "full specification (write every size / tolerance / version the customer listed, e.g. 280mm, ventilated)", "qty": "quantity (e.g. 300 pcs; if not stated write 'not specified')", "price_note": "price evolution for this model (e.g. we quoted $8 → customer asked for $6.5 in May; if none, write 'no price discussed')", "extra": "other requirements the customer mentioned for this model (MOQ / certification / packaging etc.; if none, write 'none')"}}
  ],
  "requirements": [
    "every concrete requirement or condition the customer raised, listed one by one (e.g. MOQ, lead time, freight, certification, payment terms, sample request) - be complete"
  ],
  "open_questions": [
    "specific questions the customer asked that we have not answered or resolved yet (e.g. please send drawings, confirm lead time, give volume discount), listed one by one"
  ],
  "commitments": [
    "any commitments we made in the emails (e.g. free samples, lead-time guarantee, price held), listed one by one - important for later negotiation"
  ],
  "price_flow": "price negotiation history: each quote, counter-offer and the customer's expected level (2-3 sentences)",
  "status": "current status: where the negotiation is stuck, who is waiting on whom, and any buying signals (2-3 sentences)",
  "signals": ["key signal 1 (e.g. price comparison / pressing for discount)", "key signal 2 (e.g. decision maker involved)", "key signal 3 (e.g. urgent order)", "key signal 4 (e.g. repeat-purchase intent)"],
  "next_action": "recommended next step: one concrete opening line for the salesperson, tied to real details from the emails (e.g. our quote of Aug 7 was not answered and the customer is still waiting for pricing on the item they asked about)"
}}

Requirements:
- Base everything strictly on the emails; do not invent facts
- products: list at most 10 key products/models with complete specs; if there are more than 10, mention the total count and representative specs in overview
- requirements / open_questions / commitments: list each item completely; better to include more than to miss one
- next_action must be specific - quote the customer's own words or dates; no generic advice

Email history (oldest to newest, {count} emails):
{emails}
"""


def _looks_quote_worthy(content: str, subject: str) -> bool:
    blob = f"{content or ''} {subject or ''}".lower()
    return any(k in blob for k in TRIGGER_KEYWORDS)


def _looks_inquiry_worthy(content: str, subject: str) -> bool:
    blob = f"{content or ''} {subject or ''}".lower()
    return any(k in blob for k in INQUIRY_KEYWORDS)


def _parse_ai_json(text: str) -> dict | None:
    """从 AI 输出里抠出 JSON 对象（兼容代码围栏、前后多余文字、尾逗号）。"""
    if not text:
        return None
    t = text.strip()
    import re as _re
    t = _re.sub(r"```(?:json)?\s*", "", t).replace("```", "").strip()
    try:
        return json.loads(t)
    except Exception:
        s, e = t.find("{"), t.rfind("}")
        if 0 <= s < e:
            try:
                return json.loads(t[s : e + 1])
            except Exception:
                pass
            try:
                from services.deepseek_service import _parse_json
                parsed = _parse_json(t[s : e + 1])
                if isinstance(parsed, dict) and not parsed.get("error"):
                    return parsed
            except Exception:
                pass
    return None


def _already_extracted(db, prospect_id: int, source_id: int) -> bool:
    return (
        db.query(QuoteHistory)
        .filter(
            QuoteHistory.prospect_id == prospect_id,
            QuoteHistory.source_id == source_id,
            QuoteHistory.is_deleted == 0,
        )
        .first()
        is not None
    )


def _extract_one(db, it: Interaction) -> int:
    """单封互动：inbound→询盘，outbound→报价。返回 0/1。"""
    content = (it.content or "")[:6000]
    subject = it.subject or ""
    is_inbound = (it.direction or "") == "inbound"

    if is_inbound:
        if not _looks_inquiry_worthy(content, subject):
            return 0
    else:
        if not _looks_quote_worthy(content, subject):
            return 0

    if _already_extracted(db, it.prospect_id, it.id):
        return 0

    date_str = ""
    if it.interacted_at:
        try:
            date_str = it.interacted_at.strftime("%Y-%m-%d")
        except Exception:
            date_str = ""

    prompt = (EXTRACT_PROMPT_INQUIRY if is_inbound else EXTRACT_PROMPT_QUOTE).format(
        subject=subject[:300],
        date=date_str,
        content=content,
    )
    try:
        raw = call_simple_sync(prompt, temperature=0.1, max_tokens=800)
    except Exception as exc:
        logger.warning("quote extract AI call failed (inter %s): %s", it.id, exc)
        return 0
    data = _parse_ai_json(raw)
    if is_inbound:
        if not data or not data.get("has_inquiry"):
            return 0
    elif not data or not data.get("has_quote"):
        return 0

    prospect = db.query(Prospect).filter(Prospect.id == it.prospect_id).first()
    qh = QuoteHistory(
        tenant_id=prospect.tenant_id if prospect else None,
        owner_user_id=prospect.owner_user_id if prospect else None,
        prospect_id=it.prospect_id,
        direction="inquiry" if is_inbound else "quote",
        source_type="email" if it.channel in ("email", "linkedin") else it.channel,
        source_id=it.id,
        source_subject=subject[:300],
        quote_date=(data.get("inquiry_date" if is_inbound else "quote_date")
                    or date_str or datetime.utcnow().strftime("%Y-%m-%d"))[:10],
        product=(data.get("product") or "")[:200],
        spec=(data.get("spec") or "")[:300],
        qty=(data.get("qty") or "")[:100],
        unit_price=(data.get("target_price" if is_inbound else "unit_price") or "")[:100],
        total=(data.get("total") or "")[:100] if not is_inbound else "",
        currency=(data.get("currency") or "")[:20] if not is_inbound else "",
        terms=(data.get("terms") or "")[:500],
        summary=(data.get("summary") or "")[:500],
        ai_extracted=1,
        ai_raw=raw[:2000],
    )
    db.add(qh)
    db.commit()
    logger.info("Quote extract: +1 %s from interaction %s (prospect %s)",
                "inquiry" if is_inbound else "quote", it.id, it.prospect_id)
    return 1


def extract_quote_from_interaction(interaction_id: int) -> int:
    """对单封互动做询盘/报价提取（新邮件入库时调用，避免全量扫描）。"""
    db = SessionLocal()
    try:
        it = db.query(Interaction).filter(Interaction.id == interaction_id).first()
        if not it or not it.prospect_id:
            return 0
        return _extract_one(db, it)
    except Exception as exc:
        db.rollback()
        logger.exception("quote extract failed for interaction %s: %s", interaction_id, exc)
        return 0
    finally:
        db.close()


def extract_quotes_for_prospect(prospect_id: int, limit: int = 40) -> int:
    """扫描某个客户最近的互动，提取询盘/报价归档。返回新增条数。"""
    db = SessionLocal()
    added = 0
    try:
        prospect = db.query(Prospect).filter(Prospect.id == prospect_id).first()
        if not prospect:
            return 0
        interactions = (
            db.query(Interaction)
            .filter(
                Interaction.prospect_id == prospect_id,
                Interaction.is_deleted == 0 if hasattr(Interaction, "is_deleted") else True,
            )
            .order_by(Interaction.interacted_at.desc())
            .limit(limit)
            .all()
        )
        for it in interactions:
            try:
                added += _extract_one(db, it)
            except Exception as exc:
                logger.warning("extract skip inter %s: %s", it.id, exc)
        db.commit()
        if added:
            logger.info("Quote extract: +%d for prospect %s (%s)", added, prospect_id, prospect.company)
    except Exception as exc:
        db.rollback()
        logger.exception("quote extract failed for prospect %s: %s", prospect_id, exc)
    finally:
        db.close()
    return added


def extract_quotes_for_all(limit_prospects: int = 50) -> int:
    """扫描最近有互动的客户，逐一提取询盘/报价。返回总新增条数。"""
    db = SessionLocal()
    try:
        rows = (
            db.query(Prospect)
            .filter(Prospect.is_deleted == 0)
            .order_by(Prospect.last_edited_at.desc())
            .limit(limit_prospects)
            .all()
        )
    except Exception:
        rows = db.query(Prospect).filter(Prospect.is_deleted == 0).limit(limit_prospects).all()
    finally:
        db.close()
    total = 0
    for p in rows:
        total += extract_quotes_for_prospect(p.id)
    return total


def generate_dialogue_panorama(prospect_id: int) -> dict:
    """扫描客户最近 20 封往来邮件，AI 综合成对话全景，存 intelligence 表。
    返回 {"success": bool, "report": dict|None, "error": str|None}。"""
    db = SessionLocal()
    try:
        prospect = db.query(Prospect).filter(Prospect.id == prospect_id).first()
        if not prospect:
            return {"success": False, "error": "客户不存在"}
        # 取"最近"的 20 封（desc 再反转，保持从旧到新给 AI）
        interactions = (
            db.query(Interaction)
            .filter(
                Interaction.prospect_id == prospect_id,
                Interaction.direction.in_(("inbound", "outbound")),
            )
            .order_by(Interaction.interacted_at.desc())
            .limit(20)
            .all()
        )
        interactions.reverse()
        if len(interactions) < 2:
            return {"success": False, "error": "往来邮件太少（至少 2 封才能综合分析）"}

        email_blocks = []
        for it in interactions:
            who = "客户" if (it.direction or "") == "inbound" else "我方"
            ts = ""
            if it.interacted_at:
                try:
                    ts = it.interacted_at.strftime("%Y-%m-%d")
                except Exception:
                    ts = ""
            body = (it.content or "")[:3000].replace("<br>", "\n").replace("<br/>", "\n")
            email_blocks.append(
                f"--- [{ts}] {who} | {(it.subject or '(无主题)')[:120]} ---\n{body}"
            )
        emails_text = "\n\n".join(email_blocks)
        prompt = PANORAMA_PROMPT.format(count=len(email_blocks), emails=emails_text[:24000])
        try:
            raw = call_simple_sync(prompt, temperature=0.2, max_tokens=6000)
        except Exception as exc:
            logger.warning("panorama AI call failed (prospect %s): %s", prospect_id, exc)
            return {"success": False, "error": f"AI 调用失败: {exc}"}
        report = _parse_ai_json(raw)
        if not report:
            return {"success": False, "error": "AI 返回无法解析"}

        intel = (
            db.query(Intelligence)
            .filter(Intelligence.prospect_id == prospect_id)
            .first()
        )
        if not intel:
            intel = Intelligence(prospect_id=prospect_id, tenant_id=prospect.tenant_id)
            db.add(intel)
        intel.dialogue_panorama = json.dumps(report, ensure_ascii=False)
        intel.dialogue_panorama_at = datetime.utcnow()
        db.commit()
        logger.info("Panorama generated for prospect %s (%s)", prospect_id, prospect.company)
        return {"success": True, "report": report}
    except Exception as exc:
        db.rollback()
        logger.exception("panorama failed for prospect %s: %s", prospect_id, exc)
        return {"success": False, "error": str(exc)}
    finally:
        db.close()
