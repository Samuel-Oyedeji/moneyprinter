"""Storyboard + narration timings → the Remotion story (PaperStory props).

The storyboard speaks in slots ("left"), sizes ("medium") and cue words; this
module turns those into frame coordinates and seconds for the chosen aspect
ratio, and drops anything outside the kit's vocabulary. Pure functions — no
I/O — so the whole mapping is unit-testable.
"""

import re

from app.services.animation import vocab

FPS = 24
LEAD = 0.3  # a scene starts this long before its first word
TAIL = 0.9  # hold after the last word
LOOP_TAIL = 0.15  # a script ending in "..." flows straight back into its first line
MIN_SCENE = 1.2

LAYOUTS = {
    "9:16": {
        "width": 1080,
        "height": 1920,
        "slots": {"far-left": 0.14, "left": 0.27, "center": 0.5, "right": 0.73, "far-right": 0.86},
        "feet": 0.705,
        "ground": 0.695,
        "table": 0.632,
        "air": 0.36,
        "person": 0.32,
        "child": 0.23,
        "sizes": {"small": 0.065, "medium": 0.12, "large": 0.22, "hero": 0.3},
        "hero_y": 0.64,
        "title_y": 0.12,
        "stamp_center": (0.5, 0.19),
        "stamp_corners": [(0.8, 0.3), (0.2, 0.3)],
        "label_y": (0.2, 0.6),
        "label_rise": 0.12,
        "window": {"x": 0.74, "y": 0.3, "size": 1.0},
        "tree_y": 0.66,
        "table_min_width": 0.42,
    },
    "16:9": {
        "width": 1920,
        "height": 1080,
        "slots": {"far-left": 0.12, "left": 0.28, "center": 0.5, "right": 0.72, "far-right": 0.88},
        "feet": 0.79,
        "ground": 0.785,
        "table": 0.62,
        "air": 0.34,
        "person": 0.48,
        "child": 0.34,
        "sizes": {"small": 0.1, "medium": 0.18, "large": 0.32, "hero": 0.5},
        "hero_y": 0.76,
        "title_y": 0.13,
        "stamp_center": (0.5, 0.22),
        "stamp_corners": [(0.86, 0.28), (0.14, 0.28)],
        "label_y": (0.14, 0.62),
        "label_rise": 0.2,
        "window": {"x": 0.8, "y": 0.32, "size": 0.8},
        "tree_y": 0.7,
        "table_min_width": 0.3,
    },
}

_HEX = re.compile(r"^#[0-9a-fA-F]{6}$")


def _norm(word: str) -> str:
    return re.sub(r"[^a-z0-9%]", "", (word or "").lower())


def _pick(value, allowed, default=None):
    value = str(value or "").strip().lower()
    return value if value in allowed else default


def _hex(value):
    value = str(value or "").strip()
    return value if _HEX.match(value) else None


def _clamp(v, lo, hi):
    return max(lo, min(hi, v))


def _slug(value) -> str:
    return re.sub(r"[^a-z0-9-]+", "-", str(value or "").lower()).strip("-")[:30]


# ------------------------------------------------------------------ cast
def sanitize_character(raw: dict, index: int) -> dict:
    raw = raw if isinstance(raw, dict) else {}
    out: dict = {"id": _slug(raw.get("id")) or f"person-{index + 1}"}
    for key, allowed in (("age", vocab.AGES), ("build", vocab.BUILDS)):
        if _pick(raw.get(key), allowed):
            out[key] = _pick(raw.get(key), allowed)
    skin = _pick(raw.get("skin"), vocab.SKINS) or _hex(raw.get("skin"))
    if skin:
        out["skin"] = skin
    hair = raw.get("hair") if isinstance(raw.get("hair"), dict) else {}
    if _pick(hair.get("style"), vocab.HAIR):
        out["hair"] = {"style": _pick(hair.get("style"), vocab.HAIR)}
        if _hex(hair.get("color")):
            out["hair"]["color"] = _hex(hair.get("color"))
    if _pick(raw.get("facialHair"), vocab.FACIAL_HAIR):
        out["facialHair"] = _pick(raw.get("facialHair"), vocab.FACIAL_HAIR)
    top = raw.get("top") if isinstance(raw.get("top"), dict) else {}
    if _pick(top.get("style"), vocab.TOPS):
        out["top"] = {"style": _pick(top.get("style"), vocab.TOPS)}
        for k in ("color", "inner"):
            if _hex(top.get(k)):
                out["top"][k] = _hex(top.get(k))
    bottom = raw.get("bottom") if isinstance(raw.get("bottom"), dict) else {}
    if _pick(bottom.get("style"), vocab.BOTTOMS):
        out["bottom"] = {"style": _pick(bottom.get("style"), vocab.BOTTOMS)}
        if _hex(bottom.get("color")):
            out["bottom"]["color"] = _hex(bottom.get("color"))
    hat = raw.get("hat") if isinstance(raw.get("hat"), dict) else {}
    if _pick(hat.get("style"), vocab.HATS):
        out["hat"] = {"style": _pick(hat.get("style"), vocab.HATS)}
        if _hex(hat.get("color")):
            out["hat"]["color"] = _hex(hat.get("color"))
    accessories = [a for a in (raw.get("accessories") or []) if _pick(a, vocab.ACCESSORIES)]
    if accessories:
        out["accessories"] = [str(a).lower() for a in accessories][:3]
    for k in ("shoes", "accent"):
        if _hex(raw.get(k)):
            out[k] = _hex(raw.get(k))
    return out


