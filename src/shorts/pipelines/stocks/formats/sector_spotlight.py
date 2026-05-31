"""Format: sector_spotlight — a tour of one sector: the theme driving it and the
key movers. Backs recurring sector series (e.g. an energy arc).
"""
from __future__ import annotations

from moviepy import ImageClip

from ..script.schemas import Script
from shorts.core.visuals.brand import Brand
from ..voice.tts import TTSResult
from ._shared import rotating_ticker_cards
from . import FormatSpec, register


SPEC = FormatSpec(
    name="sector_spotlight",
    description=(
        "A tour of one sector: the macro theme driving it right now and the key "
        "stocks moving on it. Use to cover a sector as a whole, or as an episode "
        "in a recurring sector series."
    ),
    prompt_addendum=(
        "Format rules for **sector_spotlight**:\n"
        "- 3-6 tickers in `tickers[]` — the representative names in the sector.\n"
        "- Hook beat: name the sector and the one force moving it ('Energy stocks "
        "are ripping — and it's not oil').\n"
        "- A `body` beat per key mover: what it does and how it fits the theme. "
        "Explain any non-mega-cap name with a scale anchor (R7/R8).\n"
        "- Set `ticker_focus` per beat so each company's card appears.\n"
        "- Tie it together: what to watch next in the sector.\n"
        "- `cta` beat: if this is part of a series, tease the next episode.\n"
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
