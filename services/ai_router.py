"""Unified AI router — picks Gemini or DeepSeek based on system_settings.active_model.
Every AI call in the system goes through this module so changing models is transparent.
"""

import json
import logging
import re
from concurrent.futures import ThreadPoolExecutor, TimeoutError as _FutureTimeoutError

from database import SessionLocal
from models import SystemSetting

logger = logging.getLogger(__name__)

# ── Hard timeout for provider calls — prevents a hung AI provider from freezing requests ──
AI_CALL_TIMEOUT = 60
_AI_EXECUTOR = ThreadPoolExecutor(max_workers=4, thread_name_prefix="ai_call")

# ── Anti-AI-voice overlay: injected into ALL generation prompts ──
# FALLBACK — the real rules come from knowledge_base (category='voice')
FALLBACK_VOICE_RULES = """
IMPORTANT WRITING RULES — you MUST follow these:
- NEVER claim we already contacted the customer (e.g. "I sent you a spec sheet last week", "as discussed", "following up on my previous email") unless that contact appears in the interaction history provided above. If there is no history, write as a first-time outreach.
- NEVER invent product specs, sizes, tolerances, certifications, prices, stock levels, trade-show names or deadlines. Use only facts from the Knowledge Base. If no concrete facts exist, keep the message general and ask a question instead.
- Write like an experienced export sales engineer, NOT a native English speaker.
- Use slightly imperfect but clear English. Occasional minor grammar quirks are OK — they prove you're human.
- Do NOT use ChatGPT-style phrases: no "I hope this email finds you well", no "I'd be happy to", no "please don't hesitate", no "looking forward to hearing from you".
- SALUTATION — HARD REQUIREMENT: the email body MUST open with a proper greeting and nothing before it. Never use "Dear", never start with a bare name ("Klaus, ..."), never skip the greeting.
  - If the customer has a name: use ONLY their first name — never the full name or surname. E.g. "Hi Klaus," not "Hi Klaus Weber,".
  - If the customer has no name: "Hi there," or "Hello,".
  - The greeting is its own line, followed by a blank line, then the message. Example:
    Hi Klaus,

    Quick follow-up on the spec sheet...
- Keep sentences practical and direct. Chinese engineers write: "We can do 5mm -0.02~-0.04 tolerance. Delivery 10 days. Let me know if this works." Not: "I am pleased to inform you that our state-of-the-art manufacturing facility is capable of..."
- Use concrete numbers, specs, timelines. Every sentence should carry information.
- Short paragraphs. 2-3 sentences max per paragraph.
- Tone: professional but NOT salesy. You're an engineer who knows the product, not a marketing guy.
- 不要用太地道的英文表达（像母语者写的那种），老外一看就知道是假的——中国人写英文就是带点中国味才真实。
- SIGNATURE: 不要在邮件结尾写署名/签名/公司名/邮箱或任何占位符（如 "Best, [Your Name]"）——系统会自动追加真实签名。

SPAM WORD BLACKLIST — NEVER use these words anywhere (they trigger spam filters and make buyers archive instantly):
  FREE, GUARANTEED, NO OBLIGATION, 100%, WINNER, LIMITED TIME,
  ACT NOW, URGENT, AS SEEN ON, BEST PRICE, LOWEST PRICE,
  CASH BONUS, EXTRA INCOME, INCREASE YOUR, NO COST,
  RISK-FREE, SATISFACTION GUARANTEED, CLICK HERE, BUY NOW,
  ORDER TODAY, SPECIAL OFFER, ONCE IN A LIFETIME, EXCLUSIVE DEAL

SUBJECT LINE RULES:
- 30-50 characters. Question-form subject lines get 15-20% higher open rates.
- Never ALL CAPS. Never spam trigger words.
- Fill ALL placeholders — never let the buyer see "Hi {First.Name}".
- Use one of these strategies: personalized reference, curiosity question, trigger event, value-first, direct+specific.

FOLLOW-UP SEQUENCE RULES (80% of replies come after the 4th touch):
- Day 1: Cold email (80-120 words, pain-point led)
- Day 3: Gentle reminder + 1 new value point (40-60 words)
- Day 7: LinkedIn connection or comment on their post, then DM
- Day 14: New angle or new trigger event (80-120 words)
- Day 30: Breakup email — "still relevant? no problem if not" (50-70 words, HIGHEST reply rate)
- After Day 30 without reply: mark as dormant, do not chase further without a new trigger event.

BUYER TYPE AWARENESS — adjust tone and content based on what kind of buyer they are:
- Retailer / small wholesaler: lead with speed, low MOQ, fast sampling. They decide in days.
- Trading company / intermediary: emphasize stability, margin protection, willingness to be a "behind-the-scenes" supplier. They decide in weeks.
- OEM / brand buyer: lead with R&D capability, certifications (ISO 9001), quality control system, sampling policy. They decide in months.
- Chain store / big-box retail: extreme patience required (6-18 month cycles). Lead with audit readiness, compliance docs, insurance, long-term commitment.
If buyer type is unknown, default to OEM/brand buyer tone for European B2B prospects.

CALL-TO-ACTION RULES:
- Always end with a clear, specific CTA. "Worth 15 minutes?" beats "Let me know what you think."
- Never: "I look forward to hearing from you", "Please feel free to contact me", "Looking forward to your reply"
- Good CTAs: "Does this spec match what you're looking for?", "Shall I send a sample set?", "Quick call Tuesday or Thursday?"

LOST-CUSTOMER REVIVAL:
- After 3+ months of silence: short, no-pressure check-in
- Acknowledge that priorities change: "Still relevant? No worries if not — I'll stop."
- Offer one new angle they haven't heard before (new capability, new spec, new case study)

MULTI-LANGUAGE VARIANTS — for non-English markets, generate a second version per these rules:
| Region | Language | Tone | Salutation |
|--------|----------|------|------------|
| Middle East | Arabic + English | Formal, relationship-first | السيد المحترم |
| Latin America | Spanish + English | Warm, professional | Estimado/a |
| Brazil | Portuguese + English | Warm, personal | Prezado/a |
| DACH (DE/AT/CH) | German + English | Direct, formal | Sehr geehrte/r |
| France | French + English | Formal, polite | Madame, Monsieur |
| Russia/CIS | Russian + English | Formal, direct | Уважаемый/ая |
| Japan | Japanese + English | Very formal, humble | 拝啓 |
| Korea | Korean + English | Formal, respectful | 안녕하세요 |
English version is always canonical; local-language version as supplement. NEVER translate company names, product models, or proper nouns.

NEGOTIATION — 3-step reframe (never compete on price alone):
Step 1 — Reframe comparison: "Our unit price may be X% higher than [competitor], but compare: defect rate A vs B, lead time A vs B, on-time rate A vs B."
Step 2 — Quantify total cost of ownership: show what 1% defect rate actually costs them annually (returns, chargebacks, lost customers).
Step 3 — Non-price concessions: free samples, faster lead time, longer payment terms, first-order free shipping, dedicated account manager.
"""

