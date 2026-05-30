"""First-1.5s scroll-stopper. LLM writes copy, PIL renders, ffmpeg overlays.

PIL handles wrap + dynamic font sizing so the hook always fits inside 1080
pixels regardless of length.
"""
from __future__ import annotations

import subprocess
import time
from pathlib import Path

import anthropic
from imageio_ffmpeg import get_ffmpeg_exe

from shorts.core.visuals.text_render import TextStyle, render_text_png


HOOK_SYSTEM = """You write 3-5 word hook overlays for Brawl Stars short-form videos. \
Goal: stop the scroll in the first 1.5 seconds. Style: SHOUTING ALL CAPS, dramatic, \
gen-Z gaming voice. STRICT character cap: 22 characters max including spaces and \
emoji. 1 emoji max. Examples:

- "BROKE THE GAME 🤯"
- "NO WAY HE HIT"
- "WORLD RECORD ⚡"
- "1V3 CLUTCH 😱"
- "FASTEST EVER"

Return ONLY the hook text, no quotes, no explanation."""


def generate_hook(
    context: str,
    api_key: str,
    insights_text: str = "",
    feedback_text: str = "",
    model: str = "claude-haiku-4-5-20251001",
) -> str:
    client = anthropic.Anthropic(api_key=api_key)
    user_parts = [f"Moment: {context}"]
    if insights_text:
        user_parts.append("\nReviewer insights from past clips — apply them:\n" + insights_text)
    if feedback_text:
        user_parts.append("\nReviewer feedback on the previous hook for THIS clip:\n" + feedback_text)
    user_parts.append("\nWrite the hook.")

    last_err: Exception | None = None
    for attempt in range(4):
        try:
            resp = client.messages.create(
                model=model,
                max_tokens=40,
                system=HOOK_SYSTEM,
                messages=[{"role": "user", "content": "\n".join(user_parts)}],
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
    text = "".join(b.text for b in resp.content if b.type == "text").strip()
    text = text.strip("\"'`")
    # Hard cap as a safety net even if the model overshoots.
    if len(text) > 28:
        text = text[:28].rsplit(" ", 1)[0]
    return text or "INSANE MOMENT 🔥"


def burn_hook(
    in_path: Path,
    out_path: Path,
    hook_text: str,
    duration_s: float = 1.5,
    video_w: int = 1080,
    video_h: int = 1920,
) -> Path:
    png_path = in_path.parent / "_hook.png"
    style = TextStyle(
        font_size=140,           # PIL will shrink if needed
        max_lines=2,
        color=(255, 212, 0),     # brawl yellow
        stroke_color=(0, 0, 0),
        stroke_width=10,
        shadow_offset=(0, 8),
        shadow_color=(0, 0, 0, 180),
    )
    _, ow, oh = render_text_png(
        text=hook_text,
        out_path=png_path,
        canvas_w=video_w,
        canvas_h=video_h,
        margin_x=70,
        style=style,
    )
    # Position: vertically about 18% from top.
    y_px = int(video_h * 0.16)

    filter_complex = (
        f"[0:v][1:v]overlay=x=(W-w)/2:y={y_px}"
        f":enable='lt(t,{duration_s})'[v]"
    )
    cmd = [
        get_ffmpeg_exe(),
        "-y",
        "-i", str(in_path),
        "-i", str(png_path),
        "-filter_complex", filter_complex,
        "-map", "[v]",
        "-map", "0:a?",
        "-c:a", "copy",
        "-movflags", "+faststart",
        str(out_path),
    ]
    subprocess.run(cmd, check=True, capture_output=True)
    return out_path
