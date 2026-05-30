"""Cross-pipeline health checks. Expanded by later migration steps."""
from __future__ import annotations

import os
import shutil
from pathlib import Path
from typing import Any

from shorts.config import REPO_ROOT, DATA_DIR


def run_checks(console: Any) -> None:
    rows: list[tuple[str, str, str]] = []

    def add(name: str, ok: bool, note: str = "") -> None:
        rows.append((name, "✓" if ok else "✗", note))

    # ffmpeg via imageio
    try:
        from imageio_ffmpeg import get_ffmpeg_exe
        exe = get_ffmpeg_exe()
        add("ffmpeg", Path(exe).exists(), exe)
    except Exception as e:
        add("ffmpeg", False, str(e))

    # Anthropic key
    add("ANTHROPIC_API_KEY", bool(os.environ.get("ANTHROPIC_API_KEY", "").strip()))

    # YouTube Data API
    add("YOUTUBE_API_KEY", bool(os.environ.get("YOUTUBE_API_KEY", "").strip()))

    # Data dirs
    add("data/brawl/", (DATA_DIR / "brawl").exists())
    add("data/stocks/", (DATA_DIR / "stocks").exists())

    # Configs (subdir-per-pipeline pattern)
    add("config/brawl/config.yaml", (REPO_ROOT / "config" / "brawl" / "config.yaml").exists())
    add("config/stocks/config.yaml", (REPO_ROOT / "config" / "stocks" / "config.yaml").exists())

    width = max(len(r[0]) for r in rows)
    for name, mark, note in rows:
        console.print(f"  {mark}  {name:<{width}}  [dim]{note}[/dim]")
