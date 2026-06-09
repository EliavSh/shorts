"""Scraper for nadlan.gov.il — actual apartment transaction prices.

Strategy: Playwright headless browser. Navigate to a city's deals view,
intercept the POST /deal-data XHR response (gzip+base64 encoded),
decode and parse into our transaction schema.

No login or manual steps required. reCAPTCHA runs silently in the browser.
"""
import asyncio
import base64
import gzip
import json
import logging
from datetime import datetime
from pathlib import Path
from typing import Any

from playwright.async_api import async_playwright, Route, Request

from .session_manager import get_context, save_session, close_all

logger = logging.getLogger(__name__)

# City → internal nadlan settlement code (CBS yishuv codes)
CITY_CODES = {
    # Major cities
    "תל אביב": 5000,
    "ירושלים": 3000,
    "חיפה": 4000,
    "באר שבע": 1024,
    # Gush Dan
    "ראשון לציון": 8300,
    "פתח תקווה": 7900,
    "בני ברק": 2650,
    "רמת גן": 8600,
    "גבעתיים": 2800,
    "בת ים": 2300,
    "חולון": 6400,
    "אור יהודה": 345,
    "קריית אונו": 6700,
    "גני תקווה": 2960,
    # Sharon / Center
    "הרצליה": 6300,
    "כפר סבא": 6900,
    "רעננה": 8700,
    "הוד השרון": 6200,
    "ראש העין": 8220,
    "נס ציונה": 7300,
    "רחובות": 8500,
    "לוד": 7000,
    "רמלה": 8400,
    "מודיעין": 8200,
    "יבנה": 6500,
    # Netanya / North center
    "נתניה": 7400,
    "אשדוד": 7100,   # CBS code 7100; note: code 70 returned 0 — may still need verification
    "אשקלון": 200,
    # North
    "נצרת עילית": 7800,
    "עפולה": 7700,
    "עכו": 400,
    "נהריה": 7100,
    "קריית אתא": 7600,
    "קריית ביאליק": 7660,
    "קריית מוצקין": 7680,
}


def _decode_response(raw: str) -> dict:
    """Decode the gzip+base64 response from nadlan API."""
    try:
        # Try JSON first (some responses are plain JSON)
        return json.loads(raw)
    except (json.JSONDecodeError, ValueError):
        pass

    try:
        # Decode base64 → decompress gzip → JSON
        compressed = base64.b64decode(raw)
        decompressed = gzip.decompress(compressed)
        return json.loads(decompressed.decode("utf-8"))
    except Exception as e:
        logger.error(f"Failed to decode response: {e}")
        return {}


def _normalize_transaction(item: dict) -> dict:
    """Normalize one nadlan transaction record to our schema."""
    # Handle date — format varies: "DD/MM/YYYY" or "YYYY-MM-DD"
    raw_date = item.get("DEALDATETIME", item.get("dealDate", ""))
    try:
        if "/" in raw_date:
            dt = datetime.strptime(raw_date[:10], "%d/%m/%Y")
        else:
            dt = datetime.strptime(raw_date[:10], "%Y-%m-%d")
        date_str = dt.strftime("%Y-%m-%d")
    except (ValueError, TypeError):
        date_str = raw_date[:10] if raw_date else ""

    # Extract coordinates (ITM → WGS84 conversion not needed; nadlan returns WGS84)
    lat = item.get("LATITUDE") or item.get("lat")
    lon = item.get("LONGITUDE") or item.get("lon")

    return {
        "id": str(item.get("OBJECTID", item.get("id", ""))),
        "address": f"{item.get('STREET_NM', '')} {item.get('HOUSE_NM', '')}".strip(),
        "city": item.get("SETTLEMENT_NM", item.get("city", "")),
        "rooms": _safe_int(item.get("ROOM_NUM", item.get("rooms"))),
        "sqm": _safe_float(item.get("AREA", item.get("sqm"))),
        "floor": _safe_int(item.get("FLOOR_NUM", item.get("floor"))),
        "year_built": _safe_int(item.get("YEAR_BUILT_TXT", item.get("yearBuilt"))),
        "price": _safe_int(item.get("FULL_PRICE", item.get("price", 0))),
        "date": date_str,
        "gush": item.get("GUSH", item.get("gush")),
        "lat": _safe_float(lat),
        "lon": _safe_float(lon),
        "inserted_at": datetime.now().isoformat(),
    }


