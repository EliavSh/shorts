"""Listings endpoints — bypass for the existing dashboard listings query."""
from typing import Optional

import sqlite_utils
from fastapi import APIRouter, Depends, HTTPException, Query

from scanner.api.deps import disabled_sources_clause, get_database
from scanner.api.schemas import Listing, ListingScore, ListingWithScore

router = APIRouter(prefix="/api/listings", tags=["listings"])


def _row_to_dict(cursor, row) -> dict:
    return {col[0]: row[i] for i, col in enumerate(cursor.description)}


@router.get("", response_model=list[ListingWithScore])
def list_listings(
    deal_type: str = Query("sale", pattern="^(sale|rent)$"),
    city: Optional[str] = None,
    neighborhood: Optional[str] = None,
    min_rooms: Optional[float] = None,
    max_rooms: Optional[float] = None,
    min_price: Optional[int] = None,
    max_price: Optional[int] = None,
    # Total monthly cost = price + house-committee + arnona (rent mode budget).
    min_total: Optional[int] = None,
    max_total: Optional[int] = None,
    only_active: bool = True,
    include_new_construction: bool = True,
    only_new_construction: bool = False,
    restrict_to_zones: bool = False,
    near_lat: Optional[float] = None,
    near_lon: Optional[float] = None,
    near_radius_m: float = Query(2000, ge=100, le=50_000),
    limit: int = Query(2000, le=10_000),
    db: sqlite_utils.Database = Depends(get_database),
):
    """Filtered listing fetch joined with score row.

    When ``near_lat``/``near_lon`` are supplied (travel mode), results are
    spatially filtered with a fast lat/lon bounding-box pre-filter and ordered
    by approximate distance. Otherwise sorted by ``last_seen DESC``.
    """
    where = []
    params: list = []
    # Sale vs rent are separate modes over the same table. Rows predating rentals
    # are all 'sale'; treat NULL as 'sale' so legacy data stays visible.
    if deal_type == "rent":
        where.append("l.deal_type = 'rent'")
    else:
        where.append("(l.deal_type = 'sale' OR l.deal_type IS NULL)")
    if only_active:
        where.append("l.is_active = 1")
    if city:
        where.append("l.city = ?")
        params.append(city)
    if neighborhood:
        where.append("l.neighborhood = ?")
        params.append(neighborhood)
    if not include_new_construction:
        where.append("(l.is_new_construction IS NULL OR l.is_new_construction = 0)")
    if only_new_construction:
        where.append("l.is_new_construction = 1")
    if min_rooms is not None:
        where.append("l.rooms >= ?")
        params.append(min_rooms)
    if max_rooms is not None:
        where.append("l.rooms <= ?")
        params.append(max_rooms)
    if min_price is not None:
        where.append("l.price >= ?")
        params.append(min_price)
    if max_price is not None:
        where.append("l.price <= ?")
        params.append(max_price)
    # Total monthly cost, matching yad2's own formula: rent + house-committee +
    # arnona/2 (arnona is billed bi-monthly). NULLs treated as 0.
    _total_sql = "(l.price + COALESCE(l.vaad_bayit, 0) + COALESCE(l.arnona, 0) / 2)"
    if min_total is not None:
        where.append(f"{_total_sql} >= ?")
        params.append(min_total)
    if max_total is not None:
        where.append(f"{_total_sql} <= ?")
        params.append(max_total)

    order_sql = "ORDER BY l.last_seen DESC"
    if near_lat is not None and near_lon is not None:
        # 1° latitude ≈ 111 km; 1° longitude ≈ 111 km * cos(lat).
        # We bound the search by a square slightly larger than the radius.
        import math
        dlat = near_radius_m / 111_000
        dlon = near_radius_m / (111_000 * max(0.1, math.cos(math.radians(near_lat))))
        where += [
            "l.lat IS NOT NULL", "l.lon IS NOT NULL",
            "l.lat BETWEEN ? AND ?", "l.lon BETWEEN ? AND ?",
        ]
        params += [
            near_lat - dlat, near_lat + dlat,
            near_lon - dlon, near_lon + dlon,
        ]
        # Order by squared planar distance (good enough for sorting at <50km).
        order_sql = (
            f"ORDER BY ((l.lat-{near_lat})*(l.lat-{near_lat}) + "
            f"(l.lon-{near_lon})*(l.lon-{near_lon})) ASC"
        )

    where_sql = " AND ".join(where) if where else "1=1"
    # restrict_to_zones: filter by ~80 m bbox proximity to any pinui_binui_zone centroid.
    zones_join = ""
    if restrict_to_zones:
        zones_join = (
            " AND EXISTS (SELECT 1 FROM pinui_binui_zones z "
            "             WHERE z.lat IS NOT NULL AND z.lon IS NOT NULL "
            "               AND ABS(z.lat - l.lat) < 0.0007 "
            "               AND ABS(z.lon - l.lon) < 0.0007)"
        )

    sql = (
        "SELECT l.*, s.gap_percent, s.nadlan_median_ppsqm, s.percentile_rank, "
        "       s.z_score, s.motivation_score, s.value_add_gap, "
        "       s.days_on_market, s.n_cohort_sales "
        "FROM listings l "
        "LEFT JOIN listing_scores s ON s.listing_id = l.id "
        f"WHERE {where_sql}{disabled_sources_clause('l')}{zones_join} "
        f"{order_sql} "
        "LIMIT ?"
    )
    params.append(limit)

    cursor = db.execute(sql, params)
    rows = [_row_to_dict(cursor, r) for r in cursor.fetchall()]

    out: list[ListingWithScore] = []
    for r in rows:
        score_dict = {
            "listing_id": r["id"],
            "gap_percent": r.get("gap_percent"),
            "nadlan_median_ppsqm": r.get("nadlan_median_ppsqm"),
            "percentile_rank": r.get("percentile_rank"),
            "z_score": r.get("z_score"),
            "motivation_score": r.get("motivation_score"),
            "value_add_gap": r.get("value_add_gap"),
            "days_on_market": r.get("days_on_market"),
            "n_cohort_sales": r.get("n_cohort_sales"),
        }
        has_score = any(v is not None for k, v in score_dict.items() if k != "listing_id")
        out.append(ListingWithScore(
            **{k: r.get(k) for k in Listing.model_fields},
            score=ListingScore(**score_dict) if has_score else None,
        ))
    return out


