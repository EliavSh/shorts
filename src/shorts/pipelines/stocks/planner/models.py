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
PlanSource = Literal["planner", "debt", "series", "earnings", "idea"]
CommitmentStatus = Literal["open", "scheduled", "fulfilled"]
IdeaStatus = Literal["open", "done"]

# Maps the internal plan `source` to the editorial content lane shown in the UI.
CONTENT_KIND_BY_SOURCE: dict[str, str] = {
    "planner": "news",
    "idea": "evergreen",
    "series": "series",
    "earnings": "earnings",
    "debt": "commitment",
}


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

    @property
    def content_kind(self) -> str:
        """Editorial lane this item belongs to (news / evergreen / series /
        earnings / commitment) — derived from `source`, no stored field."""
        return CONTENT_KIND_BY_SOURCE.get(self.source, "news")


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
    daily_target: int = 3
    """How many clips to stage per day (the daily batch the dashboard shows)."""
    weekly_volume: int = 3  # legacy alias; daily_target is the active knob
    cadence_days: int = 1
    auto_publish: bool = True
    """When true, each rendered clip is uploaded to YouTube automatically (no
    manual review). Set false to keep clips staged in the dashboard instead."""
    publish_privacy: str = "public"
    """YouTube privacy for auto-published clips: public | unlisted | private."""
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


class IdeaItem(BaseModel):
    """A user-written evergreen topic prompt, parked until fired on demand."""

    id: str = Field(default_factory=_new_id)
    prompt: str
    status: IdeaStatus = "open"
    created_at: str = Field(default_factory=_now)
    rendered_slug: str | None = None  # slug of the clip this idea produced


class IdeaFile(BaseModel):
    items: list[IdeaItem] = Field(default_factory=list)
    updated_at: str = Field(default_factory=_now)

    def open(self) -> list[IdeaItem]:
        return [i for i in self.items if i.status == "open"]


class Strategy(BaseModel):
    """Channel strategist output — what the audience-aware critic recommends.

    `directive` is advisory (shown on the Plan page). `cooldown_tickers` is the
    concrete soft-nudge: the planner adds them to the recently-used set so they're
    avoided in selection (a genuinely news-hot one can still break through)."""

    directive: str = ""
    cooldown_tickers: list[str] = Field(default_factory=list)
    cooldown_sectors: list[str] = Field(default_factory=list)
    favor_sectors: list[str] = Field(default_factory=list)
    top_performers: list[str] = Field(default_factory=list)
    sample_size: int = 0
    computed_at: str = ""
