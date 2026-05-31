"""Format: earnings_scorecard — after a company reports, grade the print:
revenue vs estimate, EPS vs estimate, guidance, and the market reaction.

The natural fulfiller of a 'we'll cover X after earnings' commitment.
"""
from __future__ import annotations

from moviepy import ImageClip

from ..script.schemas import Script
from shorts.core.visuals.brand import Brand
from ..voice.tts import TTSResult
from ._shared import rotating_ticker_cards
from . import FormatSpec, register


SPEC = FormatSpec(
    name="earnings_scorecard",
    description=(
        "After one company reports: beat or miss on revenue and EPS, what guidance "
        "said, and how the stock reacted. Use right after a notable earnings print."
    ),
    prompt_addendum=(
        "Format rules for **earnings_scorecard**:\n"
        "- Exactly 1 ticker in `tickers[]`.\n"
        "- Hook beat: the verdict in one line ('Nvidia beat — and still dropped 3%').\n"
        "- Body beats cover, each as its own beat: revenue vs estimate, EPS vs "
        "estimate, guidance, and the stock reaction. Use the actual numbers from "
        "the topic context — never invent a number that isn't provided.\n"
        "- Lean on `number_callout` and `bar_compare` visual intents (estimate vs "
        "actual) where natural.\n"
        "- All beats share the same ticker_focus.\n"
        "- `cta` beat closes the loop.\n"
    ),
    min_tickers=1,
    max_tickers=1,
    length_band=(90, 150),
)


def add_overlays(*, script: Script, tts: TTSResult, brand: Brand,
                 total_duration_s: float) -> list[ImageClip]:
    return rotating_ticker_cards(script=script, brand=brand,
                                 total_duration_s=total_duration_s)


register(SPEC, add_overlays)
