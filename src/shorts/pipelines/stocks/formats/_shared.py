"""Helpers shared across format modules."""
from __future__ import annotations

from dataclasses import dataclass

import numpy as np
from moviepy import ImageClip
from PIL import Image

from ..script.schemas import Beat, Script


@dataclass(frozen=True)
class BeatTiming:
    beat: Beat
    start_s: float
    end_s: float

    @property
    def duration_s(self) -> float:
        return self.end_s - self.start_s


def compute_beat_timings(script: Script, total_duration_s: float) -> list[BeatTiming]:
    """Allocate each beat a slice of the total duration proportional to its
    narration character length. Used by every format."""
    if not script.beats:
        return []
    weights = [max(1.0, len(b.narration)) for b in script.beats]
    total_w = sum(weights)
    cursor = 0.0
    timings: list[BeatTiming] = []
    for b, w in zip(script.beats, weights, strict=False):
        share = (w / total_w) * total_duration_s
        timings.append(BeatTiming(beat=b, start_s=cursor, end_s=cursor + share))
        cursor += share
    # Pin the last beat's end to total to avoid float drift.
    if timings:
        last = timings[-1]
        timings[-1] = BeatTiming(beat=last.beat, start_s=last.start_s, end_s=total_duration_s)
    return timings


def find_beats_for_ticker(timings: list[BeatTiming], ticker: str) -> tuple[float, float] | None:
    """Return (start_s, end_s) window covering all beats focused on `ticker`."""
    matched = [t for t in timings if t.beat.ticker_focus and t.beat.ticker_focus.upper() == ticker.upper()]
    if not matched:
        return None
    return matched[0].start_s, matched[-1].end_s


def rotating_ticker_cards(
    *, script: Script, brand, total_duration_s: float,
    fade_in_s: float = 0.4, fade_out_s: float = 0.4,
    fallback_first_card_frac: float = 0.45,
) -> list[ImageClip]:
    """Render a ticker card per ticker, each visible only during the beats that
    focus on it (R10 — don't permanently occlude the frame).

    Generic across the multi-ticker formats (earnings roundups, sector tours).
    When a ticker has no focused beat, it's skipped. When NO beat carries
    ticker_focus at all (a thin script), we fall back to showing the first
    ticker's card during the opening `fallback_first_card_frac` of the video so
    the viewer still gets an anchor.
    """
    from ..visuals.ticker_card import OHLC, render_ticker_card

    overlays: list[ImageClip] = []
    if not script.tickers:
        return overlays

    timings = compute_beat_timings(script, total_duration_s)

    def card_for(t):
        ohlc = [OHLC(o, h, l, c) for o, h, l, c in t.ohlc_30d] if t.ohlc_30d else None
        return render_ticker_card(brand=brand, ticker=t.ticker, name=t.name,
                                  change_pct=t.change_pct, ohlc=ohlc)

    any_focus = False
    for t in script.tickers:
        win = find_beats_for_ticker(timings, t.ticker)
        if win is None:
            continue
        any_focus = True
        overlays.append(pil_to_clip(
            card_for(t), start_s=win[0], end_s=win[1],
            position=brand.ticker_card.position,
            fade_in_s=fade_in_s, fade_out_s=fade_out_s,
        ))

    if not any_focus:
        t = script.tickers[0]
        visible_until = min(total_duration_s, total_duration_s * fallback_first_card_frac)
        overlays.append(pil_to_clip(
            card_for(t), start_s=0.0, end_s=visible_until,
            position=brand.ticker_card.position,
            fade_in_s=fade_in_s, fade_out_s=fade_out_s,
        ))
    return overlays


def pil_to_clip(img: Image.Image, *, start_s: float, end_s: float,
                position: tuple[int, int] | str = (0, 0),
                fade_in_s: float = 0.0, fade_out_s: float = 0.0) -> ImageClip:
    """Convert a PIL RGBA image to a positioned, time-bounded MoviePy clip.

    Optional fade_in_s / fade_out_s apply CrossFade* effects — used for the
    ticker card so it slides in/out rather than permanently occluding.
    """
    from moviepy.video.fx import CrossFadeIn, CrossFadeOut
    arr = np.array(img.convert("RGBA"))
    clip = ImageClip(arr, is_mask=False, transparent=True).with_start(start_s).with_end(end_s).with_position(position)
    fx = []
    if fade_in_s > 0:
        fx.append(CrossFadeIn(fade_in_s))
    if fade_out_s > 0:
        fx.append(CrossFadeOut(fade_out_s))
    if fx:
        clip = clip.with_effects(fx)
    return clip
