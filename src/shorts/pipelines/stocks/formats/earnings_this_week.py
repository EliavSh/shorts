"""Format: earnings_this_week — a roundup of notable companies reporting this
week and what to watch in each.

Calendar-driven (the planner seeds it from data/earnings.py). Multiple ticker
cards rotate as each company is introduced.
"""
from __future__ import annotations

from moviepy import ImageClip

from ..script.schemas import Script
from shorts.core.visuals.brand import Brand
from ..voice.tts import TTSResult
from ._shared import rotating_ticker_cards
from . import FormatSpec, register


SPEC = FormatSpec(
    name="earnings_this_week",
    description=(
        "A roundup of the most-watched companies reporting earnings this week and "
        "the one thing to watch in each. Use when several notable reports land in "
        "the same window."
    ),
    prompt_addendum=(
        "Format rules for **earnings_this_week**:\n"
        "- 3-6 tickers in `tickers[]` — the companies reporting this week.\n"
        "- Hook beat: frame the week ('Five big reports this week — here's what "
        "matters'). Use a date or count anchor.\n"
        "- One short `body` beat per company: the report DATE plus the single key "
        "question (a number to beat, a guidance worry, a segment to watch).\n"
        "- Set `ticker_focus` on each company's beat so its card appears.\n"
        "- `cta` beat: tell viewers to follow for the scorecard after the reports.\n"
        "- Don't predict results — frame what to watch, never 'this will beat'.\n"
    ),
    min_tickers=3,
    max_tickers=6,
    length_band=(120, 180),
)


def add_overlays(*, script: Script, tts: TTSResult, brand: Brand,
                 total_duration_s: float) -> list[ImageClip]:
    return rotating_ticker_cards(script=script, brand=brand,
                                 total_duration_s=total_duration_s)


register(SPEC, add_overlays)
