"""Turn items + channel videos + metrics into tables the dashboard can slice.

``build_dataset`` gives one row per channel video, enriched with the app
item it was reconciled to: studio, topic and category, batch, and that
studio's style features. ``summarize`` / ``batch_summary`` / ``insights``
are pure functions over that table.

Raw view counts favour old videos, so the dashboard can hide very young
ones and also compares on views per day and average % viewed, which do not
grow with age.
"""

from datetime import datetime, timezone

import pandas as pd

from app.services.analytics import catalog, reconcile, store, topics

OTHER_STUDIO = "other"
STUDIO_LABELS = {**catalog.STUDIO_LABELS, OTHER_STUDIO: "Not from the app"}

# Columns every row has; anything else is a studio-specific feature.
BASE_COLUMNS = (
    "video_id", "url", "title", "studio", "studio_label", "topic", "category", "item_key",
    "batch_id", "batch_inferred", "batch_size", "generation", "posted_via", "match",
    "created_at", "published_at", "weekday", "publish_hour", "privacy", "live", "duration_seconds",
    "length", "age_days", "views", "likes", "comments", "shares", "watch_minutes",
    "avg_view_seconds", "avg_view_pct", "subs_gained", "views_per_day", "engagement_per_1k",
)

# What the dashboard can rank groups by: column → (label, aggregation).
METRICS = {
    "views": ("Median views", "median"),
    "views_per_day": ("Median views per day", "median"),
    "avg_view_pct": ("Average % viewed", "mean"),
    "engagement_per_1k": ("Likes + comments + shares per 1k views", "mean"),
    "subs_gained": ("Subscribers gained per video", "mean"),
    "watch_minutes": ("Median watch minutes", "median"),
}

# Dimensions shared by every studio; features add their own on top.
COMMON_DIMENSIONS = ("category", "generation", "posted_via", "length", "weekday", "publish_hour")
DIMENSION_LABELS = {
    "studio_label": "Studio",
    "category": "Topic category",
    "generation": "Batch or single",
    "posted_via": "How it was posted",
    "length": "Length on YouTube",
    "weekday": "Publish day",
    "publish_hour": "Publish hour",
}
_WEEKDAYS = ("Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun")


def _local_tz():
    from app.config import config

    name = config.youtube.get("publish_timezone", "")
    if name:
        try:
            from zoneinfo import ZoneInfo

            return ZoneInfo(name)
        except Exception:
            pass
    return datetime.now().astimezone().tzinfo


def _parse_time(value: str):
    try:
        return datetime.fromisoformat((value or "").replace("Z", "+00:00"))
    except ValueError:
        return None


def build_dataset(
    items: list[dict] | None = None,
    videos: list[dict] | None = None,
    metrics: dict | None = None,
    decisions: dict | None = None,
    now: datetime | None = None,
) -> pd.DataFrame:
    items = catalog.build_items() if items is None else items
    videos = store.channel_videos() if videos is None else videos
    metrics = store.load_metrics() if metrics is None else metrics
    decisions = store.load_links() if decisions is None else decisions
    now = now or datetime.now(timezone.utc)
    tz = _local_tz()
    categories = decisions.get("categories") or {}

    result = reconcile.reconcile(items, videos, decisions)
    by_key = {i["key"]: i for i in items}
    methods = {m["video_id"]: m["method"] for matches in result["links"].values() for m in matches}

    rows = []
    for video in videos:
        video_id = video["video_id"]
        item = by_key.get(result["video_to_item"].get(video_id, ""), {})
        m = metrics.get(video_id) or {}
        published = _parse_time(video.get("published_at", ""))
        local = published.astimezone(tz) if published else None
        age_days = max((now - published).total_seconds() / 86400, 0.0) if published else 0.0
        # The Data API count is real time; Analytics trails by ~2 days.
        views = max(int(video.get("views") or 0), int(m.get("views") or 0))
        likes = max(int(video.get("likes") or 0), int(m.get("likes") or 0))
        comments = max(int(video.get("comments") or 0), int(m.get("comments") or 0))
        shares = int(m.get("shares") or 0)
        studio = item.get("studio", OTHER_STUDIO)
        method = methods.get(video_id, "")
        topic = item.get("topic") or ""
        row = {
            "video_id": video_id,
            "url": f"https://youtu.be/{video_id}",
            "title": video.get("title", ""),
            "studio": studio,
            "studio_label": STUDIO_LABELS.get(studio, studio),
            "topic": topic,
            "category": categories.get(topic, topics.UNCATEGORIZED) if item else "",
            "item_key": item.get("key", ""),
            "batch_id": item.get("batch_id", ""),
            "batch_inferred": bool(item.get("batch_inferred")),
            "batch_size": int(item.get("batch_size") or 1),
            "generation": ("Batch" if item.get("batch_id") else "Single") if item else "",
            "posted_via": ("App upload" if method == "app upload" else "Posted by hand") if item else "",
            "match": method,
            "created_at": datetime.fromtimestamp(item["created_at"], timezone.utc) if item.get("created_at") else None,
            "published_at": published,
            "weekday": _WEEKDAYS[local.weekday()] if local else "",
            "publish_hour": f"{local.hour:02d}:00" if local else "",
            "privacy": video.get("privacy_status", ""),
            "live": video.get("privacy_status") in ("public", "unlisted"),
            "duration_seconds": int(video.get("duration_seconds") or 0),
            "length": catalog.length_bucket(video.get("duration_seconds") or 0),
            "age_days": round(age_days, 1),
            "views": views,
            "likes": likes,
            "comments": comments,
            "shares": shares,
            "watch_minutes": float(m.get("estimatedMinutesWatched") or 0),
            "avg_view_seconds": float(m.get("averageViewDuration") or 0),
            "avg_view_pct": float(m["averageViewPercentage"]) if m.get("averageViewPercentage") is not None else float("nan"),
            "subs_gained": int(m.get("subscribersGained") or 0),
            "views_per_day": round(views / max(age_days, 1.0), 2),
            "engagement_per_1k": round((likes + comments + shares) / views * 1000, 2) if views else 0.0,
        }
        row.update(item.get("features") or {})
        rows.append(row)
    frame = pd.DataFrame(rows)
    if frame.empty:
        return pd.DataFrame(columns=list(BASE_COLUMNS))
    return frame


