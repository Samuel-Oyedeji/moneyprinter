"""
Discord webhook notifications for scheduled video generation.

Sends a message to a configured Discord webhook when a scheduled video has
been generated and uploaded to YouTube as a private draft, or when a
scheduled run fails and needs attention.
"""
from typing import Optional

import requests
from loguru import logger

from app.config import config

_REQUEST_TIMEOUT_SECONDS = 30


class DiscordNotifyService:
    @property
    def webhook_url(self) -> str:
        return config.discord.get("webhook_url", "")

    def is_configured(self) -> bool:
        return bool(self.webhook_url)

    def send(self, content: str, embed: Optional[dict] = None) -> bool:
        """Post a message to the configured webhook.

        Notifications are best-effort: a failed alert must never fail the
        schedule run itself, so all errors are logged and swallowed.
        """
        if not self.is_configured():
            logger.warning("Discord webhook is not configured. Skipping alert.")
            return False

        payload: dict = {"content": content[:2000]}
        if embed:
            payload["embeds"] = [embed]

        try:
            response = requests.post(
                self.webhook_url, json=payload, timeout=_REQUEST_TIMEOUT_SECONDS
            )
            response.raise_for_status()
            logger.info("Discord alert sent")
            return True
        except requests.exceptions.RequestException as e:
            logger.error(f"Failed to send Discord alert: {str(e)}")
            return False

    def notify_video_ready(
        self,
        title: str,
        youtube_video_id: str,
        scheduled_date: str,
        topic: str,
        post_time: str = "",
    ) -> bool:
        studio_url = f"https://studio.youtube.com/video/{youtube_video_id}/edit"
        watch_url = f"https://youtu.be/{youtube_video_id}"
        fields = [
            {"name": "Scheduled date", "value": scheduled_date, "inline": True},
            {"name": "Topic", "value": topic[:1024] or "-", "inline": True},
        ]
        if post_time:
            fields.append(
                {"name": "Planned post time", "value": post_time, "inline": True}
            )
        embed = {
            "title": title[:256],
            "url": studio_url,
            "description": (
                f"Uploaded to YouTube as **private**.\n"
                f"[Open in YouTube Studio]({studio_url}) to review and publish.\n"
                f"Preview: {watch_url}"
            ),
            "color": 0x2ECC71,
            "fields": fields,
        }
        return self.send("🎬 A scheduled video is ready to publish!", embed=embed)

    def notify_failure(self, scheduled_date: str, topic: str, error: str) -> bool:
        embed = {
            "title": "Scheduled generation failed",
            "description": f"**Topic:** {topic[:1024] or '-'}\n**Error:** {error[:2048]}",
            "color": 0xE74C3C,
            "fields": [
                {"name": "Scheduled date", "value": scheduled_date, "inline": True},
            ],
        }
        return self.send("⚠️ A scheduled video generation failed.", embed=embed)


discord_notify_service = DiscordNotifyService()
