"""Gemini API service - Skill 1 (analysis) and Skill 2 (generation).

Key support (Google 2026 变更):
- 旧格式 AIza 开头 key：沿用 REST (HTTP POST)，代理优先、直连兜底（行为不变）。
- 新格式 AQ. 开头 key：走官方 google-genai SDK（老 REST 接口对 AQ. key 返回 401）。
"""

import json
import logging
import os
import re

import httpx

from config import GEMINI_API_KEY, GEMINI_PROXY
from database import SessionLocal
from models import KnowledgeBase
from skills.skill_1_analysis import SKILL_1_SYSTEM_PROMPT
from skills.skill_2_generation import SKILL_2_SYSTEM_PROMPT
from services.ai_router import get_voice_rules, get_signature_for_profile

logger = logging.getLogger(__name__)

GEMINI_URL = f"https://generativelanguage.googleapis.com/v1beta/models/gemini-2.5-flash:generateContent?key={GEMINI_API_KEY}"
GEMINI_MODEL = "gemini-2.5-flash"


def _is_new_key() -> bool:
    """Google 新格式 key 以 AQ. 开头，老 REST 接口不认，需走官方 SDK。"""
    return str(GEMINI_API_KEY or "").strip().startswith("AQ.")


_sdk_client = None


def _get_sdk_client():
    """Create (once) the official google-genai client. Proxy via httpx_client."""
    global _sdk_client
    if _sdk_client is None:
        from google.genai import Client, types as genai_types
        opts = {}
        if GEMINI_PROXY:
            opts["httpx_client"] = httpx.Client(proxy=GEMINI_PROXY, timeout=120)
        _sdk_client = Client(api_key=GEMINI_API_KEY,
                             http_options=genai_types.HttpOptions(**opts))
    return _sdk_client


def _call_gemini_sdk(body: dict, timeout: int = 60) -> str:
    """Call Gemini via official google-genai SDK — supports new AQ. keys."""
    from google.genai import types as genai_types
    client = _get_sdk_client()
    contents = body.get("contents") or []
    parts = []
    if contents:
        for p in (contents[0].get("parts") or []):
            if "text" in p:
                parts.append(genai_types.Part(text=p["text"]))
            elif "inlineData" in p:
                d = p["inlineData"]
                parts.append(genai_types.Part(inline_data=genai_types.Blob(
                    mime_type=d.get("mimeType", "image/png"), data=d.get("data", ""))))
    gc = body.get("generationConfig") or {}
    cfg = genai_types.GenerateContentConfig(
        temperature=gc.get("temperature"),
        max_output_tokens=gc.get("maxOutputTokens", 2048),
    )
    resp = client.models.generate_content(
        model=GEMINI_MODEL,
        contents=genai_types.Content(parts=parts) if parts else "Say hello",
        config=cfg,
    )
    if not resp.text:
        raise RuntimeError("Gemini SDK returned empty response")
    return resp.text


def _call_gemini_http(body: dict, timeout: int = 60) -> str:
    """Gemini call — AQ. keys via official SDK, legacy AIza via REST."""
    if _is_new_key():
        return _call_gemini_sdk(body, timeout=timeout)

    # ── legacy REST path (AIza keys) — proxy first, direct fallback ──
    errors = []
    if GEMINI_PROXY:
        try:
            resp = httpx.post(GEMINI_URL, json=body, timeout=8, proxy=GEMINI_PROXY)
            resp.raise_for_status()
            return resp.json()["candidates"][0]["content"]["parts"][0]["text"]
        except Exception as e:
            errors.append(f"proxy: {e}")
            logger.warning("Gemini proxy failed (%s), trying direct...", e)
    try:
        resp = httpx.post(GEMINI_URL, json=body, timeout=timeout)
        resp.raise_for_status()
        data = resp.json()
        return data["candidates"][0]["content"]["parts"][0]["text"]
    except Exception as e:
        errors.append(f"direct: {e}")
        raise RuntimeError("Gemini call failed — " + "; ".join(errors))


