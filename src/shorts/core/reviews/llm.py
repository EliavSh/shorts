"""LLM helpers for generating per-version title + description from clip context.

Shared between pipelines because both need the same pattern: take a moment
context + accumulated insights + (optional) feedback → produce JSON
{title, description}.
"""
from __future__ import annotations

import json
import time
from typing import Any

import anthropic

META_SYSTEM = """You write metadata for a Shorts content channel that credits \
original creators. Return strict JSON with keys: title, description.

title: 60-80 chars max, gen-Z gaming/finance voice, may include 1-2 emoji, no \
clickbait all-caps spam. Hook the scroll.

description: 2-3 sentences. Sentence 1 hypes the moment. Sentence 2 credits the \
original creator clearly. Include the source URL. End with 4-6 relevant hashtags.

No markdown, no commentary, just the JSON."""


def _strip_fence(text: str) -> str:
    text = text.strip()
    if text.startswith("```"):
        lines = text.splitlines()[1:]
        if lines and lines[-1].strip() == "```":
            lines = lines[:-1]
        text = "\n".join(lines).strip()
    return text


def generate_title_and_description(
    *,
    creator: str,
    source_url: str,
    hook_text: str,
    moment_context: str,
    api_key: str,
    insights_text: str = "",
    feedback_text: str = "",
    model: str = "claude-haiku-4-5-20251001",
    extra_system: str = "",
) -> tuple[str, str]:
    client = anthropic.Anthropic(api_key=api_key)
    user_parts = [
        f"Original creator: {creator}",
        f"Source URL: {source_url}",
        f"Hook overlay used: {hook_text}",
        f"Moment context: {moment_context}",
    ]
    if insights_text:
        user_parts.append("\nAccumulated reviewer insights — keep these in mind:\n" + insights_text)
    if feedback_text:
        user_parts.append("\nFeedback on the previous version of this clip:\n" + feedback_text)
    user_parts.append("\nWrite the metadata JSON.")

    system = META_SYSTEM + ("\n\n" + extra_system if extra_system else "")

    last_err: Exception | None = None
    for attempt in range(4):
        try:
            resp = client.messages.create(
                model=model,
                max_tokens=600,
                system=system,
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

    text = "".join(b.text for b in resp.content if b.type == "text")
    text = _strip_fence(text)
    try:
        data: dict[str, Any] = json.loads(text)
    except json.JSONDecodeError:
        return (
            f"{hook_text}",
            f"Clip via @{creator}. Watch the full video: {source_url}",
        )
    return str(data.get("title", "")).strip(), str(data.get("description", "")).strip()
