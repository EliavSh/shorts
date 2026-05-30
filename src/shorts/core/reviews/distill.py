"""Reviewer-insight memory — per-pipeline.

Every comment the reviewer leaves gets distilled by Claude into 1-3 short
actionable bullets and merged into a per-pipeline insights file. That file is
loaded as context whenever a new version (or future clip) is generated, so
later edits learn from earlier feedback within the pipeline.
"""
from __future__ import annotations

import json
import time
from dataclasses import asdict, dataclass, field
from datetime import datetime
from pathlib import Path

import anthropic

from shorts.config import pipeline_data_dir


@dataclass
class Insight:
    bullet: str
    added_at: str
    from_run: str
    source_comment: str
    category: str = "general"   # general | hook | captions | moment | metadata


@dataclass
class InsightsFile:
    insights: list[Insight] = field(default_factory=list)
    last_updated: str = ""


EXTRACT_SYSTEM_TEMPLATE = """You distill reviewer feedback on {kind} short-form video edits \
into 1-3 short ACTIONABLE bullets that future edits can follow.

Input: a free-form comment in any language (often Hebrew or English) plus context \
about the clip it was about.

Output: strict JSON with key "insights" — array of objects with keys "bullet" and \
"category". `category` is one of: "general", "hook", "captions", "moment", "metadata".

Rules for the bullets:
- Each bullet ≤ 18 words.
- Always in English (so bullets merge uniformly).
- Imperative voice: "Use shorter hook copy"; "Avoid mentioning X"; etc.
- Skip the bullet entirely if the comment is just a compliment or pure question.
- Skip if the comment is too specific to ONE clip and doesn't generalize.
- Merge duplicate insights — if two comments say roughly the same thing, output one.

No markdown, no prose, just the JSON."""


KIND_BY_PIPELINE = {
    "brawl": "Brawl Stars gameplay",
    "stocks": "finance / market news",
}


def _now() -> str:
    return datetime.now().isoformat(timespec="seconds")


def _strip_fence(text: str) -> str:
    text = text.strip()
    if text.startswith("```"):
        lines = text.splitlines()[1:]
        if lines and lines[-1].strip() == "```":
            lines = lines[:-1]
        text = "\n".join(lines).strip()
    return text


def _path_for(pipeline: str) -> Path:
    return pipeline_data_dir(pipeline) / "insights.json"


def load(pipeline: str) -> InsightsFile:
    p = _path_for(pipeline)
    if not p.exists():
        return InsightsFile()
    data = json.loads(p.read_text(encoding="utf-8"))
    data["insights"] = [Insight(**i) for i in data.get("insights", [])]
    return InsightsFile(**data)


def save(pipeline: str, f: InsightsFile) -> None:
    f.last_updated = _now()
    p = _path_for(pipeline)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(
        json.dumps(asdict(f), indent=2, ensure_ascii=False),
        encoding="utf-8",
    )


def format_for_prompt(pipeline: str, max_bullets: int = 20) -> str:
    """Return insights as a bullet list suitable for inclusion in LLM prompts."""
    f = load(pipeline)
    if not f.insights:
        return ""
    recent = f.insights[-max_bullets:]
    return "\n".join(f"- ({i.category}) {i.bullet}" for i in recent)


def extract_and_save(
    pipeline: str,
    comment_text: str,
    run_context: str,
    api_key: str,
    run_id: str,
    model: str = "claude-haiku-4-5-20251001",
) -> list[Insight]:
    """Distill a comment → bullets, append to per-pipeline file, return new bullets."""
    if not comment_text.strip():
        return []

    kind = KIND_BY_PIPELINE.get(pipeline, "short-form video")
    system = EXTRACT_SYSTEM_TEMPLATE.format(kind=kind)

    client = anthropic.Anthropic(api_key=api_key)
    user = (
        f"Clip context: {run_context}\n\n"
        f"Reviewer comment: {comment_text}\n\n"
        "Extract bullets."
    )
    last_err: Exception | None = None
    for attempt in range(4):
        try:
            resp = client.messages.create(
                model=model,
                max_tokens=400,
                system=system,
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
        return []

    text = "".join(b.text for b in resp.content if b.type == "text")
    text = _strip_fence(text)
    try:
        data = json.loads(text)
    except json.JSONDecodeError:
        return []

    new_bullets: list[Insight] = []
    for row in data.get("insights", []):
        bullet = str(row.get("bullet", "")).strip()
        if not bullet:
            continue
        new_bullets.append(
            Insight(
                bullet=bullet,
                added_at=_now(),
                from_run=run_id,
                source_comment=comment_text[:300],
                category=str(row.get("category", "general")),
            )
        )

    if new_bullets:
        f = load(pipeline)
        f.insights.extend(new_bullets)
        save(pipeline, f)
    return new_bullets
