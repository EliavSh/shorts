import logging
from pathlib import Path

import click
from rich.console import Console
from rich.logging import RichHandler

from . import __version__
from .db import init_db
from .settings import get_settings

console = Console()


def _setup_logging() -> None:
    s = get_settings()
    logging.basicConfig(
        level=s.log_level,
        format="%(message)s",
        datefmt="[%X]",
        handlers=[RichHandler(console=console, rich_tracebacks=True)],
    )


@click.group()
@click.version_option(__version__)
def cli() -> None:
    """stocks-reels — automated finance Shorts pipeline."""
    _setup_logging()


@cli.group()
def db() -> None:
    """Database commands."""


@db.command("init")
def db_init() -> None:
    """Create database tables."""
    init_db()
    console.print("[green]Database initialised.[/green]")


@cli.command("doctor")
def doctor_cmd() -> None:
    """Self-check every integration. Use after setup or when something's flaky."""
    from rich.table import Table

    s = get_settings()
    rows: list[tuple[str, str, str]] = []

    def add(name: str, ok: bool, note: str) -> None:
        rows.append((name, "OK" if ok else "FAIL", note))

    # Keys present
    add("anthropic key", bool(s.anthropic_api_key), "set" if s.anthropic_api_key else "ANTHROPIC_API_KEY missing")
    add("serper key", bool(s.serper_api_key), "set" if s.serper_api_key else "SERPER_API_KEY missing (optional)")
    add("pexels key", bool(s.pexels_api_key), "set" if s.pexels_api_key else "PEXELS_API_KEY missing (optional)")
    add("google_cse", bool(s.google_cse_api_key and s.google_cse_id),
        "set" if s.google_cse_api_key and s.google_cse_id else "(optional, currently disabled)")
    add("youtube client_secret", s.youtube_client_secrets_path.exists(),
        str(s.youtube_client_secrets_path) if s.youtube_client_secrets_path.exists()
        else "missing — see deploy/README for OAuth setup")
    add("youtube token", s.youtube_token_path.exists(),
        "ready" if s.youtube_token_path.exists() else "run `shorts auth youtube --pipeline stocks`")

    # Fonts
    from shorts.pipelines.stocks.visuals.brand import load_brand
    try:
        brand = load_brand("en")
        add("brand font (Heebo Bold)", brand.font_path.exists(), str(brand.font_path))
        add("brand font (Heebo Regular)", brand.font_path_regular.exists(), str(brand.font_path_regular))
    except Exception as e:
        add("brand config", False, str(e))

    # DB
    try:
        from .db import init_db
        init_db()
        add("sqlite db", True, s.db_url)
    except Exception as e:
        add("sqlite db", False, str(e))

    # Live Anthropic ping (only if key set)
    if s.anthropic_api_key:
        try:
            from shorts.core.infra.anthropic_client import make_client
            make_client().messages.create(
                model=s.claude_director_model, max_tokens=4,
                messages=[{"role": "user", "content": "ping"}],
            )
            add("anthropic live", True, "messages.create OK")
        except Exception as e:
            add("anthropic live", False, str(e)[:80])

    t = Table(show_header=True, header_style="bold cyan")
    t.add_column("Check"); t.add_column("Status"); t.add_column("Note", overflow="fold")
    for name, status, note in rows:
        style = "green" if status == "OK" else "red"
        t.add_row(name, f"[{style}]{status}[/{style}]", note)
    console.print(t)


