"""Tests for the generated graphics module."""
from pathlib import Path

from PIL import Image

from shorts.pipelines.stocks.visuals.brand import load_brand
from shorts.core.visuals.graphics import GraphicSpec, render


def test_all_kinds_render(tmp_path: Path) -> None:
    brand = load_brand("en")
    specs = [
        GraphicSpec(kind="date_card",
                    params={"year": 2026, "month": 6, "day": 17, "subtitle": "Fed decision"}),
        GraphicSpec(kind="number_callout",
                    params={"number": "$3.2B", "label": "Investment", "direction": "up"}),
        GraphicSpec(kind="bar_compare",
                    params={"title": "Q3 vs Q2", "bars": [{"label": "Q2", "value": 76.4},
                                                          {"label": "Q3", "value": 81.6}],
                            "unit": "B"}),
        GraphicSpec(kind="mini_chart",
                    params={"title": "Run", "line": [80, 85, 90, 100, 115], "label_end": "+44%",
                            "direction": "up"}),
    ]
    for spec in specs:
        p = render(spec, brand=brand, out_dir=tmp_path)
        assert p.exists()
        with Image.open(p) as im:
            assert im.size == (1080, 1920), f"{spec.kind} not 9:16"


def test_unknown_kind_raises(tmp_path: Path) -> None:
    import pytest
    brand = load_brand("en")
    with pytest.raises(ValueError):
        render(GraphicSpec(kind="nonsense", params={}), brand=brand, out_dir=tmp_path)
