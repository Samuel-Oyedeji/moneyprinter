"""LLM access for the animation pipeline.

Uses the [animation] provider/model when set and falls back to the
[documentary] ones (a strong model via OpenRouter by default). Direct
OpenAI-compatible calls let us record OpenRouter's reported cost per call
on the project.
"""

import json
import re

from loguru import logger

from app.config import config
from app.models.llm_provider import get_llm_provider
from app.services import llm as llm_service

DEFAULT_PROVIDER = "openrouter"
DEFAULT_MODEL = "anthropic/claude-sonnet-5"
_MAX_RETRIES = 3


def _setting(key: str) -> str:
    return str(config.animation.get(key, "") or config.documentary.get(key, "") or "").strip()


def _client():
    """(client, model) for a direct OpenAI-compatible call, or None."""
    from openai import OpenAI

    provider_id = _setting("llm_provider") or DEFAULT_PROVIDER
    provider = get_llm_provider(provider_id)
    if provider is None or provider.adapter != "openai_compatible":
        return None
    api_key = str(config.app.get(provider.config_key("api_key"), "") or "").strip()
    if not api_key:
        return None
    base_url = provider.resolve_base_url(config.app.get(provider.config_key("base_url"), ""))
    model = _setting("llm_model_name") or DEFAULT_MODEL
    return OpenAI(api_key=api_key, base_url=base_url), model


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


def generate_text(prompt: str, on_cost=None) -> str:
    setup = _client()
    last_error = ""
    for attempt in range(_MAX_RETRIES):
        if setup is not None:
            client, model = setup
            try:
                extra = {"usage": {"include": True}} if "openrouter" in str(client.base_url) else {}
                response = client.chat.completions.create(
                    model=model,
                    messages=[{"role": "user", "content": prompt}],
                    extra_body=extra,
                )
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
                model = _setting("llm_model_name")
                if model:
                    app_config[f"{provider}_model_name"] = model
            response = llm_service._generate_response(prompt=prompt, app_config=app_config)
            if response and not response.startswith("Error: "):
                return response
            last_error = response or "empty response"
        logger.warning(f"animation llm call failed (attempt {attempt + 1}/{_MAX_RETRIES}): {last_error}")
    raise RuntimeError(f"animation llm call failed: {last_error}")


def parse_json(text: str):
    """JSON from a model reply, tolerating code fences and stray commentary."""
    try:
        return json.loads(llm_service._strip_code_fence(text))
    except json.JSONDecodeError:
        match = re.search(r"[\[{].*[\]}]", text or "", re.DOTALL)
        if match:
            return json.loads(match.group())
        raise


def generate_json(prompt: str, on_cost=None):
    last_error = ""
    for attempt in range(_MAX_RETRIES):
        text = generate_text(prompt, on_cost=on_cost)
        try:
            return parse_json(text)
        except json.JSONDecodeError as exc:
            last_error = str(exc)
            logger.warning(f"animation llm returned non-JSON (attempt {attempt + 1}): {last_error}")
    raise RuntimeError(f"animation llm returned invalid JSON: {last_error}")
