"""JSON-file ReviewStore. One state.json per item under data/<pipeline>/output/<run_id>/.

The store is pipeline-aware via constructor injection: each pipeline's
dashboard router (or adapter) instantiates `ReviewStore(pipeline="brawl")` and
shares it with its routes.
"""
from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path

from shorts.config import pipeline_data_dir

from .schema import Comment, ReviewItem, Version, latest_version


def _now() -> str:
    return datetime.now().isoformat(timespec="seconds")


class ReviewStore:
    def __init__(self, pipeline: str):
        self.pipeline = pipeline
        self.output_root = pipeline_data_dir(pipeline) / "output"
        self.output_root.mkdir(parents=True, exist_ok=True)

    # ---- paths -----------------------------------------------------------

    def state_path(self, run_id: str) -> Path:
        return self.output_root / run_id / "state.json"

    def version_dir(self, run_id: str, v: int) -> Path:
        return self.output_root / run_id / f"v{v}"

    def short_path(self, run_id: str, v: int) -> Path:
        return self.version_dir(run_id, v) / "short.mp4"

    # ---- IO --------------------------------------------------------------

    def save(self, item: ReviewItem) -> None:
        item.updated_at = _now()
        item.pipeline = self.pipeline
        p = self.state_path(item.run_id)
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(
            json.dumps(item.to_dict(), indent=2, ensure_ascii=False),
            encoding="utf-8",
        )

    def load(self, run_id: str) -> ReviewItem | None:
        p = self.state_path(run_id)
        if not p.exists():
            return None
        data = json.loads(p.read_text(encoding="utf-8"))
        data["versions"] = [Version(**v) for v in data.get("versions", [])]
        data["comments"] = [Comment(**c) for c in data.get("comments", [])]
        # Older state files won't have `pipeline` — backfill.
        data.setdefault("pipeline", self.pipeline)
        return ReviewItem(**data)

    def list_items(self) -> list[ReviewItem]:
        items: list[ReviewItem] = []
        if not self.output_root.exists():
            return items
        for d in sorted(self.output_root.iterdir(), reverse=True):
            if not d.is_dir():
                continue
            item = self.load(d.name)
            if item:
                items.append(item)
        return items

    # ---- convenience -----------------------------------------------------

    def latest_version(self, item: ReviewItem) -> Version | None:
        return latest_version(item)

    def add_comment(self, run_id: str, text: str) -> ReviewItem | None:
        item = self.load(run_id)
        if item is None:
            return None
        item.comments.append(
            Comment(text=text, version_at_time=item.current_version, created_at=_now())
        )
        item.status = "processing"
        self.save(item)
        return item

    def mark_status(self, run_id: str, status: str) -> None:
        item = self.load(run_id)
        if item is None:
            return
        item.status = status
        self.save(item)
