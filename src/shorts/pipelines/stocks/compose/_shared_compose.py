"""PIL -> MoviePy helper used by composer.py."""
from __future__ import annotations

import numpy as np
from moviepy import ImageClip
from PIL import Image


def pil_to_clip(img: Image.Image, *, start_s: float, end_s: float,
                position: tuple[int, int] | str = (0, 0)) -> ImageClip:
    arr = np.array(img.convert("RGBA"))
    return ImageClip(arr, is_mask=False, transparent=True).with_start(start_s).with_end(end_s).with_position(position)
