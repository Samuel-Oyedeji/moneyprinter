"""LLM access for the documentary pipeline.

The documentary feature needs a stronger model than the short-form defaults,
so it carries its own provider/model override in the [documentary] config
section (defaulting to an Anthropic model via OpenRouter) and routes requests
through the existing provider layer in app.services.llm.
"""

import json
import re

from loguru import logger

from app.config import config
from app.services import llm as llm_service

_MAX_RETRIES = 3

DEFAULT_LLM_PROVIDER = "openrouter"
DEFAULT_MODEL_NAME = "anthropic/claude-sonnet-5"


def _documentary_app_config() -> dict:
    """Build an app-config snapshot with the documentary LLM override applied.

    _generate_response() reads provider, api key, base URL and model from the
    app config it is given, so overriding those keys in a copy is enough to
    redirect only documentary calls. An empty documentary.llm_provider falls
    back to the global provider unchanged.
    """
    app_config = dict(config.app)
    doc_cfg = getattr(config, "documentary", {}) or {}
    provider = str(doc_cfg.get("llm_provider", DEFAULT_LLM_PROVIDER) or "").strip()
    if not provider:
        return app_config

    app_config["llm_provider"] = provider
    model_name = str(doc_cfg.get("llm_model_name", "") or "").strip()
    if not model_name and provider == DEFAULT_LLM_PROVIDER:
        model_name = DEFAULT_MODEL_NAME
    if model_name:
        app_config[f"{provider}_model_name"] = model_name
    return app_config


def generate_text(prompt: str) -> str:
    """Run one completion, raising on provider errors instead of returning them."""
    last_error = ""
    for attempt in range(_MAX_RETRIES):
        response = llm_service._generate_response(
            prompt=prompt, app_config=_documentary_app_config()
        )
        if response and not response.startswith("Error: "):
            return response
        last_error = response or "empty response"
        logger.warning(
            f"documentary llm call failed (attempt {attempt + 1}/{_MAX_RETRIES}): "
            f"{last_error}"
        )
    raise RuntimeError(f"documentary llm call failed: {last_error}")


def generate_json(prompt: str):
    """Run a completion that must return JSON, with fence/extraction fallbacks."""
    last_error = ""
    for attempt in range(_MAX_RETRIES):
        response = generate_text(prompt)
        try:
            return json.loads(llm_service._strip_code_fence(response))
        except json.JSONDecodeError as exc:
            last_error = str(exc)

        # Some models wrap the JSON in commentary despite instructions; take
        # the outermost object or array before giving up on this attempt.
        match = re.search(r"[\[{].*[\]}]", response, re.DOTALL)
        if match:
            try:
                return json.loads(match.group())
            except json.JSONDecodeError as exc:
                last_error = str(exc)

        logger.warning(
            f"documentary llm returned non-JSON (attempt {attempt + 1}/"
            f"{_MAX_RETRIES}): {last_error}"
        )
    raise RuntimeError(f"documentary llm returned invalid JSON: {last_error}")
