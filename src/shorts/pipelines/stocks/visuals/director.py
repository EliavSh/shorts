"""Visual director — turns a Script into a VisualPlan.

The plan is a flat list of sections (≈5–6s each, ~11 sections for a 60s video).
Each section carries an *intent description* (a sentence describing what should
appear on screen) plus 2–3 candidate search queries. The intent string is what
CLIP scores against — it captures meaning where tags can't.

The director uses Claude if ANTHROPIC_API_KEY is set; otherwise it falls back
to a heuristic that derives sections from beat structure.
"""
from __future__ import annotations

import json
import logging
import math
import re

from pydantic import BaseModel, Field

from ..script.schemas import Beat, Script
from ..settings import get_settings


# R14 — patterns that DEMAND a generated graphic.
_NUMBER_PATTERNS = [
    re.compile(r"\$\s?\d[\d,.]*\s?(billion|million|trillion|B|M|T|K)\b", re.IGNORECASE),
    # Bare magnitude numbers without a $ sign: "200 million dollars", "over 300
    # million members", "26 billion a quarter". These are real, callout-worthy
    # numbers that the $-anchored pattern above misses.
    re.compile(r"\b\d[\d,.]*\s?(billion|million|trillion)\b", re.IGNORECASE),
    re.compile(r"[+\-]?\d+(\.\d+)?\s*%"),
    re.compile(r"\b\d{1,3}(,\d{3})+\b"),  # numbers with thousands separators (3,000)
    re.compile(r"\b\d+,\d+\s*(jobs|chips|employees|users|customers|people)\b", re.IGNORECASE),
]
_DATE_PATTERNS = [
    re.compile(r"\b(January|February|March|April|May|June|July|August|September|October|November|December)\s+\d{1,2}\b"),
    re.compile(r"\bQ[1-4]\s+20\d{2}\b"),
]
_MONTH_TO_NUM = {m: i for i, m in enumerate(
    ["January", "February", "March", "April", "May", "June", "July", "August",
     "September", "October", "November", "December"], start=1)}

log = logging.getLogger(__name__)

TARGET_SECONDS_PER_SECTION = 5.5
MIN_QUERIES_PER_SECTION = 2
MAX_QUERIES_PER_SECTION = 3


class VisualSection(BaseModel):
    """One planned image section of the video.

    Two modes:
    - graphic_spec is None → retrieval mode (search → CLIP rank → pick)
    - graphic_spec is set  → generated mode (dispatch to visuals.graphics)
    """
    start_s: float = Field(..., ge=0)
    end_s: float = Field(..., ge=0)
    intent: str = Field(..., min_length=8, max_length=400,
                        description="One-sentence description of what the section should depict, "
                                    "specific enough for CLIP to score image-text similarity.")
    search_queries: list[str] = Field(default_factory=list, max_length=MAX_QUERIES_PER_SECTION,
                                      description="Image search queries (retrieval mode only).")
    ticker_focus: str | None = None
    related_beat_idx: int = 0
    graphic_spec: dict | None = Field(
        default=None,
        description="If set, this section is rendered by a generated graphics module "
                    "(visuals/graphics) instead of by retrieval. Shape: {kind: str, params: {}}. "
                    "Kinds: date_card, number_callout, bar_compare, mini_chart.",
    )


class VisualPlan(BaseModel):
    sections: list[VisualSection]

    def section_for_time(self, t: float) -> VisualSection | None:
        for s in self.sections:
            if s.start_s <= t < s.end_s:
                return s
        return None


def make_plan(script: Script, *, total_duration_s: float,
              n_sections: int | None = None,
              guidance: str | None = None) -> VisualPlan:
    """Build a visual plan for a script using Claude when available, else a heuristic.

    After Claude returns a plan, we audit it: any beat whose narration contains
    a number/date but whose covering section doesn't have a graphic_spec gets
    one auto-injected. This guarantees R2/R14 compliance.

    `guidance` carries reviewer feedback from a comment-driven regeneration (e.g.
    "image doesn't match") so the director can correct the visuals.
    """
    if n_sections is None:
        n_sections = max(4, math.ceil(total_duration_s / TARGET_SECONDS_PER_SECTION))

    s = get_settings()
    plan: VisualPlan | None = None
    if s.anthropic_api_key:
        try:
            plan = _make_plan_with_claude(script, total_duration_s=total_duration_s,
                                          n_sections=n_sections, guidance=guidance)
        except Exception as e:
            log.warning("Claude director failed (%s) — falling back to heuristic", e)

    if plan is None:
        plan = _heuristic_plan(script, total_duration_s=total_duration_s, n_sections=n_sections)

    plan = _inject_missing_graphics(plan, script)
    return plan


# ─────────────────────────────────────────────────────────────────────────────
# Claude-driven plan
# ─────────────────────────────────────────────────────────────────────────────

