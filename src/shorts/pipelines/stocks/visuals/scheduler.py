"""Visual scheduler — fetches and selects images for each VisualSection.

For each section:
  1. Run each `search_query` across all retrieval sources.
  2. Drop low-quality images (resolution / aspect / file-size heuristics).
  3. CLIP-score the survivors against the section's `intent`.
  4. Keep only candidates above MIN_RELEVANCE.
  5. Pick the best one for the section.
If nothing passes, fall back to a generic ticker B-roll search, else a solid
color (composer's fallback layer).
"""
from __future__ import annotations

import logging
from dataclasses import dataclass

from PIL import Image

from .cache import CachedImage, fetch
from .director import VisualPlan, VisualSection
from shorts.core.visuals.kenburns import make_kenburns_clip
from .retrieval import search_all
from .retrieval import wikimedia, pexels

log = logging.getLogger(__name__)

MIN_SHORT_SIDE_PX = 700      # reject anything smaller than this on short side
MIN_LONG_SIDE_PX = 900       # and on long side
MAX_ASPECT = 2.6             # very wide/tall panoramas don't crop well to 9:16
MIN_FILE_BYTES = 18_000      # below this is usually thumbnails
MIN_RELEVANCE = 0.22         # CLIP cosine threshold (R6: raised from 0.18 after fomc_banks review)

# R6 — domains known to publish news-broadcast composites with chyron overlays.
# When the section intent is conceptual (not a specific news event), images from
# these domains are down-weighted.
COMPOSITE_HEAVY_DOMAINS = {
    "foxnews.com", "cnn.com", "edition.cnn.com", "msnbc.com",
    "cnbc.com", "bloombergquint.com", "rt.com",
    "skynews.com", "bbc.co.uk", "youtube.com", "i.ytimg.com",
}

# F3 — title keywords that mark an image as a composite / press graphic / dashboard
# / press-release header, which CLIP often scores artificially high for finance topics.
COMPOSITE_TITLE_KEYWORDS = (
    "infographic", "dashboard", "presentation", "screenshot",
    "press release", "headline graphic", "chart:",
    "image of", "stock photography", "vector",
    "powerpoint", "slide", "pdf",
)


@dataclass
class VisualShot:
    image: CachedImage
    start_s: float
    end_s: float
    relevance: float
    intent: str


def _is_quality_ok(img: CachedImage) -> bool:
    """Heuristic quality filter — runs after download, uses real pixel dims."""
    try:
        if img.path.stat().st_size < MIN_FILE_BYTES:
            return False
        with Image.open(img.path) as pi:
            w, h = pi.size
    except Exception:
        return False
    if w < MIN_SHORT_SIDE_PX and h < MIN_SHORT_SIDE_PX:
        return False
    if max(w, h) < MIN_LONG_SIDE_PX:
        return False
    aspect = max(w / max(h, 1), h / max(w, 1))
    if aspect > MAX_ASPECT:
        return False
    return True


def _composite_penalty(img: CachedImage) -> float:
    """R6 + F3 — return a relevance penalty for images likely to be composites
    (broadcast chyrons, dashboards, press-release headers)."""
    pen = 0.0
    url = (img.url or "").lower()
    title = (img.title or "").lower()
    for d in COMPOSITE_HEAVY_DOMAINS:
        if d in url:
            pen += 0.06
            break
    for kw in COMPOSITE_TITLE_KEYWORDS:
        if kw in title:
            pen += 0.05
            break
    return pen


def _text_heavy_penalty(img: CachedImage) -> float:
    """Penalize images that are likely text-heavy explainers / infographics.

    Photos of real scenes rarely have a large flat near-white background;
    diagrams, price-tag explainers and infographics usually do (and CLIP scores
    them deceptively high because they literally depict the subject). Cheap PIL
    histogram on a downscaled grayscale copy — no OCR needed.
    """
    try:
        with Image.open(img.path) as pi:
            g = pi.convert("L").resize((128, 128))
        hist = g.histogram()
        total = sum(hist) or 1
        near_white = sum(hist[238:]) / total
    except Exception:
        return 0.0
    if near_white > 0.45:
        return 0.12
    if near_white > 0.32:
        return 0.06
    return 0.0


def _retrieve_for_section(section: VisualSection) -> list[CachedImage]:
    """Hit all sources, download, quality-filter. Return survivors."""
    candidates = []
    for q in section.search_queries:
        candidates.extend(search_all(q, n_per_source=3))

    # dedupe by URL
    seen: set[str] = set()
    unique = []
    for c in candidates:
        if c.url and c.url not in seen:
            seen.add(c.url)
            unique.append(c)

    fetched: list[CachedImage] = []
    for c in unique:
        ci = fetch(c)
        if ci is None:
            continue
        if not _is_quality_ok(ci):
            log.debug("quality reject: %s", ci.path.name)
            continue
        fetched.append(ci)
    return fetched


