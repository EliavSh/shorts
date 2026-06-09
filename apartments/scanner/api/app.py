"""FastAPI application entry point.

Run: ``uvicorn scanner.api.app:app --host 0.0.0.0 --port 8000``

In production also serves the built React app from ``frontend/dist/``.
"""
from pathlib import Path

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from scanner.api.deps import get_database
from scanner.api.routes import analytics, charts, deals, gps, listings, meta, transactions, zones
from scanner.db import init_schema

app = FastAPI(
    title="Apartment Scanner API",
    description="REST + WebSocket layer over the scanner SQLite DB and services.",
    version="0.1.0",
)


@app.on_event("startup")
def _ensure_schema():
    # Backfills missing columns (first_seen, neighborhood, etc.) on legacy DBs.
    init_schema(get_database())


app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173", "http://127.0.0.1:5173"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(listings.router)
app.include_router(transactions.router)
app.include_router(deals.router)
app.include_router(analytics.router)
app.include_router(gps.router)
app.include_router(zones.router)
app.include_router(meta.router)
app.include_router(charts.router)


@app.get("/api/health")
def health():
    return {"status": "ok"}


# Serve the React build, if present. /api/* takes precedence because routers
# were registered first; the SPA catch-all only handles non-/api paths.
# SCANNER_FRONTEND_DIST lets a host app (e.g. the shorts dashboard that mounts
# this app under /apartments) point at a dist built elsewhere in the image.
import os as _os
_DIST = Path(
    _os.environ.get(
        "SCANNER_FRONTEND_DIST",
        str(Path(__file__).resolve().parents[2] / "frontend" / "dist"),
    )
)
if _DIST.is_dir():
    app.mount(
        "/assets",
        StaticFiles(directory=_DIST / "assets"),
        name="assets",
    )

    @app.get("/{full_path:path}", include_in_schema=False)
    def spa(full_path: str):
        # Let the API 404 normally; only serve index.html for non-/api paths.
        if full_path.startswith("api/") or full_path.startswith("ws/"):
            from fastapi import HTTPException
            raise HTTPException(status_code=404)
        candidate = _DIST / full_path
        if candidate.is_file():
            return FileResponse(candidate)
        return FileResponse(_DIST / "index.html")
