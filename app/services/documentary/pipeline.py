"""Documentary pipeline orchestration.

Owns status transitions and the human-review gates. Each gate checks the
project's auto_approve flag, so removing a checkpoint later means flipping a
flag — no flow changes. Full flow: research → fact sheet review → script →
script review → image sourcing → image review → render → done.
"""

from loguru import logger

from app.services.documentary import images, render, research, scriptwriter, store


def run_research_stage(project: dict) -> dict:
    """Research the topic; ends in factsheet_review (or scripting if auto)."""
    store.set_status(project, store.STATUS_RESEARCHING)
    try:
        research.run_research(project)
    except Exception as exc:
        logger.exception(f"research failed for {project['project_id']}")
        store.set_status(project, store.STATUS_FAILED, error=str(exc))
        raise

    if project.get("auto_approve_factsheet"):
        return approve_factsheet(project)
    store.set_status(project, store.STATUS_FACTSHEET_REVIEW)
    return project


def approve_factsheet(project: dict) -> dict:
    """Fact sheet approved (by human or auto): generate the script."""
    store.set_status(project, store.STATUS_SCRIPTING)
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
        return approve_script(project)
    store.set_status(project, store.STATUS_SCRIPT_REVIEW)
    return project


def approve_script(project: dict) -> dict:
    """Script approved (by human or auto)."""
    store.set_status(project, store.STATUS_SCRIPT_APPROVED)
    return project


def run_image_sourcing_stage(project: dict) -> dict:
    """Source candidate images for every cue; ends in image_review."""
    store.set_status(project, store.STATUS_SOURCING_IMAGES)
    try:
        images.run_image_sourcing(project)
    except Exception as exc:
        logger.exception(f"image sourcing failed for {project['project_id']}")
        store.set_status(project, store.STATUS_FAILED, error=str(exc))
        raise

    if project.get("auto_approve_images"):
        return approve_images(project)
    store.set_status(project, store.STATUS_IMAGE_REVIEW)
    return project


def approve_images(project: dict) -> dict:
    """Image selection approved: render the final video."""
    store.set_status(project, store.STATUS_RENDERING)
    try:
        render.run_render(project)
    except Exception as exc:
        logger.exception(f"render failed for {project['project_id']}")
        store.set_status(project, store.STATUS_FAILED, error=str(exc))
        raise
    store.set_status(project, store.STATUS_DONE)
    return project


def retry_failed(project: dict) -> dict:
    """Re-enter the pipeline at the stage a failed project died in."""
    project_id = project["project_id"]
    if store.load_factsheet(project_id) is None:
        return run_research_stage(project)
    if store.load_script(project_id) is None:
        return approve_factsheet(project)
    if store.load_images(project_id) is None:
        return run_image_sourcing_stage(project)
    return approve_images(project)
