"""Scheduled scrape entrypoint — invoked by systemd timer or Task Scheduler.

Runs all configured sources in unattended mode. On CAPTCHA / session-expired,
the scraper sends a Telegram message; this script does NOT prompt for input.

Circuit breaker: if a source has failed 3 cycles in a row (per run_history),
it is skipped this cycle. Manual recovery: refresh the session, then it
auto-resumes next cycle.

Usage:
    python -m scripts.cron_scrape                # all sources
    python -m scripts.cron_scrape --source madlan
"""
import asyncio
import logging
import os
import sys
import time
from datetime import datetime
from pathlib import Path

import click
from dotenv import load_dotenv

# Load .env BEFORE importing modules that snapshot env vars at import time
# (e.g. scanner.alerts.telegram reads TELEGRAM_BOT_TOKEN at module level).
# Systemd runs already get this via EnvironmentFile=, but standalone CLI
# invocations need this so manual runs can send Telegram messages.
load_dotenv(Path(__file__).resolve().parents[1] / ".env")

from scanner.alerts.telegram import notify_run_summary, send_deal_alerts, send_alert
from scanner.db import get_db, init_schema, upsert_listings, upsert_transactions
from scanner.matcher import run_scoring
from scanner.scrapers.madlan import scrape_madlan_listings
from scanner.scrapers.yad2 import scrape_yad2_listings, scrape_yad2_sold
from scanner.scrapers.nadlan import scrape_nadlan_cities, CITY_CODES
from scanner.services.listing_lifecycle import mark_delisted, match_sold_listings
from scanner.services.dedup import dedup_cross_source

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(name)s %(levelname)s: %(message)s",
)
logger = logging.getLogger("cron_scrape")

DB_PATH = Path(os.getenv("DATA_DIR", "data")) / "apartments.db"
RAW_DIR = Path(os.getenv("DATA_DIR", "data")) / "raw"
LOCK_FILE = Path(os.getenv("DATA_DIR", "data")) / "scrape.lock"
CIRCUIT_BREAKER_FAILURES = 3


def _acquire_lock() -> bool:
    if LOCK_FILE.exists():
        if time.time() - LOCK_FILE.stat().st_mtime < 7200:
            return False
        LOCK_FILE.unlink()
    LOCK_FILE.write_text(str(os.getpid()))
    return True


def _release_lock():
    LOCK_FILE.unlink(missing_ok=True)


def _is_circuit_open(db, source: str) -> bool:
    """Skip a source if its last 3 runs all failed/no_listings."""
    rows = list(
        db.execute(
            "SELECT status FROM run_history WHERE source=? "
            "ORDER BY started_at DESC LIMIT ?",
            [source, CIRCUIT_BREAKER_FAILURES],
        ).fetchall()
    )
    if len(rows) < CIRCUIT_BREAKER_FAILURES:
        return False
    return all(r[0] in ("error", "no_listings") for r in rows)


def _nadlan_watermark(db) -> str | None:
    """Return MAX(date) from transactions as a watermark, or None for full scrape."""
    row = db.execute("SELECT MAX(date) FROM transactions WHERE date IS NOT NULL").fetchone()
    return row[0] if row and row[0] else None


def _heartbeat(db, source: str, run_id: str, note: str) -> None:
    try:
        db["run_heartbeat"].insert({
            "source": source, "run_id": run_id,
            "ts": datetime.now().isoformat(), "progress_note": note,
        })
    except Exception:
        pass


def _run_row(run_id, source, started_ts, status, rows_scraped=0,
             rows_inserted=0, rows_updated=0, error_msg=None, elapsed=None, captcha=0) -> dict:
    return {
        "run_id": run_id, "source": source, "city": None,
        "started_at": started_ts, "ended_at": datetime.now().isoformat(),
        "status": status, "rows_scraped": rows_scraped,
        "rows_inserted": rows_inserted, "rows_updated": rows_updated,
        "error_message": error_msg,
        "elapsed_seconds": elapsed,
        "captcha_detected": captcha,
        "pid": os.getpid(),
    }


def _count_new_listings(db, listing_ids: list[str]) -> int:
    """How many of these listing IDs are not yet in the DB.

    Used for the 'rows (+N new)' line in the Telegram run summary so the user
    can tell at a glance how many of a cycle's rows were truly new vs refreshes
    of already-tracked listings.
    """
    if not listing_ids:
        return 0
    placeholders = ",".join("?" * len(listing_ids))
    existing = db.execute(
        f"SELECT COUNT(*) FROM listings WHERE id IN ({placeholders})",
        listing_ids,
    ).fetchone()[0]
    return len(listing_ids) - existing


