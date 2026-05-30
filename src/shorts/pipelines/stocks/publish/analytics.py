"""YouTube Analytics — pull performance metrics on promoted videos.

Stored in the existing Performance table. The script writer can then look at
the top-performing past videos and use them as few-shot examples for the next
script generation pass (`write_script(..., few_shot_winners=N)`).

Setup: the same OAuth token from `auth youtube` already has access to the
youtube.readonly scope by default. If not, re-run `auth youtube` after adding
'https://www.googleapis.com/auth/yt-analytics.readonly' to SCOPES.
"""
from __future__ import annotations

import logging
from datetime import date, datetime, timedelta

from sqlmodel import Session, select

from ..db import Performance, Upload, get_engine
from .youtube import SCOPES, get_authenticated_service  # noqa: F401 (re-exposed)

log = logging.getLogger(__name__)


def pull_recent_performance(*, lookback_days: int = 30) -> int:
    """Fetch view counts, average view duration, etc. for all promoted uploads
    in the last `lookback_days` and persist a Performance row each.

    Returns the number of Performance rows written.
    """
    from googleapiclient.errors import HttpError

    yt = get_authenticated_service()
    since = (date.today() - timedelta(days=lookback_days)).isoformat()
    today = date.today().isoformat()

    with Session(get_engine()) as session:
        uploads = session.exec(
            select(Upload).where(Upload.visibility == "public")
        ).all()

    written = 0
    for u in uploads:
        try:
            stats = yt.videos().list(
                part="statistics,contentDetails", id=u.youtube_video_id,
            ).execute()
            items = stats.get("items", [])
            if not items:
                continue
            s = items[0].get("statistics", {})
            views = int(s.get("viewCount", 0))
            likes = int(s.get("likeCount", 0))

            # YouTube Analytics API gives retention / watch time; here we use
            # the simpler videos.list stats. Upgrade to youtubeAnalytics for
            # the retention curve and avgViewDuration.
            with Session(get_engine()) as session:
                session.add(Performance(
                    upload_id=u.id,
                    fetched_at=datetime.utcnow(),
                    views=views, likes=likes,
                    avg_view_duration_s=0.0,
                ))
                session.commit()
            written += 1
        except HttpError as e:
            log.warning("analytics fetch failed for %s: %s", u.youtube_video_id, e)
    log.info("Wrote %d performance rows", written)
    return written


def top_performers(*, n: int = 3, min_views: int = 100) -> list[Performance]:
    """Return the top-N most-viewed Performance snapshots."""
    with Session(get_engine()) as session:
        return session.exec(
            select(Performance)
            .where(Performance.views >= min_views)
            .order_by(Performance.views.desc())
            .limit(n)
        ).all()
