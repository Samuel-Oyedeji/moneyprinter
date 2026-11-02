"""The weekly planning agent.

Once a week (and on its first run, for the rest of the current week) a
studio's agent reads its results packet (evaluate.py), its playbook, its
running experiments and the owner's unread notes, then submits a plan:

    review              what last week showed, in plain words
    slots               one video per free upload slot: date, time, brief,
                        experiment, prediction (above / at / below baseline)
    reserves            2 spare topics, used when a video fails QA
    experiments         new tests this week (one lever, two or more values)
    experiment_updates  running tests to conclude or abandon
    beliefs             playbook changes, each citing its experiments
    defaults            new default lever values (only with an adopted belief)
    note_replies        answers to the owner's notes

The model decides; code checks. check_plan() enforces every rule (slot
counts, lever values, the experiment and explore limits, topic novelty,
budget, the belief evidence rule) and returns all problems at once; the
model gets them back as the tool result and resubmits, up to 3 times.
Explore vs exploit is not the model's call: a slot that uses the default
for every lever is "exploit", anything else "explore".
"""

import json
from dataclasses import dataclass
from datetime import date as date_cls
from datetime import timedelta

from loguru import logger

from app.config import config
from app.services.studios import evaluate, model, store, topics

MAX_TESTS = 2  # levers under test in one week
RESERVES = 2
MAX_EXPLORE_SHARE = 0.4
CALIBRATION_EXPLORE_SHARE = 0.7  # no baseline yet: explore more
MIN_GAP_MINUTES = 60
MAX_ROUNDS = 12
MAX_FAILED_SUBMITS = 3
DEFAULT_VIDEO_COST = 0.30
REVIEW_MIN_CHARS = 40
MAX_RECENT_TOPICS = 150


class PlannerError(RuntimeError):
    pass


# ------------------------------------------------------------------ context
@dataclass
class Context:
    studio: dict
    playbook: dict
    experiments: list[dict]
    queue: list[dict]
    packet: dict
    judged: dict  # every experiment's judgement, by id
    days: list[dict]  # [{"date", "needed", "booked_times", "suggested_times"}]
    week: str
    recent: list[dict]
    notes: list[dict]
    video_cost: float


def planning_days(studio: dict, queue: list[dict], today: date_cls) -> list[dict]:
    """Tomorrow through the end of tomorrow's week, with the slots each day
    still needs (the studio's cadence, less what is booked, within the
    shared upload budget)."""
    from app.services import upload_budget

    first = today + timedelta(days=1)
    last = first + timedelta(days=6 - first.weekday())
    days = []
    day = first
    while day <= last:
        iso = day.isoformat()
        booked = sorted(s["time"] for s in queue if s.get("date") == iso and store.counts_toward_budget(s))
        needed = max(0, studio["cadence"]["per_day"] - len(booked))
        needed = min(needed, upload_budget.daily_load(iso)["left"])
        free_times = [t for t in model.slot_times(studio) if t not in booked]
        days.append({"date": iso, "needed": needed, "booked_times": booked, "suggested_times": free_times[:needed]})
        day += timedelta(days=1)
    return days


