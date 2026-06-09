"""Per-building price percentile (Sprint 4).

Given a listing's `(street, house_number, city, price)`, compute where its
asking price falls in the distribution of historical sales at that exact
building. Falls back to street-block (±5 numbers) and then to neighborhood
when the building has too few comparable sales.

Inputs come from the `transactions` table (nadlan.gov.il + future Yad2 sold).

Performance: prefer ``compute_percentile_batch`` when scoring many listings —
it pulls each city's transactions ONCE instead of per-listing.
"""
from __future__ import annotations

import logging
import re
from dataclasses import dataclass

import pandas as pd
import sqlite_utils

logger = logging.getLogger(__name__)


def load_city_transactions(db: sqlite_utils.Database, city: str, lookback_days: int = 365 * 5) -> pd.DataFrame:
    """Pull all transactions for a city, parse street/number once, return a frame."""
    rows = list(
        db.execute(
            """
            SELECT address, city, price, sqm, date
            FROM transactions
            WHERE city = ? AND price > 0
              AND date >= date('now', '-' || ? || ' days')
            """,
            [city.strip(), lookback_days],
        ).fetchall()
    )
    if not rows:
        return pd.DataFrame(columns=["address", "city", "price", "sqm", "date", "t_street", "t_num", "ppm"])
    df = pd.DataFrame(rows, columns=["address", "city", "price", "sqm", "date"])
    parts = df["address"].astype(str).str.extract(r"^\s*(?P<street>[^\d,]+?)\s+(?P<num>\d+)")
    df["t_street"] = parts["street"].apply(_normalize_street)
    df["t_num"] = pd.to_numeric(parts["num"], errors="coerce")
    df["ppm"] = df["price"] / df["sqm"].replace(0, pd.NA)
    return df

# Tweak these knobs as data density grows.
MIN_BUILDING_SALES = 5     # below this → fall back to street block
MIN_STREET_SALES = 8       # below this → fall back to neighborhood
LOOKBACK_DAYS = 365 * 5    # 5 years of transactions are still informative


@dataclass
class PercentileResult:
    """Result of a percentile lookup. ``percentile`` is in [0, 1]."""

    percentile: float          # 0..1, where listing falls
    n_sales: int               # how many comparable sales formed the distribution
    median_price: float        # median of the comparison set
    p25: float
    p75: float
    scope: str                 # "building" | "street_block" | "neighborhood"
    label: str                 # human-readable summary for the popup


def _normalize_street(s: str | None) -> str:
    if not s or not isinstance(s, str):
        return ""
    s = s.strip().replace("‏", "").replace("‎", "")
    s = re.sub(r"\s+", " ", s)
    return s


def _street_number(s: str | int | None) -> int | None:
    if s is None:
        return None
    m = re.match(r"\s*(\d+)", str(s))
    return int(m.group(1)) if m else None


def compute_percentile_from_df(
    df: pd.DataFrame,
    *,
    street: str,
    house_number: str | int | None,
    price: float,
    sqm: float | None = None,
    include_city_fallback: bool = True,
) -> PercentileResult | None:
    """Same logic as compute_percentile but uses a prebuilt city DataFrame.

    The ``near`` scope of the dual-percentile design (see compute_dual_percentile)
    sets ``include_city_fallback=False`` to keep the cohort tightly local — a
    listing with no comparable street-level sales should return None rather
    than dilute into the whole city.
    """
    street_n = _normalize_street(street)
    num = _street_number(house_number)
    if not street_n or price <= 0 or df.empty:
        return None

    metric_col = "price"
    target_value = price
    if sqm and sqm > 0:
        df = df.dropna(subset=["ppm"])
        metric_col = "ppm"
        target_value = price / sqm

    same_street = df[df["t_street"] == street_n]

    if num is not None:
        bldg = same_street[same_street["t_num"] == num]
        if len(bldg) >= MIN_BUILDING_SALES:
            return _build_result(target_value, bldg[metric_col], "building",
                                 f"this building ({street_n} {num})")

        block = same_street[(same_street["t_num"] - num).abs() <= 5]
        if len(block) >= MIN_STREET_SALES:
            return _build_result(target_value, block[metric_col], "street_block",
                                 f"street block ({street_n} {num-5}–{num+5})")

    if len(same_street) >= MIN_STREET_SALES:
        return _build_result(target_value, same_street[metric_col], "street",
                             f"street ({street_n})")

    if include_city_fallback and len(df) >= MIN_STREET_SALES:
        return _build_result(target_value, df[metric_col], "city", "city-wide")

    return None


