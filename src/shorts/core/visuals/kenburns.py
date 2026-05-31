"""Ken Burns effect — turn a still image into a cinematic clip with slow
zoom/pan over its display duration. Makes every photo feel alive.
"""
from __future__ import annotations

import random
from pathlib import Path

import numpy as np
from moviepy import VideoClip
from PIL import Image

FRAME_W = 1080
FRAME_H = 1920


def make_kenburns_clip(image_path: Path, *, duration_s: float,
                      zoom_from: float = 1.0, zoom_to: float = 1.12,
                      pan: tuple[float, float] | None = None,
                      seed: int | None = None,
                      static: bool = False) -> VideoClip:
    """Load image, fill 1080x1920, animate a slow zoom (+ optional pan).

    `pan` is (dx_pct, dy_pct) total drift across the clip, expressed as
    fractions of the image size. If None, a small random pan is chosen.

    R5: when the source image is wide (chart-like, aspect > 2.0), disable
    zoom and pan — zooming into a chart slices it and hides the takeaway.

    `static=True`: the image is a generated graphic that is already exactly
    1080x1920 with text laid out inside safe margins. Skip the watermark-band
    strip, the cover-fit re-crop, and all zoom/pan — any of those scale or
    shift the frame and push centered text out of bounds. Show it verbatim.
    """
    if static:
        base = _load_exact(image_path)
        base_arr = np.array(base)

        def frame_static(t: float) -> np.ndarray:
            return base_arr

        return VideoClip(frame_static, duration=duration_s).with_fps(30)

    if _looks_like_chart(image_path):
        zoom_from = 1.0
        zoom_to = 1.0
        pan = (0.0, 0.0)
    rng = random.Random(seed)
    if pan is None:
        pan = (rng.uniform(-0.04, 0.04), rng.uniform(-0.04, 0.04))

    base = _load_filled(image_path)  # PIL RGB 1080x1920 with image cover-fit
    bw, bh = base.size
    base_arr = np.array(base)

    def frame_at(t: float) -> np.ndarray:
        p = min(max(t / max(duration_s, 0.001), 0.0), 1.0)
        zoom = zoom_from + (zoom_to - zoom_from) * p
        dx = pan[0] * p * bw
        dy = pan[1] * p * bh

        # Crop a centred zoom rectangle, then resize to frame size.
        cw, ch = int(bw / zoom), int(bh / zoom)
        cx = (bw - cw) // 2 + int(dx)
        cy = (bh - ch) // 2 + int(dy)
        cx = max(0, min(bw - cw, cx))
        cy = max(0, min(bh - ch, cy))
        crop = base_arr[cy:cy + ch, cx:cx + cw]
        # Nearest-neighbour resize via PIL would be too slow per frame; use a fast cv2-style.
        img = Image.fromarray(crop).resize((FRAME_W, FRAME_H), Image.Resampling.BILINEAR)
        return np.array(img)

    return VideoClip(frame_at, duration=duration_s).with_fps(30)


# R12 — default vertical band crop to remove baked-in source watermarks / chyrons.
WATERMARK_TOP_FRAC = 0.05
WATERMARK_BOTTOM_FRAC = 0.06

# R5 — disable Ken Burns zoom for wide/chart-like images. Aspect >= 2.0
# usually means a chart, graph, or news graphic — content where the
# takeaway lives at the edges, not the center.
CHART_LIKE_ASPECT = 2.0


def _looks_like_chart(image_path: Path) -> bool:
    try:
        with Image.open(image_path) as pi:
            w, h = pi.size
        return (w / h) >= CHART_LIKE_ASPECT
    except Exception:
        return False


def _load_exact(path: Path) -> Image.Image:
    """Open a generated graphic and guarantee a 1080x1920 RGB frame without
    cropping or shifting — it was authored at exactly this size with text-safe
    margins, so any band-strip / cover-fit would clip the text."""
    img = Image.open(path).convert("RGB")
    if img.size != (FRAME_W, FRAME_H):
        img = img.resize((FRAME_W, FRAME_H), Image.Resampling.LANCZOS)
    return img


def _load_filled(path: Path) -> Image.Image:
    """Open image, strip likely watermark bands, scale to cover 1080x1920."""
    img = Image.open(path).convert("RGB")
    w, h = img.size

    # R12 — pre-strip top/bottom bands where source bylines/chyrons usually sit.
    top_band = int(h * WATERMARK_TOP_FRAC)
    bottom_band = int(h * WATERMARK_BOTTOM_FRAC)
    if top_band + bottom_band < h - 100:
        img = img.crop((0, top_band, w, h - bottom_band))
        w, h = img.size

    target_ratio = FRAME_W / FRAME_H
    img_ratio = w / h
    if img_ratio > target_ratio:
        # too wide — crop sides
        new_w = int(h * target_ratio)
        x0 = (w - new_w) // 2
        img = img.crop((x0, 0, x0 + new_w, h))
    else:
        # too tall — crop top/bottom
        new_h = int(w / target_ratio)
        y0 = (h - new_h) // 2
        img = img.crop((0, y0, w, y0 + new_h))
    return img.resize((FRAME_W, FRAME_H), Image.Resampling.LANCZOS)
