"""
Content-calendar scheduling for automated video generation.

Entries live in ``storage/schedule/schedule.json``. Each entry describes one
scheduled batch: a date, a topic, how many videos to make, and a format
preset (Shorts 9:16 or horizontal 16:9). A daily cron hit on
``POST /v1/schedules/run`` (or ``python -m app.services.schedule``) picks up
every pending entry due today or earlier, generates the videos through the
existing task pipeline, uploads them to YouTube as private drafts with
LLM-generated metadata, and alerts the owner via Discord.

Generation parameters not covered by the preset (voice, subtitles, BGM,
video source…) are inherited from the saved WebUI defaults in ``config.ui``,
so the scheduler always produces the same style of video the owner last
configured interactively.
"""
from __future__ import annotations

import json
import os
import subprocess
import tempfile
import threading
from datetime import date as date_cls
from datetime import datetime, timezone
from typing import Optional

from loguru import logger

from app.config import config
from app.models.schema import VideoParams
from app.utils import utils

STATUS_PENDING = "pending"
STATUS_GENERATING = "generating"
STATUS_DONE = "done"
STATUS_FAILED = "failed"

# 格式预设只覆盖画幅；其余参数继承 WebUI 保存的默认值，
# 保证排期生成的视频风格与手动生成一致。
PRESETS = {
    "shorts": {"label": "Shorts (9:16)", "video_aspect": "9:16"},
    "horizontal": {"label": "Horizontal (16:9)", "video_aspect": "16:9"},
}

_store_lock = threading.RLock()
_run_lock = threading.Lock()


def _schedule_file() -> str:
    return os.path.join(utils.storage_dir("schedule", create=True), "schedule.json")


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _load_entries() -> list[dict]:
    path = _schedule_file()
    if not os.path.isfile(path):
        return []
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
        entries = data.get("entries", [])
        return entries if isinstance(entries, list) else []
    except (OSError, json.JSONDecodeError) as e:
        logger.error(f"failed to load schedule file, treating as empty: {str(e)}")
        return []


def _save_entries(entries: list[dict]) -> None:
    path = _schedule_file()
    serialized = json.dumps({"entries": entries}, ensure_ascii=False, indent=2)
    fd, temp_path = tempfile.mkstemp(
        prefix=".schedule-", suffix=".json.tmp", dir=os.path.dirname(path)
    )
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            f.write(serialized)
            f.flush()
            os.fsync(f.fileno())
        os.replace(temp_path, path)
    finally:
        if os.path.exists(temp_path):
            os.remove(temp_path)


def _validate_date(value: str) -> str:
    try:
        return date_cls.fromisoformat(value).isoformat()
    except (TypeError, ValueError):
        raise ValueError(f"invalid date, expected YYYY-MM-DD: {value!r}")


def _validate_post_time(value: str) -> str:
    if not value:
        return ""
    try:
        datetime.strptime(value, "%H:%M")
    except (TypeError, ValueError):
        raise ValueError(f"invalid post_time, expected HH:MM: {value!r}")
    return value


def _validate_preset(value: str) -> str:
    if value not in PRESETS:
        raise ValueError(
            f"unknown preset: {value!r}, expected one of {sorted(PRESETS)}"
        )
    return value


def list_entries(
    start_date: Optional[str] = None, end_date: Optional[str] = None
) -> list[dict]:
    with _store_lock:
        entries = _load_entries()
    if start_date:
        start_date = _validate_date(start_date)
        entries = [e for e in entries if e.get("date", "") >= start_date]
    if end_date:
        end_date = _validate_date(end_date)
        entries = [e for e in entries if e.get("date", "") <= end_date]
    entries.sort(key=lambda e: (e.get("date", ""), e.get("post_time", "")))
    return entries


def get_entry(entry_id: str) -> Optional[dict]:
    with _store_lock:
        for entry in _load_entries():
            if entry.get("id") == entry_id:
                return entry
    return None


