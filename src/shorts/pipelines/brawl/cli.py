from __future__ import annotations

import json
import sys
from datetime import datetime
from pathlib import Path
from typing import Optional

import typer
from rich.console import Console

# Windows shells often use a non-UTF-8 codepage (cp1252, cp1255, etc.).
# Rich emits Unicode box-drawing chars that crash those encoders. Force UTF-8.
for stream in (sys.stdout, sys.stderr):
    if hasattr(stream, "reconfigure"):
        try:
            stream.reconfigure(encoding="utf-8", errors="replace")
        except Exception:
            pass

from . import config as cfg
from .discovery import hype_filter, youtube
from .clips import moment as moment_picker
from .edit import compose as edit_compose
from .publish import insights as insights_mod
from .publish import metadata as meta_mod

app = typer.Typer(add_completion=False, help="Brawl Stars shorts pipeline.")
console = Console()


@app.callback()
def _root() -> None:
    """Brawl Stars shorts pipeline."""


@app.command()
def discover(
    days: int = typer.Option(7, "--days", help="Lookback window in days."),
    top: int = typer.Option(10, "--top", help="How many candidates to display."),
    no_llm: bool = typer.Option(False, "--no-llm", help="Skip the Claude hype filter."),
    queries_file: Optional[Path] = typer.Option(
        None, "--queries-file", help="Override config/hype_terms.yaml."
    ),
) -> None:
    """Search YouTube, rank by view velocity + hype boost, optionally LLM-filter, print."""
    secrets = cfg.load_secrets(require_anthropic=not no_llm)
    config = cfg.load_yaml("config.yaml")
    hype = (
        _load_yaml_path(queries_file) if queries_file else cfg.load_yaml("hype_terms.yaml")
    )

    queries: list[str] = list(hype.get("search_queries", []))
    boost_terms: dict[str, float] = dict(hype.get("rank_boost_terms", {}))
    penalty_terms: dict[str, float] = dict(hype.get("rank_penalty_terms", {}))
    if not queries:
        raise typer.BadParameter("No search_queries configured.")

    disc_cfg = config.get("discovery", {})
    min_velocity = float(disc_cfg.get("min_view_velocity", 200))
    max_per_query = int(disc_cfg.get("max_results_per_query", 50))
    min_duration_s = int(disc_cfg.get("min_duration_s", 0))

    console.print(
        f"[bold]Searching[/bold] {len(queries)} queries, last [bold]{days}[/bold] day(s)..."
    )
    candidates = youtube.search_videos(
        api_key=secrets.youtube_api_key,
        queries=queries,
        lookback_days=days,
        max_results_per_query=max_per_query,
    )
    console.print(f"  {len(candidates)} unique videos hydrated")

    if min_duration_s > 0:
        long_enough = [c for c in candidates if c.duration_s >= min_duration_s]
        console.print(
            f"  {len(long_enough)} long enough "
            f"(≥{min_duration_s}s = {min_duration_s // 60}m)"
        )

    ranked = youtube.rank_candidates(
        candidates=candidates,
        boost_terms=boost_terms,
        penalty_terms=penalty_terms,
        min_velocity=min_velocity,
        min_duration_s=min_duration_s,
    )
    console.print(f"  {len(ranked)} above min velocity ({min_velocity:.0f} v/h)")

    if not no_llm and ranked:
        # Filter at most 2× top to save tokens.
        head = ranked[: max(top * 2, top)]
        llm_cfg = config.get("llm", {})
        console.print(f"  hype-filtering {len(head)} via {llm_cfg.get('model', 'claude')}...")
        decisions = hype_filter.filter_candidates(
            head,
            api_key=secrets.anthropic_api_key,
            model=llm_cfg.get("model", "claude-haiku-4-5-20251001"),
            max_tokens=int(llm_cfg.get("max_tokens", 2048)),
        )
        keep_ids = {d.video_id for d in decisions if d.keep}
        reason_by_id = {d.video_id: d.reason for d in decisions}
        ranked = [c for c in ranked if c.video_id in keep_ids or c not in head]
        # Annotate kept items with the model's reason for display.
        for c in ranked:
            r = reason_by_id.get(c.video_id, "")
            if r:
                c.score_rationale += f" — {r}"

    top_rows = ranked[:top]
    _render_results(top_rows)
    out_path = _write_results_json(top_rows)
    console.print(f"\n[bold]Saved[/bold] full results to [cyan]{out_path}[/cyan]")


