"""Animation writer: the finished script → scenes + staging in the kit's vocabulary.

The script comes from script.py (its own model and system prompt). This LLM
(role "writer") splits it into scenes without changing a word and directs
each one (who stands where, how they feel, what they hold, which gesture
lands on which spoken word), but only by choosing named options. Positions are slots ("left", "center"...), timing is a cue word
from the narration; the compiler turns both into coordinates and seconds
once the voice-over exists, for whichever aspect ratio is being rendered.
"""

import difflib
import re

from loguru import logger

from app.services.animation import llm, vocab

WORDS_PER_SECOND = 2.3  # measured: ElevenLabs storytelling voices read ~2.3–2.4 words/s


def target_words(seconds: int) -> tuple[int, int, int]:
    target = round(seconds * WORDS_PER_SECOND)
    return target, round(target * 0.85), round(target * 1.12)


def scene_range(seconds: int) -> tuple[int, int]:
    return max(2, round(seconds / 8)), max(3, round(seconds / 4))


def _opts(values) -> str:
    return " | ".join(values)


def script_seconds(script: str) -> int:
    return max(5, round(len(script.split()) / WORDS_PER_SECOND))


def build_prompt(topic: str, context: str, script: str, aspect: str) -> str:
    min_scenes, max_scenes = scene_range(script_seconds(script))
    orientation = "vertical 9:16 (phone, Shorts)" if aspect == "9:16" else "landscape 16:9 (regular YouTube)"
    return f"""
# Role
You direct short animated videos in a paper cut-out storybook style. The
script is already written; your job is to split it into scenes and stage
each one: backdrops, who is on screen, how they feel, what they hold and do,
and the props and notes that make each line visual. Every picture is drawn
by code from a fixed kit, so you may ONLY use the options listed below.

# The video
Topic: {topic}
Context / research from the producer (use it to get people, places and
objects right):
{context.strip() or "(none)"}
Format: {orientation}.

# The script (final: do not edit it)
{script.strip()}

# Splitting rules
- Split the script into {min_scenes}-{max_scenes} scenes, in order. Each scene's
  "narration" is a run of consecutive sentences copied EXACTLY from the script.
- Every word of the script appears once, in order. Do not add, drop, reword
  or re-punctuate anything; the narration is read aloud and shown as captions.
- Blank lines in the script separate its beats (hook, set-up, the main run,
  the turn, the ending). Cut on a beat, or inside a long beat where the
  picture should change: a new place, time, person or idea.
- If the last line trails off with "...", it loops back into the first line
  when the video replays: keep it exactly as written, as the final scene.

# Staging rules
- Each scene: one setting (sky + ground), at most 3 people and 3 props.
  Vary settings, and pick ones that suit the video (see Settings).
- People are defined once in "cast" and keep the same look in every scene.
  An outfit change = a second cast entry copying the face/hair/skin.
- Every action and note is timed by a "cue": one word copied exactly from
  that scene's narration; it happens when that word is spoken.
- Put people and props in different places so nothing overlaps.
- Direct the emotion: give each person the face that fits the line, and use
  "feel" actions when the mood turns (worried → surprised → smile).
- Use notes sparingly: a "title" banner for the main subject, a "stamp" for
  a key date or number (text should be just the number, e.g. "1928" or
  "70%"), a "label" to name a person or object on screen (target = a cast id
  or a prop name in that scene).

# Settings
sky, outdoors: {_opts(vocab.OUTDOOR_SKIES)}
  with a ground: {_opts(vocab.OUTDOOR_GROUNDS)}
sky, indoors (no ground): room (a home, with a window) | classroom (a
  chalkboard) | lab (shelves of flasks) | hall (a castle hall: stone,
  banners, torches)
sky "space": ground "lunar" (the Moon's surface) or "none"
sky "underwater": its own seabed (no ground needed)
sky "parchment": a plain paper board for close-up fact moments (no ground)
extras (optional; listing any replaces the setting's defaults):
  outdoors: {_opts(vocab.SKY_EXTRAS)}
  one landmark on the horizon: {_opts(vocab.LANDMARKS)}
  room: window · space: {_opts(vocab.SPACE_EXTRAS)} · underwater: {_opts(vocab.UNDERWATER_EXTRAS)}
What suits what:
  moral stories: town (a village), field, forest, hills, room; dawn and
    dusk for mood; fables cast animals (a sly fox, a quick rabbit...)
  history: desert + pyramids (a pharaoh), hills + castle and hall (a
    knight), field + temple, sea or beach (+ boat, lighthouse), parchment
    for dates and maps
  science and facts: space (+ lunar, planet, earth; an astronaut),
    underwater, lab (a robot or a scientist in a labcoat), classroom, city,
    mountains or volcano, parchment for numbers

# Transitions (how each scene after the first arrives)
"tear" (the old page rips away; the default) or "cut" (instant, for a
punchline or a sharp contrast). The rest happen inside the picture, so the
PREVIOUS scene has to set them up:
- {{"type": "fly", "from": "left"}} (or "right"): a paper bird swoops at the
  camera and carries the cut. The previous scene must be outdoors. Good for
  travel, a new place, time passing.
- {{"type": "hand", "who": "<cast id>"}}: someone in the previous scene raises a
  hand to the camera and their palm covers the cut. Good after they speak,
  or for "but", "stop", a reveal.
- {{"type": "zoom", "into": "<thing>"}}: the camera flies into something in the
  previous scene and this scene is what's inside or beyond it: "window" (in
  a room), "sun", "moon", "planet", "earth", or a prop in that scene: a
  clock for a time jump, a globe for a place, a book, scroll or letter into
  the story, a phone or laptop into the screen, or a custom prop's name.
- {{"type": "pull"}}: a paper hand pulls the old page away like a card. Good
  before a parchment fact card or a big reveal.
In a video with 4 or more scenes, at least 2 changes should use fly, hand,
zoom or pull, each because the picture sets it up. Never the same one twice
in a row.

# Options (use exactly these words)
camera: {_opts(vocab.CAMERAS)}
place: {_opts(vocab.PLACES)}
cast.kind (optional): person (default) | astronaut | knight | pharaoh | robot | animal
  astronaut, knight and pharaoh come dressed (a knight's tabard takes
  top.color); a robot is metal (top.color tints it); an animal is a
  storybook animal that stands, talks and wears clothes: give "species":
  {_opts(vocab.SPECIES)} and dress it with top/bottom/hat as usual
cast.age: {_opts(vocab.AGES)} · build: {_opts(vocab.BUILDS)} · skin: {_opts(vocab.SKINS)}
cast.hair.style: {_opts(vocab.HAIR)}
cast.facialHair: {_opts(vocab.FACIAL_HAIR)}
cast.top.style: {_opts(vocab.TOPS)} · bottom.style: {_opts(vocab.BOTTOMS)}
cast.hat.style (optional): {_opts(vocab.HATS)}
cast.accessories: {_opts(vocab.ACCESSORIES)}
colours: hex like "#7a5a43"
person.face: {_opts(vocab.EXPRESSIONS)}
person.enter: {_opts(vocab.PERSON_ENTERS)} · exit: {_opts(vocab.PERSON_EXITS)}
person.actions[].do: {_opts(vocab.PERSON_ACTIONS)}
  (walk needs "to": a place; look needs "dir": left|right|up|down|ahead;
   feel needs "face": an expression; talk/point/think may give "seconds")
person.holding.prop: {_opts(vocab.HOLDABLE)} · holding.pose: down | up
prop.prop: {_opts(vocab.PROPS)} | custom
  custom = an object not in the list, built from 2–12 simple shapes inside
  its own box (x, y, w, h, r in 0–1; 0,0 = top-left; drawn in order):
  {{"prop": "custom", "name": "tower", "aspect": 0.35, "shapes": [
    {{"type": "rect", "x": 0.15, "y": 0.1, "w": 0.7, "h": 0.9, "color": "#efe6d2"}},
    {{"type": "rect", "x": 0.15, "y": 0.3, "w": 0.7, "h": 0.04, "color": "#c9b89a"}},
    {{"type": "circle", "x": 0.5, "y": 0.1, "r": 0.06, "color": "#c9b89a"}},
    {{"type": "poly", "points": [[0.1, 0.12], [0.5, 0.0], [0.9, 0.12]], "color": "#b5542d"}},
    {{"type": "ellipse", "x": 0.5, "y": 0.6, "rx": 0.2, "ry": 0.05, "color": "#d9cdb4"}}]}}
  (aspect = width / height; "name" lets a label point at it)
prop.size: {_opts(vocab.PROP_SIZES)} — how big it looks on screen: small = hand-held
  (coin, cup, book), medium = furniture-sized (chest, chair, bucket),
  large = buildings, towers, trees, boats; hero = the one big close-up
  object, alone on parchment
prop.level: {_opts(vocab.PROP_LEVELS)} (table adds a table under it)
prop.enter: {_opts(vocab.PROP_ENTERS)} · prop.actions[].do: {_opts(vocab.PROP_ACTIONS)}
  (tilt leans the prop over and keeps it leaning; optional "deg", default 8)
prop.text (optional, short: a label on a bottle, book, sign or scroll)

# Output
Respond ONLY with JSON in this shape:
{{
  "title": "working title",
  "cast": [
    {{"id": "ada", "age": "adult", "build": "average", "skin": "fair",
      "hair": {{"style": "bun", "color": "#4a3426"}}, "facialHair": "none",
      "top": {{"style": "dress", "color": "#6c8ebf"}},
      "bottom": {{"style": "skirt", "color": "#3d405b"}},
      "hat": null, "accessories": ["necklace"], "accent": "#d1495b"}}
  ],
  "scenes": [
    {{
      "narration": "In 1843, Ada Lovelace wrote the first computer program.",
      "sky": "room", "ground": "none", "extras": ["window"], "camera": "push",
      "transition": "tear",
      "people": [
        {{"who": "ada", "place": "left", "facing": "right", "face": "smile",
          "enter": "pop", "holding": {{"prop": "scroll", "pose": "up"}},
          "actions": [{{"do": "point", "cue": "program"}}]}}
      ],
      "props": [
        {{"prop": "book", "place": "right", "size": "small", "level": "table",
          "text": "Notes", "enter": "drop", "cue": "wrote", "actions": []}}
      ],
      "notes": [
        {{"kind": "stamp", "text": "1843", "cue": "1843"}},
        {{"kind": "label", "text": "Ada Lovelace", "target": "ada", "cue": "Ada"}}
      ]
    }},
    {{
      "narration": "Inside, her notes described a machine that could weave numbers.",
      "sky": "parchment", "camera": "still",
      "transition": {{"type": "zoom", "into": "book"}},
      "people": [], "props": [], "notes": []
    }}
  ]
}}
""".strip()


