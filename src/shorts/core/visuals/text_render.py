"""Render text → PNG with Pillow + Pilmoji.

ffmpeg's drawtext can't measure or wrap text and can't render emoji. We use
Pillow for layout and Pilmoji to composite Twemoji PNGs in place of emoji
glyphs (since Arial/Impact don't include emoji in their glyph set).
"""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont
from pilmoji import Pilmoji
from pilmoji.source import GoogleEmojiSource

# Windows system fonts (tried in order). Custom font in assets/fonts/ wins.
REPO_ROOT = Path(__file__).resolve().parents[3]
FONT_SEARCH = [
    REPO_ROOT / "assets" / "fonts" / "Anton-Regular.ttf",
    REPO_ROOT / "assets" / "fonts" / "Bangers-Regular.ttf",
    Path(r"C:\Windows\Fonts\impact.ttf"),
    Path(r"C:\Windows\Fonts\arialbd.ttf"),
    Path(r"C:\Windows\Fonts\Arial.ttf"),
    # Common Linux/Mac fallbacks
    Path("/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf"),
    Path("/System/Library/Fonts/Supplemental/Arial Bold.ttf"),
]


def _find_font() -> Path:
    for p in FONT_SEARCH:
        if p.exists():
            return p
    raise FileNotFoundError(
        "No display font available. Drop a .ttf into assets/fonts/ "
        "(Anton or Bangers from Google Fonts recommended)."
    )


def _wrap_to_fit(
    text: str,
    font: ImageFont.FreeTypeFont,
    max_width: int,
) -> list[str]:
    """Greedy word-wrap so no line exceeds max_width pixels."""
    words = text.split()
    if not words:
        return []
    lines: list[str] = []
    cur: list[str] = []
    for w in words:
        trial = " ".join(cur + [w])
        bbox = font.getbbox(trial)
        if bbox[2] - bbox[0] <= max_width:
            cur.append(w)
        else:
            if cur:
                lines.append(" ".join(cur))
            cur = [w]
    if cur:
        lines.append(" ".join(cur))
    return lines


def _fit_font_size(
    text: str,
    font_path: Path,
    max_width: int,
    max_lines: int,
    initial_size: int,
    min_size: int = 36,
) -> tuple[ImageFont.FreeTypeFont, list[str]]:
    """Shrink size until text wraps to <= max_lines."""
    size = initial_size
    while size >= min_size:
        font = ImageFont.truetype(str(font_path), size)
        lines = _wrap_to_fit(text, font, max_width)
        if len(lines) <= max_lines:
            return font, lines
        size -= 4
    font = ImageFont.truetype(str(font_path), min_size)
    return font, _wrap_to_fit(text, font, max_width)


@dataclass
class TextStyle:
    font_size: int = 96
    max_lines: int = 2
    color: tuple[int, int, int] = (255, 212, 0)  # brawl yellow
    stroke_color: tuple[int, int, int] = (0, 0, 0)
    stroke_width: int = 8
    shadow_offset: tuple[int, int] = (0, 6)
    shadow_color: tuple[int, int, int, int] = (0, 0, 0, 160)
    line_spacing: int = 8
    # Optional sticker-style pill background behind the text.
    bg_color: tuple[int, int, int, int] | None = None      # e.g. (0,0,0,200)
    bg_radius: int = 28
    bg_pad_x: int = 36
    bg_pad_y: int = 18


def render_text_png(
    text: str,
    out_path: Path,
    canvas_w: int = 1080,
    canvas_h: int = 1920,
    margin_x: int = 60,
    style: TextStyle | None = None,
) -> tuple[Path, int, int]:
    """Render a text overlay (transparent PNG) sized to fit canvas_w.

    Returns (path, content_w, content_h) — the actual pixel extent of the text
    so the caller can compute centered overlay positions.
    """
    style = style or TextStyle()
    font_path = _find_font()
    max_width = canvas_w - 2 * margin_x

    font, lines = _fit_font_size(
        text=text,
        font_path=font_path,
        max_width=max_width,
        max_lines=style.max_lines,
        initial_size=style.font_size,
    )

    # Measure final block.
    line_heights: list[int] = []
    line_widths: list[int] = []
    for ln in lines:
        bbox = font.getbbox(ln)
        line_widths.append(bbox[2] - bbox[0])
        # Use font.size as height estimate (more reliable than bbox vertical).
        line_heights.append(int(font.size * 1.15))
    content_w = max(line_widths) if line_widths else 0
    content_h = sum(line_heights) + style.line_spacing * (len(lines) - 1)

    # Padding to accommodate stroke + shadow + optional pill background.
    base_pad = style.stroke_width + max(abs(style.shadow_offset[0]), abs(style.shadow_offset[1])) + 8
    if style.bg_color is not None:
        pad_x = max(base_pad, style.bg_pad_x + 4)
        pad_y = max(base_pad, style.bg_pad_y + 4)
    else:
        pad_x = pad_y = base_pad
    pad = pad_y  # used for shadow rendering offset later
    img_w = content_w + 2 * pad_x
    img_h = content_h + 2 * pad_y

    img = Image.new("RGBA", (img_w, img_h), (0, 0, 0, 0))

    # Optional sticker pill behind text. Drawn first so text sits on top.
    if style.bg_color is not None:
        bx0 = pad_x - style.bg_pad_x
        by0 = pad_y - style.bg_pad_y
        bx1 = pad_x + content_w + style.bg_pad_x
        by1 = pad_y + content_h + style.bg_pad_y
        bx0 = max(0, bx0)
        by0 = max(0, by0)
        bx1 = min(img_w, bx1)
        by1 = min(img_h, by1)
        ImageDraw.Draw(img).rounded_rectangle(
            (bx0, by0, bx1, by1),
            radius=style.bg_radius,
            fill=style.bg_color,
        )

    # Pilmoji renders text + composites Twemoji PNGs where emoji glyphs appear.
    # It supports stroke_width/stroke_fill on text but does not draw stroke
    # around emoji (Twemoji PNGs already have built-in style). Shadow we draw
    # ourselves underneath.
    with Pilmoji(img, source=GoogleEmojiSource) as pm:
        y = pad_y
        for ln, lh in zip(lines, line_heights):
            # Use a plain text bbox for centering (emoji ~ same advance width).
            bbox = font.getbbox(ln)
            line_w = bbox[2] - bbox[0]
            x = (img_w - line_w) // 2 - bbox[0]
            # Shadow pass.
            sx, sy = style.shadow_offset
            if sx or sy:
                pm.text(
                    (x + sx, y + sy),
                    ln,
                    font=font,
                    fill=style.shadow_color,
                    emoji_scale_factor=1.0,
                )
            # Main text (stroked).
            pm.text(
                (x, y),
                ln,
                font=font,
                fill=style.color + (255,),
                stroke_width=style.stroke_width,
                stroke_fill=style.stroke_color + (255,),
                emoji_scale_factor=1.05,
                emoji_position_offset=(0, 8),
            )
            y += lh + style.line_spacing

    img.save(out_path, "PNG")
    return out_path, img_w, img_h