@cli.command("inspect")
@click.argument("name")
@click.option("--lang", default="en", type=click.Choice(["en"]))
def inspect_cmd(name: str, lang: str) -> None:
    """Show a per-section breakdown of the last render: which image was picked,
    its source, CLIP relevance score, and attribution.
    """
    from rich.table import Table
    s = get_settings()
    manifest_path = s.output_dir / f"{name}_{lang}.manifest.json"
    if not manifest_path.exists():
        console.print(f"[red]No manifest at {manifest_path}.[/red]")
        raise SystemExit(1)
    import json
    m = json.loads(manifest_path.read_text(encoding="utf-8"))
    console.print(f"[bold]{m['title']}[/bold]")
    console.print(f"  format={m['format']}  lang={m['lang']}  duration={m['duration_s']:.1f}s")
    console.print(f"  tickers={[t['ticker'] for t in m['tickers']]}")
    console.print()

    table = Table(show_header=True, header_style="bold cyan")
    table.add_column("Time", width=10)
    table.add_column("Score", width=6, justify="right")
    table.add_column("Source", width=10)
    table.add_column("Title / attribution", width=40)
    table.add_column("Intent", width=50)
    for shot in m["shots"]:
        table.add_row(
            f"{shot['start_s']:.1f}-{shot['end_s']:.1f}",
            f"{shot['relevance']:.2f}",
            shot["source"],
            (shot["title"] or shot["attribution"] or "")[:40],
            shot["intent"][:50],
        )
    console.print(table)

    if len(m["shots"]) < len(m["plan_sections"]):
        gap = len(m["plan_sections"]) - len(m["shots"])
        console.print(f"[yellow]Note: {gap} section(s) had no usable image — fallback bg shown.[/yellow]")


@cli.command("costs")
@click.option("--days", default=30, type=int, help="Look back this many days.")
def costs_cmd(days: int) -> None:
    """Show API spend / quota usage rolled up by provider and by video."""
    from datetime import datetime, timedelta
    from rich.table import Table

    from shorts.core.usage import spend_by_provider, spend_by_video

    since = datetime.utcnow() - timedelta(days=days)
    by_p = spend_by_provider(since=since)
    by_v = spend_by_video(since=since)
    total = sum(b["cost_usd"] for b in by_p.values())

    console.print(f"[bold]Spend last {days}d:[/bold]  ${total:.4f}")
    console.print()

    t = Table(title="By provider", show_header=True, header_style="bold cyan")
    t.add_column("Provider"); t.add_column("Events", justify="right"); t.add_column("Units", justify="right")
    t.add_column("In tokens", justify="right"); t.add_column("Out tokens", justify="right")
    t.add_column("Cost", justify="right")
    for p, b in sorted(by_p.items(), key=lambda x: -x[1]["cost_usd"]):
        t.add_row(p, str(b["events"]), str(b["units"]),
                  str(b["units_in"] or "-"), str(b["units_out"] or "-"),
                  f"${b['cost_usd']:.4f}")
    console.print(t)

    if by_v:
        console.print()
        t = Table(title="By video", show_header=True, header_style="bold cyan")
        t.add_column("Video"); t.add_column("Events", justify="right"); t.add_column("Cost", justify="right")
        t.add_column("Top providers")
        for v, b in sorted(by_v.items(), key=lambda x: -x[1]["cost_usd"]):
            label = v or "[dim](unattributed)[/dim]"
            top = ", ".join(f"{p}:${c:.3f}" for p, c in
                            sorted(b["by_provider"].items(), key=lambda x: -x[1])[:4])
            t.add_row(label, str(b["events"]), f"${b['cost_usd']:.4f}", top)
        console.print(t)


@cli.command("dashboard")
@click.option("--port", default=8765, type=int)
@click.option("--host", default="127.0.0.1")
def dashboard_cmd(host: str, port: int) -> None:
    """Run the review + cost dashboard."""
    import uvicorn
    uvicorn.run("shorts.core.dashboard.factory:app", host=host, port=port, log_level="info")


