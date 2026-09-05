"""Web-grounded research for documentary projects.

The niche (Nigerian / West African disasters and dark history) is exactly
where LLM training data is thinnest, so scripts must never be written from
model memory. This module searches the web via SerpApi, fetches and extracts
the most relevant pages, and distills them into a fact sheet where every
claim carries its source URLs and a confidence level. The scriptwriter is
then constrained to that fact sheet.
"""

import time
from urllib.parse import urlparse

import requests
from loguru import logger

from app.config import config
from app.services.documentary import costs, llm_bridge, store, webtext

SERPAPI_ENDPOINT = "https://serpapi.com/search.json"
SERPAPI_ACCOUNT_ENDPOINT = "https://serpapi.com/account"
QUOTA_WARN_THRESHOLD = 20  # one research run is ~14 searches


class SerpApiQuotaError(RuntimeError):
    """SerpApi key has no searches left (or is invalid)."""
MAX_QUERIES = 5
MAX_SOURCES = 8
MAX_SOURCE_CHARS = 9000
MIN_SOURCE_CHARS = 300
FETCH_TIMEOUT = 20
FETCH_BYTE_CAP = 3 * 1024 * 1024
# Search results run to ~140 unique URLs. Walking all of them at FETCH_TIMEOUT
# each is 45+ minutes of a stalled research stage on a slow network, and the
# useful sources are near the top of the ranking anyway — so the walk stops on
# whichever bound is hit first.
MAX_FETCH_ATTEMPTS = 30
FETCH_BUDGET_SECONDS = 240

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


def get_quota(api_key: str | None = None) -> dict | None:
    """Ask SerpApi how many searches the key has left.

    The /account endpoint is free (it does not consume a search). Returns
    {"left", "per_month", "used"} on success, {"error": ...} for an invalid
    key, and None when the key is unset or the endpoint is unreachable.
    """
    key = (api_key or "").strip() or str(
        config.documentary.get("serpapi_api_key", "") or ""
    ).strip()
    if not key:
        return None
    try:
        response = requests.get(
            SERPAPI_ACCOUNT_ENDPOINT, params={"api_key": key}, timeout=15
        )
        if response.status_code in (401, 403):
            return {"error": "SerpApi rejected this API key"}
        response.raise_for_status()
        data = response.json()
    except Exception as exc:
        logger.warning(f"serpapi quota check failed: {exc}")
        return None

    left = data.get("total_searches_left", data.get("plan_searches_left"))
    return {
        "left": int(left) if left is not None else None,
        "per_month": data.get("searches_per_month"),
        "used": data.get("this_month_usage"),
    }


def check_quota_guardrail() -> None:
    """Raise before a research run that has no searches to work with."""
    quota = get_quota()
    if quota is None:
        return  # unreachable endpoint shouldn't block research outright
    if quota.get("error"):
        raise SerpApiQuotaError(
            f"{quota['error']} — update documentary.serpapi_api_key in the "
            "research settings and refresh the quota."
        )
    left = quota.get("left")
    if left is None:
        return
    if left <= 0:
        raise SerpApiQuotaError(
            "The SerpApi key has 0 searches left. Change or top up the key "
            "in the research settings, then refresh the quota."
        )
    if left < QUOTA_WARN_THRESHOLD:
        logger.warning(
            f"SerpApi quota is low: {left} searches left (a research run "
            f"uses ~14)"
        )


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


def _serpapi_search(query: str, engine: str, stats: dict | None = None) -> list[dict]:
    params = {
        "engine": engine,
        "q": query,
        "api_key": _serpapi_key(),
        "num": 10,
    }
    try:
        response = requests.get(SERPAPI_ENDPOINT, params=params, timeout=30)
        try:
            data = response.json()
        except ValueError:
            data = {}
        # A mid-run quota exhaustion must stop the whole research pass loudly
        # instead of degrading into "no usable web sources".
        error_text = str(data.get("error", ""))
        if "run out of searches" in error_text.lower():
            raise SerpApiQuotaError(
                "The SerpApi key ran out of searches mid-run. Change or top "
                "up the key in the research settings, then retry."
            )
        response.raise_for_status()
        costs.record_serpapi(f"{engine}: {query}")
    except SerpApiQuotaError:
        raise
    except Exception as exc:
        # A dropped search is silent data loss: the fact sheet still gets
        # built, just from a fraction of the planned coverage. Count it so
        # the run can say so instead of quietly degrading.
        logger.warning(f"serpapi search failed for {query!r} ({engine}): {exc}")
        if stats is not None:
            stats["searches_failed"] = stats.get("searches_failed", 0) + 1
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


