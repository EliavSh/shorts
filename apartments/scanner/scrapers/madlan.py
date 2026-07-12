"""Scraper for Madlan.co.il apartment listings.

Strategy:
  1. Open a real browser via Playwright (headed; user solves PerimeterX CAPTCHA once).
  2. For each major Israeli city, subdivide its lat/lon bbox into a grid of
     Web Mercator zoom-18 tile chunks. Call `searchPoi` for each tile via the
     browser's own fetch (bypasses IP rate-limit since it uses the live session).
  3. Madlan returns up to ~150-300 bulletins per tile call.
  4. Save session after each city so progress survives crashes/closes.

Session file is created via the `refresh-session --site madlan` CLI command.
"""
import asyncio
import json
import logging
import math
import re
import time
from datetime import datetime
from pathlib import Path
from typing import Any

import httpx

logger = logging.getLogger(__name__)

SESSION_FILE = Path("data/sessions/madlan.json")
BASE_URL = "https://www.madlan.co.il"
API_ENDPOINT = "https://www.madlan.co.il/api2"

# City docId → (lat_min, lon_min, lat_max, lon_max) bounding box (approximate).
# Used to derive Web Mercator zoom-18 tile coordinates for searchPoi pagination.
CITIES: dict[str, tuple[float, float, float, float]] = {
    "תל-אביב-יפו-ישראל":          (32.030, 34.740, 32.140, 34.850),
    "ירושלים-ישראל":               (31.700, 35.130, 31.840, 35.270),
    "חיפה-ישראל":                  (32.770, 34.940, 32.840, 35.060),
    "ראשון-לציון-ישראל":           (31.940, 34.730, 32.020, 34.830),
    "פתח-תקווה-ישראל":             (32.060, 34.860, 32.130, 34.940),
    "אשדוד-ישראל":                 (31.760, 34.620, 31.840, 34.700),
    "נתניה-ישראל":                 (32.260, 34.830, 32.360, 34.890),
    "באר-שבע-ישראל":               (31.200, 34.740, 31.290, 34.840),
    "חולון-ישראל":                 (32.000, 34.740, 32.040, 34.810),
    "בני-ברק-ישראל":               (32.070, 34.820, 32.110, 34.860),
    "רמת-גן-ישראל":                (32.060, 34.800, 32.100, 34.840),
    "אשקלון-ישראל":                (31.640, 34.520, 31.720, 34.610),
    "רחובות-ישראל":                (31.870, 34.780, 31.920, 34.840),
    "בת-ים-ישראל":                 (32.000, 34.730, 32.030, 34.770),
    "הרצליה-ישראל":                (32.140, 34.790, 32.200, 34.850),
    "כפר-סבא-ישראל":               (32.150, 34.870, 32.220, 34.940),
    "רעננה-ישראל":                 (32.160, 34.840, 32.210, 34.890),
    "גבעתיים-ישראל":               (32.060, 34.800, 32.090, 34.830),
    "מודיעין-מכבים-רעות-ישראל":    (31.880, 34.980, 31.940, 35.070),
}
CITY_DOCIDS = list(CITIES.keys())


def _lat_lon_to_tile(lat: float, lon: float, zoom: int = 18) -> tuple[int, int]:
    n = 2 ** zoom
    x = int((lon + 180.0) / 360.0 * n)
    lat_rad = math.radians(lat)
    y = int((1.0 - math.log(math.tan(lat_rad) + 1.0 / math.cos(lat_rad)) / math.pi) / 2.0 * n)
    return x, y


