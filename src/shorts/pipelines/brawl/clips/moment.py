"""Pick the climax moment inside a long video.

Pipeline:
  1. Pull top comments and cluster timestamp mentions (cheapest signal).
  2. For each ranked cluster, download the candidate window via yt-dlp.
  3. Sample N frames from the window.
  4. Vision-gate via Claude: must be pure gameplay, no people, no menus.
  5. Return the first window that passes. If none pass, return failure.

Audio-peak + Whisper-LLM fallbacks (steps 2b/2c from the brief) are stubbed
for a later pass — comment clustering covers most cases.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

from . import comments, download, frame_check


@dataclass
class MomentResult:
    video_id: str
    start_s: int
    end_s: int
    confidence: float           # 0-1, from cluster weight + frame purity
    rationale: str
    frame_paths: list[Path] = field(default_factory=list)
    facecam_corner: str = "none"
    clip_path: Path | None = None
    attempts: list[dict] = field(default_factory=list)  # debug trail


def _window_for(center_s: int, video_duration_s: int, clip_len_s: int = 25) -> tuple[int, int]:
    """Window the clip around the commenter timestamp.

    YouTube norm: comment timestamps point to the START of the highlight, not
    the middle. So lead-in is small (~3s context) and the bulk of the window
    is *after* the timestamp. This also keeps us away from the post-match
    results screen that often follows by 20–30s.
    """
    lead = clip_len_s * 0.15   # ~4s of context
    trail = clip_len_s * 0.85
    start = max(0, int(center_s - lead))
    end = min(video_duration_s, int(center_s + trail))
    # If we hit a boundary, expand the other side to keep total length.
    if end - start < clip_len_s:
        if start == 0:
            end = min(video_duration_s, clip_len_s)
        else:
            start = max(0, end - clip_len_s)
    return start, end


def pick_moment(
    video_id: str,
    video_duration_s: int,
    youtube_api_key: str,
    anthropic_api_key: str,
    clip_len_s: int = 25,
    max_attempts: int = 4,
    vision_model: str = "claude-haiku-4-5-20251001",
) -> MomentResult | None:
    """Return a vision-validated moment, or None if no candidate passes."""
    clusters = comments.find_moment_from_comments(
        api_key=youtube_api_key,
        video_id=video_id,
        duration_s=video_duration_s,
    )
    attempts: list[dict] = []

    if not clusters:
        return MomentResult(
            video_id=video_id,
            start_s=0,
            end_s=0,
            confidence=0.0,
            rationale="No timestamped comments found.",
            attempts=attempts,
        )

    # For each cluster, try the biased window first, then nudge earlier/later.
    # Many gameplay videos (especially "push" compilations) have match
    # transitions every ~60-90s; a 12s shift often lands fully inside one match.
    jitter_offsets = [0, -12, +12, -25]

    for rank, (center, n_mentions, weight) in enumerate(clusters[:max_attempts], 1):
        for j_idx, off in enumerate(jitter_offsets):
            shifted_center = center + off
            if shifted_center < clip_len_s // 2:
                continue
            if shifted_center > video_duration_s - clip_len_s // 2:
                continue
            start, end = _window_for(shifted_center, video_duration_s, clip_len_s)
            attempt: dict = {
                "rank": rank,
                "jitter": off,
                "center_s": shifted_center,
                "mentions": n_mentions,
                "weight": round(weight, 2),
                "window": [start, end],
            }
            try:
                clip_path = download.download_window(video_id, start, end)
                frames = download.sample_frames(clip_path, n=6)
                verdict = frame_check.check_frames(
                    frames, api_key=anthropic_api_key, model=vision_model
                )
            except Exception as e:
                attempt["error"] = str(e)
                attempts.append(attempt)
                continue

            attempt["clean"] = verdict.clean
            attempt["reason"] = verdict.reason
            attempt["facecam_corner"] = verdict.facecam_corner
            attempts.append(attempt)

            if verdict.clean:
                max_w = clusters[0][2] or 1.0
                cluster_score = min(1.0, weight / max_w) * 0.7
                # Penalize jittered hits slightly — a jitter=0 win is more
                # signal-aligned than a jitter=-25 win.
                jitter_penalty = 0.05 * j_idx
                confidence = round(cluster_score + 0.3 - jitter_penalty, 3)
                rationale = (
                    f"Cluster #{rank}: {n_mentions} timestamp mentions near "
                    f"{center}s (weight {weight:.1f}); jitter={off:+d}s. "
                    f"Frames pure: {verdict.reason}"
                )
                return MomentResult(
                    video_id=video_id,
                    start_s=start,
                    end_s=end,
                    confidence=confidence,
                    rationale=rationale,
                    frame_paths=frames,
                    facecam_corner=verdict.facecam_corner,
                    clip_path=clip_path,
                    attempts=attempts,
                )
        # All jitters for this cluster failed — try the next cluster.

    # No cluster's window passed the vision gate.
    return MomentResult(
        video_id=video_id,
        start_s=0,
        end_s=0,
        confidence=0.0,
        rationale=(
            f"Tried {len(attempts)} cluster(s); none passed the gameplay-purity check. "
            f"Last reason: {attempts[-1].get('reason', '?') if attempts else 'n/a'}"
        ),
        attempts=attempts,
    )


def pick_moment_manual(
    video_id: str,
    start_s: int,
    end_s: int,
    anthropic_api_key: str,
    vision_model: str = "claude-haiku-4-5-20251001",
) -> MomentResult | None:
    """Cut an explicit, reviewer-chosen [start_s, end_s] window.

    Skips comment-cluster detection entirely (the reviewer told us exactly where
    to cut), but still downloads the window and runs the frame check so we get
    the facecam corner for cropping. Vision purity is advisory here — we honour
    the human's choice and never reject the window.
    """
    if end_s <= start_s:
        return None
    clip_path = download.download_window(video_id, start_s, end_s)
    facecam_corner = "none"
    reason = "manual cut — vision check skipped"
    try:
        frames = download.sample_frames(clip_path, n=6)
        verdict = frame_check.check_frames(
            frames, api_key=anthropic_api_key, model=vision_model
        )
        facecam_corner = verdict.facecam_corner
        reason = verdict.reason
    except Exception as e:  # advisory only — never block a manual cut
        frames = []
        reason = f"frame check failed (ignored): {e}"

    return MomentResult(
        video_id=video_id,
        start_s=start_s,
        end_s=end_s,
        confidence=1.0,
        rationale=f"Manual cut [{start_s}s → {end_s}s]. {reason}",
        frame_paths=frames,
        facecam_corner=facecam_corner,
        clip_path=clip_path,
        attempts=[],
    )
