"""Everything the three studios produced, as one list of comparable items.

An item is one finished video the app made, whether or not it ever reached
YouTube:

    key              stable id: "animation:<project>", "documentary:<project>",
                     "shorts:<task>/<final-N.mp4>" (or "shorts:entry:<id>:<video>"
                     for old calendar uploads whose files are gone)
    studio           "shorts" | "documentary" | "animation"
    topic, label     what it is about / what to show it as
    titles           every title it could have been posted under, most
                     specific first (the generated YouTube title, the working
                     title, the topic): reconciliation matches on these
    created_at       epoch seconds the video was made (a channel video
                     published before this cannot be it)
    batch_id         shared by videos generated together ("" = single);
                     batch_inferred marks ids reconstructed for videos made
                     before batch ids were recorded
    known_video_ids  YouTube ids the app uploaded it as
    posted           {"manual", "url", "date"} when the owner marked it as
                     posted by hand
    features         the knobs worth comparing, as display strings
"""

import json
import os
from collections import Counter
from datetime import datetime
from glob import glob

from loguru import logger

from app.services.analytics import store as analytics_store
from app.utils import utils

STUDIOS = ("shorts", "documentary", "animation")
STUDIO_LABELS = {"shorts": "Shorts (stock footage)", "documentary": "Documentaries", "animation": "Animations"}

# Videos made within this many seconds of each other, with the same
# settings, came out of one batch form submit.
_BATCH_GAP_SECONDS = 5


def _epoch(value) -> float:
    if isinstance(value, (int, float)):
        return float(value)
    try:
        moment = datetime.fromisoformat(str(value))
    except ValueError:
        return 0.0
    return moment.timestamp()


def _dedupe(values) -> list[str]:
    return list(dict.fromkeys(v.strip() for v in values if isinstance(v, str) and v.strip()))


def _read_json(path: str):
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except (OSError, json.JSONDecodeError):
        return None


def _item(key: str, studio: str, topic: str, titles, created_at: float, **extra) -> dict:
    titles = _dedupe(titles)
    item = {
        "key": key,
        "studio": studio,
        "topic": (topic or "").strip(),
        "label": titles[0] if titles else (topic or key),
        "titles": titles,
        "created_at": created_at,
        "batch_id": "",
        "batch_inferred": False,
        "known_video_ids": [],
        "posted": {},
        "features": {},
    }
    item.update(extra)
    return item


def _infer_batches(items: list[dict], same_settings) -> None:
    """Give un-batched items made in one burst with equal settings a shared id."""
    loose = sorted((i for i in items if not i["batch_id"]), key=lambda i: i["created_at"])
    group: list[dict] = []

    def close(group):
        if len(group) > 1:
            batch_id = f"inferred-{group[0]['key'].split(':', 1)[1][:24]}"
            for member in group:
                member["batch_id"], member["batch_inferred"] = batch_id, True

    for item in loose:
        if group and item["created_at"] - group[-1]["created_at"] <= _BATCH_GAP_SECONDS and same_settings(group[0], item):
            group.append(item)
            continue
        close(group)
        group = [item]
    close(group)


# ------------------------------------------------------------------ features
def length_bucket(seconds: float) -> str:
    seconds = float(seconds or 0)
    if seconds <= 0:
        return "Unknown"
    for limit, label in ((20, "Under 20 s"), (40, "20–40 s"), (60, "40–60 s"), (180, "1–3 min"), (480, "3–8 min"), (900, "8–15 min")):
        if seconds < limit:
            return label
    return "15 min +"


def _scene_setting(scene: dict) -> str:
    from app.services.animation import vocab

    sky = str(scene.get("sky") or "")
    ground = str(scene.get("ground") or "")
    if sky in vocab.INTERIORS or sky in ("space", "underwater", "parchment"):
        return sky
    if ground and ground != "none":
        return ground
    return sky or "unknown"


def _transition_type(value) -> str:
    if isinstance(value, dict):
        return str(value.get("type") or "tear")
    return str(value or "tear")


def animation_style(board: dict) -> dict:
    """The look of an animation, read from its storyboard."""
    from app.services.animation import vocab

    scenes = [s for s in (board or {}).get("scenes") or [] if isinstance(s, dict)]
    cast = [c for c in (board or {}).get("cast") or [] if isinstance(c, dict)]
    if not scenes:
        return {}
    settings = Counter(_scene_setting(s) for s in scenes)
    kinds = sorted({str(c.get("kind") or "person") for c in cast})
    transitions = {_transition_type(s.get("transition")) for s in scenes[1:]}
    if transitions & set(vocab.MOTIVATED_TRANSITIONS):
        transition_style = "In-picture (fly / hand / zoom / pull)"
    elif "cut" in transitions:
        transition_style = "Paper tear + hard cuts"
    else:
        transition_style = "Paper tear only"
    return {
        "Main setting": settings.most_common(1)[0][0],
        "Settings per video": "1 setting" if len(settings) == 1 else f"{min(len(settings), 4)}{'+' if len(settings) >= 4 else ''} settings",
        "Characters": " + ".join(kinds) if kinds else "No characters",
        "Transitions": transition_style,
        "Scenes": f"{len(scenes)} scenes" if len(scenes) < 10 else "10+ scenes",
    }


