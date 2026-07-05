"""Scraper for Yad2.co.il apartment listings.

Strategy:
  1. Try the internal gw.yad2.co.il JSON API directly (fast, no rendering).
  2. If blocked, fall back to Playwright + playwright-stealth (intercept XHR).

Session is saved to data/sessions/yad2.json and reused across runs.
When expired, the browser opens headed to refresh it automatically.
"""
import asyncio
import json
import logging
from datetime import datetime
from pathlib import Path
from typing import Any

import httpx

from .session_manager import get_context, save_session, close_all

logger = logging.getLogger(__name__)

# Yad2 map API — returns up to 200 markers per bounding box
YAD2_MAP_API = "https://gw.yad2.co.il/realestate-feed/forsale/map"

# Yad2 uses distinct URL slugs + dealType codes for sale vs rent. The rest of
# the scrape (map tiles, pageProps extraction, normalisation) is identical.
DEAL_FEEDS = {"sale": "forsale", "rent": "rent"}
DEAL_PARAM = {"sale": "1", "rent": "2"}

# Israel bounding box tiles (lat_min, lon_min, lat_max, lon_max)
# Split into 9 tiles to stay under 200-marker limit per tile
ISRAEL_TILES = [
    # North
    (32.6, 34.8, 33.3, 35.9),
    (32.6, 34.2, 33.3, 34.8),
    # Center-North (Haifa / Sharon)
    (32.1, 34.8, 32.6, 35.3),
    (32.1, 34.2, 32.6, 34.8),
    # Center (Gush Dan / Jerusalem area)
    (31.7, 34.7, 32.1, 35.3),
    (31.7, 34.2, 32.1, 34.7),
    # South
    (31.0, 34.4, 31.7, 35.3),
    (30.0, 34.4, 31.0, 35.5),
    (29.5, 34.6, 30.0, 35.5),
]

# Standard browser headers
BROWSER_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/124.0.0.0 Safari/537.36"
    ),
    "Accept": "application/json, text/plain, */*",
    "Accept-Language": "he-IL,he;q=0.9,en-US;q=0.8",
    "Referer": "https://www.yad2.co.il/realestate/forsale",
    "Origin": "https://www.yad2.co.il",
}


