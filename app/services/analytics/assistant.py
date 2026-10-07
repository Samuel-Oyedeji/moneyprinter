"""The Analytics Assistant: a chat about the channel's numbers.

Each question goes to the chosen model (OpenRouter, through the same client
and key as the Animation studio) together with:

  - a system prompt that explains the studios and the metrics,
  - the data of the metric tags attached to the chat (see tags.py),
  - the conversation so far.

The model can also call three read-only tools to look up anything that
isn't attached: ``list_data``, ``get_data`` (any tag) and ``find_videos``.
Models without tool support get the attached data only.

Chats are saved one JSON file each under storage/analytics/chats/, so they
can be reopened, renamed and deleted from the page.
"""

import json
import os
import re
import time
import uuid
from datetime import date as date_cls
from datetime import datetime, timedelta, timezone

import pandas as pd
from loguru import logger

from app.config import config
from app.services.analytics import report, store, tags

RANGES = {"30 days": 30, "90 days": 90, "1 year": 365, "All time": None}
DEFAULT_RANGE = "All time"
NEW_CHAT_TITLE = "New chat"
MAX_HISTORY_MESSAGES = 30
MAX_CONTEXT_CHARS = 60_000
MAX_TOOL_ROUNDS = 6
_CHAT_ID_RE = re.compile(r"^[a-z0-9-]{6,64}$")


class AssistantError(Exception):
    """The question could not be answered (no key, model error…)."""


# ------------------------------------------------------------------- models
def default_model() -> str:
    from app.services.animation import llm as anim_llm

    return str(config.assistant.get("model", "") or "").strip() or anim_llm.model_for("writer")


def set_default_model(model: str) -> None:
    model = (model or "").strip()
    if model and model != config.assistant.get("model"):
        config.assistant["model"] = model
        config.save_config()


# ------------------------------------------------------------------ history
def _chats_dir() -> str:
    path = os.path.join(store.analytics_dir(), "chats")
    os.makedirs(path, exist_ok=True)
    return path


def _chat_path(chat_id: str) -> str:
    if not _CHAT_ID_RE.match(chat_id or ""):
        raise ValueError(f"invalid chat id: {chat_id!r}")
    return os.path.join(_chats_dir(), f"{chat_id}.json")


def new_chat(model: str = "", refs: list[str] | None = None, data_range: str = DEFAULT_RANGE) -> dict:
    """A fresh, unsaved chat; it is written on its first message."""
    now = time.time()
    return {
        "id": f"{time.strftime('%Y%m%d-%H%M%S')}-{uuid.uuid4().hex[:6]}",
        "title": NEW_CHAT_TITLE,
        "model": model or default_model(),
        "refs": list(refs or []),
        "range": data_range if data_range in RANGES else DEFAULT_RANGE,
        "messages": [],
        "cost": 0.0,
        "created_at": now,
        "updated_at": now,
    }


def save_chat(chat: dict) -> None:
    chat["updated_at"] = time.time()
    path = _chat_path(chat["id"])
    with store._lock:
        with open(f"{path}.tmp", "w", encoding="utf-8") as f:
            json.dump(chat, f, ensure_ascii=False, indent=2)
        os.replace(f"{path}.tmp", path)


def load_chat(chat_id: str) -> dict | None:
    try:
        with open(_chat_path(chat_id), "r", encoding="utf-8") as f:
            chat = json.load(f)
    except (OSError, ValueError):
        return None
    return chat if isinstance(chat, dict) and chat.get("id") == chat_id else None


def list_chats() -> list[dict]:
    """Saved chats, most recently used first (without their messages)."""
    chats = []
    for name in os.listdir(_chats_dir()):
        if not name.endswith(".json"):
            continue
        chat = load_chat(name[:-5])
        if chat:
            chats.append({k: chat.get(k) for k in ("id", "title", "model", "updated_at", "created_at")} | {"messages": len(chat.get("messages") or [])})
    return sorted(chats, key=lambda c: c.get("updated_at") or 0, reverse=True)


def rename_chat(chat_id: str, title: str) -> dict:
    chat = load_chat(chat_id)
    if not chat:
        raise KeyError(chat_id)
    chat["title"] = (title or "").strip()[:80] or chat["title"]
    save_chat(chat)
    return chat


