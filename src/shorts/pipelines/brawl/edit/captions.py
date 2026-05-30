"""Editorial hype captions — NOT a transcript.

Claude generates 3-4 short punchy phrases from the moment context. Each is
rendered as a PNG via Pillow and overlaid onto the video at staggered
timestamps, alternating positions and colors for CapCut-y energy.
"""
from __future__ import annotations

import json
import subprocess
import time
from dataclasses import dataclass
from pathlib import Path

import anthropic
from imageio_ffmpeg import get_ffmpeg_exe

from shorts.core.visuals.text_render import TextStyle, render_text_png


CAPTIONS_SYSTEM = """You write punchy on-screen captions for Brawl Stars short-form videos. \
These are editor-style hype phrases — NOT a transcript. They pop up at key beats \
to amplify the action.

Voice: SHOUTING ALL CAPS, gen-Z gaming, 2-4 words each, ≤1 emoji per phrase.

The N captions you return will be placed in temporal order across the clip:
- Caption 1: setup / anticipation ("WAIT FOR IT", "WATCH THIS", "HE'S LOW")
- Captions 2..N-1: action beats ("1V3", "NO WAY", "INSANE", "BROKEN 🔥", "HE DID IT")
- Last caption: reaction / payoff ("GAME OVER", "GG 🏆", "ARE YOU SERIOUS")

GREAT examples (varied beats, gaming-specific, punchy):
- "WAIT FOR IT" → "1V3 INCOMING" → "NO ESCAPE" → "INSANE 🔥" → "ABSOLUTE COOK"
- "HE'S TRAPPED" → "WATCH THIS" → "BROKEN" → "GG"
- "FINAL ROUND" → "CLUTCH MODE" → "ARE YOU KIDDING" → "WORLD RECORD ⚡"

DO NOT:
- Transcribe what the streamer is actually saying
- Use more than 4 words per caption
- Use lowercase, complete sentences, or punctuation
- Repeat the same emoji twice
- Use the EXACT hook text (it's already on the clip)

Return strict JSON with key "captions" — array of EXACTLY N short strings, in clip order. \
No prose, no markdown fences."""


@dataclass
class HypeCaption:
    text: str
    start_s: float
    duration_s: float
    y_position: float    # 0-1 fraction of video height (top edge of overlay)
    style: TextStyle


def _strip_fence(text: str) -> str:
    text = text.strip()
    if text.startswith("```"):
        lines = text.splitlines()[1:]
        if lines and lines[-1].strip() == "```":
            lines = lines[:-1]
        text = "\n".join(lines).strip()
    return text


def generate_hype_captions(
    context: str,
    api_key: str,
    n: int = 4,
    insights_text: str = "",
    feedback_text: str = "",
    model: str = "claude-haiku-4-5-20251001",
) -> list[str]:
    """Return n short editor-style captions for the clip."""
    client = anthropic.Anthropic(api_key=api_key)
    parts = [f"Moment context: {context}"]
    if insights_text:
        parts.append("\nReviewer insights from past clips — apply them:\n" + insights_text)
    if feedback_text:
        parts.append("\nReviewer feedback on the previous captions for THIS clip:\n" + feedback_text)
    parts.append(f"\nWrite {n} captions, in clip order.")
    user = "\n".join(parts)
    last_err: Exception | None = None
    for attempt in range(4):
        try:
            resp = client.messages.create(
                model=model,
                max_tokens=300,
                system=CAPTIONS_SYSTEM,
                messages=[{"role": "user", "content": user}],
            )
            break
        except anthropic.APIStatusError as e:
            last_err = e
            if e.status_code in (429, 529):
                time.sleep(min(2 ** attempt, 20))
                continue
            raise
    else:
        raise RuntimeError(f"Anthropic overloaded: {last_err}")

    text = "".join(b.text for b in resp.content if b.type == "text")
    text = _strip_fence(text)
    try:
        data = json.loads(text)
        captions = [str(c).strip().strip("\"'") for c in data.get("captions", [])]
    except json.JSONDecodeError:
        # Defensive fallback.
        captions = ["WAIT FOR IT", "NO WAY 😱", "INSANE 🔥", "GG"]
    captions = [c for c in captions if c]
    return captions[:n] if captions else ["INSANE 🔥"]