class Yad2Scraper:
    """Scrape apartment listings from Yad2."""

    def __init__(self, raw_snapshot_dir: Path | None = None, deal_type: str = "sale"):
        self.raw_snapshot_dir = raw_snapshot_dir
        self.deal_type = deal_type if deal_type in DEAL_FEEDS else "sale"
        self.feed = DEAL_FEEDS[self.deal_type]           # "forsale" | "rent"
        self.deal_param = DEAL_PARAM[self.deal_type]      # "1" | "2"
        self.map_api = f"https://gw.yad2.co.il/realestate-feed/{self.feed}/map"

    async def scrape(
        self,
        city: str = "",
        rooms_min: int | None = None,
        rooms_max: int | None = None,
        price_max: int | None = None,
        max_pages: int = 20,
    ) -> list[dict[str, Any]]:
        """Scrape listings: map API tiles first, then Playwright page extraction."""
        # 1. Try map API directly with session cookies (fastest, no browser)
        listings = await self._try_map_api()
        if listings:
            logger.info(f"Map API succeeded: {len(listings)} listings")
            return listings

        # 2. Fallback: Playwright — navigate search page and extract pageProps.feed
        logger.info("Map API blocked — falling back to Playwright page extraction")
        listings = await self._playwright_scrape(city, rooms_min, rooms_max, price_max, max_pages)
        return listings

    # ── Map API (tiles across Israel) ────────────────────────────────────────

    def _load_cookies(self) -> dict:
        session_file = Path("data/sessions/yad2.json")
        if not session_file.exists():
            return {}
        try:
            state = json.loads(session_file.read_text(encoding="utf-8"))
            return {c["name"]: c["value"] for c in state.get("cookies", [])}
        except Exception:
            return {}

    async def _try_map_api(self) -> list[dict]:
        """Call gw.yad2.co.il map endpoint for each Israel tile."""
        cookies = self._load_cookies()
        if not cookies:
            logger.info("No saved session — skipping map API")
            return []

        all_listings: list[dict] = []
        seen_ids: set[str] = set()

        async with httpx.AsyncClient(
            headers=BROWSER_HEADERS,
            cookies=cookies,
            follow_redirects=True,
            timeout=20,
        ) as client:
            for i, (lat_min, lon_min, lat_max, lon_max) in enumerate(ISRAEL_TILES):
                bbox = f"{lat_min},{lon_min},{lat_max},{lon_max}"
                params = {"bBox": bbox, "propertyGroup": "apartments", "dealType": self.deal_param}
                try:
                    resp = await client.get(self.map_api, params=params)
                except httpx.RequestError as e:
                    logger.error(f"Map API tile {i} request error: {e}")
                    continue

                if resp.status_code in (403, 429, 503):
                    logger.warning(f"Map API blocked ({resp.status_code}) — need Playwright")
                    return []

                ct = resp.headers.get("content-type", "")
                if resp.status_code != 200 or "json" not in ct:
                    logger.warning(f"Map API tile {i}: status={resp.status_code} ct={ct[:40]}")
                    return []

                try:
                    data = resp.json()
                except Exception:
                    logger.warning(f"Map API tile {i}: non-JSON response")
                    return []

                raw = data.get("data", {})
                markers = raw.get("markers", []) + raw.get("agencyPromotions", [])
                batch = []
                for item in markers:
                    norm = self._normalize_map_item(item)
                    if norm and norm.get("price") and norm["id"] not in seen_ids:
                        seen_ids.add(norm["id"])
                        batch.append(norm)

                logger.info(f"  Tile {i+1}/{len(ISRAEL_TILES)} bbox={bbox}: {len(batch)} listings")
                all_listings.extend(batch)
                await asyncio.sleep(1.0)

        if self.raw_snapshot_dir and all_listings:
            self._save_snapshot(all_listings, "map_api")

        return all_listings

    # ── Playwright fallback ───────────────────────────────────────────────────

    async def _playwright_scrape(
        self, city, rooms_min, rooms_max, price_max, max_pages
    ) -> list[dict]:
        """Navigate Yad2 search page and extract listings from pageProps.feed."""
        apply_stealth = None
        try:
            from playwright_stealth import Stealth  # v2
            _stealth_obj = Stealth()
            async def apply_stealth(page):
                await _stealth_obj.apply_stealth_async(page)
        except ImportError:
            try:
                from playwright_stealth import stealth_async  # v1
                apply_stealth = stealth_async
            except ImportError:
                logger.warning("playwright-stealth not installed; running without stealth")

        all_listings: list[dict] = []
        # Use city code to get search results page (not lobby)
        city_code = getattr(self, "_city_code", 5000)
        search_url = f"https://www.yad2.co.il/realestate/{self.feed}?city={city_code}"
        if city:
            search_url = self._build_search_url(city, rooms_min, rooms_max, price_max)

        for headless in [True, False]:
            playwright, browser, context = await get_context(
                "yad2", headless=headless, force_fresh=False
            )
            try:
                page = await context.new_page()
                if apply_stealth:
                    await apply_stealth(page)

                # Also capture map API responses that fire client-side
                map_items: list[dict] = []

                async def handle_map_response(response):
                    if "realestate-feed" in response.url and response.status == 200:
                        try:
                            data = await response.json()
                            raw = data.get("data", {})
                            markers = raw.get("markers", []) + raw.get("agencyPromotions", [])
                            for item in markers:
                                norm = self._normalize_map_item(item)
                                if norm and norm.get("price"):
                                    map_items.append(norm)
                            if markers:
                                logger.info(f"  Map XHR: {len(markers)} markers from {response.url[:80]}")
                        except Exception:
                            pass

                page.on("response", handle_map_response)

                logger.info(f"  Opening ({'headless' if headless else 'headed'}): {search_url}")
                await page.goto(search_url, wait_until="networkidle", timeout=45000)
                await page.wait_for_timeout(3000)

                # Detect CAPTCHA / session-expired page
                current_url = page.url
                if any(d in current_url.lower() for d in ("perfdrive.com", "captcha", "challenge")):
                    logger.warning(f"  CAPTCHA detected (headless={headless}): {current_url[:80]}")
                    if headless:
                        try:
                            from .captcha_vnc import send_screenshot_alert
                            await send_screenshot_alert(page, "yad2")
                        except Exception as e:
                            logger.warning(f"screenshot alert failed: {e}")
                    continue

                # Extract from pageProps.feed (SSR embedded data)
                batch = await self._extract_feed_from_props(page)
                if batch:
                    all_listings.extend(batch)
                    logger.info(f"  pageProps.feed: {len(batch)} listings")

                # Add any map API calls that fired
                if map_items:
                    seen = {l["id"] for l in all_listings}
                    new_map = [m for m in map_items if m["id"] not in seen]
                    all_listings.extend(new_map)
                    logger.info(f"  Map XHR total: {len(new_map)} additional listings")

                if all_listings:
                    await save_session(context, "yad2")
                    break

                logger.warning(f"No listings captured ({'headless' if headless else 'headed'} mode)")

            finally:
                await close_all(playwright, browser, context)

        if self.raw_snapshot_dir and all_listings:
            self._save_snapshot(all_listings, "playwright")

        return all_listings

    async def _extract_feed_from_props(self, page) -> list[dict]:
        """Extract listings from pageProps.feed (set when navigating a search URL)."""
        try:
            next_data = await page.evaluate("""() => {
                const el = document.getElementById('__NEXT_DATA__');
                return el ? JSON.parse(el.textContent) : null;
            }""")
            if not next_data:
                return []
            props = next_data.get("props", {}).get("pageProps", {})
            feed = props.get("feed", {})
            if not isinstance(feed, dict):
                return []

            # Collect listings from all feed categories
            raw_items = []
            for key in ("private", "agency", "platinum", "booster"):
                items = feed.get(key, [])
                if isinstance(items, list):
                    raw_items.extend(items)

            results = []
            seen: set[str] = set()
            for item in raw_items:
                norm = self._normalize_map_item(item)
                if norm and norm.get("price") and norm["id"] not in seen:
                    seen.add(norm["id"])
                    results.append(norm)
            return results
        except Exception as e:
            logger.warning(f"pageProps.feed extraction error: {e}")
            return []

    def _find_feed_items(self, data: dict, depth: int = 0) -> list:
        """Recursively search a dict for feed_items."""
        if depth > 5:
            return []
        if "feed_items" in data:
            return data["feed_items"]
        for v in data.values():
            if isinstance(v, dict):
                result = self._find_feed_items(v, depth + 1)
                if result:
                    return result
            elif isinstance(v, list) and v and isinstance(v[0], dict):
                # Check if it looks like a list of listings
                if any(k in v[0] for k in ("price", "id", "rooms", "orderId")):
                    return v
        return []

    def _extract_from_dehydrated_state(self, dehydrated: dict) -> list[dict]:
        """Search React Query dehydratedState.queries for feed items."""
        queries = dehydrated.get("queries", [])
        logger.info(f"  dehydratedState: {len(queries)} queries cached")
        for q in queries:
            state_data = q.get("state", {}).get("data")
            if state_data is None:
                qk = str(q.get("queryKey", ""))[:80]
                logger.info(f"  query has no data yet (client-side fetch): key={qk}")
                continue
            # Could be nested in pages (infinite query) or flat
            pages = state_data.get("pages", [state_data]) if isinstance(state_data, dict) else []
            for page_data in pages:
                if not isinstance(page_data, dict):
                    continue
                items = (
                    page_data.get("data", {}).get("feed", {}).get("feed_items", [])
                    or page_data.get("feed", {}).get("feed_items", [])
                    or page_data.get("feed_items", [])
                )
                if items:
                    logger.info(f"  Found {len(items)} feed_items in query '{q.get('queryKey', '')}'")
                    return items
            qk = str(q.get("queryKey", ""))[:60]
            sd_keys = list(state_data.keys())[:5] if isinstance(state_data, dict) else type(state_data).__name__
            logger.info(f"  query key={qk} state.data keys={sd_keys}")
        return []

    async def _extract_next_data(self, page) -> list[dict]:
        """Extract listings embedded in Next.js __NEXT_DATA__ script tag."""
        try:
            next_data_json = await page.evaluate("""() => {
                const el = document.getElementById('__NEXT_DATA__');
                return el ? el.textContent : null;
            }""")
            if not next_data_json:
                logger.info("__NEXT_DATA__: not found on page")
                return []

            data = json.loads(next_data_json)
            props = data.get("props", {}).get("pageProps", {})
            logger.info(f"__NEXT_DATA__ pageProps keys: {list(props.keys())[:15]}")

            # Try several known paths
            feed_items = (
                props.get("initialData", {}).get("data", {}).get("feed", {}).get("feed_items", [])
                or props.get("data", {}).get("feed", {}).get("feed_items", [])
                or props.get("feed", {}).get("feed_items", [])
                or props.get("initialData", {}).get("feed_items", [])
                or props.get("feedItems", [])
            )

            if not feed_items:
                # Yad2 uses React Query — data lives in dehydratedState.queries
                feed_items = self._extract_from_dehydrated_state(
                    props.get("dehydratedState", {})
                )

            if not feed_items:
                # Dig one level deeper and log all nested keys to find the data
                for k, v in props.items():
                    if isinstance(v, dict):
                        logger.info(f"  pageProps['{k}'] keys: {list(v.keys())[:10]}")
                    elif isinstance(v, list) and v:
                        logger.info(f"  pageProps['{k}']: list of {len(v)}")
                return []

            logger.info(f"  Found {len(feed_items)} raw items in __NEXT_DATA__")
            batch = [self._normalize_api_listing(item) for item in feed_items]
            return [b for b in batch if b and b.get("price")]

        except Exception as e:
            logger.warning(f"__NEXT_DATA__ extraction error: {e}")
            return []

    async def _try_xhr_on_page(self, page) -> list[dict]:
        """Wait for any feed-related XHR/fetch that fires after page load."""
        captured: list[dict] = []
        api_urls_seen: list[str] = []

        async def handle_response(response):
            url = response.url
            ct = response.headers.get("content-type", "")
            if "_next/static" in url or "outbrain" in url or "google" in url:
                return  # skip static assets and trackers
            status = response.status
            api_urls_seen.append(f"[{status}] {url[:120]}")
            if status == 200 and "json" in ct:
                try:
                    data = await response.json()
                    if not isinstance(data, dict):
                        return
                    items = self._find_feed_items(data)
                    if items:
                        batch = [self._normalize_api_listing(i) for i in items]
                        captured.extend([b for b in batch if b and b.get("price")])
                        logger.info(f"  XHR captured {len(items)} items from {url[:80]}")
                except Exception:
                    pass

        page.on("response", handle_response)
        # Wait for React Query client-side fetch
        await page.wait_for_timeout(3000)
        title = await page.title()
        current_url = page.url
        logger.info(f"  Page title: '{title}' | URL: {current_url[:100]}")
        await page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
        await page.wait_for_timeout(6000)

        if api_urls_seen:
            logger.info("All API calls seen:\n  " + "\n  ".join(api_urls_seen[:30]))
        else:
            logger.info("No API calls detected after page load")

        return captured

    def _build_search_url(self, city, rooms_min, rooms_max, price_max) -> str:
        base = f"https://www.yad2.co.il/realestate/{self.feed}"
        parts = []
        if city:
            parts.append(f"city={city}")
        if rooms_min:
            parts.append(f"rooms={rooms_min}-{rooms_max or 10}")
        if price_max:
            parts.append(f"price=0-{price_max}")
        return base + ("?" + "&".join(parts) if parts else "")

    # ── Normalisation ─────────────────────────────────────────────────────────

    def _normalize_map_item(self, item: dict) -> dict | None:
        """Normalize a Yad2 map marker / pageProps.feed item to our schema."""
        try:
            addr = item.get("address", {})
            street = addr.get("street", {}).get("text", "")
            house_num = addr.get("house", {}).get("number", "")
            floor = _safe_int(addr.get("house", {}).get("floor"))
            city_text = addr.get("city", {}).get("text", "")
            coords = addr.get("coords", {})
            lat = _safe_float(coords.get("lat"))
            lon = _safe_float(coords.get("lon"))

            details = item.get("additionalDetails", {})
            sqm = _safe_float(details.get("squareMeter"))
            rooms = _safe_float(details.get("roomsCount"))

            price = _parse_price(item.get("price", 0))
            token = item.get("token", "")
            order_id = str(item.get("orderId", token))

            meta = item.get("metaData", {})
            posted_at = meta.get("date", datetime.now().isoformat())

            now = datetime.now().isoformat()
            return {
                "id": order_id,
                "title": "",
                "address": f"{street} {house_num}".strip(),
                "city": city_text,
                "rooms": int(rooms) if rooms else None,
                "sqm": sqm,
                "floor": floor,
                "price": price,
                "price_per_sqm": round(price / sqm) if price and sqm else None,
                "url": f"https://www.yad2.co.il/realestate/item/{token}",
                "posted_at": posted_at,
                "gush": None,
                "lat": lat,
                "lon": lon,
                "last_seen": now,
                "is_active": True,
                "deal_type": self.deal_type,
            }
        except Exception as e:
            logger.debug(f"Map normalization error: {e}")
            return None

    def _normalize_api_listing(self, item: dict) -> dict | None:
        """Normalize one Yad2 feed item (old format) to our schema."""
        try:
            if item.get("type") in ("promotion", "commercial_promotion"):
                return None
            # Try new map format first
            if "additionalDetails" in item or "address" in item and isinstance(item.get("address"), dict) and "coords" in item.get("address", {}):
                return self._normalize_map_item(item)

            price_raw = item.get("price", "")
            price = _parse_price(price_raw)
            sqm_raw = item.get("square_meters", item.get("Squaremeter", 0))
            sqm = _safe_float(sqm_raw)

            address = item.get("address", {})
            street = address.get("street", {}).get("text", "")
            house = address.get("house_number", "")
            city = address.get("city", {}).get("text", "")

            lat = _safe_float(item.get("coordinates", {}).get("latitude"))
            lon = _safe_float(item.get("coordinates", {}).get("longitude"))

            rooms_raw = item.get("rooms", item.get("Rooms_text", ""))
            rooms = _parse_rooms(rooms_raw)

            now = datetime.now().isoformat()
            return {
                "id": str(item.get("id", item.get("orderId", ""))),
                "title": item.get("title_1", item.get("title", "")),
                "address": f"{street} {house}".strip(),
                "city": city,
                "rooms": rooms,
                "sqm": sqm,
                "floor": _safe_int(item.get("floor", item.get("Floor"))),
                "price": price,
                "price_per_sqm": round(price / sqm) if price and sqm else None,
                "url": f"https://www.yad2.co.il/realestate/item/{item.get('id', '')}",
                "posted_at": item.get("date_added", now),
                "gush": None,
                "lat": lat,
                "lon": lon,
                "last_seen": now,
                "is_active": True,
            }
        except Exception as e:
            logger.debug(f"Normalization error: {e}")
            return None

    def _save_snapshot(self, listings: list, source: str) -> None:
        if not self.raw_snapshot_dir:
            return
        snap_dir = self.raw_snapshot_dir / "yad2" / datetime.now().strftime("%Y-%m-%d")
        snap_dir.mkdir(parents=True, exist_ok=True)
        snap_file = snap_dir / f"listings_{source}_{datetime.now().strftime('%H%M%S')}.json"
        snap_file.write_text(json.dumps(listings, ensure_ascii=False, indent=2), encoding="utf-8")


