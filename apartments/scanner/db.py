"""SQLite database schema and helpers."""
import sqlite3
import statistics as _statistics
from datetime import datetime
from pathlib import Path
from typing import Any, Optional

import sqlite_utils


def get_db(db_path: str | Path) -> sqlite_utils.Database:
    """Get or create SQLite database."""
    db_path = Path(db_path)
    db_path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(db_path), check_same_thread=False)
    return sqlite_utils.Database(conn)


def init_schema(db: sqlite_utils.Database) -> None:
    """Initialize database schema if it doesn't exist."""

    # Enable WAL so the dashboard can read while a scrape is writing.
    # Idempotent — safe to call on every init.
    try:
        db.execute("PRAGMA journal_mode=WAL")
        db.execute("PRAGMA synchronous=NORMAL")
    except Exception:
        pass

    # Transactions table: actual recorded sales from nadlan.gov.il
    db.execute("""
        CREATE TABLE IF NOT EXISTS transactions (
            id TEXT PRIMARY KEY,
            address TEXT,
            city TEXT,
            rooms INTEGER,
            sqm REAL,
            floor INTEGER,
            year_built INTEGER,
            price INTEGER,
            date TEXT,
            gush TEXT,
            lat REAL,
            lon REAL,
            inserted_at TEXT
        )
    """)

    db.execute("""
        CREATE INDEX IF NOT EXISTS idx_transactions_city_date
        ON transactions(city, date)
    """)

    db.execute("""
        CREATE INDEX IF NOT EXISTS idx_transactions_city_rooms_date
        ON transactions(city, rooms, date)
    """)

    # Listings table: current asking-price listings from Yad2 / Madlan
    db.execute("""
        CREATE TABLE IF NOT EXISTS listings (
            id TEXT PRIMARY KEY,
            title TEXT,
            address TEXT,
            city TEXT,
            neighborhood TEXT,
            rooms INTEGER,
            sqm REAL,
            floor INTEGER,
            price INTEGER,
            price_per_sqm REAL,
            url TEXT,
            posted_at TEXT,
            gush TEXT,
            lat REAL,
            lon REAL,
            last_seen TEXT,
            is_active BOOLEAN
        )
    """)
    # Backfill: add columns on legacy DBs (idempotent)
    try:
        cols = {r[1] for r in db.execute("PRAGMA table_info(listings)").fetchall()}
        if "neighborhood" not in cols:
            db.execute("ALTER TABLE listings ADD COLUMN neighborhood TEXT")
        if "is_new_construction" not in cols:
            db.execute("ALTER TABLE listings ADD COLUMN is_new_construction INTEGER DEFAULT 0")
        if "alt_ids" not in cols:
            db.execute("ALTER TABLE listings ADD COLUMN alt_ids TEXT")
        if "geocode_status" not in cols:
            db.execute("ALTER TABLE listings ADD COLUMN geocode_status TEXT DEFAULT 'pending'")
        if "first_seen" not in cols:
            db.execute("ALTER TABLE listings ADD COLUMN first_seen TEXT")
        # Phase 2 metadata: nullable so existing rows don't need backfill — UI
        # treats NULL as "Not provided".
        if "has_balcony" not in cols:
            db.execute("ALTER TABLE listings ADD COLUMN has_balcony INTEGER")
        if "direction" not in cols:
            db.execute("ALTER TABLE listings ADD COLUMN direction TEXT")
    except Exception:
        pass

    db.execute("""
        CREATE INDEX IF NOT EXISTS idx_listings_city_rooms
        ON listings(city, rooms)
    """)

    db.execute("""
        CREATE INDEX IF NOT EXISTS idx_listings_last_seen
        ON listings(last_seen)
    """)

    # Listing snapshots: track price changes per listing over time
    db.execute("""
        CREATE TABLE IF NOT EXISTS listing_snapshots (
            listing_id TEXT,
            snapshot_date TEXT,
            price INTEGER,
            price_per_sqm REAL,
            status TEXT
        )
    """)

    db.execute("""
        CREATE INDEX IF NOT EXISTS idx_listing_snapshots
        ON listing_snapshots(listing_id, snapshot_date)
    """)

    # Geocode cache: avoid re-geocoding same address
    db.execute("""
        CREATE TABLE IF NOT EXISTS geocode_cache (
            address TEXT,
            city TEXT,
            gush TEXT,
            lat REAL,
            lon REAL,
            cached_at TEXT,
            PRIMARY KEY (address, city)
        )
    """)

    # Run history: metadata about each scrape/alert run, optionally per-city
    db.execute("""
        CREATE TABLE IF NOT EXISTS run_history (
            run_id TEXT PRIMARY KEY,
            source TEXT,
            city TEXT,
            started_at TEXT,
            ended_at TEXT,
            status TEXT,
            error_message TEXT,
            rows_scraped INTEGER,
            rows_inserted INTEGER,
            rows_updated INTEGER
        )
    """)
    # Backfill: add columns on legacy DBs (idempotent)
    try:
        cols = {r[1] for r in db.execute("PRAGMA table_info(run_history)").fetchall()}
        for col, coldef in [
            ("city", "TEXT"),
            ("elapsed_seconds", "REAL"),
            ("captcha_detected", "INTEGER DEFAULT 0"),
            ("error_type", "TEXT"),
            ("pid", "INTEGER"),
        ]:
            if col not in cols:
                db.execute(f"ALTER TABLE run_history ADD COLUMN {col} {coldef}")
    except Exception:
        pass

    # Heartbeat: one row per scrape phase, used for stall detection
    db.execute("""
        CREATE TABLE IF NOT EXISTS run_heartbeat (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            source TEXT,
            run_id TEXT,
            ts TEXT,
            progress_note TEXT
        )
    """)

    # Per-listing price history (Sprint 3.a) — Madlan's `eventsHistory` per Bulletin
    db.execute("""
        CREATE TABLE IF NOT EXISTS listing_price_history (
            listing_id TEXT,
            event_type TEXT,
            price INTEGER,
            date TEXT,
            PRIMARY KEY (listing_id, event_type, date)
        )
    """)
    db.execute("""
        CREATE INDEX IF NOT EXISTS idx_lph_listing_date
        ON listing_price_history(listing_id, date)
    """)

    # Listings history: archived listings (delisted, sold, or merged duplicates)
    db.execute("""
        CREATE TABLE IF NOT EXISTS listings_history (
            id TEXT PRIMARY KEY,
            title TEXT,
            address TEXT,
            city TEXT,
            neighborhood TEXT,
            rooms INTEGER,
            sqm REAL,
            floor INTEGER,
            price INTEGER,
            price_per_sqm REAL,
            url TEXT,
            posted_at TEXT,
            gush TEXT,
            lat REAL,
            lon REAL,
            is_new_construction INTEGER DEFAULT 0,
            alt_ids TEXT,
            first_seen TEXT,
            last_seen TEXT,
            deactivated_at TEXT,
            deactivation_reason TEXT,
            matched_transaction_id TEXT
        )
    """)
    # Backfill: add match_confidence on legacy DBs (idempotent)
    try:
        h_cols = {r[1] for r in db.execute("PRAGMA table_info(listings_history)").fetchall()}
        if "match_confidence" not in h_cols:
            db.execute("ALTER TABLE listings_history ADD COLUMN match_confidence REAL")
    except Exception:
        pass

    db.execute("""
        CREATE INDEX IF NOT EXISTS idx_lh_city_deactivated
        ON listings_history(city, deactivated_at)
    """)
    db.execute("""
        CREATE INDEX IF NOT EXISTS idx_lh_reason
        ON listings_history(deactivation_reason)
    """)

    # Pinui Binui zones: urban renewal evacuation-construction zones from MOCH
    db.execute("""
        CREATE TABLE IF NOT EXISTS pinui_binui_zones (
            id INTEGER PRIMARY KEY,
            zone_name TEXT,
            city TEXT,
            status TEXT,
            track TEXT,
            plan_number TEXT,
            planning_status TEXT,
            approval_date TEXT,
            units_existing INTEGER,
            units_added INTEGER,
            units_total INTEGER,
            lat REAL,
            lon REAL,
            geometry_json TEXT,
            fetched_at TEXT
        )
    """)
    # Migrate: add geometry_json if the table already existed without it
    existing_cols = {row[1] for row in db.execute("PRAGMA table_info(pinui_binui_zones)").fetchall()}
    if "geometry_json" not in existing_cols:
        db.execute("ALTER TABLE pinui_binui_zones ADD COLUMN geometry_json TEXT")

    db.execute("""
        CREATE INDEX IF NOT EXISTS idx_pb_zones_city
        ON pinui_binui_zones(city)
    """)

    # Scoring results: one row per active listing, recomputed each cron cycle
    db.execute("""
        CREATE TABLE IF NOT EXISTS listing_scores (
            listing_id TEXT PRIMARY KEY,
            computed_at TEXT,
            cohort_city TEXT,
            cohort_rooms INTEGER,
            z_score REAL,
            gap_percent REAL,
            nadlan_median_ppsqm REAL,
            percentile_rank REAL,
            n_cohort_sales INTEGER,
            motivation_score REAL,
            value_add_gap REAL,
            days_on_market INTEGER,
            last_alerted_at TEXT
        )
    """)
    db.execute("""
        CREATE INDEX IF NOT EXISTS idx_ls_gap
        ON listing_scores(gap_percent)
    """)
    db.execute("""
        CREATE INDEX IF NOT EXISTS idx_ls_zscore
        ON listing_scores(z_score)
    """)

    # Backfill: columns added after the schema was deployed (idempotent).
    # `near_*` mirror the existing percentile_rank/n_cohort_sales for the
    # street-level cohort; `area_*` are the rooms-aware city cohort.
    try:
        score_cols = {
            r[1] for r in db.execute("PRAGMA table_info(listing_scores)").fetchall()
        }
        if "near_scope" not in score_cols:
            db.execute("ALTER TABLE listing_scores ADD COLUMN near_scope TEXT")
        if "near_n_sales" not in score_cols:
            db.execute("ALTER TABLE listing_scores ADD COLUMN near_n_sales INTEGER")
        if "near_median_ppsqm" not in score_cols:
            db.execute("ALTER TABLE listing_scores ADD COLUMN near_median_ppsqm REAL")
        if "area_percentile_rank" not in score_cols:
            db.execute("ALTER TABLE listing_scores ADD COLUMN area_percentile_rank REAL")
        if "area_n_sales" not in score_cols:
            db.execute("ALTER TABLE listing_scores ADD COLUMN area_n_sales INTEGER")
        if "area_median_ppsqm" not in score_cols:
            db.execute("ALTER TABLE listing_scores ADD COLUMN area_median_ppsqm REAL")
    except Exception:
        pass

    db.conn.commit()


