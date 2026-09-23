"""File-backed persistence for animation projects.

Each project lives in storage/animation/<project_id>/:

    project.json     - topic, context, length, aspect, voice, status, progress,
                       costs, YouTube metadata, manual "already posted" mark
    storyboard.json  - the LLM's storyboard (narration + staging by scene)
    public/          - Remotion's public dir for this render (narration.mp3)
    words.json       - word timings from TTS (drive captions and action cues)
    story.json       - the compiled Remotion story (props for PaperStory)
    final.mp4        - the rendered video
    thumb.jpg        - a frame for the library card / YouTube thumbnail
"""

import json
import os
import re
import shutil
import threading
import time
import uuid

from app.utils import utils

STATUS_QUEUED = "queued"
STATUS_WRITING = "writing"  # storyboard
STATUS_VOICING = "voicing"  # TTS
STATUS_RENDERING = "rendering"
STATUS_PACKAGING = "packaging"  # YouTube metadata
STATUS_DONE = "done"
STATUS_FAILED = "failed"

RUNNING_STATUSES = (STATUS_WRITING, STATUS_VOICING, STATUS_RENDERING, STATUS_PACKAGING)
ASPECTS = ("9:16", "16:9")

_write_lock = threading.RLock()


def animation_dir() -> str:
    return utils.storage_dir("animation", create=True)


def _slugify(text: str, max_length: int = 40) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", (text or "").lower()).strip("-")
    return slug[:max_length].rstrip("-") or "video"


def project_dir(project_id: str) -> str:
    if not re.fullmatch(r"[A-Za-z0-9._-]+", project_id or ""):
        raise ValueError(f"invalid animation project id: {project_id!r}")
    return os.path.join(animation_dir(), project_id)


def path(project_id: str, name: str) -> str:
    return os.path.join(project_dir(project_id), name)


def public_dir(project_id: str) -> str:
    d = path(project_id, "public")
    os.makedirs(d, exist_ok=True)
    return d


def final_path(project_id: str) -> str:
    return path(project_id, "final.mp4")


def thumb_path(project_id: str) -> str:
    return path(project_id, "thumb.jpg")


def write_json(file_path: str, data) -> None:
    with _write_lock:
        os.makedirs(os.path.dirname(file_path), exist_ok=True)
        tmp = f"{file_path}.tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
        os.replace(tmp, file_path)


def read_json(file_path: str):
    try:
        with open(file_path, "r", encoding="utf-8") as f:
            return json.load(f)
    except (OSError, json.JSONDecodeError):
        return None


def create_project(
    topic: str,
    context: str = "",
    seconds: int = 30,
    aspect: str = "9:16",
    voice: str = "",
    source: str = "manual",
) -> dict:
    topic = (topic or "").strip()
    if not topic:
        raise ValueError("a topic is required")
    if aspect not in ASPECTS:
        raise ValueError(f"unsupported aspect ratio: {aspect!r}")
    seconds = int(seconds)
    if not 10 <= seconds <= 180:
        raise ValueError("length must be between 10 and 180 seconds")
    project_id = f"{time.strftime('%Y%m%d-%H%M%S')}-{_slugify(topic)}-{uuid.uuid4().hex[:6]}"
    project = {
        "project_id": project_id,
        "topic": topic,
        "context": (context or "").strip(),
        "seconds": seconds,
        "aspect": aspect,
        "voice": voice,
        "source": source,  # manual | schedule
        "status": STATUS_QUEUED,
        "stage": "Queued",
        "progress": 0.0,
        "error": "",
        "costs": {},
        "youtube": {},
        "posted": {},
        "created_at": time.time(),
        "updated_at": time.time(),
    }
    save_project(project)
    return project


def save_project(project: dict) -> None:
    project["updated_at"] = time.time()
    write_json(path(project["project_id"], "project.json"), project)


def load_project(project_id: str) -> dict | None:
    try:
        return read_json(path(project_id, "project.json"))
    except ValueError:
        return None


def update_project(project_id: str, **fields) -> dict:
    with _write_lock:
        project = load_project(project_id)
        if not project:
            raise KeyError(f"animation project not found: {project_id}")
        project.update(fields)
        save_project(project)
        return project


def add_cost(project_id: str, kind: str, amount: float) -> None:
    with _write_lock:
        project = load_project(project_id)
        if not project:
            return
        costs = project.setdefault("costs", {})
        costs[kind] = round(float(costs.get(kind, 0.0)) + float(amount or 0.0), 5)
        save_project(project)


def total_cost(project: dict) -> float:
    return round(sum(float(v or 0) for v in (project.get("costs") or {}).values()), 4)


def list_projects() -> list[dict]:
    root = animation_dir()
    projects = []
    for name in os.listdir(root):
        if name.startswith("_"):
            continue
        project = read_json(os.path.join(root, name, "project.json"))
        if isinstance(project, dict) and project.get("project_id"):
            projects.append(project)
    projects.sort(key=lambda p: p.get("created_at", 0), reverse=True)
    return projects


def finished_projects() -> list[dict]:
    return [p for p in list_projects() if p.get("status") == STATUS_DONE and os.path.isfile(final_path(p["project_id"]))]


def delete_project(project_id: str) -> None:
    shutil.rmtree(project_dir(project_id), ignore_errors=True)


def mark_posted(project_id: str, url: str = "", posted_on: str = "") -> dict:
    """Record that the owner uploaded this video themselves."""
    posted = {"manual": True, "url": (url or "").strip(), "date": posted_on or time.strftime("%Y-%m-%d"), "at": time.time()}
    return update_project(project_id, posted=posted)


def unmark_posted(project_id: str) -> dict:
    return update_project(project_id, posted={})