# ── Helpers ───────────────────────────────────────────────────────────────────

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


def _parse_price(val) -> int:
    """Parse price — may be int, float, or formatted string like '2,500,000'."""
    if isinstance(val, (int, float)):
        return int(val)
    if isinstance(val, str):
        clean = val.replace(",", "").replace("₪", "").replace(" ", "")
        try:
            return int(float(clean))
        except ValueError:
            return 0
    return 0


def _parse_rooms(val) -> int | None:
    """Parse rooms — may be '3', '3.5', '4 חדרים' etc."""
    if isinstance(val, (int, float)):
        return int(val)
    if isinstance(val, str):
        import re
        m = re.search(r"(\d+(?:\.\d+)?)", val)
        if m:
            return int(float(m.group(1)))
    return None


# ── Public API ────────────────────────────────────────────────────────────────

# Major Israeli cities and their Yad2 city codes
# Note: codes < 1000 must be zero-padded strings (e.g. "0070" not 70)
CITY_CODES = {
    5000: "תל אביב",
    8600: "רמת גן",
    2800: "גבעתיים",
    3000: "ירושלים",
    4000: "חיפה",
    8300: "ראשון לציון",
    # 7900: "פתח תקווה",  # Disabled — consistently times out during Playwright page load (45s+)
    "0070": "אשדוד",
    7400: "נתניה",
    6300: "הרצליה",
    6900: "כפר סבא",
    8700: "רעננה",
    2300: "בת ים",
    2650: "בני ברק",
    8500: "רחובות",
    9000: "באר שבע",
}


