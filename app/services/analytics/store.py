"""File-backed state for the Analytics page: CSV files under storage/analytics/.

Everything is plain CSV (UTF-8 with a BOM, so Excel opens it cleanly):

    items.csv             every video the app ever made: studio, topic, the
                          titles it could be posted under, batch, YouTube ids,
                          posted mark and style features. Rendered files get
                          swept from disk after a few days; this row stays, so
                          a swept video is still reconciled and analysed.
    channel_videos.csv    the channel's videos as of the last sync (Data API:
                          title, publish time, privacy, live view counts)
    daily_stats.csv       one row per video per day with its live view / like
                          / comment counts, kept for the first 30 days after
                          publishing (enough for "views after 7 days")
    analytics.csv         Analytics API metrics per video per fetched date
                          range. Each sync only asks for the days since the
                          last one; rows older than 35 days are compacted into
                          one row per video, so the file stays small
    matches.csv           your Reconcile-tab decisions: item key, video id,
                          "link" or "reject"
    posted_marks.csv      videos marked "already posted" that have no studio
                          project to hold the mark (Shorts, swept projects)
    topic_categories.csv  topic → category (LLM-assigned or edited)

plus two tiny JSON files: channel.json (channel id / title) and sync.json
(how the last sync went).
"""

import csv
import json
import os
import threading
import time
from datetime import date as date_cls
from datetime import timedelta

from app.utils import utils

_lock = threading.RLock()

# Analytics API metrics that add up across date ranges.
ADDITIVE_METRICS = ("views", "estimatedMinutesWatched", "likes", "comments", "shares", "subscribersGained")
ANALYTICS_COLUMNS = ("start_date", "end_date", "video_id", *ADDITIVE_METRICS, "averageViewPercentage")
CHANNEL_COLUMNS = (
    "video_id", "title", "published_at", "privacy_status", "publish_at",
    "duration_seconds", "views", "likes", "comments", "thumbnail",
)
_CHANNEL_INTS = ("duration_seconds", "views", "likes", "comments")
SNAPSHOT_COLUMNS = ("date", "video_id", "views", "likes", "comments")
SNAPSHOT_MAX_AGE_DAYS = 30
COMPACT_AFTER_DAYS = 35


def analytics_dir() -> str:
    return utils.storage_dir("analytics", create=True)


def _path(name: str) -> str:
    return os.path.join(analytics_dir(), name)


def read_csv(name: str) -> list[dict]:
    try:
        with open(_path(name), "r", encoding="utf-8-sig", newline="") as f:
            return list(csv.DictReader(f))
    except OSError:
        return []


def write_csv(name: str, rows: list[dict], columns) -> None:
    """Atomic rewrite; columns not listed are dropped, missing ones left blank."""
    with _lock:
        path = _path(name)
        tmp = f"{path}.tmp"
        with open(tmp, "w", encoding="utf-8-sig", newline="") as f:
            writer = csv.DictWriter(f, fieldnames=list(columns), extrasaction="ignore")
            writer.writeheader()
            writer.writerows(rows)
        os.replace(tmp, path)


def _read_json(name: str) -> dict:
    try:
        with open(_path(name), "r", encoding="utf-8") as f:
            data = json.load(f)
        return data if isinstance(data, dict) else {}
    except (OSError, json.JSONDecodeError):
        return {}


