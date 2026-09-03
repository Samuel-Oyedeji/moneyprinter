"""Rendering for documentary projects: stills + narration → final video.

Narration is synthesized per paragraph so each still's screen time exactly
matches its narration beat (plus a breathing pause). Visuals are Ken Burns
moves (slow zoom/pan via ffmpeg zoompan) with a subtle vignette and grain
for the archival feel, cut together with short fades.

The final video is written into the regular task directory
(storage/tasks/<project_id>/final-1.mp4) with a script.json sidecar, so the
existing Library page, YouTube upload and scheduling features pick it up
without documentary-specific plumbing.
"""

import hashlib
import json
import os
import subprocess

from loguru import logger

from app.config import config
from app.services import voice
from app.services.documentary import images as images_service
from app.services.documentary import scriptwriter, store
from app.utils import utils

VIDEO_WIDTH = 1920
VIDEO_HEIGHT = 1080
FPS = 25
PARAGRAPH_GAP = 0.7  # seconds of silence after each paragraph
SECTION_GAP = 1.4  # longer beat between sections
FADE_DURATION = 0.4
INTRO_DURATION = 5.0

DEFAULT_VOICE = "en-GB-RyanNeural-Male"
DEFAULT_INTRO_FONT = "BeVietnamPro-Bold.ttf"


def _ffmpeg_exe() -> str:
    if config.ffmpeg_path and os.path.isfile(config.ffmpeg_path):
        return config.ffmpeg_path
    import imageio_ffmpeg

    return imageio_ffmpeg.get_ffmpeg_exe()