def _voice_label(voice: str) -> str:
    voice = voice or ""
    if voice.startswith("elevenlabs:") and voice.count(":") >= 2:
        return f"ElevenLabs · {voice.split(':', 2)[2]}"
    return voice or "Default"


# ----------------------------------------------------------------- animations
def animation_items() -> list[dict]:
    from app.services.animation import schedule as anim_schedule
    from app.services.animation import store

    entries_by_project: dict[str, list[dict]] = {}
    for entry in anim_schedule.list_entries():
        if entry.get("project_id"):
            entries_by_project.setdefault(entry["project_id"], []).append(entry)

    items = []
    for project in store.list_projects():
        pid = project["project_id"]
        entries = entries_by_project.get(pid, [])
        uploaded = _dedupe([project.get("youtube_video_id", "")] + [e.get("youtube_video_id", "") for e in entries])
        if project.get("status") != store.STATUS_DONE and not uploaded:
            continue
        board = store.read_json(store.path(pid, "storyboard.json")) or {}
        words = store.read_json(store.path(pid, "words.json")) or {}
        batch_id = project.get("batch_id") or next((e["batch_id"] for e in entries if e.get("batch_id")), "")
        features = {
            "Aspect": "Vertical 9:16" if project.get("aspect") == "9:16" else "Landscape 16:9",
            "Planned length": f"{project.get('seconds', 0)} s",
            "Voice": _voice_label(words.get("voice") or project.get("voice", "")),
            "Made from": "Calendar (auto)" if project.get("source") == "schedule" else "Studio",
            "Research given": "Yes" if (project.get("context") or "").strip() else "No",
            **animation_style(board),
        }
        items.append(
            _item(
                f"animation:{pid}",
                "animation",
                project.get("topic", ""),
                [(project.get("youtube") or {}).get("title", ""), board.get("title", ""), project.get("title", ""), project.get("topic", "")],
                _epoch(project.get("created_at", 0)),
                project_id=pid,
                batch_id=batch_id,
                known_video_ids=uploaded,
                posted=project.get("posted") or {},
                features=features,
                settings=(project.get("source"), project.get("seconds"), project.get("aspect"), project.get("voice")),
            )
        )
    _infer_batches(items, lambda a, b: a["settings"] == b["settings"])
    for item in items:
        item.pop("settings", None)
    return items


# --------------------------------------------------------------- documentaries
def documentary_items() -> list[dict]:
    from app.services.documentary import doc_schedule, store, thumbnail

    entries_by_project: dict[str, list[dict]] = {}
    for entry in doc_schedule.list_entries():
        if entry.get("project_id"):
            entries_by_project.setdefault(entry["project_id"], []).append(entry)

    items = []
    for project in store.list_projects():
        pid = project["project_id"]
        entries = entries_by_project.get(pid, [])
        uploaded = _dedupe([e.get("youtube_video_id", "") for e in entries])
        if project.get("status") != store.STATUS_DONE and not uploaded:
            continue
        script = store.load_script(pid) or {}
        youtube = script.get("youtube") or {}
        words = int(script.get("word_count") or 0)
        minutes = float(project.get("target_minutes") or 0) or words / 150
        auto = any(e.get("mode") == "auto" for e in entries)
        try:
            has_thumb = os.path.isfile(thumbnail.thumbnail_path(pid))
        except Exception:
            has_thumb = False
        features = {
            "Planned length": length_bucket(minutes * 60) if minutes else "Unknown",
            "Made from": "Calendar autopilot" if auto else "Studio (reviewed)",
            "Research notes given": "Yes" if (project.get("user_notes") or "").strip() else "No",
            "Designed thumbnail": "Yes" if has_thumb else "No",
        }
        items.append(
            _item(
                f"documentary:{pid}",
                "documentary",
                project.get("topic", ""),
                [youtube.get("title", ""), script.get("title", ""), project.get("topic", "")],
                _epoch(project.get("created_at", 0)),
                project_id=pid,
                known_video_ids=uploaded,
                posted=project.get("posted") or {},
                features=features,
            )
        )
    return items


# ---------------------------------------------------------------------- shorts
def _shorts_features(params: dict, preset: str = "") -> dict:
    aspect = params.get("video_aspect") or ("16:9" if preset == "horizontal" else "9:16")
    features = {"Aspect": "Horizontal 16:9" if aspect == "16:9" else "Vertical 9:16"}
    if params:
        features.update(
            {
                "Footage source": str(params.get("video_source") or "Unknown"),
                "Voice": _voice_label(str(params.get("voice_name") or "")),
                "Music": str(params.get("bgm_type") or "none"),
                "Subtitles": "On" if params.get("subtitle_enabled", True) else "Off",
                "Clip length": f"{params.get('video_clip_duration', '?')} s clips",
            }
        )
    return features