def _bbox_to_tile_grid(
    lat_min: float, lon_min: float, lat_max: float, lon_max: float,
    grid: int = 3, zoom: int = 18,
) -> list[dict[str, int]]:
    """Subdivide a lat/lon bbox into a `grid x grid` array of tile-range chunks."""
    x1_total, y2_total = _lat_lon_to_tile(lat_min, lon_min, zoom)  # SW corner: x small, y large
    x2_total, y1_total = _lat_lon_to_tile(lat_max, lon_max, zoom)  # NE corner: x large, y small
    if x2_total < x1_total: x1_total, x2_total = x2_total, x1_total
    if y2_total < y1_total: y1_total, y2_total = y2_total, y1_total
    dx = max(1, (x2_total - x1_total) // grid)
    dy = max(1, (y2_total - y1_total) // grid)
    tiles = []
    for i in range(grid):
        for j in range(grid):
            x1 = x1_total + i * dx
            x2 = x1_total + (i + 1) * dx if i < grid - 1 else x2_total
            y1 = y1_total + j * dy
            y2 = y1_total + (j + 1) * dy if j < grid - 1 else y2_total
            tiles.append({"x1": x1, "y1": y1, "x2": x2, "y2": y2})
    return tiles

BROWSER_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/124.0.0.0 Safari/537.36"
    ),
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9",
    "Accept-Language": "he-IL,he;q=0.9,en-US;q=0.8",
}

# GraphQL searchPoi query (operationName=searchPoi, server resolves to searchPoiV2).
# Trimmed PoiInner to fields we actually consume.
SEARCH_POI_QUERY = """
query searchPoi($dealType: String, $sort: [SortField], $tileRanges: [TileRange],
                $cursor: inputCursor, $limit: Int, $offset: Int,
                $poiTypes: [PoiType], $searchContext: SearchContext,
                $abtests: JSONObject, $userContext: JSONObject) {
  searchPoiV2(
    dealType: $dealType, sort: $sort, tileRanges: $tileRanges,
    cursor: $cursor, limit: $limit, offset: $offset,
    poiTypes: $poiTypes, searchContext: $searchContext,
    abtests: $abtests, userContext: $userContext
  ) {
    total
    cursor { bulletinsOffset projectsOffset seenProjects __typename }
    poi {
      id
      type
      __typename
      ... on Bulletin {
        locationPoint { lat lng __typename }
        addressDetails {
          docId city streetName streetNumber neighbourhood cityDocId __typename
        }
        address
        beds
        floor
        area
        price
        buildingYear
        firstTimeSeen
        lastUpdated
        eventsHistory { eventType price date __typename }
        __typename
      }
    }
  }
}
""".strip()


# Sale vs rent: madlan uses distinct URL slugs and GraphQL dealType values.
MADLAN_SLUGS = {"sale": "for-sale", "rent": "for-rent"}
MADLAN_DEAL_PARAM = {"sale": "unitBuy", "rent": "unitRent"}


