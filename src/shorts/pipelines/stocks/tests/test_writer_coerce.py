"""Unit tests for writer payload coercion — over-generated list fields should be
trimmed before validation rather than crashing the render."""
from __future__ import annotations

from shorts.pipelines.stocks.script import writer as W
from shorts.pipelines.stocks.script.schemas import Script


def _payload(**over):
    base = {
        "lang": "en",
        "format": "deep_dive_one_stock",
        "title": "Why Oracle jumped 14% today",
        "description_hashtags": ["ORCL", "Oracle", "stocks", "Shorts"],
        "tickers": [{"ticker": "ORCL", "name": "Oracle", "change_pct": 14.0}],
        "target_seconds": 90,
        "beats": [
            {"narration": "Oracle jumped 14% today.", "role": "hook"},
            {"narration": "Cloud revenue beat expectations.", "role": "body"},
        ],
    }
    base.update(over)
    return base


def test_coerce_trims_excess_hashtags() -> None:
    p = _payload(description_hashtags=[f"tag{i}" for i in range(14)])
    W._coerce_payload(p)
    assert len(p["description_hashtags"]) == 12
    # And the trimmed payload now validates cleanly.
    Script.model_validate(p)


def test_coerce_trims_excess_tickers_and_beats() -> None:
    p = _payload(
        tickers=[{"ticker": f"T{i}", "name": f"N{i}", "change_pct": 1.0} for i in range(9)],
        beats=[{"narration": f"Beat {i} text.", "role": "body"} for i in range(30)],
    )
    W._coerce_payload(p)
    assert len(p["tickers"]) == 6
    assert len(p["beats"]) == 24
    Script.model_validate(p)


def test_coerce_trims_beat_visual_tags() -> None:
    p = _payload(beats=[
        {"narration": "Hook line here.", "role": "hook",
         "visual_tags": ["a", "b", "c", "d", "e", "f"]},
        {"narration": "Body line here.", "role": "body"},
    ])
    W._coerce_payload(p)
    assert len(p["beats"][0]["visual_tags"]) == 4


def test_coerce_noop_when_within_limits() -> None:
    p = _payload()
    before = {k: list(v) if isinstance(v, list) else v for k, v in p.items()}
    W._coerce_payload(p)
    assert p["description_hashtags"] == before["description_hashtags"]
    assert len(p["tickers"]) == 1
