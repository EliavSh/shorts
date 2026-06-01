"""Unit tests for the news/trending/selection/upload/SEO work.

All network calls are monkeypatched so these run offline.
"""
from __future__ import annotations

import pytest

from shorts.pipelines.stocks.data import news as news_mod
from shorts.pipelines.stocks.data import trending as trending_mod
from shorts.pipelines.stocks.planner.planner import MoverLite, _order_movers


# ── Part A / E1: multi-provider per-ticker news ────────────────────────────────

def test_get_news_merges_and_dedupes(monkeypatch) -> None:
    monkeypatch.setattr(
        news_mod, "_finnhub_company_news",
        lambda t, *, days_back: [("Nvidia beats earnings", "Revenue hit a record.")],
    )
    monkeypatch.setattr(
        news_mod, "_yahoo_rss_ticker",
        lambda t: [
            ("Nvidia Beats Earnings!", "dup of finnhub headline"),  # dedupe target
            ("Nvidia guidance disappoints", "Traders wanted more."),
        ],
    )
    out = news_mod.get_news_for_ticker("NVDA")
    # Two unique headlines survive (the near-duplicate is dropped).
    assert len(out) == 2
    assert any("Nvidia beats earnings" in s for s in out)
    assert any("guidance disappoints" in s for s in out)
    # E1: summary text is folded into the string.
    assert any("Revenue hit a record" in s for s in out)


def test_get_news_empty_when_all_fail(monkeypatch) -> None:
    monkeypatch.setattr(news_mod, "_finnhub_company_news", lambda t, *, days_back: [])
    monkeypatch.setattr(news_mod, "_yahoo_rss_ticker", lambda t: [])
    assert news_mod.get_news_for_ticker("NVDA") == []


def test_get_news_respects_limit(monkeypatch) -> None:
    many = [(f"Headline number {i}", "") for i in range(20)]
    monkeypatch.setattr(news_mod, "_finnhub_company_news", lambda t, *, days_back: many)
    monkeypatch.setattr(news_mod, "_yahoo_rss_ticker", lambda t: [])
    assert len(news_mod.get_news_for_ticker("NVDA", limit=4)) == 4


def test_parse_rss_items() -> None:
    xml = """<?xml version="1.0"?><rss version="2.0"><channel>
      <item><title>First</title><description>Body one</description></item>
      <item><title>Second</title><description>Body two</description></item>
    </channel></rss>"""
    items = news_mod.parse_rss_items(xml)
    assert items == [("First", "Body one"), ("Second", "Body two")]


# ── Part B: trending tickers ───────────────────────────────────────────────────

def test_trending_counts_finnhub_related(monkeypatch) -> None:
    def fake_finnhub(counter):
        for related in ["NVDA,AMD", "NVDA", "AAPL"]:
            for sym in related.split(","):
                counter[sym] += 1
    monkeypatch.setattr(trending_mod, "_finnhub_general", fake_finnhub)
    monkeypatch.setattr(trending_mod, "_market_rss", lambda c: None)
    out = trending_mod.trending_tickers()
    assert out["NVDA"] == 2
    assert out["AMD"] == 1
    assert out["AAPL"] == 1


def test_trending_rss_ignores_non_universe_words(monkeypatch) -> None:
    # 'CEO' and 'USA' are ALL-CAPS but not in the universe → ignored.
    # 'NVDA' matches the universe; '$TSLA' is a cashtag.
    rss = """<?xml version="1.0"?><rss version="2.0"><channel>
      <item><title>CEO of NVDA talks $TSLA in USA</title><description></description></item>
    </channel></rss>"""

    def fake_rss(counter):
        for title, summary in news_mod.parse_rss_items(rss):
            text = f"{title} {summary}"
            for sym in trending_mod._CASHTAG.findall(text.upper()):
                counter[sym] += 1
            for sym in trending_mod._WORD.findall(text):
                if sym in trending_mod._UNIVERSE:
                    counter[sym] += 1

    monkeypatch.setattr(trending_mod, "_finnhub_general", lambda c: None)
    monkeypatch.setattr(trending_mod, "_market_rss", fake_rss)
    out = trending_mod.trending_tickers()
    assert out.get("NVDA") == 1
    assert out.get("TSLA", 0) >= 1  # cashtag + universe-word both count it
    assert "CEO" not in out
    assert "USA" not in out


def test_trending_empty_on_total_failure(monkeypatch) -> None:
    monkeypatch.setattr(trending_mod, "_finnhub_general", lambda c: None)
    monkeypatch.setattr(trending_mod, "_market_rss", lambda c: None)
    assert trending_mod.trending_tickers() == {}


