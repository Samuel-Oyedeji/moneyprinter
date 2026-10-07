"""One analytics sync: channel → reconcile → posted marks → metrics → topics.

Runs from the Analytics page's Sync button, ``POST /api/v1/analytics/sync``,
``python -m app.services.analytics.sync``, and (best-effort) at the start of
every cron run, so a video posted by hand is marked posted before the
calendar can upload a second copy of it.

Metrics are fetched incrementally (only days not stored yet) and every
video the app made is remembered in items.csv, so videos swept from disk
still reconcile and still count.

Reconciliation writes back to the studios: an animation or documentary
found on the channel under its title gets the same "posted by hand" mark
the owner can set on its library card, which takes its pending calendar
entries off the upload budget.
"""

import json
import threading
import time
from datetime import date as date_cls
from datetime import datetime, timedelta

from loguru import logger

from app.services.analytics import catalog, reconcile, store, topics, youtube_api

_sync_lock = threading.Lock()

# Methods that mean "the owner posted this by hand" (not an app upload).
_MANUAL_METHODS = ("title", "manual")


def _publish_date(video: dict) -> str:
    value = video.get("published_at") or ""
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00")).date().isoformat()
    except ValueError:
        return date_cls.today().isoformat()


def apply_posted_marks(items: list[dict], result: dict, videos: list[dict]) -> list[str]:
    """Mark items the owner posted by hand as posted in their studio.

    Only items the app never uploaded and that are not marked yet; returns
    the keys that were marked.
    """
    from app.services.animation import schedule as anim_schedule
    from app.services.animation import store as anim_store
    from app.services.documentary import doc_schedule
    from app.services.documentary import store as doc_store

    by_key = {i["key"]: i for i in items}
    by_video = {v["video_id"]: v for v in videos}
    marked = []
    for key, matches in result["links"].items():
        item = by_key.get(key)
        if not item or item.get("known_video_ids") or (item.get("posted") or {}).get("manual"):
            continue
        match = next((m for m in matches if m["method"] in _MANUAL_METHODS), None)
        if not match:
            continue
        video = by_video.get(match["video_id"], {})
        url, posted_on = f"https://youtu.be/{match['video_id']}", _publish_date(video)
        try:
            # The studio holds the mark (and frees calendar slots) while the
            # project is still on disk; swept ones keep it in posted_marks.csv.
            if item["studio"] == "animation" and item.get("on_disk") and anim_store.load_project(item["project_id"]):
                anim_schedule.mark_posted(item["project_id"], url=url, posted_on=posted_on)
            elif item["studio"] == "documentary" and item.get("on_disk") and doc_store.load_project(item["project_id"]):
                doc_schedule.mark_posted(item["project_id"], url=url, posted_on=posted_on)
            else:
                store.mark_posted(key, url=url, posted_on=posted_on)
        except Exception:
            logger.exception(f"analytics: could not mark {key} as posted")
            continue
        item["posted"] = {"manual": True, "url": url, "date": posted_on}
        marked.append(key)
    if marked:
        logger.info(f"analytics: marked {len(marked)} hand-posted video(s) as posted")
    return marked


# The Analytics API keeps revising the last couple of days; only days at
# least this old are fetched, so a stored day never changes afterwards.
SETTLE_DAYS = 3


def fetch_new_metrics(videos: list[dict], today: date_cls | None = None) -> dict:
    """Fetch Analytics metrics only for the days not stored yet.

    The first sync backfills from the oldest upload; after that each sync
    asks for the few settled days since the previous one (one request per
    200 videos), appends them to analytics.csv and compacts old rows.
    """
    today = today or date_cls.today()
    end = (today - timedelta(days=SETTLE_DAYS)).isoformat()
    through = store.metrics_through()
    start = (date_cls.fromisoformat(through) + timedelta(days=1)).isoformat() if through else min(_publish_date(v) for v in videos)
    if start > end:
        return {"metrics_range": "", "metrics_rows": 0}
    # a video published after the range cannot have data in it
    ids = [v["video_id"] for v in videos if _publish_date(v) <= end]
    metrics = youtube_api.fetch_video_metrics(ids, start_date=start, end_date=end) if ids else {}
    added = store.add_metric_period(start, end, metrics)
    store.compact_metric_periods(today.isoformat())
    return {"metrics_range": f"{start} → {end}", "metrics_rows": added}


