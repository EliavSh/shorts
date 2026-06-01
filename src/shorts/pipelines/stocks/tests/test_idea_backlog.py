"""Unit tests for the evergreen idea backlog + content-kind breakdown."""
from __future__ import annotations

from datetime import date

from shorts.pipelines.stocks.planner.models import (
    IdeaFile, IdeaItem, PlannedVideo, TopicSeed,
)


def test_content_kind_mapping() -> None:
    mk = lambda src: PlannedVideo(scheduled_for=date.today(), source=src).content_kind
    assert mk("planner") == "news"
    assert mk("idea") == "evergreen"
    assert mk("series") == "series"
    assert mk("earnings") == "earnings"
    assert mk("debt") == "commitment"


def test_ideafile_open_and_roundtrip() -> None:
    f = IdeaFile(items=[
        IdeaItem(prompt="Explain the chip supply chain"),
        IdeaItem(prompt="How the Fed sets rates", status="done", rendered_slug="x_en"),
    ])
    assert [i.prompt for i in f.open()] == ["Explain the chip supply chain"]
    # JSON round-trip preserves status + rendered_slug.
    f2 = IdeaFile.model_validate_json(f.model_dump_json())
    assert len(f2.items) == 2
    assert f2.items[1].status == "done"
    assert f2.items[1].rendered_slug == "x_en"


def test_store_ideas_roundtrip(tmp_path, monkeypatch) -> None:
    from shorts.pipelines.stocks.planner import store as ps

    monkeypatch.setattr(ps, "_path", lambda name: tmp_path / name)
    assert ps.load_ideas().items == []  # missing file → empty
    f = IdeaFile(items=[IdeaItem(prompt="Buybacks 101")])
    ps.save_ideas(f)
    assert (tmp_path / "ideas.json").exists()
    loaded = ps.load_ideas()
    assert [i.prompt for i in loaded.items] == ["Buybacks 101"]


def test_build_context_for_theme_only_no_tickers() -> None:
    # An evergreen idea has no tickers — context must still build (MKT placeholder)
    # and carry the prompt in macro_notes. No network: the ticker loop is empty.
    from shorts.pipelines.stocks.data import topic_picker

    ctx = topic_picker.build_context_for([], theme="Explain the chip supply chain")
    assert ctx is not None
    assert len(ctx.candidates) == 1
    assert ctx.candidates[0].ticker == "MKT"
    assert "chip supply chain" in (ctx.macro_notes or "")