class MadlanScraper:
    SITE_KEY = "madlan"

    def __init__(self, raw_snapshot_dir: Path | None = None, deal_type: str = "sale"):
        self.raw_snapshot_dir = raw_snapshot_dir
        self.deal_type = deal_type if deal_type in MADLAN_SLUGS else "sale"
        self.slug = MADLAN_SLUGS[self.deal_type]            # "for-sale" | "for-rent"
        self.px_deal = MADLAN_DEAL_PARAM[self.deal_type]    # "unitBuy" | "unitRent"
        self.cookies = self._load_cookies()

    def _load_cookies(self) -> dict[str, str]:
        if not SESSION_FILE.exists():
            logger.warning(
                "No Madlan session found at %s — run "
                "`python -m scanner.cli refresh-session --site madlan` first.",
                SESSION_FILE,
            )
            return {}
        state = json.loads(SESSION_FILE.read_text(encoding="utf-8"))
        return {
            c["name"]: c["value"]
            for c in state.get("cookies", [])
            if "madlan" in c.get("domain", "")
        }

    # ── SSR HTML extraction ──────────────────────────────────────────────────

    @staticmethod
    def _extract_ssr_context(html: str) -> dict | None:
        """Extract and parse window.__SSR_HYDRATED_CONTEXT__ from the page HTML."""
        marker = "window.__SSR_HYDRATED_CONTEXT__"
        start = html.find(marker)
        if start < 0:
            return None
        brace_start = html.find("{", start)
        script_end = html.find("</script>", brace_start)
        if script_end < 0:
            return None
        chunk = html[brace_start:script_end].rstrip()
        if chunk.endswith(";"):
            chunk = chunk[:-1]
        # Madlan injects raw JS literals like `undefined` — convert to JSON null
        chunk = re.sub(r"(?<![A-Za-z0-9_])undefined(?![A-Za-z0-9_])", "null", chunk)
        try:
            return json.loads(chunk)
        except json.JSONDecodeError as e:
            logger.warning(f"SSR JSON parse failed: {e}")
            return None

    def _fetch_first_page(
        self, client: httpx.Client, city_docid: str
    ) -> tuple[list[dict], dict | None, int]:
        """Fetch the listings page HTML for a city and parse the embedded SSR data.

        Returns (bulletins, cursor, total).
        """
        url = (
            f"{BASE_URL}/{self.slug}/{city_docid}"
            "?tracking_search_source=new_search&marketplace=residential"
        )
        try:
            resp = client.get(url, headers={**BROWSER_HEADERS, "Referer": BASE_URL + "/"})
        except httpx.RequestError as e:
            logger.warning(f"  HTTP error: {e}")
            return [], None, 0
        if resp.status_code != 200:
            logger.warning(f"  Non-200 status: {resp.status_code} ({len(resp.text)} bytes)")
            return [], None, 0
        ctx = self._extract_ssr_context(resp.text)
        if not ctx:
            logger.warning("  No SSR context in HTML")
            return [], None, 0
        sp = (
            ctx.get("reduxInitialState", {})
            .get("domainData", {})
            .get("searchList", {})
            .get("data", {})
            .get("searchPoiV2", {})
        )
        if not sp:
            logger.warning("  searchPoiV2 missing from SSR")
            return [], None, 0
        total = sp.get("total") or 0
        cursor = sp.get("cursor") or {}
        poi = sp.get("poi") or []
        bulletins = [p for p in poi if (p.get("__typename") == "Bulletin" or p.get("type") == "bulletin")]
        return bulletins, cursor, total

    # ── GraphQL pagination ───────────────────────────────────────────────────

    def _fetch_next_page(
        self, client: httpx.Client, city_docid: str, cursor: dict
    ) -> tuple[list[dict], dict | None]:
        """POST searchPoi to /api2 to fetch the next page using the cursor."""
        variables = {
            "dealType": self.px_deal,
            "poiTypes": ["bulletin", "project"],
            "searchContext": "marketplace",
            "sort": [{
                "field": "geometry",
                "order": "asc",
                "reference": None,
                "docIds": [city_docid],
            }],
            "cursor": {
                "bulletinsOffset": cursor.get("bulletinsOffset", 0),
                "projectsOffset": cursor.get("projectsOffset", 0),
                "seenProjects": cursor.get("seenProjects") or [],
            },
            "offset": cursor.get("bulletinsOffset", 0),
            "limit": 50,
            "userContext": None,
            "abtests": {},
        }
        body = {
            "operationName": "searchPoi",
            "variables": variables,
            "query": SEARCH_POI_QUERY,
        }
        try:
            resp = client.post(
                API_ENDPOINT,
                json=body,
                headers={
                    **BROWSER_HEADERS,
                    "Content-Type": "application/json",
                    "Accept": "*/*",
                    "Origin": BASE_URL,
                    "Referer": f"{BASE_URL}/{self.slug}/{city_docid}?tracking_search_source=new_search&marketplace=residential",
                    "X-Requested-With": "XMLHttpRequest",
                },
            )
        except httpx.RequestError as e:
            logger.warning(f"  GraphQL HTTP error: {e}")
            return [], None
        if resp.status_code != 200:
            logger.warning(f"  GraphQL non-200: {resp.status_code} body={resp.text[:200]}")
            return [], None
        try:
            data = resp.json()
        except Exception:
            return [], None
        sp = (data.get("data") or {}).get("searchPoiV2") or {}
        new_cursor = sp.get("cursor") or {}
        poi = sp.get("poi") or []
        bulletins = [p for p in poi if (p.get("__typename") == "Bulletin" or p.get("type") == "bulletin")]
        return bulletins, new_cursor

    # ── Per-city loop ────────────────────────────────────────────────────────

    def scrape_city(
        self,
        client: httpx.Client,
        city_docid: str,
        max_pages: int = 1,
    ) -> list[dict]:
        """Fetch all listings for one city (up to max_pages of 50)."""
        logger.info(f"  [{city_docid}] fetching first page (SSR HTML)...")
        bulletins, cursor, total = self._fetch_first_page(client, city_docid)
        logger.info(f"  [{city_docid}] total={total}, page1 bulletins={len(bulletins)}")
        if not bulletins:
            return []

        all_bulletins = list(bulletins)
        seen_ids = {b["id"] for b in bulletins}
        page = 1
        while cursor and len(all_bulletins) < total and page < max_pages:
            time.sleep(1.5)  # throttle to avoid rate limit
            page += 1
            logger.info(
                f"  [{city_docid}] page {page} cursor.bulletinsOffset="
                f"{cursor.get('bulletinsOffset')}"
            )
            new_bulletins, cursor = self._fetch_next_page(client, city_docid, cursor)
            if not new_bulletins:
                logger.info(f"  [{city_docid}] no more bulletins, stopping")
                break
            new = [b for b in new_bulletins if b["id"] not in seen_ids]
            seen_ids.update(b["id"] for b in new)
            all_bulletins.extend(new)
            if not new:
                logger.info(f"  [{city_docid}] only duplicates, stopping")
                break

        logger.info(f"  [{city_docid}] collected {len(all_bulletins)} bulletins")
        return all_bulletins

    # ── Normalization ────────────────────────────────────────────────────────

    def _normalize(self, b: dict) -> dict | None:
        try:
            ad = b.get("addressDetails") or {}
            loc = b.get("locationPoint") or {}
            price = b.get("price") or 0
            sqm = b.get("area") or 0
            now = datetime.now().isoformat()
            doc_id = ad.get("docId") or ""
            listing_id = b.get("id") or doc_id
            if not listing_id or not price:
                return None
            # Price history events (Sprint 3.a) — Madlan returns a list per Bulletin.
            # Stored under a leading-underscore key so cli.py can split it out before upsert
            # (the listings table doesn't have an `_events` column).
            events_raw = b.get("eventsHistory") or []
            events = [
                {
                    "listing_id": f"mdl_{listing_id}",
                    "event_type": e.get("eventType") or "",
                    "price": _safe_int(e.get("price")) or 0,
                    "date": e.get("date") or "",
                }
                for e in events_raw
                if isinstance(e, dict) and e.get("date")
            ]
            # Sprint 5 — tag as new construction if building year is current or future
            from datetime import datetime as _dt
            building_year = _safe_int(b.get("buildingYear"))
            this_year = _dt.now().year
            is_new = bool(building_year and building_year >= this_year - 1)

            return {
                "id": f"mdl_{listing_id}",
                "title": "",
                "address": b.get("address") or f"{ad.get('streetName','')} {ad.get('streetNumber','')}".strip(),
                "city": ad.get("city") or "",
                "neighborhood": ad.get("neighbourhood") or "",
                "is_new_construction": int(is_new),
                "_events": events,
                "rooms": _safe_int(b.get("beds")),
                "sqm": _safe_float(sqm),
                "floor": _safe_int(b.get("floor")),
                "price": int(price),
                "price_per_sqm": round(price / sqm) if price and sqm else None,
                "url": f"{BASE_URL}/listings/{doc_id}" if doc_id else f"{BASE_URL}/bulletin/{listing_id}",
                "posted_at": b.get("firstTimeSeen") or now,
                "gush": None,
                "lat": _safe_float((loc or {}).get("lat")),
                "lon": _safe_float((loc or {}).get("lng")),
                "last_seen": now,
                "is_active": True,
                "deal_type": self.deal_type,
            }
        except Exception as e:
            logger.debug(f"normalize error: {e}")
            return None

    def _save_snapshot(self, listings: list, name: str) -> None:
        if not self.raw_snapshot_dir:
            return
        snap_dir = self.raw_snapshot_dir / "madlan" / datetime.now().strftime("%Y-%m-%d")
        snap_dir.mkdir(parents=True, exist_ok=True)
        snap_file = snap_dir / f"listings_{name}_{datetime.now().strftime('%H%M%S')}.json"
        snap_file.write_text(json.dumps(listings, ensure_ascii=False, indent=2), encoding="utf-8")

    # ── Public entry ─────────────────────────────────────────────────────────

    def scrape(self, cities: list[str] | None = None) -> list[dict]:
        # httpx scrape kept for reference; default path is Playwright (handles PerimeterX).
        return []

    async def scrape_playwright(
        self,
        cities: list[str] | None = None,
        unattended: bool = False,
    ) -> list[dict]:
        """Use real headless browser with saved session — bypasses PerimeterX.
        Loads each city's listings page, parses embedded SSR for first ~50 listings.

        unattended=True: when CAPTCHA can't be auto-solved, send a Telegram ping and
        bail out cleanly (skips the 3-min headed wait that blocks cron jobs).
        """
        if not SESSION_FILE.exists():
            logger.warning(
                "No Madlan session — run `python -m scanner.cli refresh-session --site madlan` first."
            )
            return []

        from .session_manager import get_context, save_session, close_all
        cities = cities or CITY_DOCIDS
        all_listings: list[dict] = []
        seen_ids: set[str] = set()

        # PerimeterX flags headless — use headed when a display is available.
        # On headless servers (no $DISPLAY), fall back to headless=True; the saved
        # session cookies usually carry enough auth to bypass fingerprinting.
        import os
        # PerimeterX fingerprints headless Chromium and challenges it even with a
        # valid session, so run HEADED wherever a display exists. Windows (the
        # residential scrape host) always has one; on Linux fall back to $DISPLAY.
        use_headless = os.name != "nt" and not bool(os.environ.get("DISPLAY"))
        if use_headless:
            logger.info("No display — using headless=True for Madlan (server mode; PX may block)")
        else:
            logger.info("Display available — running Madlan headed to pass PerimeterX")
        playwright, browser, context = await get_context("madlan", headless=use_headless)
        try:
            page = await context.new_page()
            for i, city_docid in enumerate(cities):
                url = (
                    f"{BASE_URL}/{self.slug}/{city_docid}"
                    "?tracking_search_source=new_search&marketplace=residential"
                )
                try:
                    await page.goto(url, wait_until="domcontentloaded", timeout=45000)
                    await page.wait_for_timeout(2500)
                except Exception as e:
                    logger.warning(f"  [{city_docid}] goto error: {e}")
                    continue

                # Wait up to 3 minutes (interactive) or 30 sec (unattended) for
                # SSR to be present. Try auto-solving PerimeterX press-and-hold first.
                sp = None
                tried_autosolve = False
                max_attempts = 6 if unattended else 36
                for attempt in range(max_attempts):
                    sp = await page.evaluate("""
                        () => {
                            try {
                                const ctx = window.__SSR_HYDRATED_CONTEXT__;
                                if (!ctx) return null;
                                return ctx?.reduxInitialState?.domainData?.searchList?.data?.searchPoiV2 || null;
                            } catch(e) { return null; }
                        }
                    """)
                    if sp and sp.get("poi"):
                        break
                    if attempt == 0:
                        # Try to auto-solve press-and-hold once
                        if await _try_autosolve_pxcaptcha(page):
                            tried_autosolve = True
                            logger.info(f"  [{city_docid}] auto-solved press-and-hold")
                            await page.wait_for_timeout(3000)
                            continue
                        # Send Telegram alert with screenshot so user can see what's blocking
                        logger.warning(f"  [{city_docid}] CAPTCHA detected — sending screenshot to Telegram")
                        try:
                            from ..alerts.telegram import notify_captcha
                            notify_captcha("madlan")
                        except Exception as e:
                            logger.warning(f"notify_captcha failed: {e}")
                        try:
                            from .captcha_vnc import send_screenshot_alert
                            await send_screenshot_alert(page, "madlan")
                        except Exception as e:
                            logger.warning(f"screenshot alert failed: {e}")
                        if not unattended:
                            logger.warning(
                                f"  [{city_docid}] no SSR yet — waiting up to 3 min for manual solve..."
                            )
                    await page.wait_for_timeout(5000)

                if not sp or not sp.get("poi"):
                    logger.warning(f"  [{city_docid}] gave up waiting for SSR")
                    continue
                total = sp.get("total") or 0
                poi = sp.get("poi") or []
                bulletins = [p for p in poi if (p.get("__typename") == "Bulletin" or p.get("type") == "bulletin")]
                logger.info(f"  [{city_docid}] total={total}, page1 bulletins={len(bulletins)}")

                # Tile-based pagination with adaptive subdivision: start with a
                # 4x4 grid; if a tile saturates the 500-cap, split it 2x2 and recurse.
                # This recovers listings in dense areas (e.g., central Tel Aviv).
                city_ids = {b["id"] for b in bulletins}
                bbox = CITIES.get(city_docid)
                if bbox:
                    initial_tiles = _bbox_to_tile_grid(*bbox, grid=4)
                    # Stack of (tile, depth) — DFS so dense tiles get drilled before moving on
                    tile_stack: list[tuple[dict[str, int], int]] = [(t, 0) for t in initial_tiles]
                    logger.info(f"  [{city_docid}] paginating across {len(tile_stack)} initial tiles (recursive)")
                    LIMIT = 500
                    MAX_DEPTH = 4   # 4x4 → up to 16x16x16x16 = effective 256x256 grid
                    tile_n = 0
                    while tile_stack:
                        tile, depth = tile_stack.pop()
                        tile_n += 1
                        batch = await page.evaluate(
                            """async (args) => {
                                const { tile, query, limit, dealType } = args;
                                const variables = {
                                    dealType: dealType,
                                    poiTypes: ["bulletin"],
                                    searchContext: "marketplace",
                                    tileRanges: [tile],
                                    cursor: { bulletinsOffset: 0, projectsOffset: 0, seenProjects: [] },
                                    offset: 0,
                                    limit: limit,
                                    userContext: null,
                                    abtests: {},
                                };
                                try {
                                    const resp = await fetch('/api2', {
                                        method: 'POST',
                                        headers: { 'Content-Type': 'application/json', 'Accept': '*/*', 'X-Requested-With': 'XMLHttpRequest' },
                                        body: JSON.stringify({ operationName: 'searchPoi', variables, query }),
                                    });
                                    if (!resp.ok) return { error: `status ${resp.status}` };
                                    const json = await resp.json();
                                    return json?.data?.searchPoiV2 || { error: 'no data' };
                                } catch(e) { return { error: String(e) }; }
                            }""",
                            {"tile": tile, "query": SEARCH_POI_QUERY, "limit": LIMIT, "dealType": self.px_deal},
                        )
                        if not batch or batch.get("error"):
                            logger.warning(f"  [{city_docid}] tile #{tile_n} (d={depth}) error: {batch}")
                            continue
                        new_poi = batch.get("poi") or []
                        new_bull = [p for p in new_poi if (p.get("__typename") == "Bulletin" or p.get("type") == "bulletin")]
                        new_count = 0
                        for b in new_bull:
                            if b["id"] in city_ids:
                                continue
                            city_ids.add(b["id"])
                            bulletins.append(b)
                            new_count += 1
                        # If we hit the cap and tile is bigger than 1px, split 2x2
                        saturated = len(new_bull) >= LIMIT
                        sub_tiles_pushed = 0
                        if saturated and depth < MAX_DEPTH:
                            mx = (tile["x1"] + tile["x2"]) // 2
                            my = (tile["y1"] + tile["y2"]) // 2
                            if mx > tile["x1"] and my > tile["y1"]:
                                for sub in [
                                    {"x1": tile["x1"], "y1": tile["y1"], "x2": mx, "y2": my},
                                    {"x1": mx, "y1": tile["y1"], "x2": tile["x2"], "y2": my},
                                    {"x1": tile["x1"], "y1": my, "x2": mx, "y2": tile["y2"]},
                                    {"x1": mx, "y1": my, "x2": tile["x2"], "y2": tile["y2"]},
                                ]:
                                    tile_stack.append((sub, depth + 1))
                                    sub_tiles_pushed = 4
                        logger.info(
                            f"  [{city_docid}] tile #{tile_n} (d={depth}): +{new_count} new "
                            f"(city {len(city_ids)}/{total})"
                            + (f" [split into 4]" if sub_tiles_pushed else "")
                        )
                        await page.wait_for_timeout(400)  # gentle pacing

                added = 0
                for b in bulletins:
                    norm = self._normalize(b)
                    if norm and norm["id"] not in seen_ids:
                        seen_ids.add(norm["id"])
                        all_listings.append(norm)
                        added += 1
                logger.info(f"  [{city_docid}] DONE +{added} new (grand total {len(all_listings)})")
                # Save cookies after each city so progress survives crashes
                await save_session(context, "madlan")
                await page.wait_for_timeout(1500)  # polite throttle between cities
        finally:
            try:
                await save_session(context, "madlan")
            except Exception:
                pass
            await close_all(playwright, browser, context)

        if self.raw_snapshot_dir and all_listings:
            self._save_snapshot(all_listings, "all")
        return all_listings


