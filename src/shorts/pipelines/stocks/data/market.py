"""Market data — quotes, top movers, sector classification.

Uses yfinance as the primary free source; falls back gracefully when data is
missing. All functions return plain dataclasses so downstream code never
depends on yfinance internals.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from functools import lru_cache

import yfinance as yf

log = logging.getLogger(__name__)


@dataclass
class TickerQuote:
    ticker: str
    name: str
    price: float
    change_pct: float
    volume: int
    market_cap: float | None = None
    sector: str | None = None
    industry: str | None = None
    ohlc_30d: list[tuple[float, float, float, float]] = field(default_factory=list)
    """List of (open, high, low, close) for the last 30 trading days."""


def get_quote(ticker: str) -> TickerQuote | None:
    """Fetch a single ticker quote with 30-day OHLC for chart rendering."""
    try:
        t = yf.Ticker(ticker)
        info = t.info or {}
        hist = t.history(period="40d", interval="1d")  # extra days to ensure 30 trading days
        if hist.empty:
            log.warning("no history for %s", ticker)
            return None

        recent = hist.tail(30)
        ohlc = [(float(r.Open), float(r.High), float(r.Low), float(r.Close)) for r in recent.itertuples()]

        last_close = float(recent["Close"].iloc[-1])
        prev_close = float(recent["Close"].iloc[-2]) if len(recent) > 1 else last_close
        change_pct = ((last_close - prev_close) / prev_close * 100) if prev_close else 0.0

        return TickerQuote(
            ticker=ticker.upper(),
            name=info.get("shortName") or info.get("longName") or ticker.upper(),
            price=last_close,
            change_pct=round(change_pct, 2),
            volume=int(recent["Volume"].iloc[-1]),
            market_cap=info.get("marketCap"),
            sector=info.get("sector"),
            industry=info.get("industry"),
            ohlc_30d=ohlc,
        )
    except Exception as e:
        log.warning("get_quote(%s) failed: %s", ticker, e)
        return None


# A small static universe of liquid US large-caps — enough to find a daily story
# without us having to scrape an index list every morning. Expand over time.
DEFAULT_UNIVERSE: tuple[str, ...] = (
    "NVDA", "AMD", "INTC", "TSM", "AVGO", "QCOM", "MU", "ASML", "AMAT", "LRCX",
    "AAPL", "MSFT", "GOOGL", "META", "AMZN", "TSLA", "NFLX", "ORCL", "CRM", "ADBE",
    "JPM", "BAC", "GS", "MS", "WFC", "C",
    "XOM", "CVX", "COP", "OXY",
    "PFE", "MRK", "LLY", "JNJ", "ABBV",
    "DIS", "NKE", "MCD", "SBUX",
    "BA", "GE", "CAT", "DE",
    "COIN", "MSTR",
    "WMT", "COST", "TGT", "HD",
)


@lru_cache(maxsize=1)
def _universe_tuple() -> tuple[str, ...]:
    return DEFAULT_UNIVERSE


def top_movers(*, n: int = 10, universe: tuple[str, ...] | None = None) -> list[TickerQuote]:
    """Return the top-N |percent change| names in the universe today."""
    uni = universe or _universe_tuple()
    quotes: list[TickerQuote] = []
    for t in uni:
        q = get_quote(t)
        if q is not None:
            quotes.append(q)
    quotes.sort(key=lambda q: abs(q.change_pct), reverse=True)
    return quotes[:n]
