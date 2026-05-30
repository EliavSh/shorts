"""Last 1.5s creator-credit overlay. Legal/ethical baseline + attribution."""
from __future__ import annotations

import subprocess
from pathlib import Path

from imageio_ffmpeg import get_ffmpeg_exe


def _escape_drawtext(text: str) -> str:
    out = text.replace("\\", r"\\")
    out = out.replace(":", r"\:")
    out = out.replace("'", r"\'")
    out = out.replace("%", r"\%")
    return out


def burn_endcard(
    in_path: Path,
    out_path: Path,
    creator: str,
    clip_duration_s: float,
    duration_s: float = 1.5,
) -> Path:
    """Overlay 'clip by @creator' on the last `duration_s` seconds."""
    line1 = _escape_drawtext("clip by")
    line2 = _escape_drawtext(f"@{creator}")
    start = max(0.0, clip_duration_s - duration_s)

    vf = (
        # Dim the underlying frame so credit pops.
        f"drawbox=x=0:y=0:w=iw:h=ih:color=black@0.55:t=fill:"
        f"enable='gt(t,{start})',"
        f"drawtext=text='{line1}':"
        f"fontcolor=white:fontsize=64:borderw=4:bordercolor=black:"
        f"x=(w-text_w)/2:y=h*0.42:"
        f"enable='gt(t,{start})',"
        f"drawtext=text='{line2}':"
        f"fontcolor=#FFD400:fontsize=96:borderw=6:bordercolor=black:"
        f"x=(w-text_w)/2:y=h*0.5:"
        f"enable='gt(t,{start})'"
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
