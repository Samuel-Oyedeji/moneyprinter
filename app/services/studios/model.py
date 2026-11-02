"""The shapes of a studio's files, and the rules that keep them honest.

    studio.json    the rules the owner sets; the agent reads, never writes
    playbook.json  what the agent believes works, each belief with evidence
    queue.json     the studio's upload slots and reserve topics
    experiments.json  the tests the agent runs: one lever, two or more values
    timeline.jsonl what happened, one event per line (append-only)
    notes.json     the owner's notes to the agent

Every validator returns a normalized copy and raises StudioError listing
every problem at once, so the planner agent (later) can fix a rejected plan
in one retry instead of one problem per round trip.
"""

import re
import time
from datetime import date as date_cls

STUDIO_ID_RE = re.compile(r"[a-z0-9][a-z0-9-]{0,39}")
TIME_RE = re.compile(r"([01]\d|2[0-3]):[0-5]\d")

PIPELINES = ("animation",)  # documentary and shorts join after the pilot

# Upload slots. Planned slots wait to be made; ready ones wait out the veto
# window; uploaded ones are on YouTube (private until their publish time).
SLOT_PLANNED = "planned"
SLOT_PRODUCING = "producing"
SLOT_READY = "ready"
SLOT_UPLOADING = "uploading"
SLOT_UPLOADED = "uploaded"
SLOT_CANCELLED = "cancelled"  # vetoed by the owner, or replaced by the agent
SLOT_FAILED = "failed"
SLOT_STATUSES = (SLOT_PLANNED, SLOT_PRODUCING, SLOT_READY, SLOT_UPLOADING, SLOT_UPLOADED, SLOT_CANCELLED, SLOT_FAILED)
# Slots that will (or did) use one of the day's uploads.
BUDGET_STATUSES = (SLOT_PLANNED, SLOT_PRODUCING, SLOT_READY, SLOT_UPLOADING, SLOT_UPLOADED)

ARMS = ("exploit", "explore")
PREDICTIONS = ("above", "at", "below")  # vs the studio baseline

EVENT_TYPES = (
    "plan",  # the weekly plan, with its review of last week
    "result",  # an experiment read out
    "belief",  # a playbook change, with evidence
    "produced",
    "qa_failed",
    "uploaded",
    "vetoed",
    "incident",  # anything that went wrong outside QA
    "note",  # the owner's
    "settings",  # the owner changed the studio's rules
)

EXPERIMENT_STATUSES = ("running", "concluded", "abandoned")
WEEK_RE = re.compile(r"\d{4}-W(0[1-9]|[1-4]\d|5[0-3])")

BELIEF_STATUSES = ("testing", "adopted", "rejected")
# A belief is adopted only with enough videos on every side, seen in more
# than one week, so a lucky week never becomes a rule.
ADOPT_MIN_VIDEOS_PER_ARM = 6
ADOPT_MIN_WEEKS = 2

# Brief fields that are not levers.
BRIEF_TEXT_FIELDS = ("topic", "category", "notes")
TOPIC_MAX = 200
NOTES_MAX = 2000


class StudioError(ValueError):
    """Invalid studio data. ``problems`` lists every issue found."""

    def __init__(self, problems):
        self.problems = [problems] if isinstance(problems, str) else list(problems)
        super().__init__("; ".join(self.problems))


def _minutes(hhmm: str) -> int:
    hours, minutes = hhmm.split(":")
    return int(hours) * 60 + int(minutes)


