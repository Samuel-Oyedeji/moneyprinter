"""Daily storage clean-up for finished videos and the stock-clip cache.

Rendered videos are big and, once on YouTube, rarely needed again. The cron
hook (POST /api/v1/schedules/run) runs this right after the analytics sync:

  posted videos      heavy files deleted ``posted_days`` (7) after they went
                     up on YouTube: uploaded by the app, marked "Already
                     posted", or matched to a channel video by title
  never posted       deleted ``unposted_days`` (30) after they were made
  stock-clip cache   downloaded clips older than ``cache_days`` (7)

What goes per studio:

  Shorts         the task folder in storage/tasks (video, audio, subtitles)
  Animations     final.mp4 and the public/ folder (narration); project.json,
                 the script, storyboard and thumbnail stay
  Documentaries  the render in storage/tasks/<project> (thumbnail kept) and
                 the images/, audio/ and render/ folders; project.json,
                 fact sheet, script and sources stay

Never touched: anything booked, running or waiting for a retry on a calendar
(its upload reads the file), documentaries and animations that aren't
finished, anything modified in the last day, and storage/analytics.
Every video is recorded in analytics/items.csv before its files go, so the
Analytics page keeps all of it.

Settings live under [sweeper] in config.toml. Every deletion is logged to
storage/sweeper/log.csv.
"""

import csv
import json
import os
import shutil
import threading
import time
from datetime import date as date_cls
from datetime import datetime, timedelta

from loguru import logger

from app.config import config
from app.utils import utils

DEFAULTS = {"enabled": True, "posted_days": 7, "unposted_days": 30, "cache_days": 7}
# Nothing changed this recently is touched, whatever its age says.
_QUIET_SECONDS = 24 * 3600
_LOG_COLUMNS = ("swept_at", "studio", "key", "label", "reason", "bytes", "paths")
_run_lock = threading.Lock()


def settings() -> dict:
    current = {**DEFAULTS, **dict(config.sweeper)}
    for key in ("posted_days", "unposted_days", "cache_days"):
        current[key] = max(1, int(current[key]))
    current["enabled"] = bool(current["enabled"])
    return current


# ------------------------------------------------------------------ helpers
def _size(path: str) -> int:
    if os.path.isfile(path):
        return os.path.getsize(path)
    total = 0
    for root, _, files in os.walk(path):
        for name in files:
            try:
                total += os.path.getsize(os.path.join(root, name))
            except OSError:
                pass
    return total


def _newest_mtime(paths: list[str]) -> float:
    """When anything under ``paths`` last changed (0.0 when there is nothing)."""
    newest = 0.0
    for path in paths:
        if os.path.isfile(path):
            newest = max(newest, os.path.getmtime(path))
            continue
        for root, _, files in os.walk(path):
            for name in files:
                try:
                    newest = max(newest, os.path.getmtime(os.path.join(root, name)))
                except OSError:
                    pass
    return newest


def _to_date(value) -> date_cls | None:
    if not value:
        return None
    if isinstance(value, (int, float)):
        return datetime.fromtimestamp(float(value)).date() if value else None
    text = str(value)
    try:
        return datetime.fromisoformat(text.replace("Z", "+00:00")).date()
    except ValueError:
        try:
            return date_cls.fromisoformat(text[:10])
        except ValueError:
            return None


def posting_dates() -> tuple[list[dict], dict]:
    """Every app video and, for the posted ones, the day it went up.

    Uses the analytics catalog and reconciliation, so hand-posted videos
    count once the sync matched them, and records every item in items.csv
    (before anything is deleted). Returns ``(items, {key: date})``.
    """
    from app.services.analytics import catalog, reconcile
    from app.services.analytics import store as analytics_store

    items = catalog.build_items(persist=True)
    videos = analytics_store.channel_videos()
    by_video = {v["video_id"]: v for v in videos}
    result = reconcile.reconcile(items, videos, analytics_store.load_links())
    posted: dict = {}
    for item in items:
        dates = []
        for match in result["links"].get(item["key"], []):
            video = by_video.get(match["video_id"], {})
            # a scheduled upload is only live from its publishAt time
            day = max(filter(None, [_to_date(video.get("published_at")), _to_date(video.get("publish_at"))]), default=None)
            if day:
                dates.append(day)
        mark = item.get("posted") or {}
        if not dates and mark.get("manual"):
            dates.append(_to_date(mark.get("date")) or _to_date(item.get("created_at")))
        if not dates and item.get("known_video_ids"):
            # uploaded by the app, channel not synced: it went up when made
            dates.append(_to_date(item.get("created_at")))
        dates = [d for d in dates if d]
        if dates:
            posted[item["key"]] = max(dates)
    return items, posted


