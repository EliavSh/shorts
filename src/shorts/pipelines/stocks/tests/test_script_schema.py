from pathlib import Path

import pytest
from pydantic import ValidationError

from shorts.pipelines.stocks.script.schemas import Script
from shorts.pipelines.stocks.script.writer import write_script_from_fixture

FIX_DIR = Path(__file__).parent / "fixtures"


def test_two_story_pivot_fixture_validates() -> None:
    s = write_script_from_fixture(FIX_DIR / "script_nvda_tsmc_en.json")
    assert isinstance(s, Script)
    assert s.format == "two_story_pivot"
    assert s.lang == "en"
    assert [t.ticker for t in s.tickers] == ["NVDA", "TSM"]


def test_beat_roles_and_order() -> None:
    s = write_script_from_fixture(FIX_DIR / "script_nvda_tsmc_en.json")
    roles = [b.role for b in s.beats]
    assert roles[0] == "hook"
    assert roles[-1] == "cta"
    assert "pivot" in roles


def test_narration_word_count() -> None:
    s = write_script_from_fixture(FIX_DIR / "script_nvda_tsmc_en.json")
    word_count = len(s.narration_text().split())
    # English target: ~150 words for 55-58s at ~2.7 wps. Allow a generous window.
    assert 110 <= word_count <= 200, f"got {word_count} words"


def test_unknown_format_raises() -> None:
    bad_path = FIX_DIR / "bad_unknown_format.json"
    bad_path.write_text(
        '{"lang":"en","format":"nonsense","title":"x x x x x","tickers":[],'
        '"beats":[{"narration":"a a"},{"narration":"b b"}]}',
        encoding="utf-8",
    )
    try:
        with pytest.raises((ValidationError, ValueError, KeyError)):
            write_script_from_fixture(bad_path)
    finally:
        bad_path.unlink()


def test_format_ticker_count_enforced() -> None:
    """deep_dive_one_stock with two tickers should fail."""
    bad_path = FIX_DIR / "bad_too_many_tickers.json"
    bad_path.write_text(
        '{"lang":"en","format":"deep_dive_one_stock","title":"x x x x x",'
        '"tickers":[{"ticker":"NVDA","name":"Nvidia","change_pct":1},'
        '{"ticker":"TSM","name":"TSMC","change_pct":1}],'
        '"beats":[{"narration":"a a"},{"narration":"b b"}]}',
        encoding="utf-8",
    )
    try:
        with pytest.raises(ValueError):
            write_script_from_fixture(bad_path)
    finally:
        bad_path.unlink()
