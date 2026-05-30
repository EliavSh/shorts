"""Image retrieval — multi-source search returning a unified ImageCandidate.

Sources implement `search(query, n) -> list[ImageCandidate]` and are tried in
the priority order defined in `search_all`. Each candidate carries a `source`
field so downstream code can apply license rules and attribution.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Literal


SourceName = Literal["google_cse", "wikimedia", "pexels", "finnhub_news", "serper"]


@dataclass(frozen=True)
class ImageCandidate:
    url: str
    source: SourceName
    title: str = ""
    width: int | None = None
    height: int | None = None
    license: str | None = None  # "pd", "cc-by", "editorial", "pexels", etc.
    attribution: str | None = None  # display text under the image, e.g. "Photo: Reuters"
    source_page: str | None = None  # original article / wiki page URL


def search_all(query: str, *, n_per_source: int = 4) -> list[ImageCandidate]:
    """Query every configured source; merged candidates in priority order.

    Sources self-skip when their key isn't configured, so the same code path
    works for users with any subset of providers set up.
    """
    from . import google_cse, pexels, serper, wikimedia

    out: list[ImageCandidate] = []
    out.extend(serper.search(query, n=n_per_source))      # news photos (Google Images via Serper)
    out.extend(google_cse.search(query, n=n_per_source))  # legacy Google CSE — disabled for new projects
    out.extend(wikimedia.search(query, n=n_per_source))   # PD photos
    out.extend(pexels.search(query, n=n_per_source))      # stock B-roll
    return out
