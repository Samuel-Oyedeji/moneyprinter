"""Metric tags: named slices of the analytics that a chat can reference.

A tag says *which videos* (a studio and optional filters such as "Main
setting = space") and *how to show them* (one of the kinds below). The
Assistant attaches the tags you pick to a conversation and sends their data
with every question; it can also look up any other tag itself.

Built-in tags are generated from the data, one per metric that exists today
(every animation style setting, every Shorts / documentary setting, topic
categories, batches…). When a studio starts recording a new style setting,
its tag appears on its own. Your own tags live in
storage/analytics/tags.json.

Kinds:
    breakdown  one row per group of ``group_by`` with the usual metrics
    videos     one row per video: title, numbers and that studio's features
    top        best and weakest videos by views per day
    batches    every generation batch with its best / weakest video
    insights   the groups that clearly beat or trail the typical video
"""

import json
import os
import re
import uuid

import pandas as pd

from app.services.analytics import catalog, report, store

KINDS = ("breakdown", "videos", "top", "batches", "insights")
MAX_VIDEO_ROWS = 80
_VIDEO_COLUMNS = (
    "title", "published", "views", "views_per_day", "views_7d", "avg_view_pct", "likes",
    "comments", "subs_gained", "topic", "category", "generation", "posted_via",
)
_COLUMN_NAMES = {
    "views_per_day": "views/day",
    "views_7d": "views at 7 days",
    "avg_view_pct": "% viewed",
    "subs_gained": "subs gained",
    "generation": "made as",
    "posted_via": "posted",
    "studio_label": "studio",
}


def _label(studio: str) -> str:
    return catalog.STUDIO_LABELS.get(studio, "All studios") if studio else "All studios"


def _tag(tag_id: str, name: str, kind: str, studio: str = "", group_by: str = "", filters=None, description: str = "", builtin: bool = True) -> dict:
    return {
        "id": tag_id,
        "name": name,
        "kind": kind,
        "studio": studio,
        "group_by": group_by,
        "filters": filters or {},
        "description": description,
        "builtin": builtin,
    }


# ------------------------------------------------------------------ built-in
def builtin_tags(df: pd.DataFrame) -> list[dict]:
    tags = [
        _tag("builtin:overview", "Studio vs studio", "breakdown", group_by="studio_label", description="Each studio's results side by side."),
        _tag("builtin:top", "Best & weakest videos (all studios)", "top", description="Top 15 and bottom 10 videos by views per day."),
        _tag("builtin:batches", "Batches (all studios)", "batches", description="Every generation batch and its best / weakest video."),
        _tag("builtin:category", "Topic categories (all studios)", "breakdown", group_by="category"),
    ]
    present = [s for s in catalog.STUDIOS if not df.empty and (df["studio"] == s).any()]
    for studio in present:
        label = _label(studio)
        tags.append(_tag(f"builtin:{studio}:videos", f"{label} · every video (titles & numbers)", "videos", studio, description="Titles, numbers and style of every video, best first."))
        tags.append(_tag(f"builtin:{studio}:insights", f"{label} · what stands out", "insights", studio))
        for dim in report.feature_dimensions(df, studio):
            if dim == "studio_label":
                continue
            tags.append(_tag(f"builtin:{studio}:{dim}", f"{label} · {report.DIMENSION_LABELS.get(dim, dim)}", "breakdown", studio, group_by=dim))
    return tags


# -------------------------------------------------------------------- custom
def _path() -> str:
    return os.path.join(store.analytics_dir(), "tags.json")


def custom_tags() -> list[dict]:
    try:
        with open(_path(), "r", encoding="utf-8") as f:
            data = json.load(f)
    except (OSError, json.JSONDecodeError):
        return []
    return [t for t in data if isinstance(t, dict) and t.get("id")] if isinstance(data, list) else []


def _save_custom(tags: list[dict]) -> None:
    with store._lock:
        path = _path()
        with open(f"{path}.tmp", "w", encoding="utf-8") as f:
            json.dump(tags, f, ensure_ascii=False, indent=2)
        os.replace(f"{path}.tmp", path)


def save_tag(name: str, studio: str = "", filters: dict | None = None, group_by: str = "", description: str = "", tag_id: str = "") -> dict:
    """Create (or, with ``tag_id``, replace) one of your own tags."""
    name = (name or "").strip()
    if not name:
        raise ValueError("a tag needs a name")
    if studio and studio not in catalog.STUDIOS:
        raise ValueError(f"unknown studio: {studio!r}")
    clean = {str(k): [str(v) for v in values] for k, values in (filters or {}).items() if k and values}
    tags = custom_tags()
    if any(t["name"].casefold() == name.casefold() and t["id"] != tag_id for t in tags):
        raise ValueError(f"there's already a tag called {name!r}")
    slug = re.sub(r"[^a-z0-9]+", "-", name.casefold()).strip("-")[:30] or "tag"
    tag = _tag(
        tag_id or f"custom:{slug}-{uuid.uuid4().hex[:6]}",
        name,
        "breakdown" if group_by else "videos",
        studio,
        group_by=group_by,
        filters=clean,
        description=(description or "").strip(),
        builtin=False,
    )
    tags = [t for t in tags if t["id"] != tag["id"]] + [tag]
    _save_custom(tags)
    return tag


