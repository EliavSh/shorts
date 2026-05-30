"""brawl pipeline config — thin wrapper over shorts.config that resolves
yaml files relative to config/brawl/ rather than the top-level config/.
"""
from __future__ import annotations

from pathlib import Path
from typing import Any

from shorts.config import (
    CONFIG_DIR,
    REPO_ROOT,
    Secrets,
    load_secrets,
    load_yaml as _load_yaml_path,
    pipeline_data_dir,
)

BRAWL_CONFIG_DIR = CONFIG_DIR / "brawl"
DATA_DIR = pipeline_data_dir("brawl")

__all__ = [
    "BRAWL_CONFIG_DIR",
    "DATA_DIR",
    "REPO_ROOT",
    "Secrets",
    "load_secrets",
    "load_yaml",
]


def load_yaml(name: str) -> dict[str, Any]:
    """Load a yaml file by name from config/brawl/."""
    path = BRAWL_CONFIG_DIR / name
    return _load_yaml_path(path)
