"""Narration with word timings.

ElevenLabs' /with-timestamps endpoint returns the audio plus per-character
start/end times; those become per-word times that drive the captions and
every action cue in the animation. Edge TTS (free) is the fallback for
non-ElevenLabs voice names; its word boundaries lose punctuation, which is
re-attached from the script.
"""

import asyncio
import base64
import os

import requests
from loguru import logger

from app.config import config
from app.services import voice as voice_service

ELEVENLABS_URL = "https://api.elevenlabs.io/v1/text-to-speech/{voice_id}/with-timestamps"
DEFAULT_PRICE_PER_1K_CHARS = 0.10
_NON_RETRYABLE = {400, 401, 403, 404, 422}


class TTSError(RuntimeError):
    pass


def words_from_alignment(alignment: dict) -> list[dict]:
    """ElevenLabs character alignment → [{"text", "at", "end"}] per word."""
    chars = alignment.get("characters") or []
    starts = alignment.get("character_start_times_seconds") or []
    ends = alignment.get("character_end_times_seconds") or []
    words: list[dict] = []
    text, start, end = "", 0.0, 0.0
    for ch, s, e in zip(chars, starts, ends):
        if ch.isspace():
            if text:
                words.append({"text": text, "at": round(start, 3), "end": round(end, 3)})
                text = ""
            continue
        if not text:
            start = float(s)
        text += ch
        end = float(e)
    if text:
        words.append({"text": text, "at": round(start, 3), "end": round(end, 3)})
    return words


def reattach_punctuation(script: str, raw_words: list[dict]) -> list[dict]:
    """Give TTS word boundaries back the script's own tokens (with punctuation).

    A boundary can cover two script tokens ("In 1928"), so tokens are
    consumed by count. If the counts disagree the raw words are returned.
    """
    tokens = script.split()
    out, k = [], 0
    for w in raw_words:
        n = max(1, len(str(w["text"]).split()))
        out.append({**w, "text": " ".join(tokens[k : k + n])})
        k += n
    if k != len(tokens):
        logger.warning(f"word boundary count mismatch ({k} vs {len(tokens)}); keeping raw words")
        return raw_words
    return out


def price_per_1k_chars() -> float:
    for section in (config.animation, config.documentary):
        value = section.get("elevenlabs_price_per_1k_chars")
        if value not in (None, ""):
            try:
                return float(value)
            except (TypeError, ValueError):
                pass
    return DEFAULT_PRICE_PER_1K_CHARS


def _audio_duration(path: str) -> float:
    from moviepy.audio.io.AudioFileClip import AudioFileClip

    clip = AudioFileClip(path)
    try:
        return float(clip.duration)
    finally:
        clip.close()


def elevenlabs_with_timestamps(text: str, voice_id: str, out_path: str) -> list[dict]:
    api_key = voice_service.get_elevenlabs_api_key()
    if not api_key:
        raise TTSError("ElevenLabs API key is not set (Animation page → voice settings)")
    payload = {
        "text": text,
        "model_id": config.elevenlabs.get("model_id", "eleven_multilingual_v2"),
        "voice_settings": {"stability": 0.5, "similarity_boost": 0.75, "style": 0.0, "use_speaker_boost": True},
    }
    last = ""
    for attempt in range(3):
        try:
            response = requests.post(
                ELEVENLABS_URL.format(voice_id=voice_id),
                params={"output_format": "mp3_44100_128"},
                headers={"xi-api-key": api_key, "Content-Type": "application/json"},
                json=payload,
                timeout=180,
            )
        except requests.RequestException as exc:
            last = str(exc)
            logger.warning(f"ElevenLabs request failed (attempt {attempt + 1}): {last}")
            continue
        if response.status_code != 200:
            last = f"HTTP {response.status_code}: {response.text[:300]}"
            if response.status_code in _NON_RETRYABLE:
                break
            logger.warning(f"ElevenLabs TTS failed (attempt {attempt + 1}): {last}")
            continue
        data = response.json()
        with open(out_path, "wb") as f:
            f.write(base64.b64decode(data["audio_base64"]))
        words = words_from_alignment(data.get("alignment") or data.get("normalized_alignment") or {})
        if not words:
            raise TTSError("ElevenLabs returned no word timings")
        return words
    raise TTSError(f"ElevenLabs TTS failed: {last}")


def edge_with_boundaries(text: str, voice: str, out_path: str) -> list[dict]:
    import edge_tts

    # the app lists Edge voices as "en-GB-RyanNeural-Male"; Edge wants the name
    for suffix in ("-Male", "-Female"):
        if voice.endswith(suffix):
            voice = voice[: -len(suffix)]

    async def run():
        communicate = edge_tts.Communicate(text, voice, boundary="WordBoundary")
        audio = bytearray()
        raw = []
        async for chunk in communicate.stream():
            if chunk["type"] == "audio":
                audio.extend(chunk["data"])
            elif chunk["type"] == "WordBoundary":
                at = chunk["offset"] / 1e7
                raw.append({"text": chunk["text"], "at": round(at, 3), "end": round(at + chunk["duration"] / 1e7, 3)})
        return bytes(audio), raw

    audio, raw = asyncio.run(run())
    if not audio or not raw:
        raise TTSError(f"Edge TTS returned no audio for voice {voice!r}")
    with open(out_path, "wb") as f:
        f.write(audio)
    return reattach_punctuation(text, raw)


def synthesize(text: str, voice: str, out_path: str) -> dict:
    """Write the narration to out_path; return words, duration and cost."""
    text = (text or "").strip()
    if not text:
        raise TTSError("nothing to narrate")
    os.makedirs(os.path.dirname(out_path), exist_ok=True)
    if voice_service.is_elevenlabs_voice(voice):
        parts = voice.split(":", 2)
        if len(parts) < 2 or not parts[1]:
            raise TTSError(f"invalid ElevenLabs voice: {voice!r}")
        words = elevenlabs_with_timestamps(text, parts[1], out_path)
        cost = len(text) / 1000 * price_per_1k_chars()
        provider = "elevenlabs"
    else:
        words = edge_with_boundaries(text, voice or "en-GB-RyanNeural", out_path)
        cost = 0.0
        provider = "edge"
    duration = _audio_duration(out_path)
    return {"words": words, "duration": duration, "cost": round(cost, 5), "provider": provider, "chars": len(text)}
