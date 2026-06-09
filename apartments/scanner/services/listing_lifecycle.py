"""Listing lifecycle management: ghost state, delisted, confidence-scored sold matching."""
import logging
import math
import re
import unicodedata
from datetime import datetime, timedelta
from difflib import SequenceMatcher

import sqlite_utils

logger = logging.getLogger(__name__)

SOURCE_PREFIXES = {
    "madlan": "mdl_",
    "yad2": "yad2_",
}

# A listing absent from scrape for this long is finalized as delisted.
GHOST_HOURS = 48


def _normalize_text(s: str) -> str:
    if not s:
        return ""
    s = unicodedata.normalize("NFC", s)
    s = re.sub(r"[^\w\s]", " ", s, flags=re.UNICODE)
    return re.sub(r"\s+", " ", s).strip().lower()


def _similar(a: str, b: str) -> bool:
    a, b = _normalize_text(a), _normalize_text(b)
    if not a or not b:
        return False
    return a == b or SequenceMatcher(None, a, b).ratio() >= 0.85


def _exact_match(a: str, b: str) -> bool:
    return _normalize_text(a) == _normalize_text(b)


def _haversine_m(lat1, lon1, lat2, lon2) -> float:
    """Distance in metres between two lat/lon points."""
    R = 6_371_000
    phi1, phi2 = math.radians(lat1), math.radians(lat2)
    dphi = math.radians(lat2 - lat1)
    dlam = math.radians(lon2 - lon1)
    a = math.sin(dphi / 2) ** 2 + math.cos(phi1) * math.cos(phi2) * math.sin(dlam / 2) ** 2
    return 2 * R * math.atan2(math.sqrt(a), math.sqrt(1 - a))


def _match_confidence(listing: dict, txn: dict) -> int:
    """Score how likely a transaction matches a listing (0–100+ points).

    Points table:
      +40  exact normalized address match
      +25  fuzzy address match (ratio ≥ 0.85, if not exact)
      +30  same gush (land registry parcel)
      +15  rooms within ±0.5
      +15  sqm within ±10%
      +10  price within ±15%
      +10  transaction date ≥ listing posted_at
      +20  lat/lon within 100 m

    Threshold for archiving: ≥ 60 → "sold"; 40–59 → "probable_match"
    """
    score = 0

    l_addr = listing.get("address") or ""
    t_addr = txn.get("address") or ""
    if l_addr and t_addr:
        if _exact_match(l_addr, t_addr):
            score += 40
        elif _similar(l_addr, t_addr):
            score += 25

    l_gush = listing.get("gush")
    t_gush = txn.get("gush")
    if l_gush and t_gush and str(l_gush).strip() == str(t_gush).strip():
        score += 30

    l_rooms = listing.get("rooms") or 0
    t_rooms = txn.get("rooms")
    if t_rooms is not None and abs(l_rooms - t_rooms) <= 0.5:
        score += 15

    l_sqm = listing.get("sqm") or 0
    t_sqm = txn.get("sqm") or 0
    if l_sqm > 0 and t_sqm > 0 and abs(l_sqm - t_sqm) / max(l_sqm, t_sqm) <= 0.10:
        score += 15

    l_price = listing.get("price") or 0
    t_price = txn.get("price") or 0
    if l_price > 0 and t_price > 0 and abs(l_price - t_price) / t_price <= 0.15:
        score += 10

    t_date = txn.get("date") or ""
    l_posted = (listing.get("posted_at") or "")[:10]
    if t_date and l_posted and t_date >= l_posted:
        score += 10

    l_lat, l_lon = listing.get("lat"), listing.get("lon")
    t_lat, t_lon = txn.get("lat"), txn.get("lon")
    if all(v is not None for v in (l_lat, l_lon, t_lat, t_lon)):
        try:
            if _haversine_m(l_lat, l_lon, t_lat, t_lon) <= 100:
                score += 20
        except Exception:
            pass

    return score


def _archive_listing(
    db: sqlite_utils.Database,
    listing: dict,
    reason: str,
    matched_transaction_id: str | None = None,
    match_confidence: float | None = None,
) -> None:
    now = datetime.now().isoformat()
    history_row = {
        "id": listing["id"],
        "title": listing.get("title"),
        "address": listing.get("address"),
        "city": listing.get("city"),
        "neighborhood": listing.get("neighborhood"),
        "rooms": listing.get("rooms"),
        "sqm": listing.get("sqm"),
        "floor": listing.get("floor"),
        "price": listing.get("price"),
        "price_per_sqm": listing.get("price_per_sqm"),
        "url": listing.get("url"),
        "posted_at": listing.get("posted_at"),
        "gush": listing.get("gush"),
        "lat": listing.get("lat"),
        "lon": listing.get("lon"),
        "is_new_construction": listing.get("is_new_construction", 0),
        "alt_ids": listing.get("alt_ids"),
        "first_seen": listing.get("posted_at"),
        "last_seen": listing.get("last_seen"),
        "deactivated_at": now,
        "deactivation_reason": reason,
        "matched_transaction_id": matched_transaction_id,
        "match_confidence": match_confidence,
    }
    db["listings_history"].insert(history_row, replace=True)
    db.execute("DELETE FROM listings WHERE id = ?", [listing["id"]])
    db.execute("DELETE FROM listing_scores WHERE listing_id = ?", [listing["id"]])