def upsert_pinui_binui_zones(
    db: sqlite_utils.Database,
    zones: list[dict[str, Any]],
) -> int:
    """Upsert פינוי בינוי zones. Return count."""
    if not zones:
        return 0
    db["pinui_binui_zones"].insert_all(zones, replace=True)
    return len(zones)


def upsert_transactions(
    db: sqlite_utils.Database,
    transactions: list[dict[str, Any]],
) -> int:
    """Upsert transactions into database. Return count inserted/updated."""
    if not transactions:
        return 0

    db["transactions"].insert_all(
        transactions,
        replace=True,
    )
    return len(transactions)


def upsert_listings(
    db: sqlite_utils.Database,
    listings: list[dict[str, Any]],
) -> int:
    """Upsert listings into database. Return count inserted/updated.

    Side-effect: writes a 'price_change' row to listing_price_history when the
    price of an already-known listing has changed.
    """
    if not listings:
        return 0

    ids = [l["id"] for l in listings if l.get("id")]
    if ids:
        placeholders = ",".join("?" * len(ids))
        existing_rows = {
            row[0]: (row[1], row[2])
            for row in db.execute(
                f"SELECT id, price, first_seen FROM listings WHERE id IN ({placeholders})", ids
            ).fetchall()
        }
        now_iso = datetime.now().isoformat()
        today = datetime.now().strftime("%Y-%m-%d")
        price_events = []
        for listing in listings:
            lid = listing.get("id")
            new_price = listing.get("price")
            old_price, old_first_seen = existing_rows.get(lid, (None, None))
            if lid and old_price is not None and old_price != new_price and new_price:
                price_events.append({
                    "listing_id": lid,
                    "event_type": "price_change",
                    "price": new_price,
                    "date": today,
                })
            # Preserve existing first_seen; set now_iso for brand-new listings
            listing["first_seen"] = old_first_seen or now_iso
        if price_events:
            db["listing_price_history"].insert_all(price_events, replace=True)
    else:
        now_iso = datetime.now().isoformat()
        for listing in listings:
            listing["first_seen"] = listing.get("first_seen") or now_iso

    db["listings"].insert_all(listings, replace=True)
    return len(listings)


