"""brawl pipeline routes — mounted at /brawl by the shared dashboard factory.

Hebrew RTL iteration UX: comment → status=processing → background regen → v2
appears side-by-side. Each comment also distills into the brawl pipeline's
permanent insights file.
"""
from __future__ import annotations

import os
import subprocess
import sys
from datetime import datetime
from pathlib import Path
from threading import Lock
from typing import Any

from fastapi import APIRouter, BackgroundTasks, Form, HTTPException, Request
from fastapi.responses import FileResponse, HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates

from shorts.config import REPO_ROOT
from shorts.core import jobs as job_mod
from shorts.core.reviews import ReviewStore, latest_version
from shorts.core.reviews import distill as distill_mod

PIPELINE = "brawl"
TEMPLATES_DIR = Path(__file__).resolve().parent / "templates"

router = APIRouter(prefix="/brawl", tags=["brawl"])
templates = Jinja2Templates(directory=str(TEMPLATES_DIR))
_store = ReviewStore(PIPELINE)

# Only one regeneration at a time; comments queue behind it.
_regen_lock = Lock()


def _trigger_regenerate(run_id: str) -> None:
    with _regen_lock:
        job_mod.start(
            PIPELINE, "regenerate", run_id,
            [sys.executable, "-m", "shorts.cli", "brawl", "regenerate", run_id],
            cwd=str(REPO_ROOT),
        )


def _trigger_make_short(url: str, start: int = -1, end: int = -1) -> None:
    cmd = [sys.executable, "-m", "shorts.cli", "brawl", "make-short", url]
    label = url
    if start >= 0 and end >= 0:
        cmd += ["--start", str(start), "--end", str(end)]
        label = f"{url} [{start}-{end}s]"
    job_mod.start(PIPELINE, "make-short", label, cmd, cwd=str(REPO_ROOT))


def _trigger_publish(run_id: str) -> None:
    job_mod.start(
        PIPELINE, "publish", run_id,
        [sys.executable, "-m", "shorts.cli", "upload", run_id, "--pipeline", "brawl"],
        cwd=str(REPO_ROOT),
    )


def _trigger_refresh_library() -> None:
    job_mod.start(
        PIPELINE, "refresh-library", "(discovery)",
        [sys.executable, "-m", "shorts.cli", "brawl", "refresh-library"],
        cwd=str(REPO_ROOT),
    )


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------


@router.get("/", response_class=HTMLResponse)
def index(request: Request) -> Any:
    from . import library as lib_mod

    items = _store.list_items()
    jobs = job_mod.list_jobs(PIPELINE, limit=20)
    library = lib_mod.load()
    return templates.TemplateResponse(
        request, "index.html",
        {
            "items": items,
            "latest_version_of": latest_version,
            "url_prefix": "/brawl",
            "jobs": jobs,
            "library": library.entries,
        },
    )


@router.get("/jobs")
def api_jobs() -> dict:
    return {"jobs": job_mod.list_jobs(PIPELINE, limit=20)}


@router.get("/run/{run_id}", response_class=HTMLResponse)
def run_detail(request: Request, run_id: str) -> Any:
    item = _store.load(run_id)
    if item is None:
        raise HTTPException(404, "Run not found")
    versions = sorted(item.versions, key=lambda v: v.v, reverse=True)
    return templates.TemplateResponse(
        request, "run.html",
        {"item": item, "versions": versions, "run_id": run_id, "url_prefix": "/brawl"},
    )


@router.get("/video/{run_id}/v{version}")
def serve_video(run_id: str, version: int) -> FileResponse:
    path = _store.short_path(run_id, version)
    if not path.exists():
        raise HTTPException(404, f"v{version} short.mp4 missing")
    return FileResponse(path, media_type="video/mp4")


def _apply_comment(run_id: str, text: str, background_tasks: BackgroundTasks) -> bool:
    """Append a comment to one run, distill it, mark processing, queue regen.

    Returns True if applied, False if the run was missing. Shared by the
    single-clip comment route and the bulk scoped-review route.
    """
    item = _store.load(run_id)
    if item is None:
        return False

    from shorts.core.reviews.schema import Comment

    item.comments.append(
        Comment(
            text=text,
            version_at_time=item.current_version,
            created_at=datetime.now().isoformat(timespec="seconds"),
        )
    )
    item.status = "processing"
    _store.save(item)

    # Side effect: distill the comment into permanent insights (best-effort).
    try:
        key = os.environ.get("ANTHROPIC_API_KEY", "").strip()
        if key:
            distill_mod.extract_and_save(
                PIPELINE,
                comment_text=text,
                run_context=f"{item.source_title} (v{item.current_version})",
                api_key=key,
                run_id=run_id,
            )
    except Exception:
        pass

    background_tasks.add_task(_trigger_regenerate, run_id)
    return True


@router.post("/run/{run_id}/comment")
def post_comment(
    run_id: str,
    background_tasks: BackgroundTasks,
    text: str = Form(...),
) -> RedirectResponse:
    text = text.strip()
    if not text:
        return RedirectResponse(url=f"/brawl/run/{run_id}", status_code=303)
    if not _apply_comment(run_id, text, background_tasks):
        raise HTTPException(404, "Run not found")
    return RedirectResponse(url=f"/brawl/run/{run_id}", status_code=303)


