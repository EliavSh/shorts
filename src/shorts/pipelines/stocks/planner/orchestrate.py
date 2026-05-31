"""High-level orchestration — gather live inputs, build a plan, and run the
auto-pilot tick. Thin glue over planner.build_plan + store + pipeline.
"""
from __future__ import annotations

import logging
from datetime import date

from . import store
from .models import Plan, PlannedVideo
from .planner import EarningsLite, MoverLite, build_plan

log = logging.getLogger(__name__)


def _recent_renders(limit: int = 12) -> tuple[tuple[str, ...], tuple[str, ...]]:
    """Pull recently-used formats + tickers from the review store for freshness.

    Reads each render's manifest (written by the composer) when present; falls
    back to the item title otherwise. Best-effort — returns ((), ()) on any issue.
    """
    formats_seen: list[str] = []
    tickers_seen: list[str] = []
    try:
        import json

        from shorts.core.reviews import ReviewStore

        rs = ReviewStore("stocks")
        for item in rs.list_items()[:limit]:
            manifest = rs.output_root / item.run_id / "short.manifest.json"
            if manifest.exists():
                m = json.loads(manifest.read_text(encoding="utf-8"))
                if m.get("format"):
                    formats_seen.append(m["format"])
                tickers_seen.extend(t.get("ticker", "") for t in m.get("tickers", []))
    except Exception as e:
        log.debug("recent_renders lookup failed: %s", e)
    return tuple(f for f in formats_seen if f), tuple(t for t in tickers_seen if t)


def _live_movers(n: int = 12) -> list[MoverLite]:
    try:
        from ..data.market import top_movers
        return [MoverLite(ticker=q.ticker, sector=q.sector, change_pct=q.change_pct)
                for q in top_movers(n=n)]
    except Exception as e:
        log.warning("top_movers failed, planning without movers: %s", e)
        return []


def _live_earnings(days: int = 7) -> list[EarningsLite]:
    try:
        from ..data.earnings import upcoming_earnings
        return [EarningsLite(ticker=e.ticker, report_date=e.report_date)
                for e in upcoming_earnings(days=days)]
    except Exception as e:
        log.warning("upcoming_earnings failed, planning without calendar: %s", e)
        return []


def regenerate_plan(*, today: date | None = None) -> Plan:
    """Gather live inputs, build a fresh plan, persist it, and return it.

    Pinned items from the existing plan are preserved (the user explicitly
    parked them); everything else is replaced.
    """
    cfg = store.load_config()
    debt = store.load_debt()
    recent_formats, recent_tickers = _recent_renders()

    pinned = [it for it in store.load_plan().items if it.pinned and it.status != "rendered"]

    plan = build_plan(
        config=cfg,
        commitments=debt.open(),
        earnings=_live_earnings(),
        movers=_live_movers(),
        recent_formats=recent_formats,
        recent_tickers=recent_tickers,
        today=today,
    )
    if pinned:
        plan.items = pinned + [it for it in plan.items][: max(0, cfg.daily_target - len(pinned))]
    store.save_plan(plan)
    log.info("Plan regenerated: %d items.", len(plan.items))
    return plan


def next_due_item(plan: Plan | None = None, *, today: date | None = None) -> PlannedVideo | None:
    """The earliest still-`planned` item whose date has arrived (pins first)."""
    plan = plan if plan is not None else store.load_plan()
    today = today or date.today()
    candidates = [it for it in plan.items if it.status == "planned" and it.scheduled_for <= today]
    if not candidates:
        # Nothing due yet — fall back to the soonest planned item.
        candidates = [it for it in plan.items if it.status == "planned"]
    if not candidates:
        return None
    candidates.sort(key=lambda it: (not it.pinned, it.scheduled_for))
    return candidates[0]


def _render_one(*, lang: str, replan_if_empty: bool):
    """Render the single next-due planned item. Returns its RunResult or None."""
    plan = store.load_plan()
    if replan_if_empty and not any(it.status == "planned" for it in plan.items):
        plan = regenerate_plan()

    item = next_due_item(plan)
    if item is None:
        return None

    # Mark rendering so a concurrent tick won't double-render.
    item.status = "rendering"
    for it in plan.items:
        if it.id == item.id:
            it.status = "rendering"
    store.save_plan(plan)

    from ..pipeline import render_planned_item
    return render_planned_item(item, lang=lang)


def _rendered_today(today: date) -> int:
    plan = store.load_plan()
    return sum(1 for it in plan.items if it.status == "rendered" and it.scheduled_for == today)


def tick(*, lang: str = "en", replan_if_empty: bool = True, max_items: int | None = None):
    """Render today's batch of planned items, up to the daily target.

    A single daily cron run produces the whole day's clips. Stops when the
    daily target is reached or nothing is due. Returns the list of RunResults.
    """
    today = date.today()
    cap = max_items if max_items is not None else store.load_config().daily_target
    results = []
    while _rendered_today(today) < cap:
        result = _render_one(lang=lang, replan_if_empty=replan_if_empty)
        if result is None:
            break
        results.append(result)
    if not results:
        log.info("autopilot tick: nothing due.")
    return results
