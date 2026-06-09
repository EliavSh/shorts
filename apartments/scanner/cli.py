"""Command-line interface for apartment scanner."""
import asyncio
import json
import logging
import os
import sys
import time as _time
import uuid
from datetime import datetime, timedelta
from pathlib import Path
from typing import Optional

import click
from dotenv import load_dotenv

from .db import get_db, init_schema, upsert_transactions, upsert_listings, upsert_pinui_binui_zones
from .scrapers.nadlan import scrape_nadlan_cities, get_mock_transactions
from .scrapers.yad2 import scrape_yad2_listings, scrape_yad2_sold, get_mock_listings
from .scrapers.madlan import scrape_madlan_listings
from .matcher import find_matching_listings
from .alerts.telegram import send_listing_alert
import yaml

# Load environment variables
load_dotenv()

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
)
logger = logging.getLogger(__name__)


@click.group()
def cli():
    """Apartment scanner CLI."""
    pass


@cli.command()
@click.option(
    "--source",
    type=click.Choice(["yad2", "madlan", "yad2_sold"]),  # "nadlan" hidden — kept in code but not exposed
    required=True,
    help="Data source to scrape",
)
@click.option(
    "--mode",
    type=click.Choice(["full", "incremental"]),
    default="incremental",
    help="Full historical or incremental (new only)",
)
@click.option(
    "--cities",
    multiple=True,
    default=["תל אביב", "רמת גן", "גבעתיים"],
    help="Hebrew city names to scrape (repeatable)",
)
@click.option(
    "--db-path",
    default="data/apartments.db",
    help="Path to SQLite database",
)
@click.option(
    "--raw-snapshots",
    default="data/raw",
    help="Directory to save raw JSON snapshots",
)
def scrape(source: str, mode: str, cities, db_path: str, raw_snapshots: str):
    """Scrape apartment data."""
    db_path = Path(db_path)
    raw_snapshots = Path(raw_snapshots)

    logger.info(f"Starting scrape: source={source}, mode={mode}, cities={cities}")

    db = get_db(db_path)
    init_schema(db)

    run_id = str(uuid.uuid4())
    start_time = datetime.now().isoformat()

    if source == "nadlan":
        try:
            logger.info(f"Scraping nadlan via Playwright for {list(cities)}")
            transactions = asyncio.run(
                scrape_nadlan_cities(
                    list(cities),
                    since_date=None if mode == "full" else db.execute("SELECT MAX(date) FROM transactions").fetchone()[0],
                    raw_snapshot_dir=raw_snapshots,
                )
            )
            if not transactions:
                logger.warning("No transactions from live scrape — falling back to mock data")
                transactions = get_mock_transactions()

            if transactions:
                count = upsert_transactions(db, transactions)
                logger.info(f"Inserted/updated {count} transactions")

                # Log run
                db["run_history"].insert(
                    {
                        "run_id": run_id,
                        "source": source,
                        "started_at": start_time,
                        "ended_at": datetime.now().isoformat(),
                        "status": "success",
                        "rows_scraped": len(transactions),
                        "rows_inserted": count,
                        "rows_updated": 0,
                    }
                )
            else:
                logger.warning("No transactions scraped")

        except Exception as e:
            logger.error(f"Scrape failed: {e}", exc_info=True)
            db["run_history"].insert(
                {
                    "run_id": run_id,
                    "source": source,
                    "started_at": start_time,
                    "ended_at": datetime.now().isoformat(),
                    "status": "error",
                    "error_message": str(e),
                    "rows_scraped": 0,
                    "rows_inserted": 0,
                    "rows_updated": 0,
                }
            )
            sys.exit(1)

    elif source == "madlan":
        try:
            logger.info("Scraping Madlan listings (SSR HTML + GraphQL)")
            listings = asyncio.run(scrape_madlan_listings(raw_snapshot_dir=raw_snapshots))
            if listings:
                # Split _events out into listing_price_history (Sprint 3.a)
                events: list[dict] = []
                for l in listings:
                    events.extend(l.pop("_events", []) or [])
                if events:
                    db["listing_price_history"].insert_all(events, ignore=True)
                    logger.info(f"Inserted {len(events)} price-history events")
                count = upsert_listings(db, listings)
                logger.info(f"Inserted/updated {count} Madlan listings")
                db["run_history"].insert({
                    "run_id": run_id, "source": source,
                    "started_at": start_time, "ended_at": datetime.now().isoformat(),
                    "status": "success", "rows_scraped": len(listings),
                    "rows_inserted": count, "rows_updated": 0,
                })
            else:
                logger.warning("No Madlan listings — session may be missing/expired. "
                               "Run: python -m scanner.cli refresh-session --site madlan")
                db["run_history"].insert({
                    "run_id": run_id, "source": source,
                    "started_at": start_time, "ended_at": datetime.now().isoformat(),
                    "status": "no_listings", "rows_scraped": 0,
                    "rows_inserted": 0, "rows_updated": 0,
                })
        except Exception as e:
            logger.error(f"Madlan scrape failed: {e}", exc_info=True)
            db["run_history"].insert({
                "run_id": run_id, "source": source,
                "started_at": start_time, "ended_at": datetime.now().isoformat(),
                "status": "error", "error_message": str(e),
                "rows_scraped": 0, "rows_inserted": 0, "rows_updated": 0,
            })
            sys.exit(1)

    elif source == "yad2":
        try:
            logger.info("Scraping Yad2 listings via Playwright")
            listings = asyncio.run(scrape_yad2_listings(raw_snapshot_dir=raw_snapshots))
            if listings:
                count = upsert_listings(db, listings)
                logger.info(f"Inserted/updated {count} listings")
                db["run_history"].insert({
                    "run_id": run_id,
                    "source": source,
                    "started_at": start_time,
                    "ended_at": datetime.now().isoformat(),
                    "status": "success",
                    "rows_scraped": len(listings),
                    "rows_inserted": count,
                    "rows_updated": 0,
                })
            else:
                logger.warning(
                    "No Yad2 listings scraped — session may be missing/expired. "
                    "Run: python -m scanner.cli refresh-session --site yad2"
                )
                db["run_history"].insert({
                    "run_id": run_id,
                    "source": source,
                    "started_at": start_time,
                    "ended_at": datetime.now().isoformat(),
                    "status": "no_listings",
                    "rows_scraped": 0,
                    "rows_inserted": 0,
                    "rows_updated": 0,
                })

        except Exception as e:
            logger.error(f"Scrape failed: {e}", exc_info=True)
            db["run_history"].insert(
                {
                    "run_id": run_id,
                    "source": source,
                    "started_at": start_time,
                    "ended_at": datetime.now().isoformat(),
                    "status": "error",
                    "error_message": str(e),
                    "rows_scraped": 0,
                    "rows_inserted": 0,
                    "rows_updated": 0,
                }
            )
            sys.exit(1)

    elif source == "yad2_sold":
        try:
            transactions = asyncio.run(scrape_yad2_sold())
            if transactions:
                count = upsert_transactions(db, transactions)
                logger.info(f"Yad2 sold: inserted {count} transactions")
                db["run_history"].insert({
                    "run_id": run_id, "source": source, "city": None,
                    "started_at": start_time, "ended_at": datetime.now().isoformat(),
                    "status": "success", "rows_scraped": len(transactions),
                    "rows_inserted": count, "rows_updated": 0,
                })
            else:
                logger.warning("No Yad2 sold transactions — session may be expired.")
                db["run_history"].insert({
                    "run_id": run_id, "source": source, "city": None,
                    "started_at": start_time, "ended_at": datetime.now().isoformat(),
                    "status": "no_listings", "rows_scraped": 0,
                    "rows_inserted": 0, "rows_updated": 0,
                })
        except Exception as e:
            logger.error(f"yad2_sold scrape failed: {e}", exc_info=True)
            db["run_history"].insert({
                "run_id": run_id, "source": source, "city": None,
                "started_at": start_time, "ended_at": datetime.now().isoformat(),
                "status": "error", "error_message": str(e),
                "rows_scraped": 0, "rows_inserted": 0, "rows_updated": 0,
            })
            sys.exit(1)