# Wider-area cohort: same city + same rooms-bucket + recent sales.
# Rooms-aware so a 50 m² flat isn't pooled with a 120 m² penthouse just
# because they share an address. Mirrors compute_zscore's cohort but returns
# a percentile rather than z-score.
ROOMS_COHORT_LOOKBACK_DAYS = 18 * 30
MIN_ROOMS_COHORT_SALES = 10


def compute_rooms_cohort_percentile(
    db: sqlite_utils.Database,
    *,
    city: str,
    rooms: float | None,
    price: float,
    sqm: float,
) -> PercentileResult | None:
    """Percentile of ``price/sqm`` vs same-city, same-rooms-bucket sales.

    Returns a PercentileResult with scope='rooms_cohort' or None if the cohort
    is too small. Used as the "wider area" half of the dual percentile pair.
    """
    if not city or price <= 0 or not sqm or sqm <= 0:
        return None
    rooms_bucket = round(rooms) if rooms is not None else None

    query = """
        SELECT price, sqm FROM transactions
        WHERE city = ? AND price > 0 AND sqm > 0
          AND date >= date('now', '-' || ? || ' days')
    """
    params: list = [city.strip(), ROOMS_COHORT_LOOKBACK_DAYS]
    if rooms_bucket is not None:
        query += " AND rooms = ?"
        params.append(rooms_bucket)

    rows = db.execute(query, params).fetchall()
    ppsqms = [r[0] / r[1] for r in rows if r[1] > 0]
    if len(ppsqms) < MIN_ROOMS_COHORT_SALES:
        return None

    series = pd.Series(ppsqms)
    label_scope = (
        f"{city.strip()}, {rooms_bucket}-room apartments"
        if rooms_bucket is not None
        else f"{city.strip()} (any size)"
    )
    return _build_result(price / sqm, series, "rooms_cohort", label_scope)


@dataclass
class DualPercentileResult:
    """Pair of percentiles for the same listing at two cohort scopes.

    - ``near``  : street-level cohort (building → street_block → street).
                  Skips the city fallback so the comparison stays local.
    - ``area``  : same-city same-rooms-bucket cohort (18-month lookback).
                  Rooms-aware → 50 m² and 120 m² are independent populations.
    Either field may be None if its cohort threshold isn't met.
    """

    near: PercentileResult | None
    area: PercentileResult | None


def compute_dual_percentile(
    df: pd.DataFrame,
    db: sqlite_utils.Database,
    *,
    city: str,
    rooms: float | None,
    street: str,
    house_number: str | int | None,
    price: float,
    sqm: float | None = None,
) -> DualPercentileResult:
    """Compute both cohort percentiles for a listing.

    `df` is the city-scoped transactions DataFrame produced by
    `load_city_transactions` — passed in so the caller (run_scoring) can
    cache it across the loop. `db` is needed only for the rooms-cohort
    query (uses recent sales, separate filter than the 5-yr df).
    """
    near = compute_percentile_from_df(
        df,
        street=street,
        house_number=house_number,
        price=price,
        sqm=sqm,
        include_city_fallback=False,
    )
    area = (
        compute_rooms_cohort_percentile(
            db, city=city, rooms=rooms, price=price, sqm=sqm
        )
        if sqm and sqm > 0
        else None
    )
    return DualPercentileResult(near=near, area=area)


