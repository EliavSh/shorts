"""Voice/CTA/inspector changes: fps, CTA via brand.cta_text, consistency critic."""
from __future__ import annotations

import types


def test_fps_is_30() -> None:
    from shorts.core.visuals import kenburns
    from shorts.pipelines.stocks.compose import composer
    assert composer.FPS == 30
    assert kenburns.FPS == 30


def test_cta_graphic_uses_brand_text() -> None:
    from shorts.core.visuals.graphics import follow_cta
    from shorts.pipelines.stocks.visuals.brand import load_brand

    brand = load_brand("en")
    assert "Subscribe" in brand.cta_text
    img = follow_cta.render(brand=brand)  # no headline → falls back to brand.cta_text
    assert img.size == (follow_cta.FRAME_W, follow_cta.FRAME_H)


def test_parse_issues_lenient() -> None:
    from shorts.pipelines.stocks.script.writer import _parse_issues
    assert _parse_issues('{"issues": ["says 12, names 4"]}') == ["says 12, names 4"]
    # tolerate prose around the JSON
    assert _parse_issues('Sure!\n{"issues": []}\nthanks') == []
    assert _parse_issues("not json") == []
    assert _parse_issues('{"issues": "oops"}') == []  # wrong type → []


class _FakeResp:
    def __init__(self, text: str):
        self.content = [types.SimpleNamespace(type="text", text=text)]


class _FakeClient:
    def __init__(self, text: str):
        self._text = text
        self.messages = types.SimpleNamespace(create=self._create)

    def _create(self, **kwargs):
        return _FakeResp(self._text)


def _script(beats):
    from shorts.pipelines.stocks.script.schemas import Beat, Script
    return Script(
        lang="en", format="story_telling", title="The chip supply chain explained",
        description_hashtags=["Shorts"], tickers=[], target_seconds=60,
        beats=[Beat(narration=n, role=r) for n, r in beats],
    )


def test_inspector_flags_mismatch() -> None:
    from shorts.pipelines.stocks.script.writer import _inspect_consistency
    script = _script([
        ("12 companies touch the chip before it reaches your phone.", "hook"),
        ("Start with ASML in the Netherlands.", "body"),
        ("Then TSMC fabs it in Taiwan.", "body"),
        ("Subscribe for your daily Market Minute.", "cta"),
    ])
    client = _FakeClient('{"issues": ["hook says 12 companies but body names only 2"]}')
    issues = _inspect_consistency(script, client=client, model="x")
    assert issues == ["hook says 12 companies but body names only 2"]


def test_inspector_clean_passes() -> None:
    from shorts.pipelines.stocks.script.writer import _inspect_consistency
    script = _script([
        ("Nvidia jumped 4% on AI demand.", "hook"),
        ("Data-center revenue led the move.", "body"),
        ("Subscribe for your daily Market Minute.", "cta"),
    ])
    client = _FakeClient('{"issues": []}')
    assert _inspect_consistency(script, client=client, model="x") == []


def test_inspector_fails_open() -> None:
    from shorts.pipelines.stocks.script.writer import _inspect_consistency

    class _Boom:
        def __init__(self):
            self.messages = types.SimpleNamespace(create=self._raise)

        def _raise(self, **kwargs):
            raise RuntimeError("api down")

    script = _script([("Nvidia jumped today.", "hook"),
                      ("Demand was strong.", "body"),
                      ("Subscribe for more.", "cta")])
    assert _inspect_consistency(script, client=_Boom(), model="x") == []
