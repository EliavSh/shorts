"""Generated 'Follow for more' CTA card — branded, used in the last beat by default.

Replaces the generic retrieval-found stock photo at the CTA. The CTA visual is
where retrieval is weakest (it's an abstract action, not a thing), so a clean
generated card outperforms.
"""
from __future__ import annotations

from PIL import Image, ImageDraw, ImageFont

from ..brand import Brand, hex_to_rgba

FRAME_W = 1080
FRAME_H = 1920


def render(*, brand: Brand, headline: str | None = None,
           subline: str | None = None) -> Image.Image:
    """A vertical CTA: big brand-coloured Subscribe button → headline → subtitle.

    `headline` defaults to the brand's canonical `cta_text` so the closing line is
    edited in one place (config/stocks/brand_en.yaml)."""
    headline = headline or brand.cta_text
    style = brand.ticker_card
    img = Image.new("RGB", (FRAME_W, FRAME_H), (12, 24, 48))
    draw = ImageDraw.Draw(img, "RGBA")

    f_headline = ImageFont.truetype(str(brand.font_path), size=88)
    f_subline = ImageFont.truetype(str(brand.font_path_regular), size=46)
    f_pill = ImageFont.truetype(str(brand.font_path), size=58)

    accent = style.accent_up

    # Big arrow + pill — "FOLLOW" button block
    pill_w, pill_h = 580, 200
    pill_x = (FRAME_W - pill_w) // 2
    pill_y = 600
    draw.rounded_rectangle(
        (pill_x, pill_y, pill_x + pill_w, pill_y + pill_h),
        radius=46, fill=hex_to_rgba(accent, 1.0),
    )
    follow_txt = "SUBSCRIBE"
    bbox = draw.textbbox((0, 0), follow_txt, font=f_pill)
    fw = bbox[2] - bbox[0]
    fh = bbox[3] - bbox[1]
    draw.text(
        (pill_x + (pill_w - fw) // 2, pill_y + (pill_h - fh) // 2 - bbox[1]),
        follow_txt, font=f_pill, fill="#0B1F3A",
    )

    # Headline below the pill
    head_y = pill_y + pill_h + 100
    lines = _wrap_for_width(headline, f_headline, max_w=FRAME_W - 160)
    for line in lines:
        bbox = draw.textbbox((0, 0), line, font=f_headline)
        line_w = bbox[2] - bbox[0]
        draw.text(((FRAME_W - line_w) // 2, head_y), line, font=f_headline, fill="#FFFFFF")
        head_y += 110

    if subline:
        sub_y = head_y + 40
        bbox = draw.textbbox((0, 0), subline, font=f_subline)
        draw.text(((FRAME_W - (bbox[2] - bbox[0])) // 2, sub_y), subline,
                  font=f_subline, fill="#A8C3E8")

    return img


def _wrap_for_width(text: str, font: ImageFont.FreeTypeFont, *, max_w: int) -> list[str]:
    words = text.split()
    if not words:
        return [""]
    dummy = Image.new("RGB", (1, 1))
    d = ImageDraw.Draw(dummy)
    lines: list[str] = []
    cur = ""
    for w in words:
        cand = f"{cur} {w}".strip()
        if d.textbbox((0, 0), cand, font=font)[2] <= max_w or not cur:
            cur = cand
        else:
            lines.append(cur)
            cur = w
    if cur:
        lines.append(cur)
    return lines
