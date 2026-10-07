"""Storage clean-up API: preview what would be deleted, or run it now.

The daily cron hook already runs the clean-up (see app/services/sweeper.py);
these routes are for checking it and running it by hand.
"""
import os

from fastapi import Depends, Request

from app.controllers import base
from app.controllers.v1.base import new_router
from app.models.schema import ScheduleEntryResponse
from app.services import sweeper
from app.utils import utils

router = new_router(dependencies=[Depends(base.verify_token)])


def _public(result: dict) -> dict:
    """Paths relative to storage/, never absolute server paths."""
    root = utils.storage_dir()
    for video in result.get("videos") or []:
        video["paths"] = [os.path.relpath(p, root) for p in video["paths"]]
    return result


@router.get("/sweeper/preview", response_model=ScheduleEntryResponse, summary="List what a storage clean-up would delete (deletes nothing)")
def preview_sweep(request: Request):
    return utils.get_response(200, _public(sweeper.plan()))


@router.post("/sweeper/run", response_model=ScheduleEntryResponse, summary="Run the storage clean-up now")
def run_sweep(request: Request):
    return utils.get_response(200, sweeper.run())