@app.command("refresh-library")
def refresh_library_cmd(
    days: int = typer.Option(7, "--days", help="Lookback window in days."),
    top: int = typer.Option(12, "--top", help="How many candidates to pin as auto entries."),
    no_llm: bool = typer.Option(True, "--no-llm/--llm", help="Skip the Claude hype filter (default: skip, cheaper)."),
) -> None:
    """Populate the dashboard source-video library with long-form discovery hits.

    Replaces the previous 'auto' entries; manually-pinned videos are preserved.
    The dashboard's 'refresh from discovery' button shells out to this.
    """
    from datetime import datetime as _dt
    from . import library as lib_mod

    secrets = cfg.load_secrets(require_anthropic=not no_llm)
    config = cfg.load_yaml("config.yaml")
    hype = cfg.load_yaml("hype_terms.yaml")

    queries: list[str] = list(hype.get("search_queries", []))
    boost_terms: dict[str, float] = dict(hype.get("rank_boost_terms", {}))
    penalty_terms: dict[str, float] = dict(hype.get("rank_penalty_terms", {}))
    disc_cfg = config.get("discovery", {})
    min_velocity = float(disc_cfg.get("min_view_velocity", 200))
    max_per_query = int(disc_cfg.get("max_results_per_query", 50))
    min_duration_s = int(disc_cfg.get("min_duration_s", 0))

    console.print(f"[bold]Refreshing library[/bold] — {len(queries)} queries, last {days}d...")
    candidates = youtube.search_videos(
        api_key=secrets.youtube_api_key, queries=queries,
        lookback_days=days, max_results_per_query=max_per_query,
    )
    ranked = youtube.rank_candidates(
        candidates=candidates, boost_terms=boost_terms, penalty_terms=penalty_terms,
        min_velocity=min_velocity, min_duration_s=min_duration_s,
    )
    if not no_llm and ranked:
        head = ranked[: max(top * 2, top)]
        llm_cfg = config.get("llm", {})
        decisions = hype_filter.filter_candidates(
            head, api_key=secrets.anthropic_api_key,
            model=llm_cfg.get("model", "claude-haiku-4-5-20251001"),
            max_tokens=int(llm_cfg.get("max_tokens", 2048)),
        )
        keep_ids = {d.video_id for d in decisions if d.keep}
        ranked = [c for c in ranked if c.video_id in keep_ids or c not in head]

    now = _dt.now().isoformat(timespec="seconds")
    entries = [
        lib_mod.LibraryEntry(
            video_id=c.video_id, url=c.url, title=c.title, channel=c.channel_title,
            duration_s=c.duration_s, source="auto", added_at=now, rationale=c.score_rationale,
        )
        for c in ranked[:top]
    ]
    lib_mod.replace_auto(entries)
    console.print(f"[green]Library refreshed.[/green] {len(entries)} auto entries (manual pins kept).")


@app.command("pick-moment")
def pick_moment_cmd(
    url_or_id: str = typer.Argument(..., help="YouTube URL or bare video ID."),
    clip_len: int = typer.Option(25, "--clip-len", help="Target clip length in seconds."),
    max_attempts: int = typer.Option(
        4, "--max-attempts", help="Max candidate clusters to try before giving up."
    ),
) -> None:
    """Find a vision-validated gameplay moment inside a single video.

    Pulls top comments, clusters timestamps, downloads each candidate window,
    samples frames, and Claude-checks them for purity (no facecam, no menus,
    no people). Returns the first window that passes.
    """
    import re

    secrets = cfg.load_secrets(require_anthropic=True)
    config = cfg.load_yaml("config.yaml")

    # Accept either a full URL or a bare 11-char ID.
    m = re.search(r"(?:v=|youtu\.be/|/shorts/|/embed/)([A-Za-z0-9_-]{11})", url_or_id)
    video_id = m.group(1) if m else url_or_id
    if not re.fullmatch(r"[A-Za-z0-9_-]{11}", video_id):
        raise typer.BadParameter(f"Could not parse a video ID from {url_or_id!r}")

    # Fetch duration (+ title for nicer output) via the same hydration the
    # discover command uses — one tiny videos.list call.
    cands = youtube.search_videos.__globals__["_build_client"](secrets.youtube_api_key)
    resp = (
        cands.videos()
        .list(part="snippet,contentDetails", id=video_id)
        .execute()
    )
    if not resp.get("items"):
        raise typer.BadParameter(f"Video {video_id} not found or unavailable.")
    item = resp["items"][0]
    title = item["snippet"]["title"]
    duration_s = youtube._parse_iso8601_duration(item["contentDetails"]["duration"])

    console.print(f"[bold]Video:[/bold] {title}")
    console.print(f"[dim]  id={video_id}  duration={duration_s}s ({duration_s // 60}m)[/dim]\n")

    llm_cfg = config.get("llm", {})
    result = moment_picker.pick_moment(
        video_id=video_id,
        video_duration_s=duration_s,
        youtube_api_key=secrets.youtube_api_key,
        anthropic_api_key=secrets.anthropic_api_key,
        clip_len_s=clip_len,
        max_attempts=max_attempts,
        vision_model=llm_cfg.get("vision_model", "claude-sonnet-4-5"),
    )

    if result is None or result.end_s == result.start_s:
        console.print(f"[red]No moment found.[/red] {result.rationale if result else ''}")
        if result and result.attempts:
            console.print("[dim]Attempts:[/dim]")
            for a in result.attempts:
                console.print(f"  {a}")
        return

    console.print(
        f"[bold green]Picked moment:[/bold green] "
        f"[{result.start_s}s → {result.end_s}s]  "
        f"confidence={result.confidence:.2f}"
    )
    console.print(f"[dim]  {result.rationale}[/dim]")
    if result.facecam_corner != "none":
        console.print(
            f"[yellow]  facecam detected in {result.facecam_corner} — "
            f"step 3 (crop) must remove it.[/yellow]"
        )
    if result.clip_path:
        console.print(f"[cyan]  clip: {result.clip_path}[/cyan]")
    if result.frame_paths:
        console.print(f"[cyan]  sampled frames: {result.frame_paths[0].parent}[/cyan]")

    if len(result.attempts) > 1:
        console.print(f"\n[dim]Took {len(result.attempts)} attempt(s):[/dim]")
        for a in result.attempts:
            mark = "✓" if a.get("clean") else "✗"
            console.print(
                f"  {mark} #{a['rank']} center={a['center_s']}s "
                f"mentions={a['mentions']} — {a.get('reason', a.get('error', '?'))}"
            )