async def scrape_yad2_listings(
    raw_snapshot_dir: Path | None = None, deal_type: str = "sale"
) -> list[dict]:
    """Scrape apartment listings across all major Israeli cities.

    deal_type: "sale" (asking prices, dealType=1) or "rent" (monthly rent,
    dealType=2). Every returned listing is tagged with ``deal_type`` so the same
    ``listings`` table holds both modes.
    """
    scraper = Yad2Scraper(raw_snapshot_dir=raw_snapshot_dir, deal_type=deal_type)
    all_listings: list[dict] = []
    seen_ids: set[str] = set()

    for city_code, city_name in CITY_CODES.items():
        logger.info(f"Scraping {city_name} [{deal_type}] (code={city_code})")
        # Override the search URL for each city
        scraper._city_code = city_code
        try:
            listings = await scraper.scrape(max_pages=50)
        except Exception as e:
            logger.warning(f"  {city_name}: scrape failed, skipping — {e}")
            await asyncio.sleep(2)
            continue
        new = [l for l in listings if l.get("id") and l["id"] not in seen_ids]
        seen_ids.update(l["id"] for l in new)
        all_listings.extend(new)
        logger.info(f"  {city_name}: {len(new)} new listings (total {len(all_listings)})")
        await asyncio.sleep(2)

    # Belt-and-suspenders: guarantee every row carries the mode regardless of
    # which internal extraction path produced it.
    for l in all_listings:
        l["deal_type"] = deal_type
    return all_listings


