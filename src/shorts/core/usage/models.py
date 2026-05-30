"""UsageEvent — one row per billable / quota-consuming API call.

Each pipeline gets its own SQLite DB at data/<pipeline>/usage.db; the schema is
the same. Rollups in core/usage/record.py scope by pipeline.
"""
from __future__ import annotations

from datetime import datetime

from sqlmodel import Field, SQLModel


class UsageEvent(SQLModel, table=True):
    """One billable / quota-consuming API call. Per-pipeline DB."""
    id: int | None = Field(default=None, primary_key=True)
    timestamp: datetime = Field(default_factory=datetime.utcnow, index=True)
    provider: str = Field(index=True)         # anthropic | serper | pexels | google_cse |
                                              # wikimedia | edge_tts | elevenlabs | youtube_data_v3
    operation: str                            # messages | image_search | tts | upload | privacy_update
    model: str | None = None                  # for anthropic: claude-opus-4-7 etc.
    units_in: int = 0                         # input tokens (LLM) — 0 otherwise
    units_out: int = 0                        # output tokens (LLM) — 0 otherwise
    units: int = 0                            # generic count: queries, characters, quota units
    cost_usd: float = 0.0
    video_slug: str | None = Field(default=None, index=True)
    success: bool = True
    note: str | None = None
