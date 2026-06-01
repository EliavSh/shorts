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
    """Return (start_s, end_s) window covering all beats focused on `ticker`.

    NOTE: for non-contiguous focus this spans the gap and can enclose another
    ticker's window — use `ticker_runs` for card scheduling so cards never
    overlap."""
    matched = [t for t in timings if t.beat.ticker_focus and t.beat.ticker_focus.upper() == ticker.upper()]
    if not matched:
        return None
    return matched[0].start_s, matched[-1].end_s


def ticker_runs(timings: list[BeatTiming]) -> list[tuple[str, float, float]]:
    """Group consecutive beats by `ticker_focus` into contiguous, NON-OVERLAPPING
    runs → exactly one ticker card on screen at a time, tracking the narration.

    A `None`-focus beat (hook/pivot/cta) is absorbed into the surrounding run
    only when the SAME ticker continues on both sides (so the card doesn't flicker
    off for one beat). A focus change leaves the in-between None beats as a gap
    (clean handoff — e.g. the pivot beat, where the compare card can go).
    """
    foci: list[str | None] = [
        ((t.beat.ticker_focus or "").upper() or None) for t in timings
    ]
    n = len(foci)
    eff = list(foci)
    for i in range(n):
        if eff[i] is not None:
            continue
        prev = next((foci[j] for j in range(i - 1, -1, -1) if foci[j]), None)
        nxt = next((foci[j] for j in range(i + 1, n) if foci[j]), None)
        if prev is not None and prev == nxt:
            eff[i] = prev  # same ticker straddles the gap → keep its card up
    runs: list[tuple[str, float, float]] = []
    i = 0
    while i < n:
        if eff[i] is None:
            i += 1
            continue
        j = i
        while j + 1 < n and eff[j + 1] == eff[i]:
            j += 1
        runs.append((eff[i], timings[i].start_s, timings[j].end_s))
        i = j + 1
    return runs


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
    by_symbol = {t.ticker.upper(): t for t in script.tickers}
    _cache: dict[str, object] = {}

    def card_for(sym: str):
        if sym not in _cache:
            t = by_symbol[sym]
            ohlc = [OHLC(o, h, l, c) for o, h, l, c in t.ohlc_30d] if t.ohlc_30d else None
            _cache[sym] = render_ticker_card(brand=brand, ticker=t.ticker, name=t.name,
                                             change_pct=t.change_pct, ohlc=ohlc)
        return _cache[sym]

    # One non-overlapping card per contiguous run of the same focus.
    runs = [(sym, s, e) for sym, s, e in ticker_runs(timings) if sym in by_symbol]
    if runs:
        for sym, s, e in runs:
            overlays.append(pil_to_clip(
                card_for(sym), start_s=s, end_s=e,
                position=brand.ticker_card.position,
                fade_in_s=fade_in_s, fade_out_s=fade_out_s,
            ))
    else:
        # No beat carried ticker_focus — anchor with the first ticker's card.
        sym = script.tickers[0].ticker.upper()
        visible_until = min(total_duration_s, total_duration_s * fallback_first_card_frac)
        overlays.append(pil_to_clip(
            card_for(sym), start_s=0.0, end_s=visible_until,
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
