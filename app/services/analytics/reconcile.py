"""Match the channel's videos to the app's items.

Uploads happen two ways: the calendar uploads up to six a day itself and
records the video id, and the owner uploads the rest by hand under the
title the app wrote. Reconciliation links both kinds, in order of trust:

  manual       the owner linked them on the Analytics page
  app upload   the app uploaded it and kept the id
  posted link  the owner marked it posted and pasted the video's URL
  title        exactly the same title once case, punctuation, emoji,
               hashtags and a " (2/3)" part suffix are ignored
  suggestion   a close-but-not-equal title; shown for one-click review,
               never linked on its own

A channel video is linked to at most one item. When one title fits several
items (the same topic made twice), the item made closest before the
video's publish time wins, and a video never matches an item made more
than a day after it was published.
"""

import difflib
import re
import unicodedata
from datetime import datetime

FUZZY_THRESHOLD = 0.85
# Uploads can carry a publish time slightly before the local creation stamp
# (timezones, clock skew); anything older than this cannot be the item.
_CLOCK_SLACK_SECONDS = 24 * 3600

_PART_SUFFIX_RE = re.compile(r"\s*\(\s*\d+\s*/\s*\d+\s*\)\s*$")
_HASHTAG_RE = re.compile(r"#[^\s#]+")
_VIDEO_ID_RE = re.compile(r"^[A-Za-z0-9_-]{11}$")
_URL_ID_RES = (
    re.compile(r"youtu\.be/([A-Za-z0-9_-]{11})"),
    re.compile(r"[?&]v=([A-Za-z0-9_-]{11})"),
    re.compile(r"/(?:shorts|embed|live|video)/([A-Za-z0-9_-]{11})"),
)


def normalize_title(text: str) -> str:
    text = unicodedata.normalize("NFKC", text or "")
    text = _PART_SUFFIX_RE.sub("", text)
    text = _HASHTAG_RE.sub(" ", text)
    text = text.casefold().replace("_", " ")
    text = re.sub(r"[^\w\s]", " ", text)
    return " ".join(text.split())


def video_id_from_url(url: str) -> str:
    """The 11-character id from any YouTube / Studio URL, or a bare id."""
    url = (url or "").strip()
    if _VIDEO_ID_RE.match(url):
        return url
    for pattern in _URL_ID_RES:
        match = pattern.search(url)
        if match:
            return match.group(1)
    return ""


def _published_ts(video: dict) -> float:
    value = video.get("published_at") or ""
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00")).timestamp()
    except ValueError:
        return 0.0


def _plausible(item: dict, video: dict) -> bool:
    published, created = _published_ts(video), float(item.get("created_at") or 0)
    if not published or not created:
        return True
    return published >= created - _CLOCK_SLACK_SECONDS


def _closeness(item: dict, video: dict) -> float:
    published, created = _published_ts(video), float(item.get("created_at") or 0)
    if not published or not created:
        return float("inf")
    return abs(published - created)


def reconcile(items: list[dict], videos: list[dict], decisions: dict | None = None) -> dict:
    """Link items to channel videos.

    ``decisions`` is the owner's links.json ({"links", "rejected", ...}).
    Returns::

        links             {item key: [{"video_id", "method", "score"}]}
        video_to_item     {video id: item key}
        suggestions       [{"item_key", "video_id", "score"}], best first
        unmatched_videos  channel video ids linked to nothing
        missing_posted    keys of items marked posted with no video found
        gone              [{"item_key", "video_id"}] the app uploaded that
                          are no longer on the channel
        duplicates        [{"item_key", "video_id"}] unmatched videos with the
                          same title as an already-linked item
    """
    decisions = decisions or {}
    manual = decisions.get("links") or {}
    rejected = {k: set(v or []) for k, v in (decisions.get("rejected") or {}).items()}
    by_key = {item["key"]: item for item in items}
    by_video = {video["video_id"]: video for video in videos}

    links: dict[str, list[dict]] = {}
    video_to_item: dict[str, str] = {}
    gone: list[dict] = []

    def assign(key: str, video_id: str, method: str, score: float = 1.0) -> None:
        links.setdefault(key, []).append({"video_id": video_id, "method": method, "score": round(score, 3)})
        video_to_item[video_id] = key

    for key, video_id in manual.items():
        if key in by_key and video_id in by_video and video_id not in video_to_item:
            assign(key, video_id, "manual")

    for item in items:
        for video_id in item.get("known_video_ids") or []:
            if video_id in video_to_item:
                continue
            if video_id in by_video:
                assign(item["key"], video_id, "app upload")
            elif videos:
                gone.append({"item_key": item["key"], "video_id": video_id})

    for item in items:
        video_id = video_id_from_url((item.get("posted") or {}).get("url", ""))
        if (
            video_id
            and video_id in by_video
            and video_id not in video_to_item
            and item["key"] not in links
            and video_id not in rejected.get(item["key"], set())
        ):
            assign(item["key"], video_id, "posted link")

    def open_items():
        return [i for i in items if i["key"] not in links]

    # exact titles, oldest videos first so earlier uploads claim earlier items
    title_index: dict[str, list[dict]] = {}
    for item in open_items():
        for title in item.get("titles") or []:
            normalized = normalize_title(title)
            if normalized:
                title_index.setdefault(normalized, []).append(item)
    for video in sorted(videos, key=_published_ts):
        video_id = video["video_id"]
        if video_id in video_to_item:
            continue
        candidates = [
            i
            for i in title_index.get(normalize_title(video.get("title", "")), [])
            if i["key"] not in links and video_id not in rejected.get(i["key"], set()) and _plausible(i, video)
        ]
        if candidates:
            best = min(candidates, key=lambda i: _closeness(i, video))
            assign(best["key"], video_id, "title")

    # near misses: the best open item per open video, one suggestion per item
    best_for_item: dict[str, dict] = {}
    remaining = open_items()
    normalized_titles = {i["key"]: [normalize_title(t) for t in i.get("titles") or [] if normalize_title(t)] for i in remaining}
    for video in videos:
        video_id = video["video_id"]
        if video_id in video_to_item:
            continue
        target = normalize_title(video.get("title", ""))
        if not target:
            continue
        best = None
        for item in remaining:
            if video_id in rejected.get(item["key"], set()) or not _plausible(item, video):
                continue
            score = max((difflib.SequenceMatcher(None, target, t).ratio() for t in normalized_titles[item["key"]]), default=0.0)
            if score >= FUZZY_THRESHOLD and (best is None or score > best["score"]):
                best = {"item_key": item["key"], "video_id": video_id, "score": round(score, 3)}
        if best and best["score"] > best_for_item.get(best["item_key"], {}).get("score", 0):
            best_for_item[best["item_key"]] = best
    suggestions = sorted(best_for_item.values(), key=lambda s: s["score"], reverse=True)

    linked_titles: dict[str, str] = {}
    for key in links:
        for title in by_key[key].get("titles") or []:
            linked_titles.setdefault(normalize_title(title), key)
    unmatched = [v["video_id"] for v in videos if v["video_id"] not in video_to_item]
    duplicates = [
        {"item_key": linked_titles[normalize_title(by_video[v].get("title", ""))], "video_id": v}
        for v in unmatched
        if normalize_title(by_video[v].get("title", "")) in linked_titles
    ]
    missing_posted = [i["key"] for i in items if (i.get("posted") or {}).get("manual") and i["key"] not in links]
    return {
        "links": links,
        "video_to_item": video_to_item,
        "suggestions": suggestions,
        "unmatched_videos": unmatched,
        "missing_posted": missing_posted,
        "gone": gone,
        "duplicates": duplicates,
    }
