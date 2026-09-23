"""YouTube metadata for finished animations: title, description, hashtags, tags.

One LLM pass writes all four together (so the description doesn't just
repeat the title), then `sanitize` enforces YouTube's limits and our house
rules deterministically — the model's copy is never trusted for format.
"""

import re

from loguru import logger

from app.services.animation import llm

TITLE_MAX = 70
DESCRIPTION_MAX = 4800
MAX_HASHTAGS = 5
TAGS_TOTAL_MAX = 450


def build_prompt(topic: str, narration: str, aspect: str, working_title: str = "") -> str:
    shorts = aspect == "9:16"
    return f"""
# Role
You are a YouTube SEO copywriter for an animated storytelling channel
(paper cut-out animation; moral stories, history and surprising facts).

# Write
1. "title": the strongest of several internal drafts. At most {60 if shorts else TITLE_MAX} characters.
   Put the main search keyword early. Hook with a curiosity gap built on a
   real detail from the video. Truthful — never promise what the video
   doesn't show. No ALL-CAPS words, no emojis, no pipes, no hashtags.
2. "description": detailed and search-friendly, 120–220 words.
   - Line 1: a hook (max 120 characters) that adds a new reason to watch
     and contains the main keyword. Do not repeat the title.
   - Then 2–3 short paragraphs on what the viewer will learn, naturally
     using the phrases people would search for (names, places, years,
     the concept). Do not paste the narration.
   - End with one question that invites a comment.
   - No links, no hashtags (they are added separately), no emojis.
3. "hashtags": 3–5 specific hashtags (the first three show above the title),
   CamelCase, no spaces{", do not include #Shorts (added automatically)" if shorts else ""}.
4. "tags": 8–15 search keywords/phrases for the YouTube tags field.

# Video
Topic: {topic}
Format: {"YouTube Short (vertical, under a minute)" if shorts else "regular YouTube video (16:9)"}
Working title: {working_title or topic}
Narration (context only):
{narration[:4000]}

# Output
Respond ONLY with JSON: {{"title": "...", "description": "...", "hashtags": ["#..."], "tags": ["..."]}}
""".strip()


def _clean_title(title: str, limit: int) -> str:
    title = re.sub(r"\s+", " ", str(title or "")).strip().strip("\"'“”‘’").strip()
    title = re.sub(r"\s*[|#].*$", "", title).strip()
    if len(title) <= limit:
        return title
    cut = title[:limit].rsplit(" ", 1)[0].rstrip(",;:-–— ")
    return cut or title[:limit]


def _hashtag(value: str) -> str:
    words = re.findall(r"[A-Za-z0-9]+", str(value or "").lstrip("#"))
    if not words:
        return ""
    if len(words) == 1:
        tag = words[0]
    else:
        tag = "".join(w if w[:1].isupper() or w.isdigit() else w.capitalize() for w in words)
    return f"#{tag[:40]}"


def sanitize(raw: dict, topic: str, aspect: str) -> dict:
    raw = raw if isinstance(raw, dict) else {}
    shorts = aspect == "9:16"
    title = _clean_title(raw.get("title") or topic, 60 if shorts else TITLE_MAX) or topic[:TITLE_MAX]

    hashtags, seen = [], set()
    if shorts:
        hashtags.append("#Shorts")
        seen.add("#shorts")
    for h in raw.get("hashtags") or []:
        tag = _hashtag(h)
        if tag.lower() == "#shorts":
            continue  # only ever ours, and only on vertical videos
        if tag and tag.lower() not in seen and len(hashtags) < MAX_HASHTAGS + int(shorts):
            hashtags.append(tag)
            seen.add(tag.lower())

    description = str(raw.get("description") or "").strip()
    # hashtags belong on their own final line; drop any the model wrote inline
    description = "\n".join(line for line in description.splitlines() if not re.fullmatch(r"\s*(#\w+\s*)+", line))
    description = re.sub(r"\n{3,}", "\n\n", description).strip()
    if not description:
        description = f"{title}\n\nA paper cut-out animated story about {topic}."
    tail = "\n\n" + " ".join(hashtags) if hashtags else ""
    description = description[: DESCRIPTION_MAX - len(tail)].rstrip() + tail

    tags, total = [], 0
    for t in raw.get("tags") or []:
        t = re.sub(r"\s+", " ", str(t or "").lstrip("#")).strip()
        if not t or t.lower() in {x.lower() for x in tags}:
            continue
        if total + len(t) + 2 > TAGS_TOTAL_MAX:
            break
        tags.append(t)
        total += len(t) + 2
    return {"title": title, "description": description, "hashtags": hashtags, "tags": tags}


def generate(topic: str, narration: str, aspect: str, working_title: str = "", on_cost=None) -> dict:
    try:
        raw = llm.generate_json(build_prompt(topic, narration, aspect, working_title), on_cost=on_cost)
    except Exception as exc:
        logger.warning(f"metadata generation failed, using a plain fallback: {exc}")
        raw = {"title": working_title or topic, "description": "", "hashtags": [], "tags": [topic]}
    meta = sanitize(raw, topic, aspect)
    meta["generated"] = True
    return meta