def create_entry(
    date: str,
    topic: str,
    video_count: int = 1,
    preset: str = "shorts",
    post_time: str = "",
    language: str = "",
) -> dict:
    topic = (topic or "").strip()
    if not topic:
        raise ValueError("topic must not be empty")
    if not isinstance(video_count, int) or video_count < 1 or video_count > 20:
        raise ValueError("video_count must be an integer between 1 and 20")

    entry = {
        "id": utils.get_uuid(),
        "date": _validate_date(date),
        "topic": topic,
        "video_count": video_count,
        "preset": _validate_preset(preset),
        "post_time": _validate_post_time(post_time),
        "language": language or "",
        "status": STATUS_PENDING,
        "task_ids": [],
        "youtube_video_ids": [],
        "error": "",
        "created_at": _now_iso(),
        "updated_at": _now_iso(),
    }
    with _store_lock:
        entries = _load_entries()
        entries.append(entry)
        _save_entries(entries)
    logger.info(f"schedule entry created: {entry['id']} {entry['date']} {topic!r}")
    return entry


def update_entry(entry_id: str, **fields) -> dict:
    allowed = {"date", "topic", "video_count", "preset", "post_time", "language",
               "status"}
    unknown = set(fields) - allowed
    if unknown:
        raise ValueError(f"unknown fields: {sorted(unknown)}")

    with _store_lock:
        entries = _load_entries()
        for entry in entries:
            if entry.get("id") != entry_id:
                continue
            if entry.get("status") == STATUS_GENERATING:
                raise ValueError("entry is currently generating and cannot be edited")
            if "date" in fields:
                entry["date"] = _validate_date(fields["date"])
            if "topic" in fields:
                topic = (fields["topic"] or "").strip()
                if not topic:
                    raise ValueError("topic must not be empty")
                entry["topic"] = topic
            if "video_count" in fields:
                count = fields["video_count"]
                if not isinstance(count, int) or count < 1 or count > 20:
                    raise ValueError("video_count must be an integer between 1 and 20")
                entry["video_count"] = count
            if "preset" in fields:
                entry["preset"] = _validate_preset(fields["preset"])
            if "post_time" in fields:
                entry["post_time"] = _validate_post_time(fields["post_time"])
            if "language" in fields:
                entry["language"] = fields["language"] or ""
            if "status" in fields:
                if fields["status"] not in (STATUS_PENDING, STATUS_DONE, STATUS_FAILED):
                    raise ValueError(f"invalid status: {fields['status']!r}")
                entry["status"] = fields["status"]
                entry["error"] = ""
            entry["updated_at"] = _now_iso()
            _save_entries(entries)
            return entry
    raise KeyError(f"schedule entry not found: {entry_id}")


def delete_entry(entry_id: str) -> None:
    with _store_lock:
        entries = _load_entries()
        remaining = [e for e in entries if e.get("id") != entry_id]
        if len(remaining) == len(entries):
            raise KeyError(f"schedule entry not found: {entry_id}")
        for entry in entries:
            if entry.get("id") == entry_id and entry.get("status") == STATUS_GENERATING:
                raise ValueError("entry is currently generating and cannot be deleted")
        _save_entries(remaining)
    logger.info(f"schedule entry deleted: {entry_id}")


def duplicate_entry(entry_id: str, dates: list[str], topic: str = "") -> list[dict]:
    """Copy one entry onto other dates, optionally overriding the topic.

    This is what powers "same preset, different day/topic" in the calendar.
    """
    source = get_entry(entry_id)
    if source is None:
        raise KeyError(f"schedule entry not found: {entry_id}")
    created = []
    for target_date in dates:
        created.append(
            create_entry(
                date=target_date,
                topic=topic or source["topic"],
                video_count=source["video_count"],
                preset=source["preset"],
                post_time=source.get("post_time", ""),
                language=source.get("language", ""),
            )
        )
    return created


def _patch_entry(entry_id: str, **fields) -> None:
    """Internal writer used by the runner; bypasses user-facing validation."""
    with _store_lock:
        entries = _load_entries()
        for entry in entries:
            if entry.get("id") == entry_id:
                entry.update(fields)
                entry["updated_at"] = _now_iso()
                _save_entries(entries)
                return


