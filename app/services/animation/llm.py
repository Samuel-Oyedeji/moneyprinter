"""LLM access for the animation pipeline.

Two roles, each with its own model (set on the Animation page's Models
panel, saved under [animation]):

    script  writes the narration script in the house style (own system prompt)
    writer  splits the script into scenes and directs them: staging, faces,
            emotions, visuals. Also writes the YouTube copy.

The provider is [animation] llm_provider (OpenRouter by default); an empty
model falls back to [animation] llm_model_name, then [documentary], then
DEFAULT_MODEL, and an empty script model falls back to the writer's.
Direct OpenAI-compatible calls let us record OpenRouter's reported cost
per call on the project.
"""

import json
import re

import requests
from loguru import logger

from app.config import config
from app.models.llm_provider import get_llm_provider
from app.services import llm as llm_service

DEFAULT_PROVIDER = "openrouter"
DEFAULT_MODEL = "anthropic/claude-sonnet-5"
ROLES = ("script", "writer")
OPENROUTER_MODELS_URL = "https://openrouter.ai/api/v1/models"
_MAX_RETRIES = 3


def _setting(key: str) -> str:
    return str(config.animation.get(key, "") or config.documentary.get(key, "") or "").strip()


def provider_id() -> str:
    return _setting("llm_provider") or DEFAULT_PROVIDER


def model_for(role: str = "writer") -> str:
    if role not in ROLES:
        raise ValueError(f"unknown model role {role!r}")
    writer = str(config.animation.get("writer_model", "") or "").strip() or _setting("llm_model_name") or DEFAULT_MODEL
    if role == "script":
        return str(config.animation.get("script_model", "") or "").strip() or writer
    return writer


def _client():
    """An OpenAI-compatible client for the configured provider, or None."""
    from openai import OpenAI

    provider = get_llm_provider(provider_id())
    if provider is None or provider.adapter != "openai_compatible":
        return None
    api_key = str(config.app.get(provider.config_key("api_key"), "") or "").strip()
    if not api_key:
        return None
    base_url = provider.resolve_base_url(config.app.get(provider.config_key("base_url"), ""))
    return OpenAI(api_key=api_key, base_url=base_url)


def _reported_cost(response) -> float:
    usage = getattr(response, "usage", None)
    if usage is None:
        return 0.0
    cost = getattr(usage, "cost", None)
    if cost is None and getattr(usage, "model_extra", None):
        cost = usage.model_extra.get("cost")
    try:
        return float(cost or 0.0)
    except (TypeError, ValueError):
        return 0.0


def _flatten(messages: list[dict]) -> str:
    """One prompt for providers reached through the shared single-prompt path."""
    parts = []
    for m in messages:
        label = {"system": "", "user": "", "assistant": "# Your previous reply\n"}.get(m["role"], "")
        parts.append(label + m["content"])
    return "\n\n".join(parts)


def chat(messages: list[dict], role: str = "writer", on_cost=None) -> str:
    """Send a conversation ({"role", "content"} dicts) with the role's model."""
    client = _client()
    model = model_for(role)
    last_error = ""
    for attempt in range(_MAX_RETRIES):
        if client is not None:
            try:
                extra = {"usage": {"include": True}} if "openrouter" in str(client.base_url) else {}
                response = client.chat.completions.create(model=model, messages=messages, extra_body=extra)
                if on_cost:
                    on_cost(_reported_cost(response))
                return llm_service._extract_chat_completion_text(response, model)
            except Exception as exc:
                last_error = llm_service._sanitize_error_message(exc)
        else:
            # Non-OpenAI-compatible provider: the shared path (no cost data).
            app_config = dict(config.app)
            provider = _setting("llm_provider")
            if provider:
                app_config["llm_provider"] = provider
                app_config[f"{provider}_model_name"] = model
            response = llm_service._generate_response(prompt=_flatten(messages), app_config=app_config)
            if response and not response.startswith("Error: "):
                return response
            last_error = response or "empty response"
        logger.warning(f"animation llm call failed ({model}, attempt {attempt + 1}/{_MAX_RETRIES}): {last_error}")
    raise RuntimeError(f"animation llm call failed ({model}): {last_error}")


def generate_text(prompt: str, on_cost=None, role: str = "writer", system: str = "") -> str:
    messages = ([{"role": "system", "content": system}] if system else []) + [{"role": "user", "content": prompt}]
    return chat(messages, role=role, on_cost=on_cost)


def parse_json(text: str):
    """JSON from a model reply, tolerating code fences and stray commentary."""
    try:
        return json.loads(llm_service._strip_code_fence(text))
    except json.JSONDecodeError:
        match = re.search(r"[\[{].*[\]}]", text or "", re.DOTALL)
        if match:
            return json.loads(match.group())
        raise


def generate_json(prompt: str, on_cost=None, role: str = "writer"):
    last_error = ""
    for attempt in range(_MAX_RETRIES):
        text = generate_text(prompt, on_cost=on_cost, role=role)
        try:
            return parse_json(text)
        except json.JSONDecodeError as exc:
            last_error = str(exc)
            logger.warning(f"animation llm returned non-JSON (attempt {attempt + 1}): {last_error}")
    raise RuntimeError(f"animation llm returned invalid JSON: {last_error}")


def _per_million(price) -> float | None:
    try:
        return round(float(price) * 1_000_000, 4)
    except (TypeError, ValueError):
        return None


def openrouter_models(timeout: float = 15) -> list[dict]:
    """OpenRouter's public catalogue of text models, sorted by id.

    Each item: id, name, context, prompt/completion price in $ per million
    tokens (None when unknown). Batch-only variants are left out.
    """
    response = requests.get(OPENROUTER_MODELS_URL, timeout=timeout)
    response.raise_for_status()
    models = []
    for m in response.json().get("data", []):
        model_id = str(m.get("id") or "")
        outputs = (m.get("architecture") or {}).get("output_modalities") or ["text"]
        if not model_id or model_id.endswith(":batch") or "text" not in outputs:
            continue
        pricing = m.get("pricing") or {}
        models.append(
            {
                "id": model_id,
                "name": str(m.get("name") or model_id),
                "context": int(m.get("context_length") or 0),
                "prompt": _per_million(pricing.get("prompt")),
                "completion": _per_million(pricing.get("completion")),
            }
        )
    return sorted(models, key=lambda m: m["id"])
