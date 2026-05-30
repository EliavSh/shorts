"""Google Custom Search Engine — image search.

Setup once:
1. Console: https://programmablesearchengine.google.com/ → create a search engine
   that searches the entire web, enable Image Search.
2. Copy the Search Engine ID (cx) → GOOGLE_CSE_ID env var.
3. Get an API key from Google Cloud Console (enable "Custom Search API") →
   GOOGLE_CSE_API_KEY env var.

Free tier: 100 queries/day. Above that: $5 / 1000.
"""
from __future__ import annotations

import logging
from typing import Any

from shorts.core.infra.http_client import get as http_get
from ...settings import get_settings
from shorts.core.usage import record as record_usage
from . import ImageCandidate

log = logging.getLogger(__name__)

ENDPOINT = "https://www.googleapis.com/customsearch/v1"


def search(query: str, *, n: int = 4) -> list[ImageCandidate]:
    s = get_settings()
    if not s.google_cse_api_key or not s.google_cse_id:
        log.debug("Google CSE not configured — skipping")
        return []

    try:
        r = http_get(ENDPOINT, params={
            "key": s.google_cse_api_key,
            "cx": s.google_cse_id,
            "q": query,
            "searchType": "image",
            "num": min(n, 10),
            "safe": "active",
            "imgSize": "large",
        }, timeout=10.0)
        r.raise_for_status()
        data: dict[str, Any] = r.json()
        record_usage("google_cse", "image_search", units=1, note=query[:80])
    except Exception as e:
        log.warning("Google CSE search failed for %r: %s", query, e)
        record_usage("google_cse", "image_search", units=1, success=False, note=str(e)[:80])
        return []

    items = data.get("items", []) or []
    out: list[ImageCandidate] = []
    for it in items[:n]:
        img = it.get("image", {}) or {}
        page = it.get("displayLink") or it.get("link")
        domain = _domain(page) if page else ""
        out.append(ImageCandidate(
            url=it.get("link", ""),
            source="google_cse",
            title=it.get("title", ""),
            width=img.get("width"),
            height=img.get("height"),
            license="editorial",  # treated as editorial fair use; attribution required
            attribution=f"Source: {domain}" if domain else None,
            source_page=img.get("contextLink"),
        ))
    return out


def _domain(url: str) -> str:
    from urllib.parse import urlparse
    try:
        return urlparse(url).netloc or url
    except Exception:
        return url
