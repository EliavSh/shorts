"""Generated calendar with one date prominently highlighted.

Designed to satisfy R2: when narration cites a specific date, the visual must
make that date unambiguously prominent within 1 second.
"""
from __future__ import annotations

import calendar
from datetime import date

from bidi.algorithm import get_display
from PIL import Image, ImageDraw, ImageFont

from ..brand import Brand, hex_to_rgba

FRAME_W = 1080
FRAME_H = 1920


def render(*, brand: Brand, year: int, month: int, day: int,
           subtitle: str | None = None) -> Image.Image:
    """Return a 1080x1920 image with a month calendar, the given day circled
    and color-popped. The month name is at the top, the day is centered below.

    Args:
        year, month, day: the date to highlight (must be a real date)
        subtitle: optional one-line caption under the calendar
    """
    style = brand.ticker_card
    target_d = date(year, month, day)

    img = Image.new("RGB", (FRAME_W, FRAME_H), (12, 24, 48))
    draw = ImageDraw.Draw(img, "RGBA")

    f_month = ImageFont.truetype(str(brand.font_path), size=72)
    f_day_label = ImageFont.truetype(str(brand.font_path_regular), size=36)
    f_cell = ImageFont.truetype(str(brand.font_path), size=58)
    f_cell_dim = ImageFont.truetype(str(brand.font_path_regular), size=58)
    f_big = ImageFont.truetype(str(brand.font_path), size=240)
    f_subtitle = ImageFont.truetype(str(brand.font_path_regular), size=44)

    # ── Header: Month YEAR
    header = f"{calendar.month_name[month]} {year}"
    bbox = draw.textbbox((0, 0), header, font=f_month)
    draw.text(((FRAME_W - (bbox[2] - bbox[0])) // 2, 180), header, font=f_month, fill="#FFFFFF")

    # ── Big hero day number
    day_str = str(day)
    bbox = draw.textbbox((0, 0), day_str, font=f_big)
    big_y = 360
    draw.text(((FRAME_W - (bbox[2] - bbox[0])) // 2, big_y), day_str, font=f_big, fill=style.accent_up)

    # Day-of-week label
    dow = calendar.day_name[target_d.weekday()].upper()
    bbox = draw.textbbox((0, 0), dow, font=f_day_label)
    draw.text(((FRAME_W - (bbox[2] - bbox[0])) // 2, big_y + 290), dow,
              font=f_day_label, fill="#A8C3E8")

    # ── Mini calendar grid
    grid_top = big_y + 380
    cell_w = 130
    cell_h = 130
    grid_w = 7 * cell_w
    grid_x0 = (FRAME_W - grid_w) // 2

    # Weekday headers
    f_wdh = ImageFont.truetype(str(brand.font_path_regular), size=32)
    weekdays = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]
    for i, wd in enumerate(weekdays):
        bbox = draw.textbbox((0, 0), wd, font=f_wdh)
        draw.text(
            (grid_x0 + i * cell_w + (cell_w - (bbox[2] - bbox[0])) // 2, grid_top - 50),
            wd, font=f_wdh, fill="#A8C3E8",
        )

    # Month calendar matrix (weeks of [day or 0])
    cal = calendar.Calendar(firstweekday=0).monthdayscalendar(year, month)
    for row, week in enumerate(cal):
        for col, d in enumerate(week):
            if d == 0:
                continue
            cx = grid_x0 + col * cell_w + cell_w // 2
            cy = grid_top + row * cell_h + cell_h // 2
            is_target = d == day
            if is_target:
                # Circle highlight
                r = 56
                draw.ellipse((cx - r, cy - r, cx + r, cy + r),
                             fill=hex_to_rgba(style.accent_up, 1.0))
                color = "#0B1F3A"
                font = f_cell
            else:
                color = "#FFFFFF"
                font = f_cell_dim
            t = str(d)
            bbox = draw.textbbox((0, 0), t, font=font)
            tw = bbox[2] - bbox[0]
            th = bbox[3] - bbox[1]
            draw.text((cx - tw // 2, cy - th // 2 - bbox[1]), t, font=font, fill=color)

    # ── Optional subtitle
    if subtitle:
        subtitle_disp = get_display(subtitle) if brand.direction == "rtl" else subtitle
        bbox = draw.textbbox((0, 0), subtitle_disp, font=f_subtitle)
        sub_y = grid_top + len(cal) * cell_h + 80
        draw.text(((FRAME_W - (bbox[2] - bbox[0])) // 2, sub_y),
                  subtitle_disp, font=f_subtitle, fill="#E5E7EB")

    return img
