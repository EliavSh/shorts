"""Channel strategist: diversity cooldown + best-effort degradation."""
from __future__ import annotations

from shorts.pipelines.stocks.planner import strategist
from shorts.pipelines.stocks.planner.published import PublishedEntry, PublishedLedger


def _ledger(entries):
    return PublishedLedger(entries=entries)


def _entry(slug, tickers, sector, fmt="news_deep_dive", yid="", title=""):
    return PublishedEntry(slug=slug, title=title or slug, format=fmt,
                          tickers=tickers, sector=sector, youtube_id=yid,
                          published_at="2026-06-01T10:00:00")


def test_cooldown_flags_overcovered_ticker(monkeypatch) -> None:
    # NVDA in 6 of 8 recent clips → over-covered.
    entries = [_entry(f"c{i}", ["NVDA"], "Semiconductors") for i in range(6)]
    entries += [_entry("c6", ["JPM"], "Financials"), _entry("c7", ["XOM"], "Energy")]
    monkeypatch.setattr(strategist, "load_published", lambda: _ledger(entries))
    monkeypatch.setattr(strategist, "_video_stats", lambda ids: {})
    monkeypatch.setattr(strategist, "_llm_directive", lambda *a, **k: (_ for _ in ()).throw(RuntimeError("no llm")))

    s = strategist.compute_strategy()
    assert "NVDA" in s.cooldown_tickers
    assert "Semiconductors" in s.cooldown_sectors
    assert s.sample_size == 8
    assert s.directive  # template fallback always returns something


def test_balanced_history_no_cooldown(monkeypatch) -> None:
    entries = [_entry("a", ["NVDA"], "Semiconductors"), _entry("b", ["JPM"], "Financials"),
               _entry("c", ["XOM"], "Energy"), _entry("d", ["AAPL"], "Tech")]
    monkeypatch.setattr(strategist, "load_published", lambda: _ledger(entries))
    monkeypatch.setattr(strategist, "_video_stats", lambda ids: {})
    monkeypatch.setattr(strategist, "_llm_directive", lambda *a, **k: (_ for _ in ()).throw(RuntimeError("x")))
    s = strategist.compute_strategy()
    assert s.cooldown_tickers == []


def test_empty_history(monkeypatch) -> None:
    monkeypatch.setattr(strategist, "load_published", lambda: _ledger([]))
    s = strategist.compute_strategy()
    assert s.cooldown_tickers == []
    assert s.directive  # neutral directive


def test_video_stats_empty_without_key(monkeypatch) -> None:
    # No API key → no network call, returns {}.
    from shorts.pipelines.stocks import settings as st
    monkeypatch.setattr(st, "get_settings", lambda: type("S", (), {"youtube_api_key": ""})())
    monkeypatch.setattr(strategist, "get_settings", lambda: type("S", (), {"youtube_api_key": ""})())
    assert strategist._video_stats(["abc"]) == {}


def test_get_strategy_uses_cache(monkeypatch) -> None:
    from datetime import datetime
    from shorts.pipelines.stocks.planner import store
    from shorts.pipelines.stocks.planner.models import Strategy

    fresh = Strategy(directive="cached", computed_at=datetime.now().isoformat(timespec="seconds"))
    monkeypatch.setattr(store, "load_strategy", lambda: fresh)
    called = {"n": 0}
    monkeypatch.setattr(strategist, "compute_strategy",
                        lambda: called.__setitem__("n", called["n"] + 1) or Strategy())
    out = strategist.get_strategy(max_age_hours=18)
    assert out.directive == "cached" and called["n"] == 0  # used cache, didn't recompute