@cli.command("info")
def info_cmd() -> None:
    """Print resolved configuration (secrets masked)."""
    s = get_settings()

    def mask(v: str) -> str:
        if not v:
            return "[dim](unset)[/dim]"
        return v[:4] + "…" + v[-2:] if len(v) > 8 else "***"

    console.print(f"[bold]stocks-reels[/bold] v{__version__}")
    console.print(f"  project_root        : {s.project_root}")
    console.print(f"  db_url              : {s.db_url}")
    console.print(f"  output_dir          : {s.output_dir}")
    console.print(f"  claude_model        : {s.claude_model}")
    console.print(f"  anthropic_api_key   : {mask(s.anthropic_api_key)}")
    console.print(f"  elevenlabs_api_key  : {mask(s.elevenlabs_api_key)}")
    console.print(f"  pexels_api_key      : {mask(s.pexels_api_key)}")
    console.print(f"  newsapi_key         : {mask(s.newsapi_key)}")
    console.print(f"  finnhub_api_key     : {mask(s.finnhub_api_key)}")


@cli.group()
def topic() -> None:
    """Topic picker commands."""


@topic.command("pick")
@click.option("--lang", default="en", type=click.Choice(["en"]))
@click.option("--universe-size", default=8, type=int, help="How many top movers to enrich.")
def topic_pick(lang: str, universe_size: int) -> None:
    """Pick today's topic from live market data."""
    from .data.topic_picker import pick_topic

    ctx = pick_topic(lang=lang, limit_universe=universe_size)
    if ctx is None:
        console.print("[red]No topic — market data unavailable.[/red]")
        return
    console.print(f"[bold]Top {len(ctx.candidates)} candidates:[/bold]")
    for c in ctx.candidates:
        console.print(f"  {c.ticker:6s} {c.change_pct:+6.2f}%  vol={c.volume or 0:>14,}  {c.name}")
    if ctx.suggested_links:
        console.print()
        console.print("[bold]Suggested causal links:[/bold]")
        for l in ctx.suggested_links[:6]:
            console.print(f"  {l.from_ticker} -> {l.to_ticker}  [dim]({l.reason})[/dim]")


@topic.command("quote")
@click.argument("ticker")
def topic_quote(ticker: str) -> None:
    """Print a live quote for one ticker (sanity check yfinance access)."""
    from .data.market import get_quote

    q = get_quote(ticker.upper())
    if q is None:
        console.print(f"[red]Could not fetch {ticker}.[/red]")
        return
    console.print(f"{q.ticker}  {q.name}")
    console.print(f"  price={q.price:.2f}  change={q.change_pct:+.2f}%  volume={q.volume:,}")
    console.print(f"  sector={q.sector}  industry={q.industry}")
    console.print(f"  ohlc samples: {len(q.ohlc_30d)} days")


@cli.command("earnings")
@click.option("--days", default=7, type=int, help="Look ahead this many days.")
@click.option("--ticker", "tickers", multiple=True, help="Limit to these tickers (repeatable).")
def earnings_cmd(days: int, tickers: tuple[str, ...]) -> None:
    """List companies in the universe reporting earnings within the window."""
    from rich.table import Table

    from .data.earnings import upcoming_earnings

    events = upcoming_earnings(list(tickers) or None, days=days)
    if not events:
        console.print(f"[yellow]No upcoming reporters in the next {days}d "
                      f"(or market data unavailable).[/yellow]")
        return

    t = Table(title=f"Earnings in next {days}d", show_header=True, header_style="bold cyan")
    t.add_column("Date"); t.add_column("In", justify="right"); t.add_column("Ticker")
    t.add_column("EPS est", justify="right"); t.add_column("When")
    for ev in events:
        t.add_row(
            ev.report_date.isoformat(), f"{ev.days_away}d", ev.ticker,
            f"{ev.eps_estimate:.2f}" if ev.eps_estimate is not None else "-",
            ev.when or "-",
        )
    console.print(t)


