"""Image sourcing for documentary projects.

For every script paragraph's image cue, gather candidate photographs from
free, license-tracked sources and download them locally for review:

  1. Wikimedia Commons — the primary source for real archival/event photos.
  2. Openverse — aggregated CC-licensed photography (Flickr, museums, ...).
  3. Pexels / Pixabay photo search — representative/atmospheric stock,
     reusing the API keys already configured for the video pipeline.

Search briefs written by the scriptwriter are verbose; one LLM call turns
them into short archival + stock queries per paragraph. Every candidate
keeps its license, creator and origin page so a credits block can be
generated at publish time.
"""

import json
import os
import re
from urllib.parse import urlparse

import requests
from loguru import logger

from app.config import config
from app.services import material
from app.services.documentary import llm_bridge, store

CANDIDATES_PER_PROVIDER = 2
MAX_CANDIDATES_PER_CUE = 6
RESCUE_SCORE_THRESHOLD = 4.0
DOWNLOAD_TIMEOUT = 30
DOWNLOAD_BYTE_CAP = 15 * 1024 * 1024

_USER_AGENT = (
    "MoneyPrinterTurbo-Documentary/1.0 "
    "(https://github.com/harry0703/MoneyPrinterTurbo)"
)


def _safe_name(text: str, max_length: int = 60) -> str:
    return re.sub(r"[^A-Za-z0-9._-]+", "-", text)[:max_length].strip("-")


def _url_path(url: str) -> str:
    try:
        return (urlparse(url).path or "").lower()
    except ValueError:
        return url.lower()


def _optional_api_key(cfg_key: str) -> str:
    """Stock providers are optional here: no key just skips that provider.

    material.get_api_key() raises when unset because the short-form pipeline
    cannot work without its material source; the documentary pipeline still
    has Wikimedia and Openverse.
    """
    if not config.app.get(cfg_key):
        return ""
    return material.get_api_key(cfg_key)


def _get(url: str, **kwargs):
    kwargs.setdefault("timeout", DOWNLOAD_TIMEOUT)
    headers = kwargs.pop("headers", {})
    headers.setdefault("User-Agent", _USER_AGENT)
    return requests.get(url, headers=headers, **kwargs)


# --------------------------------------------------------------- providers
def search_wikimedia(query: str, count: int) -> list[dict]:
    params = {
        "action": "query",
        "format": "json",
        "generator": "search",
        "gsrsearch": query,
        "gsrnamespace": 6,  # File: namespace
        "gsrlimit": count * 3,
        "prop": "imageinfo",
        "iiprop": "url|extmetadata|size",
        "iiurlwidth": 1920,
    }
    try:
        response = _get("https://commons.wikimedia.org/w/api.php", params=params)
        response.raise_for_status()
        pages = (response.json().get("query") or {}).get("pages") or {}
    except Exception as exc:
        logger.warning(f"wikimedia search failed for {query!r}: {exc}")
        return []

    results = []
    for page in pages.values():
        infos = page.get("imageinfo") or []
        if not infos:
            continue
        info = infos[0]
        url = info.get("thumburl") or info.get("url")
        # Commons appends UTM query params to imageinfo URLs, so the file
        # extension must be checked on the URL path, not the raw string.
        if not url or not _url_path(url).endswith((".jpg", ".jpeg", ".png")):
            continue
        meta = info.get("extmetadata") or {}

        def _meta(field):
            return re.sub(r"<[^>]+>", "", str((meta.get(field) or {}).get("value", "")))

        results.append(
            {
                "provider": "wikimedia",
                "title": page.get("title", "").removeprefix("File:"),
                "image_url": url,
                "page_url": info.get("descriptionurl", ""),
                "license": _meta("LicenseShortName"),
                "creator": _meta("Artist"),
                "width": info.get("thumbwidth") or info.get("width"),
                "height": info.get("thumbheight") or info.get("height"),
            }
        )
        if len(results) >= count:
            break
    return results


def search_openverse(query: str, count: int) -> list[dict]:
    params = {
        "q": query,
        "page_size": count * 2,
        # The channel is monetized: only licenses allowing commercial use.
        "license_type": "commercial",
    }
    try:
        response = _get("https://api.openverse.org/v1/images/", params=params)
        response.raise_for_status()
        items = response.json().get("results") or []
    except Exception as exc:
        logger.warning(f"openverse search failed for {query!r}: {exc}")
        return []

    results = []
    for item in items:
        url = item.get("url") or ""
        if not url:
            continue
        results.append(
            {
                "provider": "openverse",
                "title": item.get("title", ""),
                "image_url": url,
                "page_url": item.get("foreign_landing_url", ""),
                "license": item.get("license", ""),
                "creator": item.get("creator", ""),
                "width": item.get("width"),
                "height": item.get("height"),
            }
        )
        if len(results) >= count:
            break
    return results


