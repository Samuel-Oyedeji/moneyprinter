"""The shared YouTube upload budget across every calendar.

The YouTube Data API's default quota allows about 6 uploads a day
(videos.insert costs 1600 of 10,000 units). Shorts, documentaries and
animations each keep their own calendar, but they all draw from this one
budget, so every planner asks here before booking a day.

Counted per calendar date (the day the upload runs):
  Shorts         every non-failed entry, times its video_count
  Documentaries  every non-failed entry
  Animations     every entry except failed ones and ones marked as already
                 posted by hand (those never touch the API)
"""

from datetime import date as date_cls
from datetime import timedelta

DAILY_BUDGET = 6


def daily_load(day: str) -> dict:
    from app.services import schedule as shorts_schedule
    from app.services.animation import schedule as animation_schedule
    from app.services.documentary import doc_schedule

    shorts = sum(
        int(e.get("video_count", 1) or 1)
        for e in shorts_schedule.list_entries(start_date=day, end_date=day)
        if e.get("status") != "failed"
    )
    documentaries = sum(
        1 for e in doc_schedule.list_entries() if e.get("date") == day and e.get("status") != doc_schedule.STATUS_FAILED
    )
    animations = sum(1 for e in animation_schedule.list_entries() if e.get("date") == day and animation_schedule.counts_toward_budget(e))
    total = shorts + documentaries + animations
    return {
        "date": day,
        "shorts": shorts,
        "documentaries": documentaries,
        "animations": animations,
        "total": total,
        "budget": DAILY_BUDGET,
        "left": max(0, DAILY_BUDGET - total),
        "full": total >= DAILY_BUDGET,
        "over_budget": total > DAILY_BUDGET,
    }


def upcoming(days: int = 14, start: str | None = None) -> list[dict]:
    first = date_cls.fromisoformat(start) if start else date_cls.today()
    return [daily_load((first + timedelta(days=i)).isoformat()) for i in range(days)]