def delete_chat(chat_id: str) -> None:
    try:
        os.remove(_chat_path(chat_id))
    except FileNotFoundError:
        pass


def delete_all_chats() -> int:
    chats = list_chats()
    for chat in chats:
        delete_chat(chat["id"])
    return len(chats)


def title_from(question: str) -> str:
    first = " ".join((question or "").split())
    return (first[:57] + "…") if len(first) > 60 else (first or NEW_CHAT_TITLE)


# --------------------------------------------------------------------- data
def scope(df: pd.DataFrame, data_range: str) -> pd.DataFrame:
    """Videos published within the chat's data range."""
    days = RANGES.get(data_range)
    if df.empty or not days:
        return df
    cutoff = datetime.now(timezone.utc) - timedelta(days=days)
    return df[df["published_at"] >= cutoff]


def context_text(refs: list[str], df: pd.DataFrame) -> str:
    """The attached tags' data, capped so a big selection can't blow the context."""
    by_id = {t["id"]: t for t in tags.all_tags(df)}
    blocks = []
    for ref in refs:
        tag = by_id.get(ref)
        blocks.append(tags.render(tag, df)["text"] if tag else f"### {ref}\n(This tag no longer exists.)")
    text = "\n\n".join(blocks)
    if len(text) > MAX_CONTEXT_CHARS:
        text = text[:MAX_CONTEXT_CHARS] + "\n…(cut: too much data attached; detach some tags or use get_data for the rest)"
    return text


def system_prompt(df: pd.DataFrame, refs: list[str], data_range: str) -> str:
    channel = (store.load_channel_info() or {}).get("title") or "this channel"
    attached = context_text(refs, df) if refs else "(Nothing attached. Use the tools to look things up.)"
    return f"""You are the analytics assistant for the YouTube channel "{channel}". The owner makes videos with three studios in one app:
- Shorts (stock footage): vertical stock-footage videos with an AI voice-over and subtitles.
- Documentaries: long-form, researched still-image documentaries with narration.
- Animations: paper cut-out story videos drawn in code. Their style settings include the main setting (forest, space, desert, room…), the characters (person, animal, astronaut, pharaoh, robot…), the transitions (paper tear, hard cuts, in-picture fly/hand/zoom/pull), scene count, length and voice.

Today is {date_cls.today().isoformat()}. Data range: videos published in the last {data_range.lower()}{'' if RANGES.get(data_range) else ' (everything)'}. {len(df[df['live']]) if not df.empty else 0} published videos are in range.

How to read the numbers:
- views: lifetime views so far (favours older videos).
- views/day: views divided by days since publishing (fairer across ages).
- views at 7 days: views 7 days after publishing, only for videos tracked from day one (the fairest comparison).
- % viewed: the average share of the video people watched (retention).
- Engagement /1k: likes + comments + shares per 1,000 views.
- made as: "Batch" (generated together with others) or "Single". posted: "App upload" or "Posted by hand".

Rules:
- Base every claim on the data below or on tool results. Quote the numbers and how many videos each rests on; call anything resting on fewer than 3 videos a hunch, not a finding.
- If the attached data doesn't answer the question, call the tools (list_data, get_data, find_videos) before answering. Never invent videos, titles or numbers.
- Title suggestions: learn from the best and weakest titles in the data (length, wording, hooks, numbers, questions), keep each under 100 characters, say which winning pattern each follows, and never reuse an existing title.
- Be concise and practical: short paragraphs, bullets, small markdown tables. End with concrete next steps when they help.

## Data the owner attached
{attached}"""