def compute_percentile(
    db: sqlite_utils.Database,
    *,
    street: str,
    house_number: str | int | None,
    city: str,
    price: float,
    sqm: float | None = None,
) -> PercentileResult | None:
    """Return where ``price`` falls vs. comparable sales, or None if no data.

    Uses absolute price by default; if ``sqm`` is given, prices are normalised
    to ₪/m² before comparison so a 60 m² flat isn't misjudged against a 120 m² one.
    """
    street_n = _normalize_street(street)
    num = _street_number(house_number)
    city_n = (city or "").strip()
    if not (street_n and city_n) or price <= 0:
        return None

    # Pull a generous candidate set; we'll filter in pandas.
    rows = list(
        db.execute(
            """
            SELECT address, city, price, sqm, date
            FROM transactions
            WHERE city = ?
              AND price > 0
              AND date >= date('now', '-' || ? || ' days')
            """,
            [city_n, LOOKBACK_DAYS],
        ).fetchall()
    )
    if not rows:
        return None

    df = pd.DataFrame(rows, columns=["address", "city", "price", "sqm", "date"])
    # Parse street + number from address ("הרצל 23" → street="הרצל", num=23)
    parts = df["address"].astype(str).str.extract(r"^\s*(?P<street>[^\d,]+?)\s+(?P<num>\d+)")
    df["t_street"] = parts["street"].apply(_normalize_street)
    df["t_num"] = pd.to_numeric(parts["num"], errors="coerce")

    # Compute comparison metric (₪/m² if we have sqm both sides, else absolute price)
    metric_col = "price"
    target_value = price
    if sqm and sqm > 0 and "sqm" in df.columns:
        df["ppm"] = df["price"] / df["sqm"].replace(0, pd.NA)
        df = df.dropna(subset=["ppm"])
        metric_col = "ppm"
        target_value = price / sqm

    same_street = df[df["t_street"] == street_n]

    # ── Building scope: same street + same house number ──
    if num is not None:
        bldg = same_street[same_street["t_num"] == num]
        if len(bldg) >= MIN_BUILDING_SALES:
            return _build_result(target_value, bldg[metric_col], "building",
                                 f"this building (street {street_n} {num})")

    # ── Street block: same street, ±5 numbers ──
    if num is not None:
        block = same_street[(same_street["t_num"] - num).abs() <= 5]
        if len(block) >= MIN_STREET_SALES:
            return _build_result(target_value, block[metric_col], "street_block",
                                 f"street block ({street_n} {num-5}–{num+5})")

    # ── Whole street ──
    if len(same_street) >= MIN_STREET_SALES:
        return _build_result(target_value, same_street[metric_col], "street",
                             f"street ({street_n})")

    # ── Neighborhood-as-city fallback (cheapest) ──
    if len(df) >= MIN_STREET_SALES:
        return _build_result(target_value, df[metric_col], "city", f"city ({city_n})")

    return None


def compute_zscore(
    db: sqlite_utils.Database,
    *,
    city: str,
    rooms: float | None,
    price: float,
    sqm: float,
    lookback_days: int = 18 * 30,
) -> tuple[float, int, float, float] | None:
    """Return (z_score, n_cohort_sales, mu, sigma) or None if cohort is too sparse.

    Cohort: transactions in (city, round(rooms)) from the last 18 months.
    Metric: ₪/m² — (asking_ppsqm − μ) / σ.
    Positive z = expensive relative to cohort; negative = cheap.
    """
    import statistics as _stats
    if not city or price <= 0 or not sqm or sqm <= 0:
        return None

    rooms_bucket = round(rooms) if rooms is not None else None
    query = """
        SELECT price, sqm FROM transactions
        WHERE city = ?
          AND sqm > 0 AND price > 0
          AND date >= date('now', '-' || ? || ' days')
    """
    params: list = [city.strip(), lookback_days]
    if rooms_bucket is not None:
        query += " AND rooms = ?"
        params.append(rooms_bucket)

    rows = db.execute(query, params).fetchall()
    ppsqms = [r[0] / r[1] for r in rows if r[1] > 0]
    if len(ppsqms) < 5:
        return None

    mu = _stats.mean(ppsqms)
    sigma = _stats.stdev(ppsqms) if len(ppsqms) >= 2 else 0.0
    if sigma == 0:
        return None

    z = (price / sqm - mu) / sigma
    return z, len(ppsqms), mu, sigma


def _build_result(value: float, series: pd.Series, scope: str, label_scope: str) -> PercentileResult:
    s = series.dropna().sort_values()
    if s.empty:
        return PercentileResult(0.5, 0, 0.0, 0.0, 0.0, scope, "no data")
    pct = float((s <= value).sum()) / len(s)
    p25, p50, p75 = s.quantile([0.25, 0.5, 0.75])
    arrow = "🟢 below" if pct < 0.4 else ("🔴 above" if pct > 0.7 else "🟡 around")
    label = (
        f"{arrow} {pct*100:.0f}th pct of {label_scope} "
        f"(n={len(s)}, median ₪{int(p50):,})"
    )
    return PercentileResult(pct, len(s), float(p50), float(p25), float(p75), scope, label)
