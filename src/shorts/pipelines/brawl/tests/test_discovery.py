from __future__ import annotations

from datetime import datetime, timedelta, timezone

from shorts.pipelines.brawl.discovery.youtube import Candidate, _parse_iso8601_duration, rank_candidates


def _make(
    vid: str,
    *,
    title: str = "",
    views: int = 1000,
    age_h: float = 10.0,
    tags: list[str] | None = None,
    duration_s: int = 120,
) -> Candidate:
    return Candidate(
        video_id=vid,
        title=title,
        description="",
        channel_id="c",
        channel_title="ch",
        published_at=datetime.now(timezone.utc) - timedelta(hours=age_h),
        view_count=views,
        like_count=0,
        comment_count=0,
        duration_s=duration_s,
        tags=tags or [],
    )


def test_parse_duration() -> None:
    assert _parse_iso8601_duration("PT4M13S") == 253
    assert _parse_iso8601_duration("PT1H2M3S") == 3723
    assert _parse_iso8601_duration("PT45S") == 45
    assert _parse_iso8601_duration("") == 0


def test_velocity_floor_drops_slow_videos() -> None:
    fast = _make("fast", views=10_000, age_h=10)   # 1000 v/h
    slow = _make("slow", views=100, age_h=10)      # 10 v/h
    ranked = rank_candidates([fast, slow], boost_terms={}, penalty_terms={}, min_velocity=200)
    assert [c.video_id for c in ranked] == ["fast"]


def test_boost_term_multiplies_score() -> None:
    plain = _make("plain", title="brawl stars match", views=10_000, age_h=10)
    hype = _make("hype", title="brawl stars WORLD RECORD", views=10_000, age_h=10)
    ranked = rank_candidates(
        [plain, hype],
        boost_terms={"world record": 1.8},
        penalty_terms={},
        min_velocity=0,
    )
    assert ranked[0].video_id == "hype"
    assert ranked[0].score > ranked[1].score * 1.5


def test_min_duration_drops_short_videos() -> None:
    short = _make("short", views=10_000, age_h=10, duration_s=30)        # native short
    long = _make("long", views=10_000, age_h=10, duration_s=1200)        # 20 min
    ranked = rank_candidates(
        [short, long],
        boost_terms={},
        penalty_terms={},
        min_velocity=0,
        min_duration_s=900,
    )
    assert [c.video_id for c in ranked] == ["long"]


def test_penalty_term_demotes_score() -> None:
    a = _make("a", title="brawl stars tier list", views=20_000, age_h=10)
    b = _make("b", title="brawl stars match", views=10_000, age_h=10)
    ranked = rank_candidates(
        [a, b],
        boost_terms={},
        penalty_terms={"tier list": 0.5},
        min_velocity=0,
    )
    # a: 2000 * 0.5 = 1000. b: 1000. a should still edge it, but barely.
    assert ranked[0].score == 1000.0
    # And without the penalty, a would be 2× b.
    ranked_no_pen = rank_candidates([a, b], boost_terms={}, penalty_terms={}, min_velocity=0)
    assert ranked_no_pen[0].score == 2000.0
