"""Playwright browser session manager — handles persistent sessions with auto-refresh."""
import asyncio
import json
import logging
from pathlib import Path
from typing import Optional

from playwright.async_api import async_playwright, BrowserContext, Page

logger = logging.getLogger(__name__)

SESSIONS_DIR = Path("data/sessions")


async def get_context(
    site_key: str,
    headless: bool = True,
    force_fresh: bool = False,
) -> tuple:
    """Get a persistent browser context, reusing a saved session if available.

    Returns (playwright, browser, context) — caller must close all three.
    """
    SESSIONS_DIR.mkdir(parents=True, exist_ok=True)
    session_file = SESSIONS_DIR / f"{site_key}.json"

    playwright = await async_playwright().start()
    browser = await playwright.chromium.launch(
        headless=headless,
        args=[
            "--no-sandbox",
            "--disable-blink-features=AutomationControlled",
            "--disable-dev-shm-usage",
        ],
    )

    # Load existing session cookies if available
    storage_state = None
    if session_file.exists() and not force_fresh:
        logger.info(f"Loading saved session for {site_key}")
        storage_state = str(session_file)

    context = await browser.new_context(
        storage_state=storage_state,
        user_agent=(
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/124.0.0.0 Safari/537.36"
        ),
        viewport={"width": 1280, "height": 800},
        locale="he-IL",
        timezone_id="Asia/Jerusalem",
    )

    return playwright, browser, context


async def save_session(context: BrowserContext, site_key: str) -> None:
    """Save browser session (cookies + localStorage) to disk."""
    SESSIONS_DIR.mkdir(parents=True, exist_ok=True)
    session_file = SESSIONS_DIR / f"{site_key}.json"
    await context.storage_state(path=str(session_file))
    logger.info(f"Session saved: {session_file}")


async def close_all(playwright, browser, context) -> None:
    """Close context, browser, and playwright cleanly."""
    await context.close()
    await browser.close()
    await playwright.stop()
