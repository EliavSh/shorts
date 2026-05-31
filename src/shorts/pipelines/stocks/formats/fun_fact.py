"""Format: fun_fact — one surprising stat or historical nugget about a company,
market, or money. Light, shareable, low-news-dependency.
"""
from __future__ import annotations

from moviepy import ImageClip

from ..script.schemas import Script
from shorts.core.visuals.brand import Brand
from ..voice.tts import TTSResult
from ._shared import rotating_ticker_cards
from . import FormatSpec, register


SPEC = FormatSpec(
    name="fun_fact",
    description=(
        "One surprising stat or historical nugget about a company, the market, or "
        "money — the kind of thing that makes someone go 'wait, really?'. Light "
        "and shareable, doesn't need fresh news."
    ),
    prompt_addendum=(
        "Format rules for **fun_fact**:\n"
        "- 0-1 ticker in `tickers[]`. Include the ticker only if the fact is "
        "about one specific public company.\n"
        "- Hook beat: lead with the surprising fact itself, framed as a punchy "
        "number or claim. No 'did you know'.\n"
        "- 2-4 body beats: the context that makes the fact land — how it compares, "
        "how it came to be, why it's surprising.\n"
        "- Lean on `number_callout` for the headline stat.\n"
        "- The fact must be true and traceable to the topic context; if you're "
        "not given the number, don't invent it.\n"
        "- `cta` beat closes.\n"
    ),
    min_tickers=0,
    max_tickers=1,
    length_band=(90, 120),
)


def add_overlays(*, script: Script, tts: TTSResult, brand: Brand,
                 total_duration_s: float) -> list[ImageClip]:
    return rotating_ticker_cards(script=script, brand=brand,
                                 total_duration_s=total_duration_s)


register(SPEC, add_overlays)