def _build_video_params(entry: dict) -> VideoParams:
    ui = config.ui
    preset = PRESETS[entry["preset"]]
    return VideoParams(
        video_subject=entry["topic"],
        video_count=entry["video_count"],
        video_aspect=preset["video_aspect"],
        video_source=config.app.get("video_source", "pexels"),
        video_concat_mode=ui.get("video_concat_mode", "random"),
        video_transition_mode=ui.get("video_transition_mode", None),
        video_clip_duration=int(ui.get("video_clip_duration", 3)),
        video_clip_speed=float(ui.get("video_clip_speed", 1.0)),
        video_language=entry.get("language", "") or ui.get("video_language", ""),
        voice_name=ui.get("voice_name", ""),
        voice_volume=float(ui.get("voice_volume", 1.0)),
        voice_rate=float(ui.get("voice_rate", 1.0)),
        bgm_type=ui.get("bgm_type", "random"),
        bgm_volume=float(ui.get("bgm_volume", 0.2)),
        subtitle_enabled=bool(ui.get("subtitle_enabled", True)),
        subtitle_position=ui.get("subtitle_position", "bottom"),
        custom_position=float(ui.get("custom_position", 70.0)),
        font_name=ui.get("font_name", "MicrosoftYaHeiBold.ttc"),
        text_fore_color=ui.get("text_fore_color", "#FFFFFF"),
        text_background_color=ui.get("subtitle_background_enabled", False)
        and ui.get("subtitle_background_color", "#000000"),
        rounded_subtitle_background=bool(
            ui.get("rounded_subtitle_background", False)
        ),
        font_size=int(ui.get("font_size", 60)),
        stroke_color=ui.get("stroke_color", "#000000"),
        stroke_width=float(ui.get("stroke_width", 1.5)),
        paragraph_number=int(ui.get("paragraph_number", 1)),
        video_script_prompt=ui.get("video_script_prompt", ""),
        custom_system_prompt=ui.get("custom_system_prompt", ""),
    )


def _extract_thumbnail(video_path: str, output_path: str) -> Optional[str]:
    """Grab a frame ~1s in as the YouTube thumbnail. Best-effort."""
    ffmpeg_bin = utils.get_ffmpeg_binary()
    try:
        subprocess.run(
            [
                ffmpeg_bin, "-y", "-ss", "1", "-i", video_path,
                "-frames:v", "1", "-q:v", "2", output_path,
            ],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            timeout=60,
            check=True,
        )
        return output_path if os.path.isfile(output_path) else None
    except (subprocess.SubprocessError, OSError) as e:
        logger.warning(f"failed to extract thumbnail: {str(e)}")
        return None


def _compute_publish_at(entry: dict) -> Optional[str]:
    """Build the YouTube ``status.publishAt`` timestamp for an entry.

    YouTube requires ISO 8601 and treats a past timestamp as "publish right
    now", so entries whose planned time has already passed fall back to a
    plain private draft instead of accidentally going public.

    The entry's date + post_time are interpreted in ``youtube.publish_timezone``
    (an IANA name like "Africa/Lagos"); when unset, the server's local
    timezone is used - note that inside Docker that is usually UTC.
    """
    post_time = entry.get("post_time", "")
    if not post_time:
        return None

    try:
        naive = datetime.strptime(f"{entry['date']} {post_time}", "%Y-%m-%d %H:%M")
    except ValueError:
        logger.warning(
            f"invalid date/post_time on entry {entry.get('id')}, "
            "uploading as plain private draft"
        )
        return None

    tz_name = config.youtube.get("publish_timezone", "")
    if tz_name:
        try:
            from zoneinfo import ZoneInfo

            local = naive.replace(tzinfo=ZoneInfo(tz_name))
        except Exception as e:
            logger.warning(
                f"invalid youtube.publish_timezone {tz_name!r} ({e}), "
                "falling back to server local time"
            )
            local = naive.astimezone()
    else:
        local = naive.astimezone()

    publish_utc = local.astimezone(timezone.utc)
    if publish_utc <= datetime.now(timezone.utc):
        logger.warning(
            f"planned publish time {publish_utc.isoformat()} is in the past "
            f"for entry {entry.get('id')}, uploading as plain private draft"
        )
        return None

    return publish_utc.strftime("%Y-%m-%dT%H:%M:%SZ")


