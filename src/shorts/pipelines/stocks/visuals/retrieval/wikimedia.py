"""Wikimedia Commons image search — free, no key, PD/CC.

Uses the MediaWiki API. Returns image URLs for the top matching files. Great
source for portraits of public figures, named buildings, named events.
"""
from __future__ import annotations

import logging

from shorts.core.infra.http_client import get as http_get
from shorts.core.usage import record as record_usage
from . import ImageCandidate

log = logging.getLogger(__name__)

ENDPOINT = "https://commons.wikimedia.org/w/api.php"

UA = "stocksreels/0.1 (https://github.com/eliavs/stocks-reels; contact via repo)"
HEADERS = {"User-Agent": UA, "Accept": "application/json"}


def search(query: str, *, n: int = 4) -> list[ImageCandidate]:
    try:
        # Step 1: search files matching the query.
        search_r = http_get(ENDPOINT, headers=HEADERS, params={
            "action": "query",
            "format": "json",
            "list": "search",
            "srsearch": f"{query} filetype:bitmap|drawing",
            "srnamespace": 6,   # File namespace
            "srlimit": min(n * 2, 12),
        }, timeout=10.0)
        search_r.raise_for_status()
        record_usage("wikimedia", "image_search", units=1, note=query[:80])
        hits = search_r.json().get("query", {}).get("search", []) or []
        if not hits:
            return []
        titles = [h["title"] for h in hits]

        # Step 2: fetch image info for those file titles.
        info_r = http_get(ENDPOINT, headers=HEADERS, params={
            "action": "query",
            "format": "json",
            "titles": "|".join(titles),
            "prop": "imageinfo",
            "iiprop": "url|size|extmetadata",
            "iiurlwidth": 1920,
        }, timeout=10.0)
        info_r.raise_for_status()
        pages = info_r.json().get("query", {}).get("pages", {}) or {}
    except Exception as e:
        log.warning("Wikimedia search failed for %r: %s", query, e)
        return []

    out: list[ImageCandidate] = []
    for _pid, page in pages.items():
        infos = page.get("imageinfo") or []
        if not infos:
            continue
        info = infos[0]
        meta = info.get("extmetadata", {}) or {}
        lic = (meta.get("LicenseShortName", {}).get("value") or "cc").lower()
        author = meta.get("Artist", {}).get("value", "") or "Wikimedia Commons"
        # Strip simple HTML.
        author = _strip_html(author)
        url = info.get("thumburl") or info.get("url")
        if not url:
            continue
        out.append(ImageCandidate(
            url=url,
            source="wikimedia",
            title=page.get("title", "").replace("File:", ""),
            width=info.get("thumbwidth") or info.get("width"),
            height=info.get("thumbheight") or info.get("height"),
            license=lic,
            attribution=f"Wikimedia Commons / {author[:60]}",
            source_page=info.get("descriptionurl"),
        ))
        if len(out) >= n:
            break
    return out


def _strip_html(s: str) -> str:
    import re
    return re.sub(r"<[^>]+>", "", s).strip()
