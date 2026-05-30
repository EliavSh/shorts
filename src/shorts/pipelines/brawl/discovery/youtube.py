from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Any, Iterable

from googleapiclient.discovery import build
from googleapiclient.errors import HttpError


@dataclass
class Candidate:
    video_id: str
    title: str
    description: str
    channel_id: str
    channel_title: str
    published_at: datetime
    view_count: int
    like_count: int
    comment_count: int
    duration_s: int
    tags: list[str] = field(default_factory=list)
    matched_queries: set[str] = field(default_factory=set)

    # Computed downstream
    velocity: float = 0.0
    boost: float = 1.0
    score: float = 0.0
    score_rationale: str = ""

    @property
    def url(self) -> str:
        return f"https://www.youtube.com/watch?v={self.video_id}"

    @property
    def age_hours(self) -> float:
        delta = datetime.now(timezone.utc) - self.published_at
        return max(delta.total_seconds() / 3600.0, 1.0)


def _build_client(api_key: str) -> Any:
    return build("youtube", "v3", developerKey=api_key, cache_discovery=False)


def _parse_iso8601_duration(s: str) -> int:
    """Parse ISO 8601 duration like PT4M13S to seconds. Handles H, M, S."""
    if not s.startswith("PT"):
        return 0
    s = s[2:]
    total = 0
    num = ""
    for ch in s:
        if ch.isdigit():
            num += ch
        else:
            if not num:
                continue
            n = int(num)
            if ch == "H":
                total += n * 3600
            elif ch == "M":
                total += n * 60
            elif ch == "S":
                total += n
            num = ""
    return total


def search_videos(
    api_key: str,
    queries: Iterable[str],
    lookback_days: int,
    max_results_per_query: int = 50,
) -> list[Candidate]:
    """Search YouTube for each query, then hydrate stats + duration for all hits.

    Two API call types:
      - search.list (100 units each) — returns video IDs matching the query.
      - videos.list (1 unit per call, up to 50 IDs per call) — returns stats + duration.
    """
    client = _build_client(api_key)
    published_after = (datetime.now(timezone.utc) - timedelta(days=lookback_days)).strftime(
        "%Y-%m-%dT%H:%M:%SZ"
    )

    by_id: dict[str, Candidate] = {}

    for query in queries:
        try:
            resp = (
                client.search()
                .list(
                    q=query,
                    part="snippet",
                    type="video",
                    order="viewCount",
                    publishedAfter=published_after,
                    maxResults=min(max_results_per_query, 50),
                    relevanceLanguage="en",
                    safeSearch="none",
                )
                .execute()
            )
        except HttpError as e:
            # Quota exceeded or transient error — surface but keep what we have.
            raise RuntimeError(f"YouTube search failed for {query!r}: {e}") from e

        for item in resp.get("items", []):
            vid = item["id"]["videoId"]
            sn = item["snippet"]
            existing = by_id.get(vid)
            if existing:
                existing.matched_queries.add(query)
                continue
            by_id[vid] = Candidate(
                video_id=vid,
                title=sn.get("title", ""),
                description=sn.get("description", ""),
                channel_id=sn.get("channelId", ""),
                channel_title=sn.get("channelTitle", ""),
                published_at=datetime.fromisoformat(
                    sn["publishedAt"].replace("Z", "+00:00")
                ),
                view_count=0,
                like_count=0,
                comment_count=0,
                duration_s=0,
                matched_queries={query},
            )

    # Hydrate stats in batches of 50.
    ids = list(by_id.keys())
    for i in range(0, len(ids), 50):
        chunk = ids[i : i + 50]
        try:
            resp = (
                client.videos()
                .list(part="statistics,contentDetails,snippet", id=",".join(chunk))
                .execute()
            )
        except HttpError as e:
            raise RuntimeError(f"YouTube videos.list failed: {e}") from e

        for item in resp.get("items", []):
            vid = item["id"]
            cand = by_id.get(vid)
            if not cand:
                continue
            stats = item.get("statistics", {})
            cand.view_count = int(stats.get("viewCount", 0))
            cand.like_count = int(stats.get("likeCount", 0))
            cand.comment_count = int(stats.get("commentCount", 0))
            cand.duration_s = _parse_iso8601_duration(
                item.get("contentDetails", {}).get("duration", "")
            )
            cand.tags = list(item.get("snippet", {}).get("tags", []) or [])

    return list(by_id.values())


def rank_candidates(
    candidates: list[Candidate],
    boost_terms: dict[str, float],
    penalty_terms: dict[str, float],
    min_velocity: float,
    min_duration_s: int = 0,
) -> list[Candidate]:
    """Score by view velocity, multiply by hype boost / penalty, sort desc.

    Velocity = view_count / age_hours. Boost = product of any boost-term multipliers
    that appear in title/description/tags (case-insensitive). Same for penalty
    (values < 1 reduce the score). Candidates below min_velocity are dropped.
    Candidates shorter than min_duration_s are also dropped — they're almost
    certainly already-edited shorts, not raw material we can re-edit.
    """
    ranked: list[Candidate] = []
    for c in candidates:
        if c.duration_s < min_duration_s:
            continue
        velocity = c.view_count / c.age_hours
        if velocity < min_velocity:
            continue
        haystack = " ".join([c.title, c.description, *c.tags]).lower()
        boost = 1.0
        hits: list[str] = []
        for term, mult in boost_terms.items():
            if term.lower() in haystack:
                boost *= mult
                hits.append(f"+{term}")
        for term, mult in penalty_terms.items():
            if term.lower() in haystack:
                boost *= mult
                hits.append(f"-{term}")
        c.velocity = velocity
        c.boost = boost
        c.score = velocity * boost
        c.score_rationale = (
            f"{velocity:,.0f} v/h × {boost:.2f}"
            + (f" ({', '.join(hits)})" if hits else "")
        )
        ranked.append(c)

    ranked.sort(key=lambda x: x.score, reverse=True)
    return ranked
