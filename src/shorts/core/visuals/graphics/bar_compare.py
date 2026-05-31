"""Bar-comparison graphic — two or three labelled bars side-by-side.

For before/after, this-quarter vs last-quarter, A-vs-B revenue, etc.
"""
from __future__ import annotations

from PIL import Image, ImageDraw, ImageFont

from ..brand import Brand
from ._textfit import fit_font

FRAME_W = 1080
FRAME_H = 1920


def render(*, brand: Brand, title: str,
           bars: list[dict],
           unit: str = "") -> Image.Image:
    """Render a vertical bar chart with N (2-3) bars.

    Args:
        title: top headline of the graphic
        bars: list of {label, value, color?} dicts. value is a float; the largest
              determines bar-height scaling.
        unit: optional unit suffix shown after each value ("B", "M", "%", "$")
    """
    style = brand.ticker_card
    img = Image.new("RGB", (FRAME_W, FRAME_H), (12, 24, 48))
    draw = ImageDraw.Draw(img, "RGBA")

    f_title = fit_font(brand.font_path, title, max_width=FRAME_W - 120, start=64, min_size=34)
    f_value = ImageFont.truetype(str(brand.font_path), size=84)
    f_label = ImageFont.truetype(str(brand.font_path_regular), size=42)

    # Title
    bbox = draw.textbbox((0, 0), title, font=f_title)
    draw.text(((FRAME_W - (bbox[2] - bbox[0])) // 2, 260), title, font=f_title, fill="#FFFFFF")

    # Layout: bars in a central band
    n = len(bars)
    if n < 1:
        return img
    chart_top = 580
    chart_bottom = 1480
    chart_h = chart_bottom - chart_top

    band_w = FRAME_W - 200
    bar_w = min(280, band_w // (n * 2))
    gap = (band_w - n * bar_w) // (n + 1)

    max_val = max(b["value"] for b in bars) or 1

    for i, b in enumerate(bars):
        x = 100 + gap + i * (bar_w + gap)
        rel = b["value"] / max_val
        h = int(chart_h * rel)
        y0 = chart_bottom - h
        color = b.get("color") or (style.accent_up if rel >= 0.99 else "#3B82F6")
        draw.rounded_rectangle((x, y0, x + bar_w, chart_bottom),
                               radius=20, fill=color)

        # Value label above the bar
        v_text = _fmt_value(b["value"], unit)
        bbox = draw.textbbox((0, 0), v_text, font=f_value)
        v_w = bbox[2] - bbox[0]
        draw.text((x + (bar_w - v_w) // 2, y0 - 110), v_text, font=f_value, fill="#FFFFFF")

        # Category label below the chart axis
        label = b["label"]
        bbox = draw.textbbox((0, 0), label, font=f_label)
        l_w = bbox[2] - bbox[0]
        draw.text((x + (bar_w - l_w) // 2, chart_bottom + 30), label,
                  font=f_label, fill="#A8C3E8")

    # Axis line
    draw.line((100, chart_bottom + 2, FRAME_W - 100, chart_bottom + 2),
              fill=(60, 70, 90, 255), width=3)

    return img


def _fmt_value(v: float, unit: str) -> str:
    if abs(v) >= 1000:
        return f"{v / 1000:.1f}K{unit}"
    if v == int(v):
        return f"{int(v)}{unit}"
    return f"{v:.1f}{unit}"
