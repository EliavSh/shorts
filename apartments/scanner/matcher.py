"""Match listings to transactions and compute price gaps."""
import logging
import re
from datetime import date, datetime
from typing import Optional

import sqlite_utils

from scanner.db import get_db, get_transaction_stats

logger = logging.getLogger(__name__)


def classify_listing_price(
    listing: dict,
    db,
    lookback_days: int = 365,
) -> dict:
    """Classify a listing as under/at/over market based on nadlan transactions.

    Args:
        listing: Listing dict with address, city, rooms, sqm, price
        db: sqlite_utils.Database instance
        lookback_days: Only consider transactions from the last N days

    Returns:
        Dict with keys:
            - status: "under_market", "at_market", "over_market"
            - nadlan_median_price_per_sqm: float or None
            - asking_price_per_sqm: float
            - gap_percent: float (negative = cheaper than market)
            - explanation: str
    """
    city = listing.get("city", "")
    rooms = listing.get("rooms")
    sqm = listing.get("sqm")
    price = listing.get("price", 0)

    if not sqm or sqm == 0:
        return {
            "status": "unknown",
            "nadlan_median_price_per_sqm": None,
            "asking_price_per_sqm": None,
            "gap_percent": None,
            "explanation": "No sqm data",
        }

    asking_price_per_sqm = price / sqm

    # Get nadlan transaction stats for comparison
    stats = get_transaction_stats(db, city, rooms=rooms, lookback_days=lookback_days)

    if not stats or stats.get("count", 0) == 0:
        return {
            "status": "unknown",
            "nadlan_median_price_per_sqm": None,
            "asking_price_per_sqm": asking_price_per_sqm,
            "gap_percent": None,
            "explanation": f"No nadlan transactions for {city} with {rooms} rooms",
        }

    nadlan_median_price_per_sqm = stats.get("median_price_per_sqm")
    if not nadlan_median_price_per_sqm:
        return {
            "status": "unknown",
            "nadlan_median_price_per_sqm": None,
            "asking_price_per_sqm": asking_price_per_sqm,
            "gap_percent": None,
            "explanation": "Could not compute nadlan median",
        }

    # Compute gap
    gap_percent = (
        (asking_price_per_sqm - nadlan_median_price_per_sqm)
        / nadlan_median_price_per_sqm
        * 100
    )

    # Classify
    if gap_percent < -10:
        status = "under_market"
        explanation = f"Asking {abs(gap_percent):.1f}% below market"
    elif gap_percent > 10:
        status = "over_market"
        explanation = f"Asking {gap_percent:.1f}% above market"
    else:
        status = "at_market"
        explanation = f"Asking within 10% of market"

    return {
        "status": status,
        "nadlan_median_price_per_sqm": nadlan_median_price_per_sqm,
        "asking_price_per_sqm": asking_price_per_sqm,
        "gap_percent": gap_percent,
        "explanation": explanation,
    }


