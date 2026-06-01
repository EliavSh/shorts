"""Ticker-card scheduling (non-overlap) + rendering (name fit) tests."""
from __future__ import annotations

from shorts.pipelines.stocks.formats._shared import BeatTiming, ticker_runs
from shorts.pipelines.stocks.script.schemas import Beat


def _timings(focuses: list[str | None], step: float = 10.0) -> list[BeatTiming]:
    out = []
    for i, f in enumerate(focuses):
        out.append(BeatTiming(
            beat=Beat(narration="x" * 10, role="body", ticker_focus=f),
            start_s=i * step, end_s=(i + 1) * step,
        ))
    return out


def _no_overlap(runs) -> bool:
    runs = sorted(runs, key=lambda r: r[1])
    return all(runs[i][2] <= runs[i + 1][1] + 1e-9 for i in range(len(runs) - 1))


def test_runs_contiguous() -> None:
    runs = ticker_runs(_timings(["NVDA", "NVDA", "TSM", "TSM"]))
    assert [(r[0]) for r in runs] == ["NVDA", "TSM"]
    assert runs[0] == ("NVDA", 0.0, 20.0)
    assert runs[1] == ("TSM", 20.0, 40.0)
    assert _no_overlap(runs)


def test_runs_interleaved_no_overlap() -> None:
    # The old find_beats_for_ticker spanned NVDA 0..50 (enclosing TSM) → overlap.
    runs = ticker_runs(_timings(["NVDA", "TSM", "NVDA"]))
    assert [r[0] for r in runs] == ["NVDA", "TSM", "NVDA"]
    assert _no_overlap(runs)


def test_runs_none_gap_is_handoff() -> None:
    # A focus change with a None (pivot) beat in between → the None beat is a gap.
    runs = ticker_runs(_timings(["NVDA", None, "TSM"]))
    assert [r[0] for r in runs] == ["NVDA", "TSM"]
    assert runs[0] == ("NVDA", 0.0, 10.0)
    assert runs[1] == ("TSM", 20.0, 30.0)  # the middle (10-20) is left as a gap
    assert _no_overlap(runs)


def test_runs_none_absorbed_when_same_ticker() -> None:
    # NVDA, (gap), NVDA → one continuous run so the card doesn't flicker off.
    runs = ticker_runs(_timings(["NVDA", None, "NVDA"]))
    assert runs == [("NVDA", 0.0, 30.0)]


def test_long_name_fits_card() -> None:
    from shorts.pipelines.stocks.visuals.brand import load_brand
    from shorts.pipelines.stocks.visuals.ticker_card import render_ticker_card

    brand = load_brand("en")
    # Must not raise and must produce the right size for a very long name.
    img = render_ticker_card(brand=brand, ticker="TSM",
                             name="Taiwan Semiconductor Manufacturing Company Limited",
                             change_pct=1.8)
    assert img.size == (brand.ticker_card.width, brand.ticker_card.height)


def test_name_autofit_wraps_within_width() -> None:
    from PIL import Image, ImageDraw

    from shorts.pipelines.stocks.visuals.brand import load_brand
    from shorts.pipelines.stocks.visuals.ticker_card import _fit_name

    brand = load_brand("en")
    max_w = brand.ticker_card.width - 64
    draw = ImageDraw.Draw(Image.new("RGBA", (10, 10)))
    font, lines = _fit_name(draw, "Taiwan Semiconductor Manufacturing",
                            str(brand.font_path_regular), max_w)
    assert 1 <= len(lines) <= 2
    for ln in lines:
        assert draw.textlength(ln, font=font) <= max_w
