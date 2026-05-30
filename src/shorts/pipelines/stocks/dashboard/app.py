"""FastAPI dashboard — staged videos + cost observability.

Routes:
  GET  /                       — staged videos list, each links to a preview
  GET  /video/{slug}           — preview the mp4 + the picks manifest + action buttons
  POST /video/{slug}/upload    — publish to YouTube as unlisted (Phase 11)
  POST /video/{slug}/promote   — flip unlisted → public (Phase 11)
  GET  /costs                  — spend by provider, by video, free-tier bars

Run with: `stocksreels dashboard` (default http://127.0.0.1:8765).
"""
from __future__ import annotations

import json
import logging
from datetime import datetime, timedelta
from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from sqlmodel import Session, select

from ..db import Upload as UploadRow
from ..db import get_engine
from ..settings import get_settings
from shorts.core.usage import prices, spend_by_provider, spend_by_video

log = logging.getLogger(__name__)

app = FastAPI(title="stocks-reels")

settings = get_settings()
settings.ensure_dirs()

app.mount("/files", StaticFiles(directory=str(settings.output_dir)), name="files")


def _list_manifests() -> list[dict]:
    out = []
    for p in sorted(settings.output_dir.glob("*.manifest.json"), key=lambda x: -x.stat().st_mtime):
        try:
            m = json.loads(p.read_text(encoding="utf-8"))
            slug = p.stem.replace(".manifest", "")
            upload = _upload_for_slug(slug)
            out.append({
                "slug": slug,
                "title": m.get("title", slug),
                "duration_s": m.get("duration_s", 0),
                "format": m.get("format", "?"),
                "tickers": [t.get("ticker") for t in m.get("tickers", [])],
                "mp4": f"/files/{slug}.mp4",
                "shots": len(m.get("shots", [])),
                "cost": m.get("cost_breakdown", {}).get("total_usd"),
                "modified": datetime.fromtimestamp(p.stat().st_mtime).isoformat(timespec="seconds"),
                "upload": upload,
            })
        except Exception:
            continue
    return out


def _upload_for_slug(slug: str) -> dict | None:
    """Latest Upload row for a slug (None if never uploaded)."""
    with Session(get_engine()) as session:
        # Render is FK'd to Script, Script to Topic — but we don't store slug
        # directly. For v1 we match by title-derived path heuristic: any Upload
        # whose title contains the slug.
        rows = session.exec(
            select(UploadRow).where(UploadRow.title.contains(slug))
            .order_by(UploadRow.created_at.desc())
        ).all()
    if not rows:
        return None
    r = rows[0]
    return {
        "youtube_video_id": r.youtube_video_id,
        "channel": r.channel,
        "visibility": r.visibility,
        "promoted_at": r.promoted_at.isoformat(timespec="seconds") if r.promoted_at else None,
        "url": f"https://www.youtube.com/watch?v={r.youtube_video_id}",
    }


# ─────────────────────────────────────────────────────────────────────────────
# HTML helpers
# ─────────────────────────────────────────────────────────────────────────────