async def scrape_yad2_sold(
    max_pages_per_city: int = 100,
    limit_per_page: int = 100,
) -> list[dict]:
    """Scrape sold property transactions from Yad2's latest-deals-completed API.

    Uses saved session cookies (no Playwright needed).  Results are normalised
    to the ``transactions`` table schema so they can be upserted directly.
    """
    session_file = Path("data/sessions/yad2.json")
    cookies: dict[str, str] = {}
    if session_file.exists():
        data = json.loads(session_file.read_text(encoding="utf-8"))
        cookies = {c["name"]: c["value"] for c in data.get("cookies", []) if "yad2.co.il" in c.get("domain", "")}

    headers = {
        "User-Agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
        ),
        "Referer": "https://www.yad2.co.il/",
        "Accept": "application/json",
    }

    all_txns: list[dict] = []
    seen_ids: set[str] = set()
    now = datetime.now().isoformat()

    async with httpx.AsyncClient(headers=headers, cookies=cookies, timeout=20) as client:
        for city_code, city_name in CITY_CODES.items():
            city_txns = 0
            for page in range(1, max_pages_per_city + 1):
                try:
                    resp = await client.get(
                        "https://gw.yad2.co.il/latest-deals-completed/",
                        params={"limit": limit_per_page, "page": page, "city": city_code},
                    )
                except Exception as exc:
                    logger.warning("yad2_sold %s page %d: %s", city_name, page, exc)
                    break
                if resp.status_code in (401, 403):
                    logger.warning("yad2_sold %s: session expired (HTTP %d)", city_name, resp.status_code)
                    break
                if resp.status_code != 200:
                    logger.warning("yad2_sold %s page %d: HTTP %d", city_name, page, resp.status_code)
                    break
                try:
                    body = resp.json()
                except Exception:
                    break
                results = body.get("data", {}).get("results", [])
                if not results:
                    break
                for item in results:
                    txn = _normalize_sold(item, now)
                    if txn and txn["id"] not in seen_ids:
                        seen_ids.add(txn["id"])
                        all_txns.append(txn)
                        city_txns += 1
                pagination = body.get("data", {}).get("pagination", {})
                total_pages = pagination.get("totalPages", 1)
                if page >= total_pages:
                    break
                await asyncio.sleep(0.3)
            logger.info("yad2_sold %s: %d transactions", city_name, city_txns)

    logger.info("yad2_sold total: %d transactions across %d cities", len(all_txns), len(CITY_CODES))
    return all_txns


