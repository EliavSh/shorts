"""Cost / usage tracking. One row per provider API call → per-video and
per-month rollups for the dashboard.

Public surface:
    record(provider, operation, *, units_in=0, units_out=0, units=0,
           model=None, video_slug=None, pipeline=None, success=True, note=None) -> UsageEvent

    cost_for_event(...) -> float (computed; used internally too)
    set_current_video(slug)   — context-var helper so wrappers know which video
    rollup(pipeline=None, days=30, console=None) — pretty-print rollup

Each pipeline writes to its own data/<pipeline>/usage.db. The pipeline is
resolved per-call from arg → context var → error.
"""
from __future__ import annotations

import contextvars
import logging
from datetime import datetime, timedelta
from functools import lru_cache
from pathlib import Path
from typing import Any

import yaml
from sqlmodel import Session, select

from .engine import current_pipeline, get_engine
from .models import UsageEvent

log = logging.getLogger(__name__)


_current_video: contextvars.ContextVar[str | None] = contextvars.ContextVar(
    "current_video", default=None,
)


def set_current_video(slug: str | None) -> None:
    """Set the active video slug so subsequent record() calls tag their events."""
    _current_video.set(slug)


def current_video() -> str | None:
    return _current_video.get()


_PRICES_PATH = Path(__file__).resolve().parent / "prices.yaml"


@lru_cache(maxsize=1)
def prices() -> dict[str, Any]:
    if not _PRICES_PATH.exists():
        return {}
    return yaml.safe_load(_PRICES_PATH.read_text(encoding="utf-8")) or {}


def cost_for_event(*, provider: str, operation: str, model: str | None,
                   units_in: int, units_out: int, units: int) -> float:
    p = prices()
    if provider == "anthropic":
        m = p.get("anthropic", {}).get(model or "")
        if not m:
            return 0.0
        return units_in * m["input"] / 1_000_000 + units_out * m["output"] / 1_000_000
    if provider == "elevenlabs":
        return units * p.get("elevenlabs", {}).get("per_character", 0.0)
    if provider == "serper":
        return units * p.get("serper", {}).get("per_query", 0.0)
    if provider == "google_cse":
        return units * p.get("google_cse", {}).get("per_query", 0.0)
    if provider == "pexels":
        return units * p.get("pexels", {}).get("per_query", 0.0)
    if provider == "wikimedia":
        return 0.0
    if provider == "edge_tts":
        return 0.0
    if provider == "youtube_data_v3":
        return 0.0
    return 0.0


def record(
    provider: str,
    operation: str,
    *,
    units_in: int = 0,
    units_out: int = 0,
    units: int = 0,
    model: str | None = None,
    video_slug: str | None = None,
    pipeline: str | None = None,
    success: bool = True,
    note: str | None = None,
) -> UsageEvent | None:
    """Persist a UsageEvent. Computes cost_usd from the price table.

    `pipeline` resolves from arg → context var. If no pipeline is set, the call
    is dropped with a warning (so unrelated module imports don't crash).
    """
    slug = video_slug or current_video()
    cost = cost_for_event(
        provider=provider, operation=operation, model=model,
        units_in=units_in, units_out=units_out, units=units,
    )
    ev = UsageEvent(
        timestamp=datetime.utcnow(),
        provider=provider, operation=operation, model=model,
        units_in=units_in, units_out=units_out, units=units,
        cost_usd=cost, video_slug=slug, success=success, note=note,
    )
    p = pipeline or current_pipeline()
    if not p:
        log.warning("usage.record dropped — no pipeline set: %s %s", provider, operation)
        return None
    try:
        with Session(get_engine(p)) as session:
            session.add(ev)
            session.commit()
            session.refresh(ev)
    except Exception as e:
        log.warning("usage.record failed for pipeline=%s: %s", p, e)
    return ev


# ─────────────────────────────────────────────────────────────────────────────
# Rollups
# ─────────────────────────────────────────────────────────────────────────────

def spend_by_provider(*, pipeline: str, since: datetime | None = None) -> dict[str, dict]:
    with Session(get_engine(pipeline)) as session:
        stmt = select(UsageEvent)
        if since:
            stmt = stmt.where(UsageEvent.timestamp >= since)
        events = session.exec(stmt).all()
    out: dict[str, dict] = {}
    for e in events:
        b = out.setdefault(e.provider, {"cost_usd": 0.0, "events": 0, "units": 0,
                                        "units_in": 0, "units_out": 0})
        b["cost_usd"] += e.cost_usd
        b["events"] += 1
        b["units"] += e.units
        b["units_in"] += e.units_in
        b["units_out"] += e.units_out
    return out


def spend_by_video(*, pipeline: str, since: datetime | None = None) -> dict[str | None, dict]:
    with Session(get_engine(pipeline)) as session:
        stmt = select(UsageEvent)
        if since:
            stmt = stmt.where(UsageEvent.timestamp >= since)
        events = session.exec(stmt).all()
    out: dict[str | None, dict] = {}
    for e in events:
        b = out.setdefault(e.video_slug, {"cost_usd": 0.0, "by_provider": {}, "events": 0})
        b["cost_usd"] += e.cost_usd
        b["events"] += 1
        b["by_provider"].setdefault(e.provider, 0.0)
        b["by_provider"][e.provider] += e.cost_usd
    return out


def rollup(pipeline: str | None = None, days: int = 30, console: Any = None) -> None:
    """CLI-facing pretty print. If pipeline is None, rolls up both."""
    pipelines = [pipeline] if pipeline else ["brawl", "stocks"]
    since = datetime.utcnow() - timedelta(days=days)

    def _out(s: str) -> None:
        if console is not None:
            console.print(s)
        else:
            print(s)

    grand_total = 0.0
    for p in pipelines:
        try:
            by_provider = spend_by_provider(pipeline=p, since=since)
        except Exception as e:
            _out(f"[dim]{p}: no usage data ({e})[/dim]")
            continue
        if not by_provider:
            _out(f"[dim]{p}: no events in last {days}d[/dim]")
            continue
        _out(f"\n[bold]{p}[/bold] — last {days}d")
        for provider, stats in sorted(by_provider.items(), key=lambda x: -x[1]['cost_usd']):
            _out(
                f"  {provider:<20} ${stats['cost_usd']:>8.4f}   "
                f"{stats['events']:>4} events"
            )
            grand_total += stats['cost_usd']
    _out(f"\n[bold]Total[/bold]  ${grand_total:.4f}")
