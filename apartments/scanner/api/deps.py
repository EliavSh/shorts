"""Shared FastAPI dependencies."""
import os
from pathlib import Path

import sqlite_utils

from scanner.db import get_db, init_schema

DEFAULT_DB_PATH = os.environ.get(
    "SCANNER_DB_PATH",
    str(Path(__file__).resolve().parents[2] / "data" / "apartments.db"),
)

# Sources to hide from API responses. Each entry must appear in either
# _SOURCE_URL_MARKERS (filters listings.url) or _SOURCE_TXN_ID_PREFIXES
# (filters transactions.id) — or both. Toggle this single list to re-enable.
#   - madlan: RE-ENABLED 2026-07 — saved session passes PerimeterX; scraped on
#     the residential PC alongside yad2 (sale + rent).
#   - nadlan: disabled per user request — sale data isn't shown on the site
DISABLED_SOURCES: tuple[str, ...] = ("nadlan",)

# The `listings` table has no `source` column; the source is encoded in `url`.
_SOURCE_URL_MARKERS: dict[str, str] = {
    "yad2": "yad2.co.il",
    "madlan": "madlan.co.il",
}

# The `transactions` table has no `source` column either; the source is encoded
# in the row id prefix (e.g. 'nadlan_42', 'yad2sold_123_2024-...').
_SOURCE_TXN_ID_PREFIXES: dict[str, str] = {
    "nadlan": "nadlan_",
    "yad2": "yad2sold_",  # yad2-sold transactions live on the same table
}


def disabled_sources_clause(alias: str = "") -> str:
    """SQL fragment ` AND <url> NOT LIKE '%marker%'` for each disabled listing source.

    Returns "" if no listing sources are disabled. `alias` is the table alias
    for the `listings` row (e.g. "l" for `FROM listings l`); pass "" when no alias.
    """
    markers = [_SOURCE_URL_MARKERS[s] for s in DISABLED_SOURCES if s in _SOURCE_URL_MARKERS]
    if not markers:
        return ""
    col = f"{alias}.url" if alias else "url"
    parts = [f"{col} NOT LIKE '%{m}%'" for m in markers]
    return " AND (" + " AND ".join(parts) + ")"


def disabled_transactions_clause(alias: str = "") -> str:
    """SQL fragment ` AND <id> NOT LIKE 'prefix_%'` for each disabled txn source.

    Returns "" if no transaction sources are disabled. Use for queries on the
    `transactions` table.
    """
    prefixes = [
        _SOURCE_TXN_ID_PREFIXES[s] for s in DISABLED_SOURCES if s in _SOURCE_TXN_ID_PREFIXES
    ]
    if not prefixes:
        return ""
    col = f"{alias}.id" if alias else "id"
    parts = [f"{col} NOT LIKE '{p}%'" for p in prefixes]
    return " AND (" + " AND ".join(parts) + ")"


def get_database() -> sqlite_utils.Database:
    """FastAPI dependency yielding a connection to the scanner SQLite DB.

    A fresh sqlite_utils.Database per request. The connection is short-lived;
    SQLite WAL mode (set in init_schema) lets readers and writers coexist.
    """
    db = get_db(DEFAULT_DB_PATH)
    return db


def get_database_with_schema() -> sqlite_utils.Database:
    """Dependency that also ensures the schema exists (used in tests)."""
    db = get_db(DEFAULT_DB_PATH)
    init_schema(db)
    return db