# ------------------------------------------------------------------ timing
def scene_word_spans(scenes: list[dict], words: list[dict]) -> list[tuple[int, int]]:
    """Which timed words belong to each scene.

    TTS words normally match the script's whitespace tokens one-to-one; if a
    provider merges or splits tokens, the boundaries are placed
    proportionally instead.
    """
    counts = [len(s.get("narration", "").split()) for s in scenes]
    total = sum(counts)
    spans, start = [], 0
    for i, n in enumerate(counts):
        if len(words) == total:
            end = start + n
        else:
            end = round(sum(counts[: i + 1]) * len(words) / max(1, total))
        end = max(end, start)
        spans.append((start, end))
        start = end
    return spans


def ends_in_loop(words: list[dict]) -> bool:
    """The script's last word trails off ("...") to loop into its first line."""
    return bool(words) and str(words[-1]["text"]).rstrip().endswith(("...", "…"))


def scene_times(spans, words, audio_duration: float) -> list[tuple[float, float]]:
    """(start, duration) per scene: cut just before each scene's first word.

    The video holds for TAIL after the narration, or, for a loop ending, cuts
    LOOP_TAIL after the last word so the replay picks the sentence up.
    """
    starts = [0.0]
    for a, b in spans[1:]:
        at = words[a]["at"] - LEAD if a < len(words) else starts[-1] + MIN_SCENE
        starts.append(max(starts[-1] + MIN_SCENE, at))
    last_word_end = max((w.get("end", w["at"]) for w in words), default=0.0)
    if ends_in_loop(words):
        end = last_word_end + LOOP_TAIL
    else:
        end = max(audio_duration, last_word_end) + TAIL
    end = max(end, starts[-1] + MIN_SCENE)
    times = []
    for i, s in enumerate(starts):
        nxt = starts[i + 1] if i + 1 < len(starts) else end
        times.append((round(s, 3), round(nxt - s, 3)))
    return times


class Cues:
    """Resolve a cue word to seconds from the scene's start."""

    def __init__(self, scene_words: list[dict], scene_start: float, duration: float):
        self.words = [(_norm(w["text"]), w["at"] - scene_start) for w in scene_words]
        self.duration = duration
        self._fallback = 0

    def at(self, cue, default: float | None = None) -> float:
        key = _norm(str(cue or "").split()[0] if str(cue or "").split() else "")
        if key:
            for norm, t in self.words:
                if norm == key:
                    return round(max(0.0, t), 2)
            for norm, t in self.words:
                if norm.startswith(key) or (len(key) > 3 and key in norm):
                    return round(max(0.0, t), 2)
        if default is not None:
            return default
        # no match: spread unmatched cues through the scene
        self._fallback += 1
        return round(min(self.duration * 0.8, 0.4 + 0.9 * self._fallback), 2)


# ------------------------------------------------------------------ scenes
def _extras(scene: dict, L: dict, has_title: bool, used_x: list[float]) -> tuple[list[dict], bool]:
    names = [_pick(e, vocab.EXTRAS) for e in (scene.get("extras") or [])]
    names = [n for n in names if n]
    out: list[dict] = []
    tree_sides = [0.1, 0.9]
    for n in dict.fromkeys(names):
        if n == "sun":
            out.append({"type": "sun", "x": 0.18, "y": 0.3, "size": 0.75} if has_title else {"type": "sun", "x": 0.8, "y": 0.12})
        elif n == "moon":
            out.append({"type": "moon", "x": 0.2, "y": 0.28 if has_title else 0.1})
        elif n == "window":
            out.append({"type": "window", **L["window"]})
        elif n == "tree":
            for x in tree_sides:
                if all(abs(x - u) > 0.15 for u in used_x):
                    out.append({"type": "tree", "x": x, "y": L["tree_y"]})
                    break
        else:
            out.append({"type": n})
    return out, bool(names)


