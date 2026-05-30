"""Persistent legal disclaimer bar.

Renders the bottom-of-frame disclaimer overlay (full-width bar with small text)
that's required for Israeli investment-content compliance and good practice for
English content.
"""
from __future__ import annotations

from PIL import Image, ImageDraw, ImageFont

from shorts.core.visuals.brand import Brand, hex_to_rgba
from shorts.core.visuals.captions import _to_display

FRAME_W = 1080
FRAME_H = 1920


def render_disclaimer(
    *,
    brand: Brand,
    frame_size: tuple[int, int] = (FRAME_W, FRAME_H),
) -> tuple[Image.Image, tuple[int, int]]:
    style = brand.disclaimer
    fw, fh = frame_size

    bar = Image.new("RGBA", (fw, style.height), hex_to_rgba(style.background, style.background_opacity))
    d = ImageDraw.Draw(bar)
    font = ImageFont.truetype(str(brand.font_path_regular), size=style.font_size)

    # Wrap to at most 3 lines based on width
    lines = _wrap_to_width(style.text, font, max_w=fw - 48, max_lines=3, direction=brand.direction)
    line_gap = 4
    line_h = max(font.getbbox("Mg")[3] - font.getbbox("Mg")[1], style.font_size + 4)
    total_h = line_h * len(lines) + line_gap * (len(lines) - 1)
    y = (style.height - total_h) // 2

    for line in lines:
        rendered = _to_display(line, brand.direction)
        bbox = d.textbbox((0, 0), rendered, font=font)
        line_w = bbox[2] - bbox[0]
        x = (fw - line_w) // 2
        d.text((x, y), rendered, font=font, fill=style.text_color)
        y += line_h + line_gap

    target_y = int(fh * style.position_y_pct) - style.height // 2
    return bar, (0, target_y)


def _wrap_to_width(text: str, font: ImageFont.FreeTypeFont, *, max_w: int, max_lines: int, direction: str) -> list[str]:
    words = text.split()
    if not words:
        return [""]
    dummy = Image.new("RGBA", (1, 1))
    d = ImageDraw.Draw(dummy)

    def width_of(s: str) -> int:
        bbox = d.textbbox((0, 0), _to_display(s, direction), font=font)
        return bbox[2] - bbox[0]

    lines: list[str] = []
    current = ""
    for w in words:
        candidate = f"{current} {w}".strip()
        if width_of(candidate) <= max_w or not current:
            current = candidate
        else:
            lines.append(current)
            current = w
            if len(lines) >= max_lines:
                break
    if current and len(lines) < max_lines:
        lines.append(current)
    return lines[:max_lines]
