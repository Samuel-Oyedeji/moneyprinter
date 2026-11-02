"""The shared YouTube upload budget across every calendar and studio.

Since June 2026 the YouTube Data API gives uploads (videos.insert) their own
allowance of 100 a day per Cloud project. The app books far fewer than that:
[youtube] daily_upload_budget (default 50) leaves room for retries and hand
uploads, and keeps the channel's posting volume deliberate. Shorts,
documentaries, animations and studios each keep their own calendar, but they
all draw from this one budget, so every planner asks here before booking.

Counted per calendar date (the day the upload runs):
  Shorts         every non-failed entry, times its video_count
  Documentaries  every entry except failed ones and ones marked as already
                 posted by hand
  Animations     every entry except failed ones and ones marked as already
                 posted by hand (those never touch the API)
  Studios        every booked slot that is not cancelled or failed
"""

from datetime import date as date_cls
from datetime import timedelta

from app.config import config

DEFAULT_DAILY_BUDGET = 50
API_DAILY_UPLOADS = 100  # videos.insert calls a project may make per day


def daily_budget() -> int:
    try:
        value = int(config.youtube.get("daily_upload_budget", DEFAULT_DAILY_BUDGET))
    except (TypeError, ValueError):
        value = DEFAULT_DAILY_BUDGET
    return max(1, min(value, API_DAILY_UPLOADS))


def daily_load(day: str) -> dict:
    from app.services import schedule as shorts_schedule
    from app.services.animation import schedule as animation_schedule
    from app.services.documentary import doc_schedule
    from app.services.studios import store as studio_store

    shorts = sum(
        int(e.get("video_count", 1) or 1)
        for e in shorts_schedule.list_entries(start_date=day, end_date=day)
        if e.get("status") != "failed"
    )
    documentaries = sum(1 for e in doc_schedule.list_entries() if e.get("date") == day and doc_schedule.counts_toward_budget(e))
    animations = sum(1 for e in animation_schedule.list_entries() if e.get("date") == day and animation_schedule.counts_toward_budget(e))
    studios = studio_store.daily_slot_count(day)
    total = shorts + documentaries + animations + studios
    budget = daily_budget()
    return {
        "date": day,
        "shorts": shorts,
        "documentaries": documentaries,
        "animations": animations,
        "studios": studios,
        "total": total,
        "budget": budget,
        "left": max(0, budget - total),
        "full": total >= budget,
        "over_budget": total > budget,
    }


def upcoming(days: int = 14, start: str | None = None) -> list[dict]:
    first = date_cls.fromisoformat(start) if start else date_cls.today()
    return [daily_load((first + timedelta(days=i)).isoformat()) for i in range(days)]
