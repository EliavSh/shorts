"""Operability alerting — Slack webhook + email fallback.

Used by orchestrators to alert on failures and by the dashboard to surface
quota warnings. Silently no-ops when no webhook is configured.
"""
from __future__ import annotations

import logging
import os

from .http_client import client as http_client

log = logging.getLogger(__name__)


def notify(text: str, *, level: str = "info", title: str | None = None) -> None:
    """Send a Slack notification. Levels: info | warn | error."""
    webhook = os.environ.get("SLACK_WEBHOOK_URL", "").strip()
    if not webhook:
        log.info("[alert/%s] %s", level, text)
        return

    emoji = {
        "info": ":information_source:",
        "warn": ":warning:",
        "error": ":rotating_light:",
    }.get(level, "")
    prefix = f"{emoji} *{title}*\n" if title else f"{emoji} "
    payload = {"text": f"{prefix}{text}"}
    try:
        with http_client(timeout=8.0) as c:
            c.post(webhook, json=payload).raise_for_status()
    except Exception as e:
        log.warning("Slack notify failed: %s", e)
