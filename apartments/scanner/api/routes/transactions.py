"""Transactions + percentile endpoints."""
import re
from typing import Optional

import sqlite_utils
from fastapi import APIRouter, Depends, HTTPException, Query

from scanner.api.deps import disabled_transactions_clause, get_database
from scanner.api.schemas import PercentileResponse, PercentileScope, Transaction
from scanner.services.percentile import (
    compute_dual_percentile,
    load_city_transactions,
)

router = APIRouter(prefix="/api/transactions", tags=["transactions"])

_ADDRESS_RE = re.compile(r"^\s*(?P<street>[^\d,]+?)\s+(?P<num>\d+)")


def _row_to_dict(cursor, row) -> dict:
    return {col[0]: row[i] for i, col in enumerate(cursor.description)}


@router.get("", response_model=list[Transaction])
def list_transactions(
    city: Optional[str] = None,
    rooms: Optional[float] = None,
    limit: int = Query(500, le=5000),
    db: sqlite_utils.Database = Depends(get_database),
):
    where: list[str] = []
    params: list = []
    if city:
        where.append("city = ?")
        params.append(city)
    if rooms is not None:
        where.append("rooms = ?")
        params.append(rooms)
    where_sql = " AND ".join(where) if where else "1=1"
    sql = (
        f"SELECT * FROM transactions WHERE {where_sql}{disabled_transactions_clause()} "
        "ORDER BY date DESC LIMIT ?"
    )
    params.append(limit)
    cursor = db.execute(sql, params)
    return [_row_to_dict(cursor, r) for r in cursor.fetchall()]


@router.get("/percentile/{listing_id}", response_model=PercentileResponse)
def percentile_for_listing(
    listing_id: str,
    db: sqlite_utils.Database = Depends(get_database),
):
    """Dual-scope percentile for a listing.

    Returns:
      - `near` : street-level cohort percentile (building → street_block → street).
      - `area` : same-city, same-rooms-bucket cohort percentile (18 mo lookback).
      - `cohort_points`: lat/lon of the *near* cohort transactions, used by the
        frontend to draw a convex hull. Falls back to the area cohort when
        near is unavailable.
    Either scope may be None when there's not enough data.
    """
    cursor = db.execute(
        "SELECT id, address, city, rooms, price, sqm FROM listings WHERE id = ?",
        [listing_id],
    )
    row = cursor.fetchone()
    if not row:
        raise HTTPException(404, "listing not found")
    listing = _row_to_dict(cursor, row)
    address = listing.get("address") or ""
    city = listing.get("city") or ""
    rooms = listing.get("rooms")
    price = listing.get("price") or 0
    sqm = listing.get("sqm") or 0

    # Address parse failure is OK — only the near (street-level) scope needs
    # it. The area (rooms-cohort) scope can still compute, so let the call
    # through with empty street/number and let compute_dual_percentile decide
    # which scopes are reachable.
    m = _ADDRESS_RE.match(address)
    street = m.group("street") if m else ""
    house_num = m.group("num") if m else None

    df = load_city_transactions(db, city, lookback_days=365 * 5)
    dp = compute_dual_percentile(
        df, db,
        city=city, rooms=rooms,
        street=street, house_number=house_num,
        price=price, sqm=sqm or None,
    )
    if dp.near is None and dp.area is None:
        raise HTTPException(404, "insufficient data to compute percentile")

    # Cohort points for the near scope when present, else for the area cohort
    # (so the convex hull on the map still has something to draw).
    if dp.near is not None:
        cohort_points = _cohort_points(db, city, street, house_num, dp.near.scope)
    else:
        cohort_points = []  # area cohort spans the whole city — hull would be useless

    def _to_scope(r) -> PercentileScope | None:
        if r is None:
            return None
        return PercentileScope(
            percentile=r.percentile,
            n_sales=r.n_sales,
            median_price=r.median_price,
            p25=r.p25,
            p75=r.p75,
            scope=r.scope,
            label=r.label,
        )

    return PercentileResponse(
        near=_to_scope(dp.near),
        area=_to_scope(dp.area),
        cohort_points=cohort_points,
    )


def _cohort_points(
    db: sqlite_utils.Database, city: str, street: str, house_num: str, scope: str,
) -> list[tuple[float, float]]:
    """Return lat/lon of transactions matching the resolved cohort scope."""
    df = load_city_transactions(db, city, lookback_days=365 * 5)
    if df.empty:
        return []
    from scanner.services.percentile import _normalize_street
    street_n = _normalize_street(street)
    num = int(house_num) if str(house_num).isdigit() else None
    if scope == "building" and num is not None:
        cohort = df[(df["t_street"] == street_n) & (df["t_num"] == num)]
    elif scope == "street_block" and num is not None:
        cohort = df[(df["t_street"] == street_n) & ((df["t_num"] - num).abs() <= 5)]
    elif scope == "street":
        cohort = df[df["t_street"] == street_n]
    else:
        cohort = df

    addresses = cohort["address"].astype(str).tolist()
    if not addresses:
        return []
    placeholders = ",".join("?" * len(addresses))
    rows = db.execute(
        f"SELECT lat, lon FROM transactions "
        f"WHERE city = ? AND address IN ({placeholders}) "
        f"AND lat IS NOT NULL AND lon IS NOT NULL{disabled_transactions_clause()}",
        [city, *addresses],
    ).fetchall()
    return [(r[0], r[1]) for r in rows]
