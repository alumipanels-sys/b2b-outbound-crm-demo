"""Shared writing rules used across all AI copy generation entry points.
Imported by case_intelligence.py (message generator) and followup_engine.py (smart follow-up).
"""
import logging
import re as _re
from sqlalchemy.orm import Session

logger = logging.getLogger(__name__)


def load_writing_rules(db: Session) -> str:
    """Load writing rules from knowledge_base (forbidden + guidelines categories)."""
    from models import KnowledgeBase

    entries = (
        db.query(KnowledgeBase)
        .filter(
            KnowledgeBase.category.in_(["forbidden", "guidelines"]),
            KnowledgeBase.is_active == 1,
        )
        .all()
    )
    text = ""
    for e in entries:
        text += f"\n### {e.title}\n{(e.content or '')[:600]}\n"
    return text


# ── Spec guidance: product facts come from the customer knowledge base ──
SPEC_LINE = """Product spec rules: only use real parameters from the customer knowledge base [Product specifications]; never invent or guess any spec figures."""


# ── Core writing rules (condensed from skills/skill_2_generation.py) ──
WRITING_RULES = """COLD OUTREACH WRITING RULES (STRICT — violate and the message is useless):

1. ONE MESSAGE = ONE HOOK. Pick the SINGLE most relevant angle for this prospect. Do NOT list multiple features or specs — that's a data sheet, not an outreach message.
   → PICK ONE spec from the product specs above. ONE. Do NOT mention ISO, capacity, centration, or surface quality unless they are THE hook.
   → If you picked tolerance as the hook, say the tolerance number and ONE value implication ("zero time on adjustments"). Stop. Move to CTA.
2. Short: email max 70-90 words, LinkedIn max 300 chars, WhatsApp max 200 chars.
3. Lead with THEIR pain or context, not our product. Open by referencing something specific about them.
4. No ChatGPT phrases: NEVER "I hope this email finds you well", "please don't hesitate", "looking forward to hearing from you", "I wanted to reach out", "I was wondering if".
5. No generic claims: never say "high quality", "best price", "leading manufacturer".
6. Use concrete numbers: one spec is worth 10 adjectives.
7. Voice: Chinese export engineer — slightly imperfect but clear English, warm and humble, like an engineer having a chat. Write as "I" not "we" (the reader is talking to the salesperson, not the company).
8. CTA: low-friction, no pressure. Use: "Worth a look?", "Happy to send specs if useful.", "Can send a sample if you want to test.", "No worries if not — just thought it might fit."
9. Close natural: "Best," or "Cheers," — never "Best regards" or "Sincerely".
10. Do NOT use bullets or numbered lists in the body — natural paragraphs only.
11. Do NOT repeat yourself. Each sentence carries new information.
12. STRUCTURE: Three beats only — (1) Their context/pain OR straight-to-hook if no real intel, (2) One spec + one implication, (3) One CTA. Nothing more.
13. CRITICAL — No fake personalization: If you don't have real intelligence about this specific company (their projects, pain points, hiring, news), do NOT invent it. Open with a direct low-pressure technical question instead. A one-line company positioning is allowed after the opening sentence, in the format: category + origin + manufacturing attribute (e.g. "China-based precision rod lens blank manufacturer"). Never open with self-introduction or company positioning, and never mention founding year, factory area, slogans or vision. Better to be direct than to fake familiarity.
14. NO ATTACHMENT MENTIONS — Never mention "attachment", "attached file", "see attached", "enclosed", or any attachment wording in ANY outreach message. Cold emails with attachment language get flagged as spam immediately. If you need to offer a spec sheet or catalog, say "can send" or "happy to share" without mentioning the word 'attachment'. For example: "Can send our spec sheet if useful" is OK, but "Please see the attached spec sheet" is FORBIDDEN.
15. ENGLISH ONLY — Write the message in English only. Never use Chinese characters, Pinyin, or section labels such as "Paragraph 1 —" in the body. The body must be plain, ready-to-send English text."""


def get_full_rules(db: Session) -> str:
    """Return WRITING_RULES + any knowledge_base additions."""
    extra = load_writing_rules(db)
    if extra:
        return WRITING_RULES + f"\n\nADDITIONAL COMPANY RULES (from knowledge base):\n{extra}"
    return WRITING_RULES


