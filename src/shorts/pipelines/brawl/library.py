"""Source-video library for the brawl pipeline.

A persisted, dashboard-managed list of long-form videos the reviewer can
generate clips from. Two kinds of entries coexist:

  - source="manual": URLs the reviewer pinned by hand (e.g. world-championship
    VODs). Survive refreshes.
  - source="auto":   candidates pulled by `discover` ranking. Replaced wholesale
    on each refresh so the list stays fresh without piling up stale rows.

Backed by a single JSON file at data/brawl/library.json.
"""
from __future__ import annotations

import json
import re
from dataclasses import asdict, dataclass, field
from datetime import datetime
from pathlib import Path

from shorts.config import pipeline_data_dir

_LIBRARY_PATH = pipeline_data_dir("brawl") / "library.json"

_VID_RE = re.compile(r"(?:v=|youtu\.be/|/shorts/|/embed/)([A-Za-z0-9_-]{11})")


def parse_video_id(url_or_id: str) -> str | None:
    url_or_id = url_or_id.strip()
    m = _VID_RE.search(url_or_id)
    if m:
        return m.group(1)
    if re.fullmatch(r"[A-Za-z0-9_-]{11}", url_or_id):
        return url_or_id
    return None


@dataclass
class LibraryEntry:
    video_id: str
    url: str
    title: str
    channel: str = ""
    duration_s: int = 0
    source: str = "manual"          # "manual" | "auto"
    added_at: str = ""
    rationale: str = ""             # why discovery surfaced it (auto only)

    def to_dict(self) -> dict:
        return asdict(self)

    @property
    def duration_label(self) -> str:
        if not self.duration_s:
            return "?"
        h, rem = divmod(int(self.duration_s), 3600)
        m, s = divmod(rem, 60)
        if h:
            return f"{h}h{m:02d}m"
        return f"{m}m{s:02d}s" if m else f"{s}s"


@dataclass
class Library:
    entries: list[LibraryEntry] = field(default_factory=list)


def _now() -> str:
    return datetime.now().isoformat(timespec="seconds")


def load() -> Library:
    if not _LIBRARY_PATH.exists():
        return Library()
    try:
        data = json.loads(_LIBRARY_PATH.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return Library()
    return Library(entries=[LibraryEntry(**e) for e in data.get("entries", [])])


def save(lib: Library) -> None:
    _LIBRARY_PATH.parent.mkdir(parents=True, exist_ok=True)
    _LIBRARY_PATH.write_text(
        json.dumps({"entries": [e.to_dict() for e in lib.entries]}, indent=2, ensure_ascii=False),
        encoding="utf-8",
    )


def add_manual(url_or_id: str, *, title: str = "", channel: str = "", duration_s: int = 0) -> LibraryEntry | None:
    """Pin a URL by hand. De-dupes on video_id. Returns the entry (new or existing)."""
    vid = parse_video_id(url_or_id)
    if vid is None:
        return None
    lib = load()
    for e in lib.entries:
        if e.video_id == vid:
            return e  # already present
    entry = LibraryEntry(
        video_id=vid,
        url=f"https://www.youtube.com/watch?v={vid}",
        title=title or f"(video {vid})",
        channel=channel,
        duration_s=duration_s,
        source="manual",
        added_at=_now(),
    )
    lib.entries.insert(0, entry)
    save(lib)
    return entry


def remove(video_id: str) -> None:
    lib = load()
    lib.entries = [e for e in lib.entries if e.video_id != video_id]
    save(lib)


def replace_auto(entries: list[LibraryEntry]) -> None:
    """Swap out all auto entries for a fresh discovery batch; keep manual pins.
    Auto entries that duplicate a manual pin are skipped (manual wins)."""
    lib = load()
    manual = [e for e in lib.entries if e.source == "manual"]
    manual_ids = {e.video_id for e in manual}
    fresh_auto = [e for e in entries if e.video_id not in manual_ids]
    lib.entries = manual + fresh_auto
    save(lib)
