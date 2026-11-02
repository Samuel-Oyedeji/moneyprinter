"""The trial report: docs/studios-trial-run.md, computed from the queue and
the timeline rather than from memory.

    shadow     the go/no-go numbers for the shadow days (§4)
    areas      the pass criteria for the live weeks (§6), each pass / fail /
               not yet (too early to tell) / info
    weeks      per ISO week: videos, spend vs budget, median 3-day views

The live period starts on the date of the first video that was uploaded to
be published (not in shadow) unless a start date is given.

"Unattended" means the video went up with no action from the owner: not
approved early and not part of a slot the owner cancelled. A slot the
owner cancelled still counts as due, so cancelling lowers autonomy.
"""

from datetime import date as date_cls
from datetime import datetime, timedelta, timezone

from app.services.studios import evaluate, model, runner, store

AUTONOMY_BAR = 0.95
AUTONOMY_DAYS = 14
FAILURE_EVENTS = ("incident", "qa_failed")


def _median(values):
    values = sorted(v for v in values if v is not None)
    if not values:
        return None
    mid = len(values) // 2
    return values[mid] if len(values) % 2 else (values[mid - 1] + values[mid]) / 2


def _area(area: str, status: str, value: str, detail: str = "") -> dict:
    return {"area": area, "status": status, "value": value, "detail": detail}


def _due(slot: dict, now: datetime) -> bool:
    return not slot["reserve"] and bool(slot.get("date")) and runner.slot_utc(slot) <= now


def _published_live(slot: dict) -> bool:
    return slot["status"] == model.SLOT_UPLOADED and not slot.get("shadow")


def shadow_summary(studio: dict, queue: list[dict], costs: dict, now: datetime, until: date_cls | None) -> dict:
    slots = [s for s in queue if _due(s, now) and (until is None or date_cls.fromisoformat(s["date"]) < until)]
    uploaded = [s for s in slots if s["status"] == model.SLOT_UPLOADED]
    unattended = [s for s in uploaded if not s["veto_waived"]]
    reviews = [s["owner_review"].get("verdict") for s in uploaded if s.get("owner_review")]
    made = [costs[s["project_id"]] for s in slots if costs.get(s.get("project_id"))]
    return {
        "slots_due": len(slots),
        "uploaded_unattended": len(unattended),
        "failed": sum(1 for s in slots if s["status"] == model.SLOT_FAILED),
        "rated_good": reviews.count("good"),
        "rated_bad": reviews.count("bad"),
        "unrated": len(uploaded) - len(reviews),
        "cost_per_video": round(sum(made) / len(made), 2) if made else None,
    }


