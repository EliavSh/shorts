"""Pinui Binui zones — GeoJSON polygons for the React map overlay."""
import json
import math
from typing import Optional

import sqlite_utils
from fastapi import APIRouter, Depends, Query

from scanner.api.deps import get_database

router = APIRouter(prefix="/api/zones", tags=["zones"])


@router.get("")
def list_zones(
    near_lat: Optional[float] = None,
    near_lon: Optional[float] = None,
    near_radius_m: float = Query(5000, ge=100, le=50_000),
    city: Optional[str] = None,
    limit: int = Query(500, le=2000),
    db: sqlite_utils.Database = Depends(get_database),
):
    """Return zones as a GeoJSON FeatureCollection.

    With ``near_lat``/``near_lon``: bounding-box prefilter on the centroid
    so mobile only loads zones nearby. ``geometry_json`` already holds a
    Polygon/MultiPolygon GeoJSON geometry — we wrap each in a Feature.
    """
    where: list[str] = ["geometry_json IS NOT NULL"]
    params: list = []

    if city:
        where.append("city = ?")
        params.append(city)

    if near_lat is not None and near_lon is not None:
        dlat = near_radius_m / 111_000
        dlon = near_radius_m / (111_000 * max(0.1, math.cos(math.radians(near_lat))))
        where += [
            "lat IS NOT NULL", "lon IS NOT NULL",
            "lat BETWEEN ? AND ?", "lon BETWEEN ? AND ?",
        ]
        params += [
            near_lat - dlat, near_lat + dlat,
            near_lon - dlon, near_lon + dlon,
        ]

    where_sql = " AND ".join(where)
    rows = db.execute(
        f"SELECT id, zone_name, city, status, track, planning_status, "
        f"       units_existing, units_added, units_total, lat, lon, geometry_json "
        f"FROM pinui_binui_zones WHERE {where_sql} LIMIT ?",
        [*params, limit],
    ).fetchall()

    features = []
    for r in rows:
        try:
            raw = json.loads(r[11])
        except (json.JSONDecodeError, TypeError):
            continue
        geom = _wrap_geometry(raw)
        if geom is None:
            continue
        features.append({
            "type": "Feature",
            "geometry": geom,
            "properties": {
                "id": r[0],
                "zone_name": r[1],
                "city": r[2],
                "status": r[3],
                "track": r[4],
                "planning_status": r[5],
                "units_existing": r[6],
                "units_added": r[7],
                "units_total": r[8],
                "centroid": [r[9], r[10]] if r[9] and r[10] else None,
            },
        })

    return {"type": "FeatureCollection", "features": features}


def _wrap_geometry(raw):
    """Wrap raw coordinates from pinui_binui_zones.geometry_json into proper GeoJSON.

    The DB stores coords (no ``type`` field). Detect Polygon vs MultiPolygon by
    nesting depth, then return a real GeoJSON Geometry. Already-wrapped objects
    pass through.
    """
    if isinstance(raw, dict) and raw.get("type") in ("Polygon", "MultiPolygon"):
        return raw
    if not isinstance(raw, list) or not raw:
        return None
    depth = _depth(raw)
    # Polygon coords: 3 levels of list ([rings][points][lon,lat])
    if depth == 3:
        return {"type": "Polygon", "coordinates": raw}
    # MultiPolygon coords: 4 levels of list ([polygons][rings][points][lon,lat])
    if depth == 4:
        return {"type": "MultiPolygon", "coordinates": raw}
    return None


def _depth(x, d=0):
    if isinstance(x, list) and x:
        return _depth(x[0], d + 1)
    return d
