"""Pipeline orchestrator: take a raw clip + moment metadata, produce a versioned short.

Each compose() call writes to data/output/<run_id>/v<N>/ — first call is v1,
subsequent calls (after reviewer feedback) are v2, v3, ...
"""
from __future__ import annotations

import shutil
import subprocess
from dataclasses import dataclass, field
from pathlib import Path

from imageio_ffmpeg import get_ffmpeg_exe

from . import captions, crop, endcard, hook, music

from shorts.config import REPO_ROOT  # noqa: E402
from shorts.config import pipeline_data_dir
OUTPUT_ROOT = pipeline_data_dir("brawl") / "output"


@dataclass
class ComposeInput:
    run_id: str
    version: int
    raw_clip_path: Path
    facecam_corner: str
    creator_handle: str
    hook_context: str
    anthropic_api_key: str
    text_model: str = "claude-haiku-4-5-20251001"
    insights_text: str = ""
    feedback_text: str = ""


@dataclass
class ComposeResult:
    short_path: Path
    version_dir: Path
    stages: list[Path] = field(default_factory=list)
    hook_text: str = ""
    caption_texts: list[str] = field(default_factory=list)


def _probe_duration(path: Path) -> float:
    proc = subprocess.run(
        [get_ffmpeg_exe(), "-i", str(path)],
        capture_output=True,
        text=True,
    )
    import re

    m = re.search(r"Duration:\s*(\d+):(\d+):([\d.]+)", proc.stderr)
    if not m:
        raise RuntimeError(f"Could not determine duration of {path}")
    h, mi, sec = int(m.group(1)), int(m.group(2)), float(m.group(3))
    return h * 3600 + mi * 60 + sec


def compose(inp: ComposeInput) -> ComposeResult:
    out_dir = OUTPUT_ROOT / inp.run_id / f"v{inp.version}"
    interm_dir = out_dir / "intermediate"
    interm_dir.mkdir(parents=True, exist_ok=True)

    stages: list[Path] = []

    # Stage 1: crop + color grade.
    s1 = interm_dir / "01_vertical.mp4"
    crop.crop_to_vertical(inp.raw_clip_path, s1, facecam_corner=inp.facecam_corner)
    stages.append(s1)

    # Stage 2: editor hype captions, steered by insights + feedback.
    s2 = interm_dir / "02_captions.mp4"
    caption_texts = captions.generate_hype_captions(
        context=inp.hook_context,
        api_key=inp.anthropic_api_key,
        n=5,
        insights_text=inp.insights_text,
        feedback_text=inp.feedback_text,
        model=inp.text_model,
    )
    clip_duration = _probe_duration(s1)
    plans = captions.plan_captions(caption_texts, clip_duration_s=clip_duration)
    captions.burn_captions(s1, s2, plans, work_dir=interm_dir / "_caption_pngs")
    stages.append(s2)

    # Stage 3: hook overlay.
    s3 = interm_dir / "03_hook.mp4"
    hook_text = hook.generate_hook(
        inp.hook_context,
        api_key=inp.anthropic_api_key,
        insights_text=inp.insights_text,
        feedback_text=inp.feedback_text,
        model=inp.text_model,
    )
    hook.burn_hook(s2, s3, hook_text)
    stages.append(s3)

    # Stage 4: end-card credit.
    s4 = interm_dir / "04_endcard.mp4"
    duration = _probe_duration(s3)
    endcard.burn_endcard(s3, s4, creator=inp.creator_handle, clip_duration_s=duration)
    stages.append(s4)

    # Stage 5: optional music bed.
    s5 = interm_dir / "05_music.mp4"
    music.add_music(s4, s5)
    stages.append(s5)

    # Final.
    final = out_dir / "short.mp4"
    shutil.copy2(s5, final)

    return ComposeResult(
        short_path=final,
        version_dir=out_dir,
        stages=stages,
        hook_text=hook_text,
        caption_texts=caption_texts,
    )
