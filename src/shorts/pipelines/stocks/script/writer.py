"""Script writer — single-pass call to Claude. The prompt lists every
registered format; Claude picks one and writes the script."""
from __future__ import annotations

import json
import logging
import re
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
    chosen_model = model or s.claude_model

    log.info("Calling Claude (model=%s, lang=%s, hint=%s)", chosen_model, ctx.lang, format_hint)

    script = _emit_script(client, chosen_model, system_prompt,
                          _topic_to_user_message(ctx, format_hint, guidance))

    # Ground spoken figures against the live snapshot; one corrective rewrite if
    # anything looks invented. Best-effort — a failed rewrite keeps the original.
    flagged = _check_numbers(script, ctx)
    if flagged:
        log.warning("number-grounding flagged %s — one corrective rewrite", flagged)
        note = (
            "IMPORTANT: only cite figures that appear in the topic context JSON. "
            "The following numbers don't match the data and look invented — remove "
            "them or replace with the correct value from the context: "
            + "; ".join(flagged)
        )
        combined = f"{guidance}\n\n{note}" if guidance else note
        try:
            script = _emit_script(client, chosen_model, system_prompt,
                                  _topic_to_user_message(ctx, format_hint, combined))
        except Exception as e:
            log.warning("corrective rewrite failed, keeping original: %s", e)

    # Punch up the opening line — the first ~1.5s decide a Short. Best-effort.
    _strengthen_hook(script, client=client, model=s.claude_director_model)
    return script


def _emit_script(client, model: str, system_prompt: str, user_message: str) -> Script:
    """One structured `emit_script` tool call → a validated, constraint-repaired
    Script. Raises if the model returns no tool_use block."""
    tool = {
        "name": "emit_script",
        "description": "Emit the finished video script as structured JSON.",
        "input_schema": Script.model_json_schema(),
    }
    response = client.messages.create(
        model=model,
        # `beats` is the LAST field in the Script schema, so a tight ceiling
        # truncates the script's actual content first and the partial-JSON
        # parser hands back a beats-less dict. Give ample headroom — output
        # tokens are billed only for what's generated, so a high cap is free
        # unless used.
        max_tokens=8192,
        system=system_prompt,
        tools=[tool],
        tool_choice={"type": "tool", "name": "emit_script"},
        messages=[{"role": "user", "content": user_message}],
    )

    # A max_tokens cutoff yields a silently-truncated tool input (e.g. missing
    # `beats`) that fails validation with a cryptic error — surface it plainly.
    if response.stop_reason == "max_tokens":
        raise RuntimeError(
            "Claude hit max_tokens before finishing the script (output truncated). "
            "Increase max_tokens or shorten the requested length."
        )

    for block in response.content:
        if getattr(block, "type", None) == "tool_use" and block.name == "emit_script":
            payload = block.input
            # Claude sometimes wraps the schema output in {"script": {...}} despite
            # the tool input_schema being the Script itself. Unwrap.
            if isinstance(payload, dict) and set(payload.keys()) == {"script"} and isinstance(payload["script"], dict):
                payload = payload["script"]
            script = Script.model_validate(payload)
            _repair_format_constraints(script)
            _validate_format_constraints(script)
            return script

    raise RuntimeError(f"Claude did not emit a tool_use block. Stop reason: {response.stop_reason!r}")


def _strengthen_hook(script: Script, *, client, model: str) -> None:
    """Rewrite the hook beat into a punchier ≤~14-word opener via a cheap model.
    Best-effort: any failure leaves the original hook untouched."""
    if not script.beats:
        return
    idx = next((i for i, b in enumerate(script.beats) if b.role == "hook"), 0)
    beat = script.beats[idx]
    original = (beat.narration or "").strip()
    if not original:
        return
    prompt = (
        "You are punching up the OPENING line of a vertical finance Short. Rewrite "
        "the hook so the first 1.5 seconds grab attention: at most 14 words, "
        "concrete, curiosity- or number-led, no hashtags, no emoji, and keep the "
        "same topic and facts. Return ONLY the rewritten line, nothing else.\n\n"
        f"Hook: {original}"
    )
    try:
        resp = client.messages.create(
            model=model, max_tokens=80,
            messages=[{"role": "user", "content": prompt}],
        )
        text = "".join(getattr(b, "text", "") for b in resp.content
                       if getattr(b, "type", None) == "text").strip().strip('"').strip()
        if text and 2 <= len(text.split()) <= 18:
            beat.narration = text
            log.info("hook strengthened: %r -> %r", original, text)
    except Exception as e:
        log.debug("hook strengthen skipped: %s", e)


# --- Number grounding -------------------------------------------------------

_MAG = {"trillion": 1e12, "t": 1e12, "billion": 1e9, "bn": 1e9, "b": 1e9,
        "million": 1e6, "m": 1e6, "thousand": 1e3, "k": 1e3}