def mark_delisted(db: sqlite_utils.Database, source: str, current_ids: set[str]) -> int:
    """Two-phase listing retirement:

    Phase 1 — finalize ghosts: listings already marked is_active=0 whose
               last_seen is older than GHOST_HOURS get archived as 'delisted'.
    Phase 2 — ghost new absences: active listings absent from this scrape
               get marked is_active=0 (recoverable for 48 h).

    Returns the number of listings **archived** (phase 1 count).
    """
    prefix = SOURCE_PREFIXES.get(source)
    if not prefix:
        logger.warning("mark_delisted: unknown source %s", source)
        return 0

    cols = [r[1] for r in db.execute("PRAGMA table_info(listings)").fetchall()]
    ghost_cutoff = (datetime.now() - timedelta(hours=GHOST_HOURS)).isoformat()

    # Phase 1: finalize expired ghosts
    ghost_rows = db.execute(
        "SELECT * FROM listings WHERE id LIKE ? AND is_active = 0 AND last_seen < ?",
        [f"{prefix}%", ghost_cutoff],
    ).fetchall()
    archived = 0
    for row in ghost_rows:
        listing = dict(zip(cols, row))
        if listing["id"] not in current_ids:
            _archive_listing(db, listing, "delisted")
            archived += 1

    # Phase 2: ghost newly absent active listings
    active_rows = db.execute(
        "SELECT * FROM listings WHERE id LIKE ? AND is_active = 1",
        [f"{prefix}%"],
    ).fetchall()
    ghosted = 0
    for row in active_rows:
        listing = dict(zip(cols, row))
        if listing["id"] not in current_ids:
            db.execute("UPDATE listings SET is_active = 0 WHERE id = ?", [listing["id"]])
            ghosted += 1

    if archived or ghosted:
        logger.info("mark_delisted[%s]: archived=%d ghosted=%d", source, archived, ghosted)
    return archived


def match_sold_listings(db: sqlite_utils.Database, lookback_days: int = 30) -> int:
    """Match recent transactions to active listings using a confidence point table.

    Confidence ≥ 60 → archived as 'sold'.
    Confidence 40–59 → archived as 'probable_match'.

    Returns the number of listings archived.
    """
    since = (datetime.now() - timedelta(days=lookback_days)).strftime("%Y-%m-%d")

    txn_rows = db.execute(
        "SELECT id, address, city, rooms, sqm, price, date, gush, lat, lon "
        "FROM transactions WHERE date >= ?",
        [since],
    ).fetchall()
    if not txn_rows:
        return 0

    txn_cols = ["id", "address", "city", "rooms", "sqm", "price", "date", "gush", "lat", "lon"]
    transactions = [dict(zip(txn_cols, r)) for r in txn_rows]

    listing_cols = [r[1] for r in db.execute("PRAGMA table_info(listings)").fetchall()]
    listing_rows = db.execute("SELECT * FROM listings WHERE is_active = 1").fetchall()
    listings = [dict(zip(listing_cols, r)) for r in listing_rows]

    # Build city → listings index for speed
    city_index: dict[str, list[dict]] = {}
    for lst in listings:
        city_key = _normalize_text(lst.get("city") or "")
        city_index.setdefault(city_key, []).append(lst)

    archived = 0
    matched_listing_ids: set[str] = set()

    for txn in transactions:
        if not txn["price"] or not txn["city"]:
            continue
        txn_city_key = _normalize_text(txn["city"])
        candidates = city_index.get(txn_city_key, [])

        best_listing: dict | None = None
        best_score = 0

        for listing in candidates:
            if listing["id"] in matched_listing_ids:
                continue
            score = _match_confidence(listing, txn)
            if score > best_score:
                best_score = score
                best_listing = listing

        if best_listing is None or best_score < 40:
            continue

        reason = "sold" if best_score >= 60 else "probable_match"
        _archive_listing(
            db, best_listing, reason,
            matched_transaction_id=txn["id"],
            match_confidence=float(best_score),
        )
        matched_listing_ids.add(best_listing["id"])
        archived += 1

    if archived:
        logger.info("match_sold_listings: archived %d listings (sold/probable_match)", archived)
    return archived
