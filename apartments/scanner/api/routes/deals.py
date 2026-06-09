"""Deals endpoint — listings sorted by motivation/gap with explanations."""
from typing import Optional

import sqlite_utils
from fastapi import APIRouter, Depends, Query

from scanner.api.deps import disabled_sources_clause, get_database
from scanner.api.schemas import DealCard, Listing, ListingScore

router = APIRouter(prefix="/api/deals", tags=["deals"])


def _row_to_dict(cursor, row) -> dict:
    return {col[0]: row[i] for i, col in enumerate(cursor.description)}


@router.get("", response_model=list[DealCard])
def get_deals(
    sort: str = Query("gap", pattern="^(gap|motivation|value_add)$"),
    min_motivation: Optional[float] = None,
    max_gap_percent: Optional[float] = None,
    city: Optional[str] = None,
    limit: int = Query(50, le=500),
    db: sqlite_utils.Database = Depends(get_database),
):
    """Return top listings ranked by `sort` key with a one-line explanation.

    Ranking:
      - gap        → most-undermarket first (gap_percent ascending, negative = cheap)
      - motivation → highest motivation score first
      - value_add  → highest absolute ₪ below market first
    """
    sort_clause = {
        "gap": "s.gap_percent ASC",
        "motivation": "s.motivation_score DESC",
        "value_add": "s.value_add_gap DESC",
    }[sort]

    where = ["l.is_active = 1", "s.listing_id IS NOT NULL"]
    params: list = []
    if city:
        where.append("l.city = ?")
        params.append(city)
    if min_motivation is not None:
        where.append("s.motivation_score >= ?")
        params.append(min_motivation)
    if max_gap_percent is not None:
        where.append("s.gap_percent <= ?")
        params.append(max_gap_percent)
    where_sql = " AND ".join(where)

    sql = (
        "SELECT l.*, s.gap_percent, s.nadlan_median_ppsqm, s.percentile_rank, "
        "       s.z_score, s.motivation_score, s.value_add_gap, "
        "       s.days_on_market, s.n_cohort_sales "
        "FROM listings l "
        "INNER JOIN listing_scores s ON s.listing_id = l.id "
        f"WHERE {where_sql}{disabled_sources_clause('l')} "
        f"ORDER BY {sort_clause} "
        "LIMIT ?"
    )
    params.append(limit)
    cursor = db.execute(sql, params)
    rows = [_row_to_dict(cursor, r) for r in cursor.fetchall()]

    cards: list[DealCard] = []
    for r in rows:
        score = ListingScore(
            listing_id=r["id"],
            gap_percent=r.get("gap_percent"),
            nadlan_median_ppsqm=r.get("nadlan_median_ppsqm"),
            percentile_rank=r.get("percentile_rank"),
            z_score=r.get("z_score"),
            motivation_score=r.get("motivation_score"),
            value_add_gap=r.get("value_add_gap"),
            days_on_market=r.get("days_on_market"),
            n_cohort_sales=r.get("n_cohort_sales"),
        )
        listing = Listing(**{k: r.get(k) for k in Listing.model_fields})
        cards.append(DealCard(
            listing=listing,
            score=score,
            explanation=_explain(score),
        ))
    return cards


def _explain(score: ListingScore) -> str:
    parts = []
    if score.gap_percent is not None and score.gap_percent <= -10:
        parts.append(f"{abs(score.gap_percent):.0f}% below market")
    if score.value_add_gap and score.value_add_gap > 0:
        parts.append(f"₪{int(score.value_add_gap):,} below median price")
    if score.motivation_score and score.motivation_score >= 60:
        parts.append(f"motivation {int(score.motivation_score)}/100")
    if score.days_on_market and score.days_on_market >= 30:
        parts.append(f"{score.days_on_market} days on market")
    return " · ".join(parts) or "scored deal"
