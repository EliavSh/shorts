"""News-driven trending tickers — surfaces which symbols the market is actually
talking about today, so topic selection can favour *relevant* names rather than
merely *volatile* ones.

Two keyless/low-cost sources, both best-effort (a failure contributes nothing):
  - Finnhub general market news (`/news?category=general`): each item lists the
    symbols it's `related` to — counted directly.
  - Google News market RSS: symbols extracted from headlines via `$CASHTAG`
    regex and a match against the known universe (guards false positives from
    ordinary words).
"""
from __future__ import annotations

import logging
import re
from collections import Counter

import httpx

from ..settings import get_settings
from .market import DEFAULT_UNIVERSE
from .news import parse_rss_items

log = logging.getLogger(__name__)

_TIMEOUT = 10.0
_UNIVERSE: frozenset[str] = frozenset(DEFAULT_UNIVERSE)
_CASHTAG = re.compile(r"\$([A-Z]{1,5})\b")
# Bare uppercase tokens only count when they're a known symbol, to avoid matching
# common ALL-CAPS words (CEO, IPO, USA, ...).
_WORD = re.compile(r"\b([A-Z]{1,5})\b")


def _finnhub_general(counter: Counter) -> None:
    s = get_settings()
    if not s.finnhub_api_key:
        log.debug("FINNHUB_API_KEY not set — skipping Finnhub general news")
        return
    url = "https://finnhub.io/api/v1/news"
    try:
        r = httpx.get(url, params={"category": "general", "token": s.finnhub_api_key},
                      timeout=_TIMEOUT)
        r.raise_for_status()
        items = r.json() or []
    except Exception as e:
        log.warning("Finnhub general news fetch failed: %s", e)
        return
    for it in items:
        related = (it.get("related") or "").upper()
        for sym in re.split(r"[,\s]+", related):
            sym = sym.strip()
            if sym:
                counter[sym] += 1


def _market_rss(counter: Counter) -> None:
    url = "https://news.google.com/rss/search"
    params = {"q": "stock market", "hl": "en-US", "gl": "US", "ceid": "US:en"}
    try:
        r = httpx.get(url, params=params, timeout=_TIMEOUT, follow_redirects=True)
        r.raise_for_status()
        items = parse_rss_items(r.text)
    except Exception as e:
        log.debug("market RSS fetch failed: %s", e)
        return
    for title, summary in items:
        text = f"{title} {summary}"
        for sym in _CASHTAG.findall(text.upper()):
            counter[sym] += 1
        for sym in _WORD.findall(text):
            if sym in _UNIVERSE:
                counter[sym] += 1


def trending_tickers(*, limit: int = 12) -> dict[str, int]:
    """Map of ticker -> news-mention count, ranked, capped at `limit`. Returns
    {} when every source fails."""
    counter: Counter = Counter()
    _finnhub_general(counter)
    _market_rss(counter)
    if not counter:
        return {}
    ranked = dict(counter.most_common(limit))
    log.info("Trending tickers: %s", ranked)
    return ranked