def _documentary_task_ids() -> set[str]:
    from app.services.documentary import store

    try:
        return {p["project_id"] for p in store.list_projects()}
    except Exception:
        return set()


def shorts_items() -> list[dict]:
    """Shorts from the calendar (with their upload records) and the generator."""
    from app.services import schedule as shorts_schedule

    posted_marks = analytics_store.load_links()["posted"]
    items: dict[str, dict] = {}

    # 1 · generator output on disk
    skip = _documentary_task_ids()
    for path in glob(os.path.join(utils.task_dir(), "*", "final-*.mp4")):
        task_dir = os.path.dirname(path)
        task_id = os.path.basename(task_dir)
        if task_id in skip:
            continue
        data = _read_json(os.path.join(task_dir, "script.json"))
        if not isinstance(data, dict):
            continue
        params = data.get("params") or {}
        key = f"shorts:{task_id}/{os.path.basename(path)}"
        try:
            created = os.path.getmtime(path)
        except OSError:
            created = 0.0
        subject = str(params.get("video_subject") or "")
        items[key] = _item(
            key,
            "shorts",
            subject,
            [subject, (data.get("script") or "")[:80]],
            created,
            task_id=task_id,
            features={**_shorts_features(params), "Made from": "Generator"},
        )

    # 2 · calendar entries: titles, upload ids and batches for those files
    finals_per_task: Counter = Counter(i.get("task_id") for i in items.values())
    entries = shorts_schedule.list_entries()
    inferred: dict[str, list[dict]] = {}
    for entry in entries:
        if not entry.get("batch_id"):
            inferred.setdefault(entry.get("created_at", ""), []).append(entry)
    inferred_batch = {e["id"]: f"inferred-{group[0]['id'][:8]}" for group in inferred.values() if len(group) > 1 for e in group}

    for entry in entries:
        batch_id, guessed = entry.get("batch_id", ""), False
        if not batch_id and entry["id"] in inferred_batch:
            batch_id, guessed = inferred_batch[entry["id"]], True
        if not batch_id and int(entry.get("video_count", 1) or 1) > 1:
            batch_id = f"variants-{entry['id'][:8]}"
        recorded_ids = set()
        for record in shorts_schedule.upload_records(entry):
            path = record.get("path", "")
            key = f"shorts:{os.path.basename(os.path.dirname(path))}/{os.path.basename(path)}"
            existing = items.get(key) or _item(key, "shorts", entry.get("topic", ""), [], _epoch(entry.get("created_at", "")))
            existing["topic"] = entry.get("topic", "") or existing["topic"]
            existing["titles"] = _dedupe([record.get("title", ""), entry.get("topic", ""), *existing["titles"]])
            existing["label"] = existing["titles"][0] if existing["titles"] else existing["label"]
            if record.get("video_id"):
                existing["known_video_ids"] = _dedupe([*existing["known_video_ids"], record["video_id"]])
                recorded_ids.add(record["video_id"])
            existing["batch_id"], existing["batch_inferred"] = batch_id, guessed
            existing["features"] = {**_shorts_features({}, entry.get("preset", "")), **existing["features"], "Made from": "Calendar"}
            existing["entry_id"] = entry["id"]
            items[key] = existing
        # uploads from before records were kept, whose files are gone
        for video_id in entry.get("youtube_video_ids") or []:
            if video_id in recorded_ids:
                continue
            key = f"shorts:entry:{entry['id']}:{video_id}"
            items[key] = _item(
                key,
                "shorts",
                entry.get("topic", ""),
                [entry.get("topic", "")],
                _epoch(entry.get("created_at", "")),
                batch_id=batch_id,
                batch_inferred=guessed,
                known_video_ids=[video_id],
                features={**_shorts_features({}, entry.get("preset", "")), "Made from": "Calendar"},
                entry_id=entry["id"],
            )

    # several finals from one generator run are one batch of variants
    for item in items.values():
        task_id = item.get("task_id")
        if not item["batch_id"] and task_id and finals_per_task[task_id] > 1:
            item["batch_id"] = f"variants-{task_id[:8]}"
        if item["key"] in posted_marks:
            item["posted"] = posted_marks[item["key"]]
    return list(items.values())


def build_items() -> list[dict]:
    """Every studio's items; a broken studio store never hides the others."""
    items = []
    for name, builder in (("shorts", shorts_items), ("documentary", documentary_items), ("animation", animation_items)):
        try:
            items.extend(builder())
        except Exception:
            logger.exception(f"analytics: could not read the {name} studio")
    sizes = Counter((i["studio"], i["batch_id"]) for i in items if i["batch_id"])
    for item in items:
        item["batch_size"] = sizes.get((item["studio"], item["batch_id"]), 1) if item["batch_id"] else 1
    return items