# ── English-only enforcement (all analysis / scoring / reply outputs) ──
ENGLISH_ONLY_RULE = """

LANGUAGE RULE (STRICT): every output value must be written in English. Never output Chinese characters anywhere in the JSON (keys or values). If the source context is written in Chinese, translate it into English. Company names, product models and personal names may keep their original spelling."""


def _has_chinese(obj) -> bool:
    try:
        return bool(re.search(r"[\u4e00-\u9fff]", json.dumps(obj, ensure_ascii=False, default=str)))
    except Exception:
        return False


def _strip_chinese(obj):
    """Last-resort fallback: remove Chinese characters from a result tree."""
    if isinstance(obj, str):
        return re.sub(r"[\u4e00-\u9fff]+", "", obj).strip()
    if isinstance(obj, list):
        return [_strip_chinese(x) for x in obj]
    if isinstance(obj, dict):
        return {k: _strip_chinese(v) for k, v in obj.items()}
    return obj


def _ensure_english_result(result, model: str):
    """If an AI result contains Chinese, ask the model to translate the JSON to English.
    Falls back to stripping Chinese characters so the UI never shows mixed language."""
    if not isinstance(result, dict) or not _has_chinese(result):
        return result
    try:
        payload = json.dumps(result, ensure_ascii=False, default=str)
        prompt = (
            "Translate every text value in the JSON below into natural, concise English. "
            "Keep all keys and the JSON structure EXACTLY the same. "
            "Return ONLY the JSON object — no prose, no code fences, and absolutely no Chinese characters.\n\n"
            + payload
        )
        raw = call_simple_sync(
            prompt,
            temperature=0.0,
            max_tokens=4096,
            model=model if model in VALID_MODEL_MODES and model != "auto" else "",
        )
        text = str(raw or "").strip()
        if text.startswith("```"):
            text = re.sub(r"^```(?:json)?\s*|\s*```$", "", text).strip()
        start, end = text.find("{"), text.rfind("}")
        if start >= 0 and end > start:
            obj = json.loads(text[start : end + 1])
            if isinstance(obj, dict) and not _has_chinese(obj):
                logger.info("English enforcement: translated a Chinese AI result into English")
                return obj
    except Exception as exc:
        logger.warning("English enforcement translation failed: %s", exc)
    return _strip_chinese(result)


