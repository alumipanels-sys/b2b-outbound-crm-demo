"""DeepSeek API service — OpenAI-compatible endpoint.
Mirrors the gemini_service interface: call_deepseek_simple, call_skill_1_analysis, call_skill_2_generation.
"""

import asyncio
import json
import logging
import os

import httpx

from config import DEEPSEEK_API_KEY
from skills.skill_1_analysis import SKILL_1_SYSTEM_PROMPT
from skills.skill_2_generation import SKILL_2_SYSTEM_PROMPT

logger = logging.getLogger(__name__)

DEEPSEEK_URL = "https://api.deepseek.com/v1/chat/completions"
DEEPSEEK_MODEL = "deepseek-v4-pro"


def _call_deepseek(messages: list, temperature: float = 0.3, max_tokens: int = 2048, timeout: int = 120) -> str:
    """HTTP POST to DeepSeek (OpenAI-compatible). Direct connection — no proxy needed in China."""
    headers = {
        "Authorization": f"Bearer {DEEPSEEK_API_KEY}",
        "Content-Type": "application/json",
    }
    body = {
        "model": DEEPSEEK_MODEL,
        "messages": messages,
        "temperature": temperature,
        "max_tokens": max_tokens,
        # Disable thinking mode — V4 Flash defaults to thinking,
        # which burns tokens on internal reasoning instead of content.
        # For email generation, we want direct output.
        "thinking": {"type": "disabled"},
    }
    try:
        with httpx.Client(proxy=None, trust_env=False) as client:
            resp = client.post(DEEPSEEK_URL, json=body, headers=headers, timeout=timeout)
            resp.raise_for_status()
            data = resp.json()
            content = data["choices"][0]["message"]["content"]
            if not content or not content.strip():
                logger.error("DeepSeek returned empty content (reasoning model may have used all tokens for reasoning). Full response: %s", json.dumps(data, ensure_ascii=False)[:500])
                raise RuntimeError("DeepSeek returned empty content — may need higher max_tokens for reasoning model")
            return content
    except httpx.HTTPStatusError as e:
        detail = e.response.text[:500]
        logger.error("DeepSeek HTTP %s: %s", e.response.status_code, detail)
        raise RuntimeError(f"DeepSeek API error {e.response.status_code}: {detail}")
    except Exception as e:
        logger.exception("DeepSeek call failed")
        raise RuntimeError(f"DeepSeek call failed: {e}")


def call_deepseek_simple(prompt: str, temperature: float = 0.3, max_tokens: int = 2048) -> str:
    """Quick single-prompt call. No system prompt."""
    messages = [{"role": "user", "content": prompt}]
    return _call_deepseek(messages, temperature=temperature, max_tokens=max_tokens)


def _parse_json(raw: str) -> dict:
    """Parse JSON from AI response. Handles EVERY case DeepSeek V3 throws at us."""
    import re as _re
    clean = raw.strip()

    # 1. Strip ALL markdown fences and surrounding whitespace
    clean = _re.sub(r'```(?:json)?\s*', '', clean)
    clean = _re.sub(r'\s*```', '', clean)
    clean = clean.strip()

    # 2. Extract outermost JSON object via brace-counting (handles ANY nesting depth)
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

    # 3. Try straight parse
    try:
        return json.loads(clean)
    except json.JSONDecodeError:
        pass

    # 4. Remove trailing commas before } or ] (DeepSeek frequently emits them)
    try:
        fixed = _re.sub(r',\s*(?=[}\]])', '', clean)
        return json.loads(fixed)
    except (json.JSONDecodeError, Exception):
        pass

    # 5. Fix unescaped newlines inside string values
    try:
        fixed = _re.sub(r'(?<=[:,]\s*"[^"]*)\n(?=[^"]*")', '\\n', clean)
        return json.loads(fixed)
    except (json.JSONDecodeError, Exception):
        pass

    # 6. Fix single-quoted strings
    try:
        fixed = clean.replace("'", '"')
        return json.loads(fixed)
    except (json.JSONDecodeError, Exception):
        pass

    # 7. Try extracting just the date and reason fields
    try:
        date_match = _re.search(r'"next_follow_date"\s*:\s*"([^"]+)"', raw)
        reason_match = _re.search(r'"reason"\s*:\s*"([^"]*)"', raw, _re.DOTALL)
        if date_match:
            return {"next_follow_date": date_match.group(1),
                    "reason": reason_match.group(1) if reason_match else ""}
    except Exception:
        pass

    # 8. Strip trailing lines, re-close braces
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

    logger.warning("DeepSeek unparseable JSON (len=%d): %s", len(raw), raw[:500])
    return {"error": "JSON parse failed", "raw": raw[:500]}


# ── Skill 1 (analysis) mirrored ──

async def call_deepseek_skill_1_analysis(task_type: str, data: dict, system_prompt: str, knowledge: str = "", user_prompt: str = "") -> dict:
    """DeepSeek version of skill_1_analysis.
    Uses separate system + user messages (OpenAI format). Runs HTTP in thread to avoid blocking."""
    full_system = system_prompt
    if knowledge:
        full_system += f"\n\n## KNOWLEDGE BASE CONTEXT\n{knowledge}"

    messages = [
        {"role": "system", "content": full_system},
        {"role": "user", "content": user_prompt},
    ]

    logger.info("DeepSeek Skill 1 [%s] — calling...", task_type)
    try:
        loop = asyncio.get_event_loop()
        raw = await loop.run_in_executor(None, _call_deepseek, messages, 0.7, 4096, 120)
        return _parse_json(raw)
    except Exception as exc:
        logger.exception("DeepSeek Skill 1 failed")
        return {"error": str(exc)}


# ── Skill 2 (generation) mirrored ──

async def call_deepseek_skill_2_generation(message_type: str, data: dict, system_prompt: str, knowledge: str = "", user_prompt: str = "") -> dict:
    """DeepSeek version of skill_2_generation. Runs HTTP in thread to avoid blocking."""
    full_system = system_prompt
    if knowledge:
        full_system += f"\n\n## KNOWLEDGE BASE CONTEXT\n{knowledge}"

    messages = [
        {"role": "system", "content": full_system},
        {"role": "user", "content": user_prompt},
    ]

    logger.info("DeepSeek Skill 2 [%s] — calling...", message_type)
    try:
        loop = asyncio.get_event_loop()
        raw = await loop.run_in_executor(None, _call_deepseek, messages, 0.7, 4096, 180)
        parsed = _parse_json(raw)
        logger.info("DeepSeek Skill 2 [%s] — raw %d chars, parsed OK=%s", message_type, len(raw), bool(parsed and not parsed.get("error")))
        return parsed
    except Exception as exc:
        logger.exception("DeepSeek Skill 2 failed: %s", exc)
        return {"error": str(exc)[:300]}