@router.get("/{listing_id}", response_model=ListingWithScore)
def get_listing(
    listing_id: str,
    db: sqlite_utils.Database = Depends(get_database),
):
    cursor = db.execute(
        "SELECT l.*, s.gap_percent, s.nadlan_median_ppsqm, s.percentile_rank, "
        "       s.z_score, s.motivation_score, s.value_add_gap, "
        "       s.days_on_market, s.n_cohort_sales "
        "FROM listings l "
        "LEFT JOIN listing_scores s ON s.listing_id = l.id "
        f"WHERE l.id = ?{disabled_sources_clause('l')}",
        [listing_id],
    )
    row = cursor.fetchone()
    if not row:
        raise HTTPException(404, "listing not found")
    r = _row_to_dict(cursor, row)
    score_dict = {
        "listing_id": r["id"],
        "gap_percent": r.get("gap_percent"),
        "nadlan_median_ppsqm": r.get("nadlan_median_ppsqm"),
        "percentile_rank": r.get("percentile_rank"),
        "z_score": r.get("z_score"),
        "motivation_score": r.get("motivation_score"),
        "value_add_gap": r.get("value_add_gap"),
        "days_on_market": r.get("days_on_market"),
        "n_cohort_sales": r.get("n_cohort_sales"),
    }
    has_score = any(v is not None for k, v in score_dict.items() if k != "listing_id")
    return ListingWithScore(
        **{k: r.get(k) for k in Listing.model_fields},
        score=ListingScore(**score_dict) if has_score else None,
    )
