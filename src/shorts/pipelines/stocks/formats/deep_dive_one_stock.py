"""Format: deep_dive_one_stock — one stock, full attention.

Used when one story is rich enough to fill a Short on its own (earnings, big
news, a chart-pattern story). Ticker card stays visible the whole time so
viewers can keep the context as we unpack details.
"""
from __future__ import annotations

from moviepy import ImageClip

from ..script.schemas import Script
from shorts.core.visuals.brand import Brand
from ..visuals.ticker_card import OHLC, render_ticker_card
from ..voice.tts import TTSResult
from ._shared import pil_to_clip
from . import FormatSpec, register


SPEC = FormatSpec(
    name="deep_dive_one_stock",
    description=(
        "One stock with enough news/story to fill 60 seconds: earnings beat, "
        "product launch, regulatory action, big chart pattern. Walk the viewer "
        "through 3-5 facts that together tell the full story."
    ),
    prompt_addendum=(
        "Format rules for **deep_dive_one_stock**:\n"
        "- Exactly 1 ticker in `tickers[]`.\n"
        "- Beat roles must include one `hook` (the headline), 3-5 `body` beats "
        "(facts, numbers, context), and one `cta`.\n"
        "- Each body beat should add NEW information; never restate the hook.\n"
        "- All beats share the same ticker_focus (the single ticker).\n"
        "- No pivot beat.\n"
    ),
    min_tickers=1,
    max_tickers=1,
)


def add_overlays(*, script: Script, tts: TTSResult, brand: Brand,
                 total_duration_s: float) -> list[ImageClip]:
    overlays: list[ImageClip] = []
    if not script.tickers:
        return overlays
    t = script.tickers[0]
    ohlc = [OHLC(o, h, l, c) for o, h, l, c in t.ohlc_30d] if t.ohlc_30d else None
    card = render_ticker_card(brand=brand, ticker=t.ticker, name=t.name,
                              change_pct=t.change_pct, ohlc=ohlc)
    # R10 — for deep dive, show ticker card only during the first ~40% of the
    # video so later body beats can show their visual focal points unobstructed.
    visible_until = min(total_duration_s, total_duration_s * 0.45)
    overlays.append(pil_to_clip(
        card, start_s=0.0, end_s=visible_until,
        position=brand.ticker_card.position,
        fade_in_s=0.4, fade_out_s=0.5,
    ))
    return overlays


register(SPEC, add_overlays)
