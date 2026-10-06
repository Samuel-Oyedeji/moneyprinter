"""Analytics API: trigger a channel sync and read per-studio results.

``POST /api/v1/analytics/sync`` returns immediately and syncs in the
background (listing the channel, reconciling hand-posted videos, pulling
metrics). The daily cron hook already runs one before its uploads, so this
is for an extra refresh, e.g. from a second cron line in the evening.
"""
import math
import threading

from fastapi import Depends, Query, Request

from app.controllers import base
from app.controllers.v1.base import new_router
from app.models.schema import ScheduleEntryResponse
from app.services.analytics import report, store, sync, youtube_api
from app.utils import utils

router = new_router(dependencies=[Depends(base.verify_token)])


def _clean(value):
    if isinstance(value, float) and math.isnan(value):
        return None
    return value


@router.post("/analytics/sync", response_model=ScheduleEntryResponse, summary="Sync the channel's videos and metrics (background)")
def sync_analytics(request: Request):
    ready, reason = youtube_api.readiness()
    if ready:
        threading.Thread(target=sync.run, daemon=True, name="analytics-sync").start()
    return utils.get_response(200, {"triggered": ready, "reason": reason})


@router.get("/analytics/status", response_model=ScheduleEntryResponse, summary="Connection and last-sync status")
def analytics_status(request: Request):
    ready, reason = youtube_api.readiness()
    return utils.get_response(200, {"ready": ready, "reason": reason, "last_sync": store.load_sync_status()})


@router.get("/analytics/summary", response_model=ScheduleEntryResponse, summary="Per-group results from the last sync")
def analytics_summary(
    request: Request,
    by: str = Query("studio_label", description="Column to group by, e.g. studio_label, category, generation"),
    studio: str = Query("", description="Only this studio: shorts, documentary or animation"),
):
    df = report.build_dataset()
    if studio and not df.empty:
        df = df[df["studio"] == studio]
    rows = report.summarize(df, by).to_dict(orient="records")
    rows = [{k: _clean(v) for k, v in row.items()} for row in rows]
    return utils.get_response(200, {"by": by, "groups": rows})