@app.command("make-short")
def make_short_cmd(
    url_or_id: str = typer.Argument(..., help="YouTube URL or 11-char video ID."),
    clip_len: int = typer.Option(25, "--clip-len", help="Clip length in seconds."),
    max_attempts: int = typer.Option(3, "--max-attempts", help="Cluster attempts."),
    start: int = typer.Option(-1, "--start", help="Manual cut start (seconds). With --end, skips moment detection."),
    end: int = typer.Option(-1, "--end", help="Manual cut end (seconds). With --start, skips moment detection."),
) -> None:
    """Full pipeline: discover the moment, cut, caption, hook, credit → short.mp4.

    Runs end-to-end and writes data/output/<run_id>/{short.mp4, metadata.json}.
    """
    import re

    secrets = cfg.load_secrets(require_anthropic=True)
    config = cfg.load_yaml("config.yaml")

    m = re.search(r"(?:v=|youtu\.be/|/shorts/|/embed/)([A-Za-z0-9_-]{11})", url_or_id)
    video_id = m.group(1) if m else url_or_id
    if not re.fullmatch(r"[A-Za-z0-9_-]{11}", video_id):
        raise typer.BadParameter(f"Could not parse a video ID from {url_or_id!r}")

    # Hydrate title/channel/duration.
    yt_client = youtube.search_videos.__globals__["_build_client"](secrets.youtube_api_key)
    resp = (
        yt_client.videos()
        .list(part="snippet,contentDetails", id=video_id)
        .execute()
    )
    if not resp.get("items"):
        raise typer.BadParameter(f"Video {video_id} not found.")
    item = resp["items"][0]
    title = item["snippet"]["title"]
    channel = item["snippet"]["channelTitle"]
    channel_id = item["snippet"]["channelId"]
    duration_s = youtube._parse_iso8601_duration(item["contentDetails"]["duration"])
    source_url = f"https://www.youtube.com/watch?v={video_id}"

    console.print(f"[bold]Video:[/bold] {title}")
    console.print(f"[dim]  @{channel}  •  {duration_s}s ({duration_s // 60}m)[/dim]\n")

    llm_cfg = config.get("llm", {})

    # ---- Stage A: moment detection -------------------------------------------
    manual = start >= 0 and end >= 0
    if manual:
        if end <= start:
            raise typer.BadParameter(f"--end ({end}s) must be greater than --start ({start}s).")
        console.print(f"[bold cyan]Stage 1/3:[/bold cyan] manual cut [{start}s → {end}s] (skipping detection)...")
        moment = moment_picker.pick_moment_manual(
            video_id=video_id,
            start_s=start,
            end_s=end,
            anthropic_api_key=secrets.anthropic_api_key,
            vision_model=llm_cfg.get("vision_model", "claude-sonnet-4-5"),
        )
    else:
        console.print("[bold cyan]Stage 1/3:[/bold cyan] finding the moment...")
        moment = moment_picker.pick_moment(
            video_id=video_id,
            video_duration_s=duration_s,
            youtube_api_key=secrets.youtube_api_key,
            anthropic_api_key=secrets.anthropic_api_key,
            clip_len_s=clip_len,
            max_attempts=max_attempts,
            vision_model=llm_cfg.get("vision_model", "claude-sonnet-4-5"),
        )
    if moment is None or moment.end_s == moment.start_s or moment.clip_path is None:
        console.print(f"[red]✗ No clean moment in this video.[/red]")
        if moment:
            console.print(f"[dim]  {moment.rationale}[/dim]")
        raise typer.Exit(code=1)
    console.print(
        f"  ✓ [{moment.start_s}s → {moment.end_s}s]  confidence={moment.confidence:.2f}"
    )

    # ---- Stage B: compose v1 -------------------------------------------------
    run_id = f"{video_id}_{moment.start_s}-{moment.end_s}"
    console.print(f"\n[bold cyan]Stage 2/3:[/bold cyan] composing short ({run_id})...")
    insights_text = insights_mod.format_for_prompt()
    if insights_text:
        console.print(f"  [dim]applying {insights_text.count(chr(10)) + 1} accumulated insights[/dim]")
    inp = edit_compose.ComposeInput(
        run_id=run_id,
        version=1,
        raw_clip_path=moment.clip_path,
        facecam_corner=moment.facecam_corner,
        creator_handle=channel,
        hook_context=f"{title} — {moment.rationale}",
        anthropic_api_key=secrets.anthropic_api_key,
        text_model=llm_cfg.get("model", "claude-haiku-4-5-20251001"),
        insights_text=insights_text,
    )
    composed = edit_compose.compose(inp)
    console.print(f"  ✓ hook: \"{composed.hook_text}\"")
    console.print(f"  ✓ captions: {len(composed.caption_texts)} hype overlays")
    console.print(f"  ✓ short: [cyan]{composed.short_path}[/cyan]")

    # ---- Stage C: state.json -------------------------------------------------
    console.print(f"\n[bold cyan]Stage 3/3:[/bold cyan] writing review state...")
    title_str, description_str = meta_mod.generate_title_and_description(
        creator=channel,
        source_url=source_url,
        hook_text=composed.hook_text,
        moment_context=f"{title} — {moment.rationale}",
        api_key=secrets.anthropic_api_key,
        insights_text=insights_text,
        model=llm_cfg.get("model", "claude-haiku-4-5-20251001"),
    )

    from datetime import datetime as _dt
    now = _dt.now().isoformat(timespec="seconds")

    item = meta_mod.ReviewItem(
        run_id=run_id,
        source_url=source_url,
        creator_handle=channel,
        creator_channel_id=channel_id,
        source_title=title,
        moment_start_s=moment.start_s,
        moment_end_s=moment.end_s,
        moment_confidence=moment.confidence,
        moment_rationale=moment.rationale,
        status="ready",
        current_version=1,
        versions=[
            meta_mod.Version(
                v=1,
                title=title_str,
                description=description_str,
                hook_text=composed.hook_text,
                captions=composed.caption_texts,
                tags=list(meta_mod.DEFAULT_TAGS),
                created_at=now,
            )
        ],
        comments=[],
        created_at=now,
        updated_at=now,
    )
    meta_mod.save(item)
    console.print(f"  ✓ title: [bold]{title_str}[/bold]")
    console.print(f"  ✓ state: [cyan]{edit_compose.OUTPUT_ROOT / run_id / 'state.json'}[/cyan]")

    console.print(
        f"\n[bold green]Done.[/bold green] Review at "
        f"[link=http://localhost:8000/run/{run_id}]http://localhost:8000/run/{run_id}[/link]"
    )