def build_context(studio_id: str, today: date_cls, df=None) -> Context:
    from app.services.analytics import report

    studio = store.load_studio(studio_id)
    if not studio:
        raise KeyError(f"studio not found: {studio_id}")
    queue = store.load_queue(studio_id)
    experiments = store.load_experiments(studio_id)
    df = report.build_dataset() if df is None else df
    costs = evaluate.production_costs(studio, queue)
    packet = evaluate.build_packet(studio, queue, experiments, df, costs, today, evaluate.planner_spend(studio_id))
    videos = evaluate.score_videos(queue, df, studio["pipeline"], costs)
    judged = {e["id"]: evaluate.judge_experiment(e, queue, videos) for e in experiments}
    known_costs = sorted(c for c in costs.values() if c)
    video_cost = known_costs[len(known_costs) // 2] if known_costs else DEFAULT_VIDEO_COST
    days = planning_days(studio, queue, today)
    return Context(
        studio=studio,
        playbook=store.load_playbook(studio_id),
        experiments=experiments,
        queue=queue,
        packet=packet,
        judged=judged,
        days=days,
        week=model.week_id(date_cls.fromisoformat(days[0]["date"])),
        recent=topics.recent_topics(today=today),
        notes=store.list_notes(studio_id, unread_only=True),
        video_cost=video_cost,
    )


# ------------------------------------------------------------------- checks
def effective_defaults(studio: dict, playbook: dict) -> dict:
    chosen = playbook.get("defaults") or {}
    return {lever: chosen.get(lever, spec["default"]) for lever, spec in studio["levers"].items()}


def arm_of(slot: dict, defaults: dict) -> str:
    brief = slot["brief"]
    return "explore" if any(brief.get(lever) != value for lever, value in defaults.items()) else "exploit"


def _lever_problems(slot: dict, defaults: dict, active: dict) -> list[str]:
    brief = slot["brief"]
    differs = [lever for lever, value in defaults.items() if brief.get(lever) != value]
    exp_id = slot.get("experiment")
    if not exp_id:
        if differs:
            return [f"{', '.join(differs)} differ(s) from the default but the slot is in no experiment"]
        return []
    experiment = active.get(exp_id)
    if not experiment:
        return [f"experiment {exp_id!r} is not running (start it under experiments)"]
    lever = experiment["lever"]
    problems = []
    if brief.get(lever) not in experiment["values"]:
        problems.append(f"{lever} = {brief.get(lever)!r} is not one of experiment {exp_id}'s values {experiment['values']}")
    others = [x for x in differs if x != lever]
    if others:
        problems.append(f"only {lever} may differ from the default in experiment {exp_id} (also differs: {', '.join(others)})")
    return problems


def _evidence(ctx: Context, belief: dict) -> tuple[list[int], list[str], str]:
    """(videos per value, weeks, problem) for an adopted belief, counted by
    code from the experiments it cites: the model's own numbers are ignored."""
    cited = [str(e) for e in belief.get("evidence") or []]
    if not cited:
        return [], [], "an adopted belief must cite the experiments behind it"
    per_value: dict[str, int] = {}
    weeks, winners = set(), 0
    for exp_id in cited:
        judged = ctx.judged.get(exp_id)
        if not judged:
            return [], [], f"cites unknown experiment {exp_id!r}"
        if belief.get("lever") and judged["lever"] != belief["lever"]:
            return [], [], f"experiment {exp_id} tested {judged['lever']}, not {belief['lever']}"
        weeks.add(judged["week"])
        winners += judged["verdict"]["status"] == "winner"
        for arm in judged["arms"]:
            per_value[str(arm["value"])] = per_value.get(str(arm["value"]), 0) + arm["scored"]
    if not winners:
        return [], [], "none of the cited experiments found a winner"
    return list(per_value.values()), sorted(weeks), ""


def check_plan(ctx: Context, plan: dict) -> tuple[dict, list[str]]:
    """Validate a submitted plan. Returns (clean plan, problems)."""
    problems: list[str] = []
    plan = plan if isinstance(plan, dict) else {}
    studio = ctx.studio

    review = str(plan.get("review", "") or "").strip()
    if len(review) < REVIEW_MIN_CHARS:
        problems.append(f"review must say what last week showed (at least {REVIEW_MIN_CHARS} characters)")

    # playbook: beliefs (adoption checked against real evidence) and defaults
    beliefs = {b["id"]: dict(b) for b in ctx.playbook.get("beliefs") or [] if b.get("id")}
    changed_beliefs = []
    for raw in plan.get("beliefs") or []:
        belief = dict(raw or {})
        belief_id = str(belief.get("id", "")).strip()
        if not belief_id:
            problems.append("every belief needs an id")
            continue
        belief["id"], belief["week"] = belief_id, ctx.week
        if belief.get("status") == "adopted":
            per_arm, weeks, why = _evidence(ctx, belief)
            if why:
                problems.append(f"belief {belief_id}: {why}")
            belief["videos_per_arm"], belief["weeks"] = per_arm, weeks
        beliefs[belief_id] = belief
        changed_beliefs.append(belief)
    new_defaults = dict(plan.get("defaults") or {})
    playbook = {"defaults": {**(ctx.playbook.get("defaults") or {}), **new_defaults}, "beliefs": list(beliefs.values())}
    defaults_ok = True
    if new_defaults:
        if ctx.packet.get("calibrating"):
            problems.append("defaults cannot change while the studio is calibrating (no baseline yet)")
            defaults_ok = False
        adopted = {b.get("lever") for b in playbook["beliefs"] if b.get("status") == "adopted"}
        for lever in new_defaults:
            if lever not in adopted:
                problems.append(f"changing the {lever} default needs an adopted belief about {lever}")
                defaults_ok = False
    try:
        playbook = model.validate_playbook(studio, playbook)
        playbook_ok = True
    except model.StudioError as exc:
        problems.extend(f"playbook: {p}" for p in exc.problems)
        playbook_ok = False
    # judge the slots against the defaults this plan will leave in place
    defaults = effective_defaults(studio, playbook if playbook_ok and defaults_ok else ctx.playbook)

    # experiments: conclude/abandon, then start new ones
    running = {e["id"]: e for e in ctx.experiments if e.get("status") == "running"}
    updates = []
    for raw in plan.get("experiment_updates") or []:
        exp_id, status = str((raw or {}).get("id", "")), (raw or {}).get("status")
        if exp_id not in running:
            problems.append(f"experiment_updates: {exp_id!r} is not a running experiment")
        elif status not in ("concluded", "abandoned"):
            problems.append(f"experiment_updates: {exp_id} status must be concluded or abandoned")
        else:
            verdict = (ctx.judged.get(exp_id) or {}).get("verdict") or {}
            updates.append({**running[exp_id], "status": status, "verdict": {**verdict, "note": str(raw.get("note", "") or "")}})
    closed = {u["id"] for u in updates}
    active = {k: v for k, v in running.items() if k not in closed}
    used_ids = {e["id"] for e in ctx.experiments}
    new_experiments = []
    for raw in plan.get("experiments") or []:
        candidate = {**(raw or {}), "week": ctx.week, "status": "running", "verdict": {}}
        exp_id = str(candidate.get("id", "")).strip()
        if exp_id in used_ids:
            problems.append(f"experiment id {exp_id!r} is already used; pick a new one")
            continue
        try:
            experiment = model.validate_experiment(studio, candidate)
        except model.StudioError as exc:
            problems.extend(f"experiment {exp_id or '?'}: {p}" for p in exc.problems)
            continue
        new_experiments.append(experiment)
        active[experiment["id"]] = experiment
        used_ids.add(exp_id)

    # slots
    needed = {d["date"]: d["needed"] for d in ctx.days}
    slots, times_by_day = [], {}
    for i, raw in enumerate(plan.get("slots") or []):
        label = f"slot {i + 1}"
        raw = dict(raw or {})
        if raw.get("date") not in needed:
            problems.append(f"{label}: date {raw.get('date')!r} is not a day this plan covers ({', '.join(needed)})")
            continue
        try:
            slot = model.validate_slot(studio, {**raw, "reserve": False, "status": model.SLOT_PLANNED}, defaults)
        except model.StudioError as exc:
            problems.extend(f"{label}: {p}" for p in exc.problems)
            continue
        if slot["prediction"] not in model.PREDICTIONS:
            problems.append(f"{label}: needs a prediction: above, at or below the baseline")
        problems.extend(f"{label}: {p}" for p in _lever_problems(slot, defaults, active))
        slot.update(arm=arm_of(slot, defaults), week=ctx.week)
        booked = next(d["booked_times"] for d in ctx.days if d["date"] == slot["date"])
        if slot["time"] in booked:
            problems.append(f"{label}: {slot['date']} {slot['time']} is already booked")
        times_by_day.setdefault(slot["date"], []).append(slot["time"])
        slots.append(slot)
    for day, count in needed.items():
        got = len(times_by_day.get(day, []))
        if got != count:
            problems.append(f"{day} needs {count} slot(s); the plan has {got}")
    for day, times in times_by_day.items():
        minutes = sorted(model._minutes(t) for t in times + next(d["booked_times"] for d in ctx.days if d["date"] == day))
        if any(b - a < MIN_GAP_MINUTES for a, b in zip(minutes, minutes[1:])):
            problems.append(f"{day}: uploads must be at least {MIN_GAP_MINUTES} minutes apart")

    reserves = []
    raw_reserves = plan.get("reserves") or []
    if len(raw_reserves) != RESERVES:
        problems.append(f"the plan needs exactly {RESERVES} reserves (it has {len(raw_reserves)})")
    for i, raw in enumerate(raw_reserves):
        raw = dict(raw or {})
        try:
            reserve = model.validate_slot(
                studio, {**raw, "reserve": True, "status": model.SLOT_PLANNED, "experiment": "", "prediction": raw.get("prediction") or "at"}, defaults
            )
        except model.StudioError as exc:
            problems.extend(f"reserve {i + 1}: {p}" for p in exc.problems)
            continue
        if arm_of(reserve, defaults) != "exploit":
            problems.append(f"reserve {i + 1}: must use the default for every lever")
        reserve.update(arm="exploit", week=ctx.week)
        reserves.append(reserve)

    # experiment sizes and the weekly limits
    for experiment in new_experiments:
        for value in experiment["values"]:
            count = sum(1 for s in slots if s["experiment"] == experiment["id"] and s["brief"].get(experiment["lever"]) == value)
            if count < evaluate.MIN_PER_ARM:
                problems.append(
                    f"experiment {experiment['id']}: {experiment['lever']} = {value!r} has {count} slot(s); "
                    f"a new test needs {evaluate.MIN_PER_ARM} per value"
                )
    tested = {active[s["experiment"]]["lever"] for s in slots if s["experiment"] in active}
    if len(tested) > MAX_TESTS:
        problems.append(f"at most {MAX_TESTS} levers can be under test in a week (this plan tests {', '.join(sorted(tested))})")
    if slots:
        explore = sum(1 for s in slots if s["arm"] == "explore")
        cap = CALIBRATION_EXPLORE_SHARE if ctx.packet.get("calibrating") else MAX_EXPLORE_SHARE
        if explore / len(slots) > cap + 1e-9:
            problems.append(
                f"{explore} of {len(slots)} slots differ from the defaults; at most {round(cap * 100)}% may "
                "(keep most videos on what works)"
            )

    # topics: new, and not repeating each other
    texts = [s["brief"]["topic"] for s in slots + reserves]
    for i, a in enumerate(texts):
        for b in texts[i + 1 :]:
            if topics.is_same(a, b):
                problems.append(f"{a!r} and {b!r} are the same topic")
    for result in topics.check(texts, ctx.recent):
        if not result["new"]:
            match = result["matches"][0]
            problems.append(f"{result['topic']!r} repeats {match['text']!r} ({match['source']}, {match['date'] or 'booked'})")

    estimate = round(len(slots) * ctx.video_cost, 2)
    budget = studio["weekly_budget_usd"]
    if estimate > budget:
        problems.append(f"{len(slots)} videos at about ${ctx.video_cost:.2f} each is ${estimate}, over the ${budget} weekly budget")

    replies = [
        {"note_id": str(r.get("note_id", "")), "reply": str(r.get("reply", "")).strip()}
        for r in plan.get("note_replies") or []
        if isinstance(r, dict) and str(r.get("reply", "")).strip()
    ]
    clean = {
        "review": review,
        "slots": slots,
        "reserves": reserves,
        "new_experiments": new_experiments,
        "experiment_updates": updates,
        "beliefs": changed_beliefs,
        "playbook": playbook,
        "new_defaults": new_defaults,
        "note_replies": replies,
        "estimated_cost": estimate,
    }
    return clean, problems


# -------------------------------------------------------------------- apply
def apply_plan(ctx: Context, clean: dict, planner_info: dict) -> dict:
    """Book the plan. The booking goes first: it is the step that can still
    fail (another process took a slot), and nothing else is written then."""
    studio_id = ctx.studio["id"]
    booked = store.add_slots(studio_id, clean["slots"] + clean["reserves"])
    for experiment in clean["new_experiments"] + clean["experiment_updates"]:
        store.save_experiment(studio_id, experiment)
    store.save_playbook(studio_id, clean["playbook"])
    store.mark_notes_read(studio_id, [n["id"] for n in ctx.notes])

    for update in clean["experiment_updates"]:
        verdict = update.get("verdict") or {}
        store.append_event(
            studio_id, "result", f"{update['id']} {update['status']}: {verdict.get('summary', '')}".strip(),
            {"experiment": update["id"], "status": update["status"], "verdict": verdict},
        )
    for belief in clean["beliefs"]:
        store.append_event(studio_id, "belief", f"{belief.get('status', '')}: {belief.get('claim', '')}", {"belief": belief})

    slots = [s for s in booked if not s["reserve"]]
    explore = sum(1 for s in slots if s["arm"] == "explore")
    tests = ", ".join(f"{e['lever']} ({' vs '.join(map(str, e['values']))})" for e in clean["new_experiments"])
    summary = f"{ctx.week}: {len(slots)} video(s) planned, {explore} exploring" + (f"; new tests: {tests}" if tests else "")
    event = store.append_event(
        studio_id,
        "plan",
        summary,
        {
            "week": ctx.week,
            "review": clean["review"],
            "slot_ids": [s["id"] for s in booked],
            "new_experiments": [e["id"] for e in clean["new_experiments"]],
            "new_defaults": clean["new_defaults"],
            "note_replies": clean["note_replies"],
            "estimated_cost": clean["estimated_cost"],
            "calibrating": ctx.packet.get("calibrating"),
            **planner_info,
        },
    )
    return {"event": event, "slots": booked}


# -------------------------------------------------------------------- agent
SUBMIT_PLAN = {
    "type": "function",
    "function": {
        "name": "submit_plan",
        "description": "Submit the week's plan. It is checked against every rule; on problems you get them all back and must resubmit the whole plan.",
        "parameters": {
            "type": "object",
            "properties": {
                "review": {"type": "string", "description": "What the results packet shows about last week, plainly, with numbers. Say when results are inconclusive."},
                "slots": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "properties": {
                            "date": {"type": "string", "description": "YYYY-MM-DD, one of the days to plan"},
                            "time": {"type": "string", "description": "HH:MM publish time inside the post window"},
                            "brief": {"type": "object", "description": "topic, category, notes (facts to get right), plus a value for any lever (missing levers use the default)"},
                            "experiment": {"type": "string", "description": "id of the experiment this video belongs to, or empty"},
                            "prediction": {"type": "string", "enum": list(model.PREDICTIONS), "description": "how its 3-day views will compare with the baseline"},
                            "why": {"type": "string", "description": "one sentence: why this video"},
                        },
                        "required": ["date", "time", "brief", "prediction"],
                    },
                },
                "reserves": {"type": "array", "items": {"type": "object", "properties": {"brief": {"type": "object"}, "why": {"type": "string"}}, "required": ["brief"]}},
                "experiments": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "properties": {
                            "id": {"type": "string"},
                            "lever": {"type": "string"},
                            "values": {"type": "array", "items": {}},
                            "hypothesis": {"type": "string"},
                        },
                        "required": ["id", "lever", "values", "hypothesis"],
                    },
                },
                "experiment_updates": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "properties": {"id": {"type": "string"}, "status": {"type": "string", "enum": ["concluded", "abandoned"]}, "note": {"type": "string"}},
                        "required": ["id", "status"],
                    },
                },
                "beliefs": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "properties": {
                            "id": {"type": "string"},
                            "claim": {"type": "string"},
                            "status": {"type": "string", "enum": list(model.BELIEF_STATUSES)},
                            "lever": {"type": "string"},
                            "evidence": {"type": "array", "items": {"type": "string"}, "description": "experiment ids"},
                            "effect": {"type": "string"},
                        },
                        "required": ["id", "claim", "status"],
                    },
                },
                "defaults": {"type": "object", "description": "lever → new default value (needs an adopted belief)"},
                "note_replies": {
                    "type": "array",
                    "items": {"type": "object", "properties": {"note_id": {"type": "string"}, "reply": {"type": "string"}}, "required": ["note_id", "reply"]},
                },
            },
            "required": ["review", "slots", "reserves"],
        },
    },
}
CHECK_TOPICS = {
    "type": "function",
    "function": {
        "name": "check_topics",
        "description": "Check candidate topics against everything the channel covered or booked in the last 60 days. Use it before submitting.",
        "parameters": {
            "type": "object",
            "properties": {"topics": {"type": "array", "items": {"type": "string"}}},
            "required": ["topics"],
        },
    },
}
TOOLS = [CHECK_TOPICS, SUBMIT_PLAN]