def _verdict(posted_on, created_on, today: date_cls, opts: dict) -> str:
    """Why these files may go, or "" to keep them."""
    if posted_on is not None:
        if posted_on <= today - timedelta(days=opts["posted_days"]):
            return f"posted {posted_on.isoformat()}, over {opts['posted_days']} days ago"
        return ""
    if created_on is not None and created_on <= today - timedelta(days=opts["unposted_days"]):
        return f"never posted, made {created_on.isoformat()}, over {opts['unposted_days']} days ago"
    return ""


# ------------------------------------------------------------------ studios
def _shorts_candidates(posted: dict, today: date_cls, opts: dict, now: float) -> list[dict]:
    from app.services import schedule as shorts_schedule
    from app.services.documentary import store as doc_store

    tasks_root = utils.task_dir()
    documentary_ids = {p["project_id"] for p in doc_store.list_projects()}
    # A failed or running calendar entry re-uploads straight from these files.
    protected = set()
    for entry in shorts_schedule.list_entries():
        if entry.get("status") in shorts_schedule.BUSY_STATUSES:
            protected.update(entry.get("task_ids") or [])
        for record in shorts_schedule.upload_records(entry):
            if not record.get("video_id") and record.get("path"):
                protected.add(os.path.basename(os.path.dirname(record["path"])))

    candidates = []
    for task_id in sorted(os.listdir(tasks_root)):
        folder = os.path.join(tasks_root, task_id)
        if not os.path.isdir(folder) or task_id in documentary_ids or task_id in protected:
            continue
        newest = _newest_mtime([folder])
        if not newest or now - newest < _QUIET_SECONDS:
            continue
        finals = sorted(n for n in os.listdir(folder) if n.startswith("final-") and n.endswith(".mp4"))
        keys = [f"shorts:{task_id}/{name}" for name in finals]
        posted_days = [posted.get(k) for k in keys]
        # variants of one task go together: posted only when all of them are
        posted_on = max(posted_days) if keys and all(posted_days) else None
        # a folder with no finished video is a failed run: the unposted rule
        reason = _verdict(posted_on, datetime.fromtimestamp(newest).date(), today, opts)
        if reason:
            data = _read_json(os.path.join(folder, "script.json")) or {}
            label = ((data.get("params") or {}).get("video_subject") or task_id)[:100]
            candidates.append(_candidate("shorts", keys[0] if keys else f"shorts:{task_id}", label, reason, [folder]))
    return candidates


def _animation_candidates(posted: dict, today: date_cls, opts: dict, now: float) -> list[dict]:
    from app.services.animation import jobs
    from app.services.animation import schedule as anim_schedule
    from app.services.animation import store

    busy = {e["project_id"] for e in anim_schedule.list_entries() if e.get("project_id") and e.get("status") in (*anim_schedule.ACTIVE_STATUSES, anim_schedule.STATUS_FAILED)}
    candidates = []
    for project in store.list_projects():
        pid = project["project_id"]
        if project.get("status") != store.STATUS_DONE or pid in busy or jobs.is_active(pid):
            continue
        paths = [p for p in (store.final_path(pid), store.path(pid, "public")) if os.path.exists(p)]
        if not paths or now - _newest_mtime(paths) < _QUIET_SECONDS:
            continue
        reason = _verdict(posted.get(f"animation:{pid}"), _to_date(project.get("created_at")), today, opts)
        if reason:
            label = ((project.get("youtube") or {}).get("title") or project.get("topic") or pid)[:100]
            candidates.append(_candidate("animation", f"animation:{pid}", label, reason, paths, project_id=pid))
    return candidates


def _documentary_candidates(posted: dict, today: date_cls, opts: dict, now: float) -> list[dict]:
    from app.services.documentary import doc_schedule, store

    busy = {e["project_id"] for e in doc_schedule.list_entries() if e.get("project_id") and e.get("status") in (*doc_schedule.ACTIVE_STATUSES, doc_schedule.STATUS_FAILED)}
    candidates = []
    for project in store.list_projects():
        pid = project["project_id"]
        if project.get("status") != store.STATUS_DONE or pid in busy:
            continue
        render = os.path.join(utils.task_dir(), pid)
        paths = [os.path.join(render, n) for n in sorted(os.listdir(render)) if not n.startswith("thumbnail")] if os.path.isdir(render) else []
        paths += [p for p in (os.path.join(store.project_dir(pid), d) for d in ("images", "audio", "render")) if os.path.isdir(p)]
        if not paths or now - _newest_mtime(paths) < _QUIET_SECONDS:
            continue
        reason = _verdict(posted.get(f"documentary:{pid}"), _to_date(project.get("created_at")), today, opts)
        if reason:
            script = store.load_script(pid) or {}
            label = ((script.get("youtube") or {}).get("title") or project.get("topic") or pid)[:100]
            candidates.append(_candidate("documentary", f"documentary:{pid}", label, reason, paths, project_id=pid))
    return candidates


