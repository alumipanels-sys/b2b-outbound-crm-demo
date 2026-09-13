"""OpenAI API service for premium/high-value sales tasks."""

from __future__ import annotations

import asyncio
import logging

import httpx

from config import OPENAI_API_KEY, OPENAI_MODEL
from services.deepseek_service import _parse_json

logger = logging.getLogger(__name__)

OPENAI_URL = "https://api.openai.com/v1/chat/completions"


def has_openai_config() -> bool:
    return bool(OPENAI_API_KEY)


def _call_openai(messages: list, temperature: float = 0.3, max_tokens: int = 2048, timeout: int = 120) -> str:
    if not OPENAI_API_KEY:
        raise RuntimeError("OPENAI_API_KEY is not configured")
    headers = {
        "Authorization": f"Bearer {OPENAI_API_KEY}",
        "Content-Type": "application/json",
    }
    body = {
        "model": OPENAI_MODEL,
        "messages": messages,
        "temperature": temperature,
        "max_tokens": max_tokens,
    }
    try:
        with httpx.Client(timeout=timeout) as client:
            resp = client.post(OPENAI_URL, json=body, headers=headers)
            resp.raise_for_status()
            data = resp.json()
            return data["choices"][0]["message"]["content"]
    except httpx.HTTPStatusError as exc:
        detail = exc.response.text[:500]
        logger.error("OpenAI HTTP %s: %s", exc.response.status_code, detail)
        raise RuntimeError(f"OpenAI API error {exc.response.status_code}: {detail}")
    except Exception as exc:
        logger.exception("OpenAI call failed")
        raise RuntimeError(f"OpenAI call failed: {exc}")


def call_openai_simple(prompt: str, temperature: float = 0.3, max_tokens: int = 2048) -> str:
    return _call_openai([{"role": "user", "content": prompt}], temperature=temperature, max_tokens=max_tokens)


async def call_openai_skill_1_analysis(task_type: str, data: dict, system_prompt: str, knowledge: str = "", user_prompt: str = "") -> dict:
    full_system = system_prompt
    if knowledge:
        full_system += f"\n\n## KNOWLEDGE BASE CONTEXT\n{knowledge}"
    messages = [
        {"role": "system", "content": full_system},
        {"role": "user", "content": user_prompt},
    ]
    try:
        loop = asyncio.get_event_loop()
        raw = await loop.run_in_executor(None, _call_openai, messages, 0.5, 4096, 120)
        return _parse_json(raw)
    except Exception as exc:
        logger.exception("OpenAI Skill 1 failed")
        return {"error": str(exc)}


async def call_openai_skill_2_generation(message_type: str, data: dict, system_prompt: str, knowledge: str = "", user_prompt: str = "") -> dict:
    full_system = system_prompt
    if knowledge:
        full_system += f"\n\n## KNOWLEDGE BASE CONTEXT\n{knowledge}"
    messages = [
        {"role": "system", "content": full_system},
        {"role": "user", "content": user_prompt},
    ]
    try:
        loop = asyncio.get_event_loop()
        raw = await loop.run_in_executor(None, _call_openai, messages, 0.6, 4096, 120)
        return _parse_json(raw)
    except Exception as exc:
        logger.exception("OpenAI Skill 2 failed")
        return {"error": str(exc)}
