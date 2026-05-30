"""Review schema — pydantic-style dataclasses shared across pipelines.

Each `ReviewItem` represents one chosen "candidate" (a clip moment for brawl,
a finished render for stocks) and the iterative edit versions + reviewer
comments accumulated on it.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any


@dataclass
class Comment:
    text: str
    version_at_time: int        # which version was the latest when comment posted
    created_at: str


@dataclass
class Version:
    v: int
    title: str
    description: str
    hook_text: str
    captions: list[str]
    tags: list[str]
    created_at: str


@dataclass
class ReviewItem:
    run_id: str                 # unique within pipeline (brawl: video_id_start-end, stocks: slug)
    source_url: str             # canonical link to the original
    creator_handle: str         # @handle of the original creator (brawl) or topic source (stocks)
    creator_channel_id: str
    source_title: str
    # Brawl-specific moment fields; stocks fills with 0 / "" when irrelevant.
    moment_start_s: int = 0
    moment_end_s: int = 0
    moment_confidence: float = 1.0
    moment_rationale: str = ""
    status: str = "ready"               # "ready" | "processing"
    current_version: int = 1
    versions: list[Version] = field(default_factory=list)
    comments: list[Comment] = field(default_factory=list)
    created_at: str = ""
    updated_at: str = ""
    pipeline: str = ""                  # filled by the store on load

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def latest_version(item: ReviewItem) -> Version | None:
    if not item.versions:
        return None
    return max(item.versions, key=lambda v: v.v)