async def _run_source(db, source: str, raw_dir: Path) -> tuple[int, int, set[str], str | None]:
    """Returns (rows_inserted, new_count, scraped_ids, error_str). error_str is None on success."""
    started = datetime.now().isoformat()
    run_id = f"{started}_{source}"
    t0 = time.time()
    _heartbeat(db, source, run_id, "starting")
    try:
        if source == "madlan":
            listings = await scrape_madlan_listings(raw_snapshot_dir=raw_dir, unattended=True)
        elif source == "yad2":
            listings = await scrape_yad2_listings(raw_snapshot_dir=raw_dir)
        elif source == "yad2_sold":
            transactions = await scrape_yad2_sold()
            if not transactions:
                db["run_history"].insert(_run_row(
                    run_id, source, started, "no_listings",
                    elapsed=time.time() - t0,
                ))
                _heartbeat(db, source, run_id, "done: 0 transactions")
                return 0, 0, set(), "no transactions (session expired?)"
            count = upsert_transactions(db, transactions)
            db["run_history"].insert(_run_row(
                run_id, source, started, "success",
                rows_scraped=len(transactions), rows_inserted=count,
                elapsed=time.time() - t0,
            ))
            _heartbeat(db, source, run_id, f"done: {count} transactions")
            return count, 0, set(), None
        elif source == "nadlan":
            # Incremental: scrape only since the latest transaction already in DB
            since = _nadlan_watermark(db)
            cities = list(CITY_CODES.keys())
            logger.info(f"nadlan: scraping {len(cities)} cities since={since}")
            transactions = await scrape_nadlan_cities(cities, since_date=since, raw_snapshot_dir=raw_dir)
            if not transactions:
                # Empty result for an incremental scrape = "everything is already in DB",
                # which is success, not failure. Recording 'success' here keeps the
                # circuit breaker from tripping on a quiet stretch of no new gov
                # transactions (the gov publishes in batches, sometimes weeks apart).
                db["run_history"].insert(_run_row(
                    run_id, source, started, "success",
                    elapsed=time.time() - t0,
                ))
                _heartbeat(db, source, run_id, "done: 0 new transactions (up to date)")
                return 0, 0, set(), None
            count = upsert_transactions(db, transactions)
            db["run_history"].insert(_run_row(
                run_id, source, started, "success",
                rows_scraped=len(transactions), rows_inserted=count,
                elapsed=time.time() - t0,
            ))
            _heartbeat(db, source, run_id, f"done: {count} transactions")
            return count, 0, set(), None
        else:
            return 0, 0, set(), f"unknown source: {source}"

        if not listings:
            db["run_history"].insert(_run_row(
                run_id, source, started, "no_listings",
                elapsed=time.time() - t0,
            ))
            _heartbeat(db, source, run_id, "done: 0 listings")
            return 0, 0, set(), "no listings (session expired?)"

        scraped_ids = {l["id"] for l in listings if l.get("id")}
        # Count how many ids are brand-new before we upsert (after upsert they'd
        # all look existing). Used for the '(+N new)' line in the Telegram message.
        new_count = _count_new_listings(db, list(scraped_ids))

        # Split _events out into listing_price_history (Sprint 3.a)
        events: list[dict] = []
        for l in listings:
            events.extend(l.pop("_events", []) or [])
        if events:
            db["listing_price_history"].insert_all(events, ignore=True)
        count = upsert_listings(db, listings)
        db["run_history"].insert(_run_row(
            run_id, source, started, "success",
            rows_scraped=len(listings), rows_inserted=new_count,
            rows_updated=count - new_count,
            elapsed=time.time() - t0,
        ))
        _heartbeat(db, source, run_id, f"done: {count} listings (+{new_count} new)")
        return count, new_count, scraped_ids, None
    except Exception as e:
        logger.exception(f"{source} scrape failed")
        err_str = str(e)
        captcha = 1 if "captcha" in err_str.lower() else 0
        db["run_history"].insert(_run_row(
            run_id, source, started, "error",
            error_msg=err_str, elapsed=time.time() - t0, captcha=captcha,
        ))
        _heartbeat(db, source, run_id, f"error: {err_str[:80]}")
        return 0, 0, set(), f"{source}: {e}"


