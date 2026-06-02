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
import time
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
from .data.topic_picker import build_context_for, pick_topic
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

_DISCLAIMER = (
    "Not financial advice. For education and entertainment only. "
    "Do your own research before investing."
)


def _build_description(script, *, credits: list[str] | None = None) -> str:
    """Compose a SEO-friendly YouTube description from a finished script.

    Structure: hook line → 2-3 key takeaways → ticker cashtags → image credits
    → disclaimer → hashtags. Best-effort; never raises (callers fall back to a
    plain narration join if this throws).
    """
    beats = list(getattr(script, "beats", []) or [])
    hook = next((b.narration.strip() for b in beats
                 if getattr(b, "role", None) == "hook" and b.narration.strip()),
                beats[0].narration.strip() if beats else "")

    # 2-3 substantive takeaways from the body (skip hook + any cta).
    takeaways: list[str] = []
    for b in beats:
        if getattr(b, "role", None) in ("hook", "cta"):
            continue
        text = (b.narration or "").strip()
        if text and text != hook:
            takeaways.append(text)
        if len(takeaways) >= 3:
            break

    # Ticker cashtags ($NVDA …), de-duped, order-preserving.
    seen: set[str] = set()
    cashtags: list[str] = []
    for t in getattr(script, "tickers", []) or []:
        sym = (getattr(t, "ticker", "") or "").upper().lstrip("$")
        if sym and sym not in seen:
            seen.add(sym)
            cashtags.append(f"${sym}")

    # Hashtags from the writer's chosen tags; always ensure #Shorts + #stocks.
    raw_tags = [h.lstrip("#") for h in getattr(script, "description_hashtags", []) if h]
    tag_seen: set[str] = set()
    hashtags: list[str] = []
    for tag in raw_tags + ["Shorts", "stocks"]:
        key = tag.lower()
        if tag and key not in tag_seen:
            tag_seen.add(key)
            hashtags.append(f"#{tag}")

    parts: list[str] = []
    if hook:
        parts.append(hook)
    if takeaways:
        parts.append("\n".join(f"• {t}" for t in takeaways))
    if cashtags:
        parts.append("Tickers: " + " ".join(cashtags))
    if credits:
        parts.append("Image credits: " + "; ".join(credits))
    parts.append(_DISCLAIMER)
    if hashtags:
        parts.append(" ".join(hashtags))
    return "\n\n".join(parts)


def _description_tags(script) -> list[str]:
    """Tag list for the YouTube API field; always include Shorts + stocks."""
    seen: set[str] = set()
    tags: list[str] = []
    for h in list(getattr(script, "description_hashtags", []) or []) + ["Shorts", "stocks"]:
        tag = (h or "").lstrip("#")
        key = tag.lower()
        if tag and key not in seen:
            seen.add(key)
            tags.append(tag)
    return tags


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
    try:
        description = _build_description(script)
    except Exception as e:  # never fail a render over description SEO
        log.warning("[%s] description build failed: %s", slug, e)
        description = " ".join(b.narration for b in script.beats)
    tags = _description_tags(script)

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


def emit_next_version(*, slug: str, script) -> Path:
    """Append a NEW version (vN+1) to an existing review item and return its
    short.mp4 path. Used by the comment→regenerate flow so prior versions stay
    on disk until the clip is published or deleted.

    Falls back to a fresh v1 if the item doesn't exist yet.
    """
    existing = _review_store.load(slug)
    if existing is None:
        return emit_review_state(slug=slug, script=script)

    now = datetime.now().isoformat(timespec="seconds")
    captions = [b.caption for b in script.beats if getattr(b, "caption", None)]
    hook = next((b.narration for b in script.beats if b.role == "hook"),
                script.beats[0].narration if script.beats else "")
    try:
        description = _build_description(script)
    except Exception as e:
        log.warning("[%s] description build failed: %s", slug, e)
        description = " ".join(b.narration for b in script.beats)
    tags = _description_tags(script)

    next_v = existing.current_version + 1
    existing.versions.append(Version(
        v=next_v, title=script.title, description=description,
        hook_text=hook, captions=captions, tags=tags, created_at=now,
    ))
    existing.current_version = next_v
    existing.source_title = script.title
    existing.status = "ready"
    _review_store.save(existing)

    short = _review_store.short_path(slug, next_v)
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
    _t0 = time.monotonic()
    today_slug = datetime.now(timezone.utc).strftime("%Y%m%d") + f"_{lang}"
    log.info("=== daily run start: %s ===", today_slug)

    s = get_settings()
    s.ensure_dirs()
    # Ensure the schema exists before the first query — a fresh checkout or a
    # blank cloud volume has the DB file but no tables ("no such table: render").
    from .db import init_db
    init_db()

    # Idempotency: have we already produced a render for today?
    if not force:
        with Session(get_engine(), expire_on_commit=False) as session:
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

    with Session(get_engine(), expire_on_commit=False) as session:
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
    # Auto-extract any forward-looking promises (content debt).
    try:
        from .planner.debt_extract import extract_and_record
        extract_and_record(script, source_slug=slug)
    except Exception as e:
        log.warning("[%s] debt extraction failed: %s", slug, e)
    with Session(get_engine(), expire_on_commit=False) as session:
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
    compose_video(script=script, tts=tts, out_path=mp4_path, started_at=_t0)
    duration_s = float(tts.duration_s)
    with Session(get_engine(), expire_on_commit=False) as session:
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


