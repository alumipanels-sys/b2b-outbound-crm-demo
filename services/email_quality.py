"""Multi-model email quality check — DeepSeek + Gemini score cold-outreach emails 0-100.

Each model independently scores the email on 6 dimensions (total 100) and returns
a JSON verdict. Results are shown side by side before human approval/sending.
"""

import asyncio
import concurrent.futures
import json
import logging
import re

logger = logging.getLogger(__name__)

# DeepSeek uses 2 workers; Gemini uses 1 dedicated worker so a slow Gemini
# response never blocks DeepSeek.
_DS_DB_EXECUTOR = concurrent.futures.ThreadPoolExecutor(max_workers=2, thread_name_prefix="email_qc_main")
_GEMINI_EXECUTOR = concurrent.futures.ThreadPoolExecutor(max_workers=1, thread_name_prefix="email_qc_gemini")

# Per-model timeout: Gemini is slower (60-90s) and must not block DeepSeek.
PROVIDER_TIMEOUT = {"deepseek": 60, "gemini": 90}

_RUBRIC = """You are a senior B2B cold-outreach email quality reviewer. Score this cold email 0-100 on these dimensions:
1) Personalization & relevance (25): references the prospect's specifics (industry / company / pain points / signals), not a generic template;
2) Compliance & red lines (20): no spam words (FREE / GUARANTEED / URGENT / ACT NOW / BEST PRICE etc.); no exaggeration ("cheapest price" / "best quality"); no unverified claims (e.g. ISO13485); never mention payment, logistics or customs clearance to Russian/Turkish customers;
3) Tone & authenticity (20): reads like a real export engineer wrote it, not AI-generated; does not open with "Dear"; avoids cliches such as "I hope this email finds you well";
4) Structure & length (15): paragraphs of 2-3 sentences, concise, information-dense, appropriate length for cold outreach;
5) Call to action (10): has a clear, low-friction next step;
6) Cultural fit (10): matches the customer's country and language habits (German-speaking buyers prefer a direct engineering style).
Return ONLY JSON (no explanation, no markdown code blocks):
{"score": integer 0-100, "verdict": "pass|revise|rewrite", "strengths": ["..."], "suggestions": ["..."], "red_flags": ["..."]}"""


def _build_prompt(subject: str, body: str, prospect=None) -> str:
    ctx = ""
    if prospect is not None:
        ctx = (
            f"\nCustomer background: company={prospect.company or ''}, country={prospect.country or ''}, "
            f"size={prospect.size or ''}, industry={prospect.industry or ''}, "
            f"profile={prospect.profile_type or ''}, value={prospect.value_level or ''}, "
            f"notes={prospect.note or ''}\n"
        )
    return f"{_RUBRIC}{ctx}\nEmail subject: {subject or ''}\nEmail body:\n{(body or '')[:5000]}"


def _call_provider(provider: str, prompt: str) -> str:
    if provider == "deepseek":
        from services.deepseek_service import call_deepseek_simple
        return call_deepseek_simple(prompt, temperature=0.2, max_tokens=800)
    from services.gemini_service import call_gemini_simple
    return call_gemini_simple(prompt, temperature=0.2, max_tokens=800)


def _as_list(data: dict, key: str) -> list[str]:
    v = data.get(key)
    if isinstance(v, list):
        return [str(x).strip()[:200] for x in v if str(x).strip()][:6]
    if isinstance(v, str) and v.strip():
        return [v.strip()[:200]]
    return []


def _parse_verdict(raw: str) -> dict:
    text = (raw or "").strip()
    text = re.sub(r"```(?:json)?", "", text).strip()
    m = re.search(r"\{.*\}", text, re.S)
    if not m:
        return {"score": None, "verdict": "unknown", "strengths": [],
                "suggestions": [], "red_flags": [], "raw": text[:300]}
    try:
        data = json.loads(m.group(0))
    except Exception:
        return {"score": None, "verdict": "unknown", "strengths": [],
                "suggestions": [], "red_flags": [], "raw": text[:300]}
    score = data.get("score")
    try:
        score = int(float(score))
    except (TypeError, ValueError):
        score = None
    verdict = data.get("verdict", "unknown") if isinstance(data.get("verdict"), str) else "unknown"
    if verdict not in ("pass", "revise", "rewrite"):
        verdict = "unknown"
    return {
        "score": score,
        "verdict": verdict,
        "strengths": _as_list(data, "strengths"),
        "suggestions": _as_list(data, "suggestions"),
        "red_flags": _as_list(data, "red_flags"),
    }


async def quality_check_email(subject: str, body: str, prospect=None,
                              timeout: int = 60, threshold: int = 70) -> dict:
    """Score an email with DeepSeek + Gemini (parallel), return 0-100 results."""
    prompt = _build_prompt(subject, body, prospect)
    loop = asyncio.get_event_loop()
    providers = ["deepseek", "gemini"]
    labels = {"deepseek": "DeepSeek", "gemini": "Gemini"}

    async def _run_one(provider: str) -> dict:
        executor = _GEMINI_EXECUTOR if provider == "gemini" else _DS_DB_EXECUTOR
        timeout_s = PROVIDER_TIMEOUT.get(provider, timeout)
        try:
            raw = await asyncio.wait_for(
                loop.run_in_executor(executor, _call_provider, provider, prompt),
                timeout=timeout_s,
            )
            r = _parse_verdict(raw)
            r["model"] = provider
            r["model_label"] = labels.get(provider, provider)
            return r
        except asyncio.TimeoutError:
            return {"model": provider, "model_label": labels.get(provider, provider),
"error": f"Timed out ({timeout_s}s)", "score": None, "verdict": "error"}
        except Exception as exc:
            logger.warning("Quality check %s failed: %s", provider, exc)
            return {"model": provider, "model_label": labels.get(provider, provider),
                    "error": str(exc)[:200], "score": None, "verdict": "error"}

    results = await asyncio.gather(*[_run_one(p) for p in providers])

    scores = [r.get("score") for r in results if isinstance(r.get("score"), int)]
    avg = round(sum(scores) / len(scores), 1) if scores else None
    return {
        "results": results,
        "average": avg,
        "pass": bool(avg is not None and avg >= threshold),
        "threshold": threshold,
    }
