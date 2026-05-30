"""Daily orchestrator — the missing glue between topic → script → tts → compose.

Per design decision (2026-05-21): runs auto-render but STOPS before upload.
The dashboard's "Upload to staging" button is the human approval gate.

Steps (each persists a DB row so the run is resumable):
  1. TOPIC      : pick today's topic (yfinance + Finnhub headlines + pivot links)
  2. SCRIPT     : Claude writes the script (Opus 4.7) → Script row
  3. RENDER     : edge-tts synth + visual director + compose → Render row + mp4
  4. (HOLD)     : pipeline exits. User reviews in dashboard and clicks "Upload."

Idempotency: a `pipeline_runs` row keyed on (date, lang) lets us re-attempt
without redoing already-completed steps.
"""
from __future__ import annotations

import logging
import re
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

from sqlmodel import Session, select

from shorts.core.infra.alerts import notify
from shorts.core.reviews import ReviewItem, ReviewStore, Version
from .compose import compose_video
from .db import Render as RenderRow
from .db import Script as ScriptRow
from .db import Topic as TopicRow
from .db import get_engine
from .data.topic_picker import pick_topic
from .script.writer import write_script
from .settings import get_settings
from shorts.core.usage import set_current_video
from .voice.tts import synthesize

log = logging.getLogger(__name__)


@dataclass
class RunResult:
    slug: str
    topic_id: int
    script_id: int
    render_id: int
    mp4_path: Path
    duration_s: float


_review_store = ReviewStore("stocks")


def emit_review_state(
    *,
    slug: str,
    script,
    source_url: str = "",
    creator_handle: str = "market",
) -> Path:
    """Write/refresh the ReviewStore state.json for a render so the dashboard
    can list it. Returns the v1 short.mp4 path the composer should target.

    This is the bridge between the stocks render (which thinks in mp4 files +
    DB rows) and the shared review UI (which lists items from state.json).
    Composing directly into v1/short.mp4 means there's no copy step.
    """
    now = datetime.now().isoformat(timespec="seconds")
    captions = [b.caption for b in script.beats if getattr(b, "caption", None)]
    hook = next((b.narration for b in script.beats if b.role == "hook"),
                script.beats[0].narration if script.beats else "")
    description = " ".join(b.narration for b in script.beats)
    tags = [h.lstrip("#") for h in getattr(script, "description_hashtags", [])]

    # A plain (re-)render always writes v1 and overwrites it in place. Version
    # accumulation is reserved for the comment→regen flow, not bare re-renders,
    # so re-running the same slug stays idempotent rather than piling up vN.
    version = Version(
        v=1, title=script.title, description=description,
        hook_text=hook, captions=captions, tags=tags, created_at=now,
    )
    existing = _review_store.load(slug)
    item = ReviewItem(
        run_id=slug,
        source_url=source_url,
        creator_handle=creator_handle,
        creator_channel_id="",
        source_title=script.title,
        status="ready",
        current_version=1,
        versions=[version],
        comments=existing.comments if existing else [],
        created_at=existing.created_at if existing else now,
        updated_at=now,
    )
    _review_store.save(item)

    short = _review_store.short_path(slug, 1)
    short.parent.mkdir(parents=True, exist_ok=True)
    return short


def run_daily(*, lang: str = "en", force: bool = False) -> RunResult | None:
    """End-to-end render for today's topic. Stops before upload."""
    try:
        return _run_daily_inner(lang=lang, force=force)
    except Exception as e:
        notify(f"Daily render failed: {type(e).__name__}: {e}",
               level="error", title="stocks-reels daily run")
        raise


def _run_daily_inner(*, lang: str = "en", force: bool = False) -> RunResult | None:
    today_slug = datetime.now(timezone.utc).strftime("%Y%m%d") + f"_{lang}"
    log.info("=== daily run start: %s ===", today_slug)

    s = get_settings()
    s.ensure_dirs()

    # Idempotency: have we already produced a render for today?
    if not force:
        with Session(get_engine()) as session:
            existing = session.exec(
                select(RenderRow).where(RenderRow.mp4_path.contains(today_slug))
            ).first()
        if existing:
            log.info("Already rendered: %s — skip (use --force to redo).", existing.mp4_path)
            return None

    # 1. Topic
    ctx = pick_topic(lang=lang)
    if ctx is None:
        log.error("Topic picker returned None — no movers? Aborting.")
        return None

    slug = _slug_from_topic(ctx, today_slug)
    set_current_video(slug)  # attribute downstream costs

    with Session(get_engine()) as session:
        primary = ctx.candidates[0]
        secondary = ctx.candidates[1] if len(ctx.candidates) > 1 else None
        topic_row = TopicRow(
            lang=lang,
            ticker_primary=primary.ticker,
            ticker_secondary=secondary.ticker if secondary else None,
            pivot_reason=(ctx.suggested_links[0].reason if ctx.suggested_links else None),
            score=primary.change_pct,  # crude — refine if we add a true score
            raw_context=ctx.model_dump(),
        )
        session.add(topic_row); session.commit(); session.refresh(topic_row)
    log.info("[%s] topic = %s (primary %s)", slug, topic_row.id, primary.ticker)

    # 2. Script
    script = write_script(ctx)
    log.info("[%s] script written: %d beats, %d words, format=%s",
             slug, len(script.beats), len(script.narration_text().split()), script.format)
    with Session(get_engine()) as session:
        script_row = ScriptRow(
            topic_id=topic_row.id,
            lang=lang,
            payload=script.model_dump(),
        )
        session.add(script_row); session.commit(); session.refresh(script_row)

    # 3. Render: TTS + composer
    work_dir = s.output_dir / slug
    log.info("[%s] synthesizing voice ...", slug)
    tts = synthesize(text=script.narration_text(), lang=lang, out_dir=work_dir)
    log.info("[%s] TTS done: %.2fs audio, %d word timings", slug, tts.duration_s, len(tts.words))

    # Bridge to the review UI: emit state.json and compose straight into the
    # v1/short.mp4 path the dashboard serves.
    mp4_path = emit_review_state(
        slug=slug, script=script, source_url="",
        creator_handle=primary.ticker,
    )
    log.info("[%s] composing video ...", slug)
    compose_video(script=script, tts=tts, out_path=mp4_path)
    duration_s = float(tts.duration_s)
    with Session(get_engine()) as session:
        render_row = RenderRow(
            script_id=script_row.id,
            mp4_path=str(mp4_path),
            duration_s=duration_s,
            audio_path=str(tts.audio_path),
        )
        session.add(render_row); session.commit(); session.refresh(render_row)

    log.info("[%s] done. Review in dashboard at /video/%s", slug, slug)
    set_current_video(None)
    return RunResult(
        slug=slug, topic_id=topic_row.id, script_id=script_row.id,
        render_id=render_row.id, mp4_path=mp4_path, duration_s=duration_s,
    )


def _slug_from_topic(ctx, today_slug: str) -> str:
    """Generate a deterministic, safe slug for today's render."""
    primary = ctx.candidates[0].ticker.lower()
    secondary = (ctx.candidates[1].ticker.lower()
                 if len(ctx.candidates) > 1 and ctx.suggested_links else "")
    parts = [today_slug, primary]
    if secondary:
        parts.append(secondary)
    raw = "_".join(parts)
    return re.sub(r"[^a-z0-9_]+", "", raw)
