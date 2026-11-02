"""Discord messages from the studios, so the owner only looks when needed.

    alerts     right away (at the end of the tick that caused them): every
               incident, every video dropped by QA, and a "ready" ping for
               each finished video with the deadline to cancel it
    digest     once a day from DIGEST_HOUR local time: what went public, what
               goes public today, what is waiting, check-ins, problems,
               spend and the last tick
    heartbeat  the daily calendar cron (and the next tick) report when the
               hourly tick has been silent for HEARTBEAT_HOURS

Everything is best-effort: a Discord failure never stops a tick. State
(what was already sent) lives in storage/studios/_notify.json.
"""

import json
import os
import threading
from datetime import datetime, timedelta, timezone

from loguru import logger

from app.config import config
from app.services.studios import model, store

DIGEST_HOUR = 7
HEARTBEAT_HOURS = 3
MAX_LINES = 12

_lock = threading.Lock()


# -------------------------------------------------------------------- state
def _state_path() -> str:
    return os.path.join(store.studios_dir(), "_notify.json")


def load_state() -> dict:
    try:
        with open(_state_path(), "r", encoding="utf-8") as f:
            return json.load(f)
    except (OSError, json.JSONDecodeError):
        return {}


def _save_state(state: dict) -> None:
    path = _state_path()
    tmp = f"{path}.{os.getpid()}.tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(state, f, indent=2)
    os.replace(tmp, path)


def _update_state(**fields) -> dict:
    with _lock:
        state = {**load_state(), **fields}
        _save_state(state)
        return state


# -------------------------------------------------------------------- sending
def page_url() -> str:
    base = str(config.studios.get("app_url", "") or "").strip().rstrip("/")
    return f"{base}/Studios" if base else ""


def _send(content: str, lines: list[str], color: int) -> bool:
    from app.services import discord_notify

    service = discord_notify.discord_notify_service
    if not service.is_configured():
        return False
    description = "\n".join(lines[:MAX_LINES])
    if len(lines) > MAX_LINES:
        description += f"\n…and {len(lines) - MAX_LINES} more on the Studios page."
    link = page_url()
    if link:
        description += f"\n\n[Open the Studios page]({link})"
    try:
        return service.send(content, embed={"description": description[:4000], "color": color})
    except Exception as exc:
        logger.warning(f"studio notification failed: {exc}")
        return False


def _local(moment: datetime) -> datetime:
    from app.services.studios import runner

    return moment.astimezone(runner.local_tz())


def _when(moment: datetime) -> str:
    return _local(moment).strftime("%a %d %b %H:%M")


# ------------------------------------------------------------------- alerts
def alert_lines(studio: dict, events: list[dict]) -> list[str]:
    """One line per event worth interrupting the owner for, oldest first."""
    from app.services.studios import runner

    lines = []
    for event in sorted(events, key=lambda e: e["ts"]):
        data = event.get("data") or {}
        if event["type"] == "incident":
            lines.append(f"⚠️ {event['summary']}")
        elif event["type"] == "qa_failed" and not data.get("retry"):
            lines.append(f"🚫 {event['summary']}")
        elif event["type"] == "produced" and config.studios.get("notify_ready", True):
            slot = store.get_slot(studio["id"], data.get("slot_id", "")) or {}
            if slot.get("status") == model.SLOT_READY:
                deadline = runner.upload_after(studio, slot)
                lines.append(f"🎬 {event['summary'].split('. It uploads')[0]}. Cancel before {_when(deadline)} to stop it.")
    return lines


def flush(studio: dict, now: datetime) -> int:
    """Send what happened since the last flush. The first flush only sets
    the mark, so turning notifications on doesn't replay old history."""
    marks = load_state().get("alerted_until") or {}
    since = marks.get(studio["id"])
    events = [] if since is None else [e for e in store.list_events(studio["id"], limit=200) if e["ts"] > since]
    newest = max([e["ts"] for e in store.list_events(studio["id"], limit=1)] or [0])
    _update_state(alerted_until={**marks, studio["id"]: max(newest, since or 0)})
    lines = alert_lines(studio, events)
    if not lines:
        return 0
    problems = any(line.startswith(("⚠️", "🚫")) for line in lines)
    _send(f"{'⚠️' if problems else '🎬'} {studio['name']}", lines, 0xE67E22 if problems else 0x3498DB)
    return len(lines)