def render_planned_item(item, *, lang: str = "en") -> RunResult | None:
    """Render one planner-scheduled video end-to-end.

    Seeds a TopicContext from the item's tickers/theme, writes the script in the
    item's format + length band, synthesizes, composes into the review store,
    and marks the item rendered in plan.json (fulfilling any linked commitment).
    Returns None if the topic context can't be built (no resolvable tickers).
    """
    _t0 = time.monotonic()
    from .planner import store as plan_store
    from .planner.debt_extract import extract_and_record

    s = get_settings()
    s.ensure_dirs()
    from .db import init_db
    init_db()

    seed = item.topic_seed
    ctx = build_context_for(seed.tickers, lang=lang, theme=seed.theme)
    if ctx is None:
        log.error("render_planned_item %s: could not build context for %s", item.id, seed.tickers)
        return None

    slug = _slug_from_planned(item, lang)
    set_current_video(slug)
    log.info("[%s] planned render: format=%s tickers=%s", slug, item.format, seed.tickers)

    # Evergreen ideas are prompt-only: let the writer choose the best explainer
    # format + length rather than forcing the planner's ticker-centric default.
    if getattr(item, "source", "") == "idea":
        script = write_script(ctx, format_hint=None, length_band=None)
    else:
        script = write_script(ctx, format_hint=item.format, length_band=tuple(item.length_band))
    log.info("[%s] script written: %d beats, %d words, target=%ss",
             slug, len(script.beats), len(script.narration_text().split()),
             getattr(script, "target_seconds", "?"))

    # Auto-extract any new promises this script makes (content debt).
    try:
        extract_and_record(script, source_slug=slug)
    except Exception as e:  # never fail a render over debt extraction
        log.warning("[%s] debt extraction failed: %s", slug, e)

    with Session(get_engine(), expire_on_commit=False) as session:
        topic_row = TopicRow(
            lang=lang,
            ticker_primary=ctx.candidates[0].ticker,
            ticker_secondary=ctx.candidates[1].ticker if len(ctx.candidates) > 1 else None,
            pivot_reason=seed.theme,
            score=0.0,
            raw_context=ctx.model_dump(),
        )
        session.add(topic_row); session.commit(); session.refresh(topic_row)
        script_row = ScriptRow(topic_id=topic_row.id, lang=lang, payload=script.model_dump())
        session.add(script_row); session.commit(); session.refresh(script_row)

    work_dir = s.output_dir / slug
    tts = synthesize(text=script.narration_text(), lang=lang, out_dir=work_dir)
    mp4_path = emit_review_state(slug=slug, script=script, creator_handle=item.source)
    compose_video(script=script, tts=tts, out_path=mp4_path, started_at=_t0)
    duration_s = float(tts.duration_s)

    with Session(get_engine(), expire_on_commit=False) as session:
        render_row = RenderRow(
            script_id=script_row.id, mp4_path=str(mp4_path),
            duration_s=duration_s, audio_path=str(tts.audio_path),
        )
        session.add(render_row); session.commit(); session.refresh(render_row)

    # Mark the plan item rendered + fulfil its commitment.
    _mark_item_rendered(plan_store, item_id=item.id, slug=slug,
                        commitment_id=item.commitment_id)

    set_current_video(None)
    log.info("[%s] planned render done.", slug)
    return RunResult(slug=slug, topic_id=topic_row.id, script_id=script_row.id,
                     render_id=render_row.id, mp4_path=mp4_path, duration_s=duration_s)