def _normalize_sold(item: dict, inserted_at: str) -> dict | None:
    """Normalise a latest-deals-completed result to the transactions schema."""
    try:
        addr = item.get("address", {})
        street = addr.get("street", {}).get("text", "")
        house_num = addr.get("houseNumber")
        address = f"{street} {house_num}".strip() if house_num else street
        city = addr.get("city", {}).get("text", "")
        sale_date_raw = item.get("saleDate", "")
        sale_date = sale_date_raw[:10] if sale_date_raw else None
        price = item.get("price")
        sqm = item.get("buildingMR")
        floor = item.get("floor")
        year_built = item.get("buildYear")
        rooms = item.get("rooms")
        address_master_id = addr.get("addressMasterId", "")
        if not (city and price and sale_date):
            return None
        # Stable unique key: building × date × price × floor (multiple units same day)
        uid = f"yad2sold_{address_master_id}_{sale_date}_{price}_{floor}"
        return {
            "id": uid,
            "address": address,
            "city": city,
            "rooms": int(rooms) if rooms is not None else None,
            "sqm": float(sqm) if sqm else None,
            "floor": int(floor) if floor is not None else None,
            "year_built": int(year_built) if year_built else None,
            "price": int(price),
            "date": sale_date,
            "gush": None,
            "lat": None,
            "lon": None,
            "inserted_at": inserted_at,
        }
    except Exception:
        return None


