"""Analytics endpoints — Scrape Graph (added/removed/active per day) and KPIs."""
from datetime import date, datetime, timedelta
from typing import Optional

import sqlite_utils
from fastapi import APIRouter, Depends, Query

from scanner.api.deps import disabled_sources_clause, get_database
from scanner.api.schemas import ScrapeGraphPoint

router = APIRouter(prefix="/api/analytics", tags=["analytics"])


@router.get("/scrape-graph", response_model=list[ScrapeGraphPoint])
def scrape_graph(
    days: int = Query(30, ge=1, le=365),
    city: Optional[str] = None,
    db: sqlite_utils.Database = Depends(get_database),
):
    """Daily series of {added, removed, active} for the last `days` days.

    - `added`: listings whose `first_seen::date == d`
    - `removed`: rows in `listings_history` with `deactivated_at::date == d`
    - `active`: total active listings at end of day d
    """
    end = date.today()
    start = end - timedelta(days=days - 1)

    city_clause = ""
    city_param: list = []
    if city:
        city_clause = " AND city = ?"
        city_param = [city]

    added_rows = db.execute(
        f"SELECT substr(first_seen, 1, 10) AS d, COUNT(*) "
        f"FROM listings WHERE first_seen >= ?{city_clause}{disabled_sources_clause()} "
        f"GROUP BY d",
        [start.isoformat(), *city_param],
    ).fetchall()
    added = {r[0]: r[1] for r in added_rows if r[0]}

    removed_rows = db.execute(
        f"SELECT substr(deactivated_at, 1, 10) AS d, COUNT(*) "
        f"FROM listings_history WHERE deactivated_at >= ?{city_clause} "
        f"GROUP BY d",
        [start.isoformat(), *city_param],
    ).fetchall()
    removed = {r[0]: r[1] for r in removed_rows if r[0]}

    # Total active right now (computed once; per-day reconstruction is expensive
    # and noisy, so we use end-of-window snapshot + cumulative net adjustment).
    active_now_row = db.execute(
        f"SELECT COUNT(*) FROM listings WHERE is_active = 1{city_clause}{disabled_sources_clause()}",
        city_param,
    ).fetchone()
    active_now = active_now_row[0] if active_now_row else 0

    out: list[ScrapeGraphPoint] = []
    cumulative_net_after_d = 0
    days_desc = [start + timedelta(days=i) for i in range(days)]
    days_desc.sort(reverse=True)
    snapshot = active_now
    per_day: dict[str, ScrapeGraphPoint] = {}
    for d in days_desc:
        ds = d.isoformat()
        a = added.get(ds, 0)
        r = removed.get(ds, 0)
        per_day[ds] = ScrapeGraphPoint(date=ds, added=a, removed=r, active=snapshot)
        snapshot = snapshot - a + r  # walk backwards in time

    for d in sorted(per_day.keys()):
        out.append(per_day[d])
    return out


@router.get("/kpis")
def kpis(
    db: sqlite_utils.Database = Depends(get_database),
):
    """Lightweight summary numbers for the dashboard header."""
    active = db.execute(
        f"SELECT COUNT(*) FROM listings WHERE is_active = 1{disabled_sources_clause()}"
    ).fetchone()[0]
    today = date.today().isoformat()
    yesterday = (date.today() - timedelta(days=1)).isoformat()
    added_today = db.execute(
        f"SELECT COUNT(*) FROM listings WHERE substr(first_seen,1,10) = ?{disabled_sources_clause()}",
        [today],
    ).fetchone()[0]
    removed_today = db.execute(
        "SELECT COUNT(*) FROM listings_history WHERE substr(deactivated_at,1,10) = ?", [today]
    ).fetchone()[0]
    last_run = db.execute(
        "SELECT MAX(ended_at) FROM run_history WHERE status = 'success'"
    ).fetchone()[0]
    return {
        "active_listings": active,
        "added_today": added_today,
        "removed_today": removed_today,
        "last_successful_run": last_run,
    }