async def _try_autosolve_pxcaptcha(page) -> bool:
    """Try to auto-solve PerimeterX 'press and hold' challenge.

    The challenge sits inside an iframe (id=px-captcha). Inside that frame,
    a button with the press-and-hold control needs ~9 sec of mouse-down.
    Returns True if a button was found and pressed.
    """
    try:
        # Wait briefly for the challenge iframe to attach
        for _ in range(6):
            iframe = page.frame(name="px-captcha") or next(
                (f for f in page.frames if "captcha" in (f.url or "").lower() or "px" in (f.name or "").lower()),
                None,
            )
            if iframe is not None:
                break
            await page.wait_for_timeout(500)
        else:
            iframe = None
        if iframe is None:
            return False

        # Find the press-and-hold button inside the iframe (varies by version)
        button = None
        for selector in [
            "div#px-captcha",
            "[role='button']",
            "button",
            "div.px-captcha-container",
        ]:
            try:
                el = iframe.locator(selector).first
                if await el.count() > 0:
                    button = el
                    break
            except Exception:
                continue
        if button is None:
            # Fallback: look on main page for #px-captcha box
            box_el = page.locator("#px-captcha").first
            if await box_el.count() == 0:
                return False
            box = await box_el.bounding_box()
            if not box:
                return False
        else:
            box = await button.bounding_box()
            if not box:
                return False

        cx = box["x"] + box["width"] / 2
        cy = box["y"] + box["height"] / 2
        await page.mouse.move(cx, cy)
        await page.mouse.down()
        # Press for ~10 seconds with tiny jitter (PX checks for human-like pressure)
        for _ in range(20):
            await page.wait_for_timeout(500)
            await page.mouse.move(cx + 0.5, cy + 0.3)
            await page.mouse.move(cx, cy)
        await page.mouse.up()
        return True
    except Exception as e:
        logger.debug(f"autosolve error: {e}")
        return False


def _safe_int(val) -> int | None:
    if val is None:
        return None
    try:
        v = int(float(str(val).replace(",", "")))
        return v if v != 0 else None
    except (TypeError, ValueError):
        return None


def _safe_float(val) -> float | None:
    if val is None:
        return None
    try:
        v = float(str(val).replace(",", ""))
        return v if v != 0.0 else None
    except (TypeError, ValueError):
        return None


async def scrape_madlan_listings(
    raw_snapshot_dir: Path | None = None,
    cities: list[str] | None = None,
    unattended: bool = False,
    deal_type: str = "sale",
) -> list[dict]:
    """Public entry: scrape Madlan listings across major Israeli cities (Playwright path).

    deal_type: "sale" (unitBuy, /for-sale/) or "rent" (unitRent, /for-rent/);
    every returned row is tagged with ``deal_type``.
    """
    scraper = MadlanScraper(raw_snapshot_dir=raw_snapshot_dir, deal_type=deal_type)
    return await scraper.scrape_playwright(cities, unattended=unattended)