CSS = """
<style>
  :root { color-scheme: dark; }
  body { background: #0b1320; color: #e5e7eb; font: 15px/1.5 -apple-system, system-ui, sans-serif;
         margin: 0; padding: 24px 32px; }
  a { color: #93c5fd; text-decoration: none; }
  a:hover { text-decoration: underline; }
  h1 { font-size: 24px; margin: 0 0 12px; }
  h3 { margin-top: 28px; }
  nav { margin-bottom: 24px; display: flex; gap: 18px; font-size: 14px; }
  nav a { color: #a8c3e8; font-weight: 600; }
  .grid { display: grid; grid-template-columns: repeat(auto-fill, minmax(280px, 1fr));
          gap: 18px; }
  .card { background: #111a2b; border: 1px solid #1f2c44; border-radius: 12px;
          padding: 16px; }
  .card h3 { font-size: 16px; margin: 0 0 6px; }
  .meta { color: #93a1bb; font-size: 12px; }
  .row { display: flex; gap: 12px; align-items: center; flex-wrap: wrap; margin: 14px 0; }
  table { width: 100%; border-collapse: collapse; margin-top: 16px; }
  th, td { padding: 8px 10px; border-bottom: 1px solid #1f2c44; text-align: left;
           vertical-align: top; }
  th { font-weight: 600; color: #a8c3e8; }
  td.num, th.num { text-align: right; font-variant-numeric: tabular-nums; }
  .pill { background: #1f2c44; padding: 2px 8px; border-radius: 8px; font-size: 12px;
          display: inline-block; }
  .pill.good { background: #14532d; color: #bbf7d0; }
  .pill.warn { background: #78350f; color: #fde68a; }
  .pill.live { background: #166534; color: #dcfce7; }
  .bar-track { background: #1f2c44; height: 8px; border-radius: 4px; overflow: hidden;
               margin-top: 4px; }
  .bar-fill { background: #22c55e; height: 100%; }
  .bar-fill.warn { background: #f59e0b; }
  .bar-fill.over { background: #ef4444; }
  video { width: 100%; max-width: 540px; border-radius: 12px; background: #000; }
  button { background: #3b82f6; color: white; border: 0; padding: 10px 18px; border-radius: 8px;
           font: inherit; font-weight: 600; cursor: pointer; }
  button:hover { background: #2563eb; }
  button.promote { background: #22c55e; }
  button.promote:hover { background: #16a34a; }
  button:disabled { background: #1f2c44; cursor: not-allowed; }
  form { display: inline; }
</style>
"""

NAV = """
<nav>
  <a href="/">Staged videos</a>
  <a href="/costs">Costs</a>
</nav>
"""


def _page(title: str, body: str) -> str:
    return f"<!doctype html><html><head><meta charset='utf-8'><title>{title} — stocks-reels</title>{CSS}</head><body>{NAV}{body}</body></html>"


# ─────────────────────────────────────────────────────────────────────────────
# Routes — listing + preview
# ─────────────────────────────────────────────────────────────────────────────

@app.get("/", response_class=HTMLResponse)
def index() -> str:
    manifests = _list_manifests()
    if not manifests:
        cards = "<p class='meta'>No renders yet. Run <code>stocksreels render-fixture &lt;slug&gt;</code> or <code>stocksreels run</code>.</p>"
    else:
        cards = "<div class='grid'>" + "".join(_video_card(m) for m in manifests) + "</div>"
    return _page("Staged videos", f"<h1>Staged videos · {len(manifests)}</h1>{cards}")


def _video_card(m: dict) -> str:
    tickers = " ".join(f"<span class='pill'>{t}</span>" for t in m["tickers"])
    status_pill = ""
    if m["upload"]:
        v = m["upload"]["visibility"]
        cls = "live" if v == "public" else "good"
        status_pill = f"<span class='pill {cls}'>{v}</span>"
    cost = f" · ${m['cost']:.3f}" if m.get("cost") is not None else ""
    return f"""
    <div class='card'>
      <h3><a href='/video/{m["slug"]}'>{m["title"]}</a></h3>
      <div class='meta'>{m["format"]} · {m["duration_s"]:.0f}s · {m["shots"]} shots · {m["modified"]}{cost}</div>
      <div style='margin-top:8px'>{tickers} {status_pill}</div>
    </div>
    """