def call_gemini_simple(prompt: str, temperature: float = 0.3, max_tokens: int = 2048) -> str:
    """Quick single-prompt call. Used for extraction / icebreaker tasks."""
    body = {
        "contents": [{"parts": [{"text": prompt}]}],
        "generationConfig": {"temperature": temperature, "maxOutputTokens": max(max_tokens, 4096)},
    }
    return _call_gemini_http(body, timeout=120)


def call_gemini_vision(prompt: str, image_b64: str, mime_type: str = "image/png", temperature: float = 0.3, max_tokens: int = 2048) -> str:
    """Gemini Vision call — send text + image for analysis.
    image_b64: raw base64 string (no data: prefix)
    mime_type: image/png, image/jpeg, image/webp"""
    body = {
        "contents": [{
            "parts": [
                {"text": prompt},
                {"inlineData": {"mimeType": mime_type, "data": image_b64}}
            ]
        }],
        "generationConfig": {"temperature": temperature, "maxOutputTokens": max_tokens},
    }
    return _call_gemini_http(body, timeout=120)


def _load_skill_prompt_from_kb(title: str, fallback: str) -> str:
    # 安全策略：Skill 提示词是系统核心逻辑，一律使用代码内置版本，
    # 不从知识库读取、不允许客户覆盖，防止核心 AI 逻辑泄露/被篡改。
    return fallback


def build_knowledge_context(task_type: str) -> str:
    db = SessionLocal()
    try:
        entries = db.query(KnowledgeBase).filter(
            KnowledgeBase.is_active == 1,
            KnowledgeBase.category != "system_prompt",
        ).all()
        matched = []
        for e in entries:
            if e.category in ("product", "profile", "guidelines", "case_study", "methodology", "tactic", "forbidden"):
                matched.append(f"## [{e.category}] {e.title}\n{e.content}")

        # ── Inject trade show context ──
        try:
            from services.trade_show_calendar import get_show_context_for_prospect
            show_ctx = get_show_context_for_prospect()
            if show_ctx and "No major trade shows" not in show_ctx:
                matched.append(f"## [trade_shows] Current Trade Show Calendar\n{show_ctx}")
        except Exception:
            pass

        return "\n\n".join(matched) if matched else ""
    finally:
        db.close()


def get_active_methodology_ids() -> list:
    """Return IDs of active methodology KB entries currently loaded for generation.
    Used by feedback loop to tag outbound interactions with which methodologies were active."""
    db = SessionLocal()
    try:
        entries = db.query(KnowledgeBase).filter(
            KnowledgeBase.is_active == 1,
            KnowledgeBase.category == "methodology",
        ).all()
        return [e.id for e in entries]
    finally:
        db.close()


def _parse_json(raw: str) -> dict:
    """Parse JSON from AI response. Handles markdown fences, trailing text, and truncation."""
    clean = raw.strip()
    if "```" in clean:
        clean = clean.replace("```json", "").replace("```", "").strip()
    # Extract JSON object via brace-counting (handles arbitrary nesting)
    start = clean.find('{')
    if start >= 0:
        depth = 0
        in_string = False
        escape = False
        for i in range(start, len(clean)):
            c = clean[i]
            if escape:
                escape = False
                continue
            if c == '\\':
                escape = True
                continue
            if c == '"' and not escape:
                in_string = not in_string
                continue
            if in_string:
                continue
            if c == '{':
                depth += 1
            elif c == '}':
                depth -= 1
                if depth == 0:
                    clean = clean[start:i+1]
                    break
    try:
        return json.loads(clean)
    except json.JSONDecodeError:
        pass
    # Fix unescaped control characters INSIDE string values (not in JSON structure).
    # Walk the JSON char-by-char, tracking whether we're inside a string value,
    # and escape any literal \n \r \t that json.loads rejects.
    try:
        fixed = _escape_control_chars_in_strings(clean)
        return json.loads(fixed)
    except (json.JSONDecodeError, Exception):
        pass
    # Last resort: strip trailing lines and re-close braces
    for strip_lines in range(1, 10):
        lines = clean.split('\n')
        if strip_lines >= len(lines):
            break
        truncated = '\n'.join(lines[:-strip_lines]).rstrip(',\n ')
        opens = truncated.count('{') - truncated.count('}')
        try:
            return json.loads(truncated + '}' * max(0, opens))
        except json.JSONDecodeError:
            continue
    logger.warning("Gemini returned unparseable JSON (len=%d): %s", len(raw), raw[:500])
    return {"error": "JSON parse failed", "raw": raw[:500]}


