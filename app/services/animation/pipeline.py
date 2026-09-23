"""Topic → finished animation, in four resumable stages.

    storyboard  LLM writes narration + staging          storyboard.json
    voice       ElevenLabs narration with word timings  public/narration.mp3, words.json
    render      compile to a Remotion story, render     story.json, final.mp4, thumb.jpg
    package     YouTube title/description/hashtags      project.json["youtube"]

Each stage is skipped when its output already exists, so a retry after a
failure picks up where the run stopped (a render failure does not pay for
the storyboard or the voice-over again).
"""

import os

from loguru import logger

from app.config import config
from app.services.animation import compose, metadata, render, store, storyboard, tts

STAGES = ("storyboard", "voice", "render", "package")


def default_voice() -> str:
    return str(config.animation.get("voice_name", "") or config.documentary.get("voice_name", "") or "en-GB-RyanNeural")


def reset_from(project_id: str, stage: str) -> dict:
    """Throw away a stage's output (and everything after it) so it reruns."""
    if stage not in STAGES:
        raise ValueError(f"unknown stage {stage!r}")
    drop = STAGES[STAGES.index(stage):]
    files = {
        "storyboard": ["storyboard.json"],
        "voice": ["words.json", os.path.join("public", "narration.mp3")],
        "render": ["story.json", "final.mp4", "thumb.jpg"],
    }
    for s in drop:
        for name in files.get(s, []):
            try:
                os.remove(store.path(project_id, name))
            except FileNotFoundError:
                pass
    fields = {"status": store.STATUS_QUEUED, "stage": "Queued", "progress": 0.0, "error": ""}
    if "package" in drop:
        fields["youtube"] = {}
    return store.update_project(project_id, **fields)


def run_project(project_id: str, on_stage=None, render_scale: float | None = None) -> dict:
    """Drive one project to done. Never raises: failures land on the project."""
    project = store.load_project(project_id)
    if not project:
        raise KeyError(f"animation project not found: {project_id}")

    def stage(status: str, label: str, progress: float | None = None):
        fields = {"status": status, "stage": label, "error": ""}
        if progress is not None:
            fields["progress"] = round(progress, 3)
        store.update_project(project_id, **fields)
        if on_stage:
            on_stage(label)

    def cost(kind: str):
        return lambda amount: store.add_cost(project_id, kind, amount)

    try:
        # 1 · storyboard
        board = store.read_json(store.path(project_id, "storyboard.json"))
        if not board:
            stage(store.STATUS_WRITING, "Writing the storyboard…", 0.05)
            board = storyboard.write_storyboard(
                project["topic"], project.get("context", ""), project["seconds"], project["aspect"], on_cost=cost("llm")
            )
            store.write_json(store.path(project_id, "storyboard.json"), board)

        # 2 · voice-over with word timings
        narration_path = os.path.join(store.public_dir(project_id), "narration.mp3")
        voice_data = store.read_json(store.path(project_id, "words.json"))
        if not voice_data or not os.path.isfile(narration_path):
            voice = project.get("voice") or default_voice()
            stage(store.STATUS_VOICING, "Recording the narration…", 0.15)
            result = tts.synthesize(storyboard.narration_text(board), voice, narration_path)
            voice_data = {k: result[k] for k in ("words", "duration", "provider", "chars")}
            voice_data["voice"] = voice
            store.write_json(store.path(project_id, "words.json"), voice_data)
            if result["cost"]:
                store.add_cost(project_id, "tts", result["cost"])

        # 3 · compile + render
        final = store.final_path(project_id)
        if not os.path.isfile(final):
            story = compose.compile_story(board, voice_data["words"], voice_data["duration"], project["aspect"])
            story_path = store.path(project_id, "story.json")
            store.write_json(story_path, story)
            stage(store.STATUS_RENDERING, "Rendering 0%", 0.2)
            last = {"pct": -1}

            def on_progress(fraction: float):
                pct = int(fraction * 100)
                if pct >= last["pct"] + 3 or pct == 100:
                    last["pct"] = pct
                    stage(store.STATUS_RENDERING, f"Rendering {pct}%", 0.2 + 0.7 * fraction)

            render.render_story(story_path, store.public_dir(project_id), final, on_progress=on_progress, scale=render_scale)
            duration = compose.story_duration(story)
            render.extract_frame(final, store.thumb_path(project_id), duration * 0.4)
            store.update_project(project_id, duration=duration, title=story.get("title", ""))

        # 4 · YouTube metadata
        project = store.load_project(project_id)
        if not (project.get("youtube") or {}).get("generated"):
            stage(store.STATUS_PACKAGING, "Writing the YouTube title & description…", 0.95)
            meta = metadata.generate(
                project["topic"], storyboard.narration_text(board), project["aspect"], board.get("title", ""), on_cost=cost("llm")
            )
            store.update_project(project_id, youtube=meta)

        stage(store.STATUS_DONE, "Done", 1.0)
        logger.success(f"animation {project_id} finished")
    except Exception as exc:
        logger.exception(f"animation {project_id} failed")
        store.update_project(project_id, status=store.STATUS_FAILED, error=str(exc)[:2000])
    return store.load_project(project_id)
