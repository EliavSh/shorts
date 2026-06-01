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


_PAD_X = 32


def render_ticker_card(
    *,
    brand: Brand,
    ticker: str,
    name: str,
    change_pct: float,
    ohlc: Sequence[OHLC] | None = None,
) -> Image.Image:
    """Render the opening ticker card.

    Modern layout: bold ticker + accent underline, a rounded change badge, the
    company name wrapped to ≤2 auto-fit lines (never overflows), and a mini
    candlestick chart filling the rest. Returns an RGBA PIL Image sized
    brand.ticker_card.width x .height.
    """
    style = brand.ticker_card
    img = Image.new("RGBA", (style.width, style.height), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)
    draw.rounded_rectangle(
        (0, 0, style.width, style.height),
        radius=style.corner_radius,
        fill=hex_to_rgba(style.background, style.background_opacity),
    )

    up = change_pct >= 0
    accent = style.accent_up if up else style.accent_down
    max_w = style.width - 2 * _PAD_X

    def _disp(s: str) -> str:
        return get_display(s) if brand.direction == "rtl" else s

    y = 26
    # Ticker symbol + a short accent underline.
    f_ticker = ImageFont.truetype(str(brand.font_path), size=76)
    draw.text((_PAD_X, y), ticker.upper(), font=f_ticker, fill=style.text_primary)
    tb = draw.textbbox((_PAD_X, y), ticker.upper(), font=f_ticker)
    uy = tb[3] + 8
    draw.rounded_rectangle((_PAD_X, uy, _PAD_X + min(tb[2] - tb[0], 132), uy + 5),
                           radius=3, fill=accent)
    y = uy + 5 + 20

    # Change badge (arrow + %).
    y = _draw_change_badge(draw, brand, _PAD_X, y, change_pct, accent, up, font_size=40) + 20

    # Company name — wrapped + auto-fit so long names (e.g. "Taiwan
    # Semiconductor Manufacturing") never spill past the card edge.
    f_name, lines = _fit_name(draw, _disp(name), str(brand.font_path_regular), max_w)
    for ln in lines:
        draw.text((_PAD_X, y), ln, font=f_name, fill=style.text_secondary)
        lb = draw.textbbox((_PAD_X, y), ln, font=f_name)
        y = lb[3] + 6
    y += 14

    # Mini candlestick chart fills the remaining space (skip if too cramped).
    chart_h = style.height - y - 24
    if chart_h >= 60:
        chart = _render_mini_chart(
            ohlc=list(ohlc) if ohlc else _synthetic_ohlc(up=up, n=30),
            width=max_w, height=chart_h,
            accent_up=style.accent_up, accent_down=style.accent_down,
        )
        img.alpha_composite(chart, (_PAD_X, y))
    return img


def render_compare_card(*, brand: Brand, primary, secondary) -> Image.Image:
    """Compact dual-ticker card — both symbols + change badges stacked with a
    divider. Shown at the pivot of a two-stock clip so the companies appear
    together. `primary`/`secondary` are TickerSpec-like (`.ticker`, `.change_pct`)."""
    style = brand.ticker_card
    w = style.width
    row_h, gap, top = 92, 22, 26
    h = top + row_h + gap + row_h + top
    img = Image.new("RGBA", (w, h), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)
    draw.rounded_rectangle((0, 0, w, h), radius=style.corner_radius,
                           fill=hex_to_rgba(style.background, style.background_opacity))

    f_t = ImageFont.truetype(str(brand.font_path), size=48)

    def _row(t, y: int) -> None:
        up = t.change_pct >= 0
        accent = style.accent_up if up else style.accent_down
        draw.text((_PAD_X, y + 8), t.ticker.upper(), font=f_t, fill=style.text_primary)
        bw, _bh = _change_badge_size(draw, brand, t.change_pct, font_size=34)
        _draw_change_badge(draw, brand, w - _PAD_X - bw, y + 14, t.change_pct,
                           accent, up, font_size=34)

    _row(primary, top)
    dy = top + row_h + gap // 2
    draw.line((_PAD_X, dy, w - _PAD_X, dy),
              fill=hex_to_rgba(style.text_secondary, 0.25), width=2)
    _row(secondary, top + row_h + gap)
    return img


def _label_daily_change(lang: str) -> str:
    return {"he": "שינוי יומי", "en": "Daily Change"}.get(lang, "Daily Change")


# ── Text fitting + change badge helpers ──────────────────────────────────────

def _change_badge_size(draw, brand: Brand, change_pct: float, *, font_size: int) -> tuple[int, int]:
    f = ImageFont.truetype(str(brand.font_path), size=font_size)
    text = f"{'+' if change_pct >= 0 else ''}{change_pct:.1f}%"
    tw = draw.textlength(text, font=f)
    arrow_w, gap, pad_h, pad_v, tri_h = 22, 12, 18, 11, int(font_size * 0.55)
    pill_w = int(pad_h + arrow_w + gap + tw + pad_h)
    pill_h = int(max(font_size, tri_h) + 2 * pad_v)
    return pill_w, pill_h


