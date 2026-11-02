"""The results packet: what a studio's videos did, computed in code.

The planner agent reads this packet instead of raw analytics. Every number
in it is computed here, reproducibly; the model only interprets it.

Scoring
    A video's score is how its views 3 days after publishing compare with
    the studio's baseline, on a log scale: log((views + 1) / (baseline + 1)).
    0 is typical, +0.22 is 25% above, -0.22 is 20% below. Log scale because
    Shorts views are heavy-tailed: one viral video must not swamp the rest.

Baseline
    The median 3-day views of the 20 videos of the same pipeline (made by
    the studio or by hand) published before this one. With fewer than 5 such
    videos there is no baseline yet: the studio is calibrating and its
    videos are reported unscored.

Experiments
    An experiment compares values of one lever. An arm needs 3 scored
    videos; a value wins only when its median score beats the runner-up by
    25% (log 1.25). Anything weaker is reported as no clear difference,
    and the packet says so in plain words.
"""

import math
from datetime import date as date_cls
from datetime import datetime, timedelta, timezone

import pandas as pd

from app.services.studios import model

SCORE_DAYS = 3
BASELINE_WINDOW = 20
MIN_BASELINE = 5
MIN_PER_ARM = 3
WIN_EFFECT = math.log(1.25)
ABOVE, BELOW = math.log(1.25), math.log(0.8)  # the "at baseline" band
MAX_VIDEOS = 40  # most recent uploads listed in the packet
RECENT_WEEKS = 4  # concluded experiments still shown


def _number(value):
    """A JSON-safe float (NaN and missing become None)."""
    if value is None:
        return None
    try:
        value = float(value)
    except (TypeError, ValueError):
        return None
    return None if math.isnan(value) else value


def _median(values: list[float]):
    values = sorted(v for v in values if v is not None)
    if not values:
        return None
    mid = len(values) // 2
    return values[mid] if len(values) % 2 else (values[mid - 1] + values[mid]) / 2


def _percent(log_ratio):
    return None if log_ratio is None else round((math.exp(log_ratio) - 1) * 100)


def outcome_of(score) -> str:
    if score is None:
        return ""
    if score >= ABOVE:
        return "above"
    if score <= BELOW:
        return "below"
    return "at"


def baseline_pool(df: pd.DataFrame, pipeline: str) -> list[tuple[datetime, float]]:
    """(published_at, views at 3 days) of the pipeline's videos, oldest first."""
    if df.empty or "views_3d" not in df.columns:
        return []
    rows = df[(df["studio"] == pipeline) & df["views_3d"].notna() & df["published_at"].notna()]
    return sorted((row.published_at, float(row.views_3d)) for row in rows.itertuples())


def baseline_at(pool: list[tuple[datetime, float]], published) -> tuple[float | None, int]:
    """(median 3-day views of the last BASELINE_WINDOW videos before
    ``published``, how many there were); None below MIN_BASELINE."""
    earlier = [views for when, views in pool if published is None or when < published][-BASELINE_WINDOW:]
    if len(earlier) < MIN_BASELINE:
        return None, len(earlier)
    return _median(earlier), len(earlier)


