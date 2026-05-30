"""News fetcher — Finnhub free company-news endpoint."""
from __future__ import annotations

import logging
from datetime import date, timedelta

import httpx

from ..settings import get_settings

log = logging.getLogger(__name__)


def get_news_for_ticker(ticker: str, *, days_back: int = 3, limit: int = 6) -> list[str]:
    """Return up to `limit` recent headline strings for the given ticker.

    Returns [] if Finnhub key is missing or call fails — callers must handle empty.
    """
    s = get_settings()
    if not s.finnhub_api_key:
        log.debug("FINNHUB_API_KEY not set — skipping news for %s", ticker)
        return []

    to = date.today()
    frm = to - timedelta(days=days_back)
    url = "https://finnhub.io/api/v1/company-news"
    params = {
        "symbol": ticker.upper(),
        "from": frm.isoformat(),
        "to": to.isoformat(),
        "token": s.finnhub_api_key,
    }
    try:
        r = httpx.get(url, params=params, timeout=10.0)
        r.raise_for_status()
        items = r.json() or []
    except Exception as e:
        log.warning("Finnhub news fetch failed for %s: %s", ticker, e)
        return []

    headlines: list[str] = []
    seen: set[str] = set()
    for item in items:
        h = (item.get("headline") or "").strip()
        if h and h not in seen:
            seen.add(h)
            headlines.append(h)
        if len(headlines) >= limit:
            break
    return headlines