# Runtime voice rules — loaded lazily from knowledge_base, falls back to hardcoded
_RUNTIME_VOICE_RULES = None


def get_voice_rules() -> str:
    """Return voice rules from knowledge_base (category='voice'), or fallback."""
    global _RUNTIME_VOICE_RULES
    if _RUNTIME_VOICE_RULES is not None:
        return _RUNTIME_VOICE_RULES
    try:
        from database import SessionLocal
        from models import KnowledgeBase
        db = SessionLocal()
        row = db.query(KnowledgeBase).filter(
            KnowledgeBase.category == "voice",
            KnowledgeBase.is_active == 1
        ).order_by(KnowledgeBase.updated_at.desc()).first()
        db.close()
        if row and row.content:
            _RUNTIME_VOICE_RULES = row.content
            logger.info("Voice rules loaded from knowledge_base (id=%s)", row.id)
            return _RUNTIME_VOICE_RULES
    except Exception as e:
        logger.warning("Failed to load voice rules from KB: %s", e)
    _RUNTIME_VOICE_RULES = FALLBACK_VOICE_RULES
    return _RUNTIME_VOICE_RULES




# Legacy alias — kept for compatibility, but all code should use get_voice_rules()
HUMAN_VOICE_RULES = FALLBACK_VOICE_RULES  # will be replaced at first call to get_voice_rules()

# ── Email signatures per prospect profile type ──
# Each profile has a different signature, emphasizing what that profile cares about most.

PROFILE_SIGNATURE_A = """{{USER_NAME}} | Export Sales
{{COMPANY}} — Certified Manufacturer
Quality certified | Custom specs OK
{{USER_EMAIL}} | {{WEBSITE}}"""

PROFILE_SIGNATURE_B = """{{USER_NAME}} | Export Sales
{{COMPANY}} — Reliable Supply
Stable quality | Competitive lead time | Sample support
{{USER_EMAIL}} | {{WEBSITE}}"""

PROFILE_SIGNATURE_C = """{{USER_NAME}} | International Sales Manager
{{COMPANY}} — Your Manufacturing Partner
Quality certified | Free sampling | Flexible MOQ · Let's talk
{{USER_EMAIL}} | {{WEBSITE}}"""

PROFILE_SIGNATURE_D = """{{USER_NAME}} | Product Specialist
{{COMPANY}} — Custom Components
Custom specs | Quality guaranteed | Fast sampling
{{USER_EMAIL}} | {{WEBSITE}}"""

PROFILE_SIGNATURE_E = """{{USER_NAME}} | Sales
{{COMPANY}} — Supply Specialists
Small batches OK · Fast shipping · Full range support
{{USER_EMAIL}} | {{WEBSITE}}"""