@click.command()
@click.option("--source", "sources", multiple=True, default=("yad2", "yad2_sold"),
              type=click.Choice(["madlan", "yad2", "yad2_sold", "nadlan"]),
              help="Source(s) to run; default = yad2 + yad2_sold. "
                   "Madlan and nadlan are excluded by default (madlan: PerimeterX "
                   "CAPTCHA unsolved; nadlan: not used on the site). "
                   "Pinui_binui zones run on their own daily timer.")
@click.option("--force", is_flag=True, default=False,
              help="Bypass the circuit breaker. Use after a transient failure "
                   "(e.g. network blip) so a manual run can re-prime the source "
                   "before the unattended hourly cycle picks it up again.")
def main(sources, force):
    """Run scheduled scrape and post a summary to Telegram."""
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    RAW_DIR.mkdir(parents=True, exist_ok=True)
    db = get_db(DB_PATH)
    init_schema(db)

    if not _acquire_lock():
        logger.warning("Scrape already running — lock file present. Exiting.")
        send_alert("⛔ Scrape skipped: previous run still active (lock file present)")
        sys.exit(0)

    rows_by_source: dict[str, int] = {}
    new_by_source: dict[str, int] = {}
    errors: list[str] = []
    listing_sources_run: list[str] = []

    try:
        for source in sources:
            if _is_circuit_open(db, source) and not force:
                logger.warning(f"Circuit breaker open for {source} (3+ recent failures) — skipping.")
                errors.append(f"{source}: circuit-breaker (refresh session)")
                send_alert(
                    f"⛔ <b>Circuit breaker open: {source}</b>\n"
                    f"3+ consecutive failures. Session refresh may be needed.\n"
                    f"Last runs: check run_history table."
                )
                continue
            try:
                rows, new_count, scraped_ids, err = asyncio.run(
                    asyncio.wait_for(_run_source(db, source, RAW_DIR), timeout=1800)
                )
            except asyncio.TimeoutError:
                rows, new_count, scraped_ids, err = 0, 0, set(), f"{source}: timed out after 30min"
                db["run_history"].insert(_run_row(
                    f"{datetime.now().isoformat()}_{source}", source,
                    datetime.now().isoformat(), "timeout", elapsed=1800,
                ))
                send_alert(f"⏱ <b>{source}</b> scrape timed out after 30 minutes")
            rows_by_source[source] = rows
            new_by_source[source] = new_count
            if err:
                errors.append(err)
            new_note = f" (+{new_count} new)" if source in ("madlan", "yad2") else ""
            logger.info(f"  [{source}] +{rows} rows{new_note}" + (f" (err: {err})" if err else ""))

            # Listing lifecycle: archive delisted listings for listing sources only
            if source in ("madlan", "yad2") and scraped_ids:
                delisted = mark_delisted(db, source, scraped_ids)
                if delisted:
                    logger.info(f"  [{source}] archived {delisted} delisted listings")
                listing_sources_run.append(source)

        # After all listing sources: match sold listings and dedup cross-source
        if listing_sources_run:
            sold = match_sold_listings(db)
            if sold:
                logger.info(f"match_sold: archived {sold} sold listings")
            deduped = dedup_cross_source(db)
            if deduped:
                logger.info(f"dedup: merged {deduped} duplicate listings")

        # Step 5: score all active listings + clean stale scores
        try:
            scored = run_scoring(db)
            logger.info(f"scoring: {scored} listings scored")
            db.execute(
                "DELETE FROM listing_scores WHERE listing_id NOT IN "
                "(SELECT id FROM listings WHERE is_active=1)"
            )
        except Exception as e:
            logger.exception("run_scoring failed")
            errors.append(f"scoring: {e}")

        # Step 6: send deal alerts (top-5 by gap, 7-day dedup)
        try:
            send_deal_alerts(db)
        except Exception as e:
            logger.exception("send_deal_alerts failed")
            errors.append(f"deal_alerts: {e}")

        notify_run_summary(rows_by_source, errors, new_by_source=new_by_source)
        logger.info(
            f"Cycle complete. summary={rows_by_source} new={new_by_source} errors={len(errors)}"
        )
    finally:
        _release_lock()
    sys.exit(1 if errors and not any(rows_by_source.values()) else 0)


if __name__ == "__main__":
    main()
