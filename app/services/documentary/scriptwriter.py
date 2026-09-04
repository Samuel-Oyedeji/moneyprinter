"""Script generation for documentary projects.

Generates a long-form narration script in a restrained, traditional
documentary register (hybrid structure: a vivid but strictly factual cold
open, then an understated chronological body). The script is written ONLY
from the reviewed fact sheet — the model is instructed to hedge or omit
where the facts are thin, mirroring how serious documentary channels handle
uncertainty.

The style is described by an original in-code spec. Optionally, a local
transcript file (documentary.style_exemplar_path in config.toml) is injected
verbatim at runtime as a few-shot exemplar; it is deliberately not shipped
with the codebase.
"""

import hashlib
import json
import os
import re

from loguru import logger

from app.config import config
from app.services.documentary import llm_bridge, store

TARGET_WORDS_MIN = 1400
TARGET_WORDS_MAX = 1800
NARRATION_WORDS_PER_MINUTE = 150
MAX_EXEMPLAR_CHARS = 12000


def _target_words(project: dict) -> tuple[int, int]:
    """Word budget from the project's target length (default ~10-12 min)."""
    minutes = float(project.get("target_minutes") or 0.0)
    if minutes <= 0:
        return TARGET_WORDS_MIN, TARGET_WORDS_MAX
    center = minutes * NARRATION_WORDS_PER_MINUTE
    return int(center * 0.9), int(center * 1.1)

STYLE_SPEC = """
## Narrative voice and style (follow strictly)
- Register: calm, measured, formal-but-plain narration in the tradition of
  understated historical documentaries. The horror must come from the facts
  and their quiet accumulation, never from adjectives or exclamation.
- Tense: past tense throughout the body. Dates written out in the pattern
  "On the 21st of April, 1930". Numbers stated plainly.
- Never address the viewer. No "you", no "imagine", no "subscribe", no
  questions to the audience, no references to "this video".
- No sensational vocabulary ("horrific", "unbelievable", "shocking",
  "nightmare"). Prefer institutional phrasing: "It was found that...",
  "By many accounts...", "The response was not immediate."
- Blame is conveyed by selecting and ordering facts, never by editorializing.
- Where the fact sheet is uncertain or conflicting, hedge honestly:
  "Reports of the death toll varied...", "The exact cause was never
  established." Never invent specifics to fill a gap.
- Use one or two short witness/official quotes at most, only if they appear
  in the fact sheet, introduced plainly ("one witness recalled...").
- Dramatic irony is the signature move of the cold open: describe a small,
  ordinary moment, then reveal quietly that it preceded catastrophe.
- Punctuate for the ear, not the page: this text will be read aloud.
  Prefer several shorter sentences over one long one; use an ellipsis
  ("...") where the narrator should pause before a reveal or between
  beats; use an em dash for an aside. A paragraph should never read as
  one unbroken breath.

## Structure
1. COLD OPEN (2-3 paragraphs, may use present tense for the first paragraph
   only): a specific dated scene drawn from the timeline facts, vivid but
   strictly factual, ending on the understated reveal of what was to come.
2. BACKGROUND: the place/institution/system — its history and how it worked,
   why conditions were as they were.
3. THE DAY: return to the date; normality, then chronological escalation
   with precise times where the facts provide them.
4. THE DISASTER: the event itself, sequential and procedural; the small
   failures compounding.
5. AFTERMATH: casualties stated plainly, rescue and recovery logistics.
6. INVESTIGATION: causes and findings, systemic failures enumerated
   matter-of-factly.
7. LEGACY: reforms, memorials, what stands there today; one measured closing
   sentence.
""".strip()


def _style_exemplar() -> str:
    path = str(config.documentary.get("style_exemplar_path", "") or "").strip()
    if not path:
        return ""
    try:
        with open(os.path.expanduser(path), "r", encoding="utf-8") as f:
            text = f.read().strip()
    except OSError as exc:
        logger.warning(f"could not read style exemplar {path}: {exc}")
        return ""
    if not text:
        return ""
    return (
        "\n## Style exemplar\nThe following is a transcript in exactly the "
        "target register. Match its tone, pacing and sentence rhythm — but "
        "never its facts:\n---\n" + text[:MAX_EXEMPLAR_CHARS] + "\n---\n"
    )


def _compact_factsheet(factsheet: dict) -> str:
    """Serialize the fact sheet for the prompt, dropping bulky bookkeeping."""
    slim = {
        "summary": factsheet.get("summary", ""),
        "sections": {},
        "conflicting_reports": factsheet.get("conflicting_reports", []),
        "open_questions": factsheet.get("open_questions", []),
        "key_people": factsheet.get("key_people", []),
    }
    for section, facts in (factsheet.get("sections") or {}).items():
        slim["sections"][section] = [
            {
                "id": fact.get("id"),
                "claim": fact.get("claim"),
                "quote": fact.get("quote", ""),
                "confidence": fact.get("confidence", "medium"),
            }
            for fact in facts
        ]
    return json.dumps(slim, ensure_ascii=False, indent=1)