def regenerate_clip(slug: str, *, lang: str = "en", guidance: str = "") -> RunResult | None:
    """Re-render an existing clip as a new version, addressing reviewer feedback.

    Recovers the original topic context + format + length from the DB (so the
    rewrite stays on the same topic/format), re-runs the script writer and the
    visual director with `guidance` (the reviewer's comments), and appends the
    result as vN+1 in the review store. Returns None if the topic context for
    the slug can't be recovered.
    """
    _t0 = time.monotonic()
    from .script.schemas import Script as ScriptModel
    from .script.schemas import TopicContext

    s = get_settings()
    s.ensure_dirs()
    from .db import init_db
    init_db()

    # Recover the source topic + prior script from the most recent render row.
    with Session(get_engine(), expire_on_commit=False) as session:
        render_row = session.exec(
            select(RenderRow).where(RenderRow.mp4_path.contains(slug))
            .order_by(RenderRow.id.desc())
        ).first()
        if render_row is None:
            log.error("regenerate_clip %s: no render row found", slug)
            return None
        script_row = session.get(ScriptRow, render_row.script_id)
        topic_row = session.get(TopicRow, script_row.topic_id) if script_row else None

    if topic_row is None or not topic_row.raw_context:
        log.error("regenerate_clip %s: missing topic context", slug)
        return None

    try:
        ctx = TopicContext.model_validate(topic_row.raw_context)
    except Exception as e:
        log.error("regenerate_clip %s: bad topic context: %s", slug, e)
        return None

    prior = ScriptModel.model_validate(script_row.payload) if script_row else None
    fmt = prior.format if prior else None
    target = getattr(prior, "target_seconds", None) if prior else None
    band = (int(target), int(target)) if target else None

    set_current_video(slug)
    log.info("[%s] regenerating (format=%s, guidance=%.60s)", slug, fmt, guidance)

    script = write_script(ctx, format_hint=fmt, length_band=band, guidance=guidance)

    try:
        from .planner.debt_extract import extract_and_record
        extract_and_record(script, source_slug=slug)
    except Exception as e:
        log.warning("[%s] debt extraction failed: %s", slug, e)

    with Session(get_engine(), expire_on_commit=False) as session:
        new_script_row = ScriptRow(topic_id=topic_row.id, lang=lang, payload=script.model_dump())
        session.add(new_script_row); session.commit(); session.refresh(new_script_row)

    work_dir = s.output_dir / slug
    tts = synthesize(text=script.narration_text(), lang=lang, out_dir=work_dir)
    mp4_path = emit_next_version(slug=slug, script=script)
    compose_video(script=script, tts=tts, out_path=mp4_path, guidance=guidance, started_at=_t0)
    duration_s = float(tts.duration_s)

    with Session(get_engine(), expire_on_commit=False) as session:
        render_row = RenderRow(
            script_id=new_script_row.id, mp4_path=str(mp4_path),
            duration_s=duration_s, audio_path=str(tts.audio_path),
        )
        session.add(render_row); session.commit(); session.refresh(render_row)

    set_current_video(None)
    log.info("[%s] regeneration done.", slug)
    return RunResult(slug=slug, topic_id=topic_row.id, script_id=new_script_row.id,
                     render_id=render_row.id, mp4_path=mp4_path, duration_s=duration_s)


def _mark_item_rendered(plan_store, *, item_id: str, slug: str,
                        commitment_id: str | None) -> None:
    plan = plan_store.load_plan()
    for it in plan.items:
        if it.id == item_id:
            it.status = "rendered"
            it.slug = slug
    plan_store.save_plan(plan)

    if commitment_id:
        debt = plan_store.load_debt()
        for c in debt.commitments:
            if c.id == commitment_id:
                c.status = "fulfilled"
                c.fulfilled_by = slug
        plan_store.save_debt(debt)


def _slug_from_planned(item, lang: str) -> str:
    primary = (item.topic_seed.tickers[0].lower() if item.topic_seed.tickers else "mkt")
    raw = f"{item.scheduled_for.strftime('%Y%m%d')}_{item.format}_{primary}_{item.id[:6]}_{lang}"
    return re.sub(r"[^a-z0-9_]+", "", raw.lower())


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
