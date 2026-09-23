"""Scheduling and YouTube upload for animations.

Mirrors the Shorts and documentary calendars: entries live in
storage/animation/_schedule.json and the existing cron hook
(POST /api/v1/schedules/run) runs whatever is due.

  library - a finished video; on the due date it is uploaded with publishAt
            set to the entry's time (private until then).
  auto    - a topic; on the due date the video is generated, then uploaded.

Every booking goes through app.services.upload_budget, so animations never
push a day past the 6 uploads that Shorts, documentaries and animations
share. Videos the owner uploads by hand are marked "posted": they leave the
calendar and stop counting against the budget.
"""

import json
import os
import re
import threading
import time
import uuid
from datetime import date as date_cls
from datetime import datetime, timedelta

from loguru import logger

from app.services import upload_budget
from app.services.animation import store

STATUS_PENDING = "pending"
STATUS_GENERATING = "generating"
STATUS_UPLOADING = "uploading"
STATUS_SCHEDULED = "scheduled"  # on YouTube, private until publishAt
STATUS_UPLOADED = "uploaded"  # on YouTube as a private draft
STATUS_POSTED = "posted"  # the owner uploaded it by hand
STATUS_FAILED = "failed"

ACTIVE_STATUSES = (STATUS_PENDING, STATUS_GENERATING, STATUS_UPLOADING)
DONE_STATUSES = (STATUS_SCHEDULED, STATUS_UPLOADED, STATUS_POSTED)

_store_lock = threading.RLock()
_run_lock = threading.Lock()


class BudgetError(ValueError):
    """Booking would exceed the shared daily upload budget."""


def _schedule_file() -> str:
    return os.path.join(store.animation_dir(), "_schedule.json")


def _load() -> list[dict]:
    try:
        with open(_schedule_file(), "r", encoding="utf-8") as f:
            data = json.load(f)
        return data if isinstance(data, list) else []
    except (OSError, json.JSONDecodeError):
        return []


def _save(entries: list[dict]) -> None:
    with _store_lock:
        path = _schedule_file()
        tmp = f"{path}.tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(entries, f, ensure_ascii=False, indent=2)
        os.replace(tmp, path)


def _validate_date(value: str) -> str:
    value = (value or "").strip()
    if not re.fullmatch(r"\d{4}-\d{2}-\d{2}", value):
        raise ValueError(f"invalid date (expected YYYY-MM-DD): {value!r}")
    datetime.strptime(value, "%Y-%m-%d")
    return value


def _validate_time(value: str) -> str:
    value = (value or "").strip()
    if value and not re.fullmatch(r"\d{2}:\d{2}", value):
        raise ValueError(f"invalid post time (expected HH:MM): {value!r}")
    return value


def counts_toward_budget(entry: dict) -> bool:
    return entry.get("status") not in (STATUS_FAILED, STATUS_POSTED)


def list_entries(start_date: str | None = None, end_date: str | None = None) -> list[dict]:
    entries = [
        e
        for e in _load()
        if (not start_date or e.get("date", "") >= start_date) and (not end_date or e.get("date", "") <= end_date)
    ]
    entries.sort(key=lambda e: (e.get("date", ""), e.get("post_time", "")))
    return entries


def get_entry(entry_id: str) -> dict | None:
    return next((e for e in _load() if e.get("id") == entry_id), None)


def entries_for_project(project_id: str) -> list[dict]:
    return [e for e in list_entries() if e.get("project_id") == project_id]


def _patch(entry_id: str, **fields) -> dict:
    with _store_lock:
        entries = _load()
        for entry in entries:
            if entry.get("id") == entry_id:
                entry.update(fields)
                entry["updated_at"] = time.time()
                _save(entries)
                return entry
    raise KeyError(f"animation schedule entry not found: {entry_id}")


def _new_entry(item: dict, batch_id: str = "") -> dict:
    mode = item.get("mode") or ("library" if item.get("project_id") else "auto")
    if mode not in ("library", "auto"):
        raise ValueError(f"invalid mode: {mode!r}")
    if mode == "library":
        project = store.load_project(item.get("project_id", ""))
        if not project or project.get("status") != store.STATUS_DONE:
            raise ValueError(f"video {item.get('project_id')!r} is not a finished animation")
        if (project.get("posted") or {}).get("manual"):
            raise ValueError("that video is marked as already posted")
    elif not str(item.get("topic", "")).strip():
        raise ValueError("auto entries need a topic")
    return {
        "id": uuid.uuid4().hex[:12],
        "date": _validate_date(item["date"]),
        "post_time": _validate_time(item.get("post_time", "")),
        "mode": mode,
        "project_id": item.get("project_id", "") if mode == "library" else "",
        "topic": str(item.get("topic", "")).strip(),
        "context": str(item.get("context", "")).strip(),
        "seconds": int(item.get("seconds") or 30),
        "aspect": item.get("aspect") or "9:16",
        "voice": item.get("voice", ""),
        "status": STATUS_PENDING,
        "youtube_video_id": "",
        "error": "",
        "batch_id": batch_id,
        "created_at": time.time(),
        "updated_at": time.time(),
    }


