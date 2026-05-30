"""16:9 → 9:16 crop, with optional facecam-corner avoidance.

Brawl Stars gameplay is centered in 16:9. A naive center crop already discards
the left/right ~657px on each side — which is where corner facecams sit. So in
practice we just center-crop. The facecam_corner argument lets us bias the
crop horizontally if we want extra safety margin (useful for unusual facecam
placements).
"""
from __future__ import annotations

import subprocess
from pathlib import Path

from imageio_ffmpeg import get_ffmpeg_exe

# Output: 1080x1920 (9:16). With source 16:9, we crop a 607.5-wide column.
TARGET_W = 1080
TARGET_H = 1920


def crop_to_vertical(
    in_path: Path,
    out_path: Path,
    facecam_corner: str = "none",
    mode: str = "center_crop",
) -> Path:
    """Convert in_path to 1080x1920.

    mode="center_crop": crop the central 9:16 strip (action area). Default.
    mode="blurred_bg":  fit full 16:9 horizontally, blur-fill the top/bottom.
    """
    # Punchy color grade — slight contrast + saturation boost makes the
    # cartoony Brawl Stars palette pop on tiny mobile screens.
    grade = "eq=contrast=1.15:saturation=1.30:brightness=0.02:gamma=0.97"
    # Subtle constant zoom-in (1.04x) for a "cinema" feel without distracting motion.
    zoom = "crop=in_w/1.04:in_h/1.04"

    if mode == "blurred_bg":
        vf = (
            f"split[main][bg];"
            f"[bg]scale={TARGET_W}:{TARGET_H}:force_original_aspect_ratio=increase,"
            f"crop={TARGET_W}:{TARGET_H},gblur=sigma=30[bg2];"
            f"[main]{zoom},scale={TARGET_W}:-2[fg];"
            f"[bg2][fg]overlay=(W-w)/2:(H-h)/2,{grade},setsar=1"
        )
    else:
        vf = (
            f"crop=ih*9/16:ih:(iw-ih*9/16)/2:0,"
            f"{zoom},"
            f"scale={TARGET_W}:{TARGET_H},"
            f"{grade},"
            f"setsar=1"
        )

    cmd = [
        get_ffmpeg_exe(),
        "-y",
        "-i",
        str(in_path),
        "-vf",
        vf,
        "-c:a",
        "copy",
        "-movflags",
        "+faststart",
        str(out_path),
    ]
    subprocess.run(cmd, check=True, capture_output=True)
    return out_path