_TOKEN_RE = re.compile(
    r"(?P<dollar>\$)?\s*(?P<num>\d[\d,]*(?:\.\d+)?)\s*"
    r"(?P<unit>%|percent|trillion|billion|million|thousand|bn|[kmbt])?\b",
    re.I,
)


def _classify(m: "re.Match[str]") -> tuple[str | None, float]:
    raw = float(m.group("num").replace(",", ""))
    unit = (m.group("unit") or "").lower()
    if unit in ("%", "percent"):
        return "pct", raw
    if unit in _MAG:
        return "big", raw * _MAG[unit]
    if m.group("dollar"):
        return "price", raw
    return None, raw  # a bare number (year, count, …) — don't grade it


def _collect_allowed(ctx: TopicContext) -> tuple[list[float], list[float], list[float]]:
    """Allowed (prices, percents, big-magnitudes) from the live snapshots.
    Empty lists disable a check, so thin/placeholder contexts never false-flag."""
    prices: list[float] = []
    pcts: list[float] = []
    bigs: list[float] = []
    for snap in ctx.candidates:
        if snap.price:
            prices.append(float(snap.price))
        if snap.change_pct is not None:
            pcts.append(abs(float(snap.change_pct)))
        if snap.volume:
            bigs.append(float(snap.volume))
        if snap.market_cap:
            bigs.append(float(snap.market_cap))
        ohlc = snap.ohlc_30d or []
        if ohlc:
            highs = [c[1] for c in ohlc]
            lows = [c[2] for c in ohlc]
            closes = [c[3] for c in ohlc]
            prices.extend(highs + lows + [closes[0], closes[-1]])
            if closes[0]:
                pcts.append(abs((closes[-1] - closes[0]) / closes[0] * 100))
            hi, lo = max(highs), min(lows)
            if hi:
                pcts.append(abs((closes[-1] - hi) / hi * 100))
            if lo:
                pcts.append(abs((closes[-1] - lo) / lo * 100))
    # Drop zeros/placeholders so a kind with no real data is simply not graded.
    return ([p for p in prices if p > 0],
            [p for p in pcts if p > 0.01],
            [b for b in bigs if b > 0])


def _matches(value: float, allowed: list[float], *, rel: float, absfloor: float = 0.0) -> bool:
    return any(abs(value - a) <= max(absfloor, rel * abs(a)) for a in allowed)


def _check_numbers(script: Script, ctx: TopicContext) -> list[str]:
    """Return the spoken financial figures that match no snapshot value. Only
    grades $/%/magnitude numbers; bare integers (years, counts) are ignored, and
    a kind with no snapshot data is skipped entirely. Conservative by design."""
    prices, pcts, bigs = _collect_allowed(ctx)
    flagged: list[str] = []
    for beat in script.beats:
        for m in _TOKEN_RE.finditer(beat.narration or ""):
            kind, value = _classify(m)
            if kind is None:
                continue
            tok = m.group(0).strip()
            if kind == "pct" and pcts and not _matches(value, pcts, rel=0.15, absfloor=0.5):
                flagged.append(tok)
            elif kind == "price" and prices and not _matches(value, prices, rel=0.08):
                flagged.append(tok)
            elif kind == "big" and bigs and not _matches(value, bigs, rel=0.10):
                flagged.append(tok)
    out: list[str] = []
    for t in flagged:
        if t not in out:
            out.append(t)
    return out[:6]


def _repair_format_constraints(script: Script) -> None:
    """Trim excess tickers so the script honours its format's max.

    The writer occasionally lists comparison stocks in `tickers[]` even for a
    single-stock format (e.g. `deep_dive_one_stock` needs exactly 1). Rather than
    crash the whole run, keep the most narratively-central tickers — ranked by
    how many beats focus on each — up to the format's max. Under-min can't be
    auto-fixed (we won't invent a stock), so that's still left to validation.
    """
    try:
        spec = formats.get_spec(script.format)
    except KeyError:
        return  # unknown format — let _validate_format_constraints report it

    n = len(script.tickers)
    if spec.max_tickers >= 1 and n > spec.max_tickers:
        focus_counts: dict[str, int] = {}
        for b in script.beats:
            tf = (b.ticker_focus or "").upper()
            if tf:
                focus_counts[tf] = focus_counts.get(tf, 0) + 1
        order = {t.ticker.upper(): i for i, t in enumerate(script.tickers)}
        ranked = sorted(
            script.tickers,
            key=lambda t: (-focus_counts.get(t.ticker.upper(), 0), order[t.ticker.upper()]),
        )
        keep = {t.ticker.upper() for t in ranked[: spec.max_tickers]}
        script.tickers = [t for t in script.tickers if t.ticker.upper() in keep]
        log.warning("trimmed tickers %d→%d for format %r (kept most-focused)",
                    n, len(script.tickers), script.format)


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
    _repair_format_constraints(script)
    _validate_format_constraints(script)
    return script