def score_videos(queue: list[dict], df: pd.DataFrame, pipeline: str, costs: dict | None = None) -> list[dict]:
    """Every uploaded slot, joined to its channel numbers and scored."""
    pool = baseline_pool(df, pipeline)
    by_id = {} if df.empty else {row["video_id"]: row for row in df.to_dict("records")}
    costs = costs or {}
    videos = []
    for slot in queue:
        if slot.get("status") != model.SLOT_UPLOADED or not slot.get("youtube_video_id"):
            continue
        row = by_id.get(slot["youtube_video_id"])
        video = {
            "slot_id": slot["id"],
            "video_id": slot["youtube_video_id"],
            "date": slot.get("date", ""),
            "week": slot.get("week", ""),
            "topic": (slot.get("brief") or {}).get("topic", ""),
            "brief": slot.get("brief") or {},
            "experiment": slot.get("experiment", ""),
            "arm": slot.get("arm", ""),
            "prediction": slot.get("prediction", ""),
            "cost": _number(costs.get(slot.get("project_id", ""))),
            "title": "",
            "published_at": "",
            "age_days": None,
            "views": None,
            "views_3d": None,
            "views_7d": None,
            "avg_view_pct": None,
            "baseline": None,
            "score": None,
            "vs_baseline_pct": None,
            "outcome": "",
            "prediction_hit": None,
            "state": "not on the channel yet",  # not synced, or still private
        }
        if row is not None:
            published = row.get("published_at")
            base, _ = baseline_at(pool, published)
            views_3d = _number(row.get("views_3d"))
            video.update(
                title=row.get("title", ""),
                published_at=published.isoformat() if isinstance(published, datetime) else "",
                age_days=_number(row.get("age_days")),
                views=_number(row.get("views")),
                views_3d=views_3d,
                views_7d=_number(row.get("views_7d")),
                avg_view_pct=_number(row.get("avg_view_pct")),
                baseline=base,
            )
            if views_3d is None:
                video["state"] = "too young to score" if (video["age_days"] or 0) < SCORE_DAYS + 1 else "no 3-day count"
            elif base is None:
                video["state"] = "no baseline yet (calibrating)"
            else:
                score = math.log((views_3d + 1) / (base + 1))
                video.update(score=round(score, 3), vs_baseline_pct=_percent(score), outcome=outcome_of(score), state="scored")
                if video["prediction"] in model.PREDICTIONS:
                    video["prediction_hit"] = video["prediction"] == video["outcome"]
        videos.append(video)
    videos.sort(key=lambda v: (v["date"], v["published_at"]))
    return videos


def judge_experiment(experiment: dict, queue: list[dict], videos: list[dict]) -> dict:
    """Each arm's numbers and the verdict, by the rules in the module doc."""
    lever = experiment["lever"]
    scored = {v["slot_id"]: v for v in videos}
    arms = []
    waiting = 0
    for value in experiment["values"]:
        slots = [
            s for s in queue
            if s.get("experiment") == experiment["id"]
            and str((s.get("brief") or {}).get(lever)) == str(value)
            and s.get("status") not in (model.SLOT_CANCELLED, model.SLOT_FAILED)
        ]
        results = [scored[s["id"]] for s in slots if s["id"] in scored]
        scores = [v["score"] for v in results if v["score"] is not None]
        waiting += len(slots) - len(scores)
        arms.append(
            {
                "value": value,
                "videos": len(slots),
                "scored": len(scores),
                "median_score": None if not scores else round(_median(scores), 3),
                "median_vs_baseline_pct": _percent(_median(scores)),
                "median_avg_view_pct": _number(_median([v["avg_view_pct"] for v in results])),
            }
        )

    ranked = sorted((a for a in arms if a["median_score"] is not None), key=lambda a: a["median_score"], reverse=True)
    enough = all(a["scored"] >= MIN_PER_ARM for a in arms)
    if enough and len(ranked) >= 2:
        best, runner_up = ranked[0], ranked[1]
        gap = best["median_score"] - runner_up["median_score"]
        if gap >= WIN_EFFECT:
            verdict = {
                "status": "winner",
                "winner": best["value"],
                "effect_pct": _percent(gap),
                "summary": f"{lever} = {best['value']} beat {runner_up['value']} by {_percent(gap)}% "
                f"(median 3-day views vs baseline, {best['scored']} vs {runner_up['scored']} videos).",
            }
        else:
            verdict = {
                "status": "no_difference",
                "winner": None,
                "effect_pct": _percent(gap),
                "summary": f"No clear difference between the {lever} values: the best leads by only "
                f"{_percent(gap)}%, under the 25% needed.",
            }
    elif waiting:
        verdict = {
            "status": "pending",
            "winner": None,
            "effect_pct": None,
            "summary": f"Waiting on {waiting} video(s) before {lever} can be judged.",
        }
    else:
        short = ", ".join(f"{a['value']} has {a['scored']}" for a in arms if a["scored"] < MIN_PER_ARM)
        verdict = {
            "status": "too_few",
            "winner": None,
            "effect_pct": None,
            "summary": f"Too few scored videos to judge {lever} ({short}; {MIN_PER_ARM} needed per value).",
        }
    return {
        "id": experiment["id"],
        "week": experiment["week"],
        "lever": lever,
        "hypothesis": experiment.get("hypothesis", ""),
        "status": experiment.get("status", "running"),
        "arms": arms,
        "videos_per_arm": [a["scored"] for a in arms],
        "verdict": verdict,
    }