@app.command("regenerate")
def regenerate_cmd(
    run_id: str = typer.Argument(..., help="Existing run id."),
) -> None:
    """Generate the next version of an existing run, using accumulated comments
    as feedback context. Used by the review server after a reviewer comments."""
    secrets = cfg.load_secrets(require_anthropic=True)
    config = cfg.load_yaml("config.yaml")
    llm_cfg = config.get("llm", {})

    item = meta_mod.load(run_id)
    if item is None:
        raise typer.BadParameter(f"Run {run_id} not found.")

    # Find the cached raw clip used by v1.
    clip_path = (
        edit_compose.REPO_ROOT
        / "data"
        / "clip_cache"
        / f"{run_id.rsplit('_', 1)[0]}_{item.moment_start_s}-{item.moment_end_s}.mp4"
    )
    if not clip_path.exists():
        raise typer.BadParameter(
            f"Raw clip missing at {clip_path}. Re-run make-short to refetch."
        )

    next_v = item.current_version + 1
    console.print(f"Regenerating [bold]v{next_v}[/bold] of {run_id}...")

    # Feedback = all comments since v1, formatted.
    feedback_lines = [
        f"v{c.version_at_time}: {c.text}" for c in item.comments
    ]
    feedback_text = "\n".join(feedback_lines)
    insights_text = insights_mod.format_for_prompt()

    item.status = "processing"
    meta_mod.save(item)
    try:
        inp = edit_compose.ComposeInput(
            run_id=run_id,
            version=next_v,
            raw_clip_path=clip_path,
            facecam_corner="none",
            creator_handle=item.creator_handle,
            hook_context=f"{item.source_title} — {item.moment_rationale}",
            anthropic_api_key=secrets.anthropic_api_key,
            text_model=llm_cfg.get("model", "claude-haiku-4-5-20251001"),
            insights_text=insights_text,
            feedback_text=feedback_text,
        )
        composed = edit_compose.compose(inp)
        title_str, description_str = meta_mod.generate_title_and_description(
            creator=item.creator_handle,
            source_url=item.source_url,
            hook_text=composed.hook_text,
            moment_context=f"{item.source_title} — {item.moment_rationale}",
            api_key=secrets.anthropic_api_key,
            insights_text=insights_text,
            feedback_text=feedback_text,
            model=llm_cfg.get("model", "claude-haiku-4-5-20251001"),
        )
        from datetime import datetime as _dt
        item.versions.append(
            meta_mod.Version(
                v=next_v,
                title=title_str,
                description=description_str,
                hook_text=composed.hook_text,
                captions=composed.caption_texts,
                tags=list(meta_mod.DEFAULT_TAGS),
                created_at=_dt.now().isoformat(timespec="seconds"),
            )
        )
        item.current_version = next_v
        item.status = "ready"
        meta_mod.save(item)
        console.print(f"[bold green]✓ v{next_v} ready.[/bold green]")
    except Exception as e:
        item.status = "ready"  # back to ready so reviewer can comment again
        meta_mod.save(item)
        raise