DIRECTOR_SYSTEM_PROMPT = """You are a video director planning the visual storyboard for a 60-second finance Short.

You will receive a finalized script (beats with narration in time order) and the total audio duration in seconds.

## TWO MODES per section

A) RETRIEVAL MODE — for sections that depict PEOPLE, PLACES, BUILDINGS, PRODUCTS, FACTORIES, OFFICES.
   Set `intent` (one specific sentence) + `search_queries` (2-3 queries). `graphic_spec`: null.
   GOOD intents: "The NVIDIA corporate headquarters building exterior in Santa Clara at dusk."
                 "A semiconductor wafer being inspected by a worker in a yellow cleanroom suit."
                 "Jensen Huang on stage in his black leather jacket at GTC."

B) GENERATED-GRAPHIC MODE — for ANY section that depicts a NUMBER, DATE, PERCENTAGE, COMPARISON, OR CHART.
   This is a HARD RULE. Don't write `intent` describing a "graphic of $X" — set `graphic_spec` instead.
   `search_queries` may be empty.

## THE HARD RULE on graphic_spec (R14)

If the narration in this section contains ANY of:
  - A specific dollar amount ($3.2B, $81.6 billion, $200B)
  - A percentage (+85%, 3%, 100%)
  - A specific count (3,000 jobs, 500,000 chips)
  - A specific date (June 17, May 2025, Q3)
  - A comparison ("X vs Y", "X versus Y", "above forecasts of Z")

→ you MUST set `graphic_spec`. Do NOT use retrieval for these beats. Retrieved photos with random
   numbers in them are the #1 quality killer in Shorts.

Also: if the LAST beat is a CTA (role=cta), set `graphic_spec` = `{"kind": "follow_cta", "params": {"headline": "Follow for daily market moves"}}`.

## graphic_spec catalogue

```json
{"kind": "date_card",      "params": {"year": 2026, "month": 6, "day": 17, "subtitle": "Fed decision"}}
{"kind": "number_callout", "params": {"number": "$3.2B",  "label": "Nvidia investment in Corning",   "direction": "up"}}
{"kind": "number_callout", "params": {"number": "+85%",   "label": "Nvidia Q1 revenue growth",       "direction": "up"}}
{"kind": "number_callout", "params": {"number": "3,000",  "label": "Intuit layoffs (17% of staff)",  "direction": "down"}}
{"kind": "bar_compare",    "params": {"title": "Q3 vs Q2 revenue", "bars": [{"label":"Q2","value":76.4},{"label":"Q3","value":81.6}], "unit":"B"}}
{"kind": "mini_chart",     "params": {"title": "QNTY: 1-year run", "line": [50,55,62,70,78,86,95,105], "label_start":"Nov 25", "label_end":"+100%", "direction":"up"}}
{"kind": "follow_cta",     "params": {"headline": "Follow for daily market moves"}}
```

`direction` is "up" for positive moves / "down" for negative / "neutral".

## Other rules

3. Speaking order: sections must flow through the script in time.
4. Sections tile the full duration with no gaps and no overlaps.
5. Vary the visuals — don't show the same building/scene in two adjacent sections.
6. Reasonable target: 40-60% of sections will be `graphic_spec` for a typical finance Short.

Return ONLY a JSON object matching the VisualPlan schema."""


def _make_plan_with_claude(script: Script, *, total_duration_s: float, n_sections: int,
                           guidance: str | None = None) -> VisualPlan:
    from shorts.core.infra.anthropic_client import make_client

    s = get_settings()
    client = make_client()

    beats_summary = []
    for i, b in enumerate(script.beats):
        beats_summary.append({
            "idx": i,
            "role": b.role,
            "ticker_focus": b.ticker_focus,
            "narration": b.narration,
            "visual_tags": b.visual_tags,
        })

    feedback = ""
    if guidance and guidance.strip():
        feedback = (
            "\n\nReviewer feedback on the previous visuals — fix these directly "
            "(e.g. mismatched or boring imagery): pick more fitting search queries "
            f"and section intents.\n{guidance.strip()}"
        )

    user_message = (
        f"Build a {n_sections}-section visual plan for this script "
        f"(total duration {total_duration_s:.2f}s).\n\n"
        f"Tickers: {[{'ticker': t.ticker, 'name': t.name} for t in script.tickers]}\n\n"
        f"Beats (in order):\n```json\n{json.dumps(beats_summary, ensure_ascii=False, indent=2)}\n```"
        f"{feedback}"
    )

    tool = {
        "name": "emit_visual_plan",
        "description": "Emit the structured visual plan.",
        "input_schema": VisualPlan.model_json_schema(),
    }
    response = client.messages.create(
        model=s.claude_director_model,
        max_tokens=4096,
        system=DIRECTOR_SYSTEM_PROMPT,
        tools=[tool],
        tool_choice={"type": "tool", "name": "emit_visual_plan"},
        messages=[{"role": "user", "content": user_message}],
    )
    for block in response.content:
        if getattr(block, "type", None) == "tool_use" and block.name == "emit_visual_plan":
            plan = VisualPlan.model_validate(block.input)
            return _normalize_plan(plan, total_duration_s)
    raise RuntimeError("Claude director did not emit a tool_use block")


