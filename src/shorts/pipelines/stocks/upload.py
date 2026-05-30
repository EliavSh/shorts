"""stocks YouTube upload — same pattern as brawl, different channel.

Stocks does not yet emit ReviewStore state.json files (legacy uses
manifest.json). Until that's wired, this command works only after a fresh
render that calls store.save(). For now it just attempts the lookup and gives
a clear error if missing.
"""
from __future__ import annotations

from rich.console import Console

from shorts.config import load_secrets
from shorts.core.publish import auth_from_env, upload_short
from shorts.core.reviews import ReviewStore, latest_version

console = Console()


def upload(slug: str, *, dry_run: bool = False) -> None:
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
    console.print(f"  title: {version.title}")
    console.print(f"  mp4:   {mp4}")

    if dry_run:
        console.print("[yellow]dry-run — skipping actual upload[/yellow]")
        return

    result = upload_short(
        auth=auth,
        mp4_path=mp4,
        title=version.title,
        description=version.description,
        tags=version.tags,
        privacy="unlisted",
        pipeline="stocks",
    )
    console.print(f"[green]✓ uploaded:[/green] {result.url}")
