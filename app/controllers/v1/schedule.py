"""Content-calendar API: CRUD for scheduled generations plus the cron hook.

``POST /api/v1/schedules/run`` is the endpoint a daily cron job hits. It
returns immediately and processes due entries in a background thread, since
one run can take an hour or more of video rendering.
"""
import threading

from fastapi import Depends, Path, Query, Request
from loguru import logger

from app.controllers import base
from app.controllers.v1.base import new_router
from app.models.exception import HttpException
from app.models.schema import (
    ScheduleDuplicateRequest,
    ScheduleEntryRequest,
    ScheduleEntryResponse,
    ScheduleEntryUpdateRequest,
    ScheduleListResponse,
    ScheduleRunRequest,
)
from app.services import schedule as schedule_service
from app.utils import utils

router = new_router(dependencies=[Depends(base.verify_token)])


@router.get(
    "/schedules",
    response_model=ScheduleListResponse,
    summary="List scheduled generation entries",
)
def list_schedules(
    request: Request,
    start_date: str = Query(None, description="Filter: date >= start_date"),
    end_date: str = Query(None, description="Filter: date <= end_date"),
):
    request_id = base.get_task_id(request)
    try:
        entries = schedule_service.list_entries(start_date, end_date)
    except ValueError as e:
        raise HttpException(
            task_id=request_id, status_code=400, message=f"{request_id}: {str(e)}"
        )
    return utils.get_response(
        200, {"entries": entries, "presets": schedule_service.PRESETS}
    )


@router.post(
    "/schedules",
    response_model=ScheduleEntryResponse,
    summary="Create a scheduled generation entry",
)
def create_schedule(request: Request, body: ScheduleEntryRequest):
    request_id = base.get_task_id(request)
    try:
        entry = schedule_service.create_entry(
            date=body.date,
            topic=body.topic,
            video_count=body.video_count,
            preset=body.preset,
            post_time=body.post_time,
            language=body.language,
        )
    except ValueError as e:
        raise HttpException(
            task_id=request_id, status_code=400, message=f"{request_id}: {str(e)}"
        )
    return utils.get_response(200, entry)


@router.put(
    "/schedules/{entry_id}",
    response_model=ScheduleEntryResponse,
    summary="Update a scheduled generation entry",
)
def update_schedule(
    request: Request,
    body: ScheduleEntryUpdateRequest,
    entry_id: str = Path(...),
):
    request_id = base.get_task_id(request)
    fields = body.model_dump(exclude_none=True)
    try:
        entry = schedule_service.update_entry(entry_id, **fields)
    except KeyError:
        raise HttpException(
            task_id=request_id, status_code=404, message=f"{request_id}: entry not found"
        )
    except ValueError as e:
        raise HttpException(
            task_id=request_id, status_code=400, message=f"{request_id}: {str(e)}"
        )
    return utils.get_response(200, entry)


@router.delete(
    "/schedules/{entry_id}",
    response_model=ScheduleEntryResponse,
    summary="Delete a scheduled generation entry",
)
def delete_schedule(request: Request, entry_id: str = Path(...)):
    request_id = base.get_task_id(request)
    try:
        schedule_service.delete_entry(entry_id)
    except KeyError:
        raise HttpException(
            task_id=request_id, status_code=404, message=f"{request_id}: entry not found"
        )
    except ValueError as e:
        raise HttpException(
            task_id=request_id, status_code=409, message=f"{request_id}: {str(e)}"
        )
    return utils.get_response(200)


@router.post(
    "/schedules/{entry_id}/duplicate",
    response_model=ScheduleListResponse,
    summary="Duplicate an entry onto other dates",
)
def duplicate_schedule(
    request: Request,
    body: ScheduleDuplicateRequest,
    entry_id: str = Path(...),
):
    request_id = base.get_task_id(request)
    try:
        created = schedule_service.duplicate_entry(entry_id, body.dates, body.topic)
    except KeyError:
        raise HttpException(
            task_id=request_id, status_code=404, message=f"{request_id}: entry not found"
        )
    except ValueError as e:
        raise HttpException(
            task_id=request_id, status_code=400, message=f"{request_id}: {str(e)}"
        )
    return utils.get_response(200, {"entries": created})


@router.post(
    "/schedules/run",
    response_model=ScheduleEntryResponse,
    summary="Run all pending entries due today (cron hook)",
)
def run_schedules(request: Request, body: ScheduleRunRequest = None):
    request_id = base.get_task_id(request)
    run_date = body.date if body else None

    # 生成一批视频可能耗时数十分钟，cron 的 curl 不应等待。
    # run_due_entries 内部有互斥锁，重复触发会被安全跳过。
    thread = threading.Thread(
        target=schedule_service.run_due_entries,
        kwargs={"run_date": run_date},
        daemon=True,
        name="schedule-run",
    )
    thread.start()
    logger.info(f"schedule run triggered, request_id: {request_id}")
    return utils.get_response(200, {"triggered": True, "date": run_date})