def _script_prompt(project: dict, factsheet: dict) -> str:
    words_min, words_max = _target_words(project)
    return f"""
# Role: Documentary Scriptwriter

Write a long-form narration script about a real historical event, for a
documentary told over still photographs. This concerns a real tragedy with
real victims: factual discipline and a respectful tone are non-negotiable.

{STYLE_SPEC}
{_style_exemplar()}
## Hard factual rules
1. Every factual statement in the script must be supported by a fact in the
   fact sheet below. Do not add names, numbers, dates, causes or details
   from your own knowledge — if it is not in the fact sheet, it does not go
   in the script.
2. Prefer "high" confidence facts. Facts marked "low" may only appear with
   hedging ("according to some reports...").
3. For entries in conflicting_reports, present the disagreement honestly.
4. Each paragraph lists the fact ids it draws on in "fact_ids".

## Length
{words_min}-{words_max} words of narration in total.
Paragraphs of 3-6 sentences; each paragraph is one visual beat. For short
films, compress the structure (fewer paragraphs per section) rather than
writing shorter paragraphs.

## Image cues
For every paragraph, write "image_cue": a concrete stock/archive photo search
brief for that beat (place, era, subject, mood), e.g. "Lagos street scene,
early 2000s, archival news photo". Cues must depict settings, objects and
places — never identifiable victims or graphic injury.

## Output
Respond ONLY with a single valid JSON object, no markdown fences:
{{
  "title": "working title for the film",
  "intro": {{
    "title": "short on-screen title card: the event's name, <=6 words",
    "date_line": "place and date line, e.g. 'Lagos, Nigeria — 27 January 2002'"
  }},
  "sections": [
    {{"name": "cold_open|background|the_day|the_disaster|aftermath|investigation|legacy",
      "paragraphs": [
        {{"text": "narration...", "image_cue": "...", "fact_ids": ["F1","F4"]}}
      ]}}
  ],
  "youtube": {{
    "title": "YouTube title, compelling but not clickbait, <=90 chars",
    "description": "2-3 sentence description",
    "tags": ["8-12 relevant tags"]
  }}
}}

## Topic
{project["topic"]}

## Fact sheet (your ONLY source of facts)
{_compact_factsheet(factsheet)}
""".strip()


def _validate_script(
    script: dict,
    words_min: int = TARGET_WORDS_MIN,
    words_max: int = TARGET_WORDS_MAX,
) -> tuple[int, list[str]]:
    problems = []
    sections = script.get("sections")
    if not isinstance(sections, list) or not sections:
        return 0, ["script has no sections"]

    word_count = 0
    for section in sections:
        paragraphs = section.get("paragraphs") if isinstance(section, dict) else None
        if not isinstance(paragraphs, list):
            problems.append(f"section {section!r:.40} has no paragraphs")
            continue
        for paragraph in paragraphs:
            text = str(paragraph.get("text", "")).strip()
            if not text:
                problems.append("empty paragraph text")
                continue
            word_count += len(text.split())
            if not str(paragraph.get("image_cue", "")).strip():
                problems.append(f"missing image_cue for: {text[:50]}...")

    if word_count < words_min * 0.7:
        problems.append(f"script too short: {word_count} words")
    if word_count > words_max * 1.2:
        problems.append(
            f"script too long: {word_count} words (target at most {words_max}); "
            "cut whole paragraphs, do not compress sentences"
        )
    return word_count, problems


# ------------------------------------------------------------------ prosody
def _word_signature(text: str) -> list[str]:
    return re.findall(r"[a-z0-9]+", text.lower())


def _iter_paragraphs(script: dict):
    for section in script.get("sections", []):
        for paragraph in section.get("paragraphs", []):
            yield paragraph


