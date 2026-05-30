from __future__ import annotations

import json
from dataclasses import dataclass

import anthropic

from .youtube import Candidate

SYSTEM_PROMPT = """You judge whether a YouTube video is likely to contain a genuine \
record-breaking, "insane", or otherwise highlight-worthy Brawl Stars moment \
suitable for a 15-45s short-form fan edit.

KEEP if the title/description suggests a single climactic moment a viewer would \
rewind to: world records, first-evers, 1v3/1v4 clutches, highest damage runs, \
unprecedented plays, "no way" reactions on rare events.

DROP if it's: tier lists, tutorials, guides, patch-note recaps, news, a long \
montage with no specific peak, drama/commentary, or pure clickbait with no real \
moment ("INSANE!!!" on a routine match).

Lean toward KEEP when in doubt — downstream moment-detection can still bail out. \
Return strict JSON only."""


@dataclass
class FilterDecision:
    video_id: str
    keep: bool
    reason: str


def filter_candidates(
    candidates: list[Candidate],
    api_key: str,
    model: str = "claude-haiku-4-5-20251001",
    max_tokens: int = 2048,
) -> list[FilterDecision]:
    """Ask Claude which candidates likely contain a real highlight moment.

    Batched in one call. Returns one decision per input video.
    """
    if not candidates:
        return []

    payload = [
        {
            "id": c.video_id,
            "title": c.title,
            "channel": c.channel_title,
            "description": c.description[:400],
            "tags": c.tags[:12],
            "duration_s": c.duration_s,
            "views": c.view_count,
        }
        for c in candidates
    ]

    user_msg = (
        "For each video, return one JSON object on its own line with keys "
        '{"id", "keep", "reason"}. "keep" is a boolean. "reason" is one short '
        "sentence. Output ONLY a JSON array, no prose, no markdown fences.\n\n"
        "VIDEOS:\n" + json.dumps(payload, ensure_ascii=False)
    )

    client = anthropic.Anthropic(api_key=api_key)
    import time

    last_err: Exception | None = None
    for attempt in range(4):
        try:
            resp = client.messages.create(
                model=model,
                max_tokens=max_tokens,
                system=SYSTEM_PROMPT,
                messages=[{"role": "user", "content": user_msg}],
            )
            break
        except anthropic.APIStatusError as e:
            last_err = e
            if e.status_code in (429, 529):
                time.sleep(2 ** attempt)
                continue
            raise
    else:
        raise RuntimeError(f"Anthropic overloaded after retries: {last_err}")

    text = "".join(block.text for block in resp.content if block.type == "text").strip()
    text = _strip_code_fence(text)

    try:
        data = json.loads(text)
    except json.JSONDecodeError as e:
        raise RuntimeError(f"Hype filter returned non-JSON: {text[:200]}") from e

    by_id = {c.video_id: c for c in candidates}
    decisions: list[FilterDecision] = []
    seen: set[str] = set()
    for row in data:
        vid = row.get("id")
        if vid not in by_id:
            continue
        decisions.append(
            FilterDecision(
                video_id=vid,
                keep=bool(row.get("keep", True)),
                reason=str(row.get("reason", "")).strip(),
            )
        )
        seen.add(vid)
    # Default to keep for anything the model omitted.
    for vid in by_id:
        if vid not in seen:
            decisions.append(FilterDecision(video_id=vid, keep=True, reason="(no decision)"))
    return decisions


def _strip_code_fence(text: str) -> str:
    if text.startswith("```"):
        lines = text.splitlines()
        if lines[0].startswith("```"):
            lines = lines[1:]
        if lines and lines[-1].strip() == "```":
            lines = lines[:-1]
        text = "\n".join(lines).strip()
    return text