# ------------------------------------------------------------------- studio
def validate_studio(data: dict) -> dict:
    problems = []
    data = dict(data or {})

    studio_id = str(data.get("id", ""))
    if not STUDIO_ID_RE.fullmatch(studio_id):
        problems.append(f"id {studio_id!r} must be lowercase letters, digits and dashes (max 40)")
    name = str(data.get("name", "")).strip()
    if not name:
        problems.append("name is required")
    if data.get("pipeline") not in PIPELINES:
        problems.append(f"pipeline must be one of {', '.join(PIPELINES)}")
    identity = str(data.get("identity", "")).strip()
    if not identity:
        problems.append("identity (the studio's topic territory) is required")
    rules = data.get("hard_rules") or []
    if not isinstance(rules, list) or not all(isinstance(r, str) and r.strip() for r in rules):
        problems.append("hard_rules must be a list of non-empty strings")
        rules = []

    cadence = data.get("cadence") or {}
    per_day = cadence.get("per_day")
    if not isinstance(per_day, int) or not 1 <= per_day <= 10:
        problems.append("cadence.per_day must be a whole number from 1 to 10")

    window = data.get("post_window") or {}
    start, end = str(window.get("start", "")), str(window.get("end", ""))
    if not (TIME_RE.fullmatch(start) and TIME_RE.fullmatch(end)):
        problems.append("post_window needs start and end as HH:MM")
    elif _minutes(end) - _minutes(start) < 60:
        problems.append("post_window must be at least an hour long, within one day")

    levers = data.get("levers") or {}
    if not isinstance(levers, dict):
        problems.append("levers must be a mapping of name → {values, default}")
        levers = {}
    for lever_name, spec in levers.items():
        values = (spec or {}).get("values") if isinstance(spec, dict) else None
        if lever_name in BRIEF_TEXT_FIELDS:
            problems.append(f"lever {lever_name!r} clashes with a brief field")
        elif not isinstance(values, list) or len(values) < 2:
            problems.append(f"lever {lever_name!r} needs at least two values")
        elif spec.get("default") not in values:
            problems.append(f"lever {lever_name!r} default must be one of its values")

    for key, low, high in (("weekly_budget_usd", 0.5, 500), ("veto_hours", 0, 72)):
        value = data.get(key)
        if isinstance(value, bool) or not isinstance(value, (int, float)) or not low <= value <= high:
            problems.append(f"{key} must be a number from {low} to {high}")

    if problems:
        raise StudioError(problems)

    now = time.time()
    return {
        "id": studio_id,
        "name": name,
        "pipeline": data["pipeline"],
        "identity": identity,
        "hard_rules": [r.strip() for r in rules],
        "cadence": {"per_day": per_day},
        "post_window": {"start": start, "end": end},
        "levers": {k: {"values": list(v["values"]), "default": v["default"]} for k, v in levers.items()},
        "pipeline_options": dict(data.get("pipeline_options") or {}),
        "weekly_budget_usd": float(data["weekly_budget_usd"]),
        "veto_hours": float(data["veto_hours"]),
        "planner_model": str(data.get("planner_model", "") or "").strip(),
        "paused": bool(data.get("paused", True)),
        "created_at": data.get("created_at") or now,
        "updated_at": now,
    }


def slot_times(studio: dict) -> list[str]:
    """The day's publish times: per_day evenly spread through the window,
    each in the middle of its block (the Shorts calendar's spacing rule)."""
    start = _minutes(studio["post_window"]["start"])
    end = _minutes(studio["post_window"]["end"])
    per_day = studio["cadence"]["per_day"]
    block = (end - start) / per_day
    times = []
    for i in range(per_day):
        minute = int(round(start + block * (i + 0.5)))
        times.append(f"{minute // 60:02d}:{minute % 60:02d}")
    return times


def in_window(studio: dict, hhmm: str) -> bool:
    if not TIME_RE.fullmatch(str(hhmm)):
        return False
    window = studio["post_window"]
    return _minutes(window["start"]) <= _minutes(hhmm) <= _minutes(window["end"])


