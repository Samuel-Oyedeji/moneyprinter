"""File-backed state for studios: storage/studios/<studio_id>/.

    studio.json     the owner's rules (model.validate_studio)
    playbook.json   the agent's defaults and beliefs (model.validate_playbook)
    queue.json      upload slots and reserve topics (model.validate_slot)
    experiments.json  the agent's tests (model.validate_experiment)
    timeline.jsonl  one event per line, append-only
    notes.json      the owner's notes to the agent, with a read mark

The web UI and the API (which runs the studio tick) are separate processes
in Docker, and both edit a studio's queue: the owner cancels a ready video
while the tick may be about to upload it. Every read-modify-write therefore
holds a per-studio file lock (flock) as well as a thread lock.
"""

import json
import os
import threading
import time
import uuid
from contextlib import contextmanager

from app.services.studios import model
from app.utils import utils

try:
    import fcntl
except ImportError:  # Windows: thread lock only
    fcntl = None

# Which status a slot may move to from each status.
TRANSITIONS = {
    model.SLOT_PLANNED: (model.SLOT_PRODUCING, model.SLOT_CANCELLED, model.SLOT_FAILED),
    model.SLOT_PRODUCING: (model.SLOT_READY, model.SLOT_PLANNED, model.SLOT_CANCELLED, model.SLOT_FAILED),
    model.SLOT_READY: (model.SLOT_UPLOADING, model.SLOT_CANCELLED),
    model.SLOT_UPLOADING: (model.SLOT_UPLOADED, model.SLOT_READY, model.SLOT_FAILED),
    model.SLOT_UPLOADED: (),
    model.SLOT_CANCELLED: (),
    model.SLOT_FAILED: (model.SLOT_PLANNED, model.SLOT_CANCELLED),
}

_thread_locks: dict[str, threading.RLock] = {}
_thread_locks_guard = threading.Lock()
_held = threading.local()


def studios_dir() -> str:
    return utils.storage_dir("studios", create=True)


def studio_dir(studio_id: str) -> str:
    if not model.STUDIO_ID_RE.fullmatch(studio_id or ""):
        raise ValueError(f"invalid studio id: {studio_id!r}")
    return os.path.join(studios_dir(), studio_id)


def _path(studio_id: str, name: str) -> str:
    return os.path.join(studio_dir(studio_id), name)


@contextmanager
def locked(studio_id: str):
    """Hold the studio's thread lock and file lock (re-entrant per thread)."""
    with _thread_locks_guard:
        lock = _thread_locks.setdefault(studio_id, threading.RLock())
    with lock:
        depth = getattr(_held, studio_id.replace("-", "_"), 0)
        handle = None
        if depth == 0 and fcntl is not None:
            os.makedirs(studio_dir(studio_id), exist_ok=True)
            handle = open(_path(studio_id, ".lock"), "a")
            fcntl.flock(handle, fcntl.LOCK_EX)
        setattr(_held, studio_id.replace("-", "_"), depth + 1)
        try:
            yield
        finally:
            setattr(_held, studio_id.replace("-", "_"), depth)
            if handle is not None:
                fcntl.flock(handle, fcntl.LOCK_UN)
                handle.close()


def _write_json(file_path: str, data) -> None:
    os.makedirs(os.path.dirname(file_path), exist_ok=True)
    tmp = f"{file_path}.{os.getpid()}.tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    os.replace(tmp, file_path)


def _read_json(file_path: str, default):
    try:
        with open(file_path, "r", encoding="utf-8") as f:
            return json.load(f)
    except (OSError, json.JSONDecodeError):
        return default


# ------------------------------------------------------------------ studios
def list_studios() -> list[dict]:
    root = utils.storage_dir("studios")  # not created: the budget asks before any studio exists
    if not os.path.isdir(root):
        return []
    studios = []
    for name in sorted(os.listdir(root)):
        if model.STUDIO_ID_RE.fullmatch(name):
            studio = load_studio(name)
            if studio:
                studios.append(studio)
    return studios


def load_studio(studio_id: str) -> dict | None:
    return _read_json(_path(studio_id, "studio.json"), None)


def create_studio(data: dict) -> dict:
    studio = model.validate_studio(data)
    with locked(studio["id"]):
        if load_studio(studio["id"]):
            raise model.StudioError(f"studio {studio['id']!r} already exists")
        _write_json(_path(studio["id"], "studio.json"), studio)
        _write_json(_path(studio["id"], "playbook.json"), model.empty_playbook())
        _write_json(_path(studio["id"], "queue.json"), [])
        _write_json(_path(studio["id"], "notes.json"), [])
    return studio