def run_scoring(db: sqlite_utils.Database) -> int:
    """Score all active listings and write results to listing_scores.

    Calls classify_listing_price() + compute_percentile_from_df() per listing.
    z_score / n_cohort_sales left NULL until Sprint 2 adds compute_zscore().
    Returns count of listings scored.
    """
    from scanner.services.percentile import load_city_transactions, compute_dual_percentile

    now = datetime.now().isoformat()
    today = date.today()

    listing_cols = [r[1] for r in db.execute("PRAGMA table_info(listings)").fetchall()]
    rows = db.execute("SELECT * FROM listings WHERE is_active = 1").fetchall()
    listings = [dict(zip(listing_cols, r)) for r in rows]

    if not listings:
        logger.info("run_scoring: no active listings")
        return 0

    from scanner.services.percentile import compute_zscore

    # Pre-load city transaction DataFrames (one query per city)
    city_dfs: dict[str, object] = {}
    for lst in listings:
        city = lst.get("city") or ""
        if city and city not in city_dfs:
            city_dfs[city] = load_city_transactions(db, city, lookback_days=365 * 5)

    # Preserve existing last_alerted_at so upsert doesn't wipe it
    existing_alerted = {
        row[0]: row[1]
        for row in db.execute(
            "SELECT listing_id, last_alerted_at FROM listing_scores"
        ).fetchall()
    }

    # Batch-load price reduction counts (Motivation Meter)
    reduction_counts: dict[str, int] = {
        row[0]: row[1]
        for row in db.execute(
            "SELECT listing_id, COUNT(*) FROM listing_price_history "
            "WHERE event_type IN ('price_change', 'priceDown') "
            "GROUP BY listing_id"
        ).fetchall()
    }

    def _motivation_score(dom, gap_pct, reductions) -> int:
        dom_score = min(40, (dom or 0) / 28 * 40)
        red_score = min(35, (reductions or 0) * 15)
        gap_score = 0.0
        if gap_pct is not None and gap_pct <= -10:
            gap_score = min(25, abs(gap_pct + 10) / 40 * 25)
        return round(min(100, dom_score + red_score + gap_score))

    scores = []
    for lst in listings:
        city = lst.get("city") or ""
        rooms = lst.get("rooms") or 0
        sqm = lst.get("sqm") or 0
        price = lst.get("price") or 0
        posted_at = lst.get("posted_at") or ""

        # Skip listings with implausible sqm — likely a scraping parse error.
        # Israeli residential apartments are almost always 30–300 sqm.
        # Also skip if price/sqm is below ₪5,000 (impossible in any Israeli city).
        if sqm < 30 or sqm > 300:
            continue
        if price > 0 and sqm > 0 and price / sqm < 5_000:
            continue

        try:
            dom = (today - date.fromisoformat(posted_at[:10])).days if posted_at else None
        except Exception:
            dom = None

        classification = classify_listing_price(lst, db)
        gap_percent = classification.get("gap_percent")
        nadlan_median_ppsqm = classification.get("nadlan_median_price_per_sqm")

        # Dual percentile (per the cohort redesign):
        #   - near = street-level cohort (no city fallback) → drives the map ring
        #   - area = same-city same-rooms-bucket → richer comparison context
        percentile_rank = None
        near_scope = None
        near_n_sales = None
        near_median_ppsqm = None
        area_percentile_rank = None
        area_n_sales = None
        area_median_ppsqm = None
        df = city_dfs.get(city)
        if df is not None and not df.empty and sqm > 0 and price > 0:
            address = lst.get("address") or ""
            m = re.match(r"^\s*(?P<street>[^\d,]+?)\s+(?P<num>\d+)", address)
            street = m.group("street") if m else address
            house_num = m.group("num") if m else None
            dp = compute_dual_percentile(
                df,
                db,
                city=city,
                rooms=rooms,
                street=street,
                house_number=house_num,
                price=price,
                sqm=sqm,
            )
            if dp.near is not None:
                percentile_rank = dp.near.percentile
                near_scope = dp.near.scope
                near_n_sales = dp.near.n_sales
                near_median_ppsqm = dp.near.median_price
            if dp.area is not None:
                area_percentile_rank = dp.area.percentile
                area_n_sales = dp.area.n_sales
                area_median_ppsqm = dp.area.median_price

        z_score = None
        n_cohort_sales = None
        if city and price > 0 and sqm > 0:
            zr = compute_zscore(db, city=city, rooms=rooms, price=price, sqm=sqm)
            if zr is not None:
                z_score, n_cohort_sales, _, _ = zr

        # Motivation Meter (0–100)
        reductions = reduction_counts.get(lst["id"], 0)
        motivation = _motivation_score(dom, gap_percent, reductions)

        # Value-Add Detector: absolute ₪ below market (positive = cheap)
        value_add_gap = None
        if nadlan_median_ppsqm and sqm > 0 and price > 0:
            value_add_gap = round((nadlan_median_ppsqm - price / sqm) * sqm)

        scores.append({
            "listing_id": lst["id"],
            "computed_at": now,
            "cohort_city": city,
            "cohort_rooms": round(rooms),
            "z_score": z_score,
            "gap_percent": gap_percent,
            "nadlan_median_ppsqm": nadlan_median_ppsqm,
            "percentile_rank": percentile_rank,         # = near percentile
            "n_cohort_sales": n_cohort_sales,
            "motivation_score": motivation,
            "value_add_gap": value_add_gap,
            "days_on_market": dom,
            "last_alerted_at": existing_alerted.get(lst["id"]),
            "near_scope": near_scope,
            "near_n_sales": near_n_sales,
            "near_median_ppsqm": near_median_ppsqm,
            "area_percentile_rank": area_percentile_rank,
            "area_n_sales": area_n_sales,
            "area_median_ppsqm": area_median_ppsqm,
        })

    if scores:
        db["listing_scores"].insert_all(scores, replace=True)
    logger.info("run_scoring: scored %d listings", len(scores))
    return len(scores)


def find_matching_listings(db, criteria: dict) -> list[dict]:
    """Find listings matching user criteria with price classification.

    Args:
        db: sqlite_utils.Database instance
        criteria: Dict with keys:
            - cities: list of city names
            - rooms: {"min": int, "max": int} or None
            - price: {"min": int, "max": int} or None
            - price_per_sqm: {"max": int} or None
            - under_market_threshold_percent: float (default 10)

    Returns:
        List of matching listings with price classification
    """
    cities = criteria.get("cities", [])
    rooms_range = criteria.get("rooms", {})
    price_range = criteria.get("price", {})
    price_per_sqm_max = criteria.get("price_per_sqm", {}).get("max")
    under_market_threshold = criteria.get("under_market_threshold_percent", 10)

    # Build where clause incrementally
    where_parts = ["is_active = 1"]
    where_args = []

    if cities:
        placeholders = ",".join("?" * len(cities))
        where_parts.append(f"city IN ({placeholders})")
        where_args.extend(cities)

    if rooms_range:
        min_rooms = rooms_range.get("min", 0)
        max_rooms = rooms_range.get("max", 10)
        where_parts.append("rooms >= ? AND rooms <= ?")
        where_args.extend([min_rooms, max_rooms])

    if price_range:
        min_price = price_range.get("min", 0)
        max_price = price_range.get("max", 10e6)
        where_parts.append("price >= ? AND price <= ?")
        where_args.extend([min_price, max_price])

    where_clause = " AND ".join(where_parts)

    # Fetch listings
    listings = list(db["listings"].rows_where(where_clause, where_args))

    # Classify each listing
    matches = []
    for listing in listings:
        classification = classify_listing_price(listing, db)
        listing_with_class = {**listing, **classification}

        # Filter to under-market matches only if criteria specifies
        if classification["status"] == "under_market":
            gap = classification.get("gap_percent", 0)
            if gap and gap <= -under_market_threshold:
                matches.append(listing_with_class)

    return matches