# -------------------------------------------------------------------- brief
def validate_brief(studio: dict, brief: dict, defaults: dict | None = None) -> dict:
    """A video's brief: topic + one value per lever (missing levers take the
    playbook default, then the studio default)."""
    problems = []
    brief = dict(brief or {})
    defaults = defaults or {}

    topic = str(brief.get("topic", "")).strip()
    if not topic:
        problems.append("brief.topic is required")
    elif len(topic) > TOPIC_MAX:
        problems.append(f"brief.topic is longer than {TOPIC_MAX} characters")
    notes = str(brief.get("notes", "") or "").strip()
    if len(notes) > NOTES_MAX:
        problems.append(f"brief.notes is longer than {NOTES_MAX} characters")

    clean = {"topic": topic, "category": str(brief.get("category", "") or "").strip(), "notes": notes}
    levers = studio.get("levers") or {}
    for lever_name, spec in levers.items():
        value = brief.get(lever_name)
        if value is None:
            value = defaults.get(lever_name, spec["default"])
        if value not in spec["values"]:
            problems.append(f"brief.{lever_name} = {value!r} is not one of {spec['values']}")
        clean[lever_name] = value
    unknown = sorted(set(brief) - set(levers) - set(BRIEF_TEXT_FIELDS))
    if unknown:
        problems.append(f"brief has unknown fields: {', '.join(unknown)}")

    if problems:
        raise StudioError(problems)
    return clean


# --------------------------------------------------------------------- slot
def validate_slot(studio: dict, slot: dict, defaults: dict | None = None) -> dict:
    """A queue slot. Reserve slots carry a brief but no date or time until
    they replace a slot that failed QA."""
    problems = []
    slot = dict(slot or {})
    reserve = bool(slot.get("reserve"))
    day, hhmm = str(slot.get("date", "") or ""), str(slot.get("time", "") or "")
    if not reserve:
        try:
            date_cls.fromisoformat(day)
        except ValueError:
            problems.append(f"slot date {day!r} must be YYYY-MM-DD")
        if not in_window(studio, hhmm):
            window = studio["post_window"]
            problems.append(f"slot time {hhmm!r} must be HH:MM within {window['start']}–{window['end']}")
    status = slot.get("status", SLOT_PLANNED)
    if status not in SLOT_STATUSES:
        problems.append(f"slot status {status!r} is unknown")
    arm = slot.get("arm", "exploit")
    if arm not in ARMS:
        problems.append(f"slot arm must be one of {', '.join(ARMS)}")
    prediction = slot.get("prediction", "")
    if prediction and prediction not in PREDICTIONS:
        problems.append(f"slot prediction must be one of {', '.join(PREDICTIONS)}")
    try:
        brief = validate_brief(studio, slot.get("brief") or {}, defaults)
    except StudioError as exc:
        problems.extend(exc.problems)
        brief = {}

    if problems:
        raise StudioError(problems)
    now = time.time()
    return {
        "id": slot.get("id", ""),
        "reserve": reserve,
        "date": "" if reserve else day,
        "time": "" if reserve else hhmm,
        "status": status,
        "brief": brief,
        "week": str(slot.get("week", "") or ""),
        "experiment": str(slot.get("experiment", "") or ""),
        "arm": arm,
        "prediction": prediction,
        "why": str(slot.get("why", "") or "").strip()[:500],  # the agent's reason for this video
        "project_id": slot.get("project_id", ""),
        "youtube_video_id": slot.get("youtube_video_id", ""),
        "publish_at": slot.get("publish_at", ""),
        "error": slot.get("error", ""),
        "created_at": slot.get("created_at") or now,
        "updated_at": now,
    }


# --------------------------------------------------------------- experiment
def week_id(day: date_cls) -> str:
    """ISO week, e.g. "2026-W46": the unit the agent plans in."""
    year, week, _ = day.isocalendar()
    return f"{year}-W{week:02d}"


