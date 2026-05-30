"""Optional phonk/hype loop, ducked under streamer commentary.

Skips cleanly if no music asset exists. Picks a random track from assets/music/
when present.
"""
from __future__ import annotations

import random
import subprocess
from pathlib import Path

from imageio_ffmpeg import get_ffmpeg_exe

from shorts.config import REPO_ROOT  # noqa: E402
MUSIC_DIR = REPO_ROOT / "assets" / "music"
SUPPORTED = {".mp3", ".m4a", ".wav", ".ogg"}


def pick_track() -> Path | None:
    if not MUSIC_DIR.exists():
        return None
    tracks = [p for p in MUSIC_DIR.iterdir() if p.suffix.lower() in SUPPORTED]
    if not tracks:
        return None
    return random.choice(tracks)


def add_music(
    in_path: Path,
    out_path: Path,
    music_path: Path | None = None,
    music_db: float = -18.0,
    original_db: float = -3.0,
) -> Path:
    """Mix a music bed under the original audio.

    If music_path is None and assets/music/ is empty, just copy in_path → out_path.
    """
    if music_path is None:
        music_path = pick_track()
    if music_path is None:
        # No-op: copy.
        cmd = [get_ffmpeg_exe(), "-y", "-i", str(in_path), "-c", "copy", str(out_path)]
        subprocess.run(cmd, check=True, capture_output=True)
        return out_path

    # Mix: original audio at original_db, music at music_db, sum, limit to video length.
    filter_complex = (
        f"[0:a]volume={original_db}dB[a0];"
        f"[1:a]volume={music_db}dB,aloop=loop=-1:size=2e9[a1];"
        f"[a0][a1]amix=inputs=2:duration=first:dropout_transition=0[aout]"
    )
    cmd = [
        get_ffmpeg_exe(),
        "-y",
        "-i",
        str(in_path),
        "-i",
        str(music_path),
        "-filter_complex",
        filter_complex,
        "-map",
        "0:v",
        "-map",
        "[aout]",
        "-c:v",
        "copy",
        "-c:a",
        "aac",
        "-shortest",
        "-movflags",
        "+faststart",
        str(out_path),
    ]
    subprocess.run(cmd, check=True, capture_output=True)
    return out_path
