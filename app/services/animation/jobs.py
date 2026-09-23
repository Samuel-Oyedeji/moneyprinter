"""Background generation queue for the Animation page.

Batch runs take minutes per video, far longer than a Streamlit script run,
so projects go into a module-level queue served by one worker thread (one
render at a time: each render already uses every CPU core). The queue lives
in this process; project state lives on disk, so after an app restart
`recover()` re-queues what was waiting and flags what was cut off mid-run.
Each queued project records the owning process id, so a second app process
(e.g. two web UIs on one machine) never picks up work that is still owned
by a live one.
"""

import os
import threading
import time
from collections import deque

from loguru import logger

from app.services.animation import pipeline, store

STALE_SECONDS = 15 * 60  # a running project silent this long was interrupted

_cond = threading.Condition()
_queue: deque[str] = deque()
_current: dict = {"id": None}
_worker: dict = {"thread": None}


def enqueue(project_ids: list[str]) -> None:
    with _cond:
        for pid in project_ids:
            if pid in _queue or pid == _current["id"]:
                continue
            store.update_project(pid, status=store.STATUS_QUEUED, stage="Queued", error="", worker_pid=os.getpid())
            _queue.append(pid)
        _cond.notify_all()
        thread = _worker["thread"]
        if thread is None or not thread.is_alive():
            thread = threading.Thread(target=_loop, daemon=True, name="animation-worker")
            _worker["thread"] = thread
            thread.start()


def _loop() -> None:
    while True:
        with _cond:
            if not _queue:
                _cond.wait(timeout=60)
            if not _queue:
                _worker["thread"] = None
                return
            pid = _queue.popleft()
            _current["id"] = pid
        try:
            logger.info(f"animation worker: starting {pid}")
            pipeline.run_project(pid)
        except Exception:
            logger.exception(f"animation worker: {pid} crashed")
        finally:
            with _cond:
                _current["id"] = None


def snapshot() -> dict:
    with _cond:
        return {"current": _current["id"], "queued": list(_queue)}


def is_active(project_id: str) -> bool:
    snap = snapshot()
    return project_id == snap["current"] or project_id in snap["queued"]


def _alive(pid) -> bool:
    try:
        os.kill(int(pid), 0)
        return True
    except (ProcessLookupError, ValueError, TypeError):
        return False
    except PermissionError:
        return True


def recover() -> None:
    """After a restart: re-queue waiting manual projects, fail stuck ones."""
    snap = snapshot()
    waiting = []
    for project in store.list_projects():
        pid = project["project_id"]
        if pid == snap["current"] or pid in snap["queued"] or project.get("source") != "manual":
            continue
        owner = project.get("worker_pid")
        if owner and owner != os.getpid() and _alive(owner):
            continue  # another live app process owns it
        if project.get("status") == store.STATUS_QUEUED:
            waiting.append(pid)
        elif project.get("status") in store.RUNNING_STATUSES and (owner or time.time() - project.get("updated_at", 0) > STALE_SECONDS):
            # its owner is gone (or never recorded and silent too long)
            store.update_project(pid, status=store.STATUS_FAILED, error="Interrupted (the app restarted mid-run) — press Retry to resume.")
    if waiting:
        waiting.reverse()  # list_projects is newest-first; keep creation order
        enqueue(waiting)
