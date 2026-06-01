"""Published ledger — the durable "trace" kept after a clip's heavy artifacts
are purged on upload.

When a clip is published (unlisted) to YouTube the mp4/frames/audio under
data/stocks/output/<slug>/ are deleted, but one small line is appended here so
the planner and the stats page still know what sector/format/tickers were
covered. Lives at data/stocks/published.json on the Fly volume, next to
plan.json / debt.json / orchestration.json.
"""
from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path

from pydantic import BaseModel, Field

from shorts.config import pipeline_data_dir

_PIPELINE = "stocks"


# Coarse, offline ticker -> sector map over the render universe. Keeps the stats
# page deterministic without a yfinance call at publish time. Unknown tickers
# fall back to "Other".
_SECTOR_MAP: dict[str, str] = {
    # Semiconductors
    "NVDA": "Semiconductors", "AMD": "Semiconductors", "INTC": "Semiconductors",
    "TSM": "Semiconductors", "AVGO": "Semiconductors", "QCOM": "Semiconductors",
    "MU": "Semiconductors", "ASML": "Semiconductors", "AMAT": "Semiconductors",
    "LRCX": "Semiconductors",
    # Mega-cap tech / software
    "AAPL": "Tech", "MSFT": "Tech", "GOOGL": "Tech", "META": "Tech",
    "AMZN": "Tech", "TSLA": "Tech", "NFLX": "Tech", "ORCL": "Tech",
    "CRM": "Tech", "ADBE": "Tech",
    # Financials
    "JPM": "Financials", "BAC": "Financials", "GS": "Financials",
    "MS": "Financials", "WFC": "Financials", "C": "Financials",
    # Energy
    "XOM": "Energy", "CVX": "Energy", "COP": "Energy", "OXY": "Energy",
    # Healthcare / pharma
    "PFE": "Healthcare", "MRK": "Healthcare", "LLY": "Healthcare",
    "JNJ": "Healthcare", "ABBV": "Healthcare",
    # Consumer
    "DIS": "Consumer", "NKE": "Consumer", "MCD": "Consumer", "SBUX": "Consumer",
    "WMT": "Consumer", "COST": "Consumer", "TGT": "Consumer", "HD": "Consumer",
    # Industrials
    "BA": "Industrials", "GE": "Industrials", "CAT": "Industrials", "DE": "Industrials",
    # Crypto-adjacent
    "COIN": "Crypto", "MSTR": "Crypto",
}


def sector_for(ticker: str) -> str:
    return _SECTOR_MAP.get((ticker or "").upper(), "Other")


class PublishedEntry(BaseModel):
    slug: str
    title: str = ""
    format: str = ""
    tickers: list[str] = Field(default_factory=list)
    sector: str = "Other"
    youtube_id: str = ""
    youtube_url: str = ""
    published_at: str = ""
    cost_usd: float | None = None


class PublishedLedger(BaseModel):
    entries: list[PublishedEntry] = Field(default_factory=list)


def _path() -> Path:
    return pipeline_data_dir(_PIPELINE) / "published.json"


def load_published() -> PublishedLedger:
    p = _path()
    if not p.exists():
        return PublishedLedger()
    try:
        return PublishedLedger.model_validate_json(p.read_text(encoding="utf-8"))
    except Exception:
        return PublishedLedger()


def record_published(
    *,
    slug: str,
    title: str = "",
    fmt: str = "",
    tickers: list[str] | None = None,
    youtube_id: str = "",
    youtube_url: str = "",
    cost_usd: float | None = None,
) -> PublishedEntry:
    """Append one entry to the ledger and persist it. Sector is derived from the
    first ticker via the static map."""
    tickers = [t.upper() for t in (tickers or [])]
    entry = PublishedEntry(
        slug=slug,
        title=title,
        format=fmt,
        tickers=tickers,
        sector=sector_for(tickers[0]) if tickers else "Other",
        youtube_id=youtube_id,
        youtube_url=youtube_url,
        published_at=datetime.now().isoformat(timespec="seconds"),
        cost_usd=cost_usd,
    )
    ledger = load_published()
    ledger.entries.append(entry)
    p = _path()
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(ledger.model_dump(), indent=2, ensure_ascii=False), encoding="utf-8")
    return entry
