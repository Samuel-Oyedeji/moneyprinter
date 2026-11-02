"""The studio tick: everything a studio does on its own, run hourly by cron.

``POST /api/v1/studios/tick`` calls tick(). Each tick does only what is due,
so running it often is cheap and running it twice is harmless (one lock):

    sync      refresh channel analytics if the last sync is 20+ hours old
    plan      Sundays (and a studio's very first tick): plan the coming days
    recover   slots a crash left "producing" or "uploading" get picked up
    missed    planned videos whose time passed 6+ hours ago are dropped
    upload    ready videos whose slot is 90 minutes away or less, once the
              owner's cancel window (veto_hours since it was ready) is over
    produce   planned videos due within 36 hours (or veto_hours + 7.5h):
              pipeline → QA → ready; a failed check gets one fix, then the
              slot goes to a reserve topic
    upload    again, for anything that became due while producing
    check-in  3 and 7 days after publishing, record the video's numbers

Nothing happens while [studios] enabled is false, [studios] paused is true,
or the studio itself is paused. Every failure is a timeline incident, and
notify.py sends Discord alerts at the end of each tick plus a daily digest.

Only one tick runs at a time across processes too (a file lock): the web
UI's "Run a tick now" and the cron hook never produce the same slot twice.
"""

import os
import threading
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone

from loguru import logger

from app.config import config
from app.services.studios import evaluate, model, notify, planner, qa, store, topics

try:
    import fcntl
except ImportError:  # Windows: one process at a time is up to the owner
    fcntl = None

UPLOAD_LEAD = timedelta(minutes=90)
PUBLISH_MIN_LEAD = timedelta(minutes=15)
PRODUCE_HORIZON = timedelta(hours=36)
PRODUCE_MARGIN = timedelta(hours=6)  # time to make a video before its cancel window starts
MISSED_AFTER = timedelta(hours=6)
MAX_ATTEMPTS = 2
MAX_UPLOAD_ATTEMPTS = 3
SYNC_EVERY = timedelta(hours=20)
CHECKINS = (("3d", 3), ("7d", 7))
CHECKIN_GRACE = timedelta(days=3)  # stop waiting for a check-in's numbers after this
QA_FIX_STAGES = {"render": "render", "voice": "voice", "script": "script", "package": "package"}

_tick_lock = threading.Lock()


# -------------------------------------------------------------------- time
def local_tz():
    name = str(config.youtube.get("publish_timezone", "") or "")
    if name:
        try:
            from zoneinfo import ZoneInfo

            return ZoneInfo(name)
        except Exception:
            logger.warning(f"invalid youtube.publish_timezone {name!r}; using server time")
    return datetime.now().astimezone().tzinfo


def slot_utc(slot: dict) -> datetime:
    naive = datetime.strptime(f"{slot['date']} {slot['time']}", "%Y-%m-%d %H:%M")
    return naive.replace(tzinfo=local_tz()).astimezone(timezone.utc)


def local_date(moment: datetime):
    return moment.astimezone(local_tz()).date()


def _ts_date(ts: float):
    return local_date(datetime.fromtimestamp(ts, timezone.utc))


def _iso(moment: datetime) -> str:
    return moment.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _incident_once_a_day(studio_id: str, key: str, summary: str, now: datetime, data: dict | None = None) -> None:
    """An incident that would repeat every tick (budget reached, YouTube not
    connected) is logged once a day."""
    today = local_date(now).isoformat()
    for event in store.list_events(studio_id, limit=200, types=("incident",)):
        found = event.get("data") or {}
        if found.get("key") == key and found.get("day") == today:
            return
    store.append_event(studio_id, "incident", summary, {"key": key, "day": today, **(data or {})})


def upload_after(studio: dict, slot: dict) -> datetime:
    """When a ready video may upload: 90 minutes before its slot, and not
    before the cancel window is over (unless the owner approved it)."""
    lead = slot_utc(slot) - UPLOAD_LEAD
    if slot.get("veto_waived") or not slot.get("ready_at"):
        return lead
    return max(lead, datetime.fromtimestamp(slot["ready_at"] + studio["veto_hours"] * 3600, timezone.utc))


