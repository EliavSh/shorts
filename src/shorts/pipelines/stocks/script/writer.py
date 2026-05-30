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


def _load_system_prompt(lang: str) -> str:
    s = get_settings()
    p = s.project_root / "src" / "stocksreels" / "script" / "prompts" / f"system_{lang}.md"
    template = p.read_text(encoding="utf-8")
    menu = formats.render_format_menu_markdown()
    return template.replace("{format_menu}", menu)


def _topic_to_user_message(ctx: TopicContext, format_hint: str | None) -> str:
    payload: dict[str, Any] = ctx.model_dump()
    instruction = "Choose the most fitting format and write the script."
    if format_hint:
        instruction = f"Use the `{format_hint}` format. " + instruction

    # If the writer picked a format upstream, append that format's specific rules.
    extra = ""
    if format_hint:
        extra = "\n\n## Format-specific rules\n\n" + formats.get_spec(format_hint).prompt_addendum

    return (
        f"{instruction}\n\n"
        "Topic context (JSON):\n"
        f"```json\n{json.dumps(payload, ensure_ascii=False, indent=2)}\n```"
        f"{extra}"
    )


def write_script(ctx: TopicContext, *, model: str | None = None,
                 format_hint: str | None = None) -> Script:
    """Generate a script for the given topic context.

    If `format_hint` is provided, that format's specific rules are appended to
    the user message and the model is gently steered to use it. Otherwise the
    model picks from the menu.
    """
    s = get_settings()
    if not s.anthropic_api_key:
        raise RuntimeError(
            "ANTHROPIC_API_KEY not set — cannot call Claude. Add it to .env, or "
            "use write_script_from_fixture() for offline testing."
        )

    client = make_anthropic()
    system_prompt = _load_system_prompt(ctx.lang)
    user_message = _topic_to_user_message(ctx, format_hint)
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