def search_pexels_photos(query: str, count: int) -> list[dict]:
    api_key = _optional_api_key("pexels_api_keys")
    if not api_key:
        return []
    try:
        response = _get(
            "https://api.pexels.com/v1/search",
            params={"query": query, "per_page": count, "orientation": "landscape"},
            headers={"Authorization": api_key},
        )
        response.raise_for_status()
        photos = response.json().get("photos") or []
    except Exception as exc:
        logger.warning(f"pexels photo search failed for {query!r}: {exc}")
        return []

    return [
        {
            "provider": "pexels",
            "title": photo.get("alt", ""),
            "image_url": (photo.get("src") or {}).get("large2x")
            or (photo.get("src") or {}).get("original", ""),
            "page_url": photo.get("url", ""),
            "license": "Pexels License",
            "creator": photo.get("photographer", ""),
            "width": photo.get("width"),
            "height": photo.get("height"),
        }
        for photo in photos[:count]
    ]


def search_pixabay_photos(query: str, count: int) -> list[dict]:
    api_key = _optional_api_key("pixabay_api_keys")
    if not api_key:
        return []
    try:
        response = _get(
            "https://pixabay.com/api/",
            params={
                "key": api_key,
                "q": query,
                "image_type": "photo",
                "orientation": "horizontal",
                "per_page": max(count, 3),
                "safesearch": "true",
            },
        )
        response.raise_for_status()
        hits = response.json().get("hits") or []
    except Exception as exc:
        logger.warning(f"pixabay photo search failed for {query!r}: {exc}")
        return []

    return [
        {
            "provider": "pixabay",
            "title": hit.get("tags", ""),
            "image_url": hit.get("largeImageURL", ""),
            "page_url": hit.get("pageURL", ""),
            "license": "Pixabay License",
            "creator": hit.get("user", ""),
            "width": hit.get("imageWidth"),
            "height": hit.get("imageHeight"),
        }
        for hit in hits[:count]
    ]


# ------------------------------------------------------------ query planning
def plan_image_queries(topic: str, items: list[dict]) -> dict:
    """One LLM call: verbose image cues → short per-provider search queries."""
    cue_lines = [f'- {item["key"]}: {item["cue"]}' for item in items]
    prompt = f"""
# Role: Photo Researcher

You are sourcing photographs for a documentary about: {topic}

Convert each image cue below into two short search queries:
- "archival": 3-6 words for archive photo search (Wikimedia Commons).
  Anchor EVERY archival query to the actual event, its location or its
  era — include the event name, city or year wherever plausible (e.g.
  "Eastland disaster Chicago 1915", not "ship hull"). Concrete nouns
  only, no style words like "archival feel" or "mood".
- "stock": 2-4 words for stock photo search — a full scene clearly
  relevant to the beat, never a symbolic object. Do not emit queries for
  badges, flags, emblems, textures or close-up props.

Respond ONLY with a JSON object mapping each key to
{{"archival": "...", "stock": "..."}}. No other text.

## Cues
{chr(10).join(cue_lines)}
""".strip()
    try:
        planned = llm_bridge.generate_json(prompt)
        if isinstance(planned, dict):
            return planned
    except Exception as exc:
        logger.warning(f"image query planning failed, using raw cues: {exc}")
    return {}


def _queries_for(item: dict, planned: dict) -> dict:
    plan = planned.get(item["key"]) or {}
    fallback = " ".join(item["cue"].split()[:5])
    return {
        "archival": str(plan.get("archival") or fallback),
        "stock": str(plan.get("stock") or fallback),
    }


# ----------------------------------------------------------------- download
def download_candidate(project_id: str, key: str, index: int, candidate: dict) -> str:
    url = candidate["image_url"]
    extension = ".png" if _url_path(url).endswith(".png") else ".jpg"
    filename = f"{key}-{index}-{candidate['provider']}{extension}"
    local_path = os.path.join(store.images_dir(project_id), _safe_name(filename, 100))
    try:
        response = _get(url, stream=True)
        response.raise_for_status()
        with open(local_path, "wb") as f:
            written = 0
            for chunk in response.iter_content(chunk_size=65536):
                written += len(chunk)
                if written > DOWNLOAD_BYTE_CAP:
                    raise ValueError("image exceeds download size cap")
                f.write(chunk)
        return local_path
    except Exception as exc:
        logger.warning(f"failed to download {url}: {exc}")
        if os.path.exists(local_path):
            os.remove(local_path)
        return ""