PROFILE_SIGNATURE_DEFAULT = """{{USER_NAME}} | {{COMPANY}}
Certified Manufacturer
{{USER_EMAIL}} | {{WEBSITE}}"""

# Map profile_type to signature
PROFILE_SIGNATURES = {
    "A": PROFILE_SIGNATURE_A,
    "B": PROFILE_SIGNATURE_B,
    "C": PROFILE_SIGNATURE_C,
    "D": PROFILE_SIGNATURE_D,
    "E": PROFILE_SIGNATURE_E,
}

import contextvars
_sig_user_ctx = contextvars.ContextVar("sig_user", default=None)


def set_signature_user(user) -> None:
    """设置当前请求的签名使用者（每个员工可配自己的签名）。"""
    _sig_user_ctx.set(user)


def _fill_signature_placeholders(sig: str, user) -> str:
    from config import COMPANY_NAME, USER_EMAIL, USER_NAME, WEBSITE
    s = sig or ""
    s = s.replace("{{USER_NAME}}", (user.name if user and user.name else USER_NAME) or "")
    s = s.replace("{{USER_EMAIL}}", (user.email if user and user.email else USER_EMAIL) or "")
    s = s.replace("{{COMPANY}}", COMPANY_NAME or "")
    s = s.replace("{{WEBSITE}}", WEBSITE or "")
    # 兼容单花括号写法 {COMPANY}
    s = s.replace("{USER_NAME}", (user.name if user and user.name else USER_NAME) or "")
    s = s.replace("{USER_EMAIL}", (user.email if user and user.email else USER_EMAIL) or "")
    s = s.replace("{COMPANY}", COMPANY_NAME or "")
    s = s.replace("{WEBSITE}", WEBSITE or "")
    return s


def get_signature_for_profile(profile_type: str) -> str:
    """Return the email signature for a given profile type.
    如果当前用户（业务员）配了自己的签名，优先用他的；否则用画像默认模板。"""
    user = _sig_user_ctx.get()
    if user is not None and getattr(user, "email_signature", None):
        sig = user.email_signature
        if sig.strip():
            return "\n\n" + _fill_signature_placeholders(sig, user)
    # 优先读系统配置里的画像签名（系统配置 → 邮件签名，可自定义）
    try:
        db = SessionLocal()
        try:
            key = "signature_profile_" + (profile_type or "").upper()
            row = db.query(SystemSetting).filter(SystemSetting.key == key).first()
            if row and row.value and row.value.strip():
                return "\n\n" + _fill_signature_placeholders(row.value, user)
            row = db.query(SystemSetting).filter(SystemSetting.key == "signature_profile_DEFAULT").first()
            if row and row.value and row.value.strip():
                return "\n\n" + _fill_signature_placeholders(row.value, user)
        finally:
            db.close()
    except Exception:
        pass
    sig = PROFILE_SIGNATURES.get((profile_type or "").upper())
    if sig:
        return "\n\n" + sig
    return "\n\n" + PROFILE_SIGNATURE_DEFAULT


VALID_MODEL_MODES = ("auto", "deepseek", "openai", "gemini")


def get_active_model() -> str:
    """Read active_model from system_settings table. Defaults to smart auto mode."""
    db = SessionLocal()
    try:
        row = db.query(SystemSetting).filter(SystemSetting.key == "active_model").first()
        if row and row.value in VALID_MODEL_MODES:
            return row.value
    except Exception:
        pass
    finally:
        db.close()
    return "auto"


def set_active_model(model: str) -> bool:
    """Persist the active model choice."""
    if model not in VALID_MODEL_MODES:
        return False
    db = SessionLocal()
    try:
        row = db.query(SystemSetting).filter(SystemSetting.key == "active_model").first()
        if row:
            row.value = model
        else:
            db.add(SystemSetting(key="active_model", value=model))
        db.commit()
        return True
    except Exception as e:
        logger.error("Failed to save active_model: %s", e)
        return False
    finally:
        db.close()