def _place(value, L: dict, taken: list[float]) -> float:
    slots = L["slots"]
    want = slots.get(_pick(value, vocab.PLACES, "center"), 0.5)
    if all(abs(want - t) > 0.12 for t in taken):
        return want
    free = [x for x in slots.values() if all(abs(x - t) > 0.12 for t in taken)]
    return min(free, key=lambda x: abs(x - want)) if free else want


def sanitize_shapes(raw) -> list[dict]:
    """Keep only well-formed shapes with coordinates inside the box."""
    shapes = []
    num = lambda v, lo=0.0, hi=1.0: round(_clamp(float(v), lo, hi), 4)  # noqa: E731
    for sh in (raw or [])[:12]:
        if not isinstance(sh, dict):
            continue
        kind, color = _pick(sh.get("type"), vocab.SHAPE_TYPES), _hex(sh.get("color"))
        if not kind or not color:
            continue
        try:
            if kind == "rect":
                out = {"type": "rect", "x": num(sh["x"]), "y": num(sh["y"]), "w": num(sh["w"], 0.01), "h": num(sh["h"], 0.01), "color": color}
                if sh.get("round") is not None:
                    out["round"] = num(sh["round"], 0.0, 0.5)
            elif kind == "circle":
                out = {"type": "circle", "x": num(sh["x"]), "y": num(sh["y"]), "r": num(sh["r"], 0.005, 0.6), "color": color}
            elif kind == "ellipse":
                out = {"type": "ellipse", "x": num(sh["x"]), "y": num(sh["y"]), "rx": num(sh["rx"], 0.005, 0.6), "ry": num(sh["ry"], 0.005, 0.6), "color": color}
            else:
                points = [[num(x), num(y)] for x, y in (sh.get("points") or [])[:14]]
                if len(points) < 3:
                    continue
                out = {"type": "poly", "points": points, "color": color}
        except (KeyError, TypeError, ValueError):
            continue
        shapes.append(out)
    return shapes


def _count_for(text: str):
    """A stamp's roll-up: years count up from a few decades before, numbers from 0."""
    t = text.strip()
    if re.fullmatch(r"1\d{3}|20\d{2}", t):
        year = int(t)
        return {"from": year - 30, "to": year, "dur": 0.9, "separator": False}
    m = re.fullmatch(r"(\d{1,3})%", t)
    if m:
        return {"from": 0, "to": int(m.group(1)), "dur": 1.0, "suffix": "%", "separator": False}
    m = re.fullmatch(r"\d{1,3}(,\d{3})+|\d{2,9}", t)
    if m:
        return {"from": 0, "to": int(t.replace(",", "")), "dur": 1.2}
    return None


