"""stocks pipeline DB models — pipeline-internal tables.

UsageEvent is owned by shorts.core.usage (shared across pipelines, but each
pipeline's instance lives at data/<pipeline>/usage.db). These tables here
(Topic, Script, Render, Upload, Performance) are stocks-specific.
"""
from datetime import datetime

from sqlmodel import JSON, Column, Field, SQLModel, create_engine

from .settings import get_settings


class Topic(SQLModel, table=True):
    id: int | None = Field(default=None, primary_key=True)
    created_at: datetime = Field(default_factory=datetime.utcnow)
    lang: str
    ticker_primary: str
    ticker_secondary: str | None = None
    pivot_reason: str | None = None
    score: float = 0.0
    raw_context: dict = Field(default_factory=dict, sa_column=Column(JSON))


class Script(SQLModel, table=True):
    id: int | None = Field(default=None, primary_key=True)
    topic_id: int = Field(foreign_key="topic.id")
    created_at: datetime = Field(default_factory=datetime.utcnow)
    lang: str
    payload: dict = Field(default_factory=dict, sa_column=Column(JSON))


class Render(SQLModel, table=True):
    id: int | None = Field(default=None, primary_key=True)
    script_id: int = Field(foreign_key="script.id")
    created_at: datetime = Field(default_factory=datetime.utcnow)
    mp4_path: str
    duration_s: float
    audio_path: str | None = None
    transcript_path: str | None = None


class Upload(SQLModel, table=True):
    id: int | None = Field(default=None, primary_key=True)
    render_id: int = Field(foreign_key="render.id")
    created_at: datetime = Field(default_factory=datetime.utcnow)
    youtube_video_id: str
    channel: str
    visibility: str
    title: str
    promoted_at: datetime | None = None


class Performance(SQLModel, table=True):
    id: int | None = Field(default=None, primary_key=True)
    upload_id: int = Field(foreign_key="upload.id")
    fetched_at: datetime = Field(default_factory=datetime.utcnow)
    views: int = 0
    likes: int = 0
    avg_view_duration_s: float = 0.0
    retention_curve: dict = Field(default_factory=dict, sa_column=Column(JSON))


def get_engine():
    s = get_settings()
    s.ensure_dirs()
    return create_engine(s.db_url, echo=False)


def init_db() -> None:
    SQLModel.metadata.create_all(get_engine())