def _openai_available() -> bool:
    try:
        from services.openai_service import has_openai_config
        return has_openai_config()
    except Exception:
        return False


def _key_usable(value) -> bool:
    v = (value or "").strip()
    if not v:
        return False
    return not any(m in v for m in ("你的", "YOUR_", "xxx", "your_", "example"))


def _provider_available(provider: str) -> bool:
    """True if the provider has a real (non-placeholder) key configured."""
    try:
        if provider == "openai":
            return _openai_available()
        from config import DEEPSEEK_API_KEY, GEMINI_API_KEY
        if provider == "deepseek":
            return _key_usable(DEEPSEEK_API_KEY)
        if provider == "gemini":
            return _key_usable(GEMINI_API_KEY)
    except Exception:
        return False
    return False


def _looks_high_value(data: dict | None) -> bool:
    if not isinstance(data, dict):
        return False
    prospect = data.get("prospect") or data.get("prospect_data") or {}
    if isinstance(prospect, dict):
        if str(prospect.get("value_level") or "").upper() == "HIGH":
            return True
        try:
            if float(prospect.get("ai_score") or 0) >= 85:
                return True
        except Exception:
            pass
    blob = str(data).lower()
    return any(x in blob for x in ("sample_address", "pricing", "hot_lead", "purchase order", "quote", "quotation", "sample", "??", "??"))


def choose_model(task_type: str = "simple", data: dict | None = None, final_output: bool = False, model_override: str | None = None) -> str:
    """Choose provider for a task.

    auto = DeepSeek by default, OpenAI for high-value/final-output tasks when configured.
    Falls back to whatever provider actually has a key — customer only needs to fill ONE.
    model_override = per-panel override (deepseek/openai/gemini/auto), takes priority over global setting.
    """
    # Per-panel override takes priority
    if model_override and model_override in ("deepseek", "openai", "gemini"):
        if _provider_available(model_override):
            return model_override
        logger.warning("Override %s has no key; falling back to auto selection", model_override)
    if model_override == "auto":
        pass  # fall through to global setting

    mode = get_active_model()
    if mode != "auto":
        if _provider_available(mode):
            return mode
        logger.warning("Active model %s has no key; falling back to auto selection", mode)

    if _openai_available():
        premium_tasks = {"reply_analysis_premium", "final_polish", "proposal", "pricing", "negotiation"}
        if final_output or task_type in premium_tasks:
            return "openai"
        if task_type == "reply_analysis" and _looks_high_value(data):
            return "openai"
        if task_type in {"cold_email", "linkedin_dm", "follow_up", "email"} and _looks_high_value(data):
            return "openai"
    for provider in ("deepseek", "openai", "gemini"):
        if _provider_available(provider):
            return provider
    return "deepseek"  # no key at all: let the provider raise a clear error


def _sync_provider_call(provider: str, prompt: str, temperature: float, max_tokens: int) -> str:
    if provider == "deepseek":
        from services.deepseek_service import call_deepseek_simple
        return call_deepseek_simple(prompt, temperature=temperature, max_tokens=max_tokens)
    if provider == "openai":
        from services.openai_service import call_openai_simple
        return call_openai_simple(prompt, temperature=temperature, max_tokens=max_tokens)
    from services.gemini_service import call_gemini_simple
    return call_gemini_simple(prompt, temperature=temperature, max_tokens=max_tokens)


def _provider_order(preferred: str) -> list[str]:
    order = [p for p in ("deepseek", "openai", "gemini") if _provider_available(p)]
    if preferred in order:
        order.remove(preferred)
        order.insert(0, preferred)
    return order


