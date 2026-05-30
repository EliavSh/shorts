"""Per-pipeline SQLite engine for cost tracking.

Each pipeline writes to its own DB file at data/<pipeline>/usage.db. A context
var lets shared modules (anthropic_client wrapper, etc.) emit records without
needing to know the pipeline name explicitly — the pipeline's CLI sets it once
at startup.
"""
from __future__ import annotations

import contextvars
from pathlib import Path

from sqlmodel import SQLModel, create_engine
from sqlalchemy.engine import Engine

from shorts.config import pipeline_data_dir

from .models import UsageEvent  # noqa: F401  — needed so SQLModel sees the table


_current_pipeline: contextvars.ContextVar[str | None] = contextvars.ContextVar(
    "current_pipeline", default=None,
)

_engines: dict[str, Engine] = {}


def set_pipeline(name: str | None) -> None:
    """Tag subsequent record() calls with this pipeline (until reset)."""
    _current_pipeline.set(name)


def current_pipeline() -> str | None:
    return _current_pipeline.get()


def db_path_for(pipeline: str) -> Path:
    return pipeline_data_dir(pipeline) / "usage.db"


def get_engine(pipeline: str | None = None) -> Engine:
    """Return (and cache) the SQLite engine for `pipeline`. Falls back to the
    context-var pipeline if not given."""
    p = pipeline or current_pipeline()
    if not p:
        raise RuntimeError(
            "No pipeline set for usage tracking. Call set_pipeline(<name>) or "
            "pass pipeline= explicitly."
        )
    if p not in _engines:
        path = db_path_for(p)
        path.parent.mkdir(parents=True, exist_ok=True)
        engine = create_engine(f"sqlite:///{path.as_posix()}", echo=False)
        SQLModel.metadata.create_all(engine)
        _engines[p] = engine
    return _engines[p]


def init_db(pipeline: str) -> None:
    """Ensure the pipeline's DB file + tables exist."""
    _ = get_engine(pipeline)
