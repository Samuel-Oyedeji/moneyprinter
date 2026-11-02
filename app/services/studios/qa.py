"""Quality checks on a finished studio video, before it may be uploaded.

Cheap mechanical checks run first; the model-based critic only runs when
they all pass. Each failed check names the fix the runner should try once:

    render   re-render (picture faults)
    voice    re-record the narration (sound faults, narration ≠ script)
    script   rewrite from the script on (length far off, a false claim, a rule broken)
    package  rewrite the YouTube title and description
    reserve  drop this video and use a reserve topic (topic now repeats)
    stop     drop it and flag it (cost overrun)

One ffmpeg pass measures the file: duration, streams, loudness, silences,
black and frozen stretches. Paper animations always "boil" a little, so a
frozen stretch only counts from FREEZE_SECONDS.
"""

import re
import subprocess

from loguru import logger

from app.utils import utils

DURATION_SLACK = 0.4  # ±40% of the brief's length
MIN_MEAN_VOLUME_DB = -40.0  # quieter than this: no narration to speak of
SILENCE_SECONDS = 2.0
BLACK_SECONDS = 1.0
FREEZE_SECONDS = 5.0
NARRATION_MATCH = 0.95
MAX_VIDEO_COST = 1.00
CAPS_WORD = re.compile(r"\b[A-Z]{5,}\b")  # NASA and DNA are fine; SHOCKING is not
BANNED_TITLE_PHRASES = (
    "you won't believe", "you wont believe", "gone wrong", "insane", "shocking", "must see", "!!", "??",
)

FIX_ORDER = ("stop", "reserve", "script", "voice", "render", "package")  # most drastic wins


# ------------------------------------------------------------------- ffmpeg
def probe(path: str) -> str:
    """ffmpeg's log for one decode pass with the measuring filters."""
    command = [
        utils.get_ffmpeg_binary(), "-hide_banner", "-nostats", "-i", path,
        "-vf", f"blackdetect=d={BLACK_SECONDS}:pix_th=0.10,freezedetect=n=0.003:d={FREEZE_SECONDS}",
        "-af", f"silencedetect=noise=-50dB:d={SILENCE_SECONDS},volumedetect",
        "-f", "null", "-",
    ]
    result = subprocess.run(command, capture_output=True, text=True, timeout=600)
    return result.stderr


def parse_probe(log: str) -> dict:
    """Numbers from an ffmpeg log (pure, so it can be tested on samples)."""
    duration = 0.0
    match = re.search(r"Duration: (\d+):(\d+):(\d+(?:\.\d+)?)", log)
    if match:
        hours, minutes, seconds = match.groups()
        duration = int(hours) * 3600 + int(minutes) * 60 + float(seconds)

    def floats(pattern):
        return [float(x) for x in re.findall(pattern, log)]

    mean = floats(r"mean_volume: (-?[\d.]+) dB")
    peak = floats(r"max_volume: (-?[\d.]+) dB")
    return {
        "duration": round(duration, 2),
        "has_video": bool(re.search(r"Stream #\d+:\d+.*: Video:", log)),
        "has_audio": bool(re.search(r"Stream #\d+:\d+.*: Audio:", log)),
        "mean_volume_db": mean[-1] if mean else None,
        "max_volume_db": peak[-1] if peak else None,
        "silences": floats(r"silence_duration: ([\d.]+)"),
        "black": floats(r"black_duration:([\d.]+)"),
        "frozen": floats(r"lavfi\.freezedetect\.freeze_duration: ([\d.]+)"),
    }


# ------------------------------------------------------------------- checks
def _check(name: str, ok: bool, detail: str, fix: str = "") -> dict:
    return {"name": name, "ok": bool(ok), "detail": detail, "fix": "" if ok else fix}


def media_checks(info: dict, planned_seconds: float) -> list[dict]:
    checks = [
        _check(
            "file",
            info["duration"] > 0 and info["has_video"] and info["has_audio"],
            f"{info['duration']}s, video {'yes' if info['has_video'] else 'MISSING'}, audio {'yes' if info['has_audio'] else 'MISSING'}",
            "render",
        )
    ]
    if not checks[0]["ok"]:
        return checks
    low, high = planned_seconds * (1 - DURATION_SLACK), planned_seconds * (1 + DURATION_SLACK)
    checks.append(
        _check("length", low <= info["duration"] <= high, f"{info['duration']:.0f}s for a {planned_seconds:.0f}s brief", "script")
    )
    mean = info["mean_volume_db"]
    checks.append(_check("audio level", mean is not None and mean >= MIN_MEAN_VOLUME_DB, f"mean {mean} dB", "voice"))
    longest_silence = max(info["silences"], default=0.0)
    checks.append(_check("silence", not info["silences"], f"longest silence {longest_silence:.1f}s", "voice"))
    checks.append(_check("black frames", not info["black"], f"{sum(info['black']):.1f}s of black", "render"))
    checks.append(_check("frozen picture", not info["frozen"], f"{sum(info['frozen']):.1f}s frozen", "render"))
    return checks


def _tokens(text: str) -> list[str]:
    return re.findall(r"[a-z0-9']+", str(text or "").lower())


def narration_check(spoken_words: list[dict], script_text: str) -> dict:
    from difflib import SequenceMatcher

    spoken = _tokens(" ".join(str(w.get("text", "")) for w in spoken_words or []))
    written = _tokens(script_text)
    ratio = SequenceMatcher(None, spoken, written).ratio() if spoken and written else 0.0
    return _check("narration matches script", ratio >= NARRATION_MATCH, f"{ratio:.0%} of words match", "voice")


