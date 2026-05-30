"""Format: two_story_pivot — two related stocks with a causal pivot in between."""
from __future__ import annotations

from moviepy import ImageClip

from ..script.schemas import Script
from shorts.core.visuals.brand import Brand
from ..visuals.ticker_card import render_ticker_card
from ..voice.tts import TTSResult
from ._shared import compute_beat_timings, find_beats_for_ticker, pil_to_clip
from . import FormatSpec, register


SPEC = FormatSpec(
    name="two_story_pivot",
    description=(
        "Two causally-linked stocks both moving today. Hook on stock A, explain "
        "why; pivot line ('but it's not only X…'); shift to stock B and explain "
        "the connection. Use only when the link between A and B is real and "
        "interesting, not coincidental."
    ),
    prompt_addendum=(
        "Format rules for **two_story_pivot**:\n"
        "- Exactly 2 tickers in `tickers[]`.\n"
        "- Beat roles must include one `hook`, one `pivot`, one `cta`.\n"
        "- Set `ticker_focus` on each body beat to the symbol it's about.\n"
        "- Hook + body beats about stock A come BEFORE the pivot beat; "
        "body beats about stock B come AFTER.\n"
        "- The pivot beat is a single short connector line, e.g. "
        "\"אבל לא רק אנבידיה מטפסת הבוקר.\"\n"
    ),
    min_tickers=2,
    max_tickers=2,
)


def add_overlays(*, script: Script, tts: TTSResult, brand: Brand,
                 total_duration_s: float) -> list[ImageClip]:
    overlays: list[ImageClip] = []
    timings = compute_beat_timings(script, total_duration_s)
    if len(script.tickers) < 2:
        return overlays  # composer will still draw captions + disclaimer

    primary, secondary = script.tickers[0], script.tickers[1]

    # Try to find tight windows from beats' ticker_focus. Fall back to "first half / second half" split around the pivot beat.
    win_a = find_beats_for_ticker(timings, primary.ticker)
    win_b = find_beats_for_ticker(timings, secondary.ticker)

    if win_a is None or win_b is None:
        pivot_idx = next((i for i, t in enumerate(timings) if t.beat.role == "pivot"), len(timings) // 2)
        win_a = (timings[0].start_s, timings[pivot_idx - 1].end_s if pivot_idx > 0 else timings[0].end_s)
        win_b = (timings[pivot_idx + 1].start_s if pivot_idx + 1 < len(timings) else timings[-1].start_s,
                 timings[-1].end_s)

    # R10 — fade ticker cards in/out so they don't permanently occlude content.
    overlays.append(pil_to_clip(
        render_ticker_card(brand=brand, ticker=primary.ticker, name=primary.name,
                           change_pct=primary.change_pct, ohlc=_ohlc_or_none(primary.ohlc_30d)),
        start_s=win_a[0], end_s=win_a[1], position=brand.ticker_card.position,
        fade_in_s=0.4, fade_out_s=0.4,
    ))
    overlays.append(pil_to_clip(
        render_ticker_card(brand=brand, ticker=secondary.ticker, name=secondary.name,
                           change_pct=secondary.change_pct, ohlc=_ohlc_or_none(secondary.ohlc_30d)),
        start_s=win_b[0], end_s=win_b[1], position=brand.ticker_card.position,
        fade_in_s=0.4, fade_out_s=0.4,
    ))
    return overlays


def _ohlc_or_none(rows):
    if not rows:
        return None
    from ..visuals.ticker_card import OHLC
    return [OHLC(o, h, l, c) for o, h, l, c in rows]


register(SPEC, add_overlays)
