"""yt-dlp wrapper: download a specific time range and cache by id+range."""
from __future__ import annotations

import os
import subprocess
from pathlib import Path

from yt_dlp import YoutubeDL
from imageio_ffmpeg import get_ffmpeg_exe

from shorts.config import REPO_ROOT  # noqa: E402
CACHE_DIR = REPO_ROOT / "data" / "clip_cache"


def _ensure_ffmpeg_on_path() -> str:
    """yt-dlp's partial-download path requires ffmpeg discoverable via PATH.

    Prepend the imageio-ffmpeg binary's directory to PATH for this process.
    Also returns the binary path for direct subprocess calls.
    """
    exe = get_ffmpeg_exe()
    bin_dir = str(Path(exe).parent)
    sep = os.pathsep
    if bin_dir not in os.environ.get("PATH", "").split(sep):
        os.environ["PATH"] = bin_dir + sep + os.environ.get("PATH", "")
    # yt-dlp expects to find an executable literally named "ffmpeg" or
    # "ffmpeg.exe" — imageio-ffmpeg ships it as "ffmpeg-win-x86_64-v7.1.exe".
    # Create a stable alias next to it on first use.
    alias = Path(bin_dir) / ("ffmpeg.exe" if os.name == "nt" else "ffmpeg")
    if not alias.exists():
        try:
            # On Windows, symlinks require admin — just copy. Tiny price (~50MB
            # once per machine), buys us a stable name yt-dlp will find.
            import shutil

            shutil.copy2(exe, alias)
        except Exception:
            pass
    return exe


def _format_ts(seconds: float) -> str:
    s = int(round(seconds))
    h, rem = divmod(s, 3600)
    m, sec = divmod(rem, 60)
    return f"{h:02d}:{m:02d}:{sec:02d}"


def download_window(
    video_id: str,
    start_s: float,
    end_s: float,
    overwrite: bool = False,
) -> Path:
    """Download just [start_s, end_s] of a video. Cached on disk.

    Uses yt-dlp's `download_ranges` to ask the server for only the bytes we need.
    Returns the local path to the resulting .mp4.
    """
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    out_path = CACHE_DIR / f"{video_id}_{int(start_s)}-{int(end_s)}.mp4"
    if out_path.exists() and not overwrite:
        return out_path

    _ensure_ffmpeg_on_path()

    ydl_opts = {
        "outtmpl": str(out_path.with_suffix(".%(ext)s")),
        "format": "bv*[height<=1080]+ba/b[height<=1080]/best",
        "merge_output_format": "mp4",
        "ffmpeg_location": get_ffmpeg_exe(),
        "download_ranges": lambda info, ydl: [
            {"start_time": start_s, "end_time": end_s, "title": "clip"}
        ],
        "force_keyframes_at_cuts": True,
        "quiet": True,
        "no_warnings": True,
        "concurrent_fragment_downloads": 4,
    }

    url = f"https://www.youtube.com/watch?v={video_id}"
    with YoutubeDL(ydl_opts) as ydl:
        ydl.download([url])

    # yt-dlp may produce .mkv or .webm depending on the source — normalize to .mp4
    if not out_path.exists():
        for candidate in CACHE_DIR.glob(f"{video_id}_{int(start_s)}-{int(end_s)}.*"):
            if candidate.suffix in (".mkv", ".webm", ".mp4"):
                if candidate.suffix != ".mp4":
                    # Remux to mp4 (no re-encode)
                    subprocess.run(
                        [
                            get_ffmpeg_exe(),
                            "-y",
                            "-i",
                            str(candidate),
                            "-c",
                            "copy",
                            str(out_path),
                        ],
                        check=True,
                        capture_output=True,
                    )
                    candidate.unlink()
                else:
                    out_path = candidate
                break
    return out_path


def sample_frames(
    video_path: Path,
    n: int = 6,
    out_dir: Path | None = None,
) -> list[Path]:
    """Extract n evenly-spaced JPEG frames from a clip via ffmpeg.

    Returns list of frame paths in temporal order.
    """
    if out_dir is None:
        out_dir = video_path.with_suffix("")
        out_dir.mkdir(exist_ok=True)
    else:
        out_dir.mkdir(parents=True, exist_ok=True)

    # Get duration via ffprobe-equivalent (ffmpeg -i is enough; parse stderr).
    proc = subprocess.run(
        [get_ffmpeg_exe(), "-i", str(video_path)],
        capture_output=True,
        text=True,
    )
    # Duration line looks like: "  Duration: 00:00:25.04, start: ..."
    import re

    m = re.search(r"Duration:\s*(\d+):(\d+):([\d.]+)", proc.stderr)
    if not m:
        raise RuntimeError(f"Could not determine duration of {video_path}")
    h, mi, sec = int(m.group(1)), int(m.group(2)), float(m.group(3))
    duration = h * 3600 + mi * 60 + sec

    paths: list[Path] = []
    # Skip the first/last 5% to avoid keyframe-boundary garbage frames.
    margin = max(0.3, duration * 0.05)
    if duration <= 2 * margin:
        margin = 0.0
    span = duration - 2 * margin
    for i in range(n):
        t = margin + (span * (i + 0.5) / n)
        out_path = out_dir / f"frame_{i:02d}.jpg"
        subprocess.run(
            [
                get_ffmpeg_exe(),
                "-y",
                "-ss",
                f"{t:.2f}",
                "-i",
                str(video_path),
                "-frames:v",
                "1",
                "-q:v",
                "3",
                "-vf",
                "scale=720:-2",
                str(out_path),
            ],
            check=True,
            capture_output=True,
        )
        paths.append(out_path)
    return paths
