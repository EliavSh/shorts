"""Shared text-fitting helpers for generated graphics.

Generated graphics draw centered headlines/labels. Without a width guard a long
string is centered at a negative x and bleeds off both frame edges — the classic
"text out of bounds" bug. `fit_font` shrinks the font until the text fits the
given pixel budget so this can never happen, regardless of label length.
"""
from __future__ import annotations

from PIL import Image, ImageDraw, ImageFont

_MEASURE = ImageDraw.Draw(Image.new("RGB", (1, 1)))


def text_width(text: str, font: ImageFont.FreeTypeFont) -> int:
    bbox = _MEASURE.textbbox((0, 0), text, font=font)
    return bbox[2] - bbox[0]


def fit_font(
    font_path,
    text: str,
    *,
    max_width: int,
    start: int,
    min_size: int = 28,
    step: int = 4,
) -> ImageFont.FreeTypeFont:
    """Return a truetype font sized so `text` fits within `max_width` pixels.

    Shrinks from `start` down to `min_size`. At `min_size` it stops shrinking
    (callers that also wrap can rely on this; for single-line labels min_size is
    chosen small enough that realistic strings fit).
    """
    size = start
    while size > min_size:
        font = ImageFont.truetype(str(font_path), size=size)
        if text_width(text, font) <= max_width:
            return font
        size -= step
    return ImageFont.truetype(str(font_path), size=min_size)