@app.get("/video/{slug}", response_class=HTMLResponse)
def video(slug: str) -> str:
    mp4 = settings.output_dir / f"{slug}.mp4"
    manifest_p = settings.output_dir / f"{slug}.manifest.json"
    if not mp4.exists() or not manifest_p.exists():
        raise HTTPException(404, "not found")
    m = json.loads(manifest_p.read_text(encoding="utf-8"))
    upload = _upload_for_slug(slug)

    # Action area depends on upload state
    if upload is None:
        actions = f"""
          <form method='post' action='/video/{slug}/upload'>
            <button type='submit'>Upload to staging (unlisted)</button>
          </form>
        """
    elif upload["visibility"] == "unlisted":
        actions = f"""
          <a href='{upload['url']}' target='_blank' class='pill good'>Open on YouTube ({upload['visibility']})</a>
          <form method='post' action='/video/{slug}/promote'>
            <button class='promote' type='submit'>Promote to public</button>
          </form>
        """
    else:  # public
        actions = f"""
          <a href='{upload['url']}' target='_blank' class='pill live'>Live on YouTube ({upload['visibility']})</a>
        """

    rows = "".join(
        f"<tr><td>{s['start_s']:.1f}–{s['end_s']:.1f}</td>"
        f"<td class='num'>{s.get('relevance', 0):.2f}</td>"
        f"<td>{s.get('source','')}</td>"
        f"<td>{(s.get('title','') or s.get('attribution',''))[:50]}</td>"
        f"<td>{s.get('intent','')[:70]}</td></tr>"
        for s in m.get("shots", [])
    )

    cost = m.get("cost_breakdown", {})
    cost_html = ""
    if cost:
        by = " ".join(f"<span class='pill'>{p}: ${c}</span>" for p, c in cost.get("by_provider", {}).items())
        cost_html = f"<div class='meta'>cost: ${cost.get('total_usd', 0):.4f} {by}</div>"

    return _page(m.get("title", slug), f"""
      <h1>{m.get('title', slug)}</h1>
      <p class='meta'>{m.get('format','?')} · {m.get('duration_s', 0):.1f}s · {len(m.get('shots',[]))} shots</p>
      {cost_html}
      <video controls preload='metadata' src='/files/{slug}.mp4'></video>
      <div class='row'>{actions}</div>
      <h3>Per-section picks</h3>
      <table>
        <thead><tr><th>Time</th><th class='num'>CLIP</th><th>Source</th><th>Title</th><th>Intent</th></tr></thead>
        <tbody>{rows}</tbody>
      </table>
    """)


# ─────────────────────────────────────────────────────────────────────────────
# Routes — upload + promote actions
# ─────────────────────────────────────────────────────────────────────────────

@app.post("/video/{slug}/upload")
def upload_action(slug: str):
    """Upload the rendered mp4 to YouTube as unlisted."""
    from ..publish import upload_short

    mp4 = settings.output_dir / f"{slug}.mp4"
    manifest_p = settings.output_dir / f"{slug}.manifest.json"
    if not mp4.exists() or not manifest_p.exists():
        raise HTTPException(404, "render not found")
    m = json.loads(manifest_p.read_text(encoding="utf-8"))

    title = m.get("title", slug)
    hashtags = m.get("description_hashtags") or []
    tags = [t.lstrip("#") for t in hashtags][:15]
    description = " ".join(hashtags)
    # Append slug to title so dashboard can map this Upload back to the slug.
    log.info("Dashboard-triggered upload of %s", slug)
    try:
        result = upload_short(
            mp4_path=Path(mp4), title=title[:90], description=description,
            tags=tags, privacy="unlisted",
        )
    except Exception as e:
        raise HTTPException(500, f"upload failed: {e}") from e

    # Persist the Upload row keyed on slug-in-title so we can find it later.
    # (Phase 12 will properly join via Render.script_id.)
    with Session(get_engine()) as session:
        session.add(UploadRow(
            render_id=0,  # placeholder until we wire Render→Upload via FK
            youtube_video_id=result.video_id,
            channel="staging",
            visibility=result.privacy,
            title=f"{slug}|{title[:80]}",  # encode slug for retrieval
        ))
        session.commit()

    return RedirectResponse(url=f"/video/{slug}", status_code=303)


@app.post("/video/{slug}/promote")
def promote_action(slug: str):
    """Flip the most recent Upload row for this slug to public."""
    from datetime import datetime as dt

    from ..publish import set_privacy

    upload = _upload_for_slug(slug)
    if not upload:
        raise HTTPException(404, "no upload for this video")

    set_privacy(upload["youtube_video_id"], privacy="public")

    with Session(get_engine()) as session:
        rows = session.exec(
            select(UploadRow).where(UploadRow.youtube_video_id == upload["youtube_video_id"])
        ).all()
        for r in rows:
            r.visibility = "public"
            r.promoted_at = dt.utcnow()
            session.add(r)
        session.commit()

    return RedirectResponse(url=f"/video/{slug}", status_code=303)