# ── Part C: news score floats above raw volatility ─────────────────────────────

def test_order_movers_news_beats_volatility() -> None:
    quiet_but_volatile = MoverLite(ticker="AMD", change_pct=9.0, news_score=0)
    trending_calm = MoverLite(ticker="NVDA", change_pct=1.0, news_score=5)
    ordered = _order_movers([quiet_but_volatile, trending_calm], sector_bias={})
    assert [m.ticker for m in ordered] == ["NVDA", "AMD"]


def test_order_movers_sector_bias_dominates() -> None:
    biased = MoverLite(ticker="XOM", sector="energy", change_pct=0.5, news_score=0)
    trending = MoverLite(ticker="NVDA", sector="tech", change_pct=1.0, news_score=9)
    ordered = _order_movers([trending, biased], sector_bias={"energy": 2.0})
    assert ordered[0].ticker == "XOM"


# ── Part D: upload privacy forwarding ──────────────────────────────────────────

def test_upload_forwards_privacy(monkeypatch) -> None:
    from shorts.pipelines.stocks import upload as upload_mod

    captured = {}

    class _Ver:
        v = 1
        title = "t"
        description = "d"
        tags = ["Shorts"]

    class _Item:
        pass

    import pathlib
    class _Store:
        output_root = pathlib.Path(__file__).parent
        def load(self, slug): return _Item()
        def short_path(self, slug, v):
            import pathlib
            return pathlib.Path(__file__)  # exists()

    class _Result:
        url = "https://youtu.be/x"
        video_id = "x"

    monkeypatch.setattr(upload_mod, "load_secrets", lambda **kw: None)
    monkeypatch.setattr(upload_mod, "ReviewStore", lambda name: _Store())
    monkeypatch.setattr(upload_mod, "latest_version", lambda item: _Ver())
    monkeypatch.setattr(upload_mod, "auth_from_env", lambda name: type("A", (), {"channel_id": "c"})())

    def fake_upload_short(**kwargs):
        captured.update(kwargs)
        return _Result()

    monkeypatch.setattr(upload_mod, "upload_short", fake_upload_short)
    # Avoid the purge + ledger tail touching disk.
    monkeypatch.setattr(upload_mod, "_manifest_meta", lambda mp4: ("fmt", ["NVDA"], 0.12))
    import shorts.pipelines.stocks.planner.published as pub
    monkeypatch.setattr(pub, "record_published", lambda **kw: None)
    monkeypatch.setattr(upload_mod.shutil, "rmtree", lambda p: None)

    upload_mod.upload("somerun", privacy="public")
    assert captured["privacy"] == "public"


# ── Part E5: SEO description ────────────────────────────────────────────────────

def _mk_script():
    from shorts.pipelines.stocks.script.schemas import Script, Beat, TickerSpec
    return Script(
        lang="en", format="deep_dive_one_stock",
        title="Nvidia drops 3% after earnings beat",
        description_hashtags=["NVDA", "Nvidia", "semiconductors"],
        tickers=[TickerSpec(ticker="NVDA", name="Nvidia", change_pct=-3.0)],
        target_seconds=90,
        beats=[
            Beat(narration="Nvidia just beat earnings and dropped 3%.", role="hook"),
            Beat(narration="Revenue hit a record 35 billion dollars.", role="body"),
            Beat(narration="But guidance disappointed traders.", role="body"),
            Beat(narration="Follow for daily market moves.", role="cta"),
        ],
    )


def test_build_description_has_cashtags_disclaimer_hashtags() -> None:
    from shorts.pipelines.stocks.pipeline import _build_description, _description_tags
    s = _mk_script()
    d = _build_description(s)
    assert "$NVDA" in d
    assert "Not financial advice" in d
    assert "#Shorts" in d
    assert "Revenue hit a record" in d  # takeaway included
    tags = _description_tags(s)
    assert "Shorts" in tags and "stocks" in tags


def test_description_tags_dedupe() -> None:
    from shorts.pipelines.stocks.pipeline import _description_tags
    from shorts.pipelines.stocks.script.schemas import Script, Beat, TickerSpec
    s = Script(
        lang="en", format="fun_fact", title="A short fact about stocks",
        description_hashtags=["Shorts", "stocks", "NVDA"],
        tickers=[], target_seconds=60,
        beats=[Beat(narration="One fact.", role="hook"), Beat(narration="Two.", role="body")],
    )
    tags = _description_tags(s)
    assert tags.count("Shorts") == 1
    assert tags.count("stocks") == 1