def gather_candidates(queries: list[str], stats: dict | None = None) -> list[dict]:
    seen: dict[str, dict] = {}
    for query in queries:
        for engine in ("google", "google_news"):
            if stats is not None:
                stats["searches"] = stats.get("searches", 0) + 1
            for item in _serpapi_search(query, engine, stats):
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


def collect_sources(
    queries: list[str],
    max_sources: int = MAX_SOURCES,
    stats: dict | None = None,
) -> list[dict]:
    """Fetch the best-ranked candidates until enough sources, or a bound, hit."""
    sources: list[dict] = []
    deadline = time.monotonic() + FETCH_BUDGET_SECONDS
    attempts = 0
    candidates = gather_candidates(queries, stats)
    for candidate in candidates:
        if len(sources) >= max_sources:
            break
        if attempts >= MAX_FETCH_ATTEMPTS:
            logger.warning(
                f"stopped fetching after {attempts} candidates with "
                f"{len(sources)} usable sources"
            )
            break
        if time.monotonic() > deadline:
            logger.warning(
                f"source fetching hit the {FETCH_BUDGET_SECONDS}s budget with "
                f"{len(sources)} usable sources"
            )
            break
        attempts += 1
        source = fetch_source(candidate)
        if source:
            sources.append(source)
            logger.info(f"collected source: {source['domain']} - {source['title']}")
    if stats is not None:
        stats["candidates"] = len(candidates)
        stats["fetch_attempts"] = attempts
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


def _research_warnings(stats: dict, sources: list[dict]) -> list[str]:
    """Human-readable notes about coverage this run did not manage to get."""
    warnings = []
    failed = stats.get("searches_failed", 0)
    planned = stats.get("searches", 0)
    if failed:
        warnings.append(
            f"{failed} of {planned} web searches failed (SerpApi was slow or "
            f"unreachable), so this fact sheet was built from partial search "
            f"coverage. Re-running research may find more."
        )
    attempts = stats.get("fetch_attempts", 0)
    if attempts >= MAX_FETCH_ATTEMPTS and len(sources) < MAX_SOURCES:
        warnings.append(
            f"Only {len(sources)} of {MAX_SOURCES} sources could be fetched "
            f"within {attempts} attempts; the rest timed out or were "
            f"unreadable."
        )
    return warnings


def run_research(project: dict) -> dict:
    """Full research pass: plan queries, collect sources, distill fact sheet.

    Raises on unrecoverable failures; the caller owns status transitions.
    """
    project_id = project["project_id"]
    topic = project["topic"]
    user_notes = project.get("user_notes", "")

    check_quota_guardrail()
    queries = plan_queries(topic, user_notes)
    logger.info(f"research queries for {project_id}: {queries}")

    stats: dict = {}
    sources = collect_sources(queries, stats=stats)
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
    factsheet["research_warnings"] = _research_warnings(stats, sources)
    fact_count = sum(len(v) for v in factsheet["sections"].values())
    if fact_count == 0:
        raise RuntimeError(
            "the fact sheet came back empty; the collected sources likely do "
            "not cover this topic. Try refining the topic or adding notes."
        )
    for warning in factsheet["research_warnings"]:
        logger.warning(f"research warning for {project_id}: {warning}")
    logger.success(
        f"fact sheet for {project_id}: {fact_count} facts from "
        f"{len(sources)} sources"
    )
    store.save_factsheet(project_id, factsheet)
    return factsheet