def _week_start(day: date_cls) -> date_cls:
    return day - timedelta(days=day.weekday())


def spend(queue: list[dict], costs: dict, today: date_cls) -> dict:
    """Production cost of the slots dated this week and last week."""
    this_week = _week_start(today)
    totals = {"this_week": 0.0, "last_week": 0.0}
    for slot in queue:
        cost = _number(costs.get(slot.get("project_id", "")))
        if not cost or not slot.get("date"):
            continue
        start = _week_start(date_cls.fromisoformat(slot["date"]))
        if start == this_week:
            totals["this_week"] += cost
        elif start == this_week - timedelta(days=7):
            totals["last_week"] += cost
    return {k: round(v, 2) for k, v in totals.items()}


def build_packet(
    studio: dict,
    queue: list[dict],
    experiments: list[dict],
    df: pd.DataFrame,
    costs: dict | None = None,
    today: date_cls | None = None,
) -> dict:
    today = today or date_cls.today()
    costs = costs or {}
    videos = score_videos(queue, df, studio["pipeline"], costs)
    pool = baseline_pool(df, studio["pipeline"])
    end_of_today = datetime.combine(today + timedelta(days=1), datetime.min.time(), timezone.utc)
    current, pool_size = baseline_at(pool, end_of_today)

    oldest_week = model.week_id(today - timedelta(weeks=RECENT_WEEKS))
    shown = [e for e in experiments if e.get("status") == "running" or e.get("week", "") >= oldest_week]
    judged = [judge_experiment(e, queue, videos) for e in shown]

    with_prediction = [v for v in videos if v["prediction_hit"] is not None]
    hits = sum(1 for v in with_prediction if v["prediction_hit"])
    budget = studio.get("weekly_budget_usd", 0)
    spent = spend(queue, costs, today)
    states: dict[str, int] = {}
    for v in videos:
        states[v["state"]] = states.get(v["state"], 0) + 1

    return {
        "studio_id": studio["id"],
        "as_of": today.isoformat(),
        "week": model.week_id(today),
        "calibrating": current is None,
        "baseline": {
            "views_3d": current,
            "videos": pool_size,
            "needed": MIN_BASELINE,
            "explained": "median views 3 days after publishing, over the last "
            f"{BASELINE_WINDOW} {studio['pipeline']} videos",
        },
        "uploads": {
            "total": len(videos),
            "by_state": states,
            "planned_ahead": sum(1 for s in queue if s.get("status") in (model.SLOT_PLANNED, model.SLOT_PRODUCING, model.SLOT_READY)),
            "failed": sum(1 for s in queue if s.get("status") == model.SLOT_FAILED),
            "cancelled": sum(1 for s in queue if s.get("status") == model.SLOT_CANCELLED),
        },
        "videos": videos[-MAX_VIDEOS:],
        "experiments": judged,
        "predictions": {
            "scored": len(with_prediction),
            "hits": hits,
            "hit_rate": round(hits / len(with_prediction), 2) if with_prediction else None,
        },
        "spend": {**spent, "weekly_budget": budget, "left_this_week": round(max(0.0, budget - spent["this_week"]), 2)},
    }


def load_packet(studio_id: str, today: date_cls | None = None) -> dict:
    """The packet from what is on disk: the studio, its queue and
    experiments, the analytics dataset and each video's production cost."""
    from app.services.analytics import report
    from app.services.studios import store

    studio = store.load_studio(studio_id)
    if not studio:
        raise KeyError(f"studio not found: {studio_id}")
    queue = store.load_queue(studio_id)
    costs = {}
    if studio["pipeline"] == "animation":
        from app.services.animation import store as anim_store

        for slot in queue:
            project = anim_store.load_project(slot["project_id"]) if slot.get("project_id") else None
            if project:
                costs[slot["project_id"]] = anim_store.total_cost(project)
    return build_packet(studio, queue, store.load_experiments(studio_id), report.build_dataset(), costs, today)