def _check_budget(new_items: list[dict]) -> None:
    per_day: dict[str, int] = {}
    for item in new_items:
        per_day[item["date"]] = per_day.get(item["date"], 0) + 1
    over = []
    for day, extra in sorted(per_day.items()):
        load = upload_budget.daily_load(day)
        if load["total"] + extra > load["budget"]:
            over.append(f"{day} ({load['total']} booked + {extra} new > {load['budget']})")
    if over:
        raise BudgetError("over the daily YouTube upload budget on " + ", ".join(over))


def create_entries(items: list[dict]) -> list[dict]:
    """Book several entries at once — all or nothing, budget-checked."""
    batch_id = uuid.uuid4().hex[:8] if len(items) > 1 else ""
    new = [_new_entry(item, batch_id) for item in items]
    library_ids = [e["project_id"] for e in new if e["project_id"]]
    if len(library_ids) != len(set(library_ids)):
        raise ValueError("the same video appears twice in this batch")
    for pid in library_ids:
        if any(e["status"] in ACTIVE_STATUSES + DONE_STATUSES for e in entries_for_project(pid)):
            raise ValueError(f"video {pid} is already scheduled or posted")
    with _store_lock:
        _check_budget(new)
        entries = _load()
        entries.extend(new)
        _save(entries)
    return new


def create_entry(**item) -> dict:
    return create_entries([item])[0]


def delete_entry(entry_id: str) -> None:
    with _store_lock:
        _save([e for e in _load() if e.get("id") != entry_id])


def reset_entry(entry_id: str) -> dict:
    return _patch(entry_id, status=STATUS_PENDING, error="")


def reschedule_entry(entry_id: str, day: str, post_time: str) -> dict:
    entry = get_entry(entry_id)
    if not entry:
        raise KeyError(entry_id)
    day, post_time = _validate_date(day), _validate_time(post_time)
    if day != entry["date"] and counts_toward_budget(entry):
        _check_budget([{"date": day}])
    return _patch(entry_id, date=day, post_time=post_time)


def mark_posted(project_id: str, url: str = "", posted_on: str = "") -> dict:
    """The owner uploaded this video themselves: record it and free its slot."""
    project = store.mark_posted(project_id, url=url, posted_on=posted_on)
    for entry in entries_for_project(project_id):
        if entry["status"] in (STATUS_PENDING, STATUS_FAILED):
            _patch(entry["id"], status=STATUS_POSTED, error="")
    return project


# ------------------------------------------------------------ batch planning
def _slot_times(per_day: int) -> list[str]:
    from app.services import schedule as shorts_schedule

    return shorts_schedule.even_slot_times(per_day)


def _now() -> datetime:
    from app.services import schedule as shorts_schedule

    return shorts_schedule._planning_now()


def plan_batch(items: list[dict], per_day: int = 1, start_date: str | None = None, now: datetime | None = None, horizon_days: int = 365) -> dict:
    """Spread items over the next days that still have upload budget left.

    Nothing is written. Each day takes at most `per_day` of these items and
    never more than the budget the other calendars leave free; slot times
    are spread evenly through waking hours and must still be in the future.
    """
    if not items:
        raise ValueError("nothing to schedule")
    if not isinstance(per_day, int) or not 1 <= per_day <= upload_budget.DAILY_BUDGET:
        raise ValueError(f"per_day must be between 1 and {upload_budget.DAILY_BUDGET}")
    reference = now or _now()
    day = date_cls.fromisoformat(_validate_date(start_date)) if start_date else reference.date()
    slots = _slot_times(per_day)
    planned: list[dict] = []
    skipped_full: list[str] = []
    last_day = day + timedelta(days=horizon_days)
    pending = list(items)
    while pending and day <= last_day:
        iso = day.isoformat()
        free_slots = [s for s in slots if datetime.combine(day, datetime.strptime(s, "%H:%M").time()) > reference]
        taken = {e.get("post_time") for e in list_entries(iso, iso) if counts_toward_budget(e)}
        free_slots = [s for s in free_slots if s not in taken]
        room = min(len(free_slots), upload_budget.daily_load(iso)["left"])
        if room <= 0 and free_slots:
            skipped_full.append(iso)
        for slot in free_slots[:room]:
            if not pending:
                break
            planned.append({**pending.pop(0), "date": iso, "post_time": slot})
        day += timedelta(days=1)
    if pending:
        raise ValueError(f"could not fit {len(pending)} video(s) within {horizon_days} days")
    return {"items": planned, "dates": sorted({p["date"] for p in planned}), "skipped_full_days": skipped_full}