def _key(token: str) -> str:
    return re.sub(r"[^\w%]", "", token.lower())


def _scene_tokens(storyboard: dict) -> list[str]:
    return [t for s in storyboard.get("scenes", []) if isinstance(s, dict) for t in str(s.get("narration", "")).split()]


def validate(storyboard, script: str) -> list[str]:
    """Problems worth one corrective retry (the compiler fixes the rest)."""
    if not isinstance(storyboard, dict):
        return ["the reply was not a JSON object"]
    problems = []
    scenes = storyboard.get("scenes")
    if not isinstance(scenes, list) or not scenes:
        return ["there are no scenes"]
    if [_key(t) for t in _scene_tokens(storyboard)] != [_key(t) for t in script.split()]:
        problems.append("the scenes' narration must be the script word for word, in order, with nothing added or left out")
    min_scenes, max_scenes = scene_range(script_seconds(script))
    if not min_scenes <= len(scenes) <= max_scenes:
        problems.append(f"there are {len(scenes)} scenes; use {min_scenes}–{max_scenes}")
    if any(not str(s.get("narration", "")).strip() for s in scenes if isinstance(s, dict)):
        problems.append("every scene needs narration")
    cast_ids = {str(c.get("id")) for c in storyboard.get("cast") or [] if isinstance(c, dict)}
    for i, scene in enumerate(scenes, 1):
        for person in (scene.get("people") or []) if isinstance(scene, dict) else []:
            if isinstance(person, dict) and str(person.get("who")) not in cast_ids:
                problems.append(f"scene {i} uses {person.get('who')!r}, which is not in the cast")
    return problems