def feature_dimensions(df: pd.DataFrame, studio: str | None = None) -> list[str]:
    """Columns worth grouping by: common ones plus the studio's features."""
    if df.empty:
        return list(COMMON_DIMENSIONS)
    subset = df if not studio else df[df["studio"] == studio]
    extra = [c for c in df.columns if c not in BASE_COLUMNS and subset[c].notna().any()]
    if not studio:
        extra = ["studio_label", *extra]
    return [*COMMON_DIMENSIONS, *extra]


def summarize(df: pd.DataFrame, by: str) -> pd.DataFrame:
    """One row per group with the metrics the dashboard shows."""
    columns = ["Videos", "Total views", "Median views", "Median views/day", "Avg % viewed", "Engagement /1k", "Subs gained", "Watch hours"]
    if df.empty or by not in df.columns:
        return pd.DataFrame(columns=[by, *columns])
    data = df[df[by].notna() & (df[by].astype(str) != "")]
    grouped = data.groupby(by, dropna=True)
    out = pd.DataFrame(
        {
            "Videos": grouped["video_id"].count(),
            "Total views": grouped["views"].sum(),
            "Median views": grouped["views"].median().round(0),
            "Median views/day": grouped["views_per_day"].median().round(1),
            "Avg % viewed": grouped["avg_view_pct"].mean().round(1),
            "Engagement /1k": grouped["engagement_per_1k"].mean().round(1),
            "Subs gained": grouped["subs_gained"].sum(),
            "Watch hours": (grouped["watch_minutes"].sum() / 60).round(1),
        }
    ).reset_index()
    return out.sort_values("Median views", ascending=False, kind="stable").reset_index(drop=True)


def batch_summary(df: pd.DataFrame) -> pd.DataFrame:
    """Every batch (and single videos, pooled per studio) with its results."""
    columns = ["Studio", "Batch", "Made", "Posted", "Batch size", "Total views", "Median views", "Avg % viewed", "Best video", "Weakest video", "batch_id", "studio"]
    batched = df[df["batch_id"].astype(str) != ""] if not df.empty else df
    if batched.empty:
        return pd.DataFrame(columns=columns)
    rows = []
    for (studio, batch_id), group in batched.groupby(["studio", "batch_id"]):
        made = group["created_at"].dropna().min()
        best = group.loc[group["views"].idxmax()]
        worst = group.loc[group["views"].idxmin()]
        made_label = made.strftime("%b %d, %Y") if made is not None and not pd.isna(made) else "?"
        rows.append(
            {
                "Studio": STUDIO_LABELS.get(studio, studio),
                "Batch": f"{made_label} · {int(group['batch_size'].max())} videos" + (" (guessed)" if group["batch_inferred"].any() else ""),
                "Made": made,
                "Posted": int(len(group)),
                "Batch size": int(group["batch_size"].max()),
                "Total views": int(group["views"].sum()),
                "Median views": float(group["views"].median()),
                "Avg % viewed": round(float(group["avg_view_pct"].mean()), 1) if group["avg_view_pct"].notna().any() else float("nan"),
                "Best video": f"{best['title']} ({int(best['views']):,})",
                "Weakest video": f"{worst['title']} ({int(worst['views']):,})",
                "batch_id": batch_id,
                "studio": studio,
            }
        )
    return pd.DataFrame(rows, columns=columns).sort_values("Made", ascending=False, na_position="last").reset_index(drop=True)


def insights(df: pd.DataFrame, dimensions: list[str], metric: str = "views", min_videos: int = 3, limit: int = 6) -> list[dict]:
    """Groups that clearly beat (or trail) the rest, in plain language.

    A group needs ``min_videos`` videos and the dimension at least two such
    groups, so one lucky video never becomes a "finding".
    """
    if df.empty or metric not in df.columns:
        return []
    label, how = METRICS.get(metric, (metric, "median"))
    data = df[df[metric].notna()]
    overall = getattr(data[metric], how)()
    if not overall or pd.isna(overall):
        return []
    found = []
    for dim in dimensions:
        if dim not in data.columns:
            continue
        valid = data[data[dim].notna() & (data[dim].astype(str) != "")]
        stats = valid.groupby(dim)[metric].agg([how, "count"])
        stats = stats[stats["count"] >= min_videos]
        if len(stats) < 2:
            continue
        for group, row in stats.iterrows():
            ratio = row[how] / overall
            if ratio >= 1.25 or ratio <= 0.75:
                found.append(
                    {
                        "dimension": dim,
                        "dimension_label": DIMENSION_LABELS.get(dim, dim),
                        "group": str(group),
                        "value": float(row[how]),
                        "ratio": float(ratio),
                        "videos": int(row["count"]),
                        "positive": ratio > 1,
                        "metric_label": label,
                    }
                )
    found.sort(key=lambda f: abs(f["ratio"] - 1) if f["positive"] else abs(1 / max(f["ratio"], 0.01) - 1), reverse=True)
    winners = [f for f in found if f["positive"]][: max(1, limit - limit // 3)]
    losers = [f for f in found if not f["positive"]][: limit // 3]
    return winners + losers
