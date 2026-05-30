"""Stocks-pipeline-flavored brand loader.

Thin wrapper over shorts.core.visuals.brand.load_brand that points it at
config/stocks/brand_<lang>.yaml.
"""
from __future__ import annotations

from shorts.config import CONFIG_DIR, REPO_ROOT
from shorts.core.visuals.brand import (
    Brand,
    CaptionsStyle,
    DisclaimerStyle,
    TickerCardStyle,
    hex_to_rgba,
)
from shorts.core.visuals.brand import load_brand as _load_brand_core


def load_brand(lang: str) -> Brand:
    return _load_brand_core(
        lang,
        config_dir=CONFIG_DIR / "stocks",
        asset_root=REPO_ROOT,
    )


__all__ = [
    "Brand",
    "CaptionsStyle",
    "DisclaimerStyle",
    "TickerCardStyle",
    "hex_to_rgba",
    "load_brand",
]