def _script_index(opcodes, p: int, script_len: int, board_len: int) -> int:
    """Where position p of the writer's words falls in the script's words."""
    if p >= board_len:
        return script_len
    for tag, i1, i2, j1, j2 in opcodes:
        if tag == "insert" and i1 == p:
            return j1  # script words the writer dropped go to the next scene
        if i1 <= p < i2:
            if tag == "equal":
                return j1 + (p - i1)
            return j1 + round((p - i1) * (j2 - j1) / (i2 - i1))
    return script_len


def align_to_script(storyboard: dict, script: str) -> dict:
    """Make the scenes speak the script exactly, keeping the writer's scene cuts.

    Any word the writer changed, dropped or added is corrected from the
    script; scenes left with no words are dropped.
    """
    script_tokens = script.split()
    scenes = [s for s in storyboard.get("scenes", []) if isinstance(s, dict)]
    lengths = [len(str(s.get("narration", "")).split()) for s in scenes]
    board_tokens = _scene_tokens(storyboard)
    opcodes = difflib.SequenceMatcher(
        a=[_key(t) for t in board_tokens], b=[_key(t) for t in script_tokens], autojunk=False
    ).get_opcodes()
    starts, pos = [], 0
    for n in lengths:
        starts.append(pos)
        pos += n
    cuts = [0] + [_script_index(opcodes, p, len(script_tokens), len(board_tokens)) for p in starts[1:]] + [len(script_tokens)]
    kept = []
    for i, scene in enumerate(scenes):
        cuts[i + 1] = max(cuts[i + 1], cuts[i])  # cuts only move forward
        if cuts[i + 1] > cuts[i]:
            kept.append({**scene, "narration": " ".join(script_tokens[cuts[i] : cuts[i + 1]])})
    return {**storyboard, "scenes": kept}


def write_storyboard(topic: str, context: str, script: str, aspect: str, on_cost=None) -> dict:
    prompt = build_prompt(topic, context, script, aspect)
    storyboard = llm.generate_json(prompt, on_cost=on_cost, role="writer")
    problems = validate(storyboard, script)
    if problems:
        logger.info(f"storyboard needs a fix: {problems}")
        retry = (
            prompt
            + "\n\n# Your previous attempt had problems — fix them and return the full JSON again:\n- "
            + "\n- ".join(problems)
        )
        second = llm.generate_json(retry, on_cost=on_cost, role="writer")
        second_problems = validate(second, script)
        if len(second_problems) <= len(problems):
            storyboard, problems = second, second_problems
    if not isinstance(storyboard, dict) or not storyboard.get("scenes"):
        raise RuntimeError("the storyboard writer returned no scenes")
    storyboard = align_to_script(storyboard, script)
    if not storyboard["scenes"]:
        raise RuntimeError("the animation writer returned no scenes")
    return storyboard


def narration_text(storyboard: dict) -> str:
    return " ".join(s["narration"] for s in storyboard.get("scenes", []) if s.get("narration"))