def gather_candidates_for_cue(project_id: str, key: str, queries: dict) -> list[dict]:
    """Search all providers for one cue and download what succeeds."""
    found = (
        search_wikimedia(queries["archival"], CANDIDATES_PER_PROVIDER)
        + search_openverse(queries["archival"], CANDIDATES_PER_PROVIDER)
        + search_pexels_photos(queries["stock"], CANDIDATES_PER_PROVIDER)
        + search_pixabay_photos(queries["stock"], CANDIDATES_PER_PROVIDER)
    )
    candidates = []
    for candidate in found:
        if len(candidates) >= MAX_CANDIDATES_PER_CUE:
            break
        local_path = download_candidate(project_id, key, len(candidates), candidate)
        if local_path:
            candidate["local_path"] = local_path
            candidates.append(candidate)
    return candidates


# ------------------------------------------------------------------ scoring
def score_candidates(item: dict, topic: str = "") -> None:
    """Have the vision model view and score this cue's candidates.

    Scores land on the candidates and the best one becomes the selection, so
    autopilot picks it directly and manual review starts from the best guess.
    A vision failure keeps the provider order selection instead of failing
    the whole sourcing stage.
    """
    candidates = item.get("candidates") or []
    if len(candidates) < 2:
        return

    prompt = f"""
# Role: Documentary Picture Editor

You are choosing the still photograph for one narration beat of a factual
historical documentary about: {topic or "a historical event"}
The images below are numbered starting at 1, in order. View each image and
score it 0-10 for this beat.

## Narration beat
{item.get("text_preview", "")}

## Picture brief
{item.get("cue", "")}

## Scoring criteria
- Relevance to THIS EVENT and this beat (most important): a photograph of
  the actual event, its location, or a clearly matching scene from the
  same era scores highest.
- An image that is merely symbolic of one word in the narration — a badge
  for "soldier", a flag, an emblem, a texture, a generic close-up object —
  scores at most 2, even if technically related.
- Looks like a real photograph of a real place/thing. Posters, logos, maps,
  drawings, watermarked images, text-heavy images and obvious stock-studio
  shots score at most 3.
- Era plausibility: a photo that visibly contradicts the era scores low.
- Respectful: identifiable dead/injured people means score 0.
- Composition: usable as a full-screen 16:9 documentary still.

## Output
Respond ONLY with a JSON array, one entry per image, in order:
[{{"index": 1, "score": 7.5, "reason": "short reason"}}, ...]
""".strip()

    try:
        scores = llm_bridge.generate_vision_json(
            prompt, [c["local_path"] for c in candidates]
        )
        if not isinstance(scores, list):
            raise ValueError("vision scores are not a list")
        for entry in scores:
            index = int(entry.get("index", 0)) - 1
            if 0 <= index < len(candidates):
                candidates[index]["score"] = float(entry.get("score", 0))
                candidates[index]["score_reason"] = str(entry.get("reason", ""))
        best = max(
            range(len(candidates)),
            key=lambda i: candidates[i].get("score", -1),
        )
        item["selected"] = best
    except Exception as exc:
        logger.warning(f"vision scoring failed for cue {item.get('key')}: {exc}")


def _best_score(item: dict) -> float:
    return max(
        (c.get("score", -1) for c in item.get("candidates") or []), default=-1
    )


def rescue_low_scoring_cue(project_id: str, item: dict, topic: str = "") -> None:
    """One retry for cues where every candidate scored poorly.

    Uses the vision model's rejection reasons to ask for a better archival
    query, re-sources the cue, and keeps whichever candidate set scored
    higher. Bounded to a single retry per cue to keep autopilot predictable.
    """
    reasons = "; ".join(
        c.get("score_reason", "")
        for c in item.get("candidates") or []
        if c.get("score_reason")
    )
    prompt = f"""
# Role: Photo Researcher

An image search for a documentary beat about "{topic}" returned only poor
candidates. Suggest ONE better search query (3-6 words, concrete
nouns/places, English) for a photo archive — anchored to the actual event,
its location or its era, never a symbolic object. Respond ONLY with JSON:
{{"query": "..."}}

## Picture brief
{item.get("cue", "")}

## Why the previous candidates were rejected
{reasons or "(no reasons available)"}

## Previous queries
{json.dumps(item.get("queries", {}))}
""".strip()
    try:
        suggestion = llm_bridge.generate_json(prompt)
        new_query = str((suggestion or {}).get("query", "")).strip()
    except Exception as exc:
        logger.warning(f"rescue query planning failed for {item.get('key')}: {exc}")
        return
    if not new_query:
        return

    logger.info(f"rescue re-search for {item['key']}: {new_query!r}")
    retry_item = {
        **item,
        "queries": {"archival": new_query, "stock": new_query},
        "candidates": gather_candidates_for_cue(
            project_id, f"{item['key']}r", {"archival": new_query, "stock": new_query}
        ),
    }
    retry_item["selected"] = 0 if retry_item["candidates"] else None
    score_candidates(retry_item, topic)
    if _best_score(retry_item) > _best_score(item):
        item.update(
            {
                "queries": retry_item["queries"],
                "candidates": retry_item["candidates"],
                "selected": retry_item["selected"],
            }
        )