def delete_tag(tag_id: str) -> None:
    _save_custom([t for t in custom_tags() if t["id"] != tag_id])


def all_tags(df: pd.DataFrame) -> list[dict]:
    return builtin_tags(df) + custom_tags()


def get_tag(tag_id: str, df: pd.DataFrame) -> dict | None:
    return next((t for t in all_tags(df) if t["id"] == tag_id), None)


# ----------------------------------------------------------------- rendering
def tag_frame(tag: dict, df: pd.DataFrame) -> pd.DataFrame:
    """The published videos a tag covers."""
    if df.empty:
        return df
    data = df[df["live"]]
    data = data[data["studio"] == tag["studio"]] if tag.get("studio") else data[data["studio"] != report.OTHER_STUDIO]
    for dim, values in (tag.get("filters") or {}).items():
        if dim not in data.columns:
            return data.iloc[0:0]
        data = data[data[dim].astype(str).isin([str(v) for v in values])]
    return data


def _csv(frame: pd.DataFrame) -> str:
    frame = frame.rename(columns=_COLUMN_NAMES)
    for column in frame.columns:
        if frame[column].dtype == object:
            frame[column] = frame[column].astype(str).str.slice(0, 90)
    return frame.to_csv(index=False, float_format="%.1f").strip()


def _video_rows(data: pd.DataFrame, studio: str, limit: int) -> pd.DataFrame:
    frame = data.copy()
    frame["published"] = frame["published_at"].map(lambda t: t.strftime("%Y-%m-%d") if t is not None and not pd.isna(t) else "")
    features = [c for c in frame.columns if c not in report.BASE_COLUMNS and c != "published" and frame[c].notna().any()] if studio else ["studio_label"]
    return frame[[*_VIDEO_COLUMNS, *features]].head(limit)


def _describe_filters(tag: dict) -> str:
    parts = [f"{report.DIMENSION_LABELS.get(d, d)} = {' or '.join(v)}" for d, v in (tag.get("filters") or {}).items()]
    return "; ".join(parts)


def render(tag: dict, df: pd.DataFrame, max_rows: int = MAX_VIDEO_ROWS) -> dict:
    """A tag's data as text a model can read: ``{"id", "name", "videos", "text"}``."""
    data = tag_frame(tag, df)
    lines = [f"### {tag['name']}  (tag id: {tag['id']})"]
    if tag.get("description"):
        lines.append(tag["description"])
    if tag.get("filters"):
        lines.append(f"Only videos where {_describe_filters(tag)}.")
    if data.empty:
        lines.append("No published videos match this yet.")
        return {"id": tag["id"], "name": tag["name"], "videos": 0, "text": "\n".join(lines)}

    overall = (
        f"{len(data)} published videos · median views {data['views'].median():,.0f} · "
        f"median views/day {data['views_per_day'].median():,.1f} · "
        f"avg % viewed {data['avg_view_pct'].mean():.1f}"
    )
    lines.append(overall)
    kind = tag.get("kind")
    if kind == "breakdown":
        summary = report.summarize(data, tag["group_by"]).rename(columns={tag["group_by"]: report.DIMENSION_LABELS.get(tag["group_by"], tag["group_by"])})
        lines.append(f"Grouped by {report.DIMENSION_LABELS.get(tag['group_by'], tag['group_by'])} (groups with fewer than 3 videos are weak evidence):")
        lines.append(_csv(summary))
    elif kind == "videos":
        ranked = data.sort_values("views_per_day", ascending=False)
        rows = _video_rows(ranked, tag.get("studio", ""), max_rows)
        if len(ranked) > max_rows:
            lines.append(f"Best {max_rows} of {len(ranked)} by views per day:")
        lines.append(_csv(rows))
    elif kind == "top":
        settled = data[data["age_days"] >= 3].sort_values("views_per_day", ascending=False)
        lines.append("Best 15 by views per day (videos at least 3 days old):")
        lines.append(_csv(_video_rows(settled.head(15), "", 15)))
        lines.append("Weakest 10:")
        lines.append(_csv(_video_rows(settled.tail(10).iloc[::-1], "", 10)))
    elif kind == "batches":
        lines.append(_csv(report.batch_summary(data).drop(columns=["batch_id", "studio"], errors="ignore")))
    elif kind == "insights":
        dims = [d for d in report.feature_dimensions(df, tag.get("studio") or None) if d != "studio_label"]
        findings = [f for metric in ("views", "avg_view_pct") for f in report.insights(data, dims, metric=metric)]
        for found in findings:
            arrow = "above" if found["positive"] else "below"
            times = found["ratio"] if found["positive"] else 1 / max(found["ratio"], 0.01)
            lines.append(
                f"- {found['dimension_label']} = {found['group']}: {found['metric_label'].lower()} "
                f"{found['value']:,.1f}, {times:.1f}× {arrow} typical ({found['videos']} videos)"
            )
        if not findings:
            lines.append("No group clearly beats or trails the rest yet (needs 3+ videos per group and a 25% gap).")
    return {"id": tag["id"], "name": tag["name"], "videos": int(len(data)), "text": "\n".join(lines)}
