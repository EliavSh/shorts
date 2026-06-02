"""stocks pipeline dashboard routes — mounted at /stocks.

Lists items from the shared ReviewStore, lets the reviewer generate a new
clip from a topic slug, leave global notes, and publish to the stocks YT
channel. Comments-per-clip will land once stocks emits state.json on render.
"""
from __future__ import annotations

import os
import subprocess
import sys
from datetime import datetime
from pathlib import Path
from typing import Any

from fastapi import APIRouter, BackgroundTasks, Form, HTTPException, Request
from fastapi.responses import FileResponse, HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates

from shorts.config import REPO_ROOT
from shorts.core import jobs as job_mod
from shorts.core.reviews import ReviewStore, latest_version
from shorts.core.reviews import distill as distill_mod

PIPELINE = "stocks"
TEMPLATES_DIR = Path(__file__).resolve().parent / "templates"

router = APIRouter(prefix="/stocks", tags=["stocks"])
templates = Jinja2Templates(directory=str(TEMPLATES_DIR))
_store = ReviewStore(PIPELINE)

# Job kinds that produce a clip (vs. publish). The dashboard shows a live
# progress placeholder for these while they run.
RENDER_KINDS = {"daily-run", "render-fixture", "autopilot-tick", "regen", "render-idea"}

# Ordered (log-substring → friendly label) pairs. The job watcher streams the
# render subprocess's stdout and advances the stage as these markers appear, so
# the dashboard can show "Researching the topic…" etc. Order = chronological.
STAGE_PATTERNS: list[tuple[str, str]] = [
    ("daily run start", "Researching the topic…"),
    ("planned render:", "Researching the topic…"),
    ("topic =", "Researching the topic…"),
    ("script written", "Writing the script…"),
    ("synthesizing voice", "Recording the voiceover…"),
    ("Visual plan:", "Planning the visuals…"),
    ("visual shots", "Finding images…"),
    ("Writing ", "Rendering the final cut…"),
    ("done.", "Wrapping up…"),
]
PUBLISH_STAGES: list[tuple[str, str]] = [("Uploading", "Uploading to YouTube…")]


def _trigger_run() -> None:
    job_mod.start(
        PIPELINE, "daily-run", "(daily orchestrator)",
        [sys.executable, "-m", "shorts.cli", "stocks", "run"],
        cwd=str(REPO_ROOT), stage_patterns=STAGE_PATTERNS,
    )


def _trigger_render_fixture(slug: str) -> None:
    job_mod.start(
        PIPELINE, "render-fixture", slug,
        [sys.executable, "-m", "shorts.cli", "stocks", "render-fixture", slug],
        cwd=str(REPO_ROOT), stage_patterns=STAGE_PATTERNS,
    )


def _trigger_publish(slug: str) -> None:
    job_mod.start(
        PIPELINE, "publish", slug,
        [sys.executable, "-m", "shorts.cli", "upload", slug, "--pipeline", "stocks"],
        cwd=str(REPO_ROOT), stage_patterns=PUBLISH_STAGES,
    )


def _trigger_autopilot_tick(*, replan: bool = False) -> None:
    cmd = [sys.executable, "-m", "shorts.cli", "stocks", "autopilot", "tick"]
    if replan:
        cmd.append("--replan")
    label = "(replan + render one fresh clip)" if replan else "(render next planned item)"
    job_mod.start(PIPELINE, "autopilot-tick", label, cmd, cwd=str(REPO_ROOT),
                  stage_patterns=STAGE_PATTERNS)


def _trigger_regen(slug: str) -> None:
    job_mod.start(
        PIPELINE, "regen", slug,
        [sys.executable, "-m", "shorts.cli", "stocks", "regen", slug],
        cwd=str(REPO_ROOT), stage_patterns=STAGE_PATTERNS,
    )


def _trigger_render_idea(idea_id: str, label: str) -> None:
    job_mod.start(
        PIPELINE, "render-idea", label[:80] or idea_id,
        [sys.executable, "-m", "shorts.cli", "stocks", "render-idea", idea_id],
        cwd=str(REPO_ROOT), stage_patterns=STAGE_PATTERNS,
    )