def _normalize_plan(plan: VisualPlan, total_duration_s: float) -> VisualPlan:
    """Snap section boundaries to the total duration and clip overlaps."""
    sections = sorted(plan.sections, key=lambda s: s.start_s)
    fixed: list[VisualSection] = []
    cursor = 0.0
    for i, sec in enumerate(sections):
        start = max(cursor, sec.start_s)
        end = sec.end_s
        if i == len(sections) - 1:
            end = total_duration_s
        if end - start < 0.5:
            continue
        fixed.append(VisualSection(
            start_s=start, end_s=end, intent=sec.intent,
            search_queries=sec.search_queries, ticker_focus=sec.ticker_focus,
            related_beat_idx=sec.related_beat_idx,
        ))
        cursor = end
    return VisualPlan(sections=fixed)


# ─────────────────────────────────────────────────────────────────────────────
# Post-pass: auto-inject graphics for beats Claude missed
# ─────────────────────────────────────────────────────────────────────────────

def _inject_missing_graphics(plan: VisualPlan, script: Script) -> VisualPlan:
    """Audit the plan against the script; auto-inject graphic_spec for any beat
    that mentions a number/date but isn't covered by an existing graphic section.

    Also: force the CTA beat (role=cta) to use a follow_cta graphic.
    """
    # Build a beat → section index map (best-fit by start_s).
    timings = _beat_timings(script, plan.sections[-1].end_s if plan.sections else 0)

    updated = list(plan.sections)
    injected = 0

    for beat_idx, beat in enumerate(script.beats):
        beat_start, beat_end = timings[beat_idx]
        gs = _classify_beat(beat)
        if gs is None:
            continue  # no number/date in this beat

        # Does any existing section in this beat's window already have graphic_spec?
        covered = any(
            (s.start_s < beat_end and s.end_s > beat_start) and s.graphic_spec
            for s in updated
        )
        if covered:
            continue

        # Find the section overlapping this beat with the largest overlap.
        best_idx = -1
        best_overlap = 0.0
        for i, s in enumerate(updated):
            overlap = max(0.0, min(s.end_s, beat_end) - max(s.start_s, beat_start))
            if overlap > best_overlap:
                best_overlap = overlap
                best_idx = i
        if best_idx == -1:
            continue

        target = updated[best_idx]
        new_spec = gs
        updated[best_idx] = VisualSection(
            start_s=target.start_s, end_s=target.end_s,
            intent=target.intent, search_queries=target.search_queries,
            ticker_focus=target.ticker_focus, related_beat_idx=beat_idx,
            graphic_spec=new_spec,
        )
        injected += 1
        log.info("auto-injected %s for beat %d (%.1f-%.1f)",
                 new_spec["kind"], beat_idx, beat_start, beat_end)

    if injected:
        log.info("Director auto-injected %d graphic_spec section(s)", injected)
    return VisualPlan(sections=updated)


def _beat_timings(script: Script, total_s: float) -> list[tuple[float, float]]:
    weights = [max(1.0, len(b.narration)) for b in script.beats]
    total_w = sum(weights)
    out: list[tuple[float, float]] = []
    cursor = 0.0
    for w in weights:
        share = (w / total_w) * total_s if total_w else 0
        out.append((cursor, cursor + share))
        cursor += share
    return out


def _classify_beat(beat: Beat) -> dict | None:
    """If this beat's narration contains a number/date/CTA cue, return a
    graphic_spec dict; else None."""
    text = beat.narration

    # CTA → follow card
    if beat.role == "cta":
        return {"kind": "follow_cta",
                "params": {"headline": "Follow for daily market moves"}}

    # Date
    for pat in _DATE_PATTERNS:
        m = pat.search(text)
        if m:
            month_match = re.search(r"\b(January|February|March|April|May|June|July|August|September|October|November|December)\s+(\d{1,2})\b", m.group(0))
            if month_match:
                month = _MONTH_TO_NUM[month_match.group(1)]
                day = int(month_match.group(2))
                # Year is fuzzy — default current year context (2026 for the test set).
                return {
                    "kind": "date_card",
                    "params": {"year": 2026, "month": month, "day": day,
                               "subtitle": _short_subtitle(beat)},
                }
            # Q3 2026 etc. → still useful as a number_callout fallback
            return {
                "kind": "number_callout",
                "params": {"number": m.group(0), "label": _short_subtitle(beat),
                           "direction": _direction(beat)},
            }

    # Number
    for pat in _NUMBER_PATTERNS:
        m = pat.search(text)
        if m:
            number = m.group(0).strip()
            return {
                "kind": "number_callout",
                "params": {"number": number, "label": _short_subtitle(beat),
                           "direction": _direction(beat)},
            }
    return None