def _run_ffmpeg(args: list[str], context: str) -> None:
    result = subprocess.run(
        [_ffmpeg_exe(), "-hide_banner", "-loglevel", "error", "-y", *args],
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        raise RuntimeError(f"ffmpeg failed ({context}): {result.stderr[-2000:]}")


# ------------------------------------------------------------------- audio
def _voice_settings() -> tuple[str, float]:
    voice_name = str(
        config.documentary.get("voice_name", "") or DEFAULT_VOICE
    ).strip()
    voice_rate = float(config.documentary.get("voice_rate", 1.0) or 1.0)
    return voice.parse_voice_name(voice_name), voice_rate


def synthesize_paragraphs(project_id: str, paragraphs: list[dict]) -> None:
    """TTS each paragraph into audio/<key>-<texthash>.mp3 (cached by hash)."""
    voice_name, voice_rate = _voice_settings()
    audio_dir = store.audio_dir(project_id)
    for paragraph in paragraphs:
        text_hash = hashlib.md5(
            f"{voice_name}|{voice_rate}|{paragraph['text']}".encode()
        ).hexdigest()[:12]
        audio_file = os.path.join(audio_dir, f"{paragraph['key']}-{text_hash}.mp3")
        paragraph["audio_file"] = audio_file
        if os.path.exists(audio_file):
            continue
        logger.info(f"tts {paragraph['key']} ({len(paragraph['text'])} chars)")
        sub_maker = voice.tts(
            text=paragraph["text"],
            voice_name=voice_name,
            voice_rate=voice_rate,
            voice_file=audio_file,
        )
        if sub_maker is None or not os.path.exists(audio_file):
            raise RuntimeError(
                f"TTS failed for paragraph {paragraph['key']}; check the "
                f"voice configuration (documentary.voice_name={voice_name})"
            )


def _measure_durations(paragraphs: list[dict]) -> None:
    from pydub import AudioSegment

    for paragraph in paragraphs:
        segment = AudioSegment.from_file(paragraph["audio_file"])
        paragraph["narration_seconds"] = len(segment) / 1000.0
        gap = SECTION_GAP if paragraph.get("section_end") else PARAGRAPH_GAP
        paragraph["display_seconds"] = paragraph["narration_seconds"] + gap


def _build_narration_track(
    project_id: str, paragraphs: list[dict], lead_in_seconds: float = 0.0
) -> str:
    """Concatenate paragraph audio with the same gaps the video uses."""
    from pydub import AudioSegment

    track = AudioSegment.silent(duration=int(lead_in_seconds * 1000))
    for paragraph in paragraphs:
        segment = AudioSegment.from_file(paragraph["audio_file"])
        gap_ms = int((paragraph["display_seconds"] - paragraph["narration_seconds"]) * 1000)
        track += segment + AudioSegment.silent(duration=gap_ms)

    bgm_file = str(config.documentary.get("bgm_file", "") or "").strip()
    if bgm_file and os.path.exists(bgm_file):
        import math

        bgm_volume = float(config.documentary.get("bgm_volume", 0.10) or 0.10)
        bgm = AudioSegment.from_file(bgm_file)
        while len(bgm) < len(track):
            bgm += bgm
        bgm = bgm[: len(track)].apply_gain(20 * math.log10(max(bgm_volume, 0.001)))
        bgm = bgm.fade_in(3000).fade_out(4000)
        track = track.overlay(bgm)

    narration_path = os.path.join(store.render_dir(project_id), "narration.mp3")
    track.export(narration_path, format="mp3", bitrate="192k")
    return narration_path


# ------------------------------------------------------------------ visuals
def _ken_burns_filter(index: int, duration: float) -> str:
    frames = max(int(duration * FPS), FPS)
    # Pre-scaling to 2x output size before zoompan avoids the sub-pixel
    # jitter zoompan produces on small inputs.
    base = (
        f"scale={VIDEO_WIDTH * 2}:{VIDEO_HEIGHT * 2}:"
        f"force_original_aspect_ratio=increase,"
        f"crop={VIDEO_WIDTH * 2}:{VIDEO_HEIGHT * 2},"
    )
    center = "x='iw/2-(iw/zoom/2)':y='ih/2-(ih/zoom/2)'"
    # Zoom/pan amounts are normalized by the segment's frame count so every
    # paragraph gets the same gentle motion regardless of narration length.
    moves = (
        "zoompan=z='1+0.10*on/{frames}':" + center,  # slow zoom in
        "zoompan=z='1.10':x='(iw-iw/zoom)*on/{frames}':y='ih/2-(ih/zoom/2)'",
        "zoompan=z='1.10-0.10*on/{frames}':" + center,  # slow zoom out
        "zoompan=z='1.10':x='iw/2-(iw/zoom/2)':y='(ih-ih/zoom)*on/{frames}'",
    )
    move = moves[index % len(moves)].format(frames=frames)
    fade_out_start = max(duration - FADE_DURATION, 0)
    return (
        base
        + f"{move}:d={frames}:s={VIDEO_WIDTH}x{VIDEO_HEIGHT}:fps={FPS},"
        f"vignette=angle=PI/5,noise=alls=4:allf=t,"
        f"fade=t=in:st=0:d={FADE_DURATION},"
        f"fade=t=out:st={fade_out_start:.2f}:d={FADE_DURATION},"
        f"format=yuv420p"
    )


def _intro_font_file() -> str:
    font_name = str(
        config.documentary.get("intro_font", "") or DEFAULT_INTRO_FONT
    ).strip()
    if os.path.isabs(font_name) and os.path.isfile(font_name):
        return font_name
    return os.path.join(utils.root_dir(), "resource", "fonts", font_name)


def _intro_texts(project: dict, script: dict) -> tuple[str, str]:
    intro = script.get("intro") or {}
    title = str(intro.get("title", "")).strip() or str(
        script.get("title", "") or project["topic"]
    )
    date_line = str(intro.get("date_line", "")).strip()
    # Older scripts predate the intro field; a "Name: Place, Date" title
    # splits naturally into the two lines of the card.
    if not date_line and ":" in title:
        title, date_line = (part.strip() for part in title.split(":", 1))
    return title, date_line


def _render_intro_segment(
    project: dict, script: dict, background_image: str, output_dir: str
) -> str:
    """Title card: the first image blurred and darkened, event name + date."""
    title, date_line = _intro_texts(project, script)
    font = _intro_font_file()
    if not os.path.isfile(font):
        raise RuntimeError(f"intro font not found: {font}")

    # drawtext escaping is two-layered (filtergraph + option parser) and
    # brittle for titles with apostrophes/colons; textfile= sidesteps it.
    title_file = os.path.join(output_dir, "intro-title.txt")
    with open(title_file, "w", encoding="utf-8") as f:
        f.write(title)
    date_file = os.path.join(output_dir, "intro-date.txt")
    with open(date_file, "w", encoding="utf-8") as f:
        f.write(date_line)

    fade_out_start = INTRO_DURATION - 0.8
    draw_common = f"fontfile='{font}':fontcolor=white:x=(w-text_w)/2"
    filters = (
        f"scale={VIDEO_WIDTH}:{VIDEO_HEIGHT}:force_original_aspect_ratio=increase,"
        f"crop={VIDEO_WIDTH}:{VIDEO_HEIGHT},"
        f"boxblur=10,eq=brightness=-0.28:saturation=0.65,"
        f"drawtext={draw_common}:y=(h/2)-110:fontsize=88:"
        f"textfile='{title_file}',"
    )
    if date_line:
        filters += (
            f"drawtext={draw_common}:y=(h/2)+30:fontsize=40:alpha=0.9:"
            f"textfile='{date_file}',"
        )
    filters += (
        f"fade=t=in:st=0:d=0.8,fade=t=out:st={fade_out_start:.2f}:d=0.8,"
        f"format=yuv420p,fps={FPS}"
    )

    intro_path = os.path.join(output_dir, "seg-intro.mp4")
    _run_ffmpeg(
        [
            "-loop",
            "1",
            "-i",
            background_image,
            "-t",
            f"{INTRO_DURATION}",
            "-vf",
            filters,
            "-r",
            str(FPS),
            "-c:v",
            "libx264",
            "-preset",
            "veryfast",
            "-crf",
            "20",
            "-an",
            intro_path,
        ],
        context="intro segment",
    )
    return intro_path


def _render_segment(
    project_id: str, index: int, paragraph: dict, image_path: str
) -> str:
    duration = paragraph["display_seconds"]
    frames = max(int(duration * FPS), FPS)
    segment_path = os.path.join(
        store.render_dir(project_id), f"seg-{index:03d}.mp4"
    )
    _run_ffmpeg(
        [
            "-i",
            image_path,
            "-vf",
            _ken_burns_filter(index, duration),
            "-frames:v",
            str(frames),
            "-r",
            str(FPS),
            "-c:v",
            "libx264",
            "-preset",
            "veryfast",
            "-crf",
            "20",
            "-an",
            segment_path,
        ],
        context=f"segment {paragraph['key']}",
    )
    return segment_path


def _concat_segments(project_id: str, segment_paths: list[str]) -> str:
    list_path = os.path.join(store.render_dir(project_id), "segments.txt")
    with open(list_path, "w", encoding="utf-8") as f:
        for path in segment_paths:
            f.write(f"file '{path}'\n")
    visual_path = os.path.join(store.render_dir(project_id), "visual.mp4")
    _run_ffmpeg(
        ["-f", "concat", "-safe", "0", "-i", list_path, "-c", "copy", visual_path],
        context="concat",
    )
    return visual_path


# ---------------------------------------------------------------- subtitles
def _format_srt_time(seconds: float) -> str:
    ms = int(round(seconds * 1000))
    return (
        f"{ms // 3600000:02d}:{(ms // 60000) % 60:02d}:"
        f"{(ms // 1000) % 60:02d},{ms % 1000:03d}"
    )


def _write_srt(
    paragraphs: list[dict], srt_path: str, offset_seconds: float = 0.0
) -> None:
    # Paragraph-level timing: coarse, but accurate at the beat level, and
    # good enough for YouTube to refine with its own alignment.
    cursor = offset_seconds
    with open(srt_path, "w", encoding="utf-8") as f:
        for index, paragraph in enumerate(paragraphs, start=1):
            start = cursor
            end = cursor + paragraph["narration_seconds"]
            f.write(
                f"{index}\n{_format_srt_time(start)} --> {_format_srt_time(end)}\n"
                f"{paragraph['text']}\n\n"
            )
            cursor += paragraph["display_seconds"]


# ------------------------------------------------------------------- driver
def _collect_paragraphs(script: dict, images: dict) -> list[dict]:
    image_by_key = {item["key"]: item for item in images.get("items", [])}
    paragraphs = []
    missing = []
    for section_idx, section in enumerate(script.get("sections", [])):
        section_paragraphs = section.get("paragraphs", [])
        for para_idx, paragraph in enumerate(section_paragraphs):
            key = f"s{section_idx}p{para_idx}"
            text = str(paragraph.get("text", "")).strip()
            if not text:
                continue
            item = image_by_key.get(key)
            image_path = images_service.selected_image_path(item) if item else ""
            if not image_path:
                missing.append(key)
            paragraphs.append(
                {
                    "key": key,
                    "text": text,
                    "image_path": image_path,
                    "section_end": para_idx == len(section_paragraphs) - 1,
                }
            )
    if missing:
        raise RuntimeError(
            f"no selected image for paragraphs: {', '.join(missing)}; pick or "
            "upload an image for every paragraph before rendering."
        )
    return paragraphs


def _publish_to_task_library(
    project: dict, script: dict, images: dict, final_path: str
) -> None:
    """Write the Library/scheduler-compatible sidecar next to the final video."""
    task_dir = utils.task_dir(project["project_id"])
    youtube_meta = script.get("youtube", {})
    description = youtube_meta.get("description", "")
    credits = images_service.credits_block(images)
    if credits:
        description = f"{description}\n\nImage credits:\n{credits}".strip()
    sidecar = {
        "params": {"video_subject": youtube_meta.get("title") or project["topic"]},
        "script": scriptwriter.full_narration_text(script),
        "documentary_project_id": project["project_id"],
        "youtube": {**youtube_meta, "description": description},
    }
    with open(os.path.join(task_dir, "script.json"), "w", encoding="utf-8") as f:
        json.dump(sidecar, f, ensure_ascii=False, indent=2)


def run_render(project: dict) -> str:
    """Render the approved script + selected images into the final video."""
    project_id = project["project_id"]
    script = store.load_script(project_id)
    images = store.load_images(project_id)
    if not script or not images:
        raise RuntimeError("script or image selection missing; cannot render")

    paragraphs = _collect_paragraphs(script, images)
    logger.info(f"rendering {project_id}: {len(paragraphs)} segments")

    synthesize_paragraphs(project_id, paragraphs)
    _measure_durations(paragraphs)
    total = sum(p["display_seconds"] for p in paragraphs)
    logger.info(f"narration timed at {total / 60:.1f} minutes")

    segment_paths = []
    intro_seconds = 0.0
    if bool(config.documentary.get("intro_enabled", True)):
        logger.info("rendering intro title card")
        segment_paths.append(
            _render_intro_segment(
                project, script, paragraphs[0]["image_path"],
                store.render_dir(project_id),
            )
        )
        intro_seconds = INTRO_DURATION
    for index, paragraph in enumerate(paragraphs):
        logger.info(f"segment {index + 1}/{len(paragraphs)} ({paragraph['key']})")
        segment_paths.append(
            _render_segment(project_id, index, paragraph, paragraph["image_path"])
        )

    visual_path = _concat_segments(project_id, segment_paths)
    narration_path = _build_narration_track(
        project_id, paragraphs, lead_in_seconds=intro_seconds
    )

    task_dir = utils.task_dir(project_id)
    final_path = os.path.join(task_dir, "final-1.mp4")
    _run_ffmpeg(
        [
            "-i",
            visual_path,
            "-i",
            narration_path,
            "-map",
            "0:v:0",
            "-map",
            "1:a:0",
            "-c:v",
            "copy",
            "-c:a",
            "aac",
            "-b:a",
            "192k",
            "-shortest",
            final_path,
        ],
        context="final mux",
    )

    _write_srt(
        paragraphs,
        os.path.join(task_dir, "final-1.srt"),
        offset_seconds=intro_seconds,
    )
    _publish_to_task_library(project, script, images, final_path)
    logger.success(f"documentary rendered: {final_path}")
    return final_path
