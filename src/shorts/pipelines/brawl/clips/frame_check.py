"""Vision-based purity gate: are these frames pure Brawl Stars gameplay?

Sends N sampled frames to Claude with vision and gets a strict yes/no plus
reason. The whole point is to reject any window where the streamer's face,
intros/outros, menu screens, or other non-gameplay content is visible.
"""
from __future__ import annotations

import base64
import json
from dataclasses import dataclass
from pathlib import Path

import anthropic

SYSTEM_PROMPT = """You are a gameplay-validation gate for a Brawl Stars short-form video pipeline.

You will see N sampled frames from a candidate ~25 second clip. Your job: \
verify that the gameplay action is happening in every frame, and report whether \
a corner facecam exists (so the downstream cropper can remove it).

Brawl Stars gameplay looks like:
- Top-down isometric view of a map
- Brawler characters (cartoon style) on the map
- HUD elements: health bars, ammo/super gauges, minimap, trophy icons, timer
- Maps are themed (grass, desert, ice, factory, etc.)

A SMALL CORNER FACECAM is FINE. The cropper will remove it during 16:9 → 9:16 \
conversion. Just report which corner it occupies. Most gaming YouTubers have \
one and that's OK.

REJECT (clean=false) only if ANY frame shows:
- A LARGE webcam taking over the frame (more than ~20% width, covering gameplay)
- A person walking around in real life / IRL footage instead of gameplay
- An intro/outro screen, "subscribe" or "like" card, sponsor plug, merch promo
- A loading screen, menu, brawler-select, shop, or settings UI as the dominant content
- The post-match "results breakdown" screen with stats and XP gain
- A different game, screen-share of YouTube/Twitter/Discord/etc.
- The streamer's full webcam reaction overlay covering the play

ACCEPT (clean=true) when the in-match action is the dominant content in every \
frame, even if a small corner facecam is present. The brief in-match "WINNER" \
banner overlaying still-visible map is fine.

Output strict JSON with these fields:
  clean: boolean
  reason: string (one short sentence — explain pass or fail)
  facecam_corner: one of "none","top-left","top-right","bottom-left","bottom-right"

No markdown, no prose outside the JSON."""


@dataclass
class FrameCheckResult:
    clean: bool
    reason: str
    facecam_corner: str  # "none" / "top-left" / etc.


def _strip_fence(text: str) -> str:
    text = text.strip()
    if text.startswith("```"):
        lines = text.splitlines()
        lines = lines[1:]
        if lines and lines[-1].strip() == "```":
            lines = lines[:-1]
        text = "\n".join(lines).strip()
    return text


def check_frames(
    frame_paths: list[Path],
    api_key: str,
    model: str = "claude-sonnet-4-5",
) -> FrameCheckResult:
    """Send sampled frames to Claude vision, return a strict pass/fail."""
    if not frame_paths:
        return FrameCheckResult(False, "no frames provided", "none")

    content: list[dict] = [
        {
            "type": "text",
            "text": f"Here are {len(frame_paths)} frames from a candidate clip, "
            "in temporal order. Apply the purity rules. Return JSON.",
        }
    ]
    for p in frame_paths:
        data = base64.standard_b64encode(p.read_bytes()).decode("ascii")
        content.append(
            {
                "type": "image",
                "source": {
                    "type": "base64",
                    "media_type": "image/jpeg",
                    "data": data,
                },
            }
        )

    client = anthropic.Anthropic(api_key=api_key)
    # Anthropic returns 529 "Overloaded" intermittently — retry with backoff.
    import time

    last_err: Exception | None = None
    for attempt in range(6):
        try:
            resp = client.messages.create(
                model=model,
                max_tokens=400,
                system=SYSTEM_PROMPT,
                messages=[{"role": "user", "content": content}],
            )
            break
        except anthropic.APIStatusError as e:
            last_err = e
            if e.status_code == 529 or e.status_code == 429:
                time.sleep(min(2 ** attempt, 20))  # 1,2,4,8,16,20s — cap to keep total < 1m
                continue
            raise
    else:
        raise RuntimeError(f"Anthropic overloaded after retries: {last_err}")
    text = "".join(b.text for b in resp.content if b.type == "text")
    text = _strip_fence(text)
    try:
        data = json.loads(text)
    except json.JSONDecodeError as e:
        raise RuntimeError(f"Frame check returned non-JSON: {text[:200]}") from e

    return FrameCheckResult(
        clean=bool(data.get("clean", False)),
        reason=str(data.get("reason", "")).strip(),
        facecam_corner=str(data.get("facecam_corner", "none")).strip(),
    )
