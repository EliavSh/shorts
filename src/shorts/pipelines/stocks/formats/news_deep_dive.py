"""Format: news_deep_dive — unpack one big recent story in depth, including the
second-order effects on a related stock.
"""
from __future__ import annotations

from moviepy import ImageClip

from ..script.schemas import Script
from shorts.core.visuals.brand import Brand
from ..voice.tts import TTSResult
from ._shared import rotating_ticker_cards
from . import FormatSpec, register


SPEC = FormatSpec(
    name="news_deep_dive",
    description=(
        "Unpack one big recent story in real depth — what happened, why it "
        "matters, who else is affected. Use when a single story has enough layers "
        "to reward 2-3 minutes."
    ),
    prompt_addendum=(
        "Format rules for **news_deep_dive**:\n"
        "- 1-2 tickers in `tickers[]` (the second only if the story genuinely "
        "spills onto a related company).\n"
        "- Hook beat: the headline as a concrete surprise.\n"
        "- Body beats build the story in layers: what happened -> the number "
        "behind it -> why it matters -> the knock-on effect / what's next.\n"
        "- Set `ticker_focus` per beat so the right card shows.\n"
        "- Every claim must trace to the topic context headlines/notes.\n"
        "- `cta` beat closes.\n"
    ),
    min_tickers=1,
    max_tickers=2,
    length_band=(150, 180),
)


def add_overlays(*, script: Script, tts: TTSResult, brand: Brand,
                 total_duration_s: float) -> list[ImageClip]:
    return rotating_ticker_cards(script=script, brand=brand,
                                 total_duration_s=total_duration_s)


register(SPEC, add_overlays)
