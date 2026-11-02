"""Starting rules for each kind of studio.

A studio is created from its template once and then belongs to the owner:
editing a template never changes a studio that already exists. Every studio
starts paused, so nothing is planned or uploaded until the owner has read
its rules and unpaused it.
"""

import copy

from app.services.animation import vocab
from app.services.studios import model, store

WRITERS_CHOICE = "writer's choice"

ANIMATION = {
    "id": "animation",
    "name": "Paper Explainers",
    "pipeline": "animation",
    "identity": (
        "Animated science and history explainers in the paper cut-out style: one "
        "surprising question, mechanism, what-if or moment from history per video, "
        "told by one narrator for a general audience on YouTube Shorts."
    ),
    "hard_rules": [
        "No medical, legal or financial advice.",
        "No living people as the subject, and nothing about current politics.",
        "No tragedies less than 25 years old, and no graphic violence.",
        "Every factual claim must be well established; no speculation presented as fact.",
        "Never repeat a topic the channel covered in the last 60 days.",
    ],
    "cadence": {"per_day": 2},
    "post_window": {"start": "07:00", "end": "22:00"},
    "levers": {
        "angle": {
            "values": ["what-if", "how-it-works", "myth-busting", "danger", "history-moment"],
            "default": "how-it-works",
        },
        "hook": {
            "values": ["question", "shocking-fact", "direct-address", "cold-scene"],
            "default": "question",
        },
        "length": {"values": [25, 35, 45, 55], "default": 35},
        "setting_hint": {
            "values": [WRITERS_CHOICE, *dict.fromkeys(vocab.SKIES + vocab.LANDMARKS)],
            "default": WRITERS_CHOICE,
        },
        "title_style": {"values": ["question", "statement", "number"], "default": "statement"},
    },
    "pipeline_options": {"aspect": "9:16", "voice": ""},
    "weekly_budget_usd": 10,
    "veto_hours": 12,
    "planner_model": "",
    "paused": True,
}

TEMPLATES = {"animation": ANIMATION}


def ensure_studio(template_id: str) -> dict:
    """The studio made from a template, created (paused) the first time."""
    if template_id not in TEMPLATES:
        raise KeyError(f"no studio template {template_id!r}")
    template = copy.deepcopy(TEMPLATES[template_id])
    existing = store.load_studio(template["id"])
    if existing:
        return existing
    try:
        studio = store.create_studio(template)
    except model.StudioError:
        # another process created it between the check and the create
        existing = store.load_studio(template["id"])
        if existing:
            return existing
        raise
    store.append_event(
        studio["id"],
        "settings",
        f"Studio created from the {template_id} template. It is paused until you unpause it.",
        {"template": template_id},
    )
    return studio
