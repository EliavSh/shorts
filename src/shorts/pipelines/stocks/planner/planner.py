"""Plan builder — blends commitments (debt), the earnings calendar, recurring
series, the tuning knobs, and freshness into a forward content calendar.

`build_plan` is pure given its inputs (movers/earnings/commitments/config), so
it's deterministic and testable offline. The CLI / autopilot gathers the live
inputs and persists the result via store.py.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import date, timedelta

from .. import formats
from ..data.market import DEFAULT_UNIVERSE
from .models import (
    Commitment,
    OrchestrationConfig,
    Plan,
    PlannedVideo,
    TopicSeed,
)

log = logging.getLogger(__name__)


# Formats the planner may pick on its own to fill slots (the earnings formats
# are only used when the calendar actually has events, handled separately).
_FILLABLE = (
    "deep_dive_one_stock",
    "news_deep_dive",
    "fun_fact",
    "story_telling",
    "myth_vs_reality",
    "sector_spotlight",
    "two_story_pivot",
)

_DEFAULT_TYPE_MIX = {
    "deep_dive_one_stock": 1.0,
    "news_deep_dive": 0.9,
    "fun_fact": 0.8,
    "myth_vs_reality": 0.7,
    "story_telling": 0.6,
    "sector_spotlight": 0.6,
    "two_story_pivot": 0.5,
}


@dataclass(frozen=True)
class MoverLite:
    """Minimal mover info the planner needs (decouples from yfinance/TickerQuote)."""
    ticker: str
    sector: str | None = None
    change_pct: float = 0.0


@dataclass(frozen=True)
class EarningsLite:
    ticker: str
    report_date: date


def _band(fmt: str) -> tuple[int, int]:
    try:
        return formats.get_spec(fmt).length_band
    except KeyError:
        return (90, 120)


def _ticker_range(fmt: str) -> tuple[int, int]:
    try:
        spec = formats.get_spec(fmt)
        return spec.min_tickers, spec.max_tickers
    except KeyError:
        return (1, 1)


def _commitment_format(c: Commitment) -> str:
    blob = f"{c.text} {c.trigger or ''}".lower()
    if "earnings" in blob or "report" in blob or "results" in blob:
        return "earnings_scorecard"
    return "news_deep_dive"


def _order_movers(movers: list[MoverLite], sector_bias: dict[str, float]) -> list[MoverLite]:
    """Rank movers by sector bias then by |change|, so a biased sector floats up."""
    def key(m: MoverLite) -> tuple[float, float]:
        w = sector_bias.get(m.sector or "", 0.0) if sector_bias else 0.0
        return (w, abs(m.change_pct))
    return sorted(movers, key=key, reverse=True)


def _fill_format_sequence(config: OrchestrationConfig, n: int) -> list[str]:
    """A deterministic, weight-ordered, rotating sequence of fill formats."""
    weights = {f: w for f, w in (config.type_mix or _DEFAULT_TYPE_MIX).items()
               if f in _FILLABLE and w > 0}
    if not weights:
        weights = {f: _DEFAULT_TYPE_MIX[f] for f in _FILLABLE}
    order = sorted(weights, key=lambda f: (-weights[f], f))
    return [order[i % len(order)] for i in range(n)]


def build_plan(
    *,
    config: OrchestrationConfig,
    commitments: list[Commitment],
    earnings: list[EarningsLite] | None = None,
    movers: list[MoverLite] | None = None,
    recent_formats: tuple[str, ...] = (),
    recent_tickers: tuple[str, ...] = (),
    today: date | None = None,
) -> Plan:
    """Assemble a content calendar of ~weekly_volume items.

    Priority order: (1) open debt, (2) this-week earnings, (3) due series,
    (4) sector/theme-biased fill honoring the type mix, avoiding recently used
    tickers/formats.
    """
    today = today or date.today()
    earnings = earnings or []
    movers = _order_movers(movers or [], config.sector_bias)

    # daily_target is the active knob: stage this many clips for *today*.
    slots = max(1, min(config.daily_target, 14))

    used_tickers: set[str] = {t.upper() for t in recent_tickers}
    mover_pool = [m for m in movers if m.ticker.upper() not in used_tickers] or movers
    pool_iter = iter(mover_pool)
    fallback_iter = iter(DEFAULT_UNIVERSE)

    def take_tickers(k: int) -> list[str]:
        out: list[str] = []
        while len(out) < k:
            m = next(pool_iter, None)
            sym = m.ticker.upper() if m else next(fallback_iter, None)
            if sym is None:
                break
            if sym in out or sym in used_tickers:
                continue
            out.append(sym)
            used_tickers.add(sym)
        return out

    items: list[PlannedVideo] = []

    # 1) Open debt — fulfil promises first.
    for c in commitments:
        if c.status != "open":
            continue
        fmt = _commitment_format(c)
        seed = c.tickers or take_tickers(_ticker_range(fmt)[0])
        items.append(PlannedVideo(
            scheduled_for=today, status="planned", format=fmt,
            length_band=_band(fmt),
            topic_seed=TopicSeed(tickers=seed, theme=c.trigger),
            title_hint=c.text[:100],
            rationale=f"Fulfils a promise: “{c.text[:80]}”",
            source="debt", commitment_id=c.id,
        ))
        for t in seed:
            used_tickers.add(t.upper())

    # 2) This-week earnings — a roundup when several land together.
    horizon = today + timedelta(days=7)
    soon = sorted([e for e in earnings if today <= e.report_date <= horizon],
                  key=lambda e: e.report_date)
    if len(soon) >= 3:
        lo, hi = _ticker_range("earnings_this_week")
        syms = [e.ticker.upper() for e in soon][:hi]
        items.append(PlannedVideo(
            scheduled_for=today, status="planned", format="earnings_this_week",
            length_band=_band("earnings_this_week"),
            topic_seed=TopicSeed(tickers=syms, theme="earnings season"),
            title_hint="Earnings to watch this week",
            rationale=f"{len(soon)} notable reports land this week.",
            source="earnings",
        ))
        used_tickers.update(syms)

    # 3) Due recurring series.
    for sx in config.active_series():
        due = sx.last_scheduled is None or (today - sx.last_scheduled).days >= sx.cadence_days
        if not due:
            continue
        if sx.total_parts is not None and sx.next_part > sx.total_parts:
            continue
        fmt = sx.format or "sector_spotlight"
        lo, hi = _ticker_range(fmt)
        seed = sx.tickers[:hi] if sx.tickers else take_tickers(lo)
        items.append(PlannedVideo(
            scheduled_for=today, status="planned", format=fmt,
            length_band=_band(fmt),
            topic_seed=TopicSeed(tickers=seed, theme=sx.theme or sx.name),
            title_hint=f"{sx.name} — part {sx.next_part}",
            rationale=f"Series “{sx.name}” part {sx.next_part} is due.",
            source="series",
        ))
        used_tickers.update(t.upper() for t in seed)

    # 4) Fill remaining slots from the type mix + biased movers.
    remaining = max(0, slots - len(items))
    for fmt in _fill_format_sequence(config, remaining):
        lo, hi = _ticker_range(fmt)
        k = lo if lo == hi else min(hi, max(lo, 3))
        seed = take_tickers(k) if hi > 0 else []
        theme = None
        if config.sector_bias:
            theme = max(config.sector_bias, key=config.sector_bias.get)
        items.append(PlannedVideo(
            scheduled_for=today, status="planned", format=fmt,
            length_band=_band(fmt),
            topic_seed=TopicSeed(tickers=seed, theme=theme),
            title_hint="",
            rationale="Fills the content mix" + (f" (bias: {theme})" if theme else "."),
            source="planner",
        ))

    # Trim to the daily target — all items are today's batch.
    items = items[:slots]
    for it in items:
        it.scheduled_for = today

    log.info("Built plan: %d items (%d debt, %d earnings, %d series)",
             len(items),
             sum(1 for x in items if x.source == "debt"),
             sum(1 for x in items if x.source == "earnings"),
             sum(1 for x in items if x.source == "series"))
    return Plan(items=items)