# ─────────────────────────────────────────────────────────────────────────────
# Routes — costs
# ─────────────────────────────────────────────────────────────────────────────

@app.get("/costs", response_class=HTMLResponse)
def costs() -> str:
    since = datetime.utcnow() - timedelta(days=30)
    by_p = spend_by_provider(since=since)
    by_v = spend_by_video(since=since)
    total = sum(b["cost_usd"] for b in by_p.values())

    p_tbl_rows = "".join(
        f"<tr><td>{p}</td><td class='num'>{b['events']}</td>"
        f"<td class='num'>{b['units']:,}</td>"
        f"<td class='num'>{b['units_in']:,}</td>"
        f"<td class='num'>{b['units_out']:,}</td>"
        f"<td class='num'>${b['cost_usd']:.4f}</td></tr>"
        for p, b in sorted(by_p.items(), key=lambda x: -x[1]["cost_usd"])
    )

    pr = prices()
    bars: list[str] = []
    bars.append(_free_tier_bar("Pexels", by_p.get("pexels", {}).get("events", 0),
                               pr.get("pexels", {}).get("free_per_month", 20000), unit="queries/mo"))
    bars.append(_free_tier_bar("Google CSE", by_p.get("google_cse", {}).get("events", 0),
                               (pr.get("google_cse", {}).get("free_per_day", 100)) * 30,
                               unit="queries (rolling 30d, free if ≤100/day)"))
    bars.append(_free_tier_bar("YouTube quota", by_p.get("youtube_data_v3", {}).get("units", 0),
                               pr.get("youtube_data_v3", {}).get("free_per_day_units", 10000) * 30,
                               unit="quota units (rolling 30d, 10K/day free)"))

    v_rows = "".join(
        f"<tr><td>{v or '(unattributed)'}</td><td class='num'>{b['events']}</td>"
        f"<td class='num'>${b['cost_usd']:.4f}</td>"
        f"<td>{_pill_list(b['by_provider'])}</td></tr>"
        for v, b in sorted(by_v.items(), key=lambda x: -x[1]["cost_usd"])
    )

    return _page("Costs", f"""
      <h1>Spend · last 30 days · ${total:.4f}</h1>

      <h3>Free-tier usage</h3>
      <div class='grid'>{''.join(bars)}</div>

      <h3>By provider</h3>
      <table>
        <thead><tr><th>Provider</th><th class='num'>Events</th><th class='num'>Units</th>
        <th class='num'>In tokens</th><th class='num'>Out tokens</th><th class='num'>Cost</th></tr></thead>
        <tbody>{p_tbl_rows}</tbody>
      </table>

      <h3>By video</h3>
      <table>
        <thead><tr><th>Video</th><th class='num'>Events</th><th class='num'>Cost</th><th>Top providers</th></tr></thead>
        <tbody>{v_rows}</tbody>
      </table>
    """)


def _free_tier_bar(label: str, used: int, cap: int, *, unit: str) -> str:
    pct = min(100, int((used / cap) * 100) if cap else 0)
    cls = "over" if pct >= 100 else "warn" if pct >= 80 else ""
    return f"""
    <div class='card'>
      <div><b>{label}</b></div>
      <div class='meta'>{used:,} / {cap:,} {unit} ({pct}%)</div>
      <div class='bar-track'><div class='bar-fill {cls}' style='width:{pct}%'></div></div>
    </div>
    """


def _pill_list(by_provider: dict) -> str:
    return " ".join(
        f"<span class='pill'>{p}: ${c:.3f}</span>"
        for p, c in sorted(by_provider.items(), key=lambda x: -x[1])[:4]
    )


@app.get("/healthz")
def healthz() -> dict:
    return {"ok": True}