@contextmanager
def _tick_guard():
    """Yield True when this caller holds the tick (thread and file lock)."""
    if not _tick_lock.acquire(blocking=False):
        yield False
        return
    handle = None
    try:
        if fcntl is not None:
            handle = open(os.path.join(store.studios_dir(), ".tick.lock"), "a")
            try:
                fcntl.flock(handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
            except BlockingIOError:
                yield False
                return
        yield True
    finally:
        if handle is not None:
            handle.close()
        _tick_lock.release()


def is_running() -> bool:
    """Whether a tick is running in any process."""
    with _tick_guard() as free:
        return not free


def _title(project: dict | None, slot: dict) -> str:
    return ((project or {}).get("youtube") or {}).get("title") or slot["brief"].get("topic", "")


# -------------------------------------------------------------------- tick
def tick(now: datetime | None = None, client=None, probe_fn=None, reload: bool = True) -> dict:
    """One pass over every studio. Never raises."""
    if reload:
        config.reload_config()  # the web UI may have changed [studios] in another process
    if not config.studios.get("enabled", False):
        return {"ran": False, "reason": "studios are disabled ([studios] enabled = false)"}
    if config.studios.get("paused", False):
        return {"ran": False, "reason": "every studio is paused ([studios] paused = true)"}
    with _tick_guard() as mine:
        if not mine:
            return {"ran": False, "reason": "a tick is already running"}
        clock = None if now else (lambda: datetime.now(timezone.utc))
        now = now or clock()
        _sync_analytics(now)
        results = {}
        for studio in store.list_studios():
            if studio.get("paused"):
                results[studio["id"]] = {"paused": True}
                continue
            try:
                results[studio["id"]] = run_studio(studio, now, client, probe_fn or qa.probe, clock)
            except Exception as exc:
                logger.exception(f"studio {studio['id']}: tick failed")
                store.append_event(studio["id"], "incident", f"The tick failed: {type(exc).__name__}: {exc}", {"stage": "tick"})
                results[studio["id"]] = {"error": f"{type(exc).__name__}: {exc}"}
            _quietly(notify.flush, studio, now)
        _quietly(notify.send_digest, now)
        _quietly(notify.record_tick, now)
        return {"ran": True, "at": _iso(now), "studios": results}


def _quietly(action, *args) -> None:
    """Notifications are best-effort: they never fail a tick."""
    try:
        action(*args)
    except Exception:
        logger.exception(f"studios: {getattr(action, '__name__', action)} failed")


def _sync_analytics(now: datetime) -> None:
    try:
        from app.services.analytics import store as analytics_store
        from app.services.analytics import sync, youtube_api

        last = float(analytics_store.load_sync_status().get("finished_at") or 0)
        if now.timestamp() - last < SYNC_EVERY.total_seconds() or not youtube_api.readiness()[0]:
            return
        sync.run(fetch_metrics=True, categorize_topics=False)
    except Exception:
        logger.exception("studios: analytics sync failed; carrying on")


def run_studio(studio: dict, now: datetime, client=None, probe_fn=qa.probe, clock=None) -> dict:
    """``clock`` gives the real time after production, which can take a
    while; without one (tests, a fixed ``now``) time stands still."""
    result = {
        "plan": maybe_plan(studio, now, client),
        "recovered": recover(studio),
        "missed": mark_missed(studio, now),
        "uploaded": upload_due(studio, now),
    }
    result["produced"] = produce_due(studio, now, client, probe_fn)
    result["uploaded"] += upload_due(studio, clock() if clock else now)
    result["checkins"] = record_checkins(studio, now)
    return result


# -------------------------------------------------------------------- plan
def maybe_plan(studio: dict, now: datetime, client=None) -> dict | None:
    """Plan on Sundays, and on a studio's first tick; one attempt a day."""
    today = local_date(now)
    first_time = not store.list_events(studio["id"], limit=1, types=("plan",))
    if today.weekday() != 6 and not first_time:
        return None
    for event in store.list_events(studio["id"], limit=200, types=("plan", "incident")):
        if _ts_date(event["ts"]) == today and (event["type"] == "plan" or (event.get("data") or {}).get("stage") == "plan"):
            return None
    result = planner.run(studio["id"], today=today, client=client)
    return {k: result.get(k) for k in ("ok", "week", "skipped", "error", "cost")}


# ---------------------------------------------------------- recover/missed
def recover(studio: dict) -> list[str]:
    """Only the tick produces and uploads, under its lock, so a slot found
    mid-way at the start of a tick was cut off by a restart."""
    from app.services.animation import store as anim_store

    fixed = []
    for slot in store.load_queue(studio["id"]):
        if slot["status"] == model.SLOT_PRODUCING:
            store.update_slot(studio["id"], slot["id"], status=model.SLOT_PLANNED, error="interrupted while producing")
            fixed.append(slot["id"])
        elif slot["status"] == model.SLOT_UPLOADING:
            project = anim_store.load_project(slot["project_id"]) if slot.get("project_id") else None
            video_id = (project or {}).get("youtube_video_id")
            if video_id:  # it went up before the restart: never upload twice
                store.update_slot(
                    studio["id"], slot["id"], status=model.SLOT_UPLOADED, youtube_video_id=video_id,
                    publish_at=(project or {}).get("publish_at", ""), uploaded_at=(project or {}).get("uploaded_at", 0),
                )
            else:
                store.update_slot(studio["id"], slot["id"], status=model.SLOT_READY, error="interrupted while uploading")
            fixed.append(slot["id"])
    return fixed


def mark_missed(studio: dict, now: datetime) -> list[str]:
    missed = []
    for slot in store.load_queue(studio["id"]):
        if slot["status"] == model.SLOT_PLANNED and not slot["reserve"] and slot_utc(slot) + MISSED_AFTER < now:
            store.update_slot(studio["id"], slot["id"], status=model.SLOT_FAILED, error="missed: never produced in time")
            store.append_event(
                studio["id"], "incident", f"Missed {slot['date']} {slot['time']}: \"{slot['brief']['topic']}\" was never produced in time.",
                {"stage": "produce", "slot_id": slot["id"]},
            )
            missed.append(slot["id"])
    return missed


# ----------------------------------------------------------------- produce
def _over_budget(studio: dict, now: datetime) -> bool:
    queue = store.load_queue(studio["id"])
    costs = evaluate.production_costs(studio, queue)
    spent = evaluate.spend(queue, costs, local_date(now), evaluate.planner_spend(studio["id"]))["this_week"]
    known = sorted(c for c in costs.values() if c)
    estimate = known[len(known) // 2] if known else planner.DEFAULT_VIDEO_COST
    return spent + estimate > studio["weekly_budget_usd"]


def produce_due(studio: dict, now: datetime, client=None, probe_fn=qa.probe) -> list[dict]:
    horizon = max(PRODUCE_HORIZON, timedelta(hours=studio["veto_hours"]) + UPLOAD_LEAD + PRODUCE_MARGIN)
    due = sorted(
        (s for s in store.load_queue(studio["id"]) if s["status"] == model.SLOT_PLANNED and not s["reserve"] and slot_utc(s) - now <= horizon),
        key=slot_utc,
    )
    results = []
    for slot in due:
        if _over_budget(studio, now):
            _incident_once_a_day(
                studio["id"], "budget", f"The weekly budget (${studio['weekly_budget_usd']}) is used up; production waits for next week.",
                now, {"stage": "produce"},
            )
            break
        try:
            results.append(produce_slot(studio, slot, now, client, probe_fn))
        except Exception as exc:
            logger.exception(f"studio {studio['id']}: producing {slot['id']} crashed")
            current = store.get_slot(studio["id"], slot["id"]) or slot
            _retry_or_replace(studio, current, now, f"{type(exc).__name__}: {exc}")
            results.append({"slot_id": slot["id"], "status": "error"})
    return results


def _new_project(studio: dict, slot: dict) -> str:
    from app.services.animation import store as anim_store

    options = studio.get("pipeline_options") or {}
    project = anim_store.create_project(
        topic=slot["brief"]["topic"],
        seconds=int(slot["brief"].get("length") or 30),
        aspect=options.get("aspect") or "9:16",
        voice=options.get("voice") or "",
        source="studio",
        brief=slot["brief"],
        studio={"studio_id": studio["id"], "slot_id": slot["id"], "week": slot["week"], "experiment": slot["experiment"], "arm": slot["arm"]},
    )
    store.update_slot(studio["id"], slot["id"], project_id=project["project_id"])
    return project["project_id"]


def produce_slot(studio: dict, slot: dict, now: datetime, client=None, probe_fn=qa.probe) -> dict:
    """Make one video and check it. Ends ready, back to planned (a retry on
    the next tick) or failed with a reserve taking its place."""
    from app.services.animation import pipeline
    from app.services.animation import store as anim_store

    sid = studio["id"]
    slot = store.update_slot(sid, slot["id"], status=model.SLOT_PRODUCING, attempts=slot["attempts"] + 1, error="")
    pid = slot["project_id"] if slot["project_id"] and anim_store.load_project(slot["project_id"]) else _new_project(studio, slot)
    recent = topics.recent_topics(today=local_date(now))
    ask = qa.default_ask(planner.planner_model(studio), client)

    report = {}
    for round_number in range(2):  # the first try, then one fix
        project = pipeline.run_project(pid)
        if project.get("status") != anim_store.STATUS_DONE:
            return _retry_or_replace(studio, store.get_slot(sid, slot["id"]), now, f"generation failed: {project.get('error', '')[:300]}")
        report = qa.run(studio, slot, project, recent, ask, probe_fn)
        if report["cost"]:
            anim_store.add_cost(pid, "qa", report["cost"])
        if report["ok"]:
            store.update_slot(sid, slot["id"], status=model.SLOT_READY, ready_at=now.timestamp(), qa=report)
            store.append_event(
                sid, "produced",
                f"Ready: \"{_title(project, slot)}\" for {slot['date']} {slot['time']}. It uploads once the {studio['veto_hours']:g}h cancel window is over.",
                {"slot_id": slot["id"], "project_id": pid},
            )
            return {"slot_id": slot["id"], "status": "ready"}
        fix = report["fix"]
        if round_number == 0 and fix in QA_FIX_STAGES:
            store.append_event(
                sid, "qa_failed", f"\"{slot['brief']['topic']}\": {qa.summary(report)}. Fixing ({fix}) and checking again.",
                {"slot_id": slot["id"], "fix": fix, "checks": report["checks"], "retry": True},
            )
            pipeline.reset_from(pid, QA_FIX_STAGES[fix])
            continue
        break

    store.update_slot(sid, slot["id"], qa=report)
    store.append_event(
        sid, "qa_failed", f"\"{slot['brief']['topic']}\": {qa.summary(report)}. Dropped.",
        {"slot_id": slot["id"], "fix": report.get("fix"), "checks": report.get("checks"), "retry": False},
    )
    return _replace(studio, store.get_slot(sid, slot["id"]), now, f"failed QA: {qa.summary(report)[:300]}")


def _retry_or_replace(studio: dict, slot: dict, now: datetime, reason: str) -> dict:
    if slot["attempts"] < MAX_ATTEMPTS and slot_utc(slot) + MISSED_AFTER > now:
        store.update_slot(studio["id"], slot["id"], status=model.SLOT_PLANNED, error=reason)
        store.append_event(
            studio["id"], "incident", f"\"{slot['brief']['topic']}\": {reason}. Retrying on the next tick.",
            {"stage": "produce", "slot_id": slot["id"]},
        )
        return {"slot_id": slot["id"], "status": "retry"}
    return _replace(studio, slot, now, reason)


def _replace(studio: dict, slot: dict, now: datetime, reason: str) -> dict:
    """Drop the slot's video; the first reserve topic takes its date and time."""
    sid = studio["id"]
    store.update_slot(sid, slot["id"], status=model.SLOT_FAILED, error=reason)
    reserve = next((s for s in store.load_queue(sid) if s["reserve"] and s["status"] == model.SLOT_PLANNED), None)
    if reserve and slot_utc(slot) + MISSED_AFTER > now:
        store.update_slot(sid, reserve["id"], date=slot["date"], time=slot["time"], week=slot["week"])
        summary = f"Dropped \"{slot['brief']['topic']}\" ({reason}). Reserve \"{reserve['brief']['topic']}\" takes {slot['date']} {slot['time']}."
    else:
        summary = f"Dropped \"{slot['brief']['topic']}\" ({reason}). No reserve left: {slot['date']} {slot['time']} stays empty."
    store.append_event(sid, "incident", summary, {"stage": "produce", "slot_id": slot["id"], "reserve_id": (reserve or {}).get("id", "")})
    return {"slot_id": slot["id"], "status": "failed", "reserve_id": (reserve or {}).get("id", "")}


# ------------------------------------------------------------------ upload
def upload_due(studio: dict, now: datetime) -> list[dict]:
    from app.services import youtube_upload

    due = [s for s in store.load_queue(studio["id"]) if s["status"] == model.SLOT_READY and now >= upload_after(studio, s)]
    if not due:
        return []
    if not youtube_upload.youtube_upload_service.is_configured():
        _incident_once_a_day(studio["id"], "youtube", "Videos are ready but YouTube uploads aren't set up (youtube.enabled + token).", now, {"stage": "upload"})
        return []
    return [upload_slot(studio, slot, now) for slot in sorted(due, key=slot_utc)]


def upload_slot(studio: dict, slot: dict, now: datetime) -> dict:
    from app.services.animation import schedule as anim_schedule
    from app.services.animation import store as anim_store

    sid = studio["id"]
    slot = store.update_slot(sid, slot["id"], status=model.SLOT_UPLOADING, upload_attempts=slot["upload_attempts"] + 1)
    publish = max(slot_utc(slot), now + PUBLISH_MIN_LEAD)
    project = anim_store.load_project(slot["project_id"])
    try:
        if not project:
            raise RuntimeError(f"project {slot['project_id']} is gone from disk")
        video_id = anim_schedule.upload_project(project, _iso(publish))
    except Exception as exc:
        error = f"upload failed: {exc}"[:500]
        final = slot["upload_attempts"] >= MAX_UPLOAD_ATTEMPTS
        store.update_slot(sid, slot["id"], status=model.SLOT_FAILED if final else model.SLOT_READY, error=error)
        store.append_event(
            sid, "incident", f"\"{_title(project, slot)}\": {error}" + (" Giving up." if final else " Retrying next tick."),
            {"stage": "upload", "slot_id": slot["id"]},
        )
        return {"slot_id": slot["id"], "status": "failed" if final else "retry"}
    store.update_slot(
        sid, slot["id"], status=model.SLOT_UPLOADED, youtube_video_id=video_id, publish_at=_iso(publish), uploaded_at=now.timestamp(), error=""
    )
    when = publish.astimezone(local_tz()).strftime("%a %d %b %H:%M")
    store.append_event(
        sid, "uploaded", f"Uploaded \"{_title(anim_store.load_project(slot['project_id']), slot)}\"; it goes public {when}.",
        {"slot_id": slot["id"], "video_id": video_id, "url": f"https://youtu.be/{video_id}", "publish_at": _iso(publish)},
    )
    return {"slot_id": slot["id"], "status": "uploaded", "video_id": video_id}


# ---------------------------------------------------------------- check-in
def _published(slot: dict) -> datetime | None:
    try:
        return datetime.strptime(slot["publish_at"], "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc)
    except (KeyError, ValueError):
        return None


def record_checkins(studio: dict, now: datetime, df=None) -> list[dict]:
    """3 and 7 days after publishing (plus a day for the numbers to land),
    write the video's numbers on its slot and the timeline."""
    queue = store.load_queue(studio["id"])
    pending = []
    for slot in queue:
        published = _published(slot) if slot["status"] == model.SLOT_UPLOADED else None
        for name, days in CHECKINS:
            if published and name not in slot["checkins"] and now >= published + timedelta(days=days + 1):
                pending.append((slot, name, published + timedelta(days=days + 1)))
    if not pending:
        return []
    if df is None:
        from app.services.analytics import report

        df = report.build_dataset()
    videos = {v["slot_id"]: v for v in evaluate.score_videos(queue, df, studio["pipeline"])}
    done = []
    for slot, name, due in pending:
        video = videos.get(slot["id"]) or {}
        views = video.get("views_3d" if name == "3d" else "views_7d")
        if views is None and now < due + CHECKIN_GRACE:
            continue  # the numbers may still come
        checkin = {"views": views, "state": video.get("state", "not on the channel"), "at": now.timestamp()}
        title = video.get("title") or slot["brief"]["topic"]
        if views is None:
            summary = f"{name} check-in: \"{title}\" has no numbers ({checkin['state']})."
        else:
            summary = f"{name} check-in: \"{title}\" has {int(views):,} views"
            if name == "3d" and video.get("score") is not None:
                checkin.update(
                    score=video["score"], outcome=video["outcome"], vs_baseline_pct=video["vs_baseline_pct"],
                    prediction=slot["prediction"], prediction_hit=video["prediction_hit"],
                )
                summary += f", {video['vs_baseline_pct']:+d}% vs baseline ({video['outcome']}; predicted {slot['prediction'] or 'nothing'})"
            summary += "."
        latest = store.get_slot(studio["id"], slot["id"])
        store.update_slot(studio["id"], slot["id"], checkins={**latest["checkins"], name: checkin})
        store.append_event(studio["id"], "result", summary, {"kind": "checkin", "slot_id": slot["id"], "checkin": name, **checkin})
        done.append({"slot_id": slot["id"], "checkin": name})
    return done
