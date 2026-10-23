"""Thin HTTP clients for chat models — no SDKs, so no dependency conflicts.

Supported: OpenAI, Anthropic, Ollama (local). `template` never touches the network.
"""

from __future__ import annotations

import json
import re
from typing import Any

from autoshorts.config import Settings
from autoshorts.util import http

OPENAI_URL = "https://api.openai.com/v1/chat/completions"
ANTHROPIC_URL = "https://api.anthropic.com/v1/messages"

DEFAULT_MODELS = {
    "openai": "gpt-4o-mini",
    "anthropic": "claude-sonnet-4-5",
    "ollama": "llama3.1",
}


class LLMUnavailable(RuntimeError):
    """Raised when a provider cannot serve the request; caller falls back."""


def model_for(settings: Settings) -> str:
    return settings.llm_model or DEFAULT_MODELS.get(settings.llm_provider, "")


def complete(system: str, user: str, settings: Settings, expect_json: bool = True) -> str:
    provider = settings.llm_provider
    if provider == "template":
        raise LLMUnavailable("template writer needs no LLM")
    if provider == "openai":
        return _openai(system, user, settings, expect_json)
    if provider == "anthropic":
        return _anthropic(system, user, settings, expect_json)
    if provider == "ollama":
        return _ollama(system, user, settings, expect_json)
    raise LLMUnavailable(f"unknown LLM_PROVIDER={provider!r} (openai|anthropic|ollama|template)")


def _finish(data: Any, text_key: tuple[str, ...]) -> str:
    if isinstance(data, dict) and "__error__" in data:
        raise LLMUnavailable(str(data["__error__"]))
    node: Any = data
    for part in text_key:
        if isinstance(node, list):
            node = node[0] if node else {}
        if not isinstance(node, dict):
            raise LLMUnavailable(f"unexpected response shape at {part!r}")
        node = node.get(part)
    if not isinstance(node, str) or not node.strip():
        raise LLMUnavailable("empty completion")
    return node


def _openai(system: str, user: str, settings: Settings, expect_json: bool) -> str:
    if not settings.openai_api_key:
        raise LLMUnavailable("OPENAI_API_KEY is empty")
    payload: dict[str, Any] = {
        "model": model_for(settings) or DEFAULT_MODELS["openai"],
        "temperature": settings.llm_temperature,
        "messages": [
            {"role": "system", "content": system},
            {"role": "user", "content": user},
        ],
    }
    if expect_json:
        payload["response_format"] = {"type": "json_object"}
    data = http.post_json(
        OPENAI_URL,
        payload,
        headers={
            "Authorization": f"Bearer {settings.openai_api_key}",
            "Content-Type": "application/json",
        },
    )
    return _finish(data, ("choices", "message", "content"))


def _anthropic(system: str, user: str, settings: Settings, expect_json: bool) -> str:
    if not settings.anthropic_api_key:
        raise LLMUnavailable("ANTHROPIC_API_KEY is empty")
    prompt = user if not expect_json else f"{user}\n\nRespond with valid JSON only."
    data = http.post_json(
        ANTHROPIC_URL,
        {
            "model": model_for(settings) or DEFAULT_MODELS["anthropic"],
            "max_tokens": 2048,
            "temperature": settings.llm_temperature,
            "system": system,
            "messages": [{"role": "user", "content": prompt}],
        },
        headers={
            "x-api-key": settings.anthropic_api_key,
            "anthropic-version": "2023-06-01",
            "content-type": "application/json",
        },
    )
    text = _finish(data, ("content", "text"))
    return text


def _ollama(system: str, user: str, settings: Settings, expect_json: bool) -> str:
    base = settings.ollama_base_url.rstrip("/")
    payload: dict[str, Any] = {
        "model": model_for(settings) or DEFAULT_MODELS["ollama"],
        "stream": False,
        "options": {"temperature": settings.llm_temperature},
        "messages": [
            {"role": "system", "content": system},
            {"role": "user", "content": user},
        ],
    }
    if expect_json:
        payload["format"] = "json"
    data = http.post_json(f"{base}/api/chat", payload, timeout=300.0)
    return _finish(data, ("message", "content"))


_JSON_BLOCK = re.compile(r"\{.*\}", re.DOTALL)


def extract_json(raw: str) -> dict[str, Any]:
    """Model output often arrives fenced or chatty; rescue the object."""
    candidates = [raw.strip()]
    fence = re.search(r"```(?:json)?\s*(.+?)```", raw, re.DOTALL)
    if fence:
        candidates.insert(0, fence.group(1).strip())
    block = _JSON_BLOCK.search(raw)
    if block:
        candidates.append(block.group(0))
    for candidate in candidates:
        try:
            parsed = json.loads(candidate)
        except Exception:
            continue
        if isinstance(parsed, dict):
            return parsed
    raise LLMUnavailable("could not parse JSON from model output")
