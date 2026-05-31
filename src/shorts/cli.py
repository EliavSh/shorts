"""Top-level CLI dispatcher.

The brawl pipeline uses Typer; the stocks pipeline uses Click. We build the
top-level group in Click (Typer is built on Click anyway) so both pipelines
compose cleanly without forcing a rewrite of either.
"""
from __future__ import annotations

import sys

import click
import typer

# Force UTF-8 stdout/stderr — Windows shells default to non-UTF-8 codepages
# that crash Rich's box-drawing output.
for stream in (sys.stdout, sys.stderr):
    if hasattr(stream, "reconfigure"):
        try:
            stream.reconfigure(encoding="utf-8", errors="replace")
        except Exception:
            pass


@click.group(help="Shorts content engine — multi-pipeline edition.")
def app() -> None:
    pass


# ---------------------------------------------------------------------------
# Pipeline subcommands
# ---------------------------------------------------------------------------

# brawl is Typer — wrap as Click command via typer.main.get_command()
try:
    from shorts.pipelines.brawl.cli import app as _brawl_typer
    _brawl_click = typer.main.get_command(_brawl_typer)
    _brawl_click.help = "Brawl Stars gameplay pipeline."
    app.add_command(_brawl_click, name="brawl")
except ImportError as e:
    _brawl_err = str(e)

    @app.command("brawl")
    def _brawl_unavailable() -> None:
        raise click.ClickException(f"brawl pipeline unavailable: {_brawl_err}")


# stocks is Click — add directly
try:
    from shorts.pipelines.stocks.cli import cli as _stocks_cli
    _stocks_cli.help = "Finance Shorts pipeline."
    app.add_command(_stocks_cli, name="stocks")
except ImportError as e:
    _stocks_err = str(e)

    @app.command("stocks")
    def _stocks_unavailable() -> None:
        raise click.ClickException(f"stocks pipeline unavailable: {_stocks_err}")


# ---------------------------------------------------------------------------
# Shared commands
# ---------------------------------------------------------------------------

@app.command("dashboard")
@click.option("--host", default="127.0.0.1")
@click.option("--port", default=8000, type=int)
def dashboard_cmd(host: str, port: int) -> None:
    """Start the review dashboard (mounts both pipelines)."""
    import uvicorn

    uvicorn.run("shorts.core.dashboard.factory:app", host=host, port=port, reload=False)


@app.command("upload")
@click.argument("item_id")
@click.option("--pipeline", "-p", required=True, type=click.Choice(["brawl", "stocks"]))
@click.option("--dry-run", is_flag=True)
def upload_cmd(item_id: str, pipeline: str, dry_run: bool) -> None:
    """Upload an approved item to that pipeline's YouTube channel."""
    if pipeline == "brawl":
        from shorts.pipelines.brawl.upload import upload as brawl_upload
        brawl_upload(item_id, dry_run=dry_run)
    elif pipeline == "stocks":
        from shorts.pipelines.stocks.upload import upload as stocks_upload
        stocks_upload(item_id, dry_run=dry_run)


@app.command("auth")
@click.argument("provider", type=click.Choice(["youtube"]))
@click.option("--pipeline", "-p", required=True, type=click.Choice(["brawl", "stocks"]))
def auth_cmd(provider: str, pipeline: str) -> None:
    """One-time login that mints a YouTube refresh token for a pipeline.

    Opens a browser to authorize the channel, then saves the refresh token to
    <PIPELINE>_YOUTUBE_TOKEN_PATH. Run this locally (the cloud machine has no
    browser); the resulting token file is what gets shipped to Fly.
    """
    from rich.console import Console

    from shorts.config import load_secrets
    from shorts.core.publish import auth_from_env, run_oauth_flow

    console = Console()
    load_secrets(require_anthropic=False)
    auth = auth_from_env(pipeline)
    if not auth.client_secret_path.exists():
        raise click.ClickException(
            f"OAuth client secrets not found at {auth.client_secret_path}.\n"
            "Download the OAuth 2.0 Client ID (Desktop application) JSON from "
            "https://console.cloud.google.com/apis/credentials and save it there, "
            f"then set {pipeline.upper()}_YOUTUBE_CLIENT_SECRET_PATH in .env."
        )
    console.print(f"[bold]Authorizing {pipeline} YouTube channel…[/bold] a browser window will open.")
    path = run_oauth_flow(auth)
    console.print(f"[green]✓ Authorized.[/green] Token saved to {path}")
    console.print("Next: try a dry run — "
                  f"[cyan]shorts upload <slug> --pipeline {pipeline} --dry-run[/cyan]")


@app.command("costs")
@click.option("--pipeline", "-p", type=click.Choice(["brawl", "stocks"]), default=None)
@click.option("--days", default=30, type=int)
def costs_cmd(pipeline: str | None, days: int) -> None:
    """Cost rollup for one pipeline or both combined."""
    from rich.console import Console

    from shorts.core.usage.record import rollup

    rollup(pipeline=pipeline, days=days, console=Console())


@app.command("doctor")
def doctor_cmd() -> None:
    """Cross-pipeline health check: ffmpeg, keys, data dirs, configs."""
    from rich.console import Console

    from shorts.core.infra.doctor import run_checks

    run_checks(Console())


if __name__ == "__main__":
    app()