def _write_json(name: str, data: dict) -> None:
    with _lock:
        path = _path(name)
        with open(f"{path}.tmp", "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
        os.replace(f"{path}.tmp", path)


def _int(value) -> int:
    try:
        return int(float(value or 0))
    except (TypeError, ValueError):
        return 0


def _float(value):
    try:
        return float(value) if value not in (None, "") else None
    except (TypeError, ValueError):
        return None


# ------------------------------------------------------------- channel videos
def save_channel(channel: dict, videos: list[dict]) -> None:
    write_csv("channel_videos.csv", videos, CHANNEL_COLUMNS)
    _write_json("channel.json", {"channel": channel, "synced_at": time.time()})


def load_channel_info() -> dict:
    return _read_json("channel.json").get("channel") or {}


def channel_videos() -> list[dict]:
    videos = read_csv("channel_videos.csv")
    for video in videos:
        for key in _CHANNEL_INTS:
            video[key] = _int(video.get(key))
    return videos


# ------------------------------------------------------ daily live snapshots
def record_snapshots(videos: list[dict], day: str, max_age_days: int = SNAPSHOT_MAX_AGE_DAYS) -> int:
    """Store today's live counts for videos published in the last ``max_age_days``.

    Older videos only need their latest counts (channel_videos.csv), so they
    are not snapshotted. One row per video per day: a second sync the same
    day replaces it. Returns how many rows were written for ``day``.
    """
    cutoff = (date_cls.fromisoformat(day) - timedelta(days=max_age_days)).isoformat()
    fresh = {
        v["video_id"]: {"date": day, "video_id": v["video_id"], "views": v.get("views", 0), "likes": v.get("likes", 0), "comments": v.get("comments", 0)}
        for v in videos
        if (v.get("published_at") or "")[:10] >= cutoff
    }
    with _lock:
        rows = [r for r in read_csv("daily_stats.csv") if not (r["date"] == day and r["video_id"] in fresh)]
        rows.extend(fresh.values())
        rows.sort(key=lambda r: (r["video_id"], r["date"]))
        write_csv("daily_stats.csv", rows, SNAPSHOT_COLUMNS)
    return len(fresh)


def load_snapshots() -> dict:
    """{video_id: [{"date", "views", "likes", "comments"}]} oldest first."""
    history: dict[str, list] = {}
    for row in read_csv("daily_stats.csv"):
        history.setdefault(row["video_id"], []).append(
            {"date": row["date"], "views": _int(row["views"]), "likes": _int(row["likes"]), "comments": _int(row["comments"])}
        )
    for rows in history.values():
        rows.sort(key=lambda r: r["date"])
    return history


# ------------------------------------------------------- Analytics API metrics
def metrics_through() -> str:
    """The last day already fetched from the Analytics API ("" = none yet)."""
    return max((r["end_date"] for r in read_csv("analytics.csv")), default="")


def add_metric_period(start_date: str, end_date: str, metrics: dict) -> int:
    """Append one fetched date range: {video_id: {metric: value}}."""
    if not metrics:
        return 0
    new = [{"start_date": start_date, "end_date": end_date, "video_id": vid, **{k: m.get(k, 0) for k in ANALYTICS_COLUMNS[3:]}} for vid, m in metrics.items()]
    with _lock:
        rows = read_csv("analytics.csv") + new
        write_csv("analytics.csv", rows, ANALYTICS_COLUMNS)
    return len(new)


def _merge(rows: list[dict]) -> dict:
    """Sum additive metrics; % viewed is averaged weighted by views."""
    total = {k: sum(_float(r.get(k)) or 0 for r in rows) for k in ADDITIVE_METRICS}
    weighted = [(_float(r.get("averageViewPercentage")), _float(r.get("views")) or 0) for r in rows]
    weighted = [(pct, views) for pct, views in weighted if pct is not None]
    weight = sum(views for _, views in weighted)
    if weight:
        total["averageViewPercentage"] = sum(pct * views for pct, views in weighted) / weight
    elif weighted:
        total["averageViewPercentage"] = sum(pct for pct, _ in weighted) / len(weighted)
    else:
        total["averageViewPercentage"] = None
    return total


def load_metric_totals() -> dict:
    """Lifetime Analytics metrics per video, summed over every stored range."""
    by_video: dict[str, list] = {}
    for row in read_csv("analytics.csv"):
        by_video.setdefault(row["video_id"], []).append(row)
    totals = {}
    for video_id, rows in by_video.items():
        total = _merge(rows)
        total["averageViewDuration"] = total["estimatedMinutesWatched"] * 60 / total["views"] if total["views"] else 0.0
        totals[video_id] = total
    return totals


def compact_metric_periods(today: str, keep_days: int = COMPACT_AFTER_DAYS) -> int:
    """Fold each video's ranges that ended over ``keep_days`` ago into one row.

    Recent ranges stay as fetched (day by day when syncing daily); older ones
    only matter as a total. Returns how many rows were removed.
    """
    cutoff = (date_cls.fromisoformat(today) - timedelta(days=keep_days)).isoformat()
    with _lock:
        rows = read_csv("analytics.csv")
        old: dict[str, list] = {}
        recent = []
        for row in rows:
            (old.setdefault(row["video_id"], []) if row["end_date"] < cutoff else recent).append(row)
        if all(len(group) < 2 for group in old.values()):
            return 0
        compacted = []
        for video_id, group in old.items():
            merged = _merge(group)
            compacted.append(
                {
                    "start_date": min(r["start_date"] for r in group),
                    "end_date": max(r["end_date"] for r in group),
                    "video_id": video_id,
                    **{k: round(v, 3) if isinstance(v, float) else v for k, v in merged.items() if v is not None},
                }
            )
        result = sorted(compacted + recent, key=lambda r: (r["video_id"], r["start_date"]))
        write_csv("analytics.csv", result, ANALYTICS_COLUMNS)
        return len(rows) - len(result)


# ------------------------------------------------------------ sync status
def load_sync_status() -> dict:
    return _read_json("sync.json")


def save_sync_status(status: dict) -> None:
    _write_json("sync.json", status)


# ----------------------------------------------------------- item registry
ITEM_COLUMNS = (
    "key", "studio", "topic", "label", "titles", "created_at", "batch_id", "batch_inferred",
    "known_video_ids", "posted_url", "posted_date", "project_id", "task_id", "entry_id",
    "first_seen", "last_seen",
)
_TITLE_SEPARATOR = " || "


def load_registry() -> dict:
    """{key: item} as last saved; feature columns come back as ``features``."""
    items = {}
    for row in read_csv("items.csv"):
        if not row.get("key"):
            continue
        posted = {"manual": True, "url": row.get("posted_url", ""), "date": row["posted_date"]} if row.get("posted_date") else {}
        items[row["key"]] = {
            "key": row["key"],
            "studio": row.get("studio", ""),
            "topic": row.get("topic", ""),
            "label": row.get("label", ""),
            "titles": [t for t in (row.get("titles") or "").split(_TITLE_SEPARATOR) if t],
            "created_at": _float(row.get("created_at")) or 0.0,
            "batch_id": row.get("batch_id", ""),
            "batch_inferred": row.get("batch_inferred") == "1",
            "known_video_ids": (row.get("known_video_ids") or "").split(),
            "posted": posted,
            "project_id": row.get("project_id", ""),
            "task_id": row.get("task_id", ""),
            "entry_id": row.get("entry_id", ""),
            "first_seen": row.get("first_seen", ""),
            "last_seen": row.get("last_seen", ""),
            "features": {k: v for k, v in row.items() if k not in ITEM_COLUMNS and k and v},
        }
    return items


def save_registry(items: list[dict]) -> None:
    feature_names = sorted({name for item in items for name in (item.get("features") or {})})
    rows = []
    for item in sorted(items, key=lambda i: (i["studio"], i.get("created_at") or 0)):
        posted = item.get("posted") or {}
        rows.append(
            {
                "key": item["key"],
                "studio": item["studio"],
                "topic": item.get("topic", ""),
                "label": item.get("label", ""),
                "titles": _TITLE_SEPARATOR.join(item.get("titles") or []),
                "created_at": round(float(item.get("created_at") or 0), 3),
                "batch_id": item.get("batch_id", ""),
                "batch_inferred": "1" if item.get("batch_inferred") else "",
                "known_video_ids": " ".join(item.get("known_video_ids") or []),
                "posted_url": posted.get("url", "") if posted.get("manual") else "",
                "posted_date": (posted.get("date") or "?") if posted.get("manual") else "",
                "project_id": item.get("project_id", ""),
                "task_id": item.get("task_id", ""),
                "entry_id": item.get("entry_id", ""),
                "first_seen": item.get("first_seen", ""),
                "last_seen": item.get("last_seen", ""),
                **(item.get("features") or {}),
            }
        )
    write_csv("items.csv", rows, [*ITEM_COLUMNS, *feature_names])


# ------------------------------------------------------------ owner decisions
def load_links() -> dict:
    """{"links": {key: video}, "rejected": {key: [videos]}, "posted": {key: mark}, "categories": {topic: category}}."""
    links: dict = {"links": {}, "rejected": {}, "posted": {}, "categories": {}}
    for row in read_csv("matches.csv"):
        if row.get("decision") == "link":
            links["links"][row["item_key"]] = row["video_id"]
        elif row.get("decision") == "reject":
            links["rejected"].setdefault(row["item_key"], []).append(row["video_id"])
    for row in read_csv("posted_marks.csv"):
        links["posted"][row["item_key"]] = {"manual": True, "url": row.get("url", ""), "date": row.get("date", "")}
    for row in read_csv("topic_categories.csv"):
        if row.get("category"):
            links["categories"][row["topic"]] = row["category"]
    return links


def _save_matches(links: dict) -> None:
    rows = [{"item_key": k, "video_id": v, "decision": "link"} for k, v in links["links"].items()]
    rows += [{"item_key": k, "video_id": v, "decision": "reject"} for k, videos in links["rejected"].items() for v in videos]
    write_csv("matches.csv", rows, ("item_key", "video_id", "decision"))


def link(item_key: str, video_id: str) -> None:
    """The owner says this app video is that YouTube video."""
    with _lock:
        links = load_links()
        # a video belongs to one item: drop any other manual link to it
        links["links"] = {k: v for k, v in links["links"].items() if v != video_id}
        links["links"][item_key] = video_id
        if video_id in links["rejected"].get(item_key, []):
            links["rejected"][item_key].remove(video_id)
        _save_matches(links)


def reject(item_key: str, video_id: str) -> None:
    """The owner says this pairing is wrong; never auto-match it again."""
    with _lock:
        links = load_links()
        if links["links"].get(item_key) == video_id:
            links["links"].pop(item_key)
        rejected = links["rejected"].setdefault(item_key, [])
        if video_id not in rejected:
            rejected.append(video_id)
        _save_matches(links)


def mark_posted(item_key: str, url: str = "", posted_on: str = "") -> None:
    with _lock:
        marks = {r["item_key"]: r for r in read_csv("posted_marks.csv")}
        marks[item_key] = {"item_key": item_key, "url": (url or "").strip(), "date": posted_on or time.strftime("%Y-%m-%d")}
        write_csv("posted_marks.csv", list(marks.values()), ("item_key", "url", "date"))


def unmark_posted(item_key: str) -> None:
    with _lock:
        rows = [r for r in read_csv("posted_marks.csv") if r["item_key"] != item_key]
        write_csv("posted_marks.csv", rows, ("item_key", "url", "date"))


def set_categories(mapping: dict) -> None:
    with _lock:
        categories = load_links()["categories"]
        for topic, category in mapping.items():
            category = (category or "").strip()
            if category:
                categories[topic] = category
            else:
                categories.pop(topic, None)
        rows = [{"topic": t, "category": c} for t, c in sorted(categories.items())]
        write_csv("topic_categories.csv", rows, ("topic", "category"))