def _clip_meta(run_id: str, version: int) -> dict:
    """Best-effort {format, sector, tickers, duration_s} from a render manifest."""
    import json as _json

    from .planner.published import sector_for

    manifest = _store.short_path(run_id, version).with_suffix(".manifest.json")
    meta = {"format": "", "sector": "", "tickers": [], "duration_s": None,
            "cost_usd": None, "ready_at": None, "build_time": None}
    if manifest.exists():
        try:
            m = _json.loads(manifest.read_text(encoding="utf-8"))
            meta["format"] = m.get("format", "")
            meta["tickers"] = [t.get("ticker", "") for t in m.get("tickers", []) if t.get("ticker")]
            meta["duration_s"] = m.get("duration_s")
            meta["cost_usd"] = (m.get("cost_breakdown") or {}).get("total_usd")
            # When it finished building (server clock, UTC) → show HH:MM.
            ra = m.get("rendered_at")
            if isinstance(ra, str) and len(ra) >= 16:
                meta["ready_at"] = ra[11:16]
            # How long it took to build → "2m 34s" or "47s".
            rs = m.get("render_seconds")
            if isinstance(rs, (int, float)):
                rs = int(round(rs))
                meta["build_time"] = f"{rs // 60}m {rs % 60:02d}s" if rs >= 60 else f"{rs}s"
            if meta["tickers"]:
                meta["sector"] = sector_for(meta["tickers"][0])
        except Exception:
            pass
    return meta


def _collect_items() -> tuple[list, list, dict[str, dict]]:
    """Split staged review items into today/earlier and gather their card meta."""
    from datetime import date

    today = date.today().isoformat()
    today_items: list = []
    earlier_items: list = []
    meta: dict[str, dict] = {}
    for item in _store.list_items():
        if item.run_id.startswith("_"):
            continue
        lv = latest_version(item)
        meta[item.run_id] = _clip_meta(item.run_id, lv.v) if lv else {}
        if (item.created_at or "")[:10] == today:
            today_items.append(item)
        else:
            earlier_items.append(item)
    return today_items, earlier_items, meta


@router.get("/", response_class=HTMLResponse)
def index(request: Request) -> Any:
    from shorts.version import build_id

    from .schedule import SCHEDULE_UTC_HOURS, next_runs

    today_items, earlier_items, meta = _collect_items()

    cfg = None
    try:
        from .planner import store as plan_store
        cfg = plan_store.load_config()
    except Exception:
        pass

    jobs = job_mod.list_jobs(PIPELINE, limit=20)
    daily_target = cfg.daily_target if cfg else 3
    # Show one countdown per clip we'll actually produce today (== daily_target,
    # bounded by the number of scheduled slots that exist).
    n_slots = max(1, min(daily_target, len(SCHEDULE_UTC_HOURS)))
    return templates.TemplateResponse(
        request, "index.html",
        {
            "today_items": today_items,
            "earlier_items": earlier_items,
            "meta": meta,
            "daily_target": daily_target,
            "latest_version_of": latest_version,
            "url_prefix": "/stocks",
            "jobs": jobs,
            "render_kinds": sorted(RENDER_KINDS),
            "next_runs": [d.isoformat() for d in next_runs(n_slots)],
            "version": build_id(),
        },
    )


@router.get("/cards", response_class=HTMLResponse)
def cards_partial(request: Request) -> Any:
    """Just the Today-grid card markup — fetched by the dashboard poller to
    slide a freshly-finished clip in at the top without a full-page reload."""
    today_items, _earlier, meta = _collect_items()
    return templates.TemplateResponse(
        request, "_cards.html",
        {
            "today_items": today_items,
            "meta": meta,
            "latest_version_of": latest_version,
            "url_prefix": "/stocks",
        },
    )


@router.get("/jobs")
def api_jobs() -> dict:
    return {"jobs": job_mod.list_jobs(PIPELINE, limit=20)}


@router.get("/scripts/recent")
def scripts_recent(limit: int = 6) -> dict:
    """Read-only dump of the most recent scripts' full narration (the rendered
    artifacts are purged on publish, but the script rows persist in the DB)."""
    from sqlmodel import Session, select

    from .db import Render as RenderRow
    from .db import Script as ScriptRow
    from .db import get_engine

    out = []
    with Session(get_engine()) as session:
        rows = session.exec(
            select(ScriptRow).order_by(ScriptRow.id.desc()).limit(limit)
        ).all()
        for sr in rows:
            p = sr.payload or {}
            beats = p.get("beats", []) or []
            render = session.exec(
                select(RenderRow).where(RenderRow.script_id == sr.id)
                .order_by(RenderRow.id.desc())
            ).first()
            slug = ""
            if render and render.mp4_path:
                # .../output/<slug>/v1/short.mp4
                parts = render.mp4_path.replace("\\", "/").split("/output/")
                slug = parts[1].split("/")[0] if len(parts) > 1 else ""
            out.append({
                "script_id": sr.id,
                "slug": slug,
                "title": p.get("title"),
                "format": p.get("format"),
                "tickers": [t.get("ticker") for t in p.get("tickers", [])],
                "narration": " ".join(b.get("narration", "") for b in beats),
                "beats": [{"role": b.get("role"), "text": b.get("narration")} for b in beats],
            })
    return {"scripts": out}


