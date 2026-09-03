"""Per-project cost ledger for the documentary pipeline.

Every external call that costs money records an entry in the project's
costs.json: LLM/vision calls (token usage, and OpenRouter's actual cost
when it reports one), SerpApi searches (count x configured price), and TTS
(characters x configured price; Edge TTS is free). Where a provider does
not report real cost, the estimate uses prices from the [documentary]
config so the user can keep them current.

The active project is process-wide state set by the pipeline stages; the
pipeline runs one stage at a time per process, so a simple module global
with a lock is enough.
"""

import threading
import time

from loguru import logger

from app.config import config
from app.services.documentary import store

_lock = threading.RLock()
_active_project_id: str | None = None

# Fallback prices, overridable in [documentary]. Estimates only — marked as
# such in the UI.
DEFAULT_LLM_PRICE_PER_MTOK = (3.0, 15.0)  # (input, output) USD per 1M tokens
DEFAULT_VISION_PRICE_PER_MTOK = (0.30, 2.50)
DEFAULT_SERPAPI_PRICE_PER_SEARCH = 0.01
# ElevenLabs bills ~$0.10/1k chars for v2 Multilingual (the app's default
# model_id); v3 Conversational and Flash/Turbo are $0.05. Override in
# [documentary] if the model or plan differs.
DEFAULT_ELEVENLABS_PRICE_PER_1K_CHARS = 0.10


def set_project(project_id: str | None) -> None:
    global _active_project_id
    with _lock:
        _active_project_id = project_id


def _config_price(key: str, default):
    value = config.documentary.get(key)
    if value in (None, ""):
        return default
    try:
        if isinstance(default, tuple):
            return tuple(float(v) for v in value)
        return float(value)
    except (TypeError, ValueError):
        return default


def _append(entry: dict) -> None:
    with _lock:
        project_id = _active_project_id
    if not project_id:
        return
    try:
        entries = store.load_costs(project_id)
        entry["ts"] = time.time()
        entries.append(entry)
        store.save_costs(project_id, entries)
    except Exception as exc:
        # Cost tracking must never break the pipeline.
        logger.warning(f"failed to record cost entry: {exc}")


def record_llm(
    kind: str,
    model: str,
    prompt_tokens: int,
    completion_tokens: int,
    reported_cost: float | None = None,
) -> None:
    """kind: 'llm' for text calls, 'vision' for image-scoring calls."""
    if reported_cost is not None:
        cost, estimated = float(reported_cost), False
    else:
        price_key = (
            "vision_price_per_mtok" if kind == "vision" else "llm_price_per_mtok"
        )
        default = (
            DEFAULT_VISION_PRICE_PER_MTOK
            if kind == "vision"
            else DEFAULT_LLM_PRICE_PER_MTOK
        )
        price_in, price_out = _config_price(price_key, default)
        cost = (
            prompt_tokens / 1e6 * price_in + completion_tokens / 1e6 * price_out
        )
        estimated = True
    _append(
        {
            "kind": kind,
            "model": model,
            "prompt_tokens": int(prompt_tokens),
            "completion_tokens": int(completion_tokens),
            "cost": round(cost, 6),
            "estimated": estimated,
        }
    )


def record_serpapi(query: str) -> None:
    price = _config_price(
        "serpapi_price_per_search", DEFAULT_SERPAPI_PRICE_PER_SEARCH
    )
    _append(
        {
            "kind": "serpapi",
            "detail": query[:80],
            "cost": round(price, 6),
            "estimated": True,
        }
    )


def record_tts(voice_name: str, characters: int) -> None:
    if voice_name.startswith("elevenlabs:"):
        price = _config_price(
            "elevenlabs_price_per_1k_chars", DEFAULT_ELEVENLABS_PRICE_PER_1K_CHARS
        )
        cost = characters / 1000 * price
        estimated = True
    else:
        cost, estimated = 0.0, False  # Edge TTS is free
    _append(
        {
            "kind": "tts",
            "detail": voice_name,
            "characters": int(characters),
            "cost": round(cost, 6),
            "estimated": estimated,
        }
    )


def summarize(project_id: str) -> dict:
    """Aggregate the ledger into totals by kind for display."""
    entries = store.load_costs(project_id)
    by_kind: dict[str, dict] = {}
    any_estimated = False
    for entry in entries:
        kind = entry.get("kind", "other")
        bucket = by_kind.setdefault(
            kind, {"count": 0, "cost": 0.0, "tokens": 0, "characters": 0}
        )
        bucket["count"] += 1
        bucket["cost"] += float(entry.get("cost", 0))
        bucket["tokens"] += int(entry.get("prompt_tokens", 0)) + int(
            entry.get("completion_tokens", 0)
        )
        bucket["characters"] += int(entry.get("characters", 0))
        any_estimated = any_estimated or bool(entry.get("estimated"))
    return {
        "total": round(sum(b["cost"] for b in by_kind.values()), 4),
        "by_kind": by_kind,
        "entries": len(entries),
        "any_estimated": any_estimated,
    }
