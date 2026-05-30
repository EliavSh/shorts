"""Thin shim — delegates to shorts.core.reviews, pre-binding pipeline=brawl.

Preserves the original API surface (save/load/list_items/latest_version + types).
"""
from __future__ import annotations

from typing import Any

from shorts.core.reviews import Comment, ReviewItem, ReviewStore, Version, latest_version
from shorts.core.reviews.llm import generate_title_and_description as _gen_t_d

_PIPELINE = "brawl"
_store = ReviewStore(_PIPELINE)

OUTPUT_ROOT = _store.output_root

DEFAULT_TAGS = [
    "Brawl Stars",
    "brawl stars highlights",
    "brawl stars clips",
    "supercell",
    "mobile gaming",
    "shorts",
    "gaming shorts",
]


def save(item: ReviewItem) -> None:
    _store.save(item)


def load(run_id: str) -> ReviewItem | None:
    return _store.load(run_id)


def list_items() -> list[ReviewItem]:
    return _store.list_items()


def generate_title_and_description(
    *,
    creator: str,
    source_url: str,
    hook_text: str,
    moment_context: str,
    api_key: str,
    insights_text: str = "",
    feedback_text: str = "",
    model: str = "claude-haiku-4-5-20251001",
) -> tuple[str, str]:
    return _gen_t_d(
        creator=creator,
        source_url=source_url,
        hook_text=hook_text,
        moment_context=moment_context,
        api_key=api_key,
        insights_text=insights_text,
        feedback_text=feedback_text,
        model=model,
    )


__all__ = [
    "Comment",
    "DEFAULT_TAGS",
    "OUTPUT_ROOT",
    "ReviewItem",
    "Version",
    "generate_title_and_description",
    "latest_version",
    "list_items",
    "load",
    "save",
]