@router.get("/video/{run_id}/v{version}")
def serve_video(run_id: str, version: int) -> FileResponse:
    path = _store.short_path(run_id, version)
    if not path.exists():
        raise HTTPException(404, f"v{version} short.mp4 missing")
    return FileResponse(path, media_type="video/mp4")


@router.post("/generate")
def generate(
    background_tasks: BackgroundTasks,
    mode: str = Form("daily"),
    fixture_slug: str = Form(""),
) -> RedirectResponse:
    """Kick off a stocks render. Two modes:
       - 'daily': run the full orchestrator on today's market.
       - 'fixture': re-render a named fixture (slug).
    """
    if mode == "fixture" and fixture_slug.strip():
        background_tasks.add_task(_trigger_render_fixture, fixture_slug.strip())
    else:
        background_tasks.add_task(_trigger_run)
    return RedirectResponse(url="/stocks/?generating=1", status_code=303)


@router.post("/run/{run_id}/publish")
def publish(run_id: str, background_tasks: BackgroundTasks) -> RedirectResponse:
    item = _store.load(run_id)
    if item is None:
        raise HTTPException(404, "Run not found")
    item.status = "publishing"
    _store.save(item)
    background_tasks.add_task(_trigger_publish, run_id)
    return RedirectResponse(url=f"/stocks/", status_code=303)


@router.post("/run/{run_id}/comment")
def comment(run_id: str, background_tasks: BackgroundTasks,
            text: str = Form(...)) -> RedirectResponse:
    """Leave a note on a clip → re-render it as a new version addressing the note."""
    text = text.strip()
    if not text:
        return RedirectResponse(url="/stocks/", status_code=303)
    item = _store.add_comment(run_id, text)  # sets status="processing"
    if item is None:
        raise HTTPException(404, "Run not found")
    background_tasks.add_task(_trigger_regen, run_id)
    return RedirectResponse(url="/stocks/?improving=1", status_code=303)


@router.post("/run/{run_id}/delete")
def delete(run_id: str) -> RedirectResponse:
    """Reject a clip — remove it from the stage. No auto-replacement."""
    import shutil

    run_dir = _store.output_root / run_id
    if run_dir.exists():
        shutil.rmtree(run_dir, ignore_errors=True)
    return RedirectResponse(url="/stocks/", status_code=303)


@router.get("/stats", response_class=HTMLResponse)
def stats_page(request: Request) -> Any:
    """Simple coverage stats from the published ledger (vs the tuning weights)."""
    from collections import Counter

    from .planner import store as plan_store
    from .planner.published import load_published

    ledger = load_published()
    cfg = plan_store.load_config()

    by_sector = Counter(e.sector for e in ledger.entries)
    by_format = Counter(e.format or "(unknown)" for e in ledger.entries)
    total = len(ledger.entries)

    # Sector rows: published count vs the user's sector_bias weight.
    sector_keys = set(by_sector) | set(cfg.sector_bias or {})
    sector_rows = sorted(
        ({"name": k, "count": by_sector.get(k, 0), "weight": (cfg.sector_bias or {}).get(k)}
         for k in sector_keys),
        key=lambda r: (-r["count"], r["name"]),
    )
    format_rows = sorted(
        ({"name": k, "count": v} for k, v in by_format.items()),
        key=lambda r: (-r["count"], r["name"]),
    )
    recent = list(reversed(ledger.entries))[:20]

    return templates.TemplateResponse(
        request, "stats.html",
        {
            "url_prefix": "/stocks",
            "total": total,
            "sector_rows": sector_rows,
            "format_rows": format_rows,
            "recent": recent,
        },
    )


