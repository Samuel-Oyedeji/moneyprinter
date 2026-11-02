"""Autonomous studios API: the hourly cron hook and a status read-out.

``POST /api/v1/studios/tick`` is what the hourly cron job hits. Like the
calendar hook it returns at once and works in a background thread, since a
tick can render several videos; the tick's own lock makes a second trigger
while one is running a no-op.
"""
import threading

from fastapi import Depends, Request
from loguru import logger

from app.controllers import base
from app.controllers.v1.base import new_router
from app.models.schema import ScheduleEntryResponse
from app.services.studios import model, runner, store
from app.utils import utils

router = new_router(dependencies=[Depends(base.verify_token)])


@router.post("/studios/tick", response_model=ScheduleEntryResponse, summary="Run the studios' hourly tick (cron hook)")
def tick_studios(request: Request):
    threading.Thread(target=runner.tick, daemon=True, name="studios-tick").start()
    logger.info(f"studios tick triggered, request_id: {base.get_task_id(request)}")
    return utils.get_response(200, {"triggered": True})


@router.get("/studios", response_model=ScheduleEntryResponse, summary="List studios with their queue counts")
def list_studios(request: Request):
    studios = []
    for studio in store.list_studios():
        counts = {status: 0 for status in model.SLOT_STATUSES}
        for slot in store.load_queue(studio["id"]):
            counts[slot["status"]] += 1
        latest = store.list_events(studio["id"], limit=1)
        studios.append(
            {
                "id": studio["id"],
                "name": studio["name"],
                "pipeline": studio["pipeline"],
                "paused": studio["paused"],
                "queue": counts,
                "latest_event": latest[0] if latest else None,
            }
        )
    return utils.get_response(200, {"studios": studios})