def _escape_control_chars_in_strings(text: str) -> str:
    """Walk through JSON text and escape literal control chars (\n, \r, \t)
    found inside string values, without touching JSON structure characters."""
    result = []
    in_string = False
    escape = False
    for c in text:
        if escape:
            result.append(c)
            escape = False
            continue
        if c == '\\':
            result.append(c)
            escape = True
            continue
        if c == '"':
            in_string = not in_string
            result.append(c)
            continue
        if in_string and c in '\n\r\t':
            esc = {'\n': '\\n', '\r': '\\r', '\t': '\\t'}
            result.append(esc[c])
        else:
            result.append(c)
    return ''.join(result)


# ═══════════════════════════════════════════════
#  Skill 1 — Analysis
# ═══════════════════════════════════════════════

async def call_skill_1_analysis(task_type: str, data: dict) -> dict:
    knowledge = build_knowledge_context(task_type)
    if task_type == "scoring":
        user_prompt = _build_scoring_prompt(data)
    elif task_type == "reply_analysis":
        user_prompt = _build_reply_analysis_prompt(data)
    else:
        return {"error": f"Unknown task_type: {task_type}"}

    full_prompt = _load_skill_prompt_from_kb(
        "冷开发 AI Skill 1 — Analysis / Scoring / Reply Intent", SKILL_1_SYSTEM_PROMPT
    )
    if knowledge:
        full_prompt += f"\n\n## KNOWLEDGE BASE CONTEXT\n{knowledge}"

    combined = full_prompt + "\n\n---\n\n" + user_prompt
    body = {
        "contents": [{"parts": [{"text": combined}]}],
        "generationConfig": {"temperature": 0.7, "maxOutputTokens": 4096},
    }
    logger.info("Skill 1 [%s] — calling Gemini...", task_type)
    try:
        raw = _call_gemini_http(body)
        return _parse_json(raw)
    except Exception as exc:
        logger.exception("Skill 1 failed")
        return {"error": str(exc)}