def get_spec_line(db: Session) -> str:
    """Product specs from the customer knowledge base (single source of truth)."""
    from models import KnowledgeBase
    entry = (
        db.query(KnowledgeBase)
        .filter(KnowledgeBase.category == "product", KnowledgeBase.is_active == 1)
        .order_by(KnowledgeBase.updated_at.desc())
        .first()
    )
    if entry and (entry.content or "").strip():
        return "Customer product specifications (must use only the facts below; never invent):\n" + entry.content[:2500]
    return SPEC_LINE


def get_spec_and_rules(db: Session) -> str:
    """Full injection block for AI prompts: specs + writing rules."""
    return get_spec_line(db) + "\n\n" + get_full_rules(db)


def sanitize_attachment_language(text: str) -> str:
    """Hard override: strip attachment-related words from AI-generated emails.
    Cold emails mentioning 'attachment', 'attached file', 'enclosed' trigger spam filters.
    Replace with alternative phrasing like 'I can send' / 'happy to share'.
    Also catches attachment wording in other languages.
    """
    # English patterns → safer alternatives
    text = _re.sub(r'(?i)\bplease\s+see\s+(the\s+)?attached\b[^.]*\.', 'Can send the details if useful. ', text)
    text = _re.sub(r'(?i)\bsee\s+attached\b[^.]*\.', 'Can send it if you want. ', text)
    text = _re.sub(r'(?i)\battached\s+is\b[^.]*\.', 'Can share it if useful. ', text)
    text = _re.sub(r'(?i)\b(the\s+)?attached\s+(file|document|pdf|spec|catalog|sheet|brochure)\b', 'our spec sheet', text)
    text = _re.sub(r'(?i)\bI( have|\'ve)?\s+attached\b[^.]*\.', 'I can send our specs if you want. ', text)
    text = _re.sub(r'(?i)\bin\s+the\s+attachment\b', 'if you want it', text)
    text = _re.sub(r'(?i)\benclosed\b[^.]*\.', 'Can share the info. ', text)
    # Clean up double dots
    text = _re.sub(r'\.\s*\.', '.', text)
    return text


def sanitize_tolerance(text: str) -> str:
    """保留接口：规格以知识库为准，不再做行业特定的强制替换。"""
    return text


# ── 发送前拦截：首轮开发信禁止自我介绍开头 ──
SELF_INTRO_OPENING_PATTERNS = (
    r"\bI am [A-Za-z][A-Za-z .'-]* from\b",
    r"\bI'm [A-Za-z][A-Za-z .'-]* from\b",
    r"\bI work with\b",
    r"\bour company\b",
    r"\bSales Manager\b",
    r"\bWe manufacture\b",
    r"\bWe specialize\b",
    r"\bOur company\b",
    r"\bOur core competency\b",
    r"\bI am reaching out\b",
    r"\bI wanted to introduce\b",
    r"\bWe('ve| have) been supplying\b",
    r"\bI handle international trade\b",
    r"\bI run a workshop\b",
)
REPLY_SUBJECT_PREFIXES = ("re:", "aw:", "fw:", "fwd:")


def _split_sentences(text: str) -> list[str]:
    return [s.strip() for s in _re.split(r"(?<=[.!?])\s+", text.strip()) if s.strip()]


def self_intro_opening_warning(body: str, subject: str = "") -> str:
    """Return a warning when a first-touch outreach opens with self-introduction."""
    if not body:
        return ""
    subj = (subject or "").strip().lower()
    if any(subj.startswith(p) for p in REPLY_SUBJECT_PREFIXES):
        return ""

    text = body or ""
    text = _re.sub(r"(?i)<br\s*/?>", "\n", text)
    text = _re.sub(r"(?i)</(p|div|tr|li)>", "\n", text)
    text = _re.sub(r"<[^>]+>", " ", text)
    text = text.replace("&nbsp;", " ").replace("&amp;", "&")
    paras = [p.strip() for p in _re.split(r"\n\s*\n", text) if p.strip()]

    first = ""
    for para in paras:
        if _re.match(r"^(hi|hello|hey|dear|good (morning|afternoon|evening))\b", para, _re.I) and len(para) <= 80:
            continue
        sentences = _split_sentences(para)
        if sentences:
            first = sentences[0]
        break
    if not first:
        return ""

    for pat in SELF_INTRO_OPENING_PATTERNS:
        if _re.search(pat, first, _re.I):
            return (
                f"First outreach email starts with a self-introduction ({first[:80]}). "
                "Rewrite to open with their context/pain point, or ask one concrete question."
            )
    return ""
