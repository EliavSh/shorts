"""Content-debt extraction — scan a finished script's narration for
forward-looking promises ("we'll cover Nvidia after earnings", "part 2 next
week", "stay tuned") and record them as Commitments.

Uses the cheap Anthropic model (mirrors core/reviews/distill.py). Best-effort:
any failure leaves debt.json untouched and never breaks a render.
"""
from __future__ import annotations

import json
import logging
import time

from ..settings import get_settings
from . import store
from .models import Commitment

log = logging.getLogger(__name__)

_CHEAP_MODEL = "claude-haiku-4-5-20251001"

_SYSTEM = """You read a finance YouTube Short script and extract any FORWARD-LOOKING \
PROMISES the narration makes to the audience — content the channel implicitly \
commits to making later.

Examples of promises:
- "We'll break down Nvidia after it reports earnings."
- "More on the energy sector next week."
- "Part 2 is coming — stay tuned."
- "We'll revisit this when the Fed decides."

NOT promises (ignore these):
- Statements about what a company will do.
- General market predictions.
- The standard "follow for more" CTA with no specific topic.

Output strict JSON: {"commitments": [{"text": "...", "tickers": ["NVDA"], "trigger": "after earnings"}]}
- `text`: the promise, rephrased as a crisp future task (≤ 15 words).
- `tickers`: array of ticker symbols the promise is about (may be empty).
- `trigger`: when it should happen — "after earnings", "next week", a date, or null.
Return {"commitments": []} when the script makes no real promise. No markdown, just JSON."""


def _strip_fence(text: str) -> str:
    text = text.strip()
    if text.startswith("```"):
        lines = text.splitlines()[1:]
        if lines and lines[-1].strip() == "```":
            lines = lines[:-1]
        text = "\n".join(lines).strip()
    return text


def extract_commitments(script, *, source_slug: str = "") -> list[Commitment]:
    """Call the cheap model to pull promises out of `script`. Returns [] on any
    failure or when no API key is configured."""
    s = get_settings()
    if not s.anthropic_api_key:
        log.debug("no anthropic key — skipping debt extraction")
        return []

    narration = script.narration_text().strip()
    if not narration:
        return []

    import anthropic

    client = anthropic.Anthropic(api_key=s.anthropic_api_key)
    user = (
        f"Title: {script.title}\n"
        f"Tickers in video: {[t.ticker for t in script.tickers]}\n\n"
        f"Narration:\n{narration}\n\nExtract commitments."
    )
    resp = None
    for attempt in range(4):
        try:
            resp = client.messages.create(
                model=_CHEAP_MODEL, max_tokens=400, system=_SYSTEM,
                messages=[{"role": "user", "content": user}],
            )
            break
        except anthropic.APIStatusError as e:
            if e.status_code in (429, 529):
                time.sleep(min(2 ** attempt, 20))
                continue
            log.warning("debt extraction API error: %s", e)
            return []
        except Exception as e:
            log.warning("debt extraction failed: %s", e)
            return []
    if resp is None:
        return []

    text = _strip_fence("".join(b.text for b in resp.content if b.type == "text"))
    try:
        data = json.loads(text)
    except json.JSONDecodeError:
        return []

    out: list[Commitment] = []
    for row in data.get("commitments", []):
        promise = str(row.get("text", "")).strip()
        if not promise:
            continue
        tickers = [str(t).upper() for t in (row.get("tickers") or []) if str(t).strip()]
        trigger = row.get("trigger")
        out.append(Commitment(
            text=promise, tickers=tickers,
            trigger=str(trigger) if trigger else None,
            source_slug=source_slug,
        ))
    return out


def extract_and_record(script, *, source_slug: str = "") -> list[Commitment]:
    """Extract commitments and append the genuinely-new ones to debt.json.

    De-dupes against existing open/scheduled commitments by (text, tickers) so
    re-rendering the same script doesn't pile up duplicates.
    """
    new = extract_commitments(script, source_slug=source_slug)
    if not new:
        return []

    debt = store.load_debt()
    seen = {(c.text.lower(), tuple(sorted(c.tickers))) for c in debt.commitments}
    added: list[Commitment] = []
    for c in new:
        key = (c.text.lower(), tuple(sorted(c.tickers)))
        if key in seen:
            continue
        seen.add(key)
        debt.commitments.append(c)
        added.append(c)
    if added:
        store.save_debt(debt)
        log.info("Recorded %d new commitment(s) from %s", len(added), source_slug)
    return added