def get_listings_for_city(db: sqlite_utils.Database, city: str) -> list[dict]:
    """Get all active listings for a city."""
    return list(
        db.execute(
            "SELECT * FROM listings WHERE city = ? AND is_active = 1 ORDER BY last_seen DESC",
            [city],
        ).fetchall()
    )


def get_transaction_stats(
    db: sqlite_utils.Database,
    city: str,
    rooms: Optional[int] = None,
    lookback_days: int = 365,
) -> dict[str, Any]:
    """Get price statistics for transactions in a city.

    Uses actual median (not mean) for ₪/sqm to avoid skew from luxury outliers.
    """
    query = """
        SELECT price, sqm, date
        FROM transactions
        WHERE city = ?
            AND date > date('now', '-' || ? || ' days')
            AND sqm > 0 AND price > 0
    """
    params = [city, lookback_days]

    if rooms is not None:
        query += " AND rooms = ?"
        params.append(rooms)

    rows = db.execute(query, params).fetchall()
    if not rows:
        return {}

    prices = [r[0] for r in rows]
    ppsqms = [r[0] / r[1] for r in rows]
    dates = [r[2] for r in rows]

    return {
        "count": len(rows),
        "median_price": _statistics.median(prices),
        "median_price_per_sqm": _statistics.median(ppsqms),
        "min_price": min(prices),
        "max_price": max(prices),
        "earliest_date": min(dates),
        "latest_date": max(dates),
    }
