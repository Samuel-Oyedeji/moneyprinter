"""Read-only YouTube access for the Analytics page.

Two Google APIs, one OAuth token (the uploader's, see youtube_upload.py):

  YouTube Data API v3      the channel's uploads: id, title, publish time,
                           privacy, duration, and live view/like/comment
                           counts. 1 quota unit per 50 videos.
  YouTube Analytics API v2 per-video watch time, average % viewed, shares
                           and subscribers gained. Separate quota, and the
                           numbers trail real time by about two days.

Both need the read scopes in youtube_upload.READ_SCOPES; a token authorized
before they existed gets a clear "run youtube_auth.py again" error instead
of a 403 from deep inside a request.
"""

import re
from datetime import date as date_cls

from loguru import logger

from app.services.youtube_upload import READ_SCOPES, youtube_upload_service

# Analytics metrics fetched per video, in the order the API returns them.
ANALYTICS_METRICS = (
    "views",
    "estimatedMinutesWatched",
    "averageViewDuration",
    "averageViewPercentage",
    "likes",
    "comments",
    "shares",
    "subscribersGained",
)
# reports.query accepts up to 500 ids in a video== filter; stay well under.
_ANALYTICS_CHUNK = 200
_DATA_API_CHUNK = 50
# The earliest date the Analytics API accepts.
_ANALYTICS_EPOCH = "2005-02-14"


class AnalyticsAuthError(Exception):
    """The token cannot read the channel (missing, unauthorized, or expired)."""


def readiness() -> tuple[bool, str]:
    """Whether analytics can run, and why not."""
    service = youtube_upload_service
    if not service.enabled:
        return False, "YouTube is turned off. Set youtube.enabled = true in config.toml."
    if not service.is_configured():
        return False, "YouTube is not connected yet. Run `python youtube_auth.py` once."
    missing = service.missing_scopes(READ_SCOPES)
    if missing:
        return False, (
            "Your YouTube token only allows uploads. Run `python youtube_auth.py` "
            "again and allow read access to your channel and its analytics "
            "(uploads keep working in the meantime)."
        )
    return True, ""


def _require_ready() -> None:
    ok, reason = readiness()
    if not ok:
        raise AnalyticsAuthError(reason)


def _execute(request):
    """Run a googleapiclient request, turning auth failures into one error type."""
    from google.auth.exceptions import RefreshError
    from googleapiclient.errors import HttpError

    try:
        return request.execute(num_retries=2)
    except RefreshError as e:
        raise AnalyticsAuthError(
            f"YouTube authorization expired ({e}). Run `python youtube_auth.py` again."
        ) from e
    except HttpError as e:
        if e.status_code in (401, 403):
            raise AnalyticsAuthError(
                f"YouTube refused the request ({e.status_code} {e.reason}). If this "
                "is about permissions, run `python youtube_auth.py` again; if the "
                "YouTube Analytics API is not enabled, enable it in Google Cloud "
                "Console (APIs & Services → Library)."
            ) from e
        raise


_DURATION_RE = re.compile(
    r"^P(?:(?P<d>\d+)D)?(?:T(?:(?P<h>\d+)H)?(?:(?P<m>\d+)M)?(?:(?P<s>\d+)S)?)?$"
)


def parse_duration(value: str) -> int:
    """ISO 8601 duration ("PT1M5S") → seconds; 0 when unparseable."""
    match = _DURATION_RE.match(value or "")
    if not match:
        return 0
    parts = {k: int(v or 0) for k, v in match.groupdict().items()}
    return parts["d"] * 86400 + parts["h"] * 3600 + parts["m"] * 60 + parts["s"]


