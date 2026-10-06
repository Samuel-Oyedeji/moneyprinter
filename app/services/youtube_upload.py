"""
YouTube Data API v3 integration for uploading generated videos as drafts.

The YouTube API has no real "draft" state, so videos are uploaded with
``privacyStatus: private`` (title/description/tags/thumbnail already set).
The owner then reviews and publishes them from YouTube Studio.

Auth model: a one-time OAuth flow (``python youtube_auth.py``) stores a
refresh token in ``storage/youtube/token.json``. All later uploads —
including headless cron runs on a VPS — reuse and auto-refresh that token.
The same token carries the read-only scopes the Analytics page uses; a
token authorized before those existed keeps uploading and only needs
``youtube_auth.py`` again to turn analytics on.

Quota note: each ``videos.insert`` call costs 1600 units of the default
10,000/day project quota, i.e. roughly 6 uploads per day unless Google
grants a quota increase.
"""
import os
from typing import Optional

from loguru import logger

from app.config import config
from app.utils import utils

# OAuth scope for uploading videos and setting thumbnails.
UPLOAD_SCOPE = "https://www.googleapis.com/auth/youtube.upload"
# Read access for the Analytics page: listing the channel's uploads (to
# reconcile videos posted by hand) and reading per-video performance.
READ_SCOPES = [
    "https://www.googleapis.com/auth/youtube.readonly",
    "https://www.googleapis.com/auth/yt-analytics.readonly",
]
# What `python youtube_auth.py` asks for.
YOUTUBE_SCOPES = [UPLOAD_SCOPE, *READ_SCOPES]

# YouTube caps: title 100 chars, description 5000 bytes, ~500 chars of tags.
_MAX_TITLE_LENGTH = 100
_MAX_DESCRIPTION_LENGTH = 4900
_MAX_TAGS_TOTAL_LENGTH = 480


class YoutubeUploadError(Exception):
    """Raised when an upload cannot start or complete."""


def _default_storage_path(filename: str) -> str:
    return os.path.join(utils.storage_dir("youtube", create=True), filename)