@cli.command("refresh-session")
@click.option("--site", default="yad2", type=click.Choice(["yad2", "nadlan", "madlan"]), help="Site to refresh session for")
def refresh_session(site: str):
    """Open a headed browser window so you can solve the CAPTCHA once.
    Session is saved automatically — future scrapes run headless.
    """
    async def _run():
        from .scrapers.session_manager import get_context, save_session, close_all

        url = {
            "yad2": "https://www.yad2.co.il/realestate/forsale",
            "nadlan": "https://www.nadlan.gov.il/",
            "madlan": (
                "https://www.madlan.co.il/for-sale/"
                "%D7%AA%D7%9C-%D7%90%D7%91%D7%99%D7%91-%D7%99%D7%A4%D7%95-%D7%99%D7%A9%D7%A8%D7%90%D7%9C"
                "?tracking_search_source=new_search&marketplace=residential"
            ),
        }[site]

        click.echo(f"\nOpening {site} in a browser window.")
        click.echo("Please solve any CAPTCHA / verification that appears.")
        click.echo("Once the page loads normally, press ENTER here to save the session.\n")

        playwright, browser, context = await get_context(site, headless=False, force_fresh=True)
        try:
            page = await context.new_page()
            await page.goto(url, wait_until="domcontentloaded", timeout=30000)
            # Wait for user confirmation in terminal
            await asyncio.get_event_loop().run_in_executor(None, input, "Press ENTER when the page is loaded and CAPTCHAs are solved: ")
            await save_session(context, site)
            click.echo(f"✅ Session saved for {site}. Future scrapes will be headless.")
        finally:
            await close_all(playwright, browser, context)

    asyncio.run(_run())