def get_mock_listings() -> list[dict[str, Any]]:
    """Return mock listing data for testing."""
    posted_time = datetime.now().isoformat()

    def listing(id_, title, address, city, rooms, sqm, floor, price, lat, lon, url_id):
        return {
            "id": f"yad2_{id_}", "title": title, "address": address, "city": city,
            "rooms": rooms, "sqm": sqm, "floor": floor, "price": price,
            "price_per_sqm": round(price / sqm),
            "url": f"https://yad2.co.il/realestate/item/{url_id}",
            "posted_at": posted_time, "gush": None,
            "lat": lat, "lon": lon, "last_seen": posted_time, "is_active": True,
        }

    return [
        listing(1, "דירת 4 חדרים הרצל", "הרצל 23", "תל אביב", 4, 120.0, 3, 2800000, 32.0597, 34.7713, 1),
        listing(2, "3 חדרים בן גוריון", "בן גוריון 50", "תל אביב", 3, 85.0, 5, 1950000, 32.0878, 34.7813, 2),
        listing(3, "פנטהאוס דיזנגוף", "דיזנגוף 100", "תל אביב", 5, 150.0, 7, 4500000, 32.0784, 34.7745, 3),
        listing(4, "4 חדרים רוטשילד", "רוטשילד 90", "תל אביב", 4, 108.0, 2, 3900000, 32.0656, 34.7737, 4),
        listing(5, "3 חדרים פלורנטין", "שלוש 15", "תל אביב", 3, 72.0, 1, 1680000, 32.0545, 34.7680, 5),
        listing(6, "4 חדרים ביאליק", "ביאליק 12", "רמת גן", 4, 105.0, 2, 2100000, 32.0834, 34.8126, 6),
        listing(7, "3 חדרים ז'בוטינסקי", "ז'בוטינסקי 50", "רמת גן", 3, 78.0, 4, 1650000, 32.0797, 34.8092, 7),
        listing(8, "4 חדרים עמק רפאים", "עמק רפאים 22", "ירושלים", 4, 115.0, 3, 3400000, 31.7643, 35.2160, 8),
        listing(9, "3 חדרים יפו", "יפו 60", "ירושלים", 3, 90.0, 2, 1900000, 31.7837, 35.2125, 9),
        listing(10, "4 חדרים סוקולוב", "סוקולוב 30", "הרצליה", 4, 130.0, 5, 2750000, 32.1642, 34.8438, 10),
        listing(11, "3 חדרים הרצל חיפה", "הרצל 45", "חיפה", 3, 80.0, 3, 1050000, 32.8156, 34.9891, 11),
    ]
