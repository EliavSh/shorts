"""Pydantic schemas for the FastAPI layer."""
from typing import Optional

from pydantic import BaseModel, Field


class Listing(BaseModel):
    id: str
    title: Optional[str] = None
    address: Optional[str] = None
    city: Optional[str] = None
    neighborhood: Optional[str] = None
    rooms: Optional[float] = None
    sqm: Optional[float] = None
    floor: Optional[int] = None
    price: Optional[int] = None
    price_per_sqm: Optional[float] = None
    url: Optional[str] = None
    posted_at: Optional[str] = None
    lat: Optional[float] = None
    lon: Optional[float] = None
    is_active: Optional[bool] = None
    first_seen: Optional[str] = None
    last_seen: Optional[str] = None
    is_new_construction: Optional[bool] = None
    has_balcony: Optional[bool] = None
    direction: Optional[str] = None
    deal_type: Optional[str] = None
    vaad_bayit: Optional[int] = None
    arnona: Optional[int] = None
    has_elevator: Optional[bool] = None
    has_parking: Optional[bool] = None
    has_mamad: Optional[bool] = None
    property_condition: Optional[int] = None


class ListingScore(BaseModel):
    listing_id: str
    gap_percent: Optional[float] = None
    nadlan_median_ppsqm: Optional[float] = None
    percentile_rank: Optional[float] = None
    z_score: Optional[float] = None
    motivation_score: Optional[float] = None
    value_add_gap: Optional[float] = None
    days_on_market: Optional[int] = None
    n_cohort_sales: Optional[int] = None


class ListingWithScore(Listing):
    score: Optional[ListingScore] = None


class Transaction(BaseModel):
    id: str
    address: Optional[str] = None
    city: Optional[str] = None
    rooms: Optional[float] = None
    sqm: Optional[float] = None
    price: Optional[int] = None
    date: Optional[str] = None
    lat: Optional[float] = None
    lon: Optional[float] = None


class PercentileScope(BaseModel):
    """One scope of the dual-percentile pair."""

    percentile: float
    n_sales: int
    median_price: float
    p25: float
    p75: float
    scope: str
    label: str


class PercentileResponse(BaseModel):
    """Dual percentile + interpretive metadata.

    `near` is the street-level cohort (building → street_block → street, no
    city fallback). `area` is the same-city, same-rooms-bucket cohort over
    the last 18 months. Either can be None when its threshold isn't met.
    """

    near: PercentileScope | None = None
    area: PercentileScope | None = None
    cohort_points: list[tuple[float, float]] = Field(default_factory=list)


class ScrapeGraphPoint(BaseModel):
    date: str
    added: int
    removed: int
    active: int


class DealCard(BaseModel):
    listing: Listing
    score: ListingScore
    explanation: str


class GpsPing(BaseModel):
    lat: float
    lon: float
    accuracy: Optional[float] = None
    timestamp: Optional[str] = None