class YoutubeUploadService:
    @property
    def enabled(self) -> bool:
        return config.youtube.get("enabled", False)

    @property
    def client_secrets_file(self) -> str:
        return config.youtube.get("client_secrets_file", "") or _default_storage_path(
            "client_secret.json"
        )

    @property
    def token_file(self) -> str:
        return config.youtube.get("token_file", "") or _default_storage_path(
            "token.json"
        )

    @property
    def default_privacy_status(self) -> str:
        return config.youtube.get("default_privacy_status", "private")

    @property
    def category_id(self) -> str:
        # 22 = "People & Blogs", YouTube's generic default.
        return str(config.youtube.get("category_id", "22"))

    @property
    def contains_synthetic_media(self) -> bool:
        """Whether uploads declare YouTube's "altered or synthetic content" label.

        YouTube only requires this for REALISTIC synthetic content - footage
        that could pass for a real person, place or event that never happened
        - and for AI-generated music. Stock footage with a TTS voiceover and
        an LLM-written script is exempt (scripts count as "production
        assistance"), so this defaults to off.

        Turn it on in config.toml when a video really does need it, e.g. when
        using AI-generated video sources (WaveSpeed) or AI-generated
        background music (Sonilo / ElevenLabs Music).
        """
        return bool(config.youtube.get("contains_synthetic_media", False))

    def is_configured(self) -> bool:
        return self.enabled and os.path.isfile(self.token_file)

    def granted_scopes(self) -> list[str]:
        """The scopes stored with the token, [] when there is no token."""
        import json

        try:
            with open(self.token_file, "r", encoding="utf-8") as f:
                scopes = json.load(f).get("scopes") or []
        except (OSError, ValueError, AttributeError):
            return []
        if isinstance(scopes, str):
            scopes = scopes.split()
        return list(scopes)

    def missing_scopes(self, required: list[str]) -> list[str]:
        granted = set(self.granted_scopes())
        return [scope for scope in required if scope not in granted]

    def _load_credentials(self):
        from google.auth.transport.requests import Request
        from google.oauth2.credentials import Credentials

        if not os.path.isfile(self.token_file):
            raise YoutubeUploadError(
                f"YouTube token file not found: {self.token_file}. "
                "Run `python youtube_auth.py` once to authorize."
            )

        # 按令牌自身保存的授权范围加载：刷新时请求比授权时更多的范围会被
        # Google 拒绝（invalid_scope），老令牌只有上传权限，不能因为新增了
        # 分析权限就让上传失效。
        credentials = Credentials.from_authorized_user_file(
            self.token_file, self.granted_scopes() or [UPLOAD_SCOPE]
        )
        if credentials.expired and credentials.refresh_token:
            logger.info("refreshing expired YouTube credentials")
            credentials.refresh(Request())
            self._save_credentials(credentials)
        if not credentials.valid:
            raise YoutubeUploadError(
                "YouTube credentials are invalid and cannot be refreshed. "
                "Run `python youtube_auth.py` again to re-authorize."
            )
        return credentials

    def _save_credentials(self, credentials) -> None:
        import json

        token_dir = os.path.dirname(self.token_file)
        if token_dir:
            os.makedirs(token_dir, exist_ok=True)
        data = json.loads(credentials.to_json())
        # Google's consent screen lets the owner untick individual scopes, so
        # store what was actually granted rather than what was asked for.
        granted = getattr(credentials, "granted_scopes", None)
        if isinstance(granted, str):
            granted = granted.split()
        if granted:
            data["scopes"] = list(granted)
        with open(self.token_file, "w", encoding="utf-8") as f:
            json.dump(data, f)

    def _build_client(self, service: str = "youtube", version: str = "v3"):
        from googleapiclient.discovery import build

        return build(
            service, version, credentials=self._load_credentials(), cache_discovery=False
        )

    def run_auth_flow(self) -> str:
        """Run the one-time interactive OAuth flow and persist the token.

        Must run on a machine with a browser (your Mac). Copy the resulting
        token file to the VPS afterwards; uploads there refresh it headlessly.
        """
        from google_auth_oauthlib.flow import InstalledAppFlow

        if not os.path.isfile(self.client_secrets_file):
            raise YoutubeUploadError(
                f"OAuth client secrets file not found: {self.client_secrets_file}. "
                "Create a Google Cloud project, enable the YouTube Data API v3, "
                "create an OAuth Desktop client, and save its JSON there."
            )

        # Accept a partial grant (e.g. upload only) instead of oauthlib
        # raising "Scope has changed"; missing scopes are reported later.
        os.environ.setdefault("OAUTHLIB_RELAX_TOKEN_SCOPE", "1")
        flow = InstalledAppFlow.from_client_secrets_file(
            self.client_secrets_file, YOUTUBE_SCOPES
        )
        credentials = flow.run_local_server(port=0, open_browser=True)
        self._save_credentials(credentials)
        logger.success(f"YouTube authorization saved to {self.token_file}")
        missing = self.missing_scopes(YOUTUBE_SCOPES)
        if missing:
            logger.warning(
                "not every permission was granted, so some features stay off: "
                + ", ".join(missing)
            )
        return self.token_file

    def upload_video(
        self,
        video_path: str,
        title: str,
        description: str = "",
        tags: Optional[list] = None,
        privacy_status: Optional[str] = None,
        thumbnail_path: Optional[str] = None,
        publish_at: Optional[str] = None,
    ) -> dict:
        """Upload one video; returns ``{"success", "video_id", "error"}``.

        ``publish_at`` (ISO 8601 UTC) makes YouTube auto-publish the private
        video at that moment; leave unset for the manual review workflow.
        """
        from google.auth.exceptions import RefreshError
        from googleapiclient.errors import HttpError
        from googleapiclient.http import MediaFileUpload

        if not os.path.isfile(video_path):
            return {"success": False, "error": f"video file not found: {video_path}"}

        tags = tags or []
        tags_total = 0
        bounded_tags = []
        for tag in tags:
            tag = str(tag).strip().lstrip("#")
            if not tag:
                continue
            tags_total += len(tag) + 2
            if tags_total > _MAX_TAGS_TOTAL_LENGTH:
                break
            bounded_tags.append(tag)

        status: dict = {
            "privacyStatus": privacy_status or self.default_privacy_status,
            "selfDeclaredMadeForKids": False,
        }
        # 仅在配置显式开启时声明合成媒体。YouTube 只对"逼真的"合成内容和
        # AI 生成音乐强制要求该标签；素材视频 + TTS 旁白不属于该范围。
        if self.contains_synthetic_media:
            status["containsSyntheticMedia"] = True
        if publish_at:
            status["publishAt"] = publish_at
            status["privacyStatus"] = "private"

        body = {
            "snippet": {
                "title": title[:_MAX_TITLE_LENGTH],
                "description": description[:_MAX_DESCRIPTION_LENGTH],
                "tags": bounded_tags,
                "categoryId": self.category_id,
            },
            "status": status,
        }

        try:
            client = self._build_client()
            media = MediaFileUpload(
                video_path, chunksize=8 * 1024 * 1024, resumable=True
            )
            request = client.videos().insert(
                part="snippet,status", body=body, media_body=media
            )

            logger.info(f"uploading to YouTube: {os.path.basename(video_path)}")
            response = None
            while response is None:
                upload_status, response = request.next_chunk()
                if upload_status:
                    logger.info(
                        f"upload progress: {int(upload_status.progress() * 100)}%"
                    )

            video_id = response.get("id", "")
            logger.success(
                f"uploaded to YouTube as {status['privacyStatus']}: "
                f"https://youtu.be/{video_id}"
            )

            if thumbnail_path and os.path.isfile(thumbnail_path):
                self._set_thumbnail(client, video_id, thumbnail_path)

            return {"success": True, "video_id": video_id}
        except HttpError as e:
            error = f"YouTube API error: {e.status_code} {e.reason}"
            logger.error(error)
            return {"success": False, "error": error}
        except RefreshError as e:
            # 刷新令牌失效（最常见：OAuth 应用停留在 "Testing" 状态，
            # 刷新令牌 7 天后过期），必须重新授权，不能靠重试恢复。
            error = (
                f"YouTube authorization expired ({str(e)}). Run "
                "`python youtube_auth.py` again and copy the new "
                f"{self.token_file} to this machine."
            )
            logger.error(error)
            return {"success": False, "error": error}
        except Exception as e:
            # 上传失败绝不能向上抛：调用方（排期 runner）会因此把整次运行
            # 中断，条目永远停在 generating 状态。
            logger.exception(f"YouTube upload failed: {str(e)}")
            return {"success": False, "error": f"{type(e).__name__}: {str(e)}"}

    def _set_thumbnail(self, client, video_id: str, thumbnail_path: str) -> None:
        from googleapiclient.errors import HttpError
        from googleapiclient.http import MediaFileUpload

        try:
            client.thumbnails().set(
                videoId=video_id,
                media_body=MediaFileUpload(thumbnail_path),
            ).execute()
            logger.info(f"thumbnail set for video {video_id}")
        except HttpError as e:
            # 未通过手机验证的频道无法调用自定义缩略图接口。
            # 缩略图失败不应导致整次上传失败。
            logger.warning(
                f"failed to set thumbnail (channel may not be verified for "
                f"custom thumbnails): {e.status_code} {e.reason}"
            )


youtube_upload_service = YoutubeUploadService()
