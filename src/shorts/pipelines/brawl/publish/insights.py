"""Thin shim — delegates to shorts.core.reviews.distill, pre-binding pipeline=brawl."""
from __future__ import annotations

from shorts.core.reviews.distill import (
    Insight,
    InsightsFile,
)
from shorts.core.reviews.distill import extract_and_save as _extract_and_save
from shorts.core.reviews.distill import format_for_prompt as _format_for_prompt
from shorts.core.reviews.distill import load as _load
from shorts.core.reviews.distill import save as _save

_PIPELINE = "brawl"


def load() -> InsightsFile:
    return _load(_PIPELINE)


def save(f: InsightsFile) -> None:
    _save(_PIPELINE, f)


def format_for_prompt(max_bullets: int = 20) -> str:
    return _format_for_prompt(_PIPELINE, max_bullets)


def extract_and_save(
    comment_text: str,
    run_context: str,
    api_key: str,
    run_id: str,
    model: str = "claude-haiku-4-5-20251001",
) -> list[Insight]:
    return _extract_and_save(
        _PIPELINE,
        comment_text=comment_text,
        run_context=run_context,
        api_key=api_key,
        run_id=run_id,
        model=model,
    )


__all__ = ["Insight", "InsightsFile", "extract_and_save", "format_for_prompt", "load", "save"]