# ------------------------------------------------------------------- digest
def digest_lines(studio: dict, now: datetime) -> list[str]:
    from app.services.studios import evaluate, runner

    today = _local(now).date()
    yesterday_start = now - timedelta(days=1)
    queue = store.load_queue(studio["id"])
    lines = [f"**{studio['name']}**" + (" (paused)" if studio.get("paused") else "")]

    def publish_time(slot):
        try:
            return datetime.strptime(slot["publish_at"], "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc)
        except (KeyError, ValueError):
            return None

    went_public = [s for s in queue if (p := publish_time(s)) and yesterday_start <= p <= now]
    if went_public:
        lines.append(f"✅ Went public in the last day: {', '.join(repr(s['brief']['topic']) for s in went_public)}")
    later = [s for s in queue if (p := publish_time(s)) and p > now and _local(p).date() == today]
    if later:
        lines.append("📅 Going public today: " + ", ".join(f"{_local(publish_time(s)).strftime('%H:%M')} {s['brief']['topic']!r}" for s in later))
    for slot in (s for s in queue if s["status"] == model.SLOT_READY):
        lines.append(f"⏳ Waiting: {slot['brief']['topic']!r} for {slot['date']} {slot['time']}, uploads {_when(runner.upload_after(studio, slot))}")
    upcoming = [s for s in queue if s["status"] == model.SLOT_PLANNED and not s["reserve"] and runner.slot_utc(s) <= now + timedelta(hours=36)]
    if upcoming:
        lines.append(f"🛠 To be made in the next 36h: {len(upcoming)}")

    recent = [e for e in store.list_events(studio["id"], limit=300) if e["ts"] >= yesterday_start.timestamp()]
    for event in recent:
        if event["type"] == "result" and (event.get("data") or {}).get("kind") == "checkin":
            lines.append(f"📈 {event['summary']}")
    problems = [e for e in recent if e["type"] == "incident" or (e["type"] == "qa_failed" and not (e.get("data") or {}).get("retry"))]
    if problems:
        lines.append(f"⚠️ {len(problems)} problem(s) in the last day, latest: {problems[0]['summary']}")

    costs = evaluate.production_costs(studio, queue)
    spent = evaluate.spend(queue, costs, today, evaluate.planner_spend(studio["id"]))["this_week"]
    lines.append(f"💵 This week: ${spent:.2f} of ${studio['weekly_budget_usd']:g}")
    return lines


def send_digest(now: datetime, force: bool = False) -> bool:
    """The daily digest, once a day from DIGEST_HOUR (or now, with force)."""
    local = _local(now)
    state = load_state()
    if not force and (local.hour < DIGEST_HOUR or state.get("digest_day") == local.date().isoformat()):
        return False
    lines = []
    for studio in store.list_studios():
        lines += digest_lines(studio, now) + [""]
    last_tick = state.get("last_tick")
    lines.append(f"Last tick: {_when(datetime.fromtimestamp(last_tick, timezone.utc))}" if last_tick else "No tick has run yet.")
    _update_state(digest_day=local.date().isoformat())
    return _send(f"📋 Studios: {local.strftime('%A %d %B')}", lines, 0x95A5A6)


# ---------------------------------------------------------------- heartbeat
def record_tick(now: datetime) -> None:
    """Note a finished tick; report it if ticks had stopped for a while."""
    last = load_state().get("last_tick")
    _update_state(last_tick=now.timestamp())
    if last and now.timestamp() - last > HEARTBEAT_HOURS * 3600:
        gap = (now.timestamp() - last) / 3600
        _send("✅ Studios: the tick is running again", [f"It had not run for {gap:.0f} hours (since {_when(datetime.fromtimestamp(last, timezone.utc))})."], 0x2ECC71)


def check_heartbeat(now: datetime | None = None) -> bool:
    """Called by the daily calendar cron: alert once per silence when the
    hourly tick hasn't run for HEARTBEAT_HOURS while studios are enabled."""
    now = now or datetime.now(timezone.utc)
    if not config.studios.get("enabled", False) or config.studios.get("paused", False):
        return False
    state = load_state()
    last = state.get("last_tick")
    if not last or now.timestamp() - last <= HEARTBEAT_HOURS * 3600 or state.get("heartbeat_alerted_for") == last:
        return False
    _update_state(heartbeat_alerted_for=last)
    return _send(
        "🛑 Studios: the hourly tick has stopped",
        [
            f"The last tick was {_when(datetime.fromtimestamp(last, timezone.utc))}. Nothing is being made or uploaded.",
            "Check the crontab line for POST /api/v1/studios/tick and the API container.",
        ],
        0xE74C3C,
    )