def _build_scoring_prompt(data: dict) -> str:
    prospect = data.get("prospect", {})
    intelligence = data.get("intelligence", {})
    lines = [
        "## TASK: SCORE THIS PROSPECT",
        f"Company: {prospect.get('company', 'N/A')}",
        f"Website: {prospect.get('website', 'N/A')}",
        f"Country: {prospect.get('country', 'N/A')}",
        f"Size: {prospect.get('size', 'N/A')}",
        f"Industry: {prospect.get('industry', 'N/A')}",
        f"Note: {prospect.get('note', 'N/A')}",
    ]
    wp = intelligence.get("website_key_points", "")
    if wp:
        lines.append(f"\nWebsite Key Points:\n{wp}")
    hs = intelligence.get("hiring_signals", "")
    if hs:
        lines.append(f"\nHiring Signals:\n{hs}")
    lc = intelligence.get("linkedin_content", "")
    if lc:
        lines.append(f"\nLinkedIn Content:\n{lc[:1500]}")

    # CRITICAL: Explicit output format requirements — DeepSeek ignores system-prompt format without this
    lines.append("\n\n## REQUIRED OUTPUT FORMAT")
    lines.append("You MUST return a complete JSON object with ALL fields below. Do NOT return a simplified version. EVERY dimension must have a `score` number and a `reason` string in Chinese.")
    lines.append("```json")
    lines.append("{")
    lines.append('  "profileType": "A|B|C|D|E|EXCLUDE",')
    lines.append('  "totalScore": 0-100,')
    lines.append('  "scoreBreakdown": {')
    lines.append('    "companyProfileFit": {"score": 0-30, "reason": "Chinese: why this profile, evidence from their business"},')
    lines.append('    "scaleCapability": {"score": 0-15, "reason": "Chinese: staff size, real operations vs shell company"},')
    lines.append('    "purchaseIntent": {"score": 0-25, "reason": "Chinese: specific signals found or missing"},')
    lines.append('    "geographicPriority": {"score": 0-15, "reason": "Chinese: why this country/region matters for the company"},')
    lines.append('    "contactability": {"score": 0-15, "reason": "Chinese: available channels and recommended approach"}')
    lines.append("  },")
    lines.append('  "valueLevel": "HIGH|MID|LOW|DEPRIORITIZE",')
    lines.append('  "scoreSummary": "2-3 sentence overall assessment in Chinese",')
    lines.append('  "redFlags": ["any exclusion flags"],')
    lines.append('  "recommendedAction": "specific next step in Chinese with recommended channel and timing"')
    lines.append("}")
    lines.append("```")
    lines.append("\nReturn ONLY the JSON object — no markdown fences, no extra text.")
    return "\n".join(lines)


def _build_reply_analysis_prompt(data: dict) -> str:
    interaction = data.get("interaction", {})
    prospect = data.get("prospect", {})
    return (
        "## TASK: ANALYZE THIS CUSTOMER REPLY\n\n"
        f"Company: {prospect.get('company', 'N/A')}\n"
        f"Profile: {prospect.get('profile_type', 'Unknown')}\n"
        f"Subject: {interaction.get('subject', 'N/A')}\n"
        f"Content: {interaction.get('content', 'N/A')}\n\n"
        "将客户回复分类为以下7种类型之一（按客户实际诉求分类，不是情绪标签）：\n"
        "- 信息型 (INFORMATION_REQUEST): 询问规格、目录、起订量、交期、认证\n"
        "- 价格型 (PRICING): 索要报价、价格单、折扣、付款条件\n"
        "- 样品型 (SAMPLE): 要求寄样、询问样品政策、先评估质量\n"
        "- 资质型 (QUALIFICATION): 要求ISO证书、工厂审核、合规文件、公司背景\n"
        "- 合作型 (COOPERATION): 表达真实兴趣、讨论具体项目、准备推进\n"
        "- 拒绝型 (REJECTION): 不感兴趣、已有供应商、时机不对、价格太高\n"
        "- 转介绍型 (REFERRAL): 转发给正确的人/部门，抄送采购\n\n"
        "只返回有效JSON，格式如下（不要markdown，不要多余文字）。CRITICAL: draftSuggestion字段必须有值，不能为空字符串。\n"
        "{\n"
        '  "replyIntent": "INFORMATION_REQUEST|PRICING|SAMPLE|QUALIFICATION|COOPERATION|REJECTION|REFERRAL",\n'
        '  "sentimentScore": 1-10,\n'
        '  "keySignals": ["关键信号1", "关键信号2 — 用中文"],\n'
        '  "suggestedNextAction": "具体的下一步建议（中文，给出可执行的行动方案）",\n'
        '  "suggestedChannel": "email|linkedin|phone|whatsapp",\n'
        '  "suggestedTiming": "建议跟进时间，如：24小时内 / 3天内 / 1周内",\n'
        '  "draftSuggestion": "完整的回复草稿（匹配客户用的语言。客户写英文则英文回复，客户写中文则中文回复，客户写繁體中文则繁體中文回复。根据回复类型：信息型→提供规格；报价型→给出价格框架；样品型→说明样品政策；资质型→列出认证；合作型→提出下一步；拒绝型→保持礼貌留后路；转介绍型→询问对接人）"\n'
        "}\n\n"
        "重要：回复中的所有字段（keySignals、suggestedNextAction）用中文，draftSuggestion用客户的原语言。\n"
        "语言匹配规则（CRITICAL）: 客户用什么语言写邮件，就用什么语言回复。\n"
        "- 客户写简体中文 → 回复简体中文\n"
        "- 客户写繁體中文 → 回复繁體中文（保持同样的用词和书写习惯）\n"
        "- 客户写英文 → 回复英文\n"
        "- 客户写德语 → 回复德语\n"
        "- 客户用其他语言 → 用同样语言回复\n"
        "不要用markdown代码块包裹。"
    )


