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

    lines = _wrap_text(text, max_chars=style.max_chars_per_line, max_lines=style.max_lines)
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


def _wrap_text(text: str, *, max_chars: int, max_lines: int) -> list[str]:
    """Greedy whitespace-aware wrap, max_lines clamp.

    Works the same way for Hebrew (word-spacing is identical to English at the
    string-processing level — BiDi reordering happens later at render time).
    """
    words = text.split()
    if not words:
        return [""]

    lines: list[str] = []
    current = ""
    for w in words:
        candidate = f"{current} {w}".strip()
        if len(candidate) <= max_chars or not current:
            current = candidate
        else:
            lines.append(current)
            current = w
            if len(lines) >= max_lines:
                break
    if current and len(lines) < max_lines:
        lines.append(current)

    # If we hit max_lines and still had words, append ellipsis to last line.
    if len(lines) == max_lines:
        consumed = sum(len(line.split()) for line in lines)
        if consumed < len(words):
            last = lines[-1]
            if len(last) + 2 <= max_chars:
                lines[-1] = last + "…"
            else:
                lines[-1] = last[: max_chars - 1] + "…"
    return lines[:max_lines]