@cli.command("render-fixture")
@click.argument("name")
@click.option("--lang", default="en", type=click.Choice(["en"]))
def render_fixture(name: str, lang: str) -> None:
    """Render a checked-in fixture script end-to-end.

    Calls live TTS (edge-tts by default — free, no key needed) to synthesize
    the narration, then composes the video. Output: data/output/<name>_<lang>.mp4.
    """
    from .compose import compose_video
    from .script.writer import write_script_from_fixture
    from .voice.tts import synthesize

    s = get_settings()
    fixture_path = Path(__file__).resolve().parent / "tests" / "fixtures" / f"script_{name}_{lang}.json"
    if not fixture_path.exists():
        console.print(f"[red]Fixture not found: {fixture_path}[/red]")
        raise SystemExit(1)

    from .pipeline import emit_review_state

    script = write_script_from_fixture(fixture_path)
    slug = f"{name}_{lang}"
    work_dir = s.output_dir / slug
    # Compose straight into the review v1/short.mp4 path so the dashboard lists it.
    out_mp4 = emit_review_state(slug=slug, script=script, creator_handle=name)

    console.print(f"[bold]Rendering[/bold] {name} ({lang}) -> {out_mp4}")
    console.print(f"  format         : {script.format}")
    console.print(f"  tickers        : {[t.ticker for t in script.tickers]}")
    console.print(f"  script beats   : {len(script.beats)}")
    console.print(f"  tts provider   : {s.tts_provider}")

    text = script.narration_text()
    console.print(f"  narration chars: {len(text)}")
    tts = synthesize(text=text, lang=lang, out_dir=work_dir)
    console.print(f"  audio duration : {tts.duration_s:.2f}s")
    console.print(f"  word timings   : {len(tts.words)}")

    compose_video(script=script, tts=tts, out_path=out_mp4)
    console.print(f"[green]Done.[/green] {out_mp4}")


@cli.command("regen")
@click.argument("slug")
@click.option("--lang", default="en", type=click.Choice(["en"]))
@click.option("--note", default="", help="Reviewer guidance; if omitted, uses the clip's pending comments.")
def regen_cmd(slug: str, lang: str, note: str) -> None:
    """Re-render a clip as a new version, addressing reviewer feedback.

    Guidance is taken from --note, or (when omitted) from the clip's comments
    that target the current version. Used by the dashboard's per-clip comment box.
    """
    from shorts.core.reviews import ReviewStore
    from .pipeline import regenerate_clip

    store = ReviewStore("stocks")
    guidance = note.strip()
    if not guidance:
        item = store.load(slug)
        if item is None:
            console.print(f"[red]Clip {slug} not found.[/red]")
            raise SystemExit(1)
        pending = [c.text for c in item.comments if c.version_at_time >= item.current_version]
        guidance = "\n".join(f"- {t}" for t in pending)

    if not guidance:
        console.print("[yellow]No guidance/comments to act on — nothing to regenerate.[/yellow]")
        return

    console.print(f"[bold]Regenerating[/bold] {slug} with guidance:\n{guidance}")
    result = regenerate_clip(slug, lang=lang, guidance=guidance)
    if result is None:
        store.mark_status(slug, "ready")
        console.print(
            "[red]Can't improve this clip — it has no completed render on record "
            "(it failed mid-render). Delete it (✕) and generate a fresh one "
            "instead.[/red]"
        )
        raise SystemExit(1)
    console.print(f"[green]Done.[/green] New version at {result.mp4_path}")


