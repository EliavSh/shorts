"""Video composer — orchestrates: background visuals (retrieved+Ken Burns),
captions (from word timings), format-specific overlays (ticker cards),
attribution credits, and persistent disclaimer.
"""
from __future__ import annotations

import json
import logging
from pathlib import Path

import random

from moviepy import AudioFileClip, ColorClip, CompositeAudioClip, CompositeVideoClip
from moviepy.audio.fx import AudioLoop, MultiplyVolume

from .. import formats
from ..script.schemas import Script
from shorts.core.visuals.attribution import render_attribution
from shorts.pipelines.stocks.visuals.brand import load_brand
from shorts.core.visuals.captions import FRAME_H, FRAME_W, render_caption
from ..visuals.disclaimer import render_disclaimer
from ..visuals.director import make_plan
from ..visuals.scheduler import schedule_plan, shot_to_clip
from ..voice.align import align_to_timings
from ..voice.tts import TTSResult
from ._shared_compose import pil_to_clip
from .chunker import chunk_words
from ..formats._shared import compute_beat_timings

log = logging.getLogger(__name__)

FPS = 30
FALLBACK_BG = (12, 24, 48)
ATTRIBUTION_POS_Y_PCT = 0.86  # under the visual, above the caption pill region
ATTRIBUTION_MARGIN = 32


def _pick_music_bed(duration_s: float):
    """Pick a random track from assets/music/, loop+duck it to fit the video.

    Returns None if the directory is empty (silent default). Drop any
    royalty-free mp3 or wav files into assets/music/ to enable music.
    """
    from ..settings import get_settings
    s = get_settings()
    if not s.music_dir.exists():
        return None
    tracks = [p for p in s.music_dir.iterdir() if p.suffix.lower() in (".mp3", ".wav", ".m4a", ".ogg")]
    if not tracks:
        return None
    pick = random.choice(tracks)
    log.info("Music bed: %s @ %.1fdB", pick.name, s.music_volume_db)
    bed = AudioFileClip(str(pick))
    if bed.duration < duration_s:
        bed = bed.with_effects([AudioLoop(duration=duration_s)])
    else:
        bed = bed.subclipped(0, duration_s)
    # Convert dB to linear gain: 10^(dB/20)
    gain = 10 ** (s.music_volume_db / 20.0)
    return bed.with_effects([MultiplyVolume(gain)])


def compose_video(*, script: Script, tts: TTSResult, out_path: Path,
                  guidance: str | None = None) -> Path:
    """Render the final 1080x1920 mp4.

    `guidance` carries reviewer feedback from a comment-driven regeneration so
    the visual director can correct mismatched/boring imagery.
    """
    brand = load_brand(script.lang)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    audio_clip = AudioFileClip(str(tts.audio_path))
    total_s = audio_clip.duration

    timings = compute_beat_timings(script, total_s)
    log.info("Composing %d beats over %.2fs in format=%r", len(timings), total_s, script.format)

    layers = []

    # 0. Fallback background (visible only where no shot is scheduled).
    layers.append(ColorClip(size=(FRAME_W, FRAME_H), color=FALLBACK_BG, duration=total_s).with_start(0))

    # 1. Background visuals — director plans sections, scheduler picks images.
    plan = make_plan(script, total_duration_s=total_s, guidance=guidance)
    log.info("Visual plan: %d sections", len(plan.sections))
    for sec in plan.sections:
        log.info("  [%.1f-%.1f] %s", sec.start_s, sec.end_s, sec.intent[:80])
    shots = schedule_plan(plan, script)
    log.info("Scheduled %d visual shots", len(shots))
    for shot in shots:
        layers.append(shot_to_clip(shot))

    # 2. Per-shot attribution credit.
    for shot in shots:
        if not shot.image.attribution:
            continue
        attr_img = render_attribution(brand, shot.image.attribution, max_width=720)
        x = ATTRIBUTION_MARGIN
        y = int(FRAME_H * ATTRIBUTION_POS_Y_PCT)
        layers.append(pil_to_clip(attr_img, start_s=shot.start_s, end_s=shot.end_s, position=(x, y)))

    # 3. Captions — script-text-anchored, timed from Whisper timings (R1).
    aligned = align_to_timings(script.narration_text(), tts.words)
    log.info("Aligned %d script words to %d Whisper timings", len(aligned), len(tts.words))
    chunks = chunk_words(aligned)
    log.info("Caption chunks: %d", len(chunks))
    for c in chunks:
        cap_img, cap_pos = render_caption(brand=brand, text=c.text)
        layers.append(pil_to_clip(cap_img, start_s=c.start_s, end_s=c.end_s, position=cap_pos))

    # 4. Format-specific overlays (ticker cards, comparison graphics, etc.).
    overlays_fn = formats.get_overlays_fn(script.format)
    layers.extend(overlays_fn(script=script, tts=tts, brand=brand, total_duration_s=total_s))

    # 5. Persistent disclaimer at the bottom.
    disc_img, disc_pos = render_disclaimer(brand=brand)
    layers.append(pil_to_clip(disc_img, start_s=0.0, end_s=total_s, position=disc_pos))

    # 6. Composite. Add background music bed (ducked) if any tracks live in assets/music/.
    final_audio = audio_clip
    bed = _pick_music_bed(total_s)
    if bed is not None:
        final_audio = CompositeAudioClip([bed, audio_clip])
    video = CompositeVideoClip(layers, size=(FRAME_W, FRAME_H))
    video = video.with_audio(final_audio).with_duration(total_s)

    log.info("Writing %s ...", out_path)
    video.write_videofile(
        str(out_path),
        fps=FPS,
        codec="libx264",
        audio_codec="aac",
        preset="medium",
        threads=4,
        logger=None,
    )

    # Write a sidecar manifest describing what was chosen — useful for the
    # `stocksreels inspect` command and for the dashboard later.
    # Include a cost_breakdown sourced from the usage layer (R-cost).
    from shorts.core.usage import current_video, spend_by_video
    cost_breakdown: dict = {}
    cur = current_video()
    if cur:
        v = spend_by_video().get(cur, {})
        cost_breakdown = {
            "total_usd": round(v.get("cost_usd", 0.0), 4),
            "by_provider": {k: round(c, 4) for k, c in v.get("by_provider", {}).items()},
            "events": v.get("events", 0),
            "video_slug": cur,
        }
    manifest_path = out_path.with_suffix(".manifest.json")
    manifest = {
        "mp4": out_path.name,
        "lang": script.lang,
        "format": script.format,
        "title": script.title,
        "duration_s": total_s,
        "tickers": [t.model_dump() for t in script.tickers],
        "plan_sections": [
            {
                "start_s": round(sec.start_s, 2),
                "end_s": round(sec.end_s, 2),
                "intent": sec.intent,
                "queries": sec.search_queries,
                "ticker_focus": sec.ticker_focus,
            }
            for sec in plan.sections
        ],
        "shots": [
            {
                "start_s": round(s.start_s, 2),
                "end_s": round(s.end_s, 2),
                "image_path": str(s.image.path),
                "source": s.image.source,
                "title": s.image.title,
                "url": s.image.url,
                "attribution": s.image.attribution,
                "relevance": round(s.relevance, 3),
                "intent": s.intent,
            }
            for s in shots
        ],
        "cost_breakdown": cost_breakdown,
    }
    manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
    return out_path
