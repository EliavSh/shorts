"""Brand preview: composes ticker card + caption + disclaimer onto a 1080x1920
frame using the reference video's first-shot scenario (NVDA +1.2%), so the user
can eyeball the brand look offline.
"""
from __future__ import annotations

from pathlib import Path

from PIL import Image

from shorts.pipelines.stocks.visuals.brand import load_brand
from shorts.core.visuals.captions import FRAME_H, FRAME_W, render_caption
from .disclaimer import render_disclaimer
from .ticker_card import render_ticker_card


def render_preview_frame(*, lang: str, caption_text: str, bg_path: Path | None = None) -> Image.Image:
    brand = load_brand(lang)

    if bg_path and bg_path.exists():
        bg = Image.open(bg_path).convert("RGBA").resize((FRAME_W, FRAME_H), Image.Resampling.LANCZOS)
    else:
        # Synthetic neutral gradient so the brand reads even with no B-roll yet.
        bg = _gradient_bg(FRAME_W, FRAME_H)

    frame = bg.copy()

    card = render_ticker_card(
        brand=brand, ticker="NVDA", name="NVIDIA Corp", change_pct=1.2,
    )
    frame.alpha_composite(card, brand.ticker_card.position)

    cap_img, cap_pos = render_caption(brand=brand, text=caption_text)
    frame.alpha_composite(cap_img, cap_pos)

    disc_img, disc_pos = render_disclaimer(brand=brand)
    frame.alpha_composite(disc_img, disc_pos)

    return frame


def _gradient_bg(w: int, h: int) -> Image.Image:
    img = Image.new("RGBA", (w, h))
    px = img.load()
    for y in range(h):
        t = y / h
        r = int(20 + 60 * t)
        g = int(28 + 70 * t)
        b = int(48 + 90 * t)
        for x in range(w):
            px[x, y] = (r, g, b, 255)
    return img


if __name__ == "__main__":
    import sys

    out = Path(sys.argv[1]) if len(sys.argv) > 1 else Path("data/preview_en.png")
    out.parent.mkdir(parents=True, exist_ok=True)
    frame = render_preview_frame(
        lang="en",
        caption_text="Nvidia up 1.2% in pre-market trading",
    )
    frame.convert("RGB").save(out, quality=92)
    print(f"saved {out}")
