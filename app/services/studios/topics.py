"""Topic novelty: has the channel covered this lately?

The planner may not repeat a topic from the last 60 days. "Repeat" is fuzzy:
"Why do cats purr?" and "The science of cat purring" are the same video to a
viewer. Two topics match when their content words (lowercased, crudely
stemmed, stop words dropped) overlap by 60% or more, or their text is 80%
alike character by character.

Recent topics come from three places, so nothing slips through: the
channel's own titles (the analytics sync), every animation project made on
this machine, and every studio's queue.
"""

import re
import time
from datetime import date as date_cls
from datetime import datetime, timedelta, timezone
from difflib import SequenceMatcher

from app.services.studios import model

RECENT_DAYS = 60
WORD_OVERLAP = 0.6
TEXT_RATIO = 0.8

_STOP = frozenset(
    "a an and are as at be but by can could did do does for from had has have how if in into is it its "
    "of on or so than that the their then there these they this to was were what when where which who "
    "why will with would you your ever really actually".split()
)


def _stem(word: str) -> str:
    for suffix in ("ing", "ed", "es"):
        if len(word) > len(suffix) + 3 and word.endswith(suffix):
            return word[: -len(suffix)]
    if len(word) > 3 and word.endswith("s") and not word.endswith("ss"):
        return word[:-1]  # cats → cat, but not glass → glas
    return word


def words(text: str) -> frozenset:
    tokens = re.findall(r"[a-z0-9]+", str(text or "").lower())
    return frozenset(_stem(t) for t in tokens if t not in _STOP)


def similarity(a: str, b: str) -> float:
    """0..1, where TEXT_RATIO and up means "the same topic". Word overlap is
    scaled so that WORD_OVERLAP lands exactly on TEXT_RATIO."""
    wa, wb = words(a), words(b)
    overlap = len(wa & wb) / len(wa | wb) if wa and wb else 0.0
    ratio = SequenceMatcher(None, str(a).lower().strip(), str(b).lower().strip()).ratio()
    return min(1.0, max(overlap * TEXT_RATIO / WORD_OVERLAP, ratio))


def is_same(a: str, b: str) -> bool:
    return similarity(a, b) >= TEXT_RATIO


def recent_topics(days: int = RECENT_DAYS, today: date_cls | None = None) -> list[dict]:
    """[{"text", "source", "date"}] of everything covered or booked lately."""
    from app.services.analytics import store as analytics_store
    from app.services.animation import store as anim_store
    from app.services.studios import store

    today = today or date_cls.today()
    since = today - timedelta(days=days)
    found = []

    for video in analytics_store.channel_videos():
        try:
            published = datetime.fromisoformat(str(video.get("published_at", "")).replace("Z", "+00:00")).date()
        except ValueError:
            continue
        if published >= since and video.get("title"):
            found.append({"text": video["title"], "source": "channel", "date": published.isoformat()})

    cutoff = time.mktime(since.timetuple())
    for project in anim_store.list_projects():
        if project.get("created_at", 0) >= cutoff and project.get("topic"):
            made = datetime.fromtimestamp(project["created_at"], timezone.utc).date().isoformat()
            found.append({"text": project["topic"], "source": "animation project", "date": made})

    for studio in store.list_studios():
        for slot in store.load_queue(studio["id"]):
            if slot.get("status") in (model.SLOT_CANCELLED, model.SLOT_FAILED):
                continue
            topic = (slot.get("brief") or {}).get("topic")
            booked = slot.get("date") or ""
            if topic and (not booked or booked >= since.isoformat()):
                found.append({"text": topic, "source": f"{studio['id']} queue", "date": booked})

    seen, unique = set(), []
    for item in found:
        key = item["text"].strip().lower()
        if key not in seen:
            seen.add(key)
            unique.append(item)
    return unique


def check(candidates: list[str], recent: list[dict]) -> list[dict]:
    """For each candidate topic: the recent topics it repeats (best first)."""
    results = []
    for candidate in candidates:
        matches = []
        for item in recent:
            score = similarity(candidate, item["text"])
            if score >= TEXT_RATIO:
                matches.append({**item, "similarity": round(score, 2)})
        matches.sort(key=lambda m: m["similarity"], reverse=True)
        results.append({"topic": candidate, "new": not matches, "matches": matches[:3]})
    return results
