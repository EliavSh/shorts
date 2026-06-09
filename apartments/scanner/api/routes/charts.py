"""Chart-data endpoints: per-listing price history, building history, city stats, velocity."""
from datetime import date, datetime, timedelta
from typing import Optional

import sqlite_utils
from fastapi import APIRouter, Depends, HTTPException, Query

from scanner.api.deps import disabled_sources_clause, disabled_transactions_clause, get_database

router = APIRouter(prefix="/api/charts", tags=["charts"])


def _row(cursor, row) -> dict:
    return {col[0]: row[i] for i, col in enumerate(cursor.description)}


@router.get("/price-history/{listing_id}")
def price_history(
    listing_id: str,
    db: sqlite_utils.Database = Depends(get_database),
):
    """Price events for a single listing (for the per-listing motivation chart)."""
    cursor = db.execute(
        "SELECT event_type, price, date FROM listing_price_history "
        "WHERE listing_id = ? ORDER BY date ASC",
        [listing_id],
    )
    events = [_row(cursor, r) for r in cursor.fetchall()]
    listing_row = db.execute(
        "SELECT price, first_seen FROM listings WHERE id = ?", [listing_id]
    ).fetchone()
    if listing_row:
        # Ensure the latest current price appears as an "asking" event.
        events.append({
            "event_type": "asking",
            "price": listing_row[0],
            "date": (listing_row[1] or datetime.now().isoformat())[:10],
        })
    return events


@router.get("/building-history")
def building_history(
    street: str,
    number: int,
    city: str,
    radius: int = Query(5, ge=0, le=50),
    db: sqlite_utils.Database = Depends(get_database),
):
    """Transaction history within ±`radius` house numbers on the same street."""
    rows = db.execute(
        "SELECT address, price, sqm, rooms, date FROM transactions "
        f"WHERE city = ? AND price > 0 AND sqm > 0{disabled_transactions_clause()} "
        "  AND date >= date('now', '-5 years') "
        "ORDER BY date DESC",
        [city],
    ).fetchall()
    import re
    out = []
    for addr, price, sqm, rooms, date_s in rows:
        m = re.match(r"^\s*([^\d,]+?)\s+(\d+)", addr or "")
        if not m:
            continue
        st = m.group(1).strip()
        try:
            num = int(m.group(2))
        except ValueError:
            continue
        if street.strip() not in st and st not in street.strip():
            continue
        if abs(num - number) > radius:
            continue
        out.append({
            "address": addr,
            "price": price,
            "sqm": sqm,
            "ppsqm": round(price / sqm) if sqm > 0 else None,
            "rooms": rooms,
            "date": date_s,
        })
    return out


@router.get("/city-stats")
def city_stats(db: sqlite_utils.Database = Depends(get_database)):
    """Per-city: count, avg price, avg ₪/m², avg rooms — for the bar charts."""
    rows = db.execute(
        "SELECT city, COUNT(*) as n, "
        "       AVG(price) as avg_price, "
        "       AVG(price_per_sqm) as avg_ppsqm, "
        "       AVG(rooms) as avg_rooms "
        f"FROM listings WHERE is_active = 1 AND city IS NOT NULL{disabled_sources_clause()} "
        "GROUP BY city HAVING n >= 5 ORDER BY n DESC LIMIT 30"
    ).fetchall()
    return [
        {
            "city": r[0],
            "count": r[1],
            "avg_price": int(r[2]) if r[2] else None,
            "avg_ppsqm": int(r[3]) if r[3] else None,
            "avg_rooms": round(r[4], 1) if r[4] else None,
        }
        for r in rows
    ]


@router.get("/velocity")
def velocity(
    days: int = Query(7, ge=1, le=90),
    near_lat: Optional[float] = None,
    near_lon: Optional[float] = None,
    near_radius_m: float = Query(15_000, ge=500, le=100_000),
    db: sqlite_utils.Database = Depends(get_database),
):
    """Listing density bucketed by ~500 m grid cells over the last `days`.

    Returns hex-like cells (we approximate H3 with a square grid for
    simplicity — same purpose: see where activity concentrates).
    Each cell carries `count` (active in window), `delta` (vs prior window
    of the same length).
    """
    grid = 0.005  # ~500 m at Israeli latitudes
    bbox_clause = ""
    bbox_params: list = []
    if near_lat is not None and near_lon is not None:
        import math
        dlat = near_radius_m / 111_000
        dlon = near_radius_m / (111_000 * max(0.1, math.cos(math.radians(near_lat))))
        bbox_clause = (
            " AND lat BETWEEN ? AND ? AND lon BETWEEN ? AND ?"
        )
        bbox_params = [near_lat - dlat, near_lat + dlat, near_lon - dlon, near_lon + dlon]

    cutoff_now = (date.today() - timedelta(days=days)).isoformat()
    cutoff_prev = (date.today() - timedelta(days=days * 2)).isoformat()

    def _cells(cutoff_low: str, cutoff_high: Optional[str]):
        sql = (
            "SELECT lat, lon FROM listings "
            f"WHERE is_active = 1 AND lat IS NOT NULL AND lon IS NOT NULL{disabled_sources_clause()} "
            "  AND first_seen >= ?"
        )
        params: list = [cutoff_low]
        if cutoff_high:
            sql += " AND first_seen < ?"
            params.append(cutoff_high)
        sql += bbox_clause
        params += bbox_params
        agg: dict[tuple[int, int], int] = {}
        for lat, lon in db.execute(sql, params).fetchall():
            key = (round(lat / grid), round(lon / grid))
            agg[key] = agg.get(key, 0) + 1
        return agg

    now_cells = _cells(cutoff_now, None)
    prev_cells = _cells(cutoff_prev, cutoff_now)

    keys = set(now_cells) | set(prev_cells)
    out = []
    for k in keys:
        lat = (k[0] + 0.5) * grid
        lon = (k[1] + 0.5) * grid
        cur = now_cells.get(k, 0)
        prev = prev_cells.get(k, 0)
        out.append({
            "lat": lat, "lon": lon,
            "count": cur,
            "delta": cur - prev,
            "size_deg": grid,
        })
    return out
