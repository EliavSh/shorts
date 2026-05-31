"""Topic picker — surfaces today's most interesting tickers and known causal
links between them. The script writer decides which format to use; this module
no longer forces a two-story-pivot.
"""
from __future__ import annotations

import logging
import math
from functools import lru_cache

import yaml

from ..script.schemas import CausalLink, TickerSnapshot, TopicContext
from ..settings import get_settings
from .market import TickerQuote, get_quote, top_movers
from .news import get_news_for_ticker

log = logging.getLogger(__name__)


@lru_cache(maxsize=1)
def _pivots() -> dict[str, list[dict]]:
    from pathlib import Path
    p = Path(__file__).resolve().parent / "pivots.yaml"
    return yaml.safe_load(p.read_text(encoding="utf-8")) or {}


def _score(q: TickerQuote, news_count: int) -> float:
    vol_factor = math.log10(max(q.volume, 1) + 10)
    news_bonus = 1.0 + min(news_count, 5) * 0.15
    return abs(q.change_pct) * vol_factor * news_bonus


def _quote_to_snapshot(q: TickerQuote, headlines: list[str]) -> TickerSnapshot:
    return TickerSnapshot(
        ticker=q.ticker,
        name=q.name,
        change_pct=q.change_pct,
        price=q.price,
        volume=q.volume,
        market_cap=q.market_cap,
        sector=q.sector,
        industry=q.industry,
        ohlc_30d=q.ohlc_30d,
        headlines=headlines[:6],
    )


def _suggest_links(candidates: list[TickerSnapshot]) -> list[CausalLink]:
    """Pull causal links from pivots.yaml whose endpoints are both in candidates."""
    by_ticker = {c.ticker: c for c in candidates}
    links: list[CausalLink] = []
    for src, entries in _pivots().items():
        if src not in by_ticker:
            continue
        for e in entries:
            dst = e["ticker"]
            if dst in by_ticker:
                links.append(CausalLink(from_ticker=src, to_ticker=dst, reason=e["reason"]))
    return links


def build_context_for(
    tickers: list[str], *, lang: str = "en",
    theme: str | None = None, macro_notes: str | None = None,
) -> TopicContext | None:
    """Build a TopicContext for an explicit set of tickers (planner-seeded).

    Unlike `pick_topic` (which scans for the day's movers), this enriches a
    caller-chosen list — used by the planner to render a specific format about
    specific companies. Returns None only if not a single ticker resolves.
    The `theme` (e.g. a sector arc) and `macro_notes` are folded into
    macro_notes so the writer keeps them in mind.
    """
    snaps: list[TickerSnapshot] = []
    for sym in tickers:
        q = get_quote(sym)
        if q is None:
            log.warning("build_context_for: could not quote %s — skipping", sym)
            continue
        snaps.append(_quote_to_snapshot(q, get_news_for_ticker(q.ticker)))

    if not snaps and tickers:
        # Ticker-less formats (fun_fact, myth) still want a context; only bail
        # when the caller wanted tickers and none resolved.
        log.warning("build_context_for: no tickers resolved from %s", tickers)
        return None

    notes_parts = [p for p in (theme, macro_notes) if p]
    notes = " ".join(notes_parts) if notes_parts else None

    # A single-element candidate list would violate the schema's min_length=1
    # only when empty; ticker-less formats need a placeholder candidate. We keep
    # at least the resolved snaps, else synthesize a thin placeholder.
    candidates = snaps or [TickerSnapshot(ticker="MKT", name="Market", change_pct=0.0)]

    return TopicContext(
        lang=lang,  # type: ignore[arg-type]
        candidates=candidates,
        suggested_links=_suggest_links(snaps),
        macro_notes=notes,
    )


def pick_topic(*, lang: str = "he", limit_universe: int = 8) -> TopicContext | None:
    """Build today's TopicContext from live market data."""
    movers = top_movers(n=limit_universe)
    if not movers:
        log.warning("no movers returned from market data")
        return None

    candidates: list[TickerSnapshot] = []
    scored: list[tuple[float, TickerSnapshot]] = []
    for q in movers:
        headlines = get_news_for_ticker(q.ticker)
        snap = _quote_to_snapshot(q, headlines)
        scored.append((_score(q, len(headlines)), snap))

    scored.sort(key=lambda t: t[0], reverse=True)
    candidates = [s for _, s in scored]

    links = _suggest_links(candidates)
    log.info("Picked %d candidates, %d suggested links", len(candidates), len(links))

    return TopicContext(
        lang=lang,  # type: ignore[arg-type]
        candidates=candidates,
        suggested_links=links,
        macro_notes=None,
    )
