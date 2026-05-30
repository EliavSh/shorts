"""YouTube Data API v3 uploader, pipeline-aware.

Each pipeline configures its own OAuth client + token paths + channel ID (so
brawl uploads to one channel and stocks to another). The functions in this
module take that config explicitly — there is no global settings reference.

Quota cost per call (against the daily 10,000-unit YouTube Data API quota):
    upload_short           1,600 units
    set_privacy               50 units

Setup once per pipeline:
  1. https://console.cloud.google.com/apis/credentials → Create OAuth 2.0
     Client ID → type "Desktop application".
  2. Download JSON to ./secrets/<pipeline>_youtube_client.json.
  3. Enable YouTube Data API v3 on the project.
  4. First upload triggers the browser auth flow; refresh token is saved.
"""
from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from tenacity import (
    before_sleep_log,
    retry,
    retry_if_exception_type,
    stop_after_attempt,
    wait_exponential,
)

from shorts.core.usage.record import record as record_usage

log = logging.getLogger(__name__)

DEFAULT_CATEGORY_ID = "25"  # News & Politics; finance + gameplay both fit here algorithmically
SCOPES = [
    "https://www.googleapis.com/auth/youtube.upload",
    "https://www.googleapis.com/auth/youtube",
]


@dataclass(frozen=True)
class YouTubeAuth:
    """OAuth config for one YouTube channel."""
    client_secret_path: Path
    token_path: Path
    channel_id: str = ""        # informational; not required for upload


@dataclass(frozen=True)
class UploadResult:
    video_id: str
    title: str
    privacy: str
    url: str


def run_oauth_flow(auth: YouTubeAuth) -> Path:
    """Interactive: opens browser, user authorizes, refresh token saved."""
    from google_auth_oauthlib.flow import InstalledAppFlow

    if not auth.client_secret_path.exists():
        raise FileNotFoundError(
            f"YouTube OAuth client secrets not found at {auth.client_secret_path}. "
            "Download the OAuth 2.0 Client ID (Desktop application) JSON from "
            "https://console.cloud.google.com/apis/credentials and place it there."
        )

    flow = InstalledAppFlow.from_client_secrets_file(str(auth.client_secret_path), SCOPES)
    creds = flow.run_local_server(port=0)
    auth.token_path.parent.mkdir(parents=True, exist_ok=True)
    auth.token_path.write_text(creds.to_json(), encoding="utf-8")
    log.info("YouTube OAuth token saved to %s", auth.token_path)
    return auth.token_path


def get_authenticated_service(auth: YouTubeAuth):
    """Build a googleapiclient YouTube service authorised by the saved token.

    Refreshes the access token automatically if it has expired.
    """
    from google.auth.transport.requests import Request
    from google.oauth2.credentials import Credentials
    from googleapiclient.discovery import build

    if not auth.token_path.exists():
        raise FileNotFoundError(
            f"No YouTube token at {auth.token_path}. Run OAuth flow first."
        )

    token_data = json.loads(auth.token_path.read_text(encoding="utf-8"))
    creds = Credentials.from_authorized_user_info(token_data, SCOPES)
    if not creds.valid:
        if creds.expired and creds.refresh_token:
            creds.refresh(Request())
            auth.token_path.write_text(creds.to_json(), encoding="utf-8")
        else:
            raise RuntimeError("YouTube token invalid and not refreshable — re-run auth.")
    return build("youtube", "v3", credentials=creds, cache_discovery=False)


@retry(
    retry=retry_if_exception_type((ConnectionError, TimeoutError, OSError)),
    stop=stop_after_attempt(5),
    wait=wait_exponential(multiplier=2, min=2, max=30),
    before_sleep=before_sleep_log(log, logging.WARNING),
    reraise=True,
)
def _resumable_upload_with_retry(request):
    response = None
    while response is None:
        status, response = request.next_chunk()
        if status:
            log.info("  upload progress: %d%%", int(status.progress() * 100))
    return response


def upload_short(
    *,
    auth: YouTubeAuth,
    mp4_path: Path,
    title: str,
    description: str,
    tags: list[str] | None = None,
    privacy: str = "unlisted",
    made_for_kids: bool = False,
    category_id: str = DEFAULT_CATEGORY_ID,
    pipeline: str | None = None,
) -> UploadResult:
    """Upload mp4_path as a YouTube Short via the given OAuth auth.

    By default uploads as `unlisted` so the dashboard can review before flipping
    to public.
    """
    from googleapiclient.http import MediaFileUpload

    if not mp4_path.exists():
        raise FileNotFoundError(mp4_path)

    yt = get_authenticated_service(auth)

    # Append the magic #Shorts tag → YouTube auto-classifies as a Short.
    desc = description.rstrip()
    if "#Shorts" not in desc and "#shorts" not in desc:
        desc = f"{desc}\n\n#Shorts"

    body: dict[str, Any] = {
        "snippet": {
            "title": title[:99],
            "description": desc[:4900],
            "tags": (tags or [])[:30],
            "categoryId": category_id,
        },
        "status": {
            "privacyStatus": privacy,
            "selfDeclaredMadeForKids": made_for_kids,
            "embeddable": True,
        },
    }
    media = MediaFileUpload(str(mp4_path), chunksize=-1, resumable=True, mimetype="video/mp4")
    request = yt.videos().insert(part="snippet,status", body=body, media_body=media)

    log.info("Uploading %s to channel=%s ...", mp4_path.name, auth.channel_id or "(default)")
    response = _resumable_upload_with_retry(request)
    video_id = response["id"]
    log.info("Uploaded as video_id=%s", video_id)
    record_usage(
        "youtube_data_v3", "upload",
        units=1600,
        pipeline=pipeline,
        note=f"video_id={video_id} channel={auth.channel_id}",
    )

    return UploadResult(
        video_id=video_id,
        title=title,
        privacy=privacy,
        url=f"https://www.youtube.com/watch?v={video_id}",
    )


def set_privacy(*, auth: YouTubeAuth, video_id: str, privacy: str, pipeline: str | None = None) -> None:
    """Flip an uploaded video's privacy. Used to promote unlisted → public."""
    yt = get_authenticated_service(auth)
    yt.videos().update(
        part="status",
        body={"id": video_id, "status": {"privacyStatus": privacy}},
    ).execute()
    log.info("Set %s privacy=%s", video_id, privacy)
    record_usage(
        "youtube_data_v3", "privacy_update",
        units=50,
        pipeline=pipeline,
        note=f"video_id={video_id} → {privacy}",
    )