def system_prompt(ctx: Context) -> str:
    studio = ctx.studio
    rules = "\n".join(f"- {r}" for r in studio["hard_rules"])
    defaults = effective_defaults(studio, ctx.playbook)
    levers = "\n".join(f"- {name}: {spec['values']} (default now: {defaults[name]!r})" for name, spec in studio["levers"].items())
    cap = CALIBRATION_EXPLORE_SHARE if ctx.packet.get("calibrating") else MAX_EXPLORE_SHARE
    return f"""You are the producer of "{studio['name']}", one studio on a YouTube channel. Each week you decide
what the studio makes, learn from the results, and plan the next week. Nobody reviews your plan
before it runs, so it must be right.

# The studio
{studio['identity']}

Hard rules (never break them):
{rules}

# Levers you choose for each video
{levers}
Every video also has a topic (specific and concrete: one question, mechanism or moment), a broad
category, and notes: the key facts the writer must get right.

# How results are judged (computed in code; you read them in the results packet)
- A video's score compares its views 3 days after publishing with the baseline (median of the last
  {evaluate.BASELINE_WINDOW} videos). "above" is 25%+ over, "below" is 20%+ under, else "at".
- An experiment compares values of one lever. A value wins only with {evaluate.MIN_PER_ARM}+ scored videos
  per value and a 25% lead. "no_difference", "pending" and "too_few" mean nothing was learned yet:
  say so; do not read a trend into it.
- With fewer than {evaluate.MIN_BASELINE} earlier videos there is no baseline: the studio is calibrating.

# Rules for the plan (checked in code)
- Exactly the slots each day needs, at least {MIN_GAP_MINUTES} minutes apart, inside the post window.
  The suggested times are fine to use.
- A video in no experiment uses the default for every lever. A video in an experiment may differ only
  on that experiment's lever. At most {MAX_TESTS} levers under test per week; a new experiment needs
  {evaluate.MIN_PER_ARM} videos per value in this plan, ideally with the current default as one value.
- At most {round(cap * 100)}% of videos may differ from the defaults this week.
- Every video gets a prediction (above / at / below) - you are scored on these.
- {RESERVES} reserve topics, all on defaults, in case a video fails its checks.
- No topic may repeat anything from the last 60 days or another topic in the plan. Call check_topics
  before submitting.
- Conclude an experiment once its verdict is in (winner / no_difference / too_few with nothing more
  coming); abandon one that no longer makes sense.
- A belief may be "adopted" only when the experiments it cites found a winner with
  {model.ADOPT_MIN_VIDEOS_PER_ARM}+ videos per value across {model.ADOPT_MIN_WEEKS}+ weeks (code counts them). Until then
  it is "testing". Change a default only with an adopted belief about that lever.
- Answer every owner note in note_replies, and follow the owner's notes unless they break a hard rule.
- Stay within the weekly budget.

Submit with submit_plan. If it comes back with problems, fix all of them and resubmit the whole plan."""