def call_simple_sync(prompt: str, temperature: float = 0.3, max_tokens: int = 2048, model: str = "") -> str:
    """Single-prompt call with cross-provider failover.
    Tries the preferred provider, then any other configured provider.
    Pass model='deepseek'/'openai'/'gemini' to override."""
    preferred = model if (model in VALID_MODEL_MODES and model != "auto" and _provider_available(model)) else choose_model("simple")
    last_err = None
    for provider in _provider_order(preferred):
        try:
            logger.info("call_simple -> %s", provider)
            fut = _AI_EXECUTOR.submit(_sync_provider_call, provider, prompt, temperature, max_tokens)
            return fut.result(timeout=AI_CALL_TIMEOUT)
        except _FutureTimeoutError:
            last_err = TimeoutError(f"AI provider {provider} timed out after {AI_CALL_TIMEOUT}s")
            logger.warning("call_simple %s timed out after %ds; trying next provider", provider, AI_CALL_TIMEOUT)
        except Exception as e:
            last_err = e
            logger.warning("call_simple %s failed (%s); trying next provider", provider, e)
    if last_err:
        raise last_err
    raise RuntimeError("No AI provider available — please configure at least one API key in System Settings")


async def call_skill_1_analysis(task_type: str, data: dict, model_override: str | None = None) -> dict:
    """Scoring or reply analysis, routed by active/auto model mode."""
    model = choose_model(task_type, data, model_override=model_override)
    logger.info("Skill 1 [%s] -> %s (override=%s)", task_type, model, model_override)

    try:
        from services.gemini_service import build_knowledge_context, _build_scoring_prompt, _build_reply_analysis_prompt, _load_skill_prompt_from_kb
        from skills.skill_1_analysis import SKILL_1_SYSTEM_PROMPT

        knowledge = build_knowledge_context(task_type)
        if task_type == "scoring":
            user_prompt = _build_scoring_prompt(data)
        elif task_type == "reply_analysis":
            user_prompt = _build_reply_analysis_prompt(data)
        else:
            return {"error": f"Unknown task_type: {task_type}"}

        system_prompt = _load_skill_prompt_from_kb(
            "AI Skill 1 - Analysis / Scoring / Reply Intent", SKILL_1_SYSTEM_PROMPT
        ) + ENGLISH_ONLY_RULE

        if model in ("deepseek", "openai"):
            if model == "openai":
                from services.openai_service import call_openai_skill_1_analysis
                result = await call_openai_skill_1_analysis(task_type, data, system_prompt, knowledge, user_prompt)
                return _ensure_english_result(result, model)
            from services.deepseek_service import call_deepseek_skill_1_analysis
            result = await call_deepseek_skill_1_analysis(task_type, data, system_prompt, knowledge, user_prompt)
            return _ensure_english_result(result, model)

        from services.gemini_service import call_skill_1_analysis as gemini_skill_1
        result = await gemini_skill_1(task_type, data)
        return _ensure_english_result(result, model)
    except Exception as exc:
        import traceback
        tb = traceback.format_exc()
        logger.warning("Skill-1 analysis failed: %s\n%s", exc, tb[-500:])
        return {"success": False, "error": str(exc), "result": str(exc)}
        # NOTE: intentionally include both error and result (as error string) so
        # the frontend can show the real reason instead of a generic "failed"


