"""RTL/LTR-aware caption renderer.

Produces a transparent PNG with a translucent pill containing 1-2 lines of
text, sized for a 1080x1920 frame. Hebrew text is processed via python-bidi so
it renders in the correct visual order on PIL.
"""
from __future__ import annotations


from bidi.algorithm import get_display
from PIL import Image, ImageDraw, ImageFont

from .brand import Brand, hex_to_rgba

FRAME_W = 1080
FRAME_H = 1920


def render_caption(
    *,
    brand: Brand,
    text: str,
    frame_size: tuple[int, int] = (FRAME_W, FRAME_H),
) -> tuple[Image.Image, tuple[int, int]]:
    """Render a caption pill.

    Returns (image, (x, y)) where (x, y) is the top-left placement in the frame.
    """
    style = brand.captions
    font = ImageFont.truetype(str(brand.font_path), size=style.font_size)

    # Hard pixel budget: the pill (text + horizontal padding) must never exceed
    # the frame's 90% safe area. Wrapping is measured against the real font so
    # no caption can render out of bounds, regardless of glyph widths or long
    # words. max_chars stays as a soft secondary cap for line aesthetics.
    fw = frame_size[0]
    max_text_w = int(fw * 0.90) - 2 * style.pill_padding_x
    lines = _wrap_text(
        text,
        max_chars=style.max_chars_per_line,
        max_lines=style.max_lines,
        font=font,
        max_text_w=max_text_w,
    )
    rendered_lines = [_to_display(line, brand.direction) for line in lines]

    # Measure
    line_heights: list[int] = []
    line_widths: list[int] = []
    ascent_descent_pad = max(8, style.font_size // 6)
    dummy = Image.new("RGBA", (1, 1))
    d = ImageDraw.Draw(dummy)
    for line in rendered_lines:
        bbox = d.textbbox((0, 0), line, font=font)
        line_widths.append(bbox[2] - bbox[0])
        line_heights.append(bbox[3] - bbox[1] + ascent_descent_pad)

    line_gap = max(6, style.font_size // 8)
    content_w = max(line_widths) if line_widths else 0
    content_h = sum(line_heights) + line_gap * (len(line_heights) - 1) if line_heights else 0

    pill_w = content_w + 2 * style.pill_padding_x
    pill_h = content_h + 2 * style.pill_padding_y

    img = Image.new("RGBA", (pill_w, pill_h), (0, 0, 0, 0))
    pd = ImageDraw.Draw(img)
    pd.rounded_rectangle(
        (0, 0, pill_w, pill_h),
        radius=style.pill_corner_radius,
        fill=hex_to_rgba(style.pill_color, style.pill_opacity),
    )

    y = style.pill_padding_y
    for line, lw, lh in zip(rendered_lines, line_widths, line_heights, strict=False):
        # Both RTL and LTR are visually centered in the pill — matches reference.
        x = (pill_w - lw) // 2
        pd.text((x, y), line, font=font, fill=style.text_color)
        y += lh + line_gap

    fw, fh = frame_size
    target_y = int(fh * style.position_y_pct) - pill_h // 2
    target_x = (fw - pill_w) // 2
    return img, (target_x, target_y)


def _to_display(text: str, direction: str) -> str:
    """Convert logical-order text to display (visual) order for PIL.

    For LTR, returns text unchanged. For RTL, applies the Unicode BiDi algorithm
    so PIL — which doesn't reorder — paints characters in the correct visual order.
    """
    if direction == "rtl":
        return get_display(text)
    return text


def _measure_w(text: str, font: "ImageFont.FreeTypeFont | None") -> int:
    """Pixel width of `text` in `font`. Returns 0 when no font (chars-only mode)."""
    if font is None or not text:
        return 0
    bbox = ImageDraw.Draw(_MEASURE_IMG).textbbox((0, 0), text, font=font)
    return bbox[2] - bbox[0]


_MEASURE_IMG = Image.new("RGBA", (1, 1))


def _fits(line: str, *, max_chars: int, font: "ImageFont.FreeTypeFont | None",
          max_text_w: int) -> bool:
    """A line fits if it's within the char cap AND (when a font is given) the
    measured pixel width is within the frame's safe area."""
    if len(line) > max_chars:
        return False
    if font is not None and max_text_w > 0 and _measure_w(line, font) > max_text_w:
        return False
    return True


def _hard_break_word(word: str, *, max_chars: int, font: "ImageFont.FreeTypeFont | None",
                     max_text_w: int) -> list[str]:
    """Split a single word too wide for one line into pixel-fitting pieces.

    Only triggers for pathological inputs (e.g. a 40-char URL-like token); normal
    finance narration never hits this, but it guarantees in-bounds rendering.
    """
    pieces: list[str] = []
    cur = ""
    for ch in word:
        candidate = cur + ch
        if cur and not _fits(candidate, max_chars=max_chars, font=font, max_text_w=max_text_w):
            pieces.append(cur)
            cur = ch
        else:
            cur = candidate
    if cur:
        pieces.append(cur)
    return pieces


def _wrap_text(
    text: str,
    *,
    max_chars: int,
    max_lines: int,
    font: "ImageFont.FreeTypeFont | None" = None,
    max_text_w: int = 0,
) -> list[str]:
    """Greedy whitespace-aware wrap with a hard pixel budget.

    A line is accepted only if it fits both the char cap and (when `font` +
    `max_text_w` are supplied) the measured pixel width. Overlong single words
    are hard-broken so a pill can never exceed the frame. Works identically for
    Hebrew — BiDi reordering happens later at render time and doesn't change width.
    """
    raw_words = text.split()
    if not raw_words:
        return [""]

    # Pre-split any word that can't fit on its own line.
    words: list[str] = []
    for w in raw_words:
        if _fits(w, max_chars=max_chars, font=font, max_text_w=max_text_w):
            words.append(w)
        else:
            words.extend(_hard_break_word(w, max_chars=max_chars, font=font, max_text_w=max_text_w))

    lines: list[str] = []
    current = ""
    for w in words:
        candidate = f"{current} {w}".strip()
        if not current or _fits(candidate, max_chars=max_chars, font=font, max_text_w=max_text_w):
            current = candidate
        else:
            lines.append(current)
            current = w
            if len(lines) >= max_lines:
                break
    if current and len(lines) < max_lines:
        lines.append(current)

    # If we hit max_lines and still had content, append an ellipsis that itself
    # stays within budget (trim characters until it fits).
    if len(lines) == max_lines:
        consumed = sum(len(line.split()) for line in lines)
        if consumed < len(words):
            last = lines[-1]
            trial = last + "…"
            while not _fits(trial, max_chars=max_chars, font=font, max_text_w=max_text_w) and last:
                last = last[:-1].rstrip()
                trial = last + "…"
            lines[-1] = trial
    return lines[:max_lines]
