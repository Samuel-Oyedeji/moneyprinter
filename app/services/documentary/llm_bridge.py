"""LLM access for the documentary pipeline.

The documentary feature needs a stronger model than the short-form defaults,
so it carries its own provider/model override in the [documentary] config
section (defaulting to an Anthropic model via OpenRouter) and routes requests
through the existing provider layer in app.services.llm.
"""

import base64
import io
import json
import re

from loguru import logger

from app.config import config
from app.models.llm_provider import get_llm_provider
from app.services import llm as llm_service

_MAX_RETRIES = 3

DEFAULT_LLM_PROVIDER = "openrouter"
DEFAULT_MODEL_NAME = "anthropic/claude-sonnet-5"
DEFAULT_VISION_MODEL = "google/gemini-3.5-flash"
VISION_IMAGE_MAX_EDGE = 768


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


# ------------------------------------------------------------------- vision
def _vision_client():
    """OpenAI-compatible client for the vision model.

    Vision calls go straight through the documentary provider (OpenRouter by
    default) because the shared _generate_response() path is text-only.
    """
    from openai import OpenAI

    doc_cfg = config.documentary
    provider_id = str(
        doc_cfg.get("llm_provider", DEFAULT_LLM_PROVIDER) or DEFAULT_LLM_PROVIDER
    ).strip()
    provider = get_llm_provider(provider_id)
    if provider is None or provider.adapter != "openai_compatible":
        raise ValueError(
            f"documentary vision scoring needs an OpenAI-compatible provider; "
            f"'{provider_id}' is not supported for vision calls"
        )
    api_key = str(config.app.get(provider.config_key("api_key"), "") or "").strip()
    if not api_key:
        raise ValueError(
            f"{provider.config_key('api_key')} is not set in config.toml"
        )
    base_url = provider.resolve_base_url(
        config.app.get(provider.config_key("base_url"), "")
    )
    model = str(
        doc_cfg.get("vision_model", DEFAULT_VISION_MODEL) or DEFAULT_VISION_MODEL
    ).strip()
    return OpenAI(api_key=api_key, base_url=base_url), model


def _image_data_url(image_path: str) -> str:
    """Downscale + JPEG-encode an image for the vision prompt."""
    from PIL import Image

    with Image.open(image_path) as image:
        image = image.convert("RGB")
        image.thumbnail((VISION_IMAGE_MAX_EDGE, VISION_IMAGE_MAX_EDGE))
        buffer = io.BytesIO()
        image.save(buffer, format="JPEG", quality=80)
    encoded = base64.b64encode(buffer.getvalue()).decode("ascii")
    return f"data:image/jpeg;base64,{encoded}"


def generate_vision_json(prompt: str, image_paths: list[str]):
    """Send text + images to the vision model; expect a JSON response."""
    client, model = _vision_client()
    content = [{"type": "text", "text": prompt}]
    for path in image_paths:
        content.append(
            {"type": "image_url", "image_url": {"url": _image_data_url(path)}}
        )

    last_error = ""
    for attempt in range(_MAX_RETRIES):
        try:
            response = client.chat.completions.create(
                model=model,
                messages=[{"role": "user", "content": content}],
            )
            text = llm_service._extract_chat_completion_text(response, "vision")
            try:
                return json.loads(llm_service._strip_code_fence(text))
            except json.JSONDecodeError:
                match = re.search(r"[\[{].*[\]}]", text, re.DOTALL)
                if match:
                    return json.loads(match.group())
                raise ValueError(f"non-JSON vision response: {text[:200]}")
        except Exception as exc:
            last_error = str(exc)
            logger.warning(
                f"vision call failed (attempt {attempt + 1}/{_MAX_RETRIES}): "
                f"{last_error}"
            )
    raise RuntimeError(f"documentary vision call failed: {last_error}")