@cli.command("render-idea")
@click.argument("idea_id")
@click.option("--lang", default="en", type=click.Choice(["en"]))
def render_idea_cmd(idea_id: str, lang: str) -> None:
    """Render one evergreen backlog idea on demand → stage it for review.

    Builds a prompt-only PlannedVideo (no tickers; the writer picks an explainer
    format), renders it, and flips the idea to `done` on success.
    """
    from datetime import date

    from .planner import store as plan_store
    from .planner.models import IdeaItem, PlannedVideo, TopicSeed
    from .pipeline import render_planned_item

    ideas = plan_store.load_ideas()
    idea: IdeaItem | None = next((i for i in ideas.items if i.id == idea_id), None)
    if idea is None:
        console.print(f"[red]Idea {idea_id} not found.[/red]")
        raise SystemExit(1)

    # Evergreen cue so the writer treats it as a concept explainer, not breaking news.
    theme = f"Educational explainer (evergreen, not tied to today's news): {idea.prompt}"
    item = PlannedVideo(
        scheduled_for=date.today(), status="planned", format="evergreen",
        topic_seed=TopicSeed(tickers=[], theme=theme),
        title_hint=idea.prompt, rationale=f"Evergreen idea: {idea.prompt[:80]}",
        source="idea",
    )
    console.print(f"[bold]Rendering idea[/bold] {idea_id}: {idea.prompt}")
    result = render_planned_item(item, lang=lang)
    if result is None:
        console.print("[red]Idea render failed — could not build a topic context.[/red]")
        raise SystemExit(1)

    idea.status = "done"
    idea.rendered_slug = result.slug
    plan_store.save_ideas(ideas)
    console.print(f"[green]Done.[/green] Staged {result.slug} at {result.mp4_path}")


# Sub-command stubs registered now so the surface is stable across phases.

@cli.command("run")
@click.option("--lang", default="en", type=click.Choice(["en"]))
@click.option("--force", is_flag=True, help="Re-render even if today's video already exists.")
def run_cmd(lang: str, force: bool) -> None:
    """Daily end-to-end pipeline: topic → script → tts → compose.

    STOPS before upload (per design). Review in the dashboard and click
    'Upload to staging' to publish.
    """
    from .pipeline import run_daily

    result = run_daily(lang=lang, force=force)
    if result is None:
        console.print("[yellow]Skipped — already rendered today, or no topic available.[/yellow]")
        return
    console.print(f"[green]Done.[/green] {result.mp4_path}")
    console.print(f"  topic_id={result.topic_id}  script_id={result.script_id}  render_id={result.render_id}")
    console.print(f"  duration={result.duration_s:.1f}s")
    console.print("Review in dashboard: http://127.0.0.1:8765/")


@cli.command("plan")
@click.option("--show/--no-show", default=True, help="Print the plan after building.")
def plan_cmd(show: bool) -> None:
    """Regenerate the content plan (data/stocks/plan.json) from live inputs."""
    from rich.table import Table

    from .planner.orchestrate import regenerate_plan

    plan = regenerate_plan()
    console.print(f"[green]Plan written:[/green] {len(plan.items)} items.")
    if not show:
        return
    t = Table(show_header=True, header_style="bold cyan")
    t.add_column("Date"); t.add_column("Format"); t.add_column("Len")
    t.add_column("Tickers"); t.add_column("Src"); t.add_column("Status")
    t.add_column("Rationale", overflow="fold")
    for it in plan.items:
        lo, hi = it.length_band
        t.add_row(
            it.scheduled_for.isoformat(), it.format, f"{lo}-{hi}s",
            ",".join(it.topic_seed.tickers) or "-", it.source, it.status,
            it.rationale,
        )
    console.print(t)


@cli.command("debt")
def debt_cmd() -> None:
    """List open content commitments (auto-extracted promises)."""
    from rich.table import Table

    from .planner import store as plan_store

    debt = plan_store.load_debt()
    if not debt.commitments:
        console.print("[dim]No commitments recorded.[/dim]")
        return
    t = Table(show_header=True, header_style="bold cyan")
    t.add_column("Status"); t.add_column("Tickers"); t.add_column("Trigger")
    t.add_column("Promise", overflow="fold"); t.add_column("From")
    for c in debt.commitments:
        t.add_row(c.status, ",".join(c.tickers) or "-", c.trigger or "-",
                  c.text, c.source_slug or "-")
    console.print(t)


@cli.group()
def autopilot() -> None:
    """Auto-pilot content generation."""