def report(studio_id: str, now: datetime | None = None, start: date_cls | None = None, end: date_cls | None = None) -> dict:
    now = now or datetime.now(timezone.utc)
    studio = store.load_studio(studio_id)
    if not studio:
        raise KeyError(f"studio not found: {studio_id}")
    queue = store.load_queue(studio_id)
    events = store.list_events(studio_id)
    costs = evaluate.production_costs(studio, queue)

    if start is None:
        live_dates = [s["date"] for s in queue if _published_live(s) and s.get("date")]
        start = date_cls.fromisoformat(min(live_dates)) if live_dates else None
    result = {"studio_id": studio_id, "live": start is not None, "shadow": shadow_summary(studio, queue, costs, now, start)}
    if start is None:
        return {**result, "areas": [], "weeks": [], "start": "", "end": ""}
    end = end or runner.local_date(now)

    window = [s for s in queue if _due(s, now) and start <= date_cls.fromisoformat(s["date"]) <= end]
    cancelled_by_owner = {(e.get("data") or {}).get("slot_id") for e in events if e["type"] == "vetoed"}
    areas = []

    # autonomy: the best run of AUTONOMY_DAYS consecutive days
    by_day: dict[date_cls, list[int]] = {}
    for slot in window:
        day = date_cls.fromisoformat(slot["date"])
        unattended = _published_live(slot) and not slot["veto_waived"] and slot["id"] not in cancelled_by_owner
        counts = by_day.setdefault(day, [0, 0])
        counts[0] += 1
        counts[1] += int(unattended)
    days = (end - start).days + 1
    total_due = sum(c[0] for c in by_day.values())
    total_ok = sum(c[1] for c in by_day.values())
    overall = total_ok / total_due if total_due else None
    best = None
    for offset in range(max(0, days - AUTONOMY_DAYS + 1)):
        span = [by_day.get(start + timedelta(days=offset + i), [0, 0]) for i in range(AUTONOMY_DAYS)]
        due = sum(c[0] for c in span)
        if due:
            rate = sum(c[1] for c in span) / due
            best = rate if best is None else max(best, rate)
    if best is None:
        areas.append(_area("Autonomy", "not yet", f"{total_ok} of {total_due} unattended", f"needs {AUTONOMY_DAYS} live days (has {days})"))
    else:
        areas.append(
            _area(
                "Autonomy", "pass" if best >= AUTONOMY_BAR else "fail", f"best {AUTONOMY_DAYS} days: {best:.0%}",
                f"overall {total_ok} of {total_due} slots ({overall:.0%}) went up with no action from you",
            )
        )

    # reliability: every dropped slot left a trace
    traced = {(e.get("data") or {}).get("slot_id") for e in events if e["type"] in FAILURE_EVENTS}
    failed = [s for s in window if s["status"] == model.SLOT_FAILED]
    silent = [s for s in failed if s["id"] not in traced]
    areas.append(
        _area(
            "Reliability", "fail" if silent else "pass", f"{len(silent)} silent of {len(failed)} failed",
            "; ".join(f"{s['date']} {s['time']} {s['brief']['topic']}" for s in silent) or "every failure is on the timeline",
        )
    )

    # quality: nothing published that the owner rated 👎
    published = [s for s in window if _published_live(s)]
    bad = [s for s in published if s["owner_review"].get("verdict") == "bad"]
    rated = sum(1 for s in published if s["owner_review"])
    qa_drops = sum(
        1 for e in events
        if e["type"] == "qa_failed" and not (e.get("data") or {}).get("retry") and start <= runner.local_date(datetime.fromtimestamp(e["ts"], timezone.utc)) <= end
    )
    areas.append(
        _area(
            "Quality", "fail" if bad else "pass", f"{len(bad)} published video(s) rated 👎",
            f"{rated} of {len(published)} rated; QA dropped {qa_drops}; you cancelled {len(cancelled_by_owner & {s['id'] for s in window})}"
            + ("; 👎: " + "; ".join(f"{s['brief']['topic']} ({s['owner_review'].get('note', '')})" for s in bad) if bad else ""),
        )
    )

    # learning hygiene: the evidence rule, and how good the predictions are
    beliefs = store.load_playbook(studio_id).get("beliefs") or []
    adopted = [b for b in beliefs if b.get("status") == "adopted"]
    unsound = [b for b in adopted if not model.can_adopt(b)[0]]
    hits = [s["checkins"]["3d"].get("prediction_hit") for s in published if (s["checkins"].get("3d") or {}).get("prediction_hit") is not None]
    hit_rate = f"{sum(hits) / len(hits):.0%} of {len(hits)} predictions right" if hits else "no scored predictions yet"
    areas.append(
        _area("Learning hygiene", "fail" if unsound else "pass", f"{len(adopted)} adopted belief(s), {len(unsound)} unsound", hit_rate)
    )

    # cost and performance, per ISO week
    planner_costs = evaluate.planner_spend(studio_id)
    weeks = []
    week = start - timedelta(days=start.weekday())
    while week <= end:
        week_end = week + timedelta(days=6)
        in_week = [s for s in queue if s.get("date") and week <= date_cls.fromisoformat(s["date"]) <= week_end]
        spend = sum(costs.get(s.get("project_id"), 0) or 0 for s in in_week)
        spend += sum(c for d, c in planner_costs if week <= date_cls.fromisoformat(d) <= week_end)
        views = [(s["checkins"].get("3d") or {}).get("views") for s in in_week if _published_live(s)]
        weeks.append(
            {
                "week": model.week_id(week),
                "videos": sum(1 for s in in_week if _published_live(s)),
                "spend": round(spend, 2),
                "budget": studio["weekly_budget_usd"],
                "median_views_3d": _median(views),
            }
        )
        week += timedelta(days=7)
    over = [w for w in weeks if w["spend"] > w["budget"]]
    areas.append(
        _area(
            "Cost", "fail" if over else "pass", f"${sum(w['spend'] for w in weeks):.2f} over {len(weeks)} week(s)",
            ", ".join(f"{w['week']} ${w['spend']:.2f} of ${w['budget']:g}" for w in weeks),
        )
    )
    known = [w for w in weeks if w["median_views_3d"] is not None]
    performance = (
        f"median 3-day views {known[0]['median_views_3d']:,.0f} ({known[0]['week']}) → {known[-1]['median_views_3d']:,.0f} ({known[-1]['week']})"
        if known else "no 3-day numbers yet"
    )
    areas.append(_area("Performance", "info", performance, "reported, not pass/fail: three weeks is too short to judge"))

    return {**result, "start": start.isoformat(), "end": end.isoformat(), "days": days, "areas": areas, "weeks": weeks}
