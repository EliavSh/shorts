"""Format: story_telling — a narrative arc about one company: a founding,
a turnaround, a near-collapse, a comeback. The longest, most cinematic format.
"""
from __future__ import annotations

from moviepy import ImageClip

from ..script.schemas import Script
from shorts.core.visuals.brand import Brand
from ..voice.tts import TTSResult
from ._shared import rotating_ticker_cards
from . import FormatSpec, register


SPEC = FormatSpec(
    name="story_telling",
    description=(
        "A narrative arc about one company — a founding, a turnaround, a "
        "near-collapse, a comeback. Tension and payoff, not a news recap. Use when "
        "a company has a genuinely dramatic story worth telling."
    ),
    prompt_addendum=(
        "Format rules for **story_telling**:\n"
        "- Exactly 1 ticker in `tickers[]` (the company the story is about).\n"
        "- Hook beat: drop the viewer into the most dramatic moment ('In 2008 this "
        "company was 30 days from bankruptcy').\n"
        "- Body beats follow a clear arc: setup -> turning point -> consequence -> "
        "where it stands today. Build tension; each beat advances the story.\n"
        "- Keep all beats focused on the one ticker.\n"
        "- Dates, dollar amounts, and milestones must trace to the topic context.\n"
        "- `cta` beat lands the moral / where the company is now and closes.\n"
    ),
    min_tickers=1,
    max_tickers=1,
    length_band=(150, 180),
)


def add_overlays(*, script: Script, tts: TTSResult, brand: Brand,
                 total_duration_s: float) -> list[ImageClip]:
    return rotating_ticker_cards(script=script, brand=brand,
                                 total_duration_s=total_duration_s)


register(SPEC, add_overlays)
