"""Format registry — each format is a strategy that knows how to write & render
one kind of finance Short. Adding a new format is one new module that defines
`SPEC` and `add_overlays(...)`.

Formats are auto-imported here so they self-register on package load.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol

from moviepy import ImageClip

from ..script.schemas import Script
from shorts.core.visuals.brand import Brand
from ..voice.tts import TTSResult


@dataclass(frozen=True)
class FormatSpec:
    name: str
    description: str
    """One-line description for the format menu the LLM sees."""
    prompt_addendum: str
    """Additional rules specific to this format, appended to the system prompt
    after the writer selects this format. Markdown OK."""
    min_tickers: int
    max_tickers: int


class AddOverlaysFn(Protocol):
    def __call__(
        self,
        *,
        script: Script,
        tts: TTSResult,
        brand: Brand,
        total_duration_s: float,
    ) -> list[ImageClip]:
        ...


_SPECS: dict[str, FormatSpec] = {}
_OVERLAYS: dict[str, AddOverlaysFn] = {}


def register(spec: FormatSpec, overlays_fn: AddOverlaysFn) -> None:
    if spec.name in _SPECS:
        raise ValueError(f"format already registered: {spec.name}")
    _SPECS[spec.name] = spec
    _OVERLAYS[spec.name] = overlays_fn


def get_spec(name: str) -> FormatSpec:
    if name not in _SPECS:
        raise KeyError(
            f"unknown format {name!r}. Registered: {sorted(_SPECS)}"
        )
    return _SPECS[name]


def get_overlays_fn(name: str) -> AddOverlaysFn:
    return _OVERLAYS[name]


def list_specs() -> list[FormatSpec]:
    return sorted(_SPECS.values(), key=lambda s: s.name)


def render_format_menu_markdown() -> str:
    """Return a markdown bulleted list of all formats for prompt injection."""
    lines: list[str] = []
    for spec in list_specs():
        lines.append(f"- **{spec.name}** — {spec.description}")
    return "\n".join(lines)


# Self-register the built-in formats. New formats: drop a module here and add
# an import line below.
from . import deep_dive_one_stock  # noqa: E402,F401
from . import two_story_pivot  # noqa: E402,F401