def _rank_by_relevance(intent: str, images: list[CachedImage]) -> list[tuple[CachedImage, float]]:
    if not images:
        return []
    try:
        from .scorer import score_batch
        scores = score_batch([ci.path for ci in images], intent)
    except ImportError:
        log.warning("open_clip not installed — using retrieval order as ranking")
        scores = [0.5 - i * 0.01 for i in range(len(images))]
    # R6 — subtract a small penalty for known composite-heavy sources.
    scores = [s - _composite_penalty(ci) - _text_heavy_penalty(ci) for ci, s in zip(images, scores, strict=False)]
    return sorted(zip(images, scores, strict=False), key=lambda t: t[1], reverse=True)


def _fallback_search(ticker_name: str | None) -> list[CachedImage]:
    """Generic B-roll fallback: try a couple of vague queries."""
    queries: list[str] = []
    if ticker_name:
        queries.append(f"{ticker_name} corporate building")
    queries += ["Wall Street stock market", "modern office building skyline"]
    out: list[CachedImage] = []
    for q in queries[:2]:
        for source_fn in (wikimedia.search, pexels.search):
            for c in source_fn(q, n=2):
                ci = fetch(c)
                if ci and _is_quality_ok(ci):
                    out.append(ci)
                    if len(out) >= 2:
                        return out
    return out


def schedule_plan(plan: VisualPlan, script) -> list[VisualShot]:
    """Pick one shot per section. Sections with graphic_spec dispatch to the
    generated-graphics module instead of retrieval. Otherwise standard retrieval
    + CLIP + diversity heuristic.
    """
    from shorts.pipelines.stocks.visuals.brand import load_brand
    from ..settings import get_settings
    from shorts.core.visuals import graphics

    brand = load_brand(script.lang)
    s = get_settings()
    graphics_dir = s.visual_cache_dir / "generated"

    shots: list[VisualShot] = []
    recent_used: list[str] = []
    for sec in plan.sections:
        if sec.graphic_spec:
            try:
                path = graphics.render(
                    graphics.GraphicSpec(kind=sec.graphic_spec["kind"], params=sec.graphic_spec.get("params", {})),
                    brand=brand, out_dir=graphics_dir,
                )
                shots.append(VisualShot(
                    image=CachedImage(
                        path=path, url=f"generated://{sec.graphic_spec['kind']}",
                        source="wikimedia",  # placeholder; not a retrieval source
                        title=f"[generated] {sec.graphic_spec['kind']}",
                        license="generated", attribution=None,
                        source_page=None, width=None, height=None,
                    ),
                    start_s=sec.start_s, end_s=sec.end_s,
                    relevance=1.0, intent=sec.intent,
                ))
                continue
            except Exception as e:
                log.warning("graphic_spec render failed (%s) — falling back to retrieval", e)
                # fall through to retrieval

        chosen, score = _pick_for_section(sec, script, avoid=set(recent_used))
        if chosen is None:
            log.warning("no usable image for section %.1f-%.1f intent=%r",
                        sec.start_s, sec.end_s, sec.intent[:60])
            continue
        shots.append(VisualShot(
            image=chosen, start_s=sec.start_s, end_s=sec.end_s,
            relevance=score, intent=sec.intent,
        ))
        recent_used.append(str(chosen.path))
        if len(recent_used) > 2:
            recent_used.pop(0)
    return shots


def _pick_for_section(section: VisualSection, script, *,
                     avoid: set[str] | None = None) -> tuple[CachedImage | None, float]:
    avoid = avoid or set()
    images = _retrieve_for_section(section)
    ranked = _rank_by_relevance(section.intent, images)

    log.info("section %.1fs-%.1fs intent=%r  candidates=%d  best=%.3f",
             section.start_s, section.end_s, section.intent[:50],
             len(ranked), ranked[0][1] if ranked else -1.0)

    # Try to find best non-recently-used candidate above threshold.
    for img, sc in ranked:
        if sc < MIN_RELEVANCE:
            break
        if str(img.path) in avoid:
            continue
        return img, sc

    # If nothing fresh passed, fall back to top regardless (repeat is fine).
    if ranked and ranked[0][1] >= MIN_RELEVANCE:
        return ranked[0]

    # Last resort: vague ticker B-roll search.
    ticker_name = None
    if section.ticker_focus:
        spec = script.ticker(section.ticker_focus)
        ticker_name = spec.name if spec else section.ticker_focus
    fb_images = _fallback_search(ticker_name)
    fb_ranked = _rank_by_relevance(section.intent, fb_images)
    for img, sc in fb_ranked:
        if sc < MIN_RELEVANCE * 0.75:
            break
        if str(img.path) in avoid:
            continue
        log.info("using fallback B-roll for section %.1f-%.1f", section.start_s, section.end_s)
        return img, sc
    if fb_ranked and fb_ranked[0][1] >= MIN_RELEVANCE * 0.75:
        return fb_ranked[0]
    return None, 0.0


def shot_to_clip(shot: VisualShot):
    """Turn a scheduled shot into a Ken-Burns-animated MoviePy clip.

    Generated graphics (number callouts, date cards, CTAs) are authored at
    exactly 1080x1920 with text inside safe margins. Render them static —
    Ken Burns zoom/pan/cover-crop would push that centered text out of frame.
    """
    is_generated = (shot.image.url or "").startswith("generated://")
    clip = make_kenburns_clip(
        shot.image.path,
        duration_s=shot.end_s - shot.start_s,
        static=is_generated,
    )
    return clip.with_start(shot.start_s).with_position(("center", "center"))
