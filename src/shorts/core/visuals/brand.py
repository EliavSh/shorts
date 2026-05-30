"""Brand config loader — pipeline-agnostic.

Each pipeline supplies its own config_dir + brand yaml file. The loader is
shared so brawl can use it too if it wants brand-config-driven captions.
"""
from __future__ import annotations

from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import Literal

import yaml

from shorts.config import REPO_ROOT


@dataclass(frozen=True)
class TickerCardStyle:
    width: int
    height: int
    position: tuple[int, int]
    background: str
    background_opacity: float
    corner_radius: int
    accent_up: str
    accent_down: str
    text_primary: str
    text_secondary: str


@dataclass(frozen=True)
class CaptionsStyle:
    font_size: int
    position_y_pct: float
    text_color: str
    pill_color: str
    pill_opacity: float
    pill_padding_x: int
    pill_padding_y: int
    pill_corner_radius: int
    max_lines: int
    max_chars_per_line: int


@dataclass(frozen=True)
class DisclaimerStyle:
    text: str
    font_size: int
    text_color: str
    background: str
    background_opacity: float
    position_y_pct: float
    height: int


@dataclass(frozen=True)
class Brand:
    lang: str
    direction: Literal["rtl", "ltr"]
    font_family: str
    font_path: Path
    font_path_regular: Path
    ticker_card: TickerCardStyle
    captions: CaptionsStyle
    disclaimer: DisclaimerStyle
    cta_text: str


@lru_cache(maxsize=4)
def load_brand(lang: str, config_dir: Path | None = None, asset_root: Path | None = None) -> Brand:
    """Load brand_<lang>.yaml from `config_dir` (default: <project>/config/).

    Font paths inside the yaml are resolved relative to `asset_root`
    (default: project root). Callers from a pipeline typically pass their
    pipeline's config dir.
    """
    config_dir = config_dir or (REPO_ROOT / "config")
    asset_root = asset_root or REPO_ROOT
    cfg_path = config_dir / f"brand_{lang}.yaml"
    if not cfg_path.exists():
        raise FileNotFoundError(f"No brand config for lang={lang!r} at {cfg_path}")
    cfg = yaml.safe_load(cfg_path.read_text(encoding="utf-8"))
    return Brand(
        lang=cfg["lang"],
        direction=cfg["direction"],
        font_family=cfg["font_family"],
        font_path=asset_root / cfg["font_path"],
        font_path_regular=asset_root / cfg["font_path_regular"],
        ticker_card=TickerCardStyle(**{
            **cfg["ticker_card"],
            "position": tuple(cfg["ticker_card"]["position"]),
        }),
        captions=CaptionsStyle(**cfg["captions"]),
        disclaimer=DisclaimerStyle(**cfg["disclaimer"]),
        cta_text=cfg["cta"]["text"],
    )


def hex_to_rgba(hex_color: str, opacity: float = 1.0) -> tuple[int, int, int, int]:
    h = hex_color.lstrip("#")
    r, g, b = int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16)
    return (r, g, b, int(round(opacity * 255)))
