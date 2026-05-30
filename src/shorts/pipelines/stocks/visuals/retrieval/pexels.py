"""Pexels image search — free, no rate-limit issues at our volume."""
from __future__ import annotations

import logging

from shorts.core.infra.http_client import get as http_get
from ...settings import get_settings
from shorts.core.usage import record as record_usage
from . import ImageCandidate

log = logging.getLogger(__name__)

ENDPOINT = "https://api.pexels.com/v1/search"


def search(query: str, *, n: int = 4) -> list[ImageCandidate]:
    s = get_settings()
    if not s.pexels_api_key:
        log.debug("PEXELS_API_KEY not set — skipping Pexels")
        return []
    try:
        r = http_get(ENDPOINT,
                      params={"query": query, "per_page": min(n, 15), "orientation": "portrait"},
                      headers={"Authorization": s.pexels_api_key},
                      timeout=10.0)
        r.raise_for_status()
        data = r.json()
        record_usage("pexels", "image_search", units=1, note=query[:80])
    except Exception as e:
        log.warning("Pexels search failed for %r: %s", query, e)
        record_usage("pexels", "image_search", units=1, success=False, note=str(e)[:80])
        return []

    photos = data.get("photos", []) or []
    out: list[ImageCandidate] = []
    for p in photos[:n]:
        src = p.get("src", {}) or {}
        out.append(ImageCandidate(
            url=src.get("large2x") or src.get("large") or src.get("original") or "",
            source="pexels",
            title=p.get("alt", "") or "",
            width=p.get("width"),
            height=p.get("height"),
            license="pexels",
            attribution=f"Photo: {p.get('photographer', 'Pexels')}",
            source_page=p.get("url"),
        ))
    return out
