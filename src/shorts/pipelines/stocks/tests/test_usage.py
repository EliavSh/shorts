"""Tests for the cost / usage tracking module."""
from datetime import datetime, timedelta

from shorts.core.usage import (
    UsageEvent,
    cost_for_event,
    record,
    set_current_video,
    set_pipeline,
    spend_by_provider,
    spend_by_video,
)


def setup_function() -> None:
    # Each test runs against the stocks pipeline's DB.
    set_pipeline("stocks")


def test_anthropic_cost_calc() -> None:
    """Opus 4.7 should bill at $15/M input + $75/M output per prices.yaml."""
    cost = cost_for_event(
        provider="anthropic", operation="messages", model="claude-opus-4-7",
        units_in=1_000_000, units_out=0, units=0,
    )
    assert cost == 15.0
    cost = cost_for_event(
        provider="anthropic", operation="messages", model="claude-opus-4-7",
        units_in=0, units_out=1_000_000, units=0,
    )
    assert cost == 75.0


def test_serper_cost_calc() -> None:
    cost = cost_for_event(
        provider="serper", operation="image_search", model=None,
        units_in=0, units_out=0, units=10,
    )
    assert cost == 10 * 0.002


def test_record_persists_and_attributes_video() -> None:
    set_current_video("test_slug")
    ev = record("serper", "image_search", units=1, note="probe")
    assert isinstance(ev, UsageEvent)
    assert ev.video_slug == "test_slug"
    assert ev.cost_usd == 0.002
    set_current_video(None)


def test_rollups() -> None:
    set_current_video("alpha")
    record("serper", "image_search", units=1)
    record("serper", "image_search", units=1)
    record("anthropic", "messages", model="claude-sonnet-4-6", units_in=10_000, units_out=2_000)

    set_current_video("beta")
    record("pexels", "image_search", units=1)
    set_current_video(None)

    since = datetime.utcnow() - timedelta(minutes=5)
    by_p = spend_by_provider(pipeline="stocks", since=since)
    assert by_p["serper"]["events"] >= 2
    assert by_p["anthropic"]["units_in"] >= 10_000

    by_v = spend_by_video(pipeline="stocks", since=since)
    assert "alpha" in by_v
    assert "beta" in by_v
    assert by_v["alpha"]["events"] >= 3