@router.post("/bulk-comment")
def bulk_comment(
    background_tasks: BackgroundTasks,
    text: str = Form(...),
    run_ids: list[str] = Form(default=[]),
) -> RedirectResponse:
    """Scoped review: apply one note to a chosen subset of clips and regenerate
    each. Each selected clip gets the comment + a new version, exactly like a
    per-clip comment, but submitted once for many clips."""
    text = text.strip()
    if text and run_ids:
        for rid in run_ids:
            _apply_comment(rid, text, background_tasks)
    return RedirectResponse(url="/brawl/", status_code=303)


# ---- Source-video library (long-form VODs to clip from) -------------------


@router.post("/library/add")
def library_add(url: str = Form(...)) -> RedirectResponse:
    """Pin a video URL to the library, hydrating title/duration from YouTube
    when an API key is available (falls back to a bare entry otherwise)."""
    from . import config as bcfg
    from . import library as lib_mod
    from .discovery import youtube as yt

    url = url.strip()
    vid = lib_mod.parse_video_id(url)
    if not vid:
        return RedirectResponse(url="/brawl/", status_code=303)

    title, channel, duration_s = "", "", 0
    try:
        secrets = bcfg.load_secrets(require_anthropic=False)
        client = yt._build_client(secrets.youtube_api_key)
        resp = client.videos().list(part="snippet,contentDetails", id=vid).execute()
        if resp.get("items"):
            it = resp["items"][0]
            title = it["snippet"]["title"]
            channel = it["snippet"]["channelTitle"]
            duration_s = yt._parse_iso8601_duration(it["contentDetails"]["duration"])
    except Exception:
        pass  # offline / no key — store the bare entry, still usable.

    lib_mod.add_manual(url, title=title, channel=channel, duration_s=duration_s)
    return RedirectResponse(url="/brawl/", status_code=303)


@router.post("/library/remove")
def library_remove(video_id: str = Form(...)) -> RedirectResponse:
    from . import library as lib_mod
    lib_mod.remove(video_id.strip())
    return RedirectResponse(url="/brawl/", status_code=303)


@router.post("/library/refresh")
def library_refresh(background_tasks: BackgroundTasks) -> RedirectResponse:
    """Repopulate auto entries from the discovery ranking (background job)."""
    background_tasks.add_task(_trigger_refresh_library)
    return RedirectResponse(url="/brawl/?refreshing=1", status_code=303)


@router.post("/library/generate")
def library_generate(
    background_tasks: BackgroundTasks,
    url: str = Form(...),
    start_s: str = Form(""),
    end_s: str = Form(""),
) -> RedirectResponse:
    """Generate a clip from a library entry — reuses the same make-short flow
    (with optional manual cut points) as the top generate form."""
    return generate(background_tasks, url=url, start_s=start_s, end_s=end_s)


@router.get("/api/status/{run_id}")
def api_status(run_id: str) -> dict:
    item = _store.load(run_id)
    if item is None:
        raise HTTPException(404)
    return {
        "status": item.status,
        "current_version": item.current_version,
        "n_versions": len(item.versions),
    }


@router.get("/insights", response_class=HTMLResponse)
def insights_page(request: Request) -> Any:
    f = distill_mod.load(PIPELINE)
    return templates.TemplateResponse(
        request, "insights.html",
        {"insights_file": f, "url_prefix": "/brawl"},
    )


@router.post("/generate")
def generate(
    background_tasks: BackgroundTasks,
    url: str = Form(...),
    start_s: str = Form(""),
    end_s: str = Form(""),
) -> RedirectResponse:
    """Kick off `shorts brawl make-short <url>` in the background.

    Optional start_s/end_s let the reviewer pick an exact cut window; when both
    are given, moment detection is skipped. Returns immediately; the new clip
    lands in the queue when done.
    """
    url = url.strip()
    if not url:
        return RedirectResponse(url="/brawl/", status_code=303)

    def _parse(v: str) -> int:
        v = v.strip()
        if not v:
            return -1
        # Accept "90" or "1:30" (mm:ss).
        if ":" in v:
            mm, ss = v.split(":", 1)
            try:
                return int(mm) * 60 + int(ss)
            except ValueError:
                return -1
        try:
            return int(float(v))
        except ValueError:
            return -1

    start, end = _parse(start_s), _parse(end_s)
    background_tasks.add_task(_trigger_make_short, url, start, end)
    return RedirectResponse(url="/brawl/?generating=1", status_code=303)


@router.post("/run/{run_id}/publish")
def publish(run_id: str, background_tasks: BackgroundTasks) -> RedirectResponse:
    """Trigger YouTube upload to the brawl channel."""
    item = _store.load(run_id)
    if item is None:
        raise HTTPException(404, "Run not found")
    # Mark as published-pending so the UI can show it.
    item.status = "publishing"
    _store.save(item)
    background_tasks.add_task(_trigger_publish, run_id)
    return RedirectResponse(url=f"/brawl/run/{run_id}", status_code=303)


# ---- Global feedback (per-pipeline notes that steer all future generations) ----


@router.get("/feedback", response_class=HTMLResponse)
def feedback_page(request: Request) -> Any:
    """Show the accumulated insights + a textarea to add a new global note."""
    f = distill_mod.load(PIPELINE)
    return templates.TemplateResponse(
        request, "feedback.html",
        {"insights_file": f, "url_prefix": "/brawl"},
    )


@router.post("/feedback")
def feedback_submit(text: str = Form(...)) -> RedirectResponse:
    """Add a manually-written global note. Stored alongside the LLM-distilled ones."""
    text = text.strip()
    if not text:
        return RedirectResponse(url="/brawl/feedback", status_code=303)

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
    return RedirectResponse(url="/brawl/feedback", status_code=303)