def _safe_int(val) -> int | None:
    try:
        v = int(float(str(val).replace(",", "")))
        return v if v != 0 else None
    except (TypeError, ValueError):
        return None


def _safe_float(val) -> float | None:
    try:
        v = float(str(val).replace(",", ""))
        return v if v != 0.0 else None
    except (TypeError, ValueError):
        return None


class NadlanScraper:
    """Scrape actual sale prices from nadlan.gov.il via Playwright."""

    def __init__(self, raw_snapshot_dir: Path | None = None):
        self.raw_snapshot_dir = raw_snapshot_dir

    async def scrape_city(
        self, city_name: str, since_date: str | None = None
    ) -> list[dict[str, Any]]:
        """Scrape all transactions for a city."""
        city_code = CITY_CODES.get(city_name)
        if not city_code:
            logger.warning(f"Unknown city: {city_name}")
            return []

        logger.info(f"Scraping nadlan for {city_name} (code={city_code})")

        captured: list[dict] = []
        last_count = -1   # for scroll-pagination idle detection

        playwright, browser, context = await get_context("nadlan", headless=True)

        try:
            page = await context.new_page()

            # Intercept the deal-data API responses (Sprint 3.c: collect ALL pages,
            # not just the first one — every scroll triggers a new XHR)
            async def handle_response(response):
                if "/deal-data" in response.url and response.status == 200:
                    try:
                        raw = await response.text()
                        data = _decode_response(raw)
                        items = (
                            data.get("data", {}).get("items", [])
                            if isinstance(data, dict)
                            else []
                        )
                        if items:
                            logger.info(f"  Captured page: {len(items)} transactions (total {len(captured) + len(items)})")
                            captured.extend(items)
                    except Exception as e:
                        logger.error(f"Error parsing deal-data response: {e}")

            page.on("response", handle_response)

            # Navigate to the city's deals page
            url = f"https://www.nadlan.gov.il/?view=deals&id={city_code}"
            logger.info(f"  Opening: {url}")
            await page.goto(url, wait_until="domcontentloaded", timeout=30000)
            await page.wait_for_timeout(4000)  # initial XHR settles

            # Sprint 3.c — paginate by scrolling the deals list. Stop when 2 consecutive
            # scrolls add zero rows (idle), or after MAX_SCROLLS as a hard cap.
            MAX_SCROLLS = 40
            idle_streak = 0
            for i in range(MAX_SCROLLS):
                prev = len(captured)
                # Scroll the body and dispatch wheel events to trigger lazy load
                try:
                    await page.evaluate("window.scrollBy(0, 1500)")
                    await page.keyboard.press("End")
                except Exception:
                    pass
                await page.wait_for_timeout(2500)
                added = len(captured) - prev
                if since_date and any(
                    (it.get("DEALDATETIME") or "")[:10] < since_date for it in captured[-(added or 1):]
                ):
                    logger.info(f"  Reached since_date watermark, stopping at page {i+1}")
                    break
                if added == 0:
                    idle_streak += 1
                    if idle_streak >= 2:
                        logger.info(f"  No new rows for 2 scrolls, stopping at page {i+1}")
                        break
                else:
                    idle_streak = 0

            # Save updated session
            await save_session(context, "nadlan")

        finally:
            await close_all(playwright, browser, context)

        # Normalize
        transactions = [_normalize_transaction(item) for item in captured]
        transactions = [t for t in transactions if t["price"] and t["price"] > 0]

        # Filter by since_date if provided
        if since_date and transactions:
            transactions = [t for t in transactions if t["date"] >= since_date]

        # Save raw snapshot
        if self.raw_snapshot_dir and captured:
            snap_dir = self.raw_snapshot_dir / "nadlan" / datetime.now().strftime("%Y-%m-%d")
            snap_dir.mkdir(parents=True, exist_ok=True)
            snap_file = snap_dir / f"{city_name}.json"
            snap_file.write_text(
                json.dumps(captured, ensure_ascii=False, indent=2), encoding="utf-8"
            )

        logger.info(f"  Done: {len(transactions)} transactions for {city_name}")
        return transactions