def reconcile_now(videos: list[dict] | None = None) -> dict:
    """Reconcile against the stored (or given) channel list and apply marks."""
    videos = store.channel_videos() if videos is None else videos
    items = catalog.build_items()
    result = reconcile.reconcile(items, videos, store.load_links())
    result["marked_posted"] = apply_posted_marks(items, result, videos)
    if result["marked_posted"]:
        # record the new marks in items.csv now, before a sweep can take
        # the project folders that hold them
        catalog.build_items(persist=True)
    return result


def run(fetch_metrics: bool = True, categorize_topics: bool = True) -> dict:
    """A full sync. Never runs twice at once; never raises."""
    if not _sync_lock.acquire(blocking=False):
        return {"ok": False, "skipped": True, "error": "a sync is already running"}
    started = time.time()
    status = {"started_at": started, "ok": False, "error": ""}
    try:
        channel = youtube_api.list_channel_videos()
        videos = channel["videos"]
        store.save_channel(channel["channel"], videos)
        status["snapshots"] = store.record_snapshots(videos, date_cls.today().isoformat())

        result = reconcile_now(videos)
        status.update(
            videos=len(videos),
            linked=len(result["video_to_item"]),
            suggestions=len(result["suggestions"]),
            marked_posted=len(result["marked_posted"]),
        )

        if fetch_metrics and videos:
            try:
                status.update(fetch_new_metrics(videos))
            except youtube_api.AnalyticsAuthError:
                raise
            except Exception as exc:
                # The Data API numbers above still make the page useful.
                logger.exception("analytics: metrics fetch failed")
                status["metrics_error"] = f"{type(exc).__name__}: {exc}"

        if categorize_topics:
            linked_topics = [i["topic"] for i in catalog.build_items() if i["key"] in result["links"]]
            try:
                status["categorized"] = len(topics.categorize(linked_topics))
            except Exception as exc:
                logger.warning(f"analytics: topic categorization skipped: {exc}")

        status["ok"] = True
    except youtube_api.AnalyticsAuthError as exc:
        status["error"] = str(exc)
        logger.warning(f"analytics sync: {exc}")
    except Exception as exc:
        status["error"] = f"{type(exc).__name__}: {exc}"
        logger.exception("analytics sync failed")
    finally:
        status["finished_at"] = time.time()
        store.save_sync_status(status)
        _sync_lock.release()
    return status


def run_before_uploads(timeout: float = 120.0) -> None:
    """Best-effort reconcile at the start of a cron run, bounded in time.

    Skipped silently when the token has no read access. A slow or failing
    YouTube never holds the uploads back for longer than ``timeout``.
    """
    from app.config import config

    # Remember every video made so far before anything can sweep its
    # files; this needs no YouTube access at all.
    try:
        catalog.build_items(persist=True)
    except Exception:
        logger.exception("analytics: could not refresh items.csv")
    if not config.youtube.get("analytics_sync_before_uploads", True):
        return
    if not youtube_api.readiness()[0]:
        return
    worker = threading.Thread(target=run, kwargs={"fetch_metrics": True}, daemon=True, name="analytics-sync")
    worker.start()
    worker.join(timeout)
    if worker.is_alive():
        logger.warning(f"analytics sync still running after {timeout:.0f}s; starting uploads anyway")


if __name__ == "__main__":
    # .venv/bin/python -m app.services.analytics.sync
    print(json.dumps(run(), ensure_ascii=False, default=str))
