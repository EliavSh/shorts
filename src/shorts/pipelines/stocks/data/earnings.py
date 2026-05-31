"""Earnings calendar — which companies in our universe report soon.

Primary source is yfinance (`Ticker.calendar` / `Ticker.get_earnings_dates`),
which needs no API key. A Finnhub `/calendar/earnings` fallback is used when a
key is present and yfinance comes back empty. Mirrors data/news.py: degrade to
`[]` on any failure so callers (the planner) never crash on a flaky network.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import date, datetime, timedelta

import httpx

from ..settings import get_settings
from .market import DEFAULT_UNIVERSE

log = logging.getLogger(__name__)


@dataclass(frozen=True)
class EarningsEvent:
    ticker: str
    report_date: date
    eps_estimate: float | None = None
    revenue_estimate: float | None = None
    when: str | None = None  # 'bmo' (before market open), 'amc' (after close), or None

    @property
    def days_away(self) -> int:
        return (self.report_date - date.today()).days


def _coerce_date(value) -> date | None:
    if value is None:
        return None
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    try:
        return datetime.fromisoformat(str(value)[:10]).date()
    except Exception:
        return None


def _yf_event(ticker: str, *, days: int) -> EarningsEvent | None:
    """Best-effort next earnings date for one ticker via yfinance."""
    import yfinance as yf

    today = date.today()
    horizon = today + timedelta(days=days)
    try:
        t = yf.Ticker(ticker)
        cal = getattr(t, "calendar", None)
        report_date: date | None = None
        eps_est: float | None = None
        rev_est: float | None = None

        # yfinance >=0.2 returns calendar as a dict; older versions a DataFrame.
        if isinstance(cal, dict):
            raw = cal.get("Earnings Date")
            if isinstance(raw, (list, tuple)) and raw:
                report_date = _coerce_date(raw[0])
            else:
                report_date = _coerce_date(raw)
            eps_est = cal.get("EPS Estimate")
            rev_est = cal.get("Revenue Estimate") or cal.get("Revenue Average")
        elif cal is not None and hasattr(cal, "empty") and not cal.empty:
            try:
                report_date = _coerce_date(cal.loc["Earnings Date"].iloc[0])
            except Exception:
                report_date = None

        if report_date is None:
            return None
        if not (today <= report_date <= horizon):
            return None

        def _num(v):
            try:
                f = float(v)
                return f if f == f else None  # drop NaN
            except (TypeError, ValueError):
                return None

        return EarningsEvent(
            ticker=ticker.upper(),
            report_date=report_date,
            eps_estimate=_num(eps_est),
            revenue_estimate=_num(rev_est),
        )
    except Exception as e:
        log.debug("yfinance earnings lookup failed for %s: %s", ticker, e)
        return None


def _finnhub_events(tickers: list[str], *, days: int) -> list[EarningsEvent]:
    """Finnhub earnings-calendar fallback. Returns [] when no key/failure."""
    s = get_settings()
    if not s.finnhub_api_key:
        return []
    today = date.today()
    to = today + timedelta(days=days)
    url = "https://finnhub.io/api/v1/calendar/earnings"
    wanted = {t.upper() for t in tickers}
    try:
        r = httpx.get(url, params={
            "from": today.isoformat(), "to": to.isoformat(),
            "token": s.finnhub_api_key,
        }, timeout=10.0)
        r.raise_for_status()
        rows = (r.json() or {}).get("earningsCalendar", []) or []
    except Exception as e:
        log.warning("Finnhub earnings calendar failed: %s", e)
        return []

    out: list[EarningsEvent] = []
    for row in rows:
        sym = (row.get("symbol") or "").upper()
        if wanted and sym not in wanted:
            continue
        d = _coerce_date(row.get("date"))
        if d is None:
            continue
        hour = (row.get("hour") or "").lower()
        when = "bmo" if hour == "bmo" else "amc" if hour == "amc" else None
        out.append(EarningsEvent(
            ticker=sym, report_date=d,
            eps_estimate=row.get("epsEstimate"),
            revenue_estimate=row.get("revenueEstimate"),
            when=when,
        ))
    return out


def upcoming_earnings(tickers: list[str] | None = None, *, days: int = 7) -> list[EarningsEvent]:
    """Return earnings events reporting within the next `days` days.

    Scans `tickers` (default: the standard universe) via yfinance, then fills
    gaps with Finnhub when a key is set. Sorted by report date ascending.
    Returns [] cleanly when offline.
    """
    syms = list(tickers) if tickers else list(DEFAULT_UNIVERSE)
    events: dict[str, EarningsEvent] = {}

    for sym in syms:
        ev = _yf_event(sym, days=days)
        if ev is not None:
            events[ev.ticker] = ev

    # Finnhub fallback — only adds tickers yfinance didn't resolve.
    for ev in _finnhub_events(syms, days=days):
        events.setdefault(ev.ticker, ev)

    return sorted(events.values(), key=lambda e: (e.report_date, e.ticker))