@app.command("review-server")
def review_server_cmd(
    host: str = typer.Option("127.0.0.1", "--host"),
    port: int = typer.Option(8000, "--port"),
) -> None:
    """Start the review web app for approving/rejecting generated shorts."""
    import uvicorn

    uvicorn.run("shorts.core.dashboard.factory:app", host=host, port=port, reload=False)


def _render_results(rows: list[youtube.Candidate]) -> None:
    console.print()
    for i, c in enumerate(rows, 1):
        console.print(f"[bold yellow]#{i}[/bold yellow]  [bold]{c.title}[/bold]")
        console.print(
            f"     [dim]{c.channel_title}  •  {c.view_count:,} views  •  "
            f"{c.age_hours:.0f}h old  •  {int(c.duration_s)}s long[/dim]"
        )
        console.print(
            f"     [green]score {c.score:,.0f}[/green]  "
            f"[dim]({c.score_rationale})[/dim]"
        )
        console.print(f"     [link={c.url}]{c.url}[/link]")
        console.print()


def _write_results_json(rows: list[youtube.Candidate]) -> Path:
    from shorts.config import pipeline_data_dir
    out_dir = pipeline_data_dir("brawl") / "discover"
    out_dir.mkdir(parents=True, exist_ok=True)
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    path = out_dir / f"discover_{ts}.json"
    payload = [
        {
            "rank": i,
            "video_id": c.video_id,
            "url": c.url,
            "title": c.title,
            "channel": c.channel_title,
            "channel_id": c.channel_id,
            "published_at": c.published_at.isoformat(),
            "age_hours": round(c.age_hours, 1),
            "duration_s": c.duration_s,
            "views": c.view_count,
            "likes": c.like_count,
            "comments": c.comment_count,
            "velocity_vph": round(c.velocity, 1),
            "boost": round(c.boost, 3),
            "score": round(c.score, 1),
            "rationale": c.score_rationale,
            "matched_queries": sorted(c.matched_queries),
        }
        for i, c in enumerate(rows, 1)
    ]
    path.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")
    return path


def _load_yaml_path(path: Path) -> dict:
    import yaml

    with path.open("r", encoding="utf-8") as f:
        data = yaml.safe_load(f)
    if not isinstance(data, dict):
        raise typer.BadParameter(f"{path} must be a YAML mapping")
    return data


if __name__ == "__main__":
    app()
