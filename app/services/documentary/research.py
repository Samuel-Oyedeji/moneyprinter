"""Web-grounded research for documentary projects.

The niche (Nigerian / West African disasters and dark history) is exactly
where LLM training data is thinnest, so scripts must never be written from
model memory. This module searches the web via SerpApi, fetches and extracts
the most relevant pages, and distills them into a fact sheet where every
claim carries its source URLs and a confidence level. The scriptwriter is
then constrained to that fact sheet.
"""

import re
from urllib.parse import urlparse

import requests
from loguru import logger

from app.config import config
from app.services.documentary import llm_bridge, store, webtext

SERPAPI_ENDPOINT = "https://serpapi.com/search.json"
MAX_QUERIES = 5
MAX_SOURCES = 8
MAX_SOURCE_CHARS = 9000
MIN_SOURCE_CHARS = 300
FETCH_TIMEOUT = 20
FETCH_BYTE_CAP = 3 * 1024 * 1024

_USER_AGENT = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/126.0 Safari/537.36"
)

# Domains that consistently carry primary coverage for this niche. Boosting
# them counters the tendency of general Google results to surface aggregator
# and listicle sites above Nigerian newspapers of record.
_PRIORITY_DOMAINS = {
    "en.wikipedia.org": 3.0,
    "punchng.com": 2.0,
    "vanguardngr.com": 2.0,
    "guardian.ng": 2.0,
    "premiumtimesng.com": 2.0,
    "thenationonlineng.net": 1.5,
    "dailytrust.com": 1.5,
    "bbc.com": 1.5,
    "bbc.co.uk": 1.5,
    "reuters.com": 1.5,
    "aljazeera.com": 1.2,
    "theguardian.com": 1.2,
    "nytimes.com": 1.2,
}

_BLOCKED_DOMAINS = {
    # Video/social results are useless as text sources.
    "youtube.com",
    "www.youtube.com",
    "m.youtube.com",
    "facebook.com",
    "www.facebook.com",
    "x.com",
    "twitter.com",
    "www.tiktok.com",
    "tiktok.com",
    "instagram.com",
    "www.instagram.com",
    "reddit.com",
    "www.reddit.com",
    "pinterest.com",
    "www.pinterest.com",
}

FACTSHEET_SECTIONS = (
    "background",
    "timeline",
    "the_event",
    "casualties_and_aftermath",
    "investigation",
    "legacy",
)


def _serpapi_key() -> str:
    key = str(config.documentary.get("serpapi_api_key", "") or "").strip()
    if not key:
        raise ValueError(
            "documentary.serpapi_api_key is not set; add it to config.toml "
            "under the [documentary] section."
        )
    return key


def plan_queries(topic: str, user_notes: str) -> list[str]:
    """Ask the LLM for search queries, then add deterministic staples."""
    prompt = f"""
# Role: Research Query Planner

You are planning web searches to research a historical disaster or dark
historical event in Nigeria / West Africa for a documentary.

## Constraints
1. Respond ONLY with a JSON array of 3 to {MAX_QUERIES} search query strings.
2. Queries must target: the event itself, casualty figures and official
   reports, the investigation/inquiry findings, and survivor/witness accounts.
3. Prefer specific queries (names, places, years) over generic ones.
4. English queries only. No hashtags, no quotes around whole queries.

## Topic
{topic}

## Background notes from the producer (may be empty)
{user_notes or "(none)"}
""".strip()

    queries: list[str] = []
    try:
        planned = llm_bridge.generate_json(prompt)
        if isinstance(planned, list):
            queries = [str(q).strip() for q in planned if str(q).strip()]
    except Exception as exc:
        logger.warning(f"query planning failed, using fallback queries: {exc}")

    staples = [topic, f"{topic} site:en.wikipedia.org"]
    merged: list[str] = []
    for query in staples + queries:
        if query.lower() not in {m.lower() for m in merged}:
            merged.append(query)
    return merged[: MAX_QUERIES + len(staples)]