# ---------------------------------------------------------------- execution
def _ensure_video(entry: dict) -> dict:
    """The entry's finished project; auto entries generate it first."""
    from app.services.animation import pipeline

    project_id = entry.get("project_id", "")
    if not project_id:
        project = store.create_project(
            topic=entry["topic"],
            context=entry.get("context", ""),
            seconds=entry.get("seconds", 30),
            aspect=entry.get("aspect", "9:16"),
            voice=entry.get("voice", ""),
            source="schedule",
        )
        project_id = project["project_id"]
        _patch(entry["id"], project_id=project_id)
    project = store.load_project(project_id)
    if not project:
        raise RuntimeError(f"video {project_id} not found on disk")
    if project.get("status") != store.STATUS_DONE:
        project = pipeline.run_project(project_id)
        if project.get("status") != store.STATUS_DONE:
            raise RuntimeError(f"generation failed: {project.get('error', '')}")
    return project


def _upload(entry: dict, project: dict) -> str:
    from app.services import schedule as shorts_schedule
    from app.services import youtube_upload
    from app.services.animation import metadata, storyboard

    pid = project["project_id"]
    meta = project.get("youtube") or {}
    if not meta.get("title"):
        board = store.read_json(store.path(pid, "storyboard.json")) or {}
        meta = metadata.generate(project["topic"], storyboard.narration_text(board), project["aspect"], board.get("title", ""))
        store.update_project(pid, youtube=meta)
    publish_at = shorts_schedule._compute_publish_at(entry)
    thumb = store.thumb_path(pid) if project.get("aspect") == "16:9" and os.path.isfile(store.thumb_path(pid)) else None
    result = youtube_upload.youtube_upload_service.upload_video(
        video_path=store.final_path(pid),
        title=meta.get("title") or project["topic"],
        description=meta.get("description", ""),
        tags=meta.get("tags", []),
        thumbnail_path=thumb,
        publish_at=publish_at,
    )
    if not result.get("success"):
        raise RuntimeError(result.get("error", "unknown upload error"))
    video_id = result["video_id"]
    _patch(entry["id"], status=STATUS_SCHEDULED if publish_at else STATUS_UPLOADED, youtube_video_id=video_id, error="")
    store.update_project(pid, youtube_video_id=video_id, uploaded_at=time.time(), publish_at=publish_at or "")
    try:
        from app.services import discord_notify

        discord_notify.discord_notify_service.notify_video_ready(
            title=meta.get("title", ""),
            youtube_video_id=video_id,
            scheduled_date=entry["date"],
            topic=project["topic"],
            post_time=entry.get("post_time", ""),
            publish_at=publish_at,
        )
    except Exception as exc:
        logger.warning(f"discord notify failed: {exc}")
    return video_id


def run_entry(entry_id: str) -> dict:
    entry = get_entry(entry_id)
    if not entry:
        raise KeyError(entry_id)
    try:
        _patch(entry_id, status=STATUS_GENERATING, error="")
        project = _ensure_video(get_entry(entry_id))
        _patch(entry_id, status=STATUS_UPLOADING)
        _upload(get_entry(entry_id), project)
        logger.success(f"animation schedule entry {entry_id} done")
    except Exception as exc:
        logger.exception(f"animation schedule entry {entry_id} failed")
        _patch(entry_id, status=STATUS_FAILED, error=str(exc)[:1000])
    return get_entry(entry_id)


def run_due_entries(run_date: str | None = None) -> dict:
    """Run every pending entry due on/before run_date (default: today)."""
    if not _run_lock.acquire(blocking=False):
        logger.info("animation schedule run already in progress, skipping")
        return {"skipped": True}
    try:
        today = run_date or date_cls.today().isoformat()
        due = [e for e in list_entries() if e.get("status") == STATUS_PENDING and e.get("date", "9999-99-99") <= today]
        logger.info(f"animation schedule: {len(due)} due entries for {today}")
        for entry in due:
            run_entry(entry["id"])
        return {"skipped": False, "ran": len(due)}
    finally:
        _run_lock.release()


def upload_now(project_id: str) -> dict:
    """Book today's budget for an immediate private upload and run it."""
    entry = create_entry(date=date_cls.today().isoformat(), post_time="", project_id=project_id)
    threading.Thread(target=run_entry, args=(entry["id"],), daemon=True, name="animation-upload").start()
    return entry