def plan_captions(
    texts: list[str],
    clip_duration_s: float,
    hook_duration_s: float = 1.5,
    endcard_duration_s: float = 1.5,
    caption_duration_s: float = 2.0,
) -> list[HypeCaption]:
    """Place captions evenly across the clip, skipping hook + endcard zones.

    Rotates y position and color so adjacent captions feel different.
    2.0s per caption is the readability floor for mobile (per Submagic / project
    research). Positions rotate through top-third, lower-third, and middle so
    the eye keeps refocusing.
    """
    # Y positions (fraction of height, top edge of overlay).
    # Mix top-third, lower-third, and just-above-center for visual rhythm.
    y_positions = [0.22, 0.62, 0.40, 0.70, 0.30, 0.55]
    # Color rotation: brawl-yellow, white, hot-red, cyan, lime, magenta.
    palettes = [
        (255, 212, 0),     # brawl yellow
        (255, 255, 255),   # white
        (255, 70, 110),    # hot red/pink
        (110, 240, 255),   # cyan
        (180, 255, 100),   # lime
        (255, 130, 230),   # magenta
    ]

    safe_start = hook_duration_s + 0.3
    safe_end = clip_duration_s - endcard_duration_s - 0.3
    safe_span = max(0.5, safe_end - safe_start)
    n = len(texts)
    if n == 0:
        return []

    # Two background-pill styles to rotate: solid black sticker + transparent
    # outline-only. Mixing them keeps the screen lively.
    bg_styles: list[tuple | None] = [
        (0, 0, 0, 220),       # solid black sticker pill
        None,                 # no bg (just stroked text)
        (0, 0, 0, 220),
        None,
        (10, 10, 30, 220),    # dark navy variant
        None,
    ]

    plans: list[HypeCaption] = []
    for i, text in enumerate(texts):
        frac = (i + 0.5) / n
        start = safe_start + frac * safe_span - caption_duration_s / 2
        start = max(safe_start, min(safe_end - caption_duration_s, start))
        if len(text) <= 10:
            font_size = 150
        elif len(text) <= 16:
            font_size = 120
        else:
            font_size = 96
        style = TextStyle(
            font_size=font_size,
            color=palettes[i % len(palettes)],
            stroke_width=10,
            bg_color=bg_styles[i % len(bg_styles)],
            bg_radius=32,
            bg_pad_x=40,
            bg_pad_y=20,
        )
        plans.append(
            HypeCaption(
                text=text,
                start_s=start,
                duration_s=caption_duration_s,
                y_position=y_positions[i % len(y_positions)],
                style=style,
            )
        )
    return plans


def burn_captions(
    in_path: Path,
    out_path: Path,
    captions: list[HypeCaption],
    work_dir: Path | None = None,
    video_w: int = 1080,
    video_h: int = 1920,
) -> Path:
    """Render each caption to PNG, then overlay all with timed enable filters."""
    if work_dir is None:
        work_dir = in_path.parent / "_caption_pngs"
    work_dir.mkdir(parents=True, exist_ok=True)

    if not captions:
        # No-op copy.
        cmd = [
            get_ffmpeg_exe(), "-y", "-i", str(in_path),
            "-c", "copy", str(out_path),
        ]
        subprocess.run(cmd, check=True, capture_output=True)
        return out_path

    overlay_inputs: list[str] = []
    overlay_filters: list[str] = []
    for i, c in enumerate(captions):
        png_path = work_dir / f"cap_{i:02d}.png"
        _, w, h = render_text_png(
            text=c.text,
            out_path=png_path,
            canvas_w=video_w,
            canvas_h=video_h,
            style=c.style,
        )
        overlay_inputs.extend(["-i", str(png_path)])
        y_px = int(c.y_position * video_h)
        prev = "[0:v]" if i == 0 else f"[v{i - 1}]"
        end_s = c.start_s + c.duration_s
        overlay_filters.append(
            f"{prev}[{i + 1}:v]"
            f"overlay=x=(W-w)/2:y={y_px}:enable='between(t,{c.start_s:.2f},{end_s:.2f})'"
            f"[v{i}]"
        )

    filter_complex = ";".join(overlay_filters)
    last_label = f"[v{len(captions) - 1}]"

    cmd = [
        get_ffmpeg_exe(),
        "-y",
        "-i", str(in_path),
        *overlay_inputs,
        "-filter_complex", filter_complex,
        "-map", last_label,
        "-map", "0:a?",
        "-c:a", "copy",
        "-movflags", "+faststart",
        str(out_path),
    ]
    subprocess.run(cmd, check=True, capture_output=True)
    return out_path
