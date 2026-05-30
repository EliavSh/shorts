"""Branded opening ticker card overlay.

Renders a card matching the reference video's frame 1: company ticker + name +
daily change % with up/down arrow, plus a mini candlestick chart of recent OHLC.
"""
from __future__ import annotations

from dataclasses import dataclass
from io import BytesIO
from pathlib import Path
from collections.abc import Sequence

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
from bidi.algorithm import get_display
from PIL import Image, ImageDraw, ImageFont

from shorts.core.visuals.brand import Brand, hex_to_rgba


@dataclass(frozen=True)
class OHLC:
    open: float
    high: float
    low: float
    close: float


def render_ticker_card(
    *,
    brand: Brand,
    ticker: str,
    name: str,
    change_pct: float,
    ohlc: Sequence[OHLC] | None = None,
) -> Image.Image:
    """Render the opening ticker card.

    Returns an RGBA PIL Image sized brand.ticker_card.width x .height.
    """
    style = brand.ticker_card
    img = Image.new("RGBA", (style.width, style.height), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)

    # Rounded card background
    draw.rounded_rectangle(
        (0, 0, style.width, style.height),
        radius=style.corner_radius,
        fill=hex_to_rgba(style.background, style.background_opacity),
    )

    up = change_pct >= 0
    accent = style.accent_up if up else style.accent_down

    # Fonts — pick sizes proportional to card width.
    f_ticker = ImageFont.truetype(str(brand.font_path), size=72)
    f_name = ImageFont.truetype(str(brand.font_path_regular), size=28)
    f_label = ImageFont.truetype(str(brand.font_path_regular), size=24)
    f_change = ImageFont.truetype(str(brand.font_path), size=64)

    pad_x = 32
    y = 28

    def _disp(s: str) -> str:
        return get_display(s) if brand.direction == "rtl" else s

    draw.text((pad_x, y), ticker.upper(), font=f_ticker, fill=style.text_primary)
    y += 80
    draw.text((pad_x, y), _disp(name), font=f_name, fill=style.text_secondary)
    y += 50

    draw.text((pad_x, y), _disp(_label_daily_change(brand.lang)), font=f_label, fill=style.text_secondary)
    y += 34

    sign = "+" if up else ""
    change_str = f"{sign}{change_pct:.1f}%"
    # Numbers + Latin: render as-is (LTR even inside an RTL card).
    draw.text((pad_x, y), change_str, font=f_change, fill=accent)

    # Up/down arrow next to change text
    bbox = draw.textbbox((pad_x, y), change_str, font=f_change)
    arrow_x = bbox[2] + 14
    arrow_y_top = bbox[1] + 14
    arrow_y_bot = bbox[3] - 8
    arrow_w = 32
    if up:
        draw.polygon(
            [
                (arrow_x, arrow_y_bot),
                (arrow_x + arrow_w, arrow_y_bot),
                (arrow_x + arrow_w / 2, arrow_y_top),
            ],
            fill=accent,
        )
    else:
        draw.polygon(
            [
                (arrow_x, arrow_y_top),
                (arrow_x + arrow_w, arrow_y_top),
                (arrow_x + arrow_w / 2, arrow_y_bot),
            ],
            fill=accent,
        )
    y = bbox[3] + 24

    # Mini chart (candlestick) — uses last `ohlc` series, or a synthetic one
    chart = _render_mini_chart(
        ohlc=list(ohlc) if ohlc else _synthetic_ohlc(up=up, n=30),
        width=style.width - 2 * pad_x,
        height=style.height - y - 24,
        accent_up=style.accent_up,
        accent_down=style.accent_down,
    )
    img.alpha_composite(chart, (pad_x, y))
    return img


def _label_daily_change(lang: str) -> str:
    return {"he": "שינוי יומי", "en": "Daily Change"}.get(lang, "Daily Change")


def _render_mini_chart(
    *,
    ohlc: list[OHLC],
    width: int,
    height: int,
    accent_up: str,
    accent_down: str,
) -> Image.Image:
    fig = plt.figure(figsize=(width / 100, height / 100), dpi=100)
    ax = fig.add_axes([0.0, 0.0, 1.0, 1.0])
    ax.set_facecolor("none")
    fig.patch.set_alpha(0.0)

    n = len(ohlc)
    wick_w = max(0.06, 0.6 / max(1, n / 30))

    for i, c in enumerate(ohlc):
        color = accent_up if c.close >= c.open else accent_down
        ax.vlines(i, c.low, c.high, color=color, linewidth=1.0)
        body_low = min(c.open, c.close)
        body_high = max(c.open, c.close)
        ax.add_patch(
            plt.Rectangle(
                (i - wick_w / 2, body_low),
                wick_w,
                max(body_high - body_low, (max(c.high, c.open, c.close) * 0.001)),
                facecolor=color,
                edgecolor=color,
                linewidth=0,
            )
        )

    lows = [c.low for c in ohlc]
    highs = [c.high for c in ohlc]
    pad = (max(highs) - min(lows)) * 0.08 or 0.5
    ax.set_xlim(-1, n)
    ax.set_ylim(min(lows) - pad, max(highs) + pad)
    ax.axis("off")

    buf = BytesIO()
    fig.savefig(buf, format="png", transparent=True, bbox_inches="tight", pad_inches=0.0)
    plt.close(fig)
    buf.seek(0)
    chart_img = Image.open(buf).convert("RGBA")
    if chart_img.size != (width, height):
        chart_img = chart_img.resize((width, height), Image.Resampling.LANCZOS)
    return chart_img


def _synthetic_ohlc(*, up: bool, n: int = 30) -> list[OHLC]:
    rng = np.random.default_rng(42)
    trend = np.linspace(0, 1, n) * (1 if up else -1)
    noise = rng.normal(0, 0.4, size=n)
    closes = 100 + np.cumsum(trend + noise)
    opens = np.concatenate([[100.0], closes[:-1]])
    highs = np.maximum(opens, closes) + rng.uniform(0.1, 0.6, size=n)
    lows = np.minimum(opens, closes) - rng.uniform(0.1, 0.6, size=n)
    return [OHLC(o, h, l, c) for o, h, l, c in zip(opens, highs, lows, closes, strict=False)]


def save_demo(out_path: Path) -> Path:
    """Render a demo card matching the reference scenario (NVDA +1.2%)."""
    from shorts.pipelines.stocks.visuals.brand import load_brand

    brand = load_brand("en")
    img = render_ticker_card(brand=brand, ticker="NVDA", name="Nvidia", change_pct=1.2)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    img.save(out_path)
    return out_path