def user_message(ctx: Context) -> str:
    running = [e for e in ctx.packet["experiments"] if e["status"] == "running"]
    context = {
        "plan_week": ctx.week,
        "days_to_plan": ctx.days,
        "post_window": ctx.studio["post_window"],
        "weekly_budget_usd": ctx.studio["weekly_budget_usd"],
        "estimated_cost_per_video": ctx.video_cost,
        "playbook": {"defaults": effective_defaults(ctx.studio, ctx.playbook), "beliefs": ctx.playbook.get("beliefs") or []},
        "running_experiments": running,
        "experiment_ids_already_used": [e["id"] for e in ctx.experiments],
        "results_packet": ctx.packet,
        "owner_notes": [{"note_id": n["id"], "text": n["text"]} for n in ctx.notes],
        "recent_topics": [t["text"] for t in ctx.recent[:MAX_RECENT_TOPICS]],
    }
    return "Plan the coming days. Everything you need:\n\n" + json.dumps(context, ensure_ascii=False, indent=1, default=str)


def planner_model(studio: dict) -> str:
    from app.services.animation import llm as anim_llm

    return studio.get("planner_model") or str(config.studios.get("planner_model", "") or "").strip() or anim_llm.model_for("writer")


def _client():
    from app.services.animation import llm as anim_llm

    client = anim_llm._client()
    if client is None:
        raise PlannerError("No OpenRouter key: the planner needs [app] openrouter_api_key (set on the Animation page's Models panel).")
    return client