# -------------------------------------------------------------------- tools
TOOLS = [
    {
        "type": "function",
        "function": {
            "name": "list_data",
            "description": "List every metric tag (a named slice of the analytics) with its id. Use it to find what you can load with get_data.",
            "parameters": {"type": "object", "properties": {}},
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_data",
            "description": "Load one metric tag's data: a breakdown table, a list of videos, batches or findings.",
            "parameters": {
                "type": "object",
                "properties": {"tag_id": {"type": "string", "description": "A tag id from list_data, e.g. builtin:animation:Main setting"}},
                "required": ["tag_id"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "find_videos",
            "description": "Search published videos and return their titles, numbers and style.",
            "parameters": {
                "type": "object",
                "properties": {
                    "studio": {"type": "string", "enum": ["", "shorts", "documentary", "animation"], "description": "Only this studio; empty for all."},
                    "title_contains": {"type": "string", "description": "Case-insensitive text the title or topic must contain."},
                    "sort_by": {"type": "string", "enum": ["views", "views_per_day", "views_7d", "avg_view_pct", "engagement_per_1k", "published_at"]},
                    "ascending": {"type": "boolean", "description": "true for the weakest / oldest first."},
                    "limit": {"type": "integer", "minimum": 1, "maximum": 50},
                },
            },
        },
    },
]


def run_tool(name: str, args: dict, df: pd.DataFrame) -> str:
    """Run one tool call; errors come back as text for the model to read."""
    try:
        if name == "list_data":
            return "\n".join(f"{t['id']} | {t['name']} | {t['kind']}" for t in tags.all_tags(df))
        if name == "get_data":
            tag = tags.get_tag(str(args.get("tag_id", "")), df)
            if not tag:
                return f"No tag with id {args.get('tag_id')!r}. Call list_data for the ids."
            return tags.render(tag, df)["text"]
        if name == "find_videos":
            data = df[df["live"]] if not df.empty else df
            studio = str(args.get("studio") or "")
            if studio:
                data = data[data["studio"] == studio]
            needle = str(args.get("title_contains") or "").strip().casefold()
            if needle:
                text = (data["title"].astype(str) + " " + data["topic"].astype(str)).str.casefold()
                data = data[text.str.contains(needle, regex=False)]
            sort_by = args.get("sort_by") if args.get("sort_by") in data.columns else "views_per_day"
            data = data.sort_values(sort_by, ascending=bool(args.get("ascending")), na_position="last")
            limit = max(1, min(int(args.get("limit") or 20), 50))
            if data.empty:
                return "No published videos match."
            return f"{len(data)} match; showing {min(limit, len(data))}:\n" + tags._csv(tags._video_rows(data, studio, limit))
        return f"Unknown tool {name!r}."
    except Exception as exc:  # a broken tool call must not end the conversation
        logger.warning(f"assistant tool {name} failed: {exc}")
        return f"Tool error: {type(exc).__name__}: {exc}"


# -------------------------------------------------------------------- agent
def _client():
    from app.services.animation import llm as anim_llm

    client = anim_llm._client()
    if client is None:
        raise AssistantError(
            "No OpenRouter key yet. Add it in the Animation studio → 🤖 Models, or under [app] "
            "openrouter_api_key in config.toml."
        )
    return client


def _no_tool_support(error: Exception) -> bool:
    text = str(error).casefold()
    return "tool" in text and ("support" in text or "not allowed" in text or "unsupported" in text)


def _history(chat: dict) -> list[dict]:
    turns = [
        {"role": m["role"], "content": m["content"]}
        for m in chat.get("messages") or []
        if m.get("role") in ("user", "assistant") and not m.get("error") and m.get("content")
    ]
    return turns[-MAX_HISTORY_MESSAGES:]


def _call(client, model: str, messages: list[dict], use_tools: bool):
    from app.services.animation import llm as anim_llm

    extra = {"usage": {"include": True}} if "openrouter" in str(getattr(client, "base_url", "")) else {}
    kwargs = {"model": model, "messages": messages, "extra_body": extra}
    if use_tools:
        kwargs["tools"] = TOOLS
    response = client.chat.completions.create(**kwargs)
    return response, anim_llm._reported_cost(response)


def ask(chat: dict, question: str, df: pd.DataFrame, client=None, on_step=None, max_rounds: int = MAX_TOOL_ROUNDS) -> dict:
    """Answer ``question`` in ``chat``, save both turns, return the reply message.

    ``df`` is the full analytics dataset (report.build_dataset); the chat's
    data range is applied here. ``on_step(text)`` is told what the model is
    looking at while it works. Failures are saved as an error reply (kept
    out of later prompts) and raised as AssistantError.
    """
    from app.services import llm as llm_service

    question = (question or "").strip()
    if not question:
        raise AssistantError("Ask a question first.")
    data = scope(df, chat.get("range", DEFAULT_RANGE))
    model = chat.get("model") or default_model()
    chat.setdefault("messages", []).append({"role": "user", "content": question, "refs": list(chat.get("refs") or []), "at": time.time()})
    if chat.get("title", NEW_CHAT_TITLE) == NEW_CHAT_TITLE:
        chat["title"] = title_from(question)

    messages = [{"role": "system", "content": system_prompt(data, chat.get("refs") or [], chat.get("range", DEFAULT_RANGE))}, *_history(chat)]
    tool_log: list[dict] = []
    cost = 0.0
    use_tools = True
    reply = None
    try:
        client = client or _client()
        for round_number in range(max_rounds + 1):
            final_round = round_number == max_rounds
            if final_round:
                messages.append({"role": "system", "content": "Answer now with the data you have; no more tool calls."})
            try:
                response, spent = _call(client, model, messages, use_tools and not final_round)
            except Exception as exc:
                if use_tools and _no_tool_support(exc):
                    logger.info(f"assistant: {model} has no tool support, answering from attached data")
                    use_tools = False
                    response, spent = _call(client, model, messages, False)
                else:
                    raise
            cost += spent
            message = response.choices[0].message
            calls = getattr(message, "tool_calls", None) or []
            if not calls:
                reply = (message.content or "").strip()
                break
            messages.append(
                {
                    "role": "assistant",
                    "content": message.content or "",
                    "tool_calls": [{"id": c.id, "type": "function", "function": {"name": c.function.name, "arguments": c.function.arguments or "{}"}} for c in calls],
                }
            )
            for call in calls:
                try:
                    args = json.loads(call.function.arguments or "{}")
                except json.JSONDecodeError:
                    args = {}
                if on_step:
                    label = args.get("tag_id") or args.get("title_contains") or args.get("studio") or ""
                    on_step(f"{call.function.name} {label}".strip())
                tool_log.append({"name": call.function.name, "args": args})
                messages.append({"role": "tool", "tool_call_id": call.id, "content": run_tool(call.function.name, args, data)})
        if not reply:
            raise AssistantError("The model returned an empty answer. Try again or pick another model.")
    except AssistantError as exc:
        _save_reply(chat, f"⚠️ {exc}", model, cost, tool_log, error=True)
        raise
    except Exception as exc:
        detail = llm_service._sanitize_error_message(exc)
        _save_reply(chat, f"⚠️ {model} failed: {detail}", model, cost, tool_log, error=True)
        raise AssistantError(f"{model} failed: {detail}") from exc
    return _save_reply(chat, reply, model, cost, tool_log)


def _save_reply(chat: dict, content: str, model: str, cost: float, tool_log: list[dict], error: bool = False) -> dict:
    reply = {"role": "assistant", "content": content, "model": model, "cost": round(cost, 6), "tools": tool_log, "at": time.time()}
    if error:
        reply["error"] = True
    chat["messages"].append(reply)
    chat["cost"] = round(float(chat.get("cost") or 0) + cost, 6)
    save_chat(chat)
    return reply


# ------------------------------------------------------------- quick starts
STARTERS = [
    ("Which animation styles get the most views?", ["builtin:animation:insights", "builtin:animation:Main setting", "builtin:animation:Characters", "builtin:animation:Transitions"]),
    ("Suggest 10 titles for my next videos, based on what works", ["builtin:top"]),
    ("Which kinds of topics should I make more of, and which less?", ["builtin:category", "builtin:overview"]),
    ("Do batches do better than one-off videos?", ["builtin:batches", "builtin:overview"]),
]


def tag_ids_present(ids: list[str], df: pd.DataFrame) -> list[str]:
    known = {t["id"] for t in tags.all_tags(df)}
    return [i for i in ids if i in known]


def dimension_values(df: pd.DataFrame, studio: str, dim: str) -> list[str]:
    """Values a dimension takes among published videos, for building filters."""
    if df.empty or dim not in df.columns:
        return []
    data = df[df["live"]]
    if studio:
        data = data[data["studio"] == studio]
    return sorted({str(v) for v in data[dim].dropna() if str(v)})


def filter_dimensions(df: pd.DataFrame, studio: str) -> list[str]:
    return [d for d in report.feature_dimensions(df, studio or None) if d != "studio_label"]
