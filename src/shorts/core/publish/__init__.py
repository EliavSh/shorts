"""Shared publish primitives."""
from __future__ import annotations

import os
from pathlib import Path

from shorts.config import REPO_ROOT

from .youtube import (
    UploadResult,
    YouTubeAuth,
    get_authenticated_service,
    run_oauth_flow,
    set_privacy,
    upload_short,
)

__all__ = [
    "UploadResult",
    "YouTubeAuth",
    "auth_from_env",
    "get_authenticated_service",
    "run_oauth_flow",
    "set_privacy",
    "upload_short",
]


def auth_from_env(pipeline: str) -> YouTubeAuth:
    """Build a YouTubeAuth from pipeline-prefixed env vars.

    Reads <PIPELINE>_YOUTUBE_CLIENT_SECRET_PATH,
          <PIPELINE>_YOUTUBE_TOKEN_PATH,
          <PIPELINE>_YOUTUBE_CHANNEL_ID
    (also recognises *_STAGING_CHANNEL_ID for stocks parity).
    """
    prefix = pipeline.upper()
    cs_path = os.environ.get(f"{prefix}_YOUTUBE_CLIENT_SECRET_PATH", "").strip()
    tk_path = os.environ.get(f"{prefix}_YOUTUBE_TOKEN_PATH", "").strip()
    channel = (
        os.environ.get(f"{prefix}_YOUTUBE_CHANNEL_ID", "").strip()
        or os.environ.get(f"{prefix}_YOUTUBE_STAGING_CHANNEL_ID", "").strip()
    )
    if not cs_path or not tk_path:
        raise RuntimeError(
            f"Set {prefix}_YOUTUBE_CLIENT_SECRET_PATH and "
            f"{prefix}_YOUTUBE_TOKEN_PATH in .env (see .env.example)."
        )

    def _abs(p: str) -> Path:
        path = Path(p)
        return path if path.is_absolute() else (REPO_ROOT / path)

    return YouTubeAuth(
        client_secret_path=_abs(cs_path),
        token_path=_abs(tk_path),
        channel_id=channel,
    )