@autopilot.command("tick")
@click.option("--lang", default="en", type=click.Choice(["en"]))
@click.option("--replan/--no-replan", default=False,
              help="Rebuild the plan from current movers/earnings first "
                   "(use for scheduled morning/noon/evening runs so each picks "
                   "fresh content). Default: render the next already-planned item.")
@click.option("--max", "max_per_tick", type=int, default=1,
              help="Clips to render this run (default 1). The daily target is "
                   "still enforced across all runs.")
def autopilot_tick(lang: str, replan: bool, max_per_tick: int) -> None:
    """Render the next due clip(s), capped at the daily target.

    One scheduled run = one fresh clip. Run it a few times a day for a
    morning/noon/evening cadence.
    """
    from .planner.orchestrate import tick

    results = tick(lang=lang, replan=replan, max_per_tick=max_per_tick)
    if not results:
        console.print("[yellow]Nothing rendered (daily target reached or nothing due).[/yellow]")
        return
    console.print(f"[green]Rendered {len(results)} clip(s).[/green]")
    for r in results:
        console.print(f"  slug={r.slug}  duration={r.duration_s:.1f}s")


# YouTube OAuth now lives in the shared top-level CLI:
#   shorts auth youtube --pipeline stocks
# (uses core.publish with per-pipeline channel config). The old stocks-local
# `auth youtube` was removed — it imported a run_oauth_flow that no longer
# exists here after the move to shorts.core.publish.


@cli.command("publish")
@click.argument("slug")
@click.option("--lang", default="en", type=click.Choice(["en"]))
@click.option("--privacy", default="unlisted", type=click.Choice(["private", "unlisted", "public"]))
def publish_cmd(slug: str, lang: str, privacy: str) -> None:
    """Upload data/output/<slug>_<lang>.mp4 to YouTube (default: unlisted to staging)."""
    from .publish import upload_short

    s = get_settings()
    mp4 = s.output_dir / f"{slug}_{lang}.mp4"
    manifest = s.output_dir / f"{slug}_{lang}.manifest.json"
    if not mp4.exists():
        console.print(f"[red]No mp4 at {mp4}.[/red]")
        raise SystemExit(1)

    title = slug
    description = ""
    tags: list[str] = []
    if manifest.exists():
        import json
        m = json.loads(manifest.read_text(encoding="utf-8"))
        title = m.get("title", slug)
        # Build a description from the script's hashtags + a couple of facts.
        hashtags = m.get("description_hashtags") or []
        tags = [t.lstrip("#") for t in hashtags][:15]
        if hashtags:
            description = " ".join(hashtags)

    console.print(f"[bold]Uploading[/bold] {mp4.name} as {privacy!r} ...")
    result = upload_short(
        mp4_path=mp4, title=title, description=description,
        tags=tags, privacy=privacy,
    )
    console.print(f"[green]Done.[/green] {result.url}")


@cli.command("analytics")
@click.option("--days", default=30, type=int)
def analytics_cmd(days: int) -> None:
    """Pull view counts on promoted videos and store as Performance rows."""
    from .publish import pull_recent_performance, top_performers

    n = pull_recent_performance(lookback_days=days)
    console.print(f"[green]Wrote {n} performance rows.[/green]")
    top = top_performers(n=5, min_views=0)
    if top:
        console.print("[bold]Top performers:[/bold]")
        for p in top:
            console.print(f"  upload_id={p.upload_id}  views={p.views:,}  likes={p.likes:,}")


@cli.command("promote")
@click.argument("video_id")
@click.option("--privacy", default="public", type=click.Choice(["public", "unlisted", "private"]))
def promote_cmd(video_id: str, privacy: str) -> None:
    """Change the privacy of a previously-uploaded video (staging → public)."""
    from .publish import set_privacy

    set_privacy(video_id, privacy=privacy)
    console.print(f"[green]Set {video_id} → {privacy}.[/green]")


if __name__ == "__main__":
    cli()
