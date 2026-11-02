"""A studio's brief, turned into directions for each step of the pipeline.

A studio decides each video's levers (studios.templates.ANIMATION): the
angle and hook shape the script, the setting hint steers the storyboard and
the title style steers the YouTube title. The length lever is the project's
``seconds``. Projects made by hand have no brief, and every function here
then returns just the project's own context, so their prompts are unchanged.
"""

WRITERS_CHOICE = "writer's choice"

ANGLES = {
    "what-if": "Angle: a what-if. Change one thing about reality and follow the consequences, one step at a time.",
    "how-it-works": "Angle: how it works. Explain the mechanism behind it, each cause leading to the next.",
    "myth-busting": "Angle: myth-busting. Start from what most people believe, then show what is actually true.",
    "danger": "Angle: a danger. Show what could go wrong, why, and how real the risk is, without fearmongering.",
    "history-moment": "Angle: a moment in history. Tell it as a story: who, where, when, what happened and why it mattered.",
}
HOOKS = {
    "question": "Hook: open with a question the viewer wants answered.",
    "shocking-fact": "Hook: open with the single most surprising true fact in the story.",
    "direct-address": 'Hook: open by speaking to the viewer directly ("You ...").',
    "cold-scene": "Hook: open in the middle of a scene, as if the story is already happening.",
}
TITLE_STYLES = {
    "question": "Phrase the title as a question.",
    "statement": "Make the title a plain, bold statement, not a question.",
    "number": "Lead the title with a specific number from the video.",
}

# Analytics features (Analytics page columns) for each lever.
FEATURE_LABELS = {"angle": "Angle", "hook": "Hook", "setting_hint": "Setting hint", "title_style": "Title style"}


def _brief(project: dict) -> dict:
    return project.get("brief") or {}


def _join(*parts: str) -> str:
    return "\n\n".join(p.strip() for p in parts if p and p.strip())


def script_notes(project: dict) -> str:
    """NOTES for the script writer: the brief's angle and hook, the brief's
    own research notes, then the project's context."""
    brief = _brief(project)
    directions = []
    for lever, texts in (("angle", ANGLES), ("hook", HOOKS)):
        value = brief.get(lever)
        if value:
            directions.append(texts.get(value, f"{lever.title()}: {value}."))
    return _join("\n".join(directions), brief.get("notes", ""), project.get("context", ""))


def storyboard_context(project: dict) -> str:
    """Context for the storyboard writer, with the setting hint if any."""
    brief = _brief(project)
    setting = brief.get("setting_hint")
    hint = ""
    if setting and setting != WRITERS_CHOICE:
        hint = f'Setting direction: where it suits the script, stage the main scenes in the "{setting}" setting.'
    return _join(hint, brief.get("notes", ""), project.get("context", ""))


def title_direction(project: dict) -> str:
    style = _brief(project).get("title_style")
    return TITLE_STYLES.get(style, "") if style else ""


def features(project: dict) -> dict:
    """The brief's levers and the studio's experiment, for the Analytics page."""
    brief, studio = _brief(project), project.get("studio") or {}
    found = {label: str(brief[lever]) for lever, label in FEATURE_LABELS.items() if brief.get(lever) not in (None, "")}
    if studio.get("studio_id"):
        found["Studio"] = studio["studio_id"]
        if studio.get("experiment"):
            found["Experiment"] = studio["experiment"]
        if studio.get("arm"):
            found["Explore / exploit"] = studio["arm"]
    return found