def _serpapi_search(query: str, engine: str) -> list[dict]:
    params = {
        "engine": engine,
        "q": query,
        "api_key": _serpapi_key(),
        "num": 10,
    }
    try:
        response = requests.get(SERPAPI_ENDPOINT, params=params, timeout=30)
        response.raise_for_status()
        data = response.json()
    except Exception as exc:
        logger.warning(f"serpapi search failed for {query!r} ({engine}): {exc}")
        return []

    results = data.get("organic_results") or data.get("news_results") or []
    items = []
    for position, result in enumerate(results):
        link = result.get("link") or ""
        if not link:
            continue
        items.append(
            {
                "url": link,
                "title": result.get("title", ""),
                "snippet": result.get("snippet", ""),
                "position": position,
                "engine": engine,
                "query": query,
            }
        )
    return items


def _domain(url: str) -> str:
    try:
        return (urlparse(url).netloc or "").lower().removeprefix("www.")
    except ValueError:
        return ""


def _score(candidate: dict) -> float:
    domain_boost = _PRIORITY_DOMAINS.get(_domain(candidate["url"]), 1.0)
    position_score = 1.0 / (1 + candidate["position"])
    return domain_boost * (0.5 + position_score)


def gather_candidates(queries: list[str]) -> list[dict]:
    seen: dict[str, dict] = {}
    for query in queries:
        for engine in ("google", "google_news"):
            for item in _serpapi_search(query, engine):
                if _domain(item["url"]) in _BLOCKED_DOMAINS:
                    continue
                key = item["url"].split("#")[0].rstrip("/")
                # Keep the best-positioned sighting of each URL.
                if key not in seen or item["position"] < seen[key]["position"]:
                    seen[key] = item
    candidates = sorted(seen.values(), key=_score, reverse=True)
    return candidates


def fetch_source(candidate: dict) -> dict | None:
    try:
        response = requests.get(
            candidate["url"],
            headers={"User-Agent": _USER_AGENT},
            timeout=FETCH_TIMEOUT,
            stream=True,
        )
        response.raise_for_status()
        content_type = response.headers.get("Content-Type", "")
        if "html" not in content_type and "text" not in content_type:
            return None
        raw = response.raw.read(FETCH_BYTE_CAP, decode_content=True)
        html = raw.decode(response.encoding or "utf-8", errors="replace")
    except Exception as exc:
        logger.warning(f"failed to fetch source {candidate['url']}: {exc}")
        return None

    text = webtext.html_to_text(html)
    if len(text) < MIN_SOURCE_CHARS:
        return None
    return {
        "url": candidate["url"],
        "title": candidate["title"],
        "domain": _domain(candidate["url"]),
        "text": text[:MAX_SOURCE_CHARS],
    }


def collect_sources(queries: list[str], max_sources: int = MAX_SOURCES) -> list[dict]:
    sources = []
    for candidate in gather_candidates(queries):
        if len(sources) >= max_sources:
            break
        source = fetch_source(candidate)
        if source:
            sources.append(source)
            logger.info(f"collected source: {source['domain']} - {source['title']}")
    return sources