def update_studio(studio_id: str, **fields) -> dict:
    """Change the owner's rules. The id and pipeline are fixed for life."""
    with locked(studio_id):
        current = load_studio(studio_id)
        if not current:
            raise KeyError(f"studio not found: {studio_id}")
        if "id" in fields or "pipeline" in fields:
            raise model.StudioError("a studio's id and pipeline cannot change")
        studio = model.validate_studio({**current, **fields})
        _write_json(_path(studio_id, "studio.json"), studio)
        changed = sorted(k for k in fields if current.get(k) != studio.get(k))
        if changed:
            append_event(studio_id, "settings", f"Changed: {', '.join(changed)}", {"fields": changed})
    return studio


def set_paused(studio_id: str, paused: bool) -> dict:
    return update_studio(studio_id, paused=bool(paused))


def _require(studio_id: str) -> dict:
    studio = load_studio(studio_id)
    if not studio:
        raise KeyError(f"studio not found: {studio_id}")
    return studio


# ----------------------------------------------------------------- playbook
def load_playbook(studio_id: str) -> dict:
    return _read_json(_path(studio_id, "playbook.json"), None) or model.empty_playbook()


def save_playbook(studio_id: str, playbook: dict) -> dict:
    with locked(studio_id):
        clean = model.validate_playbook(_require(studio_id), playbook)
        _write_json(_path(studio_id, "playbook.json"), clean)
    return clean


# -------------------------------------------------------------------- queue
def load_queue(studio_id: str) -> list[dict]:
    return _read_json(_path(studio_id, "queue.json"), [])


def get_slot(studio_id: str, slot_id: str) -> dict | None:
    return next((s for s in load_queue(studio_id) if s.get("id") == slot_id), None)


def counts_toward_budget(slot: dict) -> bool:
    return not slot.get("reserve") and slot.get("status") in model.BUDGET_STATUSES


def _check_room(studio_id: str, queue: list[dict], new_slots: list[dict]) -> list[str]:
    """Problems with booking new_slots: clashing times, full days."""
    from app.services import upload_budget

    problems = []
    taken = {(s["date"], s["time"]) for s in queue if counts_toward_budget(s)}
    per_day: dict[str, int] = {}
    for slot in new_slots:
        if slot["reserve"] or slot["status"] not in model.BUDGET_STATUSES:
            continue
        key = (slot["date"], slot["time"])
        if key in taken:
            problems.append(f"{slot['date']} {slot['time']} is already booked for this studio")
        taken.add(key)
        per_day[slot["date"]] = per_day.get(slot["date"], 0) + 1
    for day, count in sorted(per_day.items()):
        left = upload_budget.daily_load(day)["left"]
        if count > left:
            problems.append(f"{day} has {left} upload(s) left in the daily budget, {count} requested")
    return problems


def add_slots(studio_id: str, slots: list[dict]) -> list[dict]:
    """Validate and book slots (all or nothing)."""
    with locked(studio_id):
        studio = _require(studio_id)
        defaults = load_playbook(studio_id).get("defaults") or {}
        problems, clean = [], []
        for i, raw in enumerate(slots):
            try:
                slot = model.validate_slot(studio, {**raw, "status": model.SLOT_PLANNED}, defaults)
            except model.StudioError as exc:
                problems.extend(f"slot {i + 1}: {p}" for p in exc.problems)
                continue
            slot["id"] = uuid.uuid4().hex[:12]
            clean.append(slot)
        queue = load_queue(studio_id)
        if not problems:
            problems = _check_room(studio_id, queue, clean)
        if problems:
            raise model.StudioError(problems)
        _write_json(_path(studio_id, "queue.json"), queue + clean)
    return clean


def update_slot(studio_id: str, slot_id: str, **fields) -> dict:
    """Patch a slot. A status change must follow TRANSITIONS; a reserve
    given a date and time becomes a regular slot (it has to fit the day)."""
    with locked(studio_id):
        studio = _require(studio_id)
        queue = load_queue(studio_id)
        index = next((i for i, s in enumerate(queue) if s.get("id") == slot_id), None)
        if index is None:
            raise KeyError(f"slot not found: {slot_id}")
        current = queue[index]
        new_status = fields.get("status", current["status"])
        if new_status != current["status"] and new_status not in TRANSITIONS.get(current["status"], ()):
            raise model.StudioError(f"a {current['status']} slot cannot become {new_status}")
        merged = {**current, **fields}
        if current["reserve"] and fields.get("date") and fields.get("time"):
            merged["reserve"] = False
        slot = model.validate_slot(studio, merged, load_playbook(studio_id).get("defaults") or {})
        slot["id"], slot["created_at"] = current["id"], current["created_at"]
        if counts_toward_budget(slot) and not counts_toward_budget(current):
            others = queue[:index] + queue[index + 1 :]
            problems = _check_room(studio_id, others, [slot])
            if problems:
                raise model.StudioError(problems)
        queue[index] = slot
        _write_json(_path(studio_id, "queue.json"), queue)
    return slot


# -------------------------------------------------------------- experiments
def load_experiments(studio_id: str) -> list[dict]:
    return _read_json(_path(studio_id, "experiments.json"), [])


