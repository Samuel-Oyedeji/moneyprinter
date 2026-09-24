"""Script writer: topic + notes + duration → the narration, in the house style.

Its own call, with its own model (llm role "script") and its own system
prompt: prompts/script_system.md. The prompt expects TOPIC, DURATION and
NOTES from the user turn and answers "TITLE: ..." + "SCRIPT:" with a blank
line between beats. The animation writer (storyboard.py) then splits this
script into scenes without changing a word.
"""

import os
import re

from loguru import logger

from app.services.animation import llm

PROMPT_PATH = os.path.join(os.path.dirname(__file__), "prompts", "script_system.md")

# The prompt's Length table: seconds x 2.5 to seconds x 3 words. The range
# is spelled out next to DURATION (models overshoot when left to work it out),
# and a script more than 10% outside it gets up to two rewrites.
LOW_WPS, HIGH_WPS = 2.5, 3.0
SLACK = 0.1
MAX_REWRITES = 2


def word_range(seconds: int) -> tuple[int, int, int]:
    """(target, low, high) words for a length, as the prompt defines them."""
    low, high = round(seconds * LOW_WPS), round(seconds * HIGH_WPS)
    return round((low + high) / 2), low, high


def _template() -> str:
    with open(PROMPT_PATH, encoding="utf-8") as f:
        return re.sub(r"<!--.*?-->", "", f.read(), flags=re.DOTALL).strip()


def build_messages(topic: str, description: str, seconds: int) -> list[dict]:
    """The system prompt, plus a user turn with whatever the prompt didn't place."""
    _, low, high = word_range(seconds)
    words = f"{low} to {high} words"
    # placeholder: (value in the prompt, line in the request when not placed)
    values = {
        "topic": (topic.strip(), f"TOPIC: {topic.strip()}"),
        "duration": (f"{seconds} seconds", f"DURATION: {seconds} seconds ({words})"),
        "description": (description.strip(), f"NOTES: {description.strip()}" if description.strip() else ""),
        "words": (words, ""),
    }
    system = _template()
    request = []
    for key, (value, line) in values.items():
        token = "{" + key + "}"
        if token in system:
            system = system.replace(token, value or "(none)")
        elif line:
            request.append(line)
    return [{"role": "system", "content": system}, {"role": "user", "content": "\n".join(request) or "Write the script."}]


def parse_reply(text: str) -> tuple[str, str]:
    """(title, script) from a "TITLE: ... SCRIPT: ..." reply; a bare script works too.

    The script keeps its beats as paragraphs; stray headings and wrapping
    quotes are dropped.
    """
    text = re.sub(r"^```\w*[ \t]*\n?|\n?```\s*$", "", str(text or "").strip())
    title_match = re.search(r"^[ \t]*[*_#]*[ \t]*TITLE[ \t]*[*_]*[ \t]*:[ \t]*(.*\S)[ \t]*$", text, re.I | re.M)
    title = title_match.group(1).strip(" *_\"“”") if title_match else ""
    script_match = re.search(r"^[ \t]*[*_#]*[ \t]*SCRIPT[ \t]*[*_]*[ \t]*:[ \t]*", text, re.I | re.M)
    if script_match:
        body = text[script_match.end():]
    else:
        body = text[title_match.end():] if title_match else text
    paragraphs = []
    for block in re.split(r"\n[ \t]*\n", body):
        lines = [ln for ln in block.splitlines() if not re.match(r"^\s*(#+\s|\*\*[^*]+\*\*\s*$|(title|script|narration)\s*:\s*$)", ln, re.I)]
        paragraph = re.sub(r"\s+", " ", " ".join(lines)).strip()
        if paragraph:
            paragraphs.append(paragraph)
    script = "\n\n".join(paragraphs)
    if len(script) > 1 and script[0] in "\"“" and script[-1] in "\"”":
        script = script[1:-1].strip()
    return title, script


def word_count(text: str) -> int:
    return len(text.split())


def write_script(topic: str, description: str, seconds: int, on_cost=None) -> dict:
    """{"title", "text", "words", "model"}; follow-up turns while the length is off."""
    messages = build_messages(topic, description, seconds)
    reply = llm.chat(messages, role="script", on_cost=on_cost)
    title, text = parse_reply(reply)
    target, low, high = word_range(seconds)
    words = latest = word_count(text)
    for _ in range(MAX_REWRITES):
        if not text or low * (1 - SLACK) <= words <= high * (1 + SLACK):
            break
        logger.info(f"script is {latest} words for {seconds}s (wanted {low}-{high}); asking for a rewrite")
        messages = messages + [
            {"role": "assistant", "content": reply},
            {
                "role": "user",
                "content": f"That script is {latest} words. For {seconds} seconds it must be {low} to {high} words. "
                "Rewrite it at that length, keeping the same angle, and answer in the same format.",
            },
        ]
        reply = llm.chat(messages, role="script", on_cost=on_cost)
        new_title, new_text = parse_reply(reply)
        latest = word_count(new_text)
        if new_text and abs(latest - target) < abs(words - target):
            title, text, words = new_title or title, new_text, latest
    if not text:
        raise RuntimeError("the script writer returned an empty script")
    return {"title": title, "text": text, "words": words, "model": llm.model_for("script")}
