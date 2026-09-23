"""Storyboard writer: topic → narration by scene + staging in the kit's vocabulary.

The LLM writes the words AND directs the scene (who stands where, what they
hold, which gesture lands on which spoken word), but only by choosing named
options. Positions are slots ("left", "center"...), timing is a cue word
from the narration; the compiler turns both into coordinates and seconds
once the voice-over exists, for whichever aspect ratio is being rendered.
"""

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


def build_prompt(topic: str, context: str, seconds: int, aspect: str) -> str:
    target, low, high = target_words(seconds)
    min_scenes, max_scenes = scene_range(seconds)
    orientation = "vertical 9:16 (phone, Shorts)" if aspect == "9:16" else "landscape 16:9 (regular YouTube)"
    return f"""
# Role
You write and direct short animated explainer videos in a paper cut-out
storybook style. Every picture is drawn by code from a fixed kit, so you may
ONLY use the options listed below. You decide the words and the staging.

# The video
Topic: {topic}
Context / research from the producer (treat as the most reliable source):
{context.strip() or "(none)"}
Length: about {seconds} seconds of narration → {low}–{high} words total (aim for {target}).
Format: {orientation}.
Scenes: {min_scenes}–{max_scenes}, each 1–2 sentences of narration.

# Writing rules
- It can be a moral story, a slice of history, or a fact explainer; pick what
  fits the topic. The FIRST sentence must hook (a surprising fact, a question,
  a vivid moment). End with a satisfying payoff or takeaway line.
- Plain spoken English, past tense for stories. No lists, no "In this video".
- Only state facts you are confident about; prefer the producer's context.
  Do not invent precise statistics. Write numbers as digits (1928, 70%).
- The narration is read aloud AND shown as captions.

# Staging rules
- Each scene: one backdrop, at most 3 people and 3 props. Vary backdrops.
  Use "parchment" (a plain paper board) for close-up fact moments, "room"
  for interiors, outdoor skies otherwise.
- People are defined once in "cast" and keep the same look in every scene.
  An outfit change = a second cast entry copying the face/hair/skin.
- Every action and note is timed by a "cue": one word copied exactly from
  that scene's narration; it happens when that word is spoken.
- Put people and props in different places so nothing overlaps.
- Use notes sparingly: a "title" banner for the main subject, a "stamp" for
  a key date or number (text should be just the number, e.g. "1928" or
  "70%"), a "label" to name a person or object on screen (target = a cast id
  or a prop name in that scene).

# Options (use exactly these words)
sky: {_opts(vocab.SKIES)}
ground (ignored for parchment/room): {_opts(vocab.GROUNDS)}
extras: {_opts(vocab.EXTRAS)}
camera: {_opts(vocab.CAMERAS)}
transition (how a scene arrives): {_opts(vocab.TRANSITIONS)}
place: {_opts(vocab.PLACES)}
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
    }}
  ]
}}
""".strip()


def _word_count(storyboard: dict) -> int:
    return sum(len(str(s.get("narration", "")).split()) for s in storyboard.get("scenes", []))


def validate(storyboard, seconds: int) -> list[str]:
    """Problems worth one corrective retry (the compiler fixes the rest)."""
    if not isinstance(storyboard, dict):
        return ["the reply was not a JSON object"]
    problems = []
    scenes = storyboard.get("scenes")
    if not isinstance(scenes, list) or not scenes:
        return ["there are no scenes"]
    _, low, high = target_words(seconds)
    words = _word_count(storyboard)
    if not low <= words <= high:
        problems.append(f"the narration is {words} words; it must be {low}–{high} words for {seconds} seconds")
    min_scenes, max_scenes = scene_range(seconds)
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


def write_storyboard(topic: str, context: str, seconds: int, aspect: str, on_cost=None) -> dict:
    prompt = build_prompt(topic, context, seconds, aspect)
    storyboard = llm.generate_json(prompt, on_cost=on_cost)
    problems = validate(storyboard, seconds)
    if problems:
        logger.info(f"storyboard needs a fix: {problems}")
        retry = (
            prompt
            + "\n\n# Your previous attempt had problems — fix them and return the full JSON again:\n- "
            + "\n- ".join(problems)
        )
        second = llm.generate_json(retry, on_cost=on_cost)
        second_problems = validate(second, seconds)
        if len(second_problems) <= len(problems):
            storyboard, problems = second, second_problems
    if not isinstance(storyboard, dict) or not storyboard.get("scenes"):
        raise RuntimeError("the storyboard writer returned no scenes")
    for scene in storyboard["scenes"]:
        scene["narration"] = re.sub(r"\s+", " ", str(scene.get("narration", ""))).strip()
    storyboard["scenes"] = [s for s in storyboard["scenes"] if s["narration"]]
    return storyboard


def narration_text(storyboard: dict) -> str:
    return " ".join(s["narration"] for s in storyboard.get("scenes", []) if s.get("narration"))