@router.get("/feedback", response_class=HTMLResponse)
def feedback_page(request: Request) -> Any:
    f = distill_mod.load(PIPELINE)
    return templates.TemplateResponse(
        request, "feedback.html",
        {"insights_file": f, "url_prefix": "/stocks"},
    )


@router.post("/feedback")
def feedback_submit(text: str = Form(...)) -> RedirectResponse:
    text = text.strip()
    if not text:
        return RedirectResponse(url="/stocks/feedback", status_code=303)

    from shorts.core.reviews.distill import Insight, load, save

    f = load(PIPELINE)
    f.insights.append(
        Insight(
            bullet=text,
            added_at=datetime.now().isoformat(timespec="seconds"),
            from_run="(global)",
            source_comment=text[:300],
            category="general",
        )
    )
    save(PIPELINE, f)
    return RedirectResponse(url="/stocks/feedback", status_code=303)


# ── Content planner: plan calendar + tuning knobs ───────────────────────────

@router.get("/plan", response_class=HTMLResponse)
def plan_page(request: Request) -> Any:
    from collections import Counter

    from .planner import store as plan_store

    plan = plan_store.load_plan()
    debt = plan_store.load_debt()
    cfg = plan_store.load_config()
    ideas = plan_store.load_ideas()
    strategy = plan_store.load_strategy()
    jobs = job_mod.list_jobs(PIPELINE, limit=10)

    # Editorial mix: count upcoming (not-yet-rendered) items by content lane.
    mix = Counter(it.content_kind for it in plan.items if it.status in ("planned", "rendering"))
    return templates.TemplateResponse(
        request, "plan.html",
        {
            "url_prefix": "/stocks",
            "plan": plan,
            "open_debt": debt.open(),
            "all_debt": debt.commitments,
            "series": cfg.active_series(),
            "ideas": ideas.items,
            "mix": dict(mix),
            "strategy": strategy,
            "jobs": jobs,
        },
    )


@router.post("/plan/ideas/add")
def ideas_add(prompt: str = Form("")) -> RedirectResponse:
    from .planner import store as plan_store
    from .planner.models import IdeaItem

    text = prompt.strip()
    if text:
        ideas = plan_store.load_ideas()
        ideas.items.append(IdeaItem(prompt=text))
        plan_store.save_ideas(ideas)
    return RedirectResponse(url="/stocks/plan", status_code=303)


@router.post("/plan/ideas/{idea_id}/generate")
def ideas_generate(idea_id: str, background_tasks: BackgroundTasks) -> RedirectResponse:
    from .planner import store as plan_store

    ideas = plan_store.load_ideas()
    idea = next((i for i in ideas.items if i.id == idea_id), None)
    if idea is None:
        raise HTTPException(404, "Idea not found")
    background_tasks.add_task(_trigger_render_idea, idea_id, idea.prompt)
    return RedirectResponse(url="/stocks/plan?rendering=1", status_code=303)


@router.post("/plan/ideas/{idea_id}/delete")
def ideas_delete(idea_id: str) -> RedirectResponse:
    from .planner import store as plan_store

    ideas = plan_store.load_ideas()
    ideas.items = [i for i in ideas.items if i.id != idea_id]
    plan_store.save_ideas(ideas)
    return RedirectResponse(url="/stocks/plan", status_code=303)


@router.post("/plan/regenerate")
def plan_regenerate(background_tasks: BackgroundTasks) -> RedirectResponse:
    from .planner.orchestrate import regenerate_plan

    background_tasks.add_task(regenerate_plan)
    return RedirectResponse(url="/stocks/plan", status_code=303)


@router.post("/plan/render-next")
def plan_render_next(background_tasks: BackgroundTasks) -> RedirectResponse:
    background_tasks.add_task(_trigger_autopilot_tick)
    return RedirectResponse(url="/stocks/plan?rendering=1", status_code=303)


def _require_autopilot_token(request: Request) -> None:
    """Guard the machine-to-machine tick endpoint with a shared secret.

    If AUTOPILOT_TOKEN is set in the environment (a Fly secret in prod), the
    caller must echo it via the X-Autopilot-Token header or a ?token= query
    param. When unset (e.g. local dev) the endpoint stays open, matching the
    rest of the dashboard.
    """
    expected = os.environ.get("AUTOPILOT_TOKEN", "").strip()
    if not expected:
        return
    supplied = (request.headers.get("x-autopilot-token")
                or request.query_params.get("token") or "").strip()
    if supplied != expected:
        raise HTTPException(401, "bad or missing autopilot token")