def validate_experiment(studio: dict, experiment: dict) -> dict:
    """One test: a lever and the values being compared (the arms)."""
    problems = []
    experiment = dict(experiment or {})
    exp_id = str(experiment.get("id", "")).strip()
    if not exp_id:
        problems.append("experiment id is required")
    week = str(experiment.get("week", ""))
    if not WEEK_RE.fullmatch(week):
        problems.append(f"experiment week {week!r} must look like 2026-W46")
    lever = experiment.get("lever")
    levers = studio.get("levers") or {}
    values = list(experiment.get("values") or [])
    if lever not in levers:
        problems.append(f"experiment lever {lever!r} is not one of {', '.join(levers)}")
    else:
        bad = [v for v in values if v not in levers[lever]["values"]]
        if bad:
            problems.append(f"experiment values {bad} are not allowed for {lever}")
    if len(set(map(str, values))) < 2:
        problems.append("an experiment compares at least two different values")
    status = experiment.get("status", "running")
    if status not in EXPERIMENT_STATUSES:
        problems.append(f"experiment status must be one of {', '.join(EXPERIMENT_STATUSES)}")
    if problems:
        raise StudioError(problems)
    return {
        "id": exp_id,
        "week": week,
        "lever": lever,
        "values": values,
        "hypothesis": str(experiment.get("hypothesis", "") or "").strip(),
        "status": status,
        "verdict": dict(experiment.get("verdict") or {}),
        "created_at": experiment.get("created_at") or time.time(),
    }


# ----------------------------------------------------------------- playbook
def empty_playbook() -> dict:
    return {"defaults": {}, "beliefs": [], "updated_at": 0}


def can_adopt(belief: dict) -> tuple[bool, str]:
    per_arm = belief.get("videos_per_arm") or []
    weeks = sorted(set(belief.get("weeks") or []))
    if len(per_arm) < 2:
        return False, "an adopted belief needs video counts for at least two arms"
    if min(per_arm) < ADOPT_MIN_VIDEOS_PER_ARM:
        return False, f"an adopted belief needs {ADOPT_MIN_VIDEOS_PER_ARM}+ videos on every arm (has {min(per_arm)})"
    if len(weeks) < ADOPT_MIN_WEEKS:
        return False, f"an adopted belief needs evidence from {ADOPT_MIN_WEEKS}+ separate weeks (has {len(weeks)})"
    if not belief.get("evidence"):
        return False, "an adopted belief must cite its experiments"
    return True, ""


def validate_playbook(studio: dict, playbook: dict) -> dict:
    problems = []
    playbook = dict(playbook or {})
    levers = studio.get("levers") or {}

    defaults = dict(playbook.get("defaults") or {})
    for lever_name, value in defaults.items():
        if lever_name not in levers:
            problems.append(f"playbook default for unknown lever {lever_name!r}")
        elif value not in levers[lever_name]["values"]:
            problems.append(f"playbook default {lever_name} = {value!r} is not an allowed value")

    beliefs, seen = [], set()
    for i, raw in enumerate(playbook.get("beliefs") or []):
        belief = dict(raw or {})
        label = belief.get("id") or f"#{i + 1}"
        if not belief.get("id"):
            problems.append(f"belief {label} has no id")
        elif belief["id"] in seen:
            problems.append(f"belief id {belief['id']!r} is used twice")
        seen.add(belief.get("id"))
        if not str(belief.get("claim", "")).strip():
            problems.append(f"belief {label} has no claim")
        if belief.get("status") not in BELIEF_STATUSES:
            problems.append(f"belief {label} status must be one of {', '.join(BELIEF_STATUSES)}")
        if belief.get("lever") and belief["lever"] not in levers and belief["lever"] not in ("topic", "category", "publish_time"):
            problems.append(f"belief {label} refers to unknown lever {belief['lever']!r}")
        if belief.get("status") == "adopted":
            ok, why = can_adopt(belief)
            if not ok:
                problems.append(f"belief {label}: {why}")
        beliefs.append(belief)

    if problems:
        raise StudioError(problems)
    return {"defaults": defaults, "beliefs": beliefs, "updated_at": time.time()}
