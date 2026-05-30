"""Shared settings + per-pipeline config loaders."""
from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml
from dotenv import load_dotenv

REPO_ROOT = Path(__file__).resolve().parents[2]
CONFIG_DIR = REPO_ROOT / "config"
DATA_DIR = REPO_ROOT / "data"


@dataclass(frozen=True)
class Secrets:
    """Convenience holder for the most-used keys. Pipelines may read others
    directly from os.environ."""
    anthropic_api_key: str
    youtube_api_key: str = ""


def _bootstrap_env() -> None:
    """Load .env once. override=True so .env beats stale shell vars."""
    load_dotenv(REPO_ROOT / ".env", override=True)


def load_secrets(*, require_anthropic: bool = True, require_youtube: bool = False) -> Secrets:
    _bootstrap_env()
    anthropic = os.environ.get("ANTHROPIC_API_KEY", "").strip()
    youtube = os.environ.get("YOUTUBE_API_KEY", "").strip()
    missing: list[str] = []
    if require_anthropic and not anthropic:
        missing.append("ANTHROPIC_API_KEY")
    if require_youtube and not youtube:
        missing.append("YOUTUBE_API_KEY")
    if missing:
        raise RuntimeError(
            "Missing required env var(s): "
            + ", ".join(missing)
            + ". Copy .env.example to .env and fill them in."
        )
    return Secrets(anthropic_api_key=anthropic, youtube_api_key=youtube)


def load_yaml(path: Path | str) -> dict[str, Any]:
    p = Path(path) if isinstance(path, str) else path
    with p.open("r", encoding="utf-8") as f:
        data = yaml.safe_load(f)
    if not isinstance(data, dict):
        raise ValueError(f"{p} must be a YAML mapping at the top level")
    return data


def load_pipeline_config(pipeline: str) -> dict[str, Any]:
    """Load config/<pipeline>.yaml merged on top of config/shared.yaml."""
    _bootstrap_env()
    base: dict[str, Any] = {}
    shared = CONFIG_DIR / "shared.yaml"
    if shared.exists():
        base = load_yaml(shared)
    pipeline_path = CONFIG_DIR / f"{pipeline}.yaml"
    if not pipeline_path.exists():
        raise FileNotFoundError(f"No config at {pipeline_path}")
    pipeline_cfg = load_yaml(pipeline_path)
    # Shallow merge: pipeline keys override shared.
    merged = {**base, **pipeline_cfg}
    return merged


def pipeline_data_dir(pipeline: str) -> Path:
    """Where this pipeline writes its data. data/<pipeline>/."""
    p = DATA_DIR / pipeline
    p.mkdir(parents=True, exist_ok=True)
    return p