def _draw_change_badge(draw, brand: Brand, x: int, y: int, change_pct: float,
                       accent: str, up: bool, *, font_size: int) -> int:
    """Draw a rounded pill: ▲/▼ + signed percent. Returns its bottom y."""
    f = ImageFont.truetype(str(brand.font_path), size=font_size)
    text = f"{'+' if up else ''}{change_pct:.1f}%"
    tw = draw.textlength(text, font=f)
    arrow_w, gap, pad_h, pad_v, tri_h = 22, 12, 18, 11, int(font_size * 0.55)
    pill_w = int(pad_h + arrow_w + gap + tw + pad_h)
    pill_h = int(max(font_size, tri_h) + 2 * pad_v)
    draw.rounded_rectangle((x, y, x + pill_w, y + pill_h), radius=pill_h // 2,
                           fill=hex_to_rgba(accent, 0.16))
    ax = x + pad_h
    ay_top = y + (pill_h - tri_h) // 2
    ay_bot = ay_top + tri_h
    cx = ax + arrow_w / 2
    if up:
        draw.polygon([(ax, ay_bot), (ax + arrow_w, ay_bot), (cx, ay_top)], fill=accent)
    else:
        draw.polygon([(ax, ay_top), (ax + arrow_w, ay_top), (cx, ay_bot)], fill=accent)
    draw.text((ax + arrow_w + gap, y + (pill_h - font_size) // 2 - 1), text, font=f, fill=accent)
    return y + pill_h


def _fits(draw, text: str, font, max_w: int, max_lines: int) -> bool:
    """True if `text` greedily wraps into ≤ max_lines, each within max_w."""
    words = text.split()
    i, lines = 0, 0
    while i < len(words):
        if lines == max_lines:
            return False
        if draw.textlength(words[i], font=font) > max_w:
            return False  # a single word is too wide
        cur = words[i]; i += 1
        while i < len(words) and draw.textlength(f"{cur} {words[i]}", font=font) <= max_w:
            cur = f"{cur} {words[i]}"; i += 1
        lines += 1
    return True


def _wrap_lines(draw, text: str, font, max_w: int, max_lines: int) -> list[str]:
    """Greedy wrap into ≤ max_lines; ellipsize the last line if content spills."""
    words = text.split()
    lines: list[str] = []
    i = 0
    while i < len(words) and len(lines) < max_lines:
        cur = words[i]; i += 1
        while i < len(words) and draw.textlength(f"{cur} {words[i]}", font=font) <= max_w:
            cur = f"{cur} {words[i]}"; i += 1
        lines.append(cur)
    if i < len(words) and lines:  # leftover words → fold into last line, ellipsized
        lines[-1] = _ellipsize(draw, lines[-1] + " " + " ".join(words[i:]), font, max_w)
    return [ln if draw.textlength(ln, font=font) <= max_w
            else _ellipsize(draw, ln, font, max_w) for ln in lines]


def _ellipsize(draw, text: str, font, max_w: int) -> str:
    if draw.textlength(text, font=font) <= max_w:
        return text
    while text and draw.textlength(text + "…", font=font) > max_w:
        text = text[:-1].rstrip()
    return (text + "…") if text else "…"


def _fit_name(draw, name: str, font_path: str, max_w: int, *,
              start: int = 34, floor: int = 22, max_lines: int = 2):
    """Pick the largest font (start→floor) at which `name` wraps into ≤ max_lines,
    then wrap. Guarantees the name never overflows the card."""
    size = start
    while size >= floor:
        font = ImageFont.truetype(font_path, size)
        if _fits(draw, name, font, max_w, max_lines):
            return font, _wrap_lines(draw, name, font, max_w, max_lines)
        size -= 2
    font = ImageFont.truetype(font_path, floor)
    return font, _wrap_lines(draw, name, font, max_w, max_lines)


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
    """Render demo cards for visual review: short name, a long overflow-prone
    name, a down move, and the two-ticker compare card. Writes <stem>_*.png next
    to out_path and returns the directory."""
    from dataclasses import dataclass

    from shorts.pipelines.stocks.visuals.brand import load_brand

    brand = load_brand("en")
    out_dir = out_path.parent
    out_dir.mkdir(parents=True, exist_ok=True)
    stem = out_path.stem

    render_ticker_card(brand=brand, ticker="NVDA", name="Nvidia", change_pct=1.2
                       ).save(out_dir / f"{stem}_nvda.png")
    render_ticker_card(brand=brand, ticker="TSM",
                       name="Taiwan Semiconductor Manufacturing", change_pct=1.8
                       ).save(out_dir / f"{stem}_tsm_longname.png")
    render_ticker_card(brand=brand, ticker="AAPL", name="Apple", change_pct=-2.3
                       ).save(out_dir / f"{stem}_aapl_down.png")

    @dataclass
    class _T:
        ticker: str
        change_pct: float

    render_compare_card(brand=brand, primary=_T("NVDA", 2.5), secondary=_T("TSM", 1.8)
                        ).save(out_dir / f"{stem}_compare.png")
    return out_dir
