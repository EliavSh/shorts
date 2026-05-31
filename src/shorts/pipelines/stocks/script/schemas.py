"""Script schemas — flexible structure that supports multiple video formats.

The two key design choices:
- `format` is a string (not Literal) so adding formats doesn't break the schema —
  validation happens via the format registry.
- `beats` is a flat ordered list; each beat carries an optional `role` so visual
  templates can recognise hooks, CTAs, pivots, etc. without the schema knowing
  about specific formats.
"""
from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field, field_validator


BeatRole = Literal["hook", "body", "pivot", "cta"]


class TickerSpec(BaseModel):
    """A stock the video is about.

    `ohlc_30d` is optional and may be populated by the topic picker so the
    composer can draw a real candlestick chart in the ticker card.
    """

    ticker: str = Field(..., pattern=r"^[A-Z0-9\.\-]{1,12}$")
    name: str = Field(..., min_length=2, max_length=80)
    change_pct: float = Field(..., ge=-100, le=1000)
    price: float | None = None
    ohlc_30d: list[tuple[float, float, float, float]] = Field(default_factory=list)


class Beat(BaseModel):
    """One narrative beat."""

    narration: str = Field(..., min_length=2, max_length=400,
                           description="What the voice says for this beat.")
    caption: str | None = Field(
        default=None, max_length=200,
        description="Optional shortened caption. When absent, the composer derives "
                    "rolling captions from the TTS word timings instead.",
    )
    visual_tags: list[str] = Field(default_factory=list, max_length=4)
    role: BeatRole | None = None
    ticker_focus: str | None = Field(
        default=None,
        description="Optional ticker symbol this beat is 'about'. Visual templates "
                    "use this to show a matching ticker card alongside the beat.",
    )
    hook_pattern: str | None = Field(
        default=None,
        description="When role='hook', which pattern from the library was used "
                    "(e.g. concrete_surprise, numeric_punch). For analytics.",
    )

    @field_validator("visual_tags")
    @classmethod
    def _lower_tags(cls, v: list[str]) -> list[str]:
        return [t.strip().lower() for t in v if t.strip()]


class Script(BaseModel):
    """A complete short-form video script. Format-agnostic at the schema layer."""

    lang: Literal["he", "en"]
    format: str = Field(..., description="Name of a registered format in stocksreels.formats.")
    title: str = Field(..., min_length=5, max_length=110)
    description_hashtags: list[str] = Field(default_factory=list, max_length=12)
    tickers: list[TickerSpec] = Field(default_factory=list, max_length=6)
    target_seconds: int = Field(
        default=120, ge=60, le=180,
        description="Intended spoken length of the video. The writer chooses this "
                    "within the format's length band based on how much substance the "
                    "topic has. Recorded for the composer and analytics; narration is "
                    "written to this budget (~2.7 words/sec).",
    )
    beats: list[Beat] = Field(..., min_length=2, max_length=24)

    def narration_text(self) -> str:
        return " ".join(b.narration.strip() for b in self.beats if b.narration.strip())

    def beat_by_role(self, role: BeatRole) -> Beat | None:
        for b in self.beats:
            if b.role == role:
                return b
        return None

    def beats_with_role(self, role: BeatRole) -> list[Beat]:
        return [b for b in self.beats if b.role == role]

    def ticker(self, symbol: str) -> TickerSpec | None:
        for t in self.tickers:
            if t.ticker.upper() == symbol.upper():
                return t
        return None


# ─────────────────────────────────────────────────────────────────────────────
# Topic context — input to the script writer
# ─────────────────────────────────────────────────────────────────────────────

class CausalLink(BaseModel):
    """A known causal relationship between two tickers (supply chain, competitor,
    macro link). The writer may use this if it picks a multi-stock format."""

    from_ticker: str
    to_ticker: str
    reason: str


class TickerSnapshot(BaseModel):
    """A market snapshot of one ticker, with optional news for context."""

    ticker: str
    name: str
    change_pct: float
    price: float | None = None
    volume: int | None = None
    market_cap: float | None = None
    sector: str | None = None
    industry: str | None = None
    ohlc_30d: list[tuple[float, float, float, float]] = Field(default_factory=list)
    headlines: list[str] = Field(default_factory=list, max_length=8)


class TopicContext(BaseModel):
    """Everything the script writer needs to choose a format and write."""

    lang: Literal["he", "en"]
    candidates: list[TickerSnapshot] = Field(..., min_length=1, max_length=10,
                                             description="Tickers ranked by interestingness.")
    suggested_links: list[CausalLink] = Field(default_factory=list,
                                              description="Known causal connections among candidates.")
    macro_notes: str | None = Field(
        default=None,
        description="Optional context the writer should keep in mind (e.g. 'Fed meeting today').",
    )
