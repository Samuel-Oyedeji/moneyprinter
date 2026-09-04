"""Scheduling and YouTube upload for documentary films.

Documentaries get their own calendar (separate from the short-form
scheduler) stored in storage/documentary/_schedule.json. Two entry modes:

  library - a finished project picked from the Library tab; on the due date
            the film is uploaded with publishAt set to the entry's time.
  auto    - a topic only: on the due date the full autopilot pipeline runs
            (research → script → images → render) and the film is uploaded
            in the same pass.

Uploads reuse the existing YoutubeUploadService (thumbnail + publishAt) and
the short-form scheduler's publish-time math. The YouTube Data API's
default quota allows ~6 uploads/day (videos.insert costs 1600 of 10000
units), shared between Shorts and documentaries — daily_upload_load() feeds
the UI warnings for that.
"""

import json
import os
import re
import threading
import time
import uuid
from datetime import date as date_cls
from datetime import datetime

from loguru import logger

from app.services.documentary import store, thumbnail
from app.utils import utils

STATUS_PENDING = "pending"
STATUS_GENERATING = "generating"
STATUS_UPLOADING = "uploading"
STATUS_SCHEDULED = "scheduled"  # uploaded with a publishAt time
STATUS_UPLOADED = "uploaded"  # uploaded as a private draft
STATUS_FAILED = "failed"

ACTIVE_STATUSES = (STATUS_PENDING, STATUS_GENERATING, STATUS_UPLOADING)
YOUTUBE_DAILY_UPLOAD_BUDGET = 6  # videos.insert = 1600 of 10000 quota units

_store_lock = threading.RLock()
_run_lock = threading.Lock()


def _schedule_file() -> str:
    return os.path.join(store.documentary_dir(), "_schedule.json")


def _load_entries() -> list[dict]:
    try:
        with open(_schedule_file(), "r", encoding="utf-8") as f:
            data = json.load(f)
        return data if isinstance(data, list) else []
    except (OSError, json.JSONDecodeError):
        return []


def _save_entries(entries: list[dict]) -> None:
    with _store_lock:
        path = _schedule_file()
        tmp_path = f"{path}.tmp"
        with open(tmp_path, "w", encoding="utf-8") as f:
            json.dump(entries, f, ensure_ascii=False, indent=2)
        os.replace(tmp_path, path)


def _validate_date(value: str) -> str:
    value = (value or "").strip()
    if not re.fullmatch(r"\d{4}-\d{2}-\d{2}", value):
        raise ValueError(f"invalid date (expected YYYY-MM-DD): {value!r}")
    datetime.strptime(value, "%Y-%m-%d")
    return value


def _validate_post_time(value: str) -> str:
    value = (value or "").strip()
    if value and not re.fullmatch(r"\d{2}:\d{2}", value):
        raise ValueError(f"invalid post time (expected HH:MM): {value!r}")
    return value


def list_entries() -> list[dict]:
    entries = _load_entries()
    entries.sort(key=lambda e: (e.get("date", ""), e.get("post_time", "")))
    return entries


def get_entry(entry_id: str) -> dict | None:
    for entry in _load_entries():
        if entry.get("id") == entry_id:
            return entry
    return None


def create_entry(
    date: str,
    post_time: str = "",
    mode: str = "library",
    project_id: str = "",
    topic: str = "",
    user_notes: str = "",
    target_minutes: float = 0.0,
) -> dict:
    if mode not in ("library", "auto"):
        raise ValueError(f"invalid mode: {mode!r}")
    if mode == "library" and not project_id:
        raise ValueError("library entries need a project_id")
    if mode == "auto" and not topic.strip():
        raise ValueError("auto entries need a topic")

    entry = {
        "id": uuid.uuid4().hex[:12],
        "date": _validate_date(date),
        "post_time": _validate_post_time(post_time),
        "mode": mode,
        "project_id": project_id,
        "topic": topic.strip(),
        "user_notes": user_notes.strip(),
        "target_minutes": float(target_minutes or 0.0),
        "status": STATUS_PENDING,
        "youtube_video_id": "",
        "error": "",
        "created_at": time.time(),
        "updated_at": time.time(),
    }
    with _store_lock:
        entries = _load_entries()
        entries.append(entry)
        _save_entries(entries)
    return entry


def delete_entry(entry_id: str) -> None:
    with _store_lock:
        entries = [e for e in _load_entries() if e.get("id") != entry_id]
        _save_entries(entries)


def reset_entry(entry_id: str) -> dict:
    """Put a failed/stuck entry back to pending for a retry."""
    return _patch_entry(entry_id, status=STATUS_PENDING, error="")


def _patch_entry(entry_id: str, **fields) -> dict:
    with _store_lock:
        entries = _load_entries()
        for entry in entries:
            if entry.get("id") == entry_id:
                entry.update(fields)
                entry["updated_at"] = time.time()
                _save_entries(entries)
                return entry
    raise KeyError(f"schedule entry not found: {entry_id}")


def daily_upload_load(date: str) -> dict:
    """Planned YouTube uploads on a date, across Shorts and documentaries."""
    from app.services import schedule as shorts_schedule

    shorts = 0
    for entry in shorts_schedule.list_entries(start_date=date, end_date=date):
        if entry.get("status") != "failed":
            shorts += int(entry.get("video_count", 1) or 1)
    docs = sum(
        1
        for entry in _load_entries()
        if entry.get("date") == date and entry.get("status") != STATUS_FAILED
    )
    total = shorts + docs
    return {
        "shorts": shorts,
        "documentaries": docs,
        "total": total,
        "budget": YOUTUBE_DAILY_UPLOAD_BUDGET,
        "over_budget": total > YOUTUBE_DAILY_UPLOAD_BUDGET,
    }