def title_check(meta: dict, aspect: str) -> dict:
    title = str((meta or {}).get("title", "")).strip()
    limit = 60 if aspect == "9:16" else 70
    problems = []
    if not title:
        problems.append("no title")
    if len(title) > limit:
        problems.append(f"{len(title)} characters (max {limit})")
    caps = CAPS_WORD.findall(title)
    if caps:
        problems.append(f"shouting: {', '.join(caps)}")
    banned = [p for p in BANNED_TITLE_PHRASES if p in title.lower()]
    if banned:
        problems.append(f"clickbait: {', '.join(banned)}")
    if not str((meta or {}).get("description", "")).strip():
        problems.append("no description")
    return _check("title and description", not problems, "; ".join(problems) or title, "package")


def cost_check(cost: float) -> dict:
    return _check("cost", cost <= MAX_VIDEO_COST, f"${cost:.2f} (cap ${MAX_VIDEO_COST:.2f})", "stop")


def topic_check(topic: str, recent: list[dict], own_sources: tuple[str, ...]) -> dict:
    """The topic is still new: another studio or a hand-made video may have
    covered it since the plan was made. The video's own project and queue
    entry don't count."""
    from app.services.studios import topics

    others = [r for r in recent if not (r["source"] in own_sources and r["text"].strip().lower() == topic.strip().lower())]
    result = topics.check([topic], others)[0]
    detail = "new" if result["new"] else f"repeats {result['matches'][0]['text']!r} ({result['matches'][0]['source']})"
    return _check("topic still new", result["new"], detail, "reserve")


# ------------------------------------------------------------------- critic
CRITIC_PROMPT = """You check a short explainer video before it is published on YouTube. Nobody else will
review it. Be strict about facts and rules, relaxed about style.

Studio rules (the video must not break any):
{rules}

Topic: {topic}

Narration script:
{script}

YouTube title: {title}
YouTube description:
{description}

Find:
- "claim": any statement in the script that is false, misleading, or presented as more certain than
  the evidence allows. Simplification is fine; being wrong is not.
- "rule": anything that breaks a studio rule.
- "title": a title or description that promises something the video does not deliver, or states
  something false.

Respond ONLY with JSON:
{{"problems": [{{"kind": "claim" | "rule" | "title", "quote": "<the exact words>", "why": "<one sentence>"}}]}}
An empty list means the video is fine."""


def critic_check(studio: dict, topic: str, script_text: str, meta: dict, ask) -> tuple[dict, float]:
    """One model pass over the script and the YouTube copy. ``ask(prompt)``
    returns (reply text, cost). A broken reply fails safe: no upload."""
    prompt = CRITIC_PROMPT.format(
        rules="\n".join(f"- {r}" for r in studio["hard_rules"]),
        topic=topic,
        script=script_text,
        title=(meta or {}).get("title", ""),
        description=(meta or {}).get("description", ""),
    )
    try:
        text, cost = ask(prompt)
        from app.services.animation import llm as anim_llm

        problems = list((anim_llm.parse_json(text) or {}).get("problems") or [])
    except Exception as exc:
        logger.warning(f"qa critic failed: {exc}")
        return _check("critic", False, f"the critic could not run: {exc}", "package"), 0.0
    if not problems:
        return _check("critic", True, "no problems found"), cost
    kinds = {str(p.get("kind")) for p in problems}
    fix = "script" if kinds & {"claim", "rule"} else "package"
    detail = "; ".join(f"{p.get('kind')}: \"{str(p.get('quote', ''))[:120]}\" ({p.get('why', '')})" for p in problems[:5])
    return _check("critic", False, detail, fix), cost


def default_ask(model_name: str, client=None):
    """An ``ask`` for critic_check on the studio's planner model."""
    from app.services.studios import planner

    def ask(prompt: str) -> tuple[str, float]:
        from app.services.animation import llm as anim_llm

        live = client or planner._client()
        extra = {"usage": {"include": True}} if "openrouter" in str(getattr(live, "base_url", "")) else {}
        response = live.chat.completions.create(model=model_name, messages=[{"role": "user", "content": prompt}], extra_body=extra)
        return response.choices[0].message.content or "", anim_llm._reported_cost(response)

    return ask


# -------------------------------------------------------------------- run
def run(studio: dict, slot: dict, project: dict, recent: list[dict], ask, probe_fn=probe) -> dict:
    """Check one finished animation. Returns {"ok", "fix", "checks", "cost"}."""
    from app.services.animation import store as anim_store

    pid = project["project_id"]
    checks = media_checks(parse_probe(probe_fn(anim_store.final_path(pid))), float(project.get("seconds") or 30))
    script_text = (anim_store.read_json(anim_store.path(pid, "script.json")) or {}).get("text", "")
    words = (anim_store.read_json(anim_store.path(pid, "words.json")) or {}).get("words", [])
    meta = project.get("youtube") or {}
    checks += [
        narration_check(words, script_text),
        cost_check(anim_store.total_cost(project)),
        topic_check(project["topic"], recent, ("animation project", f"{studio['id']} queue")),
        title_check(meta, project.get("aspect", "9:16")),
    ]
    cost = 0.0
    if all(c["ok"] for c in checks):
        critic, cost = critic_check(studio, project["topic"], script_text, meta, ask)
        checks.append(critic)
    failed = [c for c in checks if not c["ok"]]
    fix = next((f for f in FIX_ORDER if any(c["fix"] == f for c in failed)), "")
    return {"ok": not failed, "fix": fix, "checks": checks, "cost": round(cost, 4)}


def summary(report: dict) -> str:
    failed = [c for c in report.get("checks") or [] if not c["ok"]]
    if not failed:
        return "all checks passed"
    return "; ".join(f"{c['name']}: {c['detail']}" for c in failed)
