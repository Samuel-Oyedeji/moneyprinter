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

import json
import os

from loguru import logger

from app.config import config
from app.services.documentary import llm_bridge, store

TARGET_WORDS_MIN = 1400
TARGET_WORDS_MAX = 1800
MAX_EXEMPLAR_CHARS = 12000

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
{TARGET_WORDS_MIN}-{TARGET_WORDS_MAX} words of narration in total.
Paragraphs of 3-6 sentences; each paragraph is one visual beat.

## Image cues
For every paragraph, write "image_cue": a concrete stock/archive photo search
brief for that beat (place, era, subject, mood), e.g. "Lagos street scene,
early 2000s, archival news photo". Cues must depict settings, objects and
places — never identifiable victims or graphic injury.

## Output
Respond ONLY with a single valid JSON object, no markdown fences:
{{
  "title": "working title for the film",
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


def _validate_script(script: dict) -> tuple[int, list[str]]:
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

    if word_count < TARGET_WORDS_MIN * 0.7:
        problems.append(f"script too short: {word_count} words")
    return word_count, problems


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
    script = llm_bridge.generate_json(_script_prompt(project, factsheet))
    if not isinstance(script, dict):
        raise RuntimeError("script generation returned a non-object response")

    word_count, problems = _validate_script(script)
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
        word_count, problems = _validate_script(script)
        if problems:
            raise RuntimeError(f"script failed validation: {problems}")

    script["word_count"] = word_count
    logger.success(f"script for {project_id}: {word_count} words")
    store.save_script(project_id, script)
    return script
