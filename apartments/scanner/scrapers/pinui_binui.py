"""Scraper for פינוי בינוי (evacuation-construction) zones from MOCH ArcGIS."""
import json
import logging
import math
from datetime import datetime
from typing import Any

import httpx

logger = logging.getLogger(__name__)

# FeatureServer/1 = "מתחמי פינוי בינוי"
FEATURE_SERVICE_URL = (
    "https://services6.arcgis.com/I08Ekaykft5ELucH/arcgis/rest/services"
    "/GIS_UrbanRenewal/FeatureServer/1/query"
)

PAGE_SIZE = 1000


def _web_mercator_to_wgs84(x: float, y: float) -> tuple[float, float]:
    """Convert Web Mercator (EPSG:3857) to WGS84 lat/lon."""
    lon = x * 180.0 / 20037508.34
    lat = math.degrees(math.atan(math.exp(y * math.pi / 20037508.34))) * 2 - 90
    return lat, lon


def _centroid_of_polygon(rings: list) -> tuple[float, float] | None:
    """Compute simple centroid of the first ring."""
    if not rings:
        return None
    ring = rings[0]
    if not ring:
        return None
    xs = [p[0] for p in ring]
    ys = [p[1] for p in ring]
    return sum(xs) / len(xs), sum(ys) / len(ys)


def _parse_feature(feature: dict) -> dict[str, Any]:
    attrs = feature.get("attributes", {})
    geometry = feature.get("geometry")

    lat, lon = None, None
    geometry_json = None
    if geometry:
        rings = geometry.get("rings")
        if rings:
            cx, cy = _centroid_of_polygon(rings) or (None, None)
            if cx is not None:
                # Coordinates are returned in WGS84 (outSR=4326), x=lon, y=lat
                lon, lat = cx, cy
            # Store rings as JSON: each ring is [[lon, lat], ...]
            geometry_json = json.dumps(rings)

    # taarichTokef is milliseconds epoch or None
    approval_date = None
    raw_date = attrs.get("taarichTokef")
    if raw_date is not None:
        try:
            approval_date = datetime.utcfromtimestamp(raw_date / 1000).strftime("%Y-%m-%d")
        except (ValueError, OSError):
            approval_date = None

    return {
        "id": attrs.get("MisparProject"),
        "zone_name": attrs.get("ShemMitcham"),
        "city": attrs.get("Yeshuv"),
        "status": attrs.get("codeStatusHarashut"),
        "track": attrs.get("TeurMaslul"),
        "plan_number": attrs.get("plan_name"),
        "planning_status": attrs.get("codeStatusTichnun"),
        "approval_date": approval_date,
        "units_existing": attrs.get("yachadKayamRashut"),
        "units_added": attrs.get("YachadTosafti"),
        "units_total": attrs.get("yachadMutzaRashut"),
        "lat": lat,
        "lon": lon,
        "geometry_json": geometry_json,
        "fetched_at": datetime.now().isoformat(),
    }


def scrape_pinui_binui() -> list[dict[str, Any]]:
    """Fetch all פינוי בינוי zones from MOCH ArcGIS feature service."""
    zones = []
    offset = 0

    with httpx.Client(timeout=30) as client:
        while True:
            params = {
                "where": "1=1",
                "outFields": "*",
                "returnGeometry": "true",
                "outSR": "4326",
                "f": "json",
                "resultOffset": offset,
                "resultRecordCount": PAGE_SIZE,
            }
            resp = client.get(FEATURE_SERVICE_URL, params=params)
            resp.raise_for_status()
            data = resp.json()

            features = data.get("features", [])
            if not features:
                break

            for feat in features:
                zones.append(_parse_feature(feat))

            logger.info(f"Fetched {len(zones)} zones so far (offset={offset})")

            # ArcGIS returns exceededTransferLimit=true if more pages exist
            if not data.get("exceededTransferLimit", False):
                break
            offset += PAGE_SIZE

    logger.info(f"Total פינוי בינוי zones fetched: {len(zones)}")
    return zones