def _call(client, model_name: str, messages: list[dict]):
    from app.services.animation import llm as anim_llm

    extra = {"usage": {"include": True}} if "openrouter" in str(getattr(client, "base_url", "")) else {}
    response = client.chat.completions.create(model=model_name, messages=messages, tools=TOOLS, extra_body=extra)
    return response, anim_llm._reported_cost(response)


def run(studio_id: str, today: date_cls | None = None, client=None, df=None, on_step=None) -> dict:
    """Plan the studio's coming days. Never raises: a failure is recorded on
    the timeline as an incident and returned as {"ok": False, "error"}."""
    today = today or date_cls.today()
    try:
        ctx = build_context(studio_id, today, df)
    except Exception as exc:
        error = f"{type(exc).__name__}: {exc}"
        logger.exception(f"studio {studio_id}: could not gather the planning context")
        store.append_event(studio_id, "incident", f"Planning failed before it started: {error}", {"stage": "plan"})
        return {"ok": False, "week": "", "error": error, "problems": [], "cost": 0.0}
    if not any(d["needed"] for d in ctx.days):
        return {"ok": True, "skipped": True, "week": ctx.week, "reason": "every slot in the coming days is already booked"}

    model_name = planner_model(ctx.studio)
    messages = [{"role": "system", "content": system_prompt(ctx)}, {"role": "user", "content": user_message(ctx)}]
    cost, failures, nudged, last_problems = 0.0, 0, False, []
    result = None
    try:
        client = client or _client()
        for _ in range(MAX_ROUNDS):
            response, spent = _call(client, model_name, messages)
            cost += spent
            message = response.choices[0].message
            calls = getattr(message, "tool_calls", None) or []
            if not calls:
                if nudged:
                    break
                messages.append({"role": "assistant", "content": message.content or ""})
                messages.append({"role": "user", "content": "Submit the plan now with submit_plan."})
                nudged = True
                continue
            messages.append(
                {
                    "role": "assistant",
                    "content": message.content or "",
                    "tool_calls": [{"id": c.id, "type": "function", "function": {"name": c.function.name, "arguments": c.function.arguments or "{}"}} for c in calls],
                }
            )
            for call in calls:
                try:
                    args = json.loads(call.function.arguments or "{}")
                except json.JSONDecodeError as exc:
                    args, bad_json = {}, str(exc)
                else:
                    bad_json = ""
                name = call.function.name
                if on_step:
                    on_step(name)
                if name == "check_topics":
                    content = json.dumps(topics.check([str(t) for t in args.get("topics") or []], ctx.recent), ensure_ascii=False)
                elif name == "submit_plan" and result is None:
                    clean, problems = check_plan(ctx, args)
                    if bad_json:
                        problems = [f"the arguments were not valid JSON: {bad_json}"]
                    if not problems:
                        try:
                            result = apply_plan(ctx, clean, {"planner_model": model_name, "planner_cost": round(cost, 4), "submissions": failures + 1})
                        except model.StudioError as exc:
                            problems = exc.problems
                    if problems:
                        failures += 1
                        last_problems = problems
                        content = json.dumps({"accepted": False, "problems": problems, "submissions_left": MAX_FAILED_SUBMITS - failures})
                    else:
                        content = json.dumps({"accepted": True})
                else:
                    content = f"Unknown tool {name!r}." if name != "submit_plan" else "The plan was already accepted."
                messages.append({"role": "tool", "tool_call_id": call.id, "content": content})
            if result or failures >= MAX_FAILED_SUBMITS:
                break
        if not result:
            reason = "it submitted no plan" if not failures else f"{failures} submissions were rejected"
            raise PlannerError(f"The planner gave up: {reason}.")
    except Exception as exc:
        error = str(exc) if isinstance(exc, PlannerError) else f"{type(exc).__name__}: {exc}"
        logger.warning(f"studio {studio_id} planning failed: {error}")
        store.append_event(
            studio_id, "incident", f"Planning failed: {error}",
            {"stage": "plan", "week": ctx.week, "problems": last_problems, "planner_model": model_name, "planner_cost": round(cost, 4)},
        )
        return {"ok": False, "week": ctx.week, "error": error, "problems": last_problems, "cost": round(cost, 4)}
    return {"ok": True, "week": ctx.week, "slots": result["slots"], "event": result["event"], "cost": round(cost, 4), "submissions": failures + 1}
