"""Scrape top comments from a YouTube video and cluster timestamp mentions.

The densest cluster of M:SS / MM:SS / H:MM:SS mentions is almost always pointing
at the moment viewers rewind to.
"""
from __future__ import annotations

import re
from collections import Counter
from dataclasses import dataclass
from typing import Any

from googleapiclient.discovery import build
from googleapiclient.errors import HttpError

# Matches 1:23, 12:34, or 1:23:45 — but not bare numbers or dotted decimals.
# Anchored on a word boundary so "v1:23" doesn't match, and requires the trailing
# group to be 2 digits so dotted scores like "2:1" aren't picked up.
_TS_RE = re.compile(r"(?<!\d)(\d{1,2}):(\d{2})(?::(\d{2}))?(?!\d)")


@dataclass
class TimestampHit:
    seconds: int
    comment_likes: int
    comment_text: str


def _parse_ts(match: re.Match[str]) -> int | None:
    a, b, c = match.groups()
    if c is not None:
        h, m, s = int(a), int(b), int(c)
    else:
        h, m, s = 0, int(a), int(b)
    if m >= 60 or s >= 60:
        return None
    return h * 3600 + m * 60 + s


def extract_timestamps_from_comment(text: str) -> list[int]:
    seen: set[int] = set()
    out: list[int] = []
    for m in _TS_RE.finditer(text):
        sec = _parse_ts(m)
        if sec is None or sec in seen:
            continue
        seen.add(sec)
        out.append(sec)
    return out


def fetch_top_comments(
    api_key: str,
    video_id: str,
    max_comments: int = 200,
) -> list[dict[str, Any]]:
    """Pull top-level comments ordered by relevance. ~1 quota unit per page of 100."""
    client = build("youtube", "v3", developerKey=api_key, cache_discovery=False)
    out: list[dict[str, Any]] = []
    page_token: str | None = None
    while len(out) < max_comments:
        try:
            req = client.commentThreads().list(
                part="snippet",
                videoId=video_id,
                order="relevance",
                maxResults=min(100, max_comments - len(out)),
                textFormat="plainText",
                pageToken=page_token,
            )
            resp = req.execute()
        except HttpError as e:
            # Some videos have comments disabled — surface but don't crash.
            if e.resp.status in (403, 404):
                return out
            raise
        for item in resp.get("items", []):
            sn = item["snippet"]["topLevelComment"]["snippet"]
            out.append(
                {
                    "text": sn.get("textDisplay", ""),
                    "likes": int(sn.get("likeCount", 0)),
                    "author": sn.get("authorDisplayName", ""),
                }
            )
        page_token = resp.get("nextPageToken")
        if not page_token:
            break
    return out


def cluster_timestamps(
    hits: list[TimestampHit],
    bucket_s: int = 15,
    duration_s: int | None = None,
) -> list[tuple[int, int, float]]:
    """Group nearby timestamps into buckets and rank by weighted vote.

    Returns sorted list of (center_seconds, mentions, weight) — weight uses
    log(1 + likes) so that one viral comment doesn't dominate over consensus.
    """
    import math

    raw: list[tuple[int, float]] = []
    for h in hits:
        if duration_s is not None and h.seconds > duration_s:
            continue
        # Drop timestamps in the first 30s or last 30s — almost always intros/outros.
        if h.seconds < 30:
            continue
        if duration_s is not None and h.seconds > duration_s - 30:
            continue
        weight = 1.0 + math.log1p(h.comment_likes)
        raw.append((h.seconds, weight))

    if not raw:
        return []

    raw.sort()
    # Sliding-window cluster: any two timestamps within bucket_s are in the same group.
    clusters: list[list[tuple[int, float]]] = []
    cur: list[tuple[int, float]] = [raw[0]]
    for ts, w in raw[1:]:
        if ts - cur[-1][0] <= bucket_s:
            cur.append((ts, w))
        else:
            clusters.append(cur)
            cur = [(ts, w)]
    clusters.append(cur)

    out: list[tuple[int, int, float]] = []
    for group in clusters:
        weighted = sum(w for _, w in group)
        center = round(sum(t for t, _ in group) / len(group))
        out.append((center, len(group), weighted))
    # Sort: heaviest weighted cluster first.
    out.sort(key=lambda x: x[2], reverse=True)
    return out


def find_moment_from_comments(
    api_key: str,
    video_id: str,
    duration_s: int | None = None,
    max_comments: int = 200,
) -> list[tuple[int, int, float]]:
    """Convenience: fetch → extract → cluster → return ranked clusters."""
    comments = fetch_top_comments(api_key, video_id, max_comments=max_comments)
    hits: list[TimestampHit] = []
    for c in comments:
        for sec in extract_timestamps_from_comment(c["text"]):
            hits.append(TimestampHit(seconds=sec, comment_likes=c["likes"], comment_text=c["text"]))
    return cluster_timestamps(hits, duration_s=duration_s)
