"""Format: myth_vs_reality — debunk a common market belief with the actual data.
"""
from __future__ import annotations

from moviepy import ImageClip

from ..script.schemas import Script
from shorts.core.visuals.brand import Brand
from ..voice.tts import TTSResult
from ._shared import rotating_ticker_cards
from . import FormatSpec, register


SPEC = FormatSpec(
    name="myth_vs_reality",
    description=(
        "Take a common belief retail investors hold and test it against the data — "
        "confirm it, complicate it, or debunk it. Use for an evergreen "
        "'everyone thinks X, but...' angle."
    ),
    prompt_addendum=(
        "Format rules for **myth_vs_reality**:\n"
        "- 0-2 tickers in `tickers[]` — include only the names you actually cite "
        "as evidence.\n"
        "- Hook beat: state the myth out loud as most people believe it.\n"
        "- A `pivot` beat: the turn ('Here's what the data actually shows').\n"
        "- Body beats: the evidence, with real numbers from the topic context. "
        "Use `bar_compare` / `number_callout` intents where they sharpen the point.\n"
        "- End on the nuanced takeaway — avoid a smug 'everyone is wrong'.\n"
        "- Never give trading advice; report what the data says.\n"
        "- `cta` beat closes.\n"
    ),
    min_tickers=0,
    max_tickers=2,
    length_band=(90, 150),
)


def add_overlays(*, script: Script, tts: TTSResult, brand: Brand,
                 total_duration_s: float) -> list[ImageClip]:
    return rotating_ticker_cards(script=script, brand=brand,
                                 total_duration_s=total_duration_s)


register(SPEC, add_overlays)
