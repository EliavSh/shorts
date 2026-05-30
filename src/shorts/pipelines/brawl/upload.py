"""brawl YouTube upload — reads a ReviewStore item, uploads the latest version
to the brawl-specific YouTube channel.
"""
from __future__ import annotations

from rich.console import Console

from shorts.config import load_secrets
from shorts.core.publish import auth_from_env, upload_short
from shorts.core.reviews import ReviewStore, latest_version

console = Console()


def upload(run_id: str, *, dry_run: bool = False) -> None:
    load_secrets(require_anthropic=False)  # ensure .env loaded
    store = ReviewStore("brawl")
    item = store.load(run_id)
    if item is None:
        raise FileNotFoundError(f"brawl run {run_id} not found.")

    version = latest_version(item)
    if version is None:
        raise RuntimeError(f"{run_id} has no rendered versions to upload.")

    mp4 = store.short_path(run_id, version.v)
    if not mp4.exists():
        raise FileNotFoundError(f"Missing mp4 at {mp4}")

    auth = auth_from_env("brawl")
    console.print(f"[bold]Uploading[/bold] {run_id} v{version.v} → channel={auth.channel_id or '(default)'}")
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
        pipeline="brawl",
    )
    console.print(f"[green]✓ uploaded:[/green] {result.url}")