@router.post("/autopilot/tick")
def autopilot_tick(request: Request, background_tasks: BackgroundTasks) -> dict:
    """Cloud cron entry point: enqueue a render of the next due planned item.

    Called by the scheduled GitHub Action. The POST wakes the auto-stopped Fly
    machine (auto_start_machines=true), so the render runs on the machine that
    owns the data volume. Replanning, if the queue is empty, happens inside the
    enqueued `autopilot tick` job. Returns JSON describing what will run.
    """
    _require_autopilot_token(request)

    from .planner import store as plan_store
    from .planner.orchestrate import next_due_item

    plan = plan_store.load_plan()
    planned = [it for it in plan.items if it.status == "planned"]
    due = next_due_item(plan)

    # Scheduled (cron) ticks replan first so each slot reflects the latest
    # market, then render exactly one fresh clip (the daily target caps the day).
    background_tasks.add_task(_trigger_autopilot_tick, replan=True)

    if due is None and not planned:
        return {"status": "enqueued", "action": "replan+render",
                "note": "plan empty — tick will regenerate then render"}
    target = due
    return {
        "status": "enqueued",
        "action": "render",
        "planned_remaining": len(planned),
        "next": None if target is None else {
            "id": target.id,
            "format": target.format,
            "scheduled_for": target.scheduled_for.isoformat(),
            "tickers": target.topic_seed.tickers,
            "title_hint": target.title_hint,
            "source": target.source,
        },
    }


@router.post("/plan/{item_id}/{action}")
def plan_item_action(item_id: str, action: str) -> RedirectResponse:
    """Per-item plan controls: skip | pin | bump (render sooner)."""
    from datetime import date

    from .planner import store as plan_store

    if action not in {"skip", "pin", "bump"}:
        raise HTTPException(400, f"unknown action {action!r}")
    plan = plan_store.load_plan()
    for it in plan.items:
        if it.id != item_id:
            continue
        if action == "skip":
            it.status = "skipped"
        elif action == "pin":
            it.pinned = not it.pinned
        elif action == "bump":
            it.scheduled_for = date.today()
            it.pinned = True
    plan_store.save_plan(plan)
    return RedirectResponse(url="/stocks/plan", status_code=303)


@router.get("/tune", response_class=HTMLResponse)
def tune_page(request: Request) -> Any:
    from .planner import store as plan_store

    cfg = plan_store.load_config()
    return templates.TemplateResponse(
        request, "tune.html",
        {"url_prefix": "/stocks", "cfg": cfg, "formats": _format_names()},
    )


@router.post("/tune")
def tune_submit(
    background_tasks: BackgroundTasks,
    daily_target: int = Form(3),
    sector_bias: str = Form(""),
    type_mix: str = Form(""),
    directive: str = Form(""),
    auto_publish: str = Form(""),
) -> RedirectResponse:
    """Write orchestration.json from the knobs, then regenerate the plan.

    sector_bias / type_mix are free-text "key=weight" lines (one per line or
    comma-separated) — forgiving to parse so the form stays simple.
    """
    from .planner import store as plan_store
    from .planner.orchestrate import regenerate_plan

    cfg = plan_store.load_config()
    cfg.daily_target = max(1, min(int(daily_target), 14))
    cfg.weekly_volume = cfg.daily_target  # keep legacy alias in sync
    cfg.sector_bias = _parse_weights(sector_bias)
    cfg.type_mix = _parse_weights(type_mix)
    cfg.free_text_directive = directive.strip()
    # Unchecked checkboxes submit nothing, so absence == off.
    cfg.auto_publish = auto_publish.lower() in ("1", "true", "on", "yes")
    plan_store.save_config(cfg)

    background_tasks.add_task(regenerate_plan)
    return RedirectResponse(url="/stocks/plan?tuned=1", status_code=303)


def _format_names() -> list[str]:
    from . import formats
    return [s.name for s in formats.list_specs()]


def _parse_weights(raw: str) -> dict[str, float]:
    """Parse 'key=weight' pairs separated by commas or newlines into a dict."""
    out: dict[str, float] = {}
    for chunk in raw.replace("\n", ",").split(","):
        chunk = chunk.strip()
        if not chunk or "=" not in chunk:
            continue
        key, _, val = chunk.partition("=")
        key = key.strip()
        try:
            out[key] = float(val.strip())
        except ValueError:
            continue
    return out