def _upload_entry_videos(entry: dict, video_paths: list[str], script: str) -> dict:
    """Upload each generated video and alert Discord.

    With a post_time set, the video is scheduled on YouTube (private +
    publishAt, so YouTube flips it public automatically at that moment);
    without one it stays a private draft for manual publishing.
    """
    from app.services import discord_notify, llm, youtube_upload

    uploaded_ids = []
    errors = []
    language = entry.get("language", "") or config.ui.get("video_language", "")
    publish_at = _compute_publish_at(entry)

    for index, video_path in enumerate(video_paths, start=1):
        metadata = llm.generate_social_metadata(
            video_subject=entry["topic"],
            video_script=script,
            language=language,
            platform="youtube_shorts",
        )
        title = metadata.get("title") or entry["topic"]
        if len(video_paths) > 1:
            title = f"{title} ({index}/{len(video_paths)})"
        hashtags = metadata.get("hashtags", [])
        description = metadata.get("caption", "")
        if hashtags:
            description = f"{description}\n\n{' '.join(hashtags)}".strip()

        thumbnail_path = _extract_thumbnail(
            video_path, os.path.splitext(video_path)[0] + "-thumbnail.jpg"
        )

        result = youtube_upload.youtube_upload_service.upload_video(
            video_path=video_path,
            title=title,
            description=description,
            tags=hashtags,
            thumbnail_path=thumbnail_path,
            publish_at=publish_at,
        )
        if result.get("success"):
            video_id = result["video_id"]
            uploaded_ids.append(video_id)
            discord_notify.discord_notify_service.notify_video_ready(
                title=title,
                youtube_video_id=video_id,
                scheduled_date=entry["date"],
                topic=entry["topic"],
                post_time=entry.get("post_time", ""),
                publish_at=publish_at,
            )
        else:
            errors.append(result.get("error", "unknown upload error"))

    return {"video_ids": uploaded_ids, "errors": errors}


def _run_entry(entry: dict) -> None:
    from app.services import discord_notify
    from app.services import state as sm
    from app.services import task as tm

    entry_id = entry["id"]
    task_id = utils.get_uuid()
    logger.info(
        f"running schedule entry {entry_id}: date={entry['date']}, "
        f"topic={entry['topic']!r}, count={entry['video_count']}, "
        f"preset={entry['preset']}, task_id={task_id}"
    )
    _patch_entry(
        entry_id, status=STATUS_GENERATING, task_ids=[task_id], error=""
    )

    try:
        params = _build_video_params(entry)
        sm.state.update_task(task_id)
        result = tm.start(task_id=task_id, params=params, stop_at="video")
    except Exception as e:
        logger.exception(f"schedule entry {entry_id} crashed: {str(e)}")
        _patch_entry(entry_id, status=STATUS_FAILED, error=str(e))
        discord_notify.discord_notify_service.notify_failure(
            entry["date"], entry["topic"], str(e)
        )
        return

    videos = (result or {}).get("videos") or []
    if not videos:
        error = (result or {}).get("error", "video generation failed")
        _patch_entry(entry_id, status=STATUS_FAILED, error=str(error))
        discord_notify.discord_notify_service.notify_failure(
            entry["date"], entry["topic"], str(error)
        )
        return

    script = (result or {}).get("script", "")
    upload_result = _upload_entry_videos(entry, videos, script)
    video_ids = upload_result["video_ids"]
    errors = upload_result["errors"]

    if video_ids and not errors:
        _patch_entry(
            entry_id, status=STATUS_DONE, youtube_video_ids=video_ids, error=""
        )
    else:
        error = "; ".join(errors) if errors else "no videos were uploaded"
        _patch_entry(
            entry_id,
            status=STATUS_FAILED,
            youtube_video_ids=video_ids,
            error=error,
        )
        discord_notify.discord_notify_service.notify_failure(
            entry["date"], entry["topic"], error
        )


def run_due_entries(run_date: Optional[str] = None) -> dict:
    """Generate and upload every pending entry due on or before ``run_date``.

    Due entries from earlier dates are included so a missed cron day is
    caught up on the next run instead of silently skipped. Runs are
    serialized: a second overlapping call returns immediately.
    """
    run_date = _validate_date(run_date) if run_date else date_cls.today().isoformat()

    if not _run_lock.acquire(blocking=False):
        logger.warning("a schedule run is already in progress, skipping")
        return {"ran": 0, "skipped_reason": "already running"}

    try:
        due = [
            e
            for e in list_entries(end_date=run_date)
            if e.get("status") == STATUS_PENDING
        ]
        logger.info(f"schedule run for {run_date}: {len(due)} due entries")
        for entry in due:
            _run_entry(entry)
        return {"ran": len(due), "date": run_date}
    finally:
        _run_lock.release()


if __name__ == "__main__":
    # Offline runner for host cron jobs that prefer not to hit the HTTP API:
    #   cd /path/to/MoneyPrinterTurbo && .venv/bin/python -m app.services.schedule
    print(json.dumps(run_due_entries(), ensure_ascii=False))
