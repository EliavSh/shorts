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
    """Today's candidate names, blending price action with news relevance.

    Each top-mover carries a `news_score` from how often it was mentioned in the
    market news today; additionally, the most-talked-about tickers that aren't in
    our static universe at all are pulled in (with a real quote) so a genuinely
    news-hot story can become the clip even if it isn't a big % mover.
    """
    try:
        from ..data.market import get_quote, top_movers
    except Exception as e:
        log.warning("market import failed, planning without movers: %s", e)
        return []

    try:
        from ..data.trending import trending_tickers
        trending = trending_tickers()
    except Exception as e:
        log.debug("trending_tickers failed: %s", e)
        trending = {}

    movers: list[MoverLite] = []
    seen: set[str] = set()
    try:
        for q in top_movers(n=n):
            sym = q.ticker.upper()
            seen.add(sym)
            movers.append(MoverLite(ticker=q.ticker, sector=q.sector,
                                    change_pct=q.change_pct,
                                    news_score=float(trending.get(sym, 0))))
    except Exception as e:
        log.warning("top_movers failed, planning from news only: %s", e)

    # Pull in the hottest news names outside our universe (bounded yfinance cost).
    extras = [t for t in trending if t.upper() not in seen][:4]
    for sym in extras:
        q = get_quote(sym)
        if q is not None:
            movers.append(MoverLite(ticker=q.ticker, sector=q.sector,
                                    change_pct=q.change_pct,
                                    news_score=float(trending.get(sym.upper(), 0))))
    return movers


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


def _generated_today(today: date) -> int:
    """Durable count of clips produced today: staged (review store, by
    `created_at`) + uploaded (published ledger, by `published_at`).

    Counting from produced artifacts rather than the plan means the daily
    ceiling holds even when the plan is regenerated mid-day (each slot replans
    for freshness) and after a clip is purged on upload.
    """
    iso = today.isoformat()
    n = 0
    try:
        from shorts.core.reviews import ReviewStore
        for it in ReviewStore("stocks").list_items():
            if (getattr(it, "created_at", "") or "")[:10] == iso:
                n += 1
    except Exception as e:
        log.debug("review-store day count failed: %s", e)
    try:
        from .published import load_published
        for e in load_published().entries:
            if (getattr(e, "published_at", "") or "")[:10] == iso:
                n += 1
    except Exception as e:
        log.debug("ledger day count failed: %s", e)
    return n


def _auto_publish(result, *, privacy: str) -> None:
    """Upload a freshly-rendered clip to YouTube. Best-effort: a failure leaves
    the clip staged (still publishable from the dashboard) and never propagates,
    so a publish hiccup can't crash the render tick."""
    try:
        from ..upload import upload as upload_clip
        upload_clip(result.slug, privacy=privacy)
        log.info("autopilot: auto-published %s (%s).", result.slug, privacy)
    except Exception as e:
        log.warning("autopilot: auto-publish of %s failed (left staged): %s",
                    getattr(result, "slug", "?"), e)


def tick(*, lang: str = "en", replan: bool = False, max_per_tick: int = 1):
    """Render up to `max_per_tick` due clip(s) now, never exceeding the day's
    `daily_target` ceiling, and (when `auto_publish` is on) publish each.

    Built for several scheduled runs per day (e.g. morning / noon / evening):
    each run renders ONE fresh clip. Pass `replan=True` (the cron default) to
    rebuild the plan from the latest movers + earnings first, so each slot
    reflects the current market. The daily ceiling is counted durably from
    produced clips, so it holds across replans and post-upload purges.
    """
    today = date.today()
    cfg = store.load_config()
    daily_cap = cfg.daily_target
    if replan:
        regenerate_plan(today=today)
    results = []
    while len(results) < max_per_tick and _generated_today(today) < daily_cap:
        result = _render_one(lang=lang, replan_if_empty=True)
        if result is None:
            break
        results.append(result)
        if cfg.auto_publish:
            _auto_publish(result, privacy=cfg.publish_privacy)
    if not results:
        log.info("autopilot tick: nothing rendered (cap=%d, done_today=%d).",
                 daily_cap, _generated_today(today))
    return results