# ------------------------------------------------------------------- stages
def build_items_from_script(script: dict) -> list[dict]:
    items = []
    for section_idx, section in enumerate(script.get("sections", [])):
        for para_idx, paragraph in enumerate(section.get("paragraphs", [])):
            items.append(
                {
                    "key": f"s{section_idx}p{para_idx}",
                    "section": section.get("name", f"section{section_idx}"),
                    "text_preview": str(paragraph.get("text", ""))[:400],
                    "cue": str(paragraph.get("image_cue", "")).strip()
                    or str(paragraph.get("text", ""))[:60],
                }
            )
    return items


def run_image_sourcing(project: dict) -> dict:
    """Source candidates for every paragraph cue and persist images.json."""
    project_id = project["project_id"]
    script = store.load_script(project_id)
    if not script:
        raise RuntimeError("script missing; approve a script first")

    topic = project.get("topic", "")
    items = build_items_from_script(script)
    planned = plan_image_queries(topic, items)

    for item in items:
        item["queries"] = _queries_for(item, planned)
        item["candidates"] = gather_candidates_for_cue(
            project_id, item["key"], item["queries"]
        )
        item["selected"] = 0 if item["candidates"] else None
        score_candidates(item, topic)
        if 0 <= _best_score(item) < RESCUE_SCORE_THRESHOLD:
            rescue_low_scoring_cue(project_id, item, topic)
        logger.info(
            f"cue {item['key']}: {len(item['candidates'])} candidates, "
            f"selected #{item['selected']}, best score {_best_score(item):.1f} "
            f"({item['queries']})"
        )

    images = {"items": items}
    store.save_images(project_id, images)
    missing = [item["key"] for item in items if not item["candidates"]]
    if missing:
        logger.warning(f"no candidates found for cues: {missing}")
    return images


def research_cue(project_id: str, key: str, query: str) -> dict:
    """Re-search a single cue with a user-edited query (both lanes)."""
    project = store.load_project(project_id) or {}
    images = store.load_images(project_id) or {"items": []}
    for item in images["items"]:
        if item["key"] == key:
            item["queries"] = {"archival": query, "stock": query}
            item["candidates"] = gather_candidates_for_cue(
                project_id, key, item["queries"]
            )
            item["selected"] = 0 if item["candidates"] else None
            score_candidates(item, project.get("topic", ""))
            break
    store.save_images(project_id, images)
    return images


def selected_image_path(item: dict) -> str:
    """Resolve the chosen image file for a cue ('' when nothing usable)."""
    selected = item.get("selected")
    if isinstance(selected, dict):
        path = selected.get("custom", "")
        return path if path and os.path.exists(path) else ""
    if isinstance(selected, int) and 0 <= selected < len(item.get("candidates", [])):
        path = item["candidates"][selected].get("local_path", "")
        return path if path and os.path.exists(path) else ""
    return ""


def secondary_image_path(item: dict | None, min_score: float = 5.0) -> str:
    """A decent second image for a long beat: best-scored unused candidate."""
    if not item:
        return ""
    primary = selected_image_path(item)
    best_path, best_score = "", min_score - 0.001
    for index, candidate in enumerate(item.get("candidates", [])):
        path = candidate.get("local_path", "")
        score = float(candidate.get("score", -1) or -1)
        if (
            path
            and path != primary
            and os.path.exists(path)
            and score > best_score
        ):
            best_path, best_score = path, score
    return best_path


def credits_block(images: dict) -> str:
    """Attribution lines for the video description (some CC licenses need it)."""
    lines = []
    seen = set()
    for item in images.get("items", []):
        selected = item.get("selected")
        if not isinstance(selected, int):
            continue
        candidates = item.get("candidates", [])
        if not (0 <= selected < len(candidates)):
            continue
        candidate = candidates[selected]
        credit = json.dumps(
            [candidate.get("creator"), candidate.get("page_url")], sort_keys=True
        )
        if credit in seen:
            continue
        seen.add(credit)
        parts = [
            candidate.get("title") or "Photo",
            f"by {candidate['creator']}" if candidate.get("creator") else "",
            f"({candidate['license']})" if candidate.get("license") else "",
            candidate.get("page_url", ""),
        ]
        lines.append(" ".join(p for p in parts if p))
    return "\n".join(lines)
