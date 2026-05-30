"""Generated big-number hero — one striking number, one short label.

Designed to satisfy R2: when narration lands on one striking number, that
number must be the unambiguous focal point of the frame.
"""
from __future__ import annotations

from bidi.algorithm import get_display
from PIL import Image, ImageDraw, ImageFont

from ..brand import Brand, hex_to_rgba

FRAME_W = 1080
FRAME_H = 1920


def render(*, brand: Brand, number: str, label: str,
           direction: str = "neutral",
           context: str | None = None) -> Image.Image:
    """Return a 1080x1920 image with a huge number, a short label below.

    Args:
        number: the headline number string ("$3.2B", "+85%", "500,000", "3,000")
        label: a short caption underneath ("annual revenue", "Q3 growth", "chip exports")
        direction: 'up' | 'down' | 'neutral' — picks accent color
        context: optional smaller line above the number, e.g. "Nvidia just announced"
    """
    style = brand.ticker_card

    bg_top = (16, 28, 52) if direction == "neutral" else (12, 24, 48)
    img = Image.new("RGB", (FRAME_W, FRAME_H), bg_top)
    draw = ImageDraw.Draw(img, "RGBA")

    # Pick accent
    if direction == "up":
        accent = style.accent_up
    elif direction == "down":
        accent = style.accent_down
    else:
        accent = "#FFFFFF"

    # Auto-scale the number font so it fits comfortably in the frame width.
    base_size = _fit_size(brand.font_path, number, max_width=FRAME_W - 200, start=420)
    f_number = ImageFont.truetype(str(brand.font_path), size=base_size)
    f_label = ImageFont.truetype(str(brand.font_path), size=72)
    f_context = ImageFont.truetype(str(brand.font_path_regular), size=44)

    # Vertical stack centered
    bbox_n = draw.textbbox((0, 0), number, font=f_number)
    n_w = bbox_n[2] - bbox_n[0]
    n_h = bbox_n[3] - bbox_n[1]

    label_disp = get_display(label) if brand.direction == "rtl" else label
    bbox_l = draw.textbbox((0, 0), label_disp, font=f_label)
    l_w = bbox_l[2] - bbox_l[0]
    l_h = bbox_l[3] - bbox_l[1]

    block_h = n_h + 60 + l_h
    y0 = (FRAME_H - block_h) // 2

    if context:
        ctx_disp = get_display(context) if brand.direction == "rtl" else context
        bbox_c = draw.textbbox((0, 0), ctx_disp, font=f_context)
        c_w = bbox_c[2] - bbox_c[0]
        draw.text(((FRAME_W - c_w) // 2, y0 - 130), ctx_disp,
                  font=f_context, fill="#A8C3E8")

    # Decorative underline rect behind the number — subtle accent strip
    strip_w = min(int(n_w * 1.15), FRAME_W - 120)
    strip_x0 = (FRAME_W - strip_w) // 2
    strip_y = y0 + n_h + 12
    draw.rounded_rectangle(
        (strip_x0, strip_y, strip_x0 + strip_w, strip_y + 6),
        radius=3,
        fill=hex_to_rgba(accent, 0.7),
    )

    draw.text(((FRAME_W - n_w) // 2, y0 - bbox_n[1]),
              number, font=f_number, fill=accent)

    draw.text(((FRAME_W - l_w) // 2, y0 + n_h + 60 - bbox_l[1]),
              label_disp, font=f_label, fill="#FFFFFF")

    return img


def _fit_size(font_path, text: str, *, max_width: int, start: int) -> int:
    """Iteratively shrink font size until text fits the width."""
    dummy = Image.new("RGB", (1, 1))
    d = ImageDraw.Draw(dummy)
    size = start
    while size > 80:
        f = ImageFont.truetype(str(font_path), size=size)
        bbox = d.textbbox((0, 0), text, font=f)
        if (bbox[2] - bbox[0]) <= max_width:
            return size
        size -= 16
    return 80
