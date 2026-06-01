"""stocks YouTube upload — same pattern as brawl, different channel.

Stocks does not yet emit ReviewStore state.json files (legacy uses
manifest.json). Until that's wired, this command works only after a fresh
render that calls store.save(). For now it just attempts the lookup and gives
a clear error if missing.
"""
from __future__ import annotations

import json
import shutil

from rich.console import Console

from shorts.config import load_secrets
from shorts.core.publish import auth_from_env, upload_short
from shorts.core.reviews import ReviewStore, latest_version

console = Console()


def _manifest_meta(mp4) -> tuple[str, list[str], float | None]:
    """Best-effort (format, [tickers], cost_usd) from the render's sidecar
    manifest. Read before the artifacts are purged so the cost survives in the
    published ledger."""
    manifest = mp4.with_suffix(".manifest.json")
    if not manifest.exists():
        return "", [], None
    try:
        m = json.loads(manifest.read_text(encoding="utf-8"))
        tickers = [t.get("ticker", "") for t in m.get("tickers", []) if t.get("ticker")]
        cost = (m.get("cost_breakdown") or {}).get("total_usd")
        return m.get("format", ""), tickers, cost
    except Exception:
        return "", [], None


def upload(slug: str, *, dry_run: bool = False, privacy: str = "unlisted") -> None:
    load_secrets(require_anthropic=False)
    store = ReviewStore("stocks")
    item = store.load(slug)
    if item is None:
        raise FileNotFoundError(
            f"stocks run {slug} not found in ReviewStore. "
            "Re-render after the stocks pipeline learns to emit state.json."
        )

    version = latest_version(item)
    if version is None:
        raise RuntimeError(f"{slug} has no rendered versions to upload.")

    mp4 = store.short_path(slug, version.v)
    if not mp4.exists():
        raise FileNotFoundError(f"Missing mp4 at {mp4}")

    auth = auth_from_env("stocks")
    console.print(f"[bold]Uploading[/bold] {slug} v{version.v} → channel={auth.channel_id or '(default)'}")
    console.print(f"  title:   {version.title}")
    console.print(f"  privacy: {privacy}")
    console.print(f"  mp4:     {mp4}")

    if dry_run:
        console.print("[yellow]dry-run — skipping actual upload[/yellow]")
        return

    result = upload_short(
        auth=auth,
        mp4_path=mp4,
        title=version.title,
        description=version.description,
        tags=version.tags,
        privacy=privacy,
        pipeline="stocks",
    )
    console.print(f"[green]✓ uploaded:[/green] {result.url}")

    # Record the durable trace, then purge the heavy artifacts. The dashboard is
    # a staging surface: once a clip is safely on YouTube we keep only the ledger
    # line (sector/format/tickers) for the planner + stats, and reclaim the disk.
    fmt, tickers, cost_usd = _manifest_meta(mp4)
    from .planner.published import record_published

    record_published(
        slug=slug, title=version.title, fmt=fmt, tickers=tickers,
        youtube_id=result.video_id, youtube_url=result.url, cost_usd=cost_usd,
    )
    run_dir = store.output_root / slug
    try:
        shutil.rmtree(run_dir)
        console.print(f"[green]✓ purged staged artifacts:[/green] {run_dir}")
    except Exception as e:
        console.print(f"[yellow]could not purge {run_dir}: {e}[/yellow]")