@cli.command()
@click.option("--db-path", default="data/apartments.db", help="Path to SQLite database")
@click.option("--config", default="config/search.yaml", help="Search criteria YAML file")
def alert(db_path: str, config: str):
    """Check for matching apartments and send alerts."""
    db_path = Path(db_path)
    config_path = Path(config)

    logger.info("Checking for matching apartments...")

    db = get_db(db_path)
    init_schema(db)

    # Load search criteria
    if not config_path.exists():
        logger.warning(f"Config file not found: {config_path}")
        return

    with open(config_path, encoding="utf-8") as f:
        config_data = yaml.safe_load(f)

    criteria = config_data.get("search_criteria", {})

    # Find matches
    matches = find_matching_listings(db, criteria)
    logger.info(f"Found {len(matches)} under-market listings")

    # Send alerts
    for listing in matches:
        status = send_listing_alert(listing, listing)
        if status:
            logger.info(f"Alert sent for: {listing['address']}")
        else:
            logger.warning(f"Failed to send alert for: {listing['address']}")

    if not matches:
        logger.info("No matching listings found")


@cli.command("scrape-pinui-binui")
@click.option("--db-path", default="data/apartments.db", help="Path to SQLite database")
def scrape_pinui_binui(db_path: str):
    """Scrape פינוי בינוי zones from MOCH ArcGIS."""
    from .scrapers.pinui_binui import scrape_pinui_binui as _scrape

    db = get_db(db_path)
    init_schema(db)

    started = datetime.now().isoformat()
    run_id = f"{started}_pinui_binui"
    t0 = _time.time()
    logger.info("Fetching פינוי בינוי zones...")
    try:
        zones = _scrape()
        inserted = upsert_pinui_binui_zones(db, zones)
        # Record a run_history row so the heartbeat LED reflects freshness.
        db["run_history"].insert({
            "run_id": run_id, "source": "pinui_binui", "city": None,
            "started_at": started, "ended_at": datetime.now().isoformat(),
            "status": "success",
            "rows_scraped": len(zones), "rows_inserted": inserted, "rows_updated": 0,
            "error_message": None, "elapsed_seconds": _time.time() - t0,
            "captcha_detected": 0, "pid": os.getpid(),
        })
        click.echo(f"Upserted {inserted} פינוי בינוי zones.")
    except Exception as e:
        db["run_history"].insert({
            "run_id": run_id, "source": "pinui_binui", "city": None,
            "started_at": started, "ended_at": datetime.now().isoformat(),
            "status": "error", "rows_scraped": 0, "rows_inserted": 0, "rows_updated": 0,
            "error_message": str(e), "elapsed_seconds": _time.time() - t0,
            "captcha_detected": 0, "pid": os.getpid(),
        })
        raise


@cli.command()
@click.option("--db-path", default="data/apartments.db", help="Path to SQLite database")
def stats(db_path: str):
    """Show database statistics."""
    db = get_db(db_path)
    init_schema(db)

    click.echo("\n=== Database Statistics ===\n")

    txn_count = db.execute("SELECT COUNT(*) FROM transactions").fetchone()[0]
    listing_count = db.execute("SELECT COUNT(*) FROM listings").fetchone()[0]
    run_count = db.execute("SELECT COUNT(*) FROM run_history").fetchone()[0]

    click.echo(f"Transactions:  {txn_count:,}")
    click.echo(f"Listings:      {listing_count:,}")
    click.echo(f"Scrape runs:   {run_count:,}")

    # Latest run
    latest_run = db.execute(
        "SELECT run_id, started_at, status FROM run_history ORDER BY started_at DESC LIMIT 1"
    ).fetchone()
    if latest_run:
        click.echo(f"\nLatest run: {latest_run[1]} ({latest_run[2]})")


if __name__ == "__main__":
    cli()