def compile_scene(raw: dict, index: int, start: float, duration: float, scene_words: list[dict], cast_by_id: dict, L: dict) -> dict:
    cues = Cues(scene_words, start, duration)
    sky = _pick(raw.get("sky"), vocab.SKIES, "day")
    ground = _pick(raw.get("ground"), vocab.GROUNDS, "hills")
    notes_raw = [n for n in (raw.get("notes") or []) if isinstance(n, dict)]
    has_title = any(_pick(n.get("kind"), vocab.NOTE_KINDS) == "title" for n in notes_raw)

    actors: list[dict] = []
    anchors: dict[str, tuple[float, float]] = {}  # label targets
    taken: list[float] = []

    # ---- props first (things stand behind people in list order)
    props_out = []
    table_xs = []
    for i, p in enumerate((raw.get("props") or [])[:3]):
        if not isinstance(p, dict):
            continue
        name = _pick(p.get("prop"), vocab.PROPS + (vocab.CUSTOM_PROP,))
        if not name:
            continue
        shapes = sanitize_shapes(p.get("shapes")) if name == vocab.CUSTOM_PROP else []
        if name == vocab.CUSTOM_PROP and len(shapes) < 2:
            continue
        size = _pick(p.get("size"), vocab.PROP_SIZES, "medium")
        level = _pick(p.get("level"), vocab.PROP_LEVELS, "ground")
        h = L["sizes"][size]
        if size == "hero":
            x, y = 0.5, L["hero_y"]
        else:
            x = _place(p.get("place"), L, taken if level == "ground" else [])
            y = {"ground": L["ground"], "table": L["table"], "air": L["air"]}[level]
        if level == "ground" and size != "hero":
            taken.append(x)
        if level == "table":
            table_xs.append(x)
        prop: dict = {"prop": "shapes" if shapes else name, "x": x, "y": y, "height": h, "idle": "float" if level == "air" else "still"}
        if shapes:
            prop["shapes"] = shapes
            try:
                prop["aspect"] = round(_clamp(float(p.get("aspect") or 1.0), 0.15, 4.0), 3)
            except (TypeError, ValueError):
                prop["aspect"] = 1.0
        if _hex(p.get("color")):
            prop["color"] = _hex(p.get("color"))
        text = str(p.get("text") or "").strip()
        if text:
            prop["text"] = text[:14]
        if name == "petri-dish":
            prop["mould"] = bool(p.get("mould", True))
        enter = _pick(p.get("enter"), vocab.PROP_ENTERS, "pop")
        prop["enter"] = {"type": enter, "at": cues.at(p.get("cue"), 0.2 + 0.25 * i)}
        acts = []
        for a in (p.get("actions") or [])[:3]:
            if isinstance(a, dict) and _pick(a.get("do"), vocab.PROP_ACTIONS):
                act = {"do": _pick(a.get("do"), vocab.PROP_ACTIONS), "at": cues.at(a.get("cue"))}
                if act["do"] in ("shake", "grow"):
                    act["dur"] = 0.7
                if act["do"] == "tilt":
                    try:
                        act["deg"] = round(_clamp(float(a.get("deg", 8)), -45, 45), 1)
                    except (TypeError, ValueError):
                        act["deg"] = 8
                acts.append(act)
        if acts:
            prop["actions"] = acts
        props_out.append(prop)
        anchors[name] = (x, y - h * 0.55)
        if shapes and p.get("name"):
            anchors[_slug(p.get("name"))] = (x, y - h * 0.55)

    # ---- people
    people_out = []
    for i, person in enumerate((raw.get("people") or [])[:3]):
        if not isinstance(person, dict):
            continue
        who = _slug(person.get("who"))
        if who not in cast_by_id:
            continue
        child = cast_by_id[who].get("age") == "child"
        h = L["child"] if child else L["person"]
        x = _place(person.get("place"), L, taken)
        taken.append(x)
        facing = _pick(person.get("facing"), ("left", "right", "front"))
        if not facing:
            facing = "left" if x > 0.55 else "right"
        out: dict = {"who": who, "x": x, "y": L["feet"], "height": h, "facing": facing}
        face = _pick(person.get("face"), vocab.EXPRESSIONS)
        if face:
            out["face"] = face
        enter = _pick(person.get("enter"), vocab.PERSON_ENTERS, "pop")
        enter_type = {"walk-in-left": "slide-left", "walk-in-right": "slide-right"}.get(enter, enter)
        out["enter"] = {"type": enter_type, "at": cues.at(person.get("cue"), 0.1 + 0.2 * i)}
        exit_ = _pick(person.get("exit"), vocab.PERSON_EXITS)
        if exit_:
            out["exit"] = {
                "type": {"walk-out-left": "slide-left", "walk-out-right": "slide-right"}.get(exit_, exit_),
                "at": cues.at(person.get("exit_cue"), max(0.5, duration - 1.2)),
            }
        holding = person.get("holding") if isinstance(person.get("holding"), dict) else {}
        if _pick(holding.get("prop"), vocab.HOLDABLE):
            out["holding"] = {"prop": _pick(holding.get("prop"), vocab.HOLDABLE), "pose": _pick(holding.get("pose"), ("down", "up"), "down")}
        acts = []
        for a in (person.get("actions") or [])[:4]:
            if not isinstance(a, dict):
                continue
            do = _pick(a.get("do"), vocab.PERSON_ACTIONS)
            if not do:
                continue
            at = cues.at(a.get("cue"))
            act: dict = {"do": do, "at": at}
            secs = a.get("seconds")
            if do == "walk":
                act["to"] = L["slots"].get(_pick(a.get("to"), vocab.PLACES, "center"), 0.5)
                act["dur"] = round(max(0.8, abs(act["to"] - x) / 0.38), 2)
            elif do in ("talk", "point", "think", "wave", "cheer"):
                default = {"talk": max(1.0, duration - at - 0.3), "point": 1.4, "think": 1.6, "wave": 1.4, "cheer": 1.1}[do]
                try:
                    act["dur"] = round(_clamp(float(secs), 0.5, 8.0), 2) if secs is not None else round(default, 2)
                except (TypeError, ValueError):
                    act["dur"] = round(default, 2)
            elif do == "look":
                act["dir"] = _pick(a.get("dir"), ("left", "right", "up", "down", "ahead"), "ahead")
            elif do == "feel":
                act["face"] = _pick(a.get("face"), vocab.EXPRESSIONS, "smile")
            acts.append(act)
        if acts:
            out["actions"] = acts
        people_out.append(out)
        anchors[who] = (x, L["feet"] - h * 0.62)

    actors = props_out + people_out

    # ---- backdrop
    extras, explicit = _extras(raw, L, has_title, taken)
    if table_xs:
        span_ = max(table_xs) - min(table_xs)
        extras.append({"type": "table", "x": round(sum(table_xs) / len(table_xs), 3), "y": L["table"], "width": round(max(L["table_min_width"], span_ + 0.25), 3)})
    backdrop: dict = {"sky": sky, "ground": ground, "seed": index + 1}
    if extras:
        backdrop["extras"] = extras
    if explicit:
        backdrop["noDefaults"] = True

    # ---- notes
    notes = []
    corners = list(L["stamp_corners"])
    for n in notes_raw[:3]:
        kind = _pick(n.get("kind"), vocab.NOTE_KINDS)
        text = str(n.get("text") or "").strip()
        if not kind or not text:
            continue
        at = cues.at(n.get("cue"), 0.3)
        if kind == "title":
            note = {"kind": "title", "text": text[:28], "at": at, "y": L["title_y"]}
            if str(n.get("sub") or "").strip():
                note["sub"] = str(n["sub"]).strip()[:40]
            notes.append(note)
        elif kind == "stamp":
            x, y = corners.pop(0) if has_title and corners else L["stamp_center"]
            note = {"kind": "stamp", "text": text[:10], "at": at, "x": x, "y": y, "size": 1.0 if (x, y) == L["stamp_center"] else 0.8}
            count = _count_for(text)
            if count:
                note["count"] = count
            notes.append(note)
            if (x, y) == L["stamp_center"]:
                has_title = True  # later stamps go to the corners
        elif kind == "label":
            target = _slug(n.get("target")) or str(n.get("target") or "").lower()
            anchor = anchors.get(target)
            if not anchor:
                continue
            ax, ay = anchor
            lo, hi = L["label_y"]
            notes.append({
                "kind": "label",
                "text": text[:24],
                "at": at,
                "x": round(_clamp(ax + (0.2 if ax < 0.5 else -0.2), 0.24, 0.76), 3),
                "y": round(_clamp(ay - L["label_rise"], lo, hi), 3),
                "toX": round(ax, 3),
                "toY": round(ay, 3),
            })

    camera = _pick(raw.get("camera"), vocab.CAMERAS, "drift")
    focus = actors[-1] if actors else None
    scene_out: dict = {
        "id": f"scene {index + 1}",
        "duration": duration,
        "backdrop": backdrop,
        "camera": {"move": camera, "focusX": round(focus["x"], 3) if focus else 0.5, "focusY": 0.5},
        "actors": actors,
        "transition": _pick(raw.get("transition"), vocab.TRANSITIONS, "tear"),
    }
    if notes:
        scene_out["notes"] = notes
    return scene_out


