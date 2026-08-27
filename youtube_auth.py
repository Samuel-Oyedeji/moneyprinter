"""One-time YouTube OAuth authorization.

Prerequisites (one-time, in Google Cloud Console):
  1. Create a project at https://console.cloud.google.com
  2. Enable "YouTube Data API v3" (APIs & Services > Library)
  3. Create an OAuth client ID of type "Desktop app"
     (APIs & Services > Credentials) and download its JSON
  4. Save the JSON as storage/youtube/client_secret.json
  5. Add your Google account as a test user on the OAuth consent screen

Then run:  .venv/bin/python youtube_auth.py

A browser window opens for Google sign-in; the refresh token is saved to
storage/youtube/token.json. For VPS deployments, run this locally first and
copy that token file to the server - uploads refresh it automatically.
"""
import sys

from loguru import logger

from app.services.youtube_upload import YoutubeUploadError, youtube_upload_service

if __name__ == "__main__":
    try:
        token_file = youtube_upload_service.run_auth_flow()
    except YoutubeUploadError as exc:
        logger.error(str(exc))
        sys.exit(1)
    logger.info(
        "Done. Set youtube.enabled = true in config.toml to activate uploads. "
        f"Token file: {token_file}"
    )