def _factsheet_prompt(topic: str, user_notes: str, sources: list[dict]) -> str:
    source_blocks = []
    for index, source in enumerate(sources, start=1):
        source_blocks.append(
            f"### S{index} | {source['domain']} | {source['title']}\n{source['text']}"
        )
    sources_text = "\n\n".join(source_blocks)
    sections = ", ".join(f'"{s}"' for s in FACTSHEET_SECTIONS)

    return f"""
# Role: Documentary Researcher

You are building a fact sheet about a real historical event for a factual
documentary. Accuracy is paramount: this concerns a real tragedy with real
victims, and every claim will be traced back to sources during review.

## Hard rules
1. Use ONLY the numbered sources below and the producer's notes. Do NOT add
   anything from your own memory or general knowledge, even if you are
   confident it is true.
2. Every fact must cite the source labels (e.g. ["S1","S3"]) that support it.
3. Where sources disagree (death tolls, dates, causes), do NOT pick a winner:
   record the disagreement under "conflicting_reports".
4. Confidence: "high" = multiple independent sources agree; "medium" = one
   solid source; "low" = single passing mention or uncertain sourcing.
5. If the sources are too thin to support a section, leave its array empty.
6. Respond ONLY with a single valid JSON object. No markdown, no commentary.

## Output shape
{{
  "summary": "3-4 sentence neutral overview of the event",
  "sections": {{ {sections} — each an array of facts }},
  "conflicting_reports": [
    {{"issue": "...", "versions": [{{"claim": "...", "sources": ["S1"]}}]}}
  ],
  "open_questions": ["things the sources leave unclear"],
  "key_people": [{{"name": "...", "role": "..."}}]
}}
Each fact object: {{"claim": "one specific factual statement", "quote":
"short supporting quote from the source (<=25 words)", "sources": ["S1"],
"confidence": "high|medium|low"}}
"timeline" facts should start the claim with the date/time where known.

## Topic
{topic}

## Producer notes (treat as a source labeled "producer")
{user_notes or "(none)"}

## Sources
{sources_text}
""".strip()


def _attach_fact_ids(factsheet: dict, sources: list[dict]) -> dict:
    """Normalize the LLM fact sheet: stable fact ids and resolved source URLs."""
    label_to_url = {f"S{i}": s["url"] for i, s in enumerate(sources, start=1)}
    counter = 0
    sections = factsheet.get("sections") or {}
    for section in FACTSHEET_SECTIONS:
        facts = sections.get(section)
        if not isinstance(facts, list):
            sections[section] = []
            continue
        normalized = []
        for fact in facts:
            if not isinstance(fact, dict) or not str(fact.get("claim", "")).strip():
                continue
            counter += 1
            labels = [
                str(label) for label in (fact.get("sources") or []) if str(label)
            ]
            normalized.append(
                {
                    "id": f"F{counter}",
                    "claim": str(fact.get("claim", "")).strip(),
                    "quote": str(fact.get("quote", "")).strip(),
                    "sources": labels,
                    "source_urls": [
                        label_to_url[label]
                        for label in labels
                        if label in label_to_url
                    ],
                    "confidence": str(fact.get("confidence", "medium")).lower(),
                }
            )
        sections[section] = normalized
    factsheet["sections"] = sections
    factsheet["source_index"] = [
        {"label": f"S{i}", "url": s["url"], "title": s["title"], "domain": s["domain"]}
        for i, s in enumerate(sources, start=1)
    ]
    return factsheet


def run_research(project: dict) -> dict:
    """Full research pass: plan queries, collect sources, distill fact sheet.

    Raises on unrecoverable failures; the caller owns status transitions.
    """
    project_id = project["project_id"]
    topic = project["topic"]
    user_notes = project.get("user_notes", "")

    queries = plan_queries(topic, user_notes)
    logger.info(f"research queries for {project_id}: {queries}")

    sources = collect_sources(queries)
    if not sources:
        raise RuntimeError(
            "research found no usable web sources; check the SerpApi key, "
            "network access, or try a more specific topic."
        )
    store.save_sources(project_id, sources)

    factsheet = llm_bridge.generate_json(
        _factsheet_prompt(topic, user_notes, sources)
    )
    if not isinstance(factsheet, dict):
        raise RuntimeError("fact sheet generation returned a non-object response")

    factsheet = _attach_fact_ids(factsheet, sources)
    factsheet["queries"] = queries
    fact_count = sum(len(v) for v in factsheet["sections"].values())
    if fact_count == 0:
        raise RuntimeError(
            "the fact sheet came back empty; the collected sources likely do "
            "not cover this topic. Try refining the topic or adding notes."
        )
    logger.success(
        f"fact sheet for {project_id}: {fact_count} facts from "
        f"{len(sources)} sources"
    )
    store.save_factsheet(project_id, factsheet)
    return factsheet
