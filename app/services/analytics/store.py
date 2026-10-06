"""File-backed state for the Analytics page, under storage/analytics/.

    channel.json   the channel's videos as of the last sync (Data API)
    metrics.json   per-video Analytics API metrics as of the last sync
    history.json   one lifetime-views snapshot per video per day, so growth
                   can be compared fairly between old and new videos
    links.json     what the owner decided by hand:
                     links       item key → video id ("this is that video")
                     rejected    item key → [video ids] ("not a match")
                     posted      item key → {url, date} for Shorts marked as
                                 posted (animations and documentaries keep
                                 that mark on their own project)
                     categories  topic → category (LLM-assigned or edited)
    sync.json      when the last sync ran and how it went
"""

import json
import os
import threading
import time

from app.utils import utils

_lock = threading.RLock()


def analytics_dir() -> str:
    return utils.storage_dir("analytics", create=True)


def _path(name: str) -> str:
    return os.path.join(analytics_dir(), f"{name}.json")


def _read(name: str, default):
    try:
        with open(_path(name), "r", encoding="utf-8") as f:
            data = json.load(f)
        return data if isinstance(data, type(default)) else default
    except (OSError, json.JSONDecodeError):
        return default


def _write(name: str, data) -> None:
    with _lock:
        path = _path(name)
        tmp = f"{path}.tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
        os.replace(tmp, path)


# ---------------------------------------------------------------- YouTube data
def load_channel() -> dict:
    return _read("channel", {})


def save_channel(channel: dict, videos: list[dict]) -> None:
    _write("channel", {"synced_at": time.time(), "channel": channel, "videos": videos})


def channel_videos() -> list[dict]:
    return load_channel().get("videos") or []


def load_metrics() -> dict:
    return _read("metrics", {}).get("videos") or {}


def save_metrics(metrics: dict) -> None:
    _write("metrics", {"synced_at": time.time(), "videos": metrics})


def record_snapshots(videos: list[dict], day: str) -> None:
    """Keep one lifetime-counts snapshot per video per day (the latest wins)."""
    with _lock:
        history = _read("history", {})
        for video in videos:
            rows = history.setdefault(video["video_id"], [])
            row = {"date": day, "views": video.get("views", 0), "likes": video.get("likes", 0), "comments": video.get("comments", 0)}
            if rows and rows[-1].get("date") == day:
                rows[-1] = row
            else:
                rows.append(row)
        _write("history", history)


def load_history() -> dict:
    return _read("history", {})


def load_sync_status() -> dict:
    return _read("sync", {})


def save_sync_status(status: dict) -> None:
    _write("sync", status)


# ------------------------------------------------------------ owner decisions
def load_links() -> dict:
    links = _read("links", {})
    for key in ("links", "rejected", "posted", "categories"):
        links.setdefault(key, {})
    return links


def _update_links(mutate) -> dict:
    with _lock:
        links = load_links()
        mutate(links)
        _write("links", links)
        return links


def link(item_key: str, video_id: str) -> None:
    """The owner says this app video is that YouTube video."""

    def mutate(links):
        # a video belongs to one item: drop any other manual link to it
        for key in [k for k, v in links["links"].items() if v == video_id]:
            links["links"].pop(key)
        links["links"][item_key] = video_id
        rejected = links["rejected"].get(item_key) or []
        if video_id in rejected:
            rejected.remove(video_id)

    _update_links(mutate)


def reject(item_key: str, video_id: str) -> None:
    """The owner says this pairing is wrong; never auto-match it again."""

    def mutate(links):
        if links["links"].get(item_key) == video_id:
            links["links"].pop(item_key)
        rejected = links["rejected"].setdefault(item_key, [])
        if video_id not in rejected:
            rejected.append(video_id)

    _update_links(mutate)


def mark_short_posted(item_key: str, url: str = "", posted_on: str = "") -> None:
    def mutate(links):
        links["posted"][item_key] = {"manual": True, "url": (url or "").strip(), "date": posted_on or time.strftime("%Y-%m-%d"), "at": time.time()}

    _update_links(mutate)


def unmark_short_posted(item_key: str) -> None:
    _update_links(lambda links: links["posted"].pop(item_key, None))


def set_categories(mapping: dict) -> None:
    def mutate(links):
        for topic, category in mapping.items():
            category = (category or "").strip()
            if category:
                links["categories"][topic] = category
            else:
                links["categories"].pop(topic, None)

    _update_links(mutate)
