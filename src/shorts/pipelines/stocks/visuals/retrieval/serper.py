"""Serper.dev image search — Google Images results without the GCP pain.

Setup:
1. Sign up at https://serper.dev (free 2,500 queries to start, $5/mo for renew).
2. Copy the API key from the dashboard.
3. Set SERPER_API_KEY in .env.

Endpoint docs: https://serper.dev/playground (Images tab).
"""
from __future__ import annotations

import logging
from typing import Any

from shorts.core.infra.http_client import client as http_client_factory
from ...settings import get_settings
from shorts.core.usage import record as record_usage
from . import ImageCandidate

log = logging.getLogger(__name__)

ENDPOINT = "https://google.serper.dev/images"


def search(query: str, *, n: int = 4) -> list[ImageCandidate]:
    s = get_settings()
    if not s.serper_api_key:
        log.debug("SERPER_API_KEY not set — skipping Serper")
        return []

    try:
        with http_client_factory(timeout=12.0) as c:
            r = c.post(
                ENDPOINT,
                headers={"X-API-KEY": s.serper_api_key, "Content-Type": "application/json"},
                json={"q": query, "num": min(n, 10)},
            )
            r.raise_for_status()
            data: dict[str, Any] = r.json()
        record_usage("serper", "image_search", units=1, note=query[:80])
    except Exception as e:
        log.warning("Serper search failed for %r: %s", query, e)
        record_usage("serper", "image_search", units=1, success=False, note=str(e)[:80])
        return []

    images = data.get("images", []) or []
    out: list[ImageCandidate] = []
    for it in images[:n]:
        url = it.get("imageUrl") or ""
        if not url:
            continue
        source_domain = it.get("source") or _domain(it.get("link", ""))
        out.append(ImageCandidate(
            url=url,
            source="google_cse",  # reuse the "editorial fair use w/ credit" license bucket
            title=it.get("title", "") or "",
            width=it.get("imageWidth"),
            height=it.get("imageHeight"),
            license="editorial",
            attribution=f"Source: {source_domain}" if source_domain else None,
            source_page=it.get("link"),
        ))
    return out


def _domain(url: str) -> str:
    from urllib.parse import urlparse
    try:
        return urlparse(url).netloc or url
    except Exception:
        return url