def _video_record(item: dict) -> dict:
    snippet = item.get("snippet") or {}
    status = item.get("status") or {}
    stats = item.get("statistics") or {}
    details = item.get("contentDetails") or {}
    thumbs = snippet.get("thumbnails") or {}
    thumb = (thumbs.get("medium") or thumbs.get("default") or {}).get("url", "")
    return {
        "video_id": item.get("id", ""),
        "title": snippet.get("title", ""),
        "published_at": snippet.get("publishedAt", ""),
        "privacy_status": status.get("privacyStatus", ""),
        "publish_at": status.get("publishAt", ""),
        "duration_seconds": parse_duration(details.get("duration", "")),
        "views": int(stats.get("viewCount", 0) or 0),
        "likes": int(stats.get("likeCount", 0) or 0),
        "comments": int(stats.get("commentCount", 0) or 0),
        "thumbnail": thumb,
    }


def list_channel_videos(client=None) -> dict:
    """Every video on the authorized channel, private and scheduled ones included.

    Returns ``{"channel": {"id", "title"}, "videos": [...]}``, newest first.
    """
    _require_ready()
    client = client or youtube_upload_service._build_client("youtube", "v3")
    channels = _execute(client.channels().list(part="snippet,contentDetails", mine=True))
    items = channels.get("items") or []
    if not items:
        raise AnalyticsAuthError("The authorized Google account has no YouTube channel.")
    channel = items[0]
    uploads = ((channel.get("contentDetails") or {}).get("relatedPlaylists") or {}).get("uploads", "")

    video_ids: list[str] = []
    page_token = None
    while uploads:
        page = _execute(
            client.playlistItems().list(
                part="contentDetails", playlistId=uploads, maxResults=50, pageToken=page_token
            )
        )
        for entry in page.get("items") or []:
            video_id = (entry.get("contentDetails") or {}).get("videoId")
            if video_id:
                video_ids.append(video_id)
        page_token = page.get("nextPageToken")
        if not page_token:
            break

    videos = []
    for start in range(0, len(video_ids), _DATA_API_CHUNK):
        chunk = video_ids[start : start + _DATA_API_CHUNK]
        response = _execute(
            # maxResults is not allowed together with id
            client.videos().list(part="snippet,status,statistics,contentDetails", id=",".join(chunk))
        )
        videos.extend(_video_record(item) for item in response.get("items") or [])
    videos.sort(key=lambda v: v.get("published_at", ""), reverse=True)
    logger.info(f"analytics: {len(videos)} videos on the channel")
    return {
        "channel": {"id": channel.get("id", ""), "title": (channel.get("snippet") or {}).get("title", "")},
        "videos": videos,
    }


def fetch_video_metrics(video_ids: list[str], start_date: str = "", end_date: str = "", client=None) -> dict:
    """Lifetime Analytics metrics per video: ``{video_id: {metric: value}}``.

    Videos without any analytics yet (private drafts, uploads from the last
    couple of days) are simply absent from the result.
    """
    _require_ready()
    if not video_ids:
        return {}
    client = client or youtube_upload_service._build_client("youtubeAnalytics", "v2")
    start_date = start_date or _ANALYTICS_EPOCH
    end_date = end_date or date_cls.today().isoformat()
    metrics: dict[str, dict] = {}
    for start in range(0, len(video_ids), _ANALYTICS_CHUNK):
        chunk = video_ids[start : start + _ANALYTICS_CHUNK]
        response = _execute(
            client.reports().query(
                ids="channel==MINE",
                startDate=start_date,
                endDate=end_date,
                metrics=",".join(ANALYTICS_METRICS),
                dimensions="video",
                filters="video==" + ",".join(chunk),
                # video-dimension reports require a sort and maxResults <= 200
                sort="-views",
                maxResults=len(chunk),
            )
        )
        headers = [h.get("name") for h in response.get("columnHeaders") or []]
        for row in response.get("rows") or []:
            values = dict(zip(headers, row))
            video_id = values.pop("video", None)
            if video_id:
                metrics[video_id] = {k: values.get(k, 0) or 0 for k in ANALYTICS_METRICS}
    logger.info(f"analytics: metrics for {len(metrics)} of {len(video_ids)} videos")
    return metrics
