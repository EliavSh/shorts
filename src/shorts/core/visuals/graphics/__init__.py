"""Generated graphics — for visual sections where a retrieved photo can't
deliver an unambiguous payload within 1 second of Shorts pacing (R2/R3/R4).

Each generator returns a PIL.Image sized for a 1080x1920 frame OR a path to a
saved PNG. The scheduler dispatches to one of these when a VisualSection has
`graphic_spec` set, instead of going through retrieval.

Registry:
  - date_card        — calendar grid with one date prominently highlighted
  - number_callout   — large hero number + label
  - bar_compare      — two or three bars side-by-side
  - mini_chart       — clean candlestick/line at native 9:16
"""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

from PIL import Image


@dataclass(frozen=True)
class GraphicSpec:
    """Tagged-union spec for the Claude visual director to emit per section."""

    kind: str
    """One of: date_card, number_callout, bar_compare, mini_chart"""
    params: dict[str, Any]
    """Generator-specific parameters."""


def render(spec: GraphicSpec, *, brand, out_dir: Path) -> Path:
    """Dispatch by kind. Returns the path of the saved PNG."""
    from . import bar_compare, date_card, follow_cta, mini_chart, number_callout

    handlers = {
        "date_card": date_card.render,
        "number_callout": number_callout.render,
        "bar_compare": bar_compare.render,
        "mini_chart": mini_chart.render,
        "follow_cta": follow_cta.render,
    }
    if spec.kind not in handlers:
        raise ValueError(f"unknown graphic kind: {spec.kind!r}")
    img = handlers[spec.kind](brand=brand, **spec.params)
    out_dir.mkdir(parents=True, exist_ok=True)
    out_path = out_dir / f"graphic_{spec.kind}_{abs(hash(repr(spec.params))) % 10**8}.png"
    if isinstance(img, Image.Image):
        img.save(out_path)
    return out_path


KIND_DESCRIPTIONS = {
    "date_card": "A calendar where one specific date is prominently highlighted. Use when narration "
                 "calls out a specific date (e.g. 'June 17 matters').",
    "number_callout": "A single huge hero number with a short label below. Use when the narration "
                      "lands on one striking number ('$3.2 billion', '+85%', '500,000 chips').",
    "bar_compare": "Two or three labelled bars side-by-side. Use for before/after, this-quarter "
                   "vs last-quarter, two-stock comparisons.",
    "mini_chart": "A clean candlestick or line chart of price data over time, sized natively for "
                  "9:16. Use when the takeaway is the SHAPE of price action.",
    "follow_cta": "Branded 'Follow' callout card. Use on the final CTA beat.",
}