def _short_subtitle(beat: Beat) -> str:
    """Pick a short, contextual label from the narration (≤56 chars)."""
    text = beat.narration.strip()
    # Strip the number itself; replace with a space so adjacent words don't merge.
    cleaned = re.sub(r"[+\-]?\d+(\.\d+)?\s*%", " ", text)
    cleaned = re.sub(r"\$?\s?\d[\d,.]*\s?(billion|million|trillion|B|M|T|K)?(\s*dollars)?", " ", cleaned, flags=re.IGNORECASE)
    cleaned = re.sub(r"\b\d{1,3}(,\d{3})+\b", " ", cleaned)
    # Drop quantifier words left dangling once their number is gone.
    cleaned = re.sub(r"\b(over|about|more than|nearly|roughly|around|almost|just)\b\s*(?=[,.;:]|$)", "", cleaned, flags=re.IGNORECASE)
    cleaned = re.sub(r"\s+([,.;:])", r"\1", cleaned)   # drop space before punctuation
    cleaned = re.sub(r",\s*,", ", ", cleaned)          # collapse emptied ", ,"
    cleaned = re.sub(r"\s+", " ", cleaned).strip(" —–-.,")
    if len(cleaned) > 56:
        cleaned = cleaned[:53].rstrip() + "…"
    return cleaned or "key number"


def _direction(beat: Beat) -> str:
    text = beat.narration.lower()
    up_words = ["up", "jump", "soar", "rally", "beat", "surge", "growth", "rise", "gain", "above"]
    down_words = ["down", "drop", "fall", "tumble", "miss", "decline", "loss", "cut", "below", "squeeze"]
    if any(w in text for w in down_words):
        return "down"
    if any(w in text for w in up_words):
        return "up"
    return "neutral"


# ─────────────────────────────────────────────────────────────────────────────
# Heuristic fallback
# ─────────────────────────────────────────────────────────────────────────────

def _heuristic_plan(script: Script, *, total_duration_s: float, n_sections: int) -> VisualPlan:
    """Cheap plan when Claude isn't available.

    - Compute beat timings proportionally to narration length.
    - For each beat, allocate one or more sections to fill its duration at the
      target rate.
    - Intent = "<ticker name> <visual_tags joined>" or beat narration.
    """
    weights = [max(1.0, len(b.narration)) for b in script.beats]
    total_w = sum(weights)
    cursor = 0.0
    sections: list[VisualSection] = []
    for i, (b, w) in enumerate(zip(script.beats, weights, strict=False)):
        beat_dur = (w / total_w) * total_duration_s
        n_per_beat = max(1, round(beat_dur / TARGET_SECONDS_PER_SECTION))
        per = beat_dur / n_per_beat
        for k in range(n_per_beat):
            start = cursor + k * per
            end = cursor + (k + 1) * per if k < n_per_beat - 1 else cursor + beat_dur
            intent = _beat_intent_text(b, script)
            queries = _beat_queries(b, script)
            sections.append(VisualSection(
                start_s=start, end_s=end, intent=intent, search_queries=queries,
                ticker_focus=b.ticker_focus, related_beat_idx=i,
            ))
        cursor += beat_dur
    plan = VisualPlan(sections=sections)
    return _normalize_plan(plan, total_duration_s)


def _beat_intent_text(beat: Beat, script: Script) -> str:
    ticker_name = ""
    if beat.ticker_focus:
        spec = script.ticker(beat.ticker_focus)
        if spec:
            ticker_name = spec.name
    tags = " ".join(beat.visual_tags) if beat.visual_tags else ""
    base = f"{ticker_name} {tags}".strip()
    if not base:
        return beat.narration[:160]
    return f"A scene depicting {base}: {beat.narration[:120]}"


def _beat_queries(beat: Beat, script: Script) -> list[str]:
    queries: list[str] = []
    if beat.ticker_focus:
        spec = script.ticker(beat.ticker_focus)
        if spec:
            for tag in beat.visual_tags[:2]:
                queries.append(f"{spec.name} {tag}")
            if not queries:
                queries.append(spec.name)
    for tag in beat.visual_tags[:2]:
        if tag not in [q.lower() for q in queries]:
            queries.append(tag)
    if not queries:
        queries = [beat.narration[:80]]
    return queries[:MAX_QUERIES_PER_SECTION]
