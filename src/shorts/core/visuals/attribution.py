"""Per-shot attribution overlay — small credit strip the composer adds beneath
each retrieved image, for editorial fair-use compliance.
"""
from __future__ import annotations

from PIL import Image, ImageDraw, ImageFont
from unidecode import unidecode

from .brand import Brand, hex_to_rgba


def render_attribution(brand: Brand, text: str, *, max_width: int = 720) -> Image.Image:
    """Small dark pill with the photo credit. RGBA, sized to text.

    Author names with non-Latin glyphs (e.g. CJK) are romanized via unidecode
    so they render with our Latin/Hebrew brand font.
    """
    text = _to_renderable(text)
    font = ImageFont.truetype(str(brand.font_path_regular), size=18)
    pad_x, pad_y = 14, 8

    # Truncate to max width
    dummy = Image.new("RGBA", (1, 1))
    d = ImageDraw.Draw(dummy)
    while True:
        bbox = d.textbbox((0, 0), text, font=font)
        if bbox[2] - bbox[0] <= max_width - 2 * pad_x or len(text) <= 4:
            break
        text = text[:-2] + "…"

    bbox = d.textbbox((0, 0), text, font=font)
    w = bbox[2] - bbox[0] + 2 * pad_x
    h = bbox[3] - bbox[1] + 2 * pad_y

    img = Image.new("RGBA", (w, h), (0, 0, 0, 0))
    pd = ImageDraw.Draw(img)
    pd.rounded_rectangle((0, 0, w, h), radius=8, fill=hex_to_rgba("#000000", 0.6))
    pd.text((pad_x, pad_y), text, font=font, fill="#E5E7EB")
    return img


def _to_renderable(text: str) -> str:
    """Strip whitespace and romanize non-Latin runs (CJK etc.) so we don't
    render tofu boxes with the Latin-only brand font."""
    if not text:
        return ""
    # Heuristic: if there's any non-ASCII non-Hebrew character, romanize the
    # whole string. Hebrew runs are preserved (Heebo supports them).
    has_unsupported = any(_is_unsupported(c) for c in text)
    if has_unsupported:
        text = unidecode(text)
    return " ".join(text.split())


def _is_unsupported(ch: str) -> bool:
    cp = ord(ch)
    # ASCII range
    if cp < 0x80:
        return False
    # Hebrew block U+0590..U+05FF
    if 0x0590 <= cp <= 0x05FF:
        return False
    # Latin extended (most European accents) U+0080..U+024F
    if 0x0080 <= cp <= 0x024F:
        return False
    return True
