"""Native-9:16 candlestick / line chart — clean, labelled, no chrome.

Designed for the beat that says "the stock did X over Y" — viewer needs to see
the shape of price action, big and unambiguous.
"""
from __future__ import annotations

from io import BytesIO

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
from PIL import Image, ImageDraw, ImageFont

from ..brand import Brand
from ._textfit import fit_font

FRAME_W = 1080
FRAME_H = 1920


def render(*, brand: Brand, title: str,
           ohlc: list[tuple[float, float, float, float]] | None = None,
           line: list[float] | None = None,
           label_start: str = "", label_end: str = "",
           direction: str = "neutral") -> Image.Image:
    """Render a hero chart at native 9:16.

    Use OHLC for candlestick (typical) or `line` for a line-chart variant.
    `label_start`/`label_end` annotate the first and last data point.
    """
    style = brand.ticker_card
    img = Image.new("RGB", (FRAME_W, FRAME_H), (10, 22, 46))
    draw = ImageDraw.Draw(img, "RGBA")

    f_title = fit_font(brand.font_path, title, max_width=FRAME_W - 100, start=58, min_size=32)
    f_anno = ImageFont.truetype(str(brand.font_path), size=44)
    f_anno_small = ImageFont.truetype(str(brand.font_path_regular), size=34)

    # Title
    bbox = draw.textbbox((0, 0), title, font=f_title)
    draw.text(((FRAME_W - (bbox[2] - bbox[0])) // 2, 220), title, font=f_title, fill="#FFFFFF")

    # Build chart with matplotlib at the right pixel size
    chart_w = FRAME_W - 80
    chart_h = 1100
    fig = plt.figure(figsize=(chart_w / 100, chart_h / 100), dpi=100)
    ax = fig.add_axes([0.0, 0.0, 1.0, 1.0])
    ax.set_facecolor("none")
    fig.patch.set_alpha(0.0)

    if ohlc:
        n = len(ohlc)
        for i, (o, h, l, c) in enumerate(ohlc):
            up = c >= o
            color = style.accent_up if up else style.accent_down
            ax.vlines(i, l, h, color=color, linewidth=1.4)
            body_low, body_high = (min(o, c), max(o, c))
            ax.add_patch(plt.Rectangle((i - 0.32, body_low), 0.64,
                                       max(body_high - body_low, h * 0.001 + 1e-6),
                                       facecolor=color, edgecolor=color, linewidth=0))
        lows = [c[2] for c in ohlc]
        highs = [c[1] for c in ohlc]
        pad = (max(highs) - min(lows)) * 0.1 or 1.0
        ax.set_xlim(-1, n)
        ax.set_ylim(min(lows) - pad, max(highs) + pad)
    elif line:
        n = len(line)
        up = line[-1] >= line[0]
        color = style.accent_up if up else style.accent_down
        ax.plot(range(n), line, color=color, linewidth=4.0)
        ax.fill_between(range(n), line, min(line),
                        color=color, alpha=0.18)
        pad = (max(line) - min(line)) * 0.12 or 1.0
        ax.set_xlim(0, n - 1)
        ax.set_ylim(min(line) - pad, max(line) + pad)

    ax.axis("off")

    buf = BytesIO()
    fig.savefig(buf, format="png", transparent=True, bbox_inches="tight", pad_inches=0.0)
    plt.close(fig)
    buf.seek(0)
    chart = Image.open(buf).convert("RGBA").resize((chart_w, chart_h), Image.Resampling.LANCZOS)
    img.paste(chart, (40, 380), chart)

    # Endpoint annotations
    if label_start:
        draw.text((60, 1520), label_start, font=f_anno_small, fill="#A8C3E8")
    if label_end:
        bbox = draw.textbbox((0, 0), label_end, font=f_anno)
        accent = style.accent_up if direction == "up" else style.accent_down if direction == "down" else "#FFFFFF"
        draw.text((FRAME_W - (bbox[2] - bbox[0]) - 60, 1505),
                  label_end, font=f_anno, fill=accent)

    return img
