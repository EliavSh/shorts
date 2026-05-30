"""Image cache — content-addressed local store with a manifest.

Each downloaded image is stored at `data/visual_cache/<sha256>.<ext>` with its
metadata (source, license, attribution, original URL) in a sidecar JSON file.
Subsequent runs that hit the same URL avoid the round-trip.
"""
from __future__ import annotations

import hashlib
import json
import logging
from dataclasses import dataclass
from pathlib import Path

from shorts.core.infra.http_client import stream as http_stream
from ..settings import get_settings
from .retrieval import ImageCandidate

log = logging.getLogger(__name__)


@dataclass(frozen=True)
class CachedImage:
    path: Path
    url: str
    source: str
    title: str
    license: str | None
    attribution: str | None
    source_page: str | None
    width: int | None
    height: int | None


def _hash_url(url: str) -> str:
    return hashlib.sha256(url.encode("utf-8")).hexdigest()[:24]


def _ext_from_url(url: str) -> str:
    for cand in (".jpg", ".jpeg", ".png", ".webp"):
        if cand in url.lower():
            return cand if cand != ".jpeg" else ".jpg"
    return ".jpg"


def fetch(cand: ImageCandidate) -> CachedImage | None:
    if not cand.url:
        return None
    s = get_settings()
    s.ensure_dirs()
    h = _hash_url(cand.url)
    ext = _ext_from_url(cand.url)
    img_path = s.visual_cache_dir / f"{h}{ext}"
    meta_path = s.visual_cache_dir / f"{h}.json"

    if img_path.exists() and meta_path.exists():
        meta = json.loads(meta_path.read_text(encoding="utf-8"))
        return CachedImage(path=img_path, **meta)

    try:
        with http_stream("GET", cand.url, timeout=15.0, follow_redirects=True,
                          headers={"User-Agent": "stocksreels/0.1 (https://github.com/user)"}) as r:
            r.raise_for_status()
            with img_path.open("wb") as f:
                for chunk in r.iter_bytes():
                    f.write(chunk)
    except Exception as e:
        log.warning("fetch failed for %s: %s", cand.url, e)
        if img_path.exists():
            img_path.unlink(missing_ok=True)
        return None

    meta = {
        "url": cand.url,
        "source": cand.source,
        "title": cand.title,
        "license": cand.license,
        "attribution": cand.attribution,
        "source_page": cand.source_page,
        "width": cand.width,
        "height": cand.height,
    }
    meta_path.write_text(json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8")
    return CachedImage(path=img_path, **meta)
