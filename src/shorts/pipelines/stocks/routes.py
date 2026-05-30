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


def _trigger_run() -> None:
    job_mod.start(
        PIPELINE, "daily-run", "(daily orchestrator)",
        [sys.executable, "-m", "shorts.cli", "stocks", "run"],
        cwd=str(REPO_ROOT),
    )


def _trigger_render_fixture(slug: str) -> None:
    job_mod.start(
        PIPELINE, "render-fixture", slug,
        [sys.executable, "-m", "shorts.cli", "stocks", "render-fixture", slug],
        cwd=str(REPO_ROOT),
    )


def _trigger_publish(slug: str) -> None:
    job_mod.start(
        PIPELINE, "publish", slug,
        [sys.executable, "-m", "shorts.cli", "upload", slug, "--pipeline", "stocks"],
        cwd=str(REPO_ROOT),
    )


@router.get("/", response_class=HTMLResponse)
def index(request: Request) -> Any:
    items = _store.list_items()
    jobs = job_mod.list_jobs(PIPELINE, limit=20)
    return templates.TemplateResponse(
        request, "index.html",
        {
            "items": items,
            "latest_version_of": latest_version,
            "url_prefix": "/stocks",
            "jobs": jobs,
        },
    )


@router.get("/jobs")
def api_jobs() -> dict:
    return {"jobs": job_mod.list_jobs(PIPELINE, limit=20)}


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
