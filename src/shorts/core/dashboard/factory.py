"""Shared dashboard factory.

Mounts each pipeline's router under its own URL prefix and exposes a top-level
home page listing both pipelines. Each pipeline owns its own templates so
brawl can stay Hebrew RTL while stocks runs English.
"""
from __future__ import annotations

from pathlib import Path
from typing import Any

from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates

from shorts.core.reviews import ReviewStore
from shorts.core.reviews.schema import latest_version

TEMPLATES_DIR = Path(__file__).resolve().parent / "templates"

app = FastAPI(title="Shorts review dashboard")
templates = Jinja2Templates(directory=str(TEMPLATES_DIR))


# ---------------------------------------------------------------------------
# Mount each pipeline's router (best-effort: missing pipelines just don't appear)
# ---------------------------------------------------------------------------

_pipelines: list[dict[str, Any]] = []

try:
    from shorts.pipelines.brawl.routes import router as brawl_router
    app.include_router(brawl_router)
    _pipelines.append({
        "name": "brawl",
        "label": "Brawl Stars",
        "prefix": "/brawl",
        "accent": "#FFD400",
        "store": ReviewStore("brawl"),
    })
except ImportError:
    pass

try:
    from shorts.pipelines.stocks.routes import router as stocks_router
    app.include_router(stocks_router)
    _pipelines.append({
        "name": "stocks",
        "label": "Stocks (finance)",
        "prefix": "/stocks",
        "accent": "#22C55E",
        "store": ReviewStore("stocks"),
    })
except ImportError:
    pass


# ---------------------------------------------------------------------------
# Apartment scanner — a full React SPA + FastAPI app, mounted as a sub-app under
# /apartments (not a Jinja router like the pipelines above). It has no
# ReviewStore, so it's tracked separately for the home-page tab.
# ---------------------------------------------------------------------------

_apartments_mounted = False
try:
    from scanner.api.app import app as _apartment_app
    app.mount("/apartments", _apartment_app)
    _apartments_mounted = True
except Exception as exc:  # noqa: BLE001 — never let apartments break the dashboard
    import logging
    logging.getLogger("dashboard").warning("apartments app not mounted: %s", exc)


@app.get("/", response_class=HTMLResponse)
def home(request: Request) -> Any:
    # Summarise each pipeline's queue for the landing page.
    rows: list[dict[str, Any]] = []
    for p in _pipelines:
        store: ReviewStore = p["store"]
        try:
            items = store.list_items()
        except Exception:
            items = []
        total = len(items)
        pending = sum(1 for i in items if i.status != "ready")
        latest_title = ""
        if items:
            v = latest_version(items[0])
            if v:
                latest_title = v.title
        rows.append({
            "name": p["name"],
            "label": p["label"],
            "prefix": p["prefix"],
            "accent": p["accent"],
            "total": total,
            "pending": pending,
            "latest_title": latest_title,
        })

    return templates.TemplateResponse(
        request, "home.html", {"pipelines": rows, "apartments": _apartments_mounted},
    )
