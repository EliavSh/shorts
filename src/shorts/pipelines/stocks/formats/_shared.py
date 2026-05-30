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