async def scrape_nadlan_cities(
    cities: list[str],
    since_date: str | None = None,
    raw_snapshot_dir: Path | None = None,
) -> list[dict]:
    """Scrape nadlan for multiple cities sequentially."""
    scraper = NadlanScraper(raw_snapshot_dir=raw_snapshot_dir)
    all_transactions = []
    for city in cities:
        txns = await scraper.scrape_city(city, since_date=since_date)
        all_transactions.extend(txns)
        await asyncio.sleep(2)  # be polite between cities
    return all_transactions


# Keep these for CLI compatibility
async def scrape_nadlan_full(cities, raw_snapshot_dir=None):
    return await scrape_nadlan_cities(cities, raw_snapshot_dir=raw_snapshot_dir)


async def scrape_nadlan_incremental(cities, since_date, raw_snapshot_dir=None):
    return await scrape_nadlan_cities(cities, since_date=since_date, raw_snapshot_dir=raw_snapshot_dir)


def get_mock_transactions() -> list[dict[str, Any]]:
    """Return mock transaction data (used when real scraping is skipped)."""
    today = datetime.now().strftime("%Y-%m-%d")
    inserted = datetime.now().isoformat()
    return [
        {"id": "nadlan_1", "address": "הרצל 23", "city": "תל אביב", "rooms": 4, "sqm": 120.0, "floor": 3, "year_built": 1990, "price": 2500000, "date": today, "gush": None, "lat": 32.0597, "lon": 34.7713, "inserted_at": inserted},
        {"id": "nadlan_2", "address": "בן גוריון 50", "city": "תל אביב", "rooms": 3, "sqm": 85.0, "floor": 5, "year_built": 2005, "price": 1800000, "date": today, "gush": None, "lat": 32.0878, "lon": 34.7813, "inserted_at": inserted},
        {"id": "nadlan_3", "address": "דיזנגוף 100", "city": "תל אביב", "rooms": 5, "sqm": 150.0, "floor": 2, "year_built": 1985, "price": 3200000, "date": today, "gush": None, "lat": 32.0784, "lon": 34.7745, "inserted_at": inserted},
        {"id": "nadlan_4", "address": "רוטשילד 90", "city": "תל אביב", "rooms": 4, "sqm": 110.0, "floor": 4, "year_built": 1935, "price": 4100000, "date": today, "gush": None, "lat": 32.0656, "lon": 34.7737, "inserted_at": inserted},
        {"id": "nadlan_5", "address": "ביאליק 12", "city": "רמת גן", "rooms": 4, "sqm": 105.0, "floor": 2, "year_built": 1975, "price": 2100000, "date": today, "gush": None, "lat": 32.0834, "lon": 34.8126, "inserted_at": inserted},
        {"id": "nadlan_6", "address": "ז'בוטינסקי 50", "city": "רמת גן", "rooms": 3, "sqm": 78.0, "floor": 6, "year_built": 2000, "price": 1650000, "date": today, "gush": None, "lat": 32.0797, "lon": 34.8092, "inserted_at": inserted},
        {"id": "nadlan_7", "address": "יפו 60", "city": "ירושלים", "rooms": 3, "sqm": 90.0, "floor": 1, "year_built": 1968, "price": 1950000, "date": today, "gush": None, "lat": 31.7837, "lon": 35.2125, "inserted_at": inserted},
        {"id": "nadlan_8", "address": "עמק רפאים 22", "city": "ירושלים", "rooms": 4, "sqm": 115.0, "floor": 3, "year_built": 1960, "price": 3500000, "date": today, "gush": None, "lat": 31.7643, "lon": 35.2160, "inserted_at": inserted},
        {"id": "nadlan_9", "address": "סוקולוב 30", "city": "הרצליה", "rooms": 4, "sqm": 130.0, "floor": 5, "year_built": 2010, "price": 2800000, "date": today, "gush": None, "lat": 32.1642, "lon": 34.8438, "inserted_at": inserted},
        {"id": "nadlan_10", "address": "הרצל 45", "city": "חיפה", "rooms": 3, "sqm": 80.0, "floor": 2, "year_built": 1980, "price": 1100000, "date": today, "gush": None, "lat": 32.8156, "lon": 34.9891, "inserted_at": inserted},
    ]
