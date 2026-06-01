"""Channel strategist — the audience-aware planner critic.

Looks at the channel's own published history (sectors / tickers / formats) plus
each video's public view & like counts, and produces:
  • cooldown_tickers — over-covered names the planner should rest (concrete
    soft-nudge: added to the planner's recently-used set, so they're avoided in
    selection but a genuinely news-hot one can still break through);
  • an advisory `directive` — a short, human-readable strategy note shown on the
    Plan page ("you've leaned heavily on semis; lean into earnings, which drew
    the most views; rest NVDA for a few clips").

Everything is best-effort: any failure yields a neutral Strategy so planning is
never blocked. The result is cached (recomputed at most ~once per `max_age_hours`)
to keep cost down across the many daily replans.
"""
from __future__ import annotations

import logging
from collections import Counter, defaultdict
from datetime import datetime

import httpx

from ..settings import get_settings
from . import store
from .models import Strategy
from .published import load_published

log = logging.getLogger(__name__)

_RECENT = 25          # how many recent published clips to analyse
_TIMEOUT = 10.0


def get_strategy(*, max_age_hours: float = 18.0) -> Strategy:
    """Cached strategy: reuse the stored one while it's fresh, else recompute."""
    cur = store.load_strategy()
    if cur.computed_at:
        try:
            age_h = (datetime.now() - datetime.fromisoformat(cur.computed_at)).total_seconds() / 3600
            if age_h < max_age_hours:
                return cur
        except Exception:
            pass
    fresh = compute_strategy()
    store.save_strategy(fresh)
    return fresh


def compute_strategy() -> Strategy:
    try:
        return _compute()
    except Exception as e:
        log.warning("strategist: compute failed (%s) — neutral strategy", e)
        return Strategy(computed_at=datetime.now().isoformat(timespec="seconds"))


def _compute() -> Strategy:
    entries = load_published().entries[-_RECENT:]
    now = datetime.now().isoformat(timespec="seconds")
    if not entries:
        return Strategy(
            directive="No published history yet — covering the day's biggest, most newsworthy movers.",
            computed_at=now,
        )

    n = len(entries)
    ticker_counts = Counter(t.upper() for e in entries for t in (e.tickers or []))
    sector_counts = Counter(e.sector for e in entries if e.sector)

    # Repetition: a ticker in >=35% of recent clips (min 2) is over-covered.
    cooldown_tickers = sorted(
        t for t, c in ticker_counts.items() if c >= max(2, round(n * 0.35))
    )
    cooldown_sectors = sorted(
        s for s, c in sector_counts.items() if c >= max(2, round(n * 0.5))
    )

    # Audience signal: public view/like counts → which sectors performed best.
    stats = _video_stats([e.youtube_id for e in entries if e.youtube_id])
    favor_sectors, top_performers = _audience_signal(entries, stats, cooldown_sectors)

    directive = _directive(entries, stats, ticker_counts, sector_counts,
                           cooldown_tickers, favor_sectors, top_performers)

    return Strategy(
        directive=directive,
        cooldown_tickers=cooldown_tickers,
        cooldown_sectors=cooldown_sectors,
        favor_sectors=favor_sectors,
        top_performers=top_performers,
        sample_size=n,
        computed_at=now,
    )


def _video_stats(video_ids: list[str]) -> dict[str, dict[str, int]]:
    """{video_id: {"views": int, "likes": int}} via the YouTube Data API. Needs
    `youtube_api_key`; returns {} if unset or on any error (best-effort)."""
    key = get_settings().youtube_api_key
    ids = [v for v in video_ids if v]
    if not key or not ids:
        return {}
    out: dict[str, dict[str, int]] = {}
    try:
        for i in range(0, len(ids), 50):  # API caps at 50 ids/call
            chunk = ids[i:i + 50]
            r = httpx.get(
                "https://www.googleapis.com/youtube/v3/videos",
                params={"part": "statistics", "id": ",".join(chunk), "key": key},
                timeout=_TIMEOUT,
            )
            r.raise_for_status()
            for item in r.json().get("items", []):
                st = item.get("statistics", {})
                out[item["id"]] = {
                    "views": int(st.get("viewCount", 0)),
                    "likes": int(st.get("likeCount", 0)),
                }
    except Exception as e:
        log.debug("strategist: video stats unavailable: %s", e)
        return {}
    return out