async def call_skill_2_generation(message_type: str, data: dict = None, system_prompt: str = None, model_override: str = None) -> dict:
    """Generate follow-up content / email drafts.
    Uses the model indicated by system_settings.active_model, with per-call override."""
    message_type = str(message_type or "cold_email")
    data = data or {}

    try:
        # Build knowledge and prompts — same as Gemini path, so all models get full context
        from services.gemini_service import build_knowledge_context, _build_generation_prompt, _load_skill_prompt_from_kb
        from skills.skill_2_generation import SKILL_2_SYSTEM_PROMPT

        knowledge = build_knowledge_context(message_type)
        user_prompt = _build_generation_prompt(message_type, data)
        skill_system = _load_skill_prompt_from_kb(
            "AI Skill 2 — Message Generation (LinkedIn / Email)", SKILL_2_SYSTEM_PROMPT
        )

        model = model_override if model_override and model_override in VALID_MODEL_MODES and model_override != "auto" else choose_model("simple")
        logger.info("Skill 2 [%s] -> %s (override=%s)", message_type, model, model_override)

        def _clean_body(res: dict) -> dict:
            """生成后硬清洗：去掉邮件正文里的附件暗示词（防模型漏写）。"""
            try:
                from services.writing_rules import sanitize_attachment_language
                import re as _re
                def _strip_cn(s: str) -> str:
                    # remove leftover paragraph labels like "Paragraph 1 — 点明来意: "
                    s = _re.sub(r'Paragraph\s*\d+\s*[—–-]?\s*[^:：\n]{0,24}[:：]', '', s)
                    # hard-remove any remaining Chinese characters
                    s = _re.sub(r'[\u4e00-\u9fff]+', '', s)
                    s = _re.sub(r'[ \t]{2,}', ' ', s)
                    return s.strip()
                for key in ("body", "content"):
                    if res.get(key):
                        res[key] = _strip_cn(sanitize_attachment_language(str(res[key])))
            except Exception:
                pass
            return res

        if model == "openai":
            from services.openai_service import call_openai_skill_2_generation
            return _clean_body(await call_openai_skill_2_generation(message_type, data, skill_system, knowledge, user_prompt))
        elif model == "deepseek":
            from services.deepseek_service import call_deepseek_skill_2_generation
            return _clean_body(await call_deepseek_skill_2_generation(message_type, data, skill_system, knowledge, user_prompt))

        # Gemini takes only 2 args — its own implementation builds prompts internally
        from services.gemini_service import call_skill_2_generation as gemini_skill_2
        return _clean_body(await gemini_skill_2(message_type, data))
    except Exception as exc:
        logger.warning("Skill-2 generation failed: %s", exc)
        return {"success": False, "error": str(exc)}

async def call_simple(prompt: str, model_override: str = None, temperature: float = 0.3, max_tokens: int = 2048) -> str:
    """Async simple prompt -> text completion, with cross-provider failover.
    Customer only needs to configure ONE provider."""
    prompt = str(prompt or "")

    preferred = model_override if (model_override and model_override in VALID_MODEL_MODES and model_override != "auto" and _provider_available(model_override)) else choose_model("simple")
    import asyncio as _asyncio
    loop = _asyncio.get_running_loop()
    last_err = None
    for provider in _provider_order(preferred):
        try:
            logger.info("call_simple(async) -> %s", provider)
            result = await _asyncio.wait_for(
                loop.run_in_executor(_AI_EXECUTOR, _sync_provider_call, provider, prompt, temperature, max_tokens),
                timeout=AI_CALL_TIMEOUT,
            )
            return result if isinstance(result, str) else str(result)
        except _asyncio.TimeoutError:
            last_err = TimeoutError(f"AI provider {provider} timed out after {AI_CALL_TIMEOUT}s")
            logger.warning("call_simple(async) %s timed out after %ds; trying next provider", provider, AI_CALL_TIMEOUT)
        except Exception as exc:
            last_err = exc
            logger.warning("call_simple(async) %s failed (%s); trying next provider", provider, exc)
    if last_err:
        raise last_err
    raise RuntimeError("No AI provider available — please configure at least one API key in System Settings")


# ── Voice rules management ──
# HUMAN_VOICE_RULES is set above to FALLBACK_VOICE_RULES at import time.
# Runtime overrides come from get_voice_rules() which reads knowledge_base.
# _RUNTIME_VOICE_RULES caches the KB result; invalidate_voice_rules() clears it.


def invalidate_voice_rules():
    global _RUNTIME_VOICE_RULES
    _RUNTIME_VOICE_RULES = None



# ── Profile signature (from DB, not from PROFILE_SIGNATURES) ──

async def get_signature_from_db(profile_type):
    """Return the persona signature for a given customer profile type."""
    try:
        db = SessionLocal()
        try:
            row = db.query(SystemSetting).filter(SystemSetting.key == f"signature_{profile_type}").first()
            if row and row.value:
                return row.value
        finally:
            db.close()
    except Exception:
        pass
    return ""
