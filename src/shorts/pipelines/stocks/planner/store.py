"""JSON persistence for the planner — plan.json, debt.json, orchestration.json
under data/stocks/. Mirrors core/reviews/distill.py's load/save pattern so the
files live on the Fly volume.
"""
from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path

from shorts.config import pipeline_data_dir

from .models import DebtFile, IdeaFile, OrchestrationConfig, Plan

_PIPELINE = "stocks"


def _path(name: str) -> Path:
    return pipeline_data_dir(_PIPELINE) / name


def _read(path: Path) -> dict | None:
    if not path.exists():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return None


def _write(path: Path, model) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(model.model_dump_json(indent=2), encoding="utf-8")


# ── Plan ──────────────────────────────────────────────────────────────────

def load_plan() -> Plan:
    data = _read(_path("plan.json"))
    return Plan.model_validate(data) if data else Plan()


def save_plan(plan: Plan) -> None:
    plan.generated_at = datetime.now().isoformat(timespec="seconds")
    _write(_path("plan.json"), plan)


# ── Debt ──────────────────────────────────────────────────────────────────

def load_debt() -> DebtFile:
    data = _read(_path("debt.json"))
    return DebtFile.model_validate(data) if data else DebtFile()


def save_debt(debt: DebtFile) -> None:
    debt.updated_at = datetime.now().isoformat(timespec="seconds")
    _write(_path("debt.json"), debt)


# ── Idea backlog ────────────────────────────────────────────────────────────

def load_ideas() -> IdeaFile:
    data = _read(_path("ideas.json"))
    return IdeaFile.model_validate(data) if data else IdeaFile()


def save_ideas(ideas: IdeaFile) -> None:
    ideas.updated_at = datetime.now().isoformat(timespec="seconds")
    _write(_path("ideas.json"), ideas)


# ── Orchestration config ────────────────────────────────────────────────────

def load_config() -> OrchestrationConfig:
    data = _read(_path("orchestration.json"))
    return OrchestrationConfig.model_validate(data) if data else OrchestrationConfig()


def save_config(cfg: OrchestrationConfig) -> None:
    cfg.updated_at = datetime.now().isoformat(timespec="seconds")
    _write(_path("orchestration.json"), cfg)
