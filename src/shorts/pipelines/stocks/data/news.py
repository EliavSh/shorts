"""News fetcher — merges Finnhub company-news with Yahoo Finance's per-ticker
RSS feed. Each item is folded into a compact "<headline> — <summary>" string so
the script writer gets real article context, not just a bare title.

RSS is parsed with the stdlib (xml.etree) to avoid a new dependency in the Fly
image. Every provider is best-effort: a failure returns [] and the others still
contribute. Callers must handle an empty list.
"""
from __future__ import annotations

import logging
import re
from datetime import date, timedelta
from xml.etree import ElementTree as ET

import httpx

from ..settings import get_settings

log = logging.getLogger(__name__)

_TIMEOUT = 10.0
_MAX_SUMMARY = 160


def _clean(text: str) -> str:
    """Strip HTML tags and collapse whitespace."""
    text = re.sub(r"<[^>]+>", " ", text or "")
    return re.sub(r"\s+", " ", text).strip()


def _compose(headline: str, summary: str) -> str:
    """"Headline — short summary", or just the headline when the summary is
    empty or merely repeats the title."""
    headline = _clean(headline)
    summary = _clean(summary)
    if summary and summary.lower() != headline.lower():
        if len(summary) > _MAX_SUMMARY:
            summary = summary[:_MAX_SUMMARY].rstrip() + "…"
        return f"{headline} — {summary}"
    return headline


def _finnhub_company_news(ticker: str, *, days_back: int) -> list[tuple[str, str]]:
    """(headline, summary) pairs from Finnhub's free company-news endpoint."""
    s = get_settings()
    if not s.finnhub_api_key:
        log.debug("FINNHUB_API_KEY not set — skipping Finnhub news for %s", ticker)
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
        r = httpx.get(url, params=params, timeout=_TIMEOUT)
        r.raise_for_status()
        items = r.json() or []
    except Exception as e:
        log.warning("Finnhub news fetch failed for %s: %s", ticker, e)
        return []
    return [(it.get("headline", ""), it.get("summary", "")) for it in items]


def _yahoo_rss_ticker(ticker: str) -> list[tuple[str, str]]:
    """(headline, summary) pairs from Yahoo Finance's per-ticker RSS (keyless)."""
    url = "https://feeds.finance.yahoo.com/rss/2.0/headline"
    params = {"s": ticker.upper(), "region": "US", "lang": "en-US"}
    try:
        r = httpx.get(url, params=params, timeout=_TIMEOUT, follow_redirects=True)
        r.raise_for_status()
        return parse_rss_items(r.text)
    except Exception as e:
        log.debug("Yahoo RSS fetch failed for %s: %s", ticker, e)
        return []


def parse_rss_items(xml_text: str) -> list[tuple[str, str]]:
    """Pull (title, description) out of an RSS 2.0 / Atom document. Best-effort:
    returns [] on a parse error. Shared with the trending module."""
    out: list[tuple[str, str]] = []
    try:
        root = ET.fromstring(xml_text)
    except Exception:
        return out
    for item in root.findall(".//item"):  # RSS 2.0
        out.append((item.findtext("title") or "", item.findtext("description") or ""))
    if not out:  # Atom fallback (namespaced <entry>)
        for entry in root.iter():
            if entry.tag.endswith("entry"):
                title = summary = ""
                for child in entry:
                    if child.tag.endswith("title"):
                        title = child.text or ""
                    elif child.tag.endswith("summary") or child.tag.endswith("content"):
                        summary = child.text or ""
                out.append((title, summary))
    return out


def get_news_for_ticker(ticker: str, *, days_back: int = 3, limit: int = 6) -> list[str]:
    """Up to `limit` recent "headline — summary" strings for the ticker, merged
    across providers and de-duplicated on the headline. [] when all fail."""
    providers = (
        _finnhub_company_news(ticker, days_back=days_back),
        _yahoo_rss_ticker(ticker),
    )
    out: list[str] = []
    seen: set[str] = set()
    for items in providers:
        for headline, summary in items:
            h = _clean(headline)
            if not h:
                continue
            key = re.sub(r"[^a-z0-9]", "", h.lower())[:60]
            if not key or key in seen:
                continue
            seen.add(key)
            out.append(_compose(h, summary))
            if len(out) >= limit:
                return out
    return out