def compile_story(storyboard: dict, words: list[dict], audio_duration: float, aspect: str, narration_file: str = "narration.mp3") -> dict:
    if aspect not in LAYOUTS:
        raise ValueError(f"unsupported aspect: {aspect!r}")
    L = LAYOUTS[aspect]
    scenes = [s for s in storyboard.get("scenes", []) if isinstance(s, dict) and str(s.get("narration", "")).strip()]
    if not scenes:
        raise ValueError("storyboard has no scenes")
    if not words:
        raise ValueError("no narration word timings")

    cast = []
    for i, c in enumerate(storyboard.get("cast") or []):
        character = sanitize_character(c, i)
        if character["id"] not in {x["id"] for x in cast}:
            cast.append(character)
    cast_by_id = {c["id"]: c for c in cast}

    spans = scene_word_spans(scenes, words)
    times = scene_times(spans, words, audio_duration)
    compiled = [
        compile_scene(raw, i, start, dur, words[a:b], cast_by_id, L)
        for i, (raw, (start, dur), (a, b)) in enumerate(zip(scenes, times, spans))
    ]
    return {
        "title": str(storyboard.get("title") or "")[:100],
        "width": L["width"],
        "height": L["height"],
        "fps": FPS,
        "cast": cast,
        "narration": narration_file,
        "words": [{"text": w["text"], "at": w["at"], "end": w.get("end", w["at"] + 0.3)} for w in words],
        "scenes": compiled,
    }


def story_duration(story: dict) -> float:
    return round(sum(s["duration"] for s in story.get("scenes", [])), 3)