def ensure_prosody(project_id: str, script: dict) -> None:
    """Give every paragraph a TTS-ready twin punctuated for breathing room.

    TTS engines pause on punctuation, so long FH paragraphs read as one
    unbroken breath unless the text is re-punctuated for the ear: ellipses
    between beats, run-ons split into shorter sentences, dashes for asides.
    The rewritten text goes in paragraph["tts_text"] and feeds narration
    only — the reviewed script text and subtitles stay as written. Cached by
    a hash of the source text, so edits re-trigger just their paragraphs.
    """
    pending = []
    for index, paragraph in enumerate(_iter_paragraphs(script)):
        text = str(paragraph.get("text", "")).strip()
        if not text:
            continue
        text_hash = hashlib.md5(text.encode()).hexdigest()[:12]
        if (
            paragraph.get("tts_text")
            and paragraph.get("tts_source_hash") == text_hash
        ):
            continue
        pending.append((f"p{index}", text_hash, paragraph))
    if not pending:
        return

    listing = "\n\n".join(f"[{pid}]\n{p['text']}" for pid, _, p in pending)
    prompt = f"""
# Role: Narration Prosody Editor

The paragraphs below will be read aloud by a text-to-speech narrator for a
calm, measured documentary. TTS pauses ONLY on punctuation, so re-punctuate
each paragraph for natural breathing room.

## Hard rules
1. Do NOT add, remove, reorder or change any words. Punctuation and
   spacing only. Numbers, names and spellings stay exactly as written.
2. Split long or run-on sentences into shorter ones with full stops.
3. Insert an ellipsis ("...") where the narrator should take a real pause:
   before a quiet reveal, between distinct beats, after a scene-setting
   opener. One to three per long paragraph; short paragraphs may need none.
4. Use an em dash ( — ) for asides; a question mark where a sentence is
   genuinely a question.
5. Do not overdo it — the aim is a human breathing pattern, not drama.

## Output
Respond ONLY with a JSON object mapping each id to its re-punctuated text:
{{"p0": "...", "p3": "..."}}

## Paragraphs
{listing}
""".strip()

    try:
        rewritten = llm_bridge.generate_json(prompt)
        if not isinstance(rewritten, dict):
            raise ValueError("prosody response is not an object")
    except Exception as exc:
        logger.warning(f"prosody pass failed, narrating original text: {exc}")
        return

    applied = 0
    for pid, text_hash, paragraph in pending:
        candidate = str(rewritten.get(pid, "")).strip()
        if candidate and _word_signature(candidate) == _word_signature(
            paragraph["text"]
        ):
            paragraph["tts_text"] = candidate
            paragraph["tts_source_hash"] = text_hash
            applied += 1
        else:
            # Word content changed or the paragraph is missing: narrate the
            # original rather than risk altered facts.
            logger.warning(f"prosody rewrite rejected for {pid}")
            paragraph["tts_text"] = paragraph["text"]
            paragraph["tts_source_hash"] = text_hash
    store.save_script(project_id, script)
    logger.info(f"prosody pass applied to {applied}/{len(pending)} paragraphs")


def ensure_youtube_description(
    project_id: str, script: dict, regenerate: bool = False
) -> str:
    """Write a proper YouTube description from the finished film.

    The scriptwriter's inline description tends to read like the opening of
    the narration; this dedicated pass writes actual publishing copy — a
    hook line, then what the film covers — and caches it on the script.
    """
    youtube_meta = script.setdefault("youtube", {})
    if youtube_meta.get("description_enhanced") and not regenerate:
        return youtube_meta.get("description", "")

    narration = full_narration_text(script)[:6000]
    prompt = f"""
# Role: YouTube Copywriter for a Historical Documentary Channel

Write the video description for the documentary below. This is publishing
copy, not narration: do NOT reuse or paraphrase the film's opening lines.

## Rules
1. First line: a compelling, factual hook, at most 110 characters — this
   is what viewers see before "show more". No clickbait, no all-caps.
2. Then 2 short paragraphs (60-90 words total): what happened, and what
   the film covers — the build-up, the disaster, the investigation, the
   legacy. Written to intrigue, not to summarize away the whole story.
3. Tone: respectful and measured; real people died in this event.
4. No emojis, no hashtags, no links, no "subscribe" begging. A single
   quiet closing line inviting viewers to watch is fine.
5. Respond ONLY with JSON: {{"description": "..."}}

## Film title
{youtube_meta.get("title", script.get("title", ""))}

## Narration (for facts only — do not copy its wording)
{narration}
""".strip()

    try:
        result = llm_bridge.generate_json(prompt)
        description = str((result or {}).get("description", "")).strip()
    except Exception as exc:
        logger.warning(f"description generation failed, keeping existing: {exc}")
        return youtube_meta.get("description", "")
    if not description:
        return youtube_meta.get("description", "")

    youtube_meta["description"] = description
    youtube_meta["description_enhanced"] = True
    store.save_script(project_id, script)
    logger.success(f"youtube description written for {project_id}")
    return description


def full_narration_text(script: dict) -> str:
    """Concatenate all paragraph texts — the input for TTS in phase 2."""
    paragraphs = []
    for section in script.get("sections", []):
        for paragraph in section.get("paragraphs", []):
            text = str(paragraph.get("text", "")).strip()
            if text:
                paragraphs.append(text)
    return "\n\n".join(paragraphs)


def run_scriptwriting(project: dict, factsheet: dict) -> dict:
    """Generate the script from the (reviewed) fact sheet and persist it."""
    project_id = project["project_id"]
    words_min, words_max = _target_words(project)
    script = llm_bridge.generate_json(_script_prompt(project, factsheet))
    if not isinstance(script, dict):
        raise RuntimeError("script generation returned a non-object response")

    word_count, problems = _validate_script(script, words_min, words_max)
    if problems:
        # One corrective retry with the problems spelled out; models fix
        # structural misses reliably when told exactly what was wrong.
        logger.warning(f"script validation issues, retrying once: {problems}")
        retry_prompt = (
            _script_prompt(project, factsheet)
            + "\n\n## Previous attempt was rejected for these problems — fix"
            " them all:\n- "
            + "\n- ".join(problems)
        )
        script = llm_bridge.generate_json(retry_prompt)
        word_count, problems = _validate_script(script, words_min, words_max)
        if problems:
            raise RuntimeError(f"script failed validation: {problems}")

    script["word_count"] = word_count
    logger.success(f"script for {project_id}: {word_count} words")
    store.save_script(project_id, script)
    return script