def sources_block(project_id: str, limit: int = 8) -> str:
    """Research-source attribution lines for the video description."""
    factsheet = store.load_factsheet(project_id) or {}
    lines = []
    for source in (factsheet.get("source_index") or [])[:limit]:
        title = source.get("title") or source.get("domain") or ""
        url = source.get("url", "")
        if url:
            lines.append(f"{title} — {url}".strip(" —"))
    return "\n".join(lines)


# ---------------------------------------------------------------- execution
def _resolve_project(entry: dict) -> dict:
    """Load (or, for auto entries, create) the entry's project."""
    project_id = entry.get("project_id", "")
    if project_id:
        project = store.load_project(project_id)
        if not project:
            raise RuntimeError(f"project {project_id} not found on disk")
        return project

    project = store.create_project(
        topic=entry["topic"],
        user_notes=entry.get("user_notes", ""),
        auto_approve_factsheet=True,
        auto_approve_script=True,
        auto_approve_images=True,
        target_minutes=entry.get("target_minutes", 0.0),
    )
    _patch_entry(entry["id"], project_id=project["project_id"])
    entry["project_id"] = project["project_id"]
    return project


def _ensure_project_done(project: dict) -> dict:
    """Drive an unfinished project to done via the autopilot pipeline."""
    from app.services.documentary import pipeline

    if project.get("status") == store.STATUS_DONE:
        return project
    # Auto entries own their projects, so forcing the auto flags is safe and
    # makes resume-after-failure deterministic.
    project.update(
        auto_approve_factsheet=True,
        auto_approve_script=True,
        auto_approve_images=True,
    )
    store.save_project(project)
    if project["status"] in (store.STATUS_CREATED, store.STATUS_RESEARCHING):
        pipeline.run_research_stage(project)
    else:
        pipeline.retry_failed(project)
    project = store.load_project(project["project_id"]) or project
    if project.get("status") != store.STATUS_DONE:
        raise RuntimeError(
            f"pipeline ended in status {project.get('status')!r}: "
            f"{project.get('error', '')}"
        )
    return project


def _upload_entry(entry: dict, project: dict) -> None:
    from app.services import discord_notify, schedule as shorts_schedule
    from app.services import youtube_upload
    from app.services.documentary import costs, images as images_service
    from app.services.documentary import scriptwriter

    project_id = project["project_id"]
    final_path = os.path.join(utils.task_dir(project_id), "final-1.mp4")
    if not os.path.isfile(final_path):
        raise RuntimeError("final video missing; re-render the project")

    costs.set_project(project_id)
    script = store.load_script(project_id) or {}
    youtube_meta = scriptwriter.ensure_youtube_packaging(project_id, script)
    title = youtube_meta.get("title") or project["topic"]
    description = youtube_meta.get("description", "")
    # Research sources sit above image credits: they back the narration and
    # matter more to viewers of a factual channel.
    sources = sources_block(project_id)
    if sources:
        description = f"{description}\n\nSources:\n{sources}".strip()
    credits = images_service.credits_block(store.load_images(project_id) or {})
    if credits:
        description = f"{description}\n\nImage credits:\n{credits}".strip()
    tags = youtube_meta.get("tags", [])

    thumb = thumbnail.ensure_thumbnail(project)

    publish_at = shorts_schedule._compute_publish_at(entry)
    result = youtube_upload.youtube_upload_service.upload_video(
        video_path=final_path,
        title=title,
        description=description,
        tags=tags,
        thumbnail_path=thumb,
        publish_at=publish_at,
    )
    if not result.get("success"):
        raise RuntimeError(result.get("error", "unknown upload error"))

    video_id = result["video_id"]
    _patch_entry(
        entry["id"],
        status=STATUS_SCHEDULED if publish_at else STATUS_UPLOADED,
        youtube_video_id=video_id,
        error="",
    )
    try:
        discord_notify.discord_notify_service.notify_video_ready(
            title=title,
            youtube_video_id=video_id,
            scheduled_date=entry["date"],
            topic=project["topic"],
            post_time=entry.get("post_time", ""),
            publish_at=publish_at,
        )
    except Exception as exc:
        logger.warning(f"discord notify failed: {exc}")


def _run_entry(entry: dict) -> None:
    entry_id = entry["id"]
    logger.info(
        f"running documentary schedule entry {entry_id}: "
        f"mode={entry['mode']}, date={entry['date']}, "
        f"topic={entry.get('topic') or entry.get('project_id')}"
    )
    try:
        _patch_entry(entry_id, status=STATUS_GENERATING, error="")
        project = _resolve_project(entry)
        project = _ensure_project_done(project)
        _patch_entry(entry_id, status=STATUS_UPLOADING)
        _upload_entry(entry, project)
        logger.success(f"documentary schedule entry {entry_id} completed")
    except Exception as exc:
        logger.exception(f"documentary schedule entry {entry_id} failed")
        _patch_entry(entry_id, status=STATUS_FAILED, error=str(exc))


def run_due_entries(run_date: str | None = None) -> dict:
    """Run every pending entry due on/before run_date (default: today)."""
    if not _run_lock.acquire(blocking=False):
        logger.info("documentary schedule run already in progress, skipping")
        return {"skipped": True}
    try:
        today = run_date or date_cls.today().isoformat()
        due = [
            entry
            for entry in list_entries()
            if entry.get("status") == STATUS_PENDING
            and entry.get("date", "9999-99-99") <= today
        ]
        logger.info(f"documentary schedule: {len(due)} due entries for {today}")
        for entry in due:
            _run_entry(entry)
        return {"skipped": False, "ran": len(due)}
    finally:
        _run_lock.release()
