"""Documentary pipeline orchestration.

Owns status transitions and the human-review gates. Each gate checks the
project's auto_approve flag, so removing a checkpoint later means flipping a
flag — no flow changes. Phase 1 covers research → fact sheet review →
script → script review; image sourcing and rendering attach after
STATUS_SCRIPT_APPROVED in phase 2.
"""

from loguru import logger

from app.services.documentary import research, scriptwriter, store


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
    """Script approved. Phase 2 (image sourcing) will continue from here."""
    store.set_status(project, store.STATUS_SCRIPT_APPROVED)
    return project


def retry_failed(project: dict) -> dict:
    """Re-enter the pipeline at the stage a failed project died in."""
    project_id = project["project_id"]
    if store.load_factsheet(project_id) is None:
        return run_research_stage(project)
    if store.load_script(project_id) is None:
        return approve_factsheet(project)
    return approve_script(project)
