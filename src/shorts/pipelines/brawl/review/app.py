"""FastAPI review app — Hebrew RTL.

Reviewer-driven iteration loop:
  view clip → leave comment → status=processing → background regen → v2 appears
  side-by-side with v1 → comment again on v2 → ...

Each comment is also distilled by Claude into permanent "insights" that steer
future clips, not just this one.
"""
from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path
from threading import Lock
from typing import Any

from fastapi import BackgroundTasks, FastAPI, Form, HTTPException, Request
from fastapi.responses import FileResponse, HTMLResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from ..publish import insights as insights_mod
from ..publish import metadata as meta_mod
from .. import config as cfg

from shorts.config import REPO_ROOT  # noqa: E402
from shorts.config import pipeline_data_dir
OUTPUT_ROOT = pipeline_data_dir("brawl") / "output"
TEMPLATES_DIR = Path(__file__).resolve().parent / "templates"

app = FastAPI(title="ביקורת שורטס - ברול סטארס")
templates = Jinja2Templates(directory=str(TEMPLATES_DIR))

# Only one regeneration at a time; comments queue behind it.
_regen_lock = Lock()


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _list_items() -> list[meta_mod.ReviewItem]:
    return meta_mod.list_items()


def _trigger_regenerate(run_id: str) -> None:
    """Spawn a child process running `brawlshorts regenerate <id>`.

    We don't block the request — the reviewer sees the page flip to
    processing immediately; the new version appears when polling.
    """
    # Use sys.executable to ensure same venv. Module-level invocation.
    cmd = [sys.executable, "-m", "brawlshorts.cli", "regenerate", run_id]
    env = os.environ.copy()
    env["PYTHONIOENCODING"] = "utf-8"
    with _regen_lock:
        proc = subprocess.Popen(
            cmd,
            cwd=str(REPO_ROOT),
            env=env,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
    # Don't await; the worker runs detached.
    _ = proc.pid


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------


@app.get("/", response_class=HTMLResponse)
def index(request: Request) -> Any:
    items = _list_items()
    return templates.TemplateResponse(
        request, "index.html", {"items": items, "latest_version_of": meta_mod.latest_version}
    )


@app.get("/run/{run_id}", response_class=HTMLResponse)
def run_detail(request: Request, run_id: str) -> Any:
    item = meta_mod.load(run_id)
    if item is None:
        raise HTTPException(404, "Run not found")
    # Sort versions newest-first for side-by-side display.
    versions = sorted(item.versions, key=lambda v: v.v, reverse=True)
    return templates.TemplateResponse(
        request,
        "run.html",
        {
            "item": item,
            "versions": versions,
            "run_id": run_id,
        },
    )


@app.get("/video/{run_id}/v{version}")
def serve_video(run_id: str, version: int) -> FileResponse:
    path = OUTPUT_ROOT / run_id / f"v{version}" / "short.mp4"
    if not path.exists():
        raise HTTPException(404, f"v{version} short.mp4 missing")
    return FileResponse(path, media_type="video/mp4")


@app.post("/run/{run_id}/comment")
def post_comment(
    run_id: str,
    background_tasks: BackgroundTasks,
    text: str = Form(...),
) -> RedirectResponse:
    item = meta_mod.load(run_id)
    if item is None:
        raise HTTPException(404, "Run not found")

    text = text.strip()
    if not text:
        return RedirectResponse(url=f"/run/{run_id}", status_code=303)

    from datetime import datetime as _dt
    item.comments.append(
        meta_mod.Comment(
            text=text,
            version_at_time=item.current_version,
            created_at=_dt.now().isoformat(timespec="seconds"),
        )
    )
    item.status = "processing"
    meta_mod.save(item)

    # Side effects: extract insights + kick off regeneration.
    try:
        secrets = cfg.load_secrets(require_anthropic=True)
        insights_mod.extract_and_save(
            comment_text=text,
            run_context=f"{item.source_title} (v{item.current_version})",
            api_key=secrets.anthropic_api_key,
            run_id=run_id,
        )
    except Exception:
        # Don't block the user-facing flow if insight extraction fails.
        pass

    background_tasks.add_task(_trigger_regenerate, run_id)
    return RedirectResponse(url=f"/run/{run_id}", status_code=303)


@app.get("/api/status/{run_id}")
def api_status(run_id: str) -> dict:
    """Polled by the run-detail page to know when a new version is ready."""
    item = meta_mod.load(run_id)
    if item is None:
        raise HTTPException(404)
    return {
        "status": item.status,
        "current_version": item.current_version,
        "n_versions": len(item.versions),
    }


@app.get("/insights", response_class=HTMLResponse)
def insights_page(request: Request) -> Any:
    f = insights_mod.load()
    return templates.TemplateResponse(
        request, "insights.html", {"insights_file": f}
    )