# ═══════════════════════════════════════════════
#  Skill 2 — Generation
# ═══════════════════════════════════════════════

async def call_skill_2_generation(message_type: str, data: dict) -> dict:
    knowledge = build_knowledge_context(message_type)
    user_prompt = _build_generation_prompt(message_type, data)
    full_prompt = _load_skill_prompt_from_kb(
        "冷开发 AI Skill 2 — Message Generation (LinkedIn / Email)", SKILL_2_SYSTEM_PROMPT
    )
    if knowledge:
        full_prompt += f"\n\n## KNOWLEDGE BASE CONTEXT\n{knowledge}"

    combined = full_prompt + "\n\n---\n\n" + user_prompt
    body = {
        "contents": [{"parts": [{"text": combined}]}],
        "generationConfig": {"temperature": 0.7, "maxOutputTokens": 4096},
    }
    logger.info("Skill 2 [%s] — calling Gemini...", message_type)
    try:
        raw = _call_gemini_http(body)
        return _parse_json(raw)
    except Exception as exc:
        logger.exception("Skill 2 failed")
        return {"error": str(exc)}


def _build_generation_prompt(message_type: str, data: dict) -> str:
    prospect = data.get("prospect", {})
    intelligence = data.get("intelligence", {})
    tone = data.get("tone", "formal")
    dm = prospect.get("decision_maker") or prospect.get("contact") or "there"

    lines = [
        f"## TASK: WRITE A {message_type.upper().replace('_', ' ')} MESSAGE",
        f"Message Type: {message_type}",
        f"Tone: {tone}",
        f"Company: {prospect.get('company', 'N/A')}",
        f"Website: {prospect.get('website', 'N/A')}",
        f"Country: {prospect.get('country', 'N/A')}",
        f"Industry: {prospect.get('industry', 'N/A')}",
        f"Profile Type: {prospect.get('profile_type', 'Unknown')} (CRITICAL: adapt message to this profile — see profile-specific tone rules below)",
        f"Decision Maker: {dm}",
    ]

    # Prospect-specific global trade show timing. This makes events part of the
    # customer's follow-up timeline, not a standalone calendar.
    try:
        from services.trade_show_calendar import get_show_context_for_prospect, get_show_icebreaker
        show_ctx = get_show_context_for_prospect(
            country=prospect.get("country"),
            industry=prospect.get("industry"),
            profile_type=prospect.get("profile_type"),
        )
        if show_ctx and "No major trade shows" not in show_ctx:
            lines.append("\nGLOBAL TRADE SHOW TIMING SIGNALS:")
            lines.append(show_ctx)
            icebreaker = get_show_icebreaker(
                country=prospect.get("country"),
                industry=prospect.get("industry"),
                profile_type=prospect.get("profile_type"),
            )
            if icebreaker:
                lines.append("\nRecommended trade-show opening angle:")
                lines.append(icebreaker)
            lines.append(
                "Trade-show rule: use this only as a light timing-based icebreaker. "
                "Never claim the prospect will attend. Never claim the company will attend unless explicitly stated."
            )
    except Exception:
        pass

    # Profile strategy comes from the customer knowledge base — never hardcode industry specifics
    profile = prospect.get('profile_type', '')
    lines.append(
        f"\nPROFILE {profile or '?'} STRATEGY: Use the customer knowledge base's 「客户画像与策略」"
        " to decide how to position this prospect (pain points, pitch angle, tone). "
        "Do NOT rely on training data for industry specifics — the knowledge base is the single source of truth."
    )

    # CRITICAL: Enforce five-paragraph email structure for cold_email and followup types
    if message_type in ("cold_email", "cold_linkedin", "followup_noreply", "followup_softreject", "followup_signal"):
        lines.append("\nREQUIRED EMAIL STRUCTURE (5 paragraphs, no exceptions):\n"
            "Paragraph 1 — 点明来意: State who you are ({{COMPANY}}) and why you're reaching out. 1-2 sentences, direct.\n"
            "Paragraph 2 — 匹配对方业务: Reference something specific about their company/business. Show you've done homework. Connection must feel earned, not generic.\n"
            "Paragraph 3 — 输出我方价值: Your core differentiator that matters to THEM. Lead with the spec/advantage most relevant to their profile. Use concrete numbers from the customer knowledge base only.\n"
            "Paragraph 4 — 低门槛号召: A single, low-friction next step. 'Would you be open to a 15-minute call?' or 'I can send our catalog and spec sheet — no commitment.' Make it easy to say yes.\n"
            "Paragraph 5 — 简洁收尾: One-line professional close with your name, title, and company. No fluff.\n"
            "IMPORTANT: Every paragraph must be labeled. Return subject + body as separate fields in the JSON. Body must contain exactly 5 labeled paragraphs.")
    else:
        lines.append("\nFORMAT: Return a concise message appropriate for the channel. Adapt tone to profile type above.")
    wp = intelligence.get("website_key_points", "")
    if wp:
        lines.append(f"\nWebsite Key Points:\n{wp}")
    ia = intelligence.get("icebreak_angles", "")
    if ia:
        lines.append(f"\nIcebreaker Angles:\n{ia}")
    hs = intelligence.get("hiring_signals", "")
    if hs:
        lines.append(f"\nHiring Signals:\n{hs}")
    ac = data.get("additional_context", "")
    if ac:
        lines.append(f"\nAdditional Context:\n{ac}")
    prev = data.get("previous_interactions", [])
    if prev:
        lines.append("\nPrevious Interactions:")
        for i, p in enumerate(prev[-3:], 1):
            lines.append(f"{i}. [{p.get('direction','')}] {p.get('content','')[:300]}")
    lines.append(
        "\nWrite the message and return valid JSON only.\n"
        "YOU MUST return exactly this JSON format:\n"
        '{"subject": "the email subject line", "body": "the full email body"}\n'
        "No other keys. No markdown fences. Subject and body are REQUIRED.\n\n"
        "CRITICAL — SALUTATION RULES:\n"
        "- Extract the sender name from the original email. Use that exact name in the salutation (e.g., Hi Thomas or Dear Dr. Muller).\n"
        "- If the sender signed with their full name, use their first name for follow-ups unless they use a formal tone.\n"
        "- NEVER use generic placeholders like Dear [Name] or Dear Sir/Madam.\n"
        "- NEVER use ANY name from other emails in the conversation history — only use the name from the CURRENT email being replied to.\n"
        "- LANGUAGE MATCHING (CRITICAL): Reply in the EXACT same language as the customer's email.\n"
        "  * If the customer writes in English -> reply in English\n"
        "  * If the customer writes in German -> reply in German\n"
        "  * If the customer writes in Simplified Chinese (简体中文) -> reply in Simplified Chinese\n"
        "  * If the customer writes in Traditional Chinese (繁體中文) -> reply in Traditional Chinese\n"
        "  * Match not just the language but the script variant (simplified vs traditional Chinese are different!)"
    )
    lines.append(get_voice_rules())
    # Add signature hint if profile_type is available in the data
    profile_type = data.get("prospect", {}).get("profile_type", "")
    if profile_type:
        lines.append("\nEMAIL SIGNATURE TO USE:")
        lines.append(get_signature_for_profile(profile_type))
    return "\n".join(lines)