def _read_json(path: str):
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except (OSError, json.JSONDecodeError):
        return None


def _candidate(studio: str, key: str, label: str, reason: str, paths: list[str], **extra) -> dict:
    return {"studio": studio, "key": key, "label": label, "reason": reason, "paths": paths, "bytes": sum(_size(p) for p in paths), **extra}


# --------------------------------------------------------------------- plan
def plan(today: date_cls | None = None, now: float | None = None) -> dict:
    """What a clean-up would delete right now. Deletes nothing."""
    from app.services import cache_manager

    opts = settings()
    today = today or date_cls.today()
    now = now or time.time()
    _, posted = posting_dates()
    candidates = []
    for name, finder in (("shorts", _shorts_candidates), ("animation", _animation_candidates), ("documentary", _documentary_candidates)):
        try:
            candidates.extend(finder(posted, today, opts, now))
        except Exception:
            logger.exception(f"sweeper: could not scan the {name} studio")
    cache = cache_manager.get_video_cache_stats(max_age_days=opts["cache_days"])
    return {
        "settings": opts,
        "videos": candidates,
        "video_bytes": sum(c["bytes"] for c in candidates),
        "cache_files": cache.file_count,
        "cache_bytes": cache.total_size,
    }


# ---------------------------------------------------------------------- run
def _delete(path: str) -> None:
    if os.path.isdir(path) and not os.path.islink(path):
        shutil.rmtree(path)
    elif os.path.lexists(path):
        os.remove(path)


def _log(rows: list[dict]) -> None:
    if not rows:
        return
    path = os.path.join(utils.storage_dir("sweeper", create=True), "log.csv")
    new_file = not os.path.isfile(path)
    with open(path, "a", encoding="utf-8-sig" if new_file else "utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=_LOG_COLUMNS)
        if new_file:
            writer.writeheader()
        writer.writerows(rows)


def _note_swept(candidate: dict) -> None:
    """Tell the studio its files are gone, so it doesn't offer to play them."""
    stamp = time.time()
    if candidate["studio"] == "animation":
        from app.services.animation import store

        store.update_project(candidate["project_id"], files_swept_at=stamp)
    elif candidate["studio"] == "documentary":
        from app.services.documentary import store

        project = store.load_project(candidate["project_id"])
        if project:
            project["files_swept_at"] = stamp
            store.save_project(project)


def run(dry_run: bool = False) -> dict:
    """Plan, then (unless ``dry_run``) delete and log. Never runs twice at once."""
    from app.services import cache_manager

    if not _run_lock.acquire(blocking=False):
        return {"skipped": True, "reason": "a clean-up is already running"}
    try:
        result = plan()
        if dry_run:
            return {**result, "dry_run": True}
        swept, freed, failed = [], 0, []
        stamp = datetime.now().isoformat(timespec="seconds")
        for candidate in result["videos"]:
            try:
                for path in candidate["paths"]:
                    _delete(path)
                _note_swept(candidate)
            except OSError as exc:
                logger.warning(f"sweeper: could not delete {candidate['key']}: {exc}")
                failed.append(candidate["key"])
                continue
            freed += candidate["bytes"]
            swept.append(
                {
                    "swept_at": stamp,
                    "studio": candidate["studio"],
                    "key": candidate["key"],
                    "label": candidate["label"],
                    "reason": candidate["reason"],
                    "bytes": candidate["bytes"],
                    "paths": " ".join(os.path.relpath(p, utils.storage_dir()) for p in candidate["paths"]),
                }
            )
        _log(swept)
        cache = cache_manager.clean_video_cache(max_age_days=result["settings"]["cache_days"])
        summary = {
            "dry_run": False,
            "videos_swept": len(swept),
            "video_bytes_freed": freed,
            "failed": failed,
            "cache_files_deleted": cache.deleted_count,
            "cache_bytes_freed": cache.deleted_size,
        }
        logger.info(f"sweeper: {summary}")
        return summary
    finally:
        _run_lock.release()


def run_scheduled() -> dict | None:
    """The cron hook's call: a full clean-up when [sweeper] enabled is on."""
    if not settings()["enabled"]:
        return None
    return run()


if __name__ == "__main__":
    # .venv/bin/python -m app.services.sweeper            delete
    # .venv/bin/python -m app.services.sweeper --dry-run  just list
    import sys

    print(json.dumps(run(dry_run="--dry-run" in sys.argv), ensure_ascii=False, default=str, indent=2))