def save_experiment(studio_id: str, experiment: dict) -> dict:
    """Add an experiment, or replace the one with the same id."""
    with locked(studio_id):
        clean = model.validate_experiment(_require(studio_id), experiment)
        experiments = [e for e in load_experiments(studio_id) if e.get("id") != clean["id"]]
        _write_json(_path(studio_id, "experiments.json"), experiments + [clean])
    return clean


REVIEW_VERDICTS = ("good", "bad")


def review_slot(studio_id: str, slot_id: str, verdict: str, note: str = "") -> dict:
    """The owner's verdict on a finished video. A 👎 (and a 👍 with a
    comment) also becomes a note the agent reads at its next plan."""
    if verdict not in REVIEW_VERDICTS:
        raise model.StudioError(f"verdict must be one of {', '.join(REVIEW_VERDICTS)}")
    note = str(note or "").strip()
    if verdict == "bad" and not note:
        raise model.StudioError("say in a line what's wrong with it, so the studio can learn from it")
    with locked(studio_id):
        slot = get_slot(studio_id, slot_id)
        if not slot:
            raise KeyError(f"slot not found: {slot_id}")
        if slot["status"] not in (model.SLOT_READY, model.SLOT_UPLOADING, model.SLOT_UPLOADED):
            raise model.StudioError("only a finished video can be rated")
        slot = update_slot(studio_id, slot_id, owner_review={"verdict": verdict, "note": note, "at": time.time()})
        if verdict == "bad" or note:
            mark = "👎" if verdict == "bad" else "👍"
            add_note(studio_id, f"{mark} \"{slot['brief']['topic']}\" ({slot['date']} {slot['time']}): {note or 'good'}")
    return slot


def active_project_ids() -> set[str]:
    """Projects a studio still needs on disk (not uploaded, not dropped):
    the storage sweeper must leave them alone."""
    waiting = (model.SLOT_PLANNED, model.SLOT_PRODUCING, model.SLOT_READY, model.SLOT_UPLOADING)
    return {
        slot["project_id"]
        for studio in list_studios()
        for slot in load_queue(studio["id"])
        if slot.get("project_id") and slot.get("status") in waiting
    }


def daily_slot_count(day: str) -> int:
    """Uploads every studio has booked on a date (for upload_budget)."""
    return sum(
        1
        for studio in list_studios()
        for slot in load_queue(studio["id"])
        if slot.get("date") == day and counts_toward_budget(slot)
    )


# ----------------------------------------------------------------- timeline
def append_event(studio_id: str, event_type: str, summary: str, data: dict | None = None) -> dict:
    if event_type not in model.EVENT_TYPES:
        raise ValueError(f"unknown timeline event type {event_type!r}")
    event = {
        "id": uuid.uuid4().hex[:12],
        "ts": time.time(),
        "type": event_type,
        "summary": str(summary).strip(),
        "data": data or {},
    }
    with locked(studio_id):
        os.makedirs(studio_dir(studio_id), exist_ok=True)
        with open(_path(studio_id, "timeline.jsonl"), "a", encoding="utf-8") as f:
            f.write(json.dumps(event, ensure_ascii=False) + "\n")
    return event


def list_events(studio_id: str, limit: int | None = None, types: tuple[str, ...] | None = None) -> list[dict]:
    """Newest first. A line cut short by a crash mid-write is skipped."""
    events = []
    try:
        with open(_path(studio_id, "timeline.jsonl"), "r", encoding="utf-8") as f:
            for line in f:
                try:
                    event = json.loads(line)
                except json.JSONDecodeError:
                    continue
                if not types or event.get("type") in types:
                    events.append(event)
    except FileNotFoundError:
        return []
    events.reverse()
    return events[:limit] if limit else events


# -------------------------------------------------------------------- notes
def add_note(studio_id: str, text: str) -> dict:
    text = str(text or "").strip()
    if not text:
        raise model.StudioError("a note needs some text")
    note = {"id": uuid.uuid4().hex[:12], "ts": time.time(), "text": text, "read_at": 0}
    with locked(studio_id):
        _require(studio_id)
        notes = _read_json(_path(studio_id, "notes.json"), [])
        _write_json(_path(studio_id, "notes.json"), notes + [note])
        append_event(studio_id, "note", text, {"note_id": note["id"]})
    return note


def list_notes(studio_id: str, unread_only: bool = False) -> list[dict]:
    notes = _read_json(_path(studio_id, "notes.json"), [])
    return [n for n in notes if not (unread_only and n.get("read_at"))]


def mark_notes_read(studio_id: str, note_ids: list[str]) -> None:
    with locked(studio_id):
        notes = _read_json(_path(studio_id, "notes.json"), [])
        now = time.time()
        for note in notes:
            if note["id"] in note_ids and not note.get("read_at"):
                note["read_at"] = now
        _write_json(_path(studio_id, "notes.json"), notes)
