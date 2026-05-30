"""Unit tests for the topic picker — uses monkeypatched market data so no
network. After the refactor the picker no longer forces a pivot; it just
surfaces candidates and known causal links.
"""
from __future__ import annotations

from shorts.pipelines.stocks.data import topic_picker
from shorts.pipelines.stocks.data.market import TickerQuote


def _mk(ticker: str, change: float, vol: int = 50_000_000) -> TickerQuote:
    return TickerQuote(
        ticker=ticker,
        name=f"{ticker} Inc.",
        price=100.0,
        change_pct=change,
        volume=vol,
        market_cap=1_000_000_000_000,
        ohlc_30d=[(100, 102, 99, 101) for _ in range(30)],
    )


def test_candidates_sorted_by_score(monkeypatch) -> None:
    quotes = [_mk("NVDA", 2.5), _mk("TSM", 1.8), _mk("AMD", 0.3)]
    monkeypatch.setattr(topic_picker, "top_movers", lambda n=10: quotes)
    monkeypatch.setattr(topic_picker, "get_news_for_ticker", lambda t, **kw: [f"news for {t}"])

    ctx = topic_picker.pick_topic(lang="he")
    assert ctx is not None
    assert [c.ticker for c in ctx.candidates] == ["NVDA", "TSM", "AMD"]


def test_links_only_between_present_candidates(monkeypatch) -> None:
    quotes = [_mk("NVDA", 2.5), _mk("TSM", 1.8)]  # AMD intentionally absent
    monkeypatch.setattr(topic_picker, "top_movers", lambda n=10: quotes)
    monkeypatch.setattr(topic_picker, "get_news_for_ticker", lambda t, **kw: [])

    ctx = topic_picker.pick_topic(lang="he")
    assert ctx is not None
    # Links should include NVDA->TSM (from pivots.yaml) but no link involving AMD.
    pairs = {(l.from_ticker, l.to_ticker) for l in ctx.suggested_links}
    assert ("NVDA", "TSM") in pairs
    assert all("AMD" not in (a, b) for a, b in pairs)


def test_returns_none_when_no_movers(monkeypatch) -> None:
    monkeypatch.setattr(topic_picker, "top_movers", lambda n=10: [])
    monkeypatch.setattr(topic_picker, "get_news_for_ticker", lambda t, **kw: [])
    assert topic_picker.pick_topic(lang="he") is None
