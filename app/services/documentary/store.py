"""File-backed persistence for documentary projects.

Documentary projects pause at human review checkpoints, potentially for days,
so state lives on disk under storage/documentary/<project_id>/ rather than in
the in-memory/Redis task state used by the short-form pipeline. Each project
directory holds:

    project.json    - status, topic, user notes, timestamps, approval flags
    sources.json    - fetched web sources (url, title, extracted text)
    factsheet.json  - the sourced fact sheet awaiting/after review
    script.json     - the generated script awaiting/after review
"""

import json
import os
import re
import threading
import time
import uuid

from app.utils import utils

# Status flow. Review states are the human checkpoints; each has a matching
# auto_approve flag on the project so the pause can be switched off later.
STATUS_CREATED = "created"
STATUS_RESEARCHING = "researching"
STATUS_FACTSHEET_REVIEW = "factsheet_review"
STATUS_SCRIPTING = "scripting"
STATUS_SCRIPT_REVIEW = "script_review"
STATUS_SCRIPT_APPROVED = "script_approved"
STATUS_SOURCING_IMAGES = "sourcing_images"
STATUS_IMAGE_REVIEW = "image_review"
STATUS_RENDERING = "rendering"
STATUS_DONE = "done"
STATUS_FAILED = "failed"

_write_lock = threading.RLock()


def documentary_dir(sub_dir: str = "") -> str:
    d = utils.storage_dir("documentary", create=True)
    if sub_dir:
        d = os.path.join(d, sub_dir)
        os.makedirs(d, exist_ok=True)
    return d


def _slugify(text: str, max_length: int = 40) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", (text or "").lower()).strip("-")
    return slug[:max_length].rstrip("-") or "project"


def new_project_id(topic: str) -> str:
    # Timestamp prefix keeps directory listings chronological; the uuid suffix
    # avoids collisions when the same topic is created twice.
    stamp = time.strftime("%Y%m%d-%H%M%S")
    return f"{stamp}-{_slugify(topic)}-{uuid.uuid4().hex[:6]}"


def project_dir(project_id: str) -> str:
    # Project ids become directory names; reject anything path-like. Do not
    # create the directory here — read paths (load/list after delete) must
    # not resurrect empty project directories.
    if not re.fullmatch(r"[A-Za-z0-9._-]+", project_id or ""):
        raise ValueError(f"invalid documentary project id: {project_id!r}")
    return os.path.join(documentary_dir(), project_id)


def _json_path(project_id: str, name: str) -> str:
    return os.path.join(project_dir(project_id), f"{name}.json")


def _write_json(path: str, data) -> None:
    # Atomic replace so a crash mid-write never leaves a truncated JSON file
    # that would brick the review page for that project.
    with _write_lock:
        os.makedirs(os.path.dirname(path), exist_ok=True)
        tmp_path = f"{path}.tmp"
        with open(tmp_path, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
        os.replace(tmp_path, path)


def _read_json(path: str):
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except (OSError, json.JSONDecodeError):
        return None


def create_project(
    topic: str,
    user_notes: str = "",
    language: str = "en",
    auto_approve_factsheet: bool = False,
    auto_approve_script: bool = False,
    auto_approve_images: bool = False,
) -> dict:
    project_id = new_project_id(topic)
    project = {
        "project_id": project_id,
        "topic": (topic or "").strip(),
        "user_notes": (user_notes or "").strip(),
        "language": language,
        "status": STATUS_CREATED,
        "error": "",
        "auto_approve_factsheet": bool(auto_approve_factsheet),
        "auto_approve_script": bool(auto_approve_script),
        "auto_approve_images": bool(auto_approve_images),
        "created_at": time.time(),
        "updated_at": time.time(),
    }
    _write_json(_json_path(project_id, "project"), project)
    return project


def load_project(project_id: str) -> dict | None:
    return _read_json(_json_path(project_id, "project"))


def save_project(project: dict) -> None:
    project["updated_at"] = time.time()
    _write_json(_json_path(project["project_id"], "project"), project)


def set_status(project: dict, status: str, error: str = "") -> None:
    project["status"] = status
    project["error"] = error
    save_project(project)


def list_projects() -> list[dict]:
    projects = []
    base = documentary_dir()
    for name in os.listdir(base):
        project = _read_json(os.path.join(base, name, "project.json"))
        if project:
            projects.append(project)
    projects.sort(key=lambda p: p.get("created_at", 0), reverse=True)
    return projects


def delete_project(project_id: str) -> None:
    import shutil

    shutil.rmtree(project_dir(project_id), ignore_errors=True)


def save_sources(project_id: str, sources: list[dict]) -> None:
    _write_json(_json_path(project_id, "sources"), sources)


def load_sources(project_id: str) -> list[dict]:
    return _read_json(_json_path(project_id, "sources")) or []


def save_factsheet(project_id: str, factsheet: dict) -> None:
    _write_json(_json_path(project_id, "factsheet"), factsheet)


def load_factsheet(project_id: str) -> dict | None:
    return _read_json(_json_path(project_id, "factsheet"))


def save_script(project_id: str, script: dict) -> None:
    _write_json(_json_path(project_id, "script"), script)


def load_script(project_id: str) -> dict | None:
    return _read_json(_json_path(project_id, "script"))


def save_images(project_id: str, images: dict) -> None:
    _write_json(_json_path(project_id, "images"), images)


def load_images(project_id: str) -> dict | None:
    return _read_json(_json_path(project_id, "images"))


def images_dir(project_id: str) -> str:
    d = os.path.join(project_dir(project_id), "images")
    os.makedirs(d, exist_ok=True)
    return d


def audio_dir(project_id: str) -> str:
    d = os.path.join(project_dir(project_id), "audio")
    os.makedirs(d, exist_ok=True)
    return d


def render_dir(project_id: str) -> str:
    d = os.path.join(project_dir(project_id), "render")
    os.makedirs(d, exist_ok=True)
    return d
