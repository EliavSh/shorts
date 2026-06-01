"""Format: two_story_pivot — two related stocks with a causal pivot in between."""
from __future__ import annotations

from moviepy import ImageClip

from ..script.schemas import Script
from shorts.core.visuals.brand import Brand
from ..visuals.ticker_card import render_compare_card, render_ticker_card
from ..voice.tts import TTSResult
from ._shared import compute_beat_timings, pil_to_clip, ticker_runs
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
    length_band=(90, 130),
)


def add_overlays(*, script: Script, tts: TTSResult, brand: Brand,
                 total_duration_s: float) -> list[ImageClip]:
    overlays: list[ImageClip] = []
    timings = compute_beat_timings(script, total_duration_s)
    if len(script.tickers) < 2:
        return overlays  # composer will still draw captions + disclaimer

    primary, secondary = script.tickers[0], script.tickers[1]
    by_symbol = {t.ticker.upper(): t for t in (primary, secondary)}
    pos = brand.ticker_card.position

    def _solo(t):
        return render_ticker_card(brand=brand, ticker=t.ticker, name=t.name,
                                  change_pct=t.change_pct, ohlc=_ohlc_or_none(t.ohlc_30d))

    # One non-overlapping card per contiguous focus run (A … pivot-gap … B).
    runs = [(sym, s, e) for sym, s, e in ticker_runs(timings) if sym in by_symbol]
    if not runs:
        # Thin script with no ticker_focus: split A first / B second, no overlap.
        pivot_idx = next((i for i, t in enumerate(timings) if t.beat.role == "pivot"),
                         len(timings) // 2)
        mid = timings[pivot_idx].start_s if 0 <= pivot_idx < len(timings) else total_duration_s / 2
        runs = [(primary.ticker.upper(), 0.0, mid),
                (secondary.ticker.upper(), mid, total_duration_s)]

    _cache: dict[str, object] = {}
    for sym, s, e in runs:
        if sym not in _cache:
            _cache[sym] = _solo(by_symbol[sym])
        overlays.append(pil_to_clip(_cache[sym], start_s=s, end_s=e, position=pos,
                                    fade_in_s=0.4, fade_out_s=0.4))

    # The pivot beat is the causal bridge — show BOTH tickers together there.
    pivot = next((t for t in timings if t.beat.role == "pivot"), None)
    if pivot is not None and pivot.end_s > pivot.start_s:
        overlays.append(pil_to_clip(
            render_compare_card(brand=brand, primary=primary, secondary=secondary),
            start_s=pivot.start_s, end_s=pivot.end_s, position=pos,
            fade_in_s=0.3, fade_out_s=0.3,
        ))
    return overlays


def _ohlc_or_none(rows):
    if not rows:
        return None
    from ..visuals.ticker_card import OHLC
    return [OHLC(o, h, l, c) for o, h, l, c in rows]


register(SPEC, add_overlays)