def _audience_signal(entries, stats, cooldown_sectors) -> tuple[list[str], list[str]]:
    """From view counts, find the best-performing sectors (to favour) and the
    top individual videos (for the directive). Empty when no stats."""
    if not stats:
        return [], []
    by_sector: dict[str, list[int]] = defaultdict(list)
    scored: list[tuple[int, str]] = []
    for e in entries:
        v = stats.get(e.youtube_id or "", {}).get("views")
        if v is None:
            continue
        if e.sector:
            by_sector[e.sector].append(v)
        scored.append((v, e.title or e.slug))
    if not scored:
        return [], []
    sector_avg = {s: sum(vs) / len(vs) for s, vs in by_sector.items() if vs}
    overall = sum(v for v, _ in scored) / len(scored)
    favor = sorted(
        (s for s, a in sector_avg.items() if a > overall and s not in cooldown_sectors),
        key=lambda s: sector_avg[s], reverse=True,
    )[:2]
    top = [title for _v, title in sorted(scored, reverse=True)[:2]]
    return favor, top


def _directive(entries, stats, ticker_counts, sector_counts,
               cooldown_tickers, favor_sectors, top_performers) -> str:
    """A short advisory directive. Tries a cheap LLM synthesis; falls back to a
    deterministic template so it always returns something useful."""
    try:
        return _llm_directive(entries, stats, top_performers)
    except Exception as e:
        log.debug("strategist: LLM directive failed, using template: %s", e)

    parts: list[str] = []
    if sector_counts:
        top_sec = sector_counts.most_common(1)[0][0]
        parts.append(f"Recent coverage leans on {top_sec}.")
    if cooldown_tickers:
        parts.append("Rest these for a few clips: " + ", ".join(cooldown_tickers) + ".")
    if favor_sectors:
        parts.append("Audience engaged most with " + ", ".join(favor_sectors)
                     + " — lean in.")
    if top_performers:
        parts.append("Top performer recently: " + top_performers[0] + ".")
    if not parts:
        parts.append("Healthy mix so far — keep covering the day's biggest movers and vary the sectors.")
    return " ".join(parts)


def _llm_directive(entries, stats, top_performers) -> str:
    from shorts.core.infra.anthropic_client import make_client

    s = get_settings()
    if not s.anthropic_api_key:
        raise RuntimeError("no anthropic key")
    lines = []
    for e in entries[-15:]:
        views = stats.get(e.youtube_id or "", {}).get("views")
        v = f" — {views} views" if views is not None else ""
        lines.append(f"- [{e.sector or '?'}/{e.format or '?'}] {e.title or e.slug}"
                     f" ({', '.join(e.tickers or []) or 'mkt'}){v}")
    prompt = (
        "You are the channel strategist for a daily finance-Shorts channel. Below "
        "are the most recent uploads (sector/format, title, tickers, and views "
        "where known). In 2–3 short sentences, advise what to cover next to keep "
        "the channel fresh and grow the audience: call out over-covered names or "
        "sectors to rest, and what's resonating (higher views) to lean into. Be "
        "concrete and punchy. Return ONLY the advice, no preamble.\n\n"
        + "\n".join(lines)
    )
    resp = make_client().messages.create(
        model=s.claude_director_model, max_tokens=160,
        messages=[{"role": "user", "content": prompt}],
    )
    text = "".join(getattr(b, "text", "") for b in resp.content
                   if getattr(b, "type", None) == "text").strip()
    if not text:
        raise RuntimeError("empty directive")
    return text
