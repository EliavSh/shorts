"""Script writer — single-pass call to Claude. The prompt lists every
registered format; Claude picks one and writes the script."""
from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any

from .. import formats  # registers built-in formats
from shorts.core.infra.anthropic_client import make_client as make_anthropic
from ..settings import get_settings
from .schemas import Script, TopicContext

log = logging.getLogger(__name__)


_PROMPTS_DIR = Path(__file__).resolve().parent / "prompts"

# Pacing constant shared with the length-guidance math. edge-tts / ElevenLabs
# both land close to this for calm finance narration.
_WORDS_PER_SECOND = 2.7
# Roughly one narrative beat per this many spoken seconds.
_SECONDS_PER_BEAT = 13


def _length_guidance(length_band: tuple[int, int] | None) -> str:
    """Render the prose that tells the model how long to make the video.

    `length_band` bounds the writer's choice of `target_seconds`. When None we
    use the full 90–180s Shorts range and let the model decide entirely on
    topic depth.
    """
    lo, hi = length_band or (90, 180)
    lo = max(60, min(lo, 180))
    hi = max(lo, min(hi, 180))

    def words(sec: int) -> int:
        return round(sec * _WORDS_PER_SECOND / 10) * 10

    def beats(sec: int) -> int:
        return max(2, round(sec / _SECONDS_PER_BEAT))

    if lo == hi:
        return (
            f"Make this video **{lo} seconds** long. At ~{_WORDS_PER_SECOND} words/sec "
            f"that is about **{words(lo)} words** across roughly **{beats(lo)} beats**. "
            f"Set `target_seconds` to {lo}."
        )
    return (
        f"Choose a length between **{lo} and {hi} seconds** and set `target_seconds` to "
        f"that exact value. Decide based on how much real substance the topic has — "
        f"enough to satisfy the viewer, never padded with filler.\n\n"
        f"- A lean topic → ~{lo}s ≈ **{words(lo)} words** across ~{beats(lo)} beats.\n"
        f"- A rich, layered topic → ~{hi}s ≈ **{words(hi)} words** across ~{beats(hi)} beats.\n\n"
        f"At ~{_WORDS_PER_SECOND} words/sec, write narration to the word budget for the "
        f"`target_seconds` you pick. If the topic context is thin, pick the shorter end "
        f"rather than inventing detail."
    )


def _load_system_prompt(lang: str, length_band: tuple[int, int] | None) -> str:
    p = _PROMPTS_DIR / f"system_{lang}.md"
    template = p.read_text(encoding="utf-8")
    menu = formats.render_format_menu_markdown()
    return (
        template
        .replace("{format_menu}", menu)
        .replace("{length_guidance}", _length_guidance(length_band))
    )


def _topic_to_user_message(ctx: TopicContext, format_hint: str | None,
                           guidance: str | None = None) -> str:
    payload: dict[str, Any] = ctx.model_dump()
    instruction = "Choose the most fitting format and write the script."
    if format_hint:
        instruction = f"Use the `{format_hint}` format. " + instruction

    # If the writer picked a format upstream, append that format's specific rules.
    extra = ""
    if format_hint:
        extra = "\n\n## Format-specific rules\n\n" + formats.get_spec(format_hint).prompt_addendum

    # Reviewer feedback on a previous version — this is a rewrite, not a fresh
    # write. Address the notes directly while keeping the same topic + format.
    feedback = ""
    if guidance and guidance.strip():
        feedback = (
            "\n\n## Reviewer feedback to address (REWRITE)\n\n"
            "A previous version of this exact video was rejected. Rewrite the "
            "script to directly address every note below. Keep the same topic and "
            "format; change only what the feedback calls for.\n\n"
            f"{guidance.strip()}"
        )

    return (
        f"{instruction}\n\n"
        "Topic context (JSON):\n"
        f"```json\n{json.dumps(payload, ensure_ascii=False, indent=2)}\n```"
        f"{extra}{feedback}"
    )


def write_script(ctx: TopicContext, *, model: str | None = None,
                 format_hint: str | None = None,
                 length_band: tuple[int, int] | None = None,
                 guidance: str | None = None) -> Script:
    """Generate a script for the given topic context.

    If `format_hint` is provided, that format's specific rules are appended to
    the user message and the model is gently steered to use it. Otherwise the
    model picks from the menu.

    `length_band` (lo, hi) seconds bounds the writer's choice of
    `target_seconds`. When None, the full 90–180s Shorts range applies and the
    model decides purely on topic depth. When a `format_hint` is given and no
    explicit band is passed, the format's own `length_band` is used.
    """
    s = get_settings()
    if not s.anthropic_api_key:
        raise RuntimeError(
            "ANTHROPIC_API_KEY not set — cannot call Claude. Add it to .env, or "
            "use write_script_from_fixture() for offline testing."
        )

    if length_band is None and format_hint:
        length_band = getattr(formats.get_spec(format_hint), "length_band", None)

    client = make_anthropic()
    system_prompt = _load_system_prompt(ctx.lang, length_band)
    user_message = _topic_to_user_message(ctx, format_hint, guidance)
    chosen_model = model or s.claude_model

    log.info("Calling Claude (model=%s, lang=%s, hint=%s)", chosen_model, ctx.lang, format_hint)

    tool = {
        "name": "emit_script",
        "description": "Emit the finished video script as structured JSON.",
        "input_schema": Script.model_json_schema(),
    }
    response = client.messages.create(
        model=chosen_model,
        max_tokens=2048,
        system=system_prompt,
        tools=[tool],
        tool_choice={"type": "tool", "name": "emit_script"},
        messages=[{"role": "user", "content": user_message}],
    )

    for block in response.content:
        if getattr(block, "type", None) == "tool_use" and block.name == "emit_script":
            payload = block.input
            # Claude sometimes wraps the schema output in {"script": {...}} despite
            # the tool input_schema being the Script itself. Unwrap.
            if isinstance(payload, dict) and set(payload.keys()) == {"script"} and isinstance(payload["script"], dict):
                payload = payload["script"]
            script = Script.model_validate(payload)
            _validate_format_constraints(script)
            return script

    raise RuntimeError(f"Claude did not emit a tool_use block. Stop reason: {response.stop_reason!r}")


def _validate_format_constraints(script: Script) -> None:
    """Check that the script honours its declared format's ticker constraints."""
    try:
        spec = formats.get_spec(script.format)
    except KeyError as e:
        raise ValueError(str(e)) from e

    n = len(script.tickers)
    if n < spec.min_tickers or n > spec.max_tickers:
        raise ValueError(
            f"format {script.format!r} requires {spec.min_tickers}-{spec.max_tickers} tickers, got {n}"
        )


def write_script_from_fixture(path: Path) -> Script:
    """Load a pre-recorded script JSON. Validates against schema + format constraints."""
    data = json.loads(path.read_text(encoding="utf-8"))
    script = Script.model_validate(data)
    _validate_format_constraints(script)
    return script
