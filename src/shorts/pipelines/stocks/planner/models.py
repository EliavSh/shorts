"""Planner data models — the content calendar, commitments (debt), recurring
series, and the orchestration knobs the user tunes.

All persisted as JSON under data/stocks/ (plan.json, debt.json,
orchestration.json) so they live on the Fly volume alongside insights.json.
"""
from __future__ import annotations

import uuid
from datetime import date, datetime
from typing import Literal

from pydantic import BaseModel, Field


PlanStatus = Literal["planned", "rendering", "rendered", "skipped"]
PlanSource = Literal["planner", "debt", "series", "earnings"]
CommitmentStatus = Literal["open", "scheduled", "fulfilled"]


def _new_id() -> str:
    return uuid.uuid4().hex[:10]


def _now() -> str:
    return datetime.now().isoformat(timespec="seconds")


class TopicSeed(BaseModel):
    """What a planned video is about, before the writer fleshes it out."""

    tickers: list[str] = Field(default_factory=list)
    theme: str | None = None


class PlannedVideo(BaseModel):
    id: str = Field(default_factory=_new_id)
    scheduled_for: date
    status: PlanStatus = "planned"
    format: str = "deep_dive_one_stock"
    length_band: tuple[int, int] = (90, 120)
    topic_seed: TopicSeed = Field(default_factory=TopicSeed)
    title_hint: str = ""
    rationale: str = ""
    source: PlanSource = "planner"
    pinned: bool = False
    slug: str | None = None  # set once rendered
    commitment_id: str | None = None  # set when this fulfils a commitment
    created_at: str = Field(default_factory=_now)


class Commitment(BaseModel):
    """A forward-looking promise auto-extracted from a script's narration."""

    id: str = Field(default_factory=_new_id)
    text: str
    tickers: list[str] = Field(default_factory=list)
    trigger: str | None = None  # e.g. "after earnings", "next week", "2026-06-10"
    status: CommitmentStatus = "open"
    source_slug: str = ""  # the video that made the promise
    created_at: str = Field(default_factory=_now)
    fulfilled_by: str | None = None  # slug of the video that delivered


class Series(BaseModel):
    """A recurring arc, e.g. an energy-sector series."""

    id: str = Field(default_factory=_new_id)
    name: str
    theme: str = ""
    format: str = "sector_spotlight"
    tickers: list[str] = Field(default_factory=list)
    cadence_days: int = 7
    next_part: int = 1
    total_parts: int | None = None
    active: bool = True
    last_scheduled: date | None = None


class OrchestrationConfig(BaseModel):
    """The four tuning knobs + a free-text directive."""

    sector_bias: dict[str, float] = Field(default_factory=dict)
    """Sector name -> relative weight. Higher = more videos about it."""
    type_mix: dict[str, float] = Field(default_factory=dict)
    """Format name -> relative weight in the fill mix."""
    weekly_volume: int = 5
    cadence_days: int = 1
    series: list[Series] = Field(default_factory=list)
    free_text_directive: str = ""
    updated_at: str = Field(default_factory=_now)

    def active_series(self) -> list[Series]:
        return [s for s in self.series if s.active]


# Container models for the JSON files (so we can carry metadata alongside lists).

class Plan(BaseModel):
    items: list[PlannedVideo] = Field(default_factory=list)
    generated_at: str = Field(default_factory=_now)


class DebtFile(BaseModel):
    commitments: list[Commitment] = Field(default_factory=list)
    updated_at: str = Field(default_factory=_now)

    def open(self) -> list[Commitment]:
        return [c for c in self.commitments if c.status == "open"]
