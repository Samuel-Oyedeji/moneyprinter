"""Sort video topics into a handful of categories, so "which kinds of topics
work" can be answered across hundreds of one-off topics.

The app's configured LLM does the sorting, reusing the categories it has
already handed out so the set stays small and stable. Every result can be
overridden on the Analytics page; a missing or failing LLM just leaves
topics uncategorized.
"""

import json
import re

from loguru import logger

from app.services.analytics import store

UNCATEGORIZED = "Uncategorized"
_CHUNK = 40
_MAX_CATEGORIES = 14


def build_prompt(topics: list[str], existing: list[str]) -> str:
    known = "\n".join(f"- {c}" for c in existing) or "(none yet)"
    listed = "\n".join(f"{i}. {t}" for i, t in enumerate(topics, start=1))
    return f"""You sort YouTube video topics into broad content categories so a creator can see which kinds of topics perform best.

Categories already in use (reuse one whenever it fits; the full set should stay under {_MAX_CATEGORIES}):
{known}

Rules:
- A category is 1-3 words in Title Case, broad enough to hold many videos (e.g. "Ancient History", "Science", "Moral Stories", "Money & Business", "True Crime", "Space", "Animals & Nature", "Health", "Technology", "Geography").
- Only invent a new category when none of the existing ones fit.
- Every topic gets exactly one category.

Topics:
{listed}

Reply with JSON only: an object mapping each topic number (as a string) to its category, like {{"1": "Science", "2": "Ancient History"}}."""


def parse_response(response: str, topics: list[str]) -> dict:
    text = (response or "").strip()
    text = re.sub(r"^```(?:json)?\s*|\s*```$", "", text)
    match = re.search(r"\{.*\}", text, re.DOTALL)
    if not match:
        return {}
    try:
        data = json.loads(match.group(0))
    except json.JSONDecodeError:
        return {}
    result = {}
    for number, category in (data or {}).items():
        try:
            index = int(str(number).strip().rstrip(".")) - 1
        except ValueError:
            continue
        category = str(category or "").strip()[:40]
        if 0 <= index < len(topics) and category:
            result[topics[index]] = category
    return result


def categorize(topics: list[str], generate=None) -> dict:
    """Categorize the topics that have no category yet; returns the new ones."""
    from app.services import llm

    generate = generate or llm._generate_response
    known = store.load_links()["categories"]
    todo = list(dict.fromkeys(t for t in topics if t and t not in known))
    if not todo:
        return {}
    added: dict[str, str] = {}
    for start in range(0, len(todo), _CHUNK):
        chunk = todo[start : start + _CHUNK]
        existing = sorted(set(known.values()) | set(added.values()))
        try:
            response = generate(build_prompt(chunk, existing))
        except Exception as exc:
            logger.warning(f"analytics: topic categorization failed: {exc}")
            break
        if not isinstance(response, str) or "Error: " in response:
            logger.warning(f"analytics: topic categorization failed: {response!r:.200}")
            break
        added.update(parse_response(response, chunk))
    if added:
        store.set_categories(added)
    return added
