"""Documentary pipeline orchestration.

Owns status transitions and the human-review gates. Each gate checks the
project's auto_approve flag, so removing a checkpoint later means flipping a
flag — no flow changes. Full flow: research → fact sheet review → script →
script review → image sourcing → image review → render → done.
"""

from collections.abc import Callable

from loguru import logger

from app.services.documentary import (
    costs,
    images,
    render,
    research,
    scriptwriter,
    store,
)


def _notify(on_stage: Callable[[str], None] | None, message: str) -> None:
    """Report the current stage to the caller's progress display.

    Autopilot runs every stage inside the one call the UI started, so without
    this the page shows the first stage's label for the whole run. A broken
    progress callback must never take the pipeline down with it.
    """
    if on_stage is None:
        return
    try:
        on_stage(message)
    except Exception as exc:
        logger.warning(f"stage progress callback failed: {exc}")


def run_research_stage(
    project: dict, on_stage: Callable[[str], None] | None = None
) -> dict:
    """Research the topic; ends in factsheet_review (or scripting if auto)."""
    costs.set_project(project["project_id"])
    store.set_status(project, store.STATUS_RESEARCHING)
    _notify(
        on_stage,
        "Researching — searching the web, fetching sources, distilling facts…",
    )
    try:
        research.run_research(project)
    except Exception as exc:
        logger.exception(f"research failed for {project['project_id']}")
        store.set_status(project, store.STATUS_FAILED, error=str(exc))
        raise

    if project.get("auto_approve_factsheet"):
        return approve_factsheet(project, on_stage)
    store.set_status(project, store.STATUS_FACTSHEET_REVIEW)
    return project


def approve_factsheet(
    project: dict, on_stage: Callable[[str], None] | None = None
) -> dict:
    """Fact sheet approved (by human or auto): generate the script."""
    costs.set_project(project["project_id"])
    store.set_status(project, store.STATUS_SCRIPTING)
    _notify(on_stage, "Writing the script from the approved fact sheet…")
    factsheet = store.load_factsheet(project["project_id"])
    if not factsheet:
        store.set_status(project, store.STATUS_FAILED, error="fact sheet missing")
        raise RuntimeError("fact sheet missing; run research first")

    try:
        scriptwriter.run_scriptwriting(project, factsheet)
    except Exception as exc:
        logger.exception(f"scriptwriting failed for {project['project_id']}")
        store.set_status(project, store.STATUS_FAILED, error=str(exc))
        raise

    if project.get("auto_approve_script"):
        return approve_script(project, on_stage)
    store.set_status(project, store.STATUS_SCRIPT_REVIEW)
    return project


def approve_script(
    project: dict, on_stage: Callable[[str], None] | None = None
) -> dict:
    """Script approved (by human or auto)."""
    store.set_status(project, store.STATUS_SCRIPT_APPROVED)
    if project.get("auto_approve_images"):
        # Full-autopilot chain: sourcing scores candidates with the vision
        # model and rendering follows without an image checkpoint.
        return run_image_sourcing_stage(project, on_stage)
    return project


def run_image_sourcing_stage(
    project: dict, on_stage: Callable[[str], None] | None = None
) -> dict:
    """Source candidate images for every cue; ends in image_review."""
    costs.set_project(project["project_id"])
    store.set_status(project, store.STATUS_SOURCING_IMAGES)
    _notify(
        on_stage, "Sourcing images — searching four providers per paragraph…"
    )
    try:
        images.run_image_sourcing(project, on_progress=on_stage)
    except Exception as exc:
        logger.exception(f"image sourcing failed for {project['project_id']}")
        store.set_status(project, store.STATUS_FAILED, error=str(exc))
        raise

    if project.get("auto_approve_images"):
        return approve_images(project, on_stage)
    store.set_status(project, store.STATUS_IMAGE_REVIEW)
    return project


def approve_images(
    project: dict, on_stage: Callable[[str], None] | None = None
) -> dict:
    """Image selection approved: render the final video."""
    costs.set_project(project["project_id"])
    store.set_status(project, store.STATUS_RENDERING)
    _notify(
        on_stage, "Rendering — narration, Ken Burns segments, final mux…"
    )
    try:
        render.run_render(project, on_progress=on_stage)
    except Exception as exc:
        logger.exception(f"render failed for {project['project_id']}")
        store.set_status(project, store.STATUS_FAILED, error=str(exc))
        raise
    store.set_status(project, store.STATUS_DONE)
    return project


def retry_failed(
    project: dict, on_stage: Callable[[str], None] | None = None
) -> dict:
    """Re-enter the pipeline at the stage a failed project died in."""
    project_id = project["project_id"]
    if store.load_factsheet(project_id) is None:
        return run_research_stage(project, on_stage)
    if store.load_script(project_id) is None:
        return approve_factsheet(project, on_stage)
    if store.load_images(project_id) is None:
        return run_image_sourcing_stage(project, on_stage)
    return approve_images(project, on_stage)
