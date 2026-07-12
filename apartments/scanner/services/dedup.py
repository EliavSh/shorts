"""Cross-source duplicate detection and merging."""
import json
import logging
import re
import unicodedata
from datetime import datetime

import sqlite_utils

logger = logging.getLogger(__name__)

# Prefer sources with richer data (lat/lon, neighborhood)
SOURCE_PRIORITY = ["mdl_", "yad2_"]


def _normalize_street(address: str) -> str:
    """Extract and normalize the street portion of an address for fingerprinting."""
    if not address:
        return ""
    s = unicodedata.normalize("NFC", address)
    # Drop house numbers (trailing digits / Hebrew letter+digits)
    s = re.sub(r"\s+\d+[\w]*$", "", s)
    s = re.sub(r"[^\w\s]", " ", s, flags=re.UNICODE)
    return re.sub(r"\s+", " ", s).strip().lower()


def _normalize_city(city: str) -> str:
    if not city:
        return ""
    return unicodedata.normalize("NFC", city).strip().lower()


def listing_fingerprint(listing: dict) -> str | None:
    """Return a dedup fingerprint or None if data is insufficient."""
    city = _normalize_city(listing.get("city", ""))
    street = _normalize_street(listing.get("address", ""))
    rooms = round(listing.get("rooms") or 0)
    price = listing.get("price") or 0
    sqm = listing.get("sqm") or 0
    if not city or not street or not price:
        return None
    # Sale and rent are different markets for the same address — never merge
    # across modes. Rent prices are ~100x smaller, so bucket them at ₪1k
    # (₪50k would collapse all rents to bucket 0 and merge distinct rentals).
    deal = listing.get("deal_type") or "sale"
    price_bucket = round(price / (1_000 if deal == "rent" else 50_000))
    sqm_bucket = round(sqm / 10) * 10
    return f"{deal}|{city}|{street}|{rooms}|{price_bucket}|{sqm_bucket}"


def dedup_cross_source(db: sqlite_utils.Database) -> int:
    """Find same-address listings from different sources, keep the canonical one.

    Canonical preference: Madlan (mdl_) over Yad2 (yad2_) because Madlan
    typically carries lat/lon and neighborhood data.

    Archives duplicates to listings_history with reason='merged', stores
    the archived IDs in the canonical listing's alt_ids JSON array.

    Returns the number of listings archived.
    """
    cols = [r[1] for r in db.execute("PRAGMA table_info(listings)").fetchall()]
    rows = db.execute("SELECT * FROM listings WHERE is_active = 1").fetchall()
    listings = [dict(zip(cols, r)) for r in rows]

    # Group by fingerprint
    groups: dict[str, list[dict]] = {}
    for listing in listings:
        fp = listing_fingerprint(listing)
        if fp is None:
            continue
        groups.setdefault(fp, []).append(listing)

    now = datetime.now().isoformat()
    archived = 0

    for fp, group in groups.items():
        if len(group) < 2:
            continue

        # Check that at least 2 different sources are represented
        prefixes = {next((p for p in SOURCE_PRIORITY if g["id"].startswith(p)), "other") for g in group}
        if len(prefixes) < 2:
            continue

        # Sort by priority: preferred source first, then most fields filled
        def sort_key(g: dict) -> tuple:
            prefix_rank = next((i for i, p in enumerate(SOURCE_PRIORITY) if g["id"].startswith(p)), 99)
            filled = sum(1 for v in g.values() if v is not None and v != "")
            return (prefix_rank, -filled)

        group.sort(key=sort_key)
        canonical = group[0]
        duplicates = group[1:]

        dup_ids = [d["id"] for d in duplicates]
        existing_alt = json.loads(canonical.get("alt_ids") or "[]")
        new_alt = list(set(existing_alt + dup_ids))

        # Archive duplicates
        for dup in duplicates:
            db["listings_history"].insert({
                "id": dup["id"],
                "title": dup.get("title"),
                "address": dup.get("address"),
                "city": dup.get("city"),
                "neighborhood": dup.get("neighborhood"),
                "rooms": dup.get("rooms"),
                "sqm": dup.get("sqm"),
                "floor": dup.get("floor"),
                "price": dup.get("price"),
                "price_per_sqm": dup.get("price_per_sqm"),
                "url": dup.get("url"),
                "posted_at": dup.get("posted_at"),
                "gush": dup.get("gush"),
                "lat": dup.get("lat"),
                "lon": dup.get("lon"),
                "is_new_construction": dup.get("is_new_construction", 0),
                "alt_ids": json.dumps([canonical["id"]]),
                "first_seen": dup.get("posted_at"),
                "last_seen": dup.get("last_seen"),
                "deactivated_at": now,
                "deactivation_reason": "merged",
                "matched_transaction_id": None,
            }, replace=True)
            db.execute("DELETE FROM listings WHERE id = ?", [dup["id"]])
            archived += 1

        # Update canonical listing's alt_ids
        db.execute(
            "UPDATE listings SET alt_ids = ? WHERE id = ?",
            [json.dumps(new_alt), canonical["id"]],
        )

    if archived:
        logger.info("dedup_cross_source: archived %d duplicate listings", archived)
    return archived
