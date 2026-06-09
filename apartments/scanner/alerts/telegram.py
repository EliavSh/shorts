"""Telegram bot alerts for matching apartments + scrape ops."""
import logging
import os
from datetime import datetime, timedelta
from typing import Optional

import httpx

logger = logging.getLogger(__name__)

# Telegram bot token and chat ID from environment
TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID", "")


def send_alert(message: str, parse_mode: str = "HTML") -> bool:
    """Send a message via Telegram bot API.

    Returns True on 200 OK, False otherwise (and logs the failure).
    """
    if not TELEGRAM_BOT_TOKEN or not TELEGRAM_CHAT_ID:
        logger.warning(
            "Telegram not configured — TELEGRAM_BOT_TOKEN and TELEGRAM_CHAT_ID env vars required."
        )
        logger.info(f"[TELEGRAM (dry-run)] {message}")
        return False
    url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
    try:
        resp = httpx.post(
            url,
            data={
                "chat_id": TELEGRAM_CHAT_ID,
                "text": message,
                "parse_mode": parse_mode,
                "disable_web_page_preview": "true",
            },
            timeout=10,
        )
        if resp.status_code == 200:
            return True
        logger.error(f"Telegram API {resp.status_code}: {resp.text[:200]}")
        return False
    except Exception as e:
        logger.error(f"Telegram send failed: {e}")
        return False


# ── Sprint 2 helpers ──────────────────────────────────────────────────────────

def notify_captcha(source: str, refresh_url: str | None = None) -> bool:
    """Page the user when a scheduled scrape hits a CAPTCHA / session-expired wall."""
    body = (
        f"🔒 <b>{source} session expired / CAPTCHA blocked</b>\n\n"
        f"Screenshot follows. To fix, run on your local machine:\n"
        f"<code>python scripts/capture_madlan_session.py</code>\n"
        f"Then copy <code>data/sessions/{source}.json</code> to the server."
    )
    return send_alert(body)


def notify_run_summary(
    rows_by_source: dict[str, int],
    errors: list[str] | None = None,
    new_by_source: dict[str, int] | None = None,
) -> bool:
    """Post a short end-of-run summary.

    `new_by_source`, when provided, adds a `(+K new)` annotation per source so
    the user can tell at a glance how many of the rows are first-time inserts
    vs refreshes of already-tracked listings.
    """
    lines = ["✅ <b>Scrape cycle complete</b>"]
    for source, n in rows_by_source.items():
        new = (new_by_source or {}).get(source)
        suffix = f" (+{new:,} new)" if new is not None and new > 0 else ""
        lines.append(f"  • {source}: {n:,} rows{suffix}")
    if errors:
        lines.append("\n⚠️ Errors:")
        for e in errors[:5]:
            lines.append(f"  • {e[:120]}")
        if len(errors) > 5:
            lines.append(f"  …and {len(errors) - 5} more")
    return send_alert("\n".join(lines))


def format_listing_alert(listing: dict, classification: dict) -> str:
    """Format a listing as a Telegram message.

    Args:
        listing: Listing dict
        classification: Classification dict from matcher

    Returns:
        Formatted message string
    """
    address = listing.get("address", "?")
    city = listing.get("city", "?")
    rooms = listing.get("rooms", "?")
    sqm = listing.get("sqm", "?")
    price = listing.get("price", 0)
    price_per_sqm = classification.get("asking_price_per_sqm", 0)
    nadlan_price_per_sqm = classification.get("nadlan_median_price_per_sqm")
    gap = classification.get("gap_percent", 0)
    explanation = classification.get("explanation", "")

    message = (
        f"🏠 <b>New Deal Alert!</b>\n\n"
        f"<b>{address}</b>\n"
        f"{city}\n\n"
        f"📊 Specs:\n"
        f"  Rooms: {rooms}\n"
        f"  SQM: {sqm}\n"
        f"  Price: ₪{price:,}\n"
        f"  ₪/sqm: ₪{price_per_sqm:,.0f}\n\n"
        f"📈 Market:\n"
        f"  Nadlan ₪/sqm: ₪{nadlan_price_per_sqm:,.0f}\n"
        f"  Gap: {gap:.1f}%\n"
        f"  {explanation}\n\n"
        f"<b>This is a {classification['status'].upper()} opportunity!</b>"
    )
    return message


def send_listing_alert(listing: dict, classification: dict) -> bool:
    """Send a listing alert via Telegram.

    Args:
        listing: Listing dict
        classification: Classification dict from matcher

    Returns:
        True if sent successfully, False otherwise
    """
    message = format_listing_alert(listing, classification)
    return send_alert(message)


def send_deal_alerts(db) -> int:
    """Query listing_scores for top-5 deals and send Telegram alerts.

    Skips listings alerted within the last 7 days to prevent spam.
    Returns the number of alerts sent.
    """
    cutoff = (datetime.now() - timedelta(days=7)).isoformat()
    rows = db.execute(
        """
        SELECT ls.listing_id, ls.gap_percent, ls.percentile_rank, ls.days_on_market,
               ls.nadlan_median_ppsqm, ls.motivation_score, ls.z_score, ls.n_cohort_sales,
               ls.value_add_gap,
               l.address, l.city, l.rooms, l.sqm, l.floor, l.price, l.url
        FROM listing_scores ls
        JOIN listings l ON ls.listing_id = l.id
        WHERE ls.gap_percent IS NOT NULL
          AND ls.gap_percent BETWEEN -200 AND -10
          AND l.rooms >= 1
          AND l.sqm BETWEEN 20 AND 500
          AND l.price >= 300000
          AND CAST(l.price AS REAL) / l.sqm >= 3000
          AND (ls.days_on_market IS NULL OR ls.days_on_market <= 365)
          AND (ls.n_cohort_sales IS NULL OR ls.n_cohort_sales >= 5)
          AND (ls.last_alerted_at IS NULL OR ls.last_alerted_at < ?)
        ORDER BY ls.gap_percent ASC
        LIMIT 5
        """,
        [cutoff],
    ).fetchall()

    if not rows:
        logger.info("send_deal_alerts: no qualifying deals (all alerted recently or none below -10%%)")
        return 0

    _COLS = [
        "listing_id", "gap_percent", "percentile_rank", "days_on_market",
        "nadlan_median_ppsqm", "motivation_score", "z_score", "n_cohort_sales",
        "value_add_gap",
        "address", "city", "rooms", "sqm", "floor", "price", "url",
    ]
    now = datetime.now().isoformat()
    sent = 0
    for row in rows:
        deal = dict(zip(_COLS, row))
        msg = _format_deal_alert(deal)
        if send_alert(msg):
            db.execute(
                "UPDATE listing_scores SET last_alerted_at = ? WHERE listing_id = ?",
                [now, deal["listing_id"]],
            )
            sent += 1

    logger.info("send_deal_alerts: sent %d alerts", sent)
    return sent


def _format_deal_alert(deal: dict) -> str:
    price = deal.get("price") or 0
    sqm = deal.get("sqm") or 0
    gap = deal.get("gap_percent") or 0
    ppsqm = price / sqm if sqm else 0
    median_ppsqm = deal.get("nadlan_median_ppsqm") or 0
    dom = deal.get("days_on_market")
    pct = deal.get("percentile_rank")
    motivation = deal.get("motivation_score")
    z = deal.get("z_score")
    n_cohort = deal.get("n_cohort_sales")
    value_add = deal.get("value_add_gap")

    lines = [
        "🏠 <b>Deal Alert</b>",
        f"📍 {deal.get('address')}, {deal.get('city')}",
        f"🛏 {deal.get('rooms')} rooms · {sqm:.0f} m² · floor {deal.get('floor') or '?'}",
        f"💰 ₪{price:,.0f}  (₪{ppsqm:,.0f}/m²)",
        f"📊 {abs(gap):.1f}% below market · median ₪{median_ppsqm:,.0f}/m²",
    ]
    if z is not None:
        cohort_note = f" (n={n_cohort})" if n_cohort else ""
        lines.append(f"📉 Z-score: {z:+.2f}{cohort_note}")
    if pct is not None:
        lines.append(f"📈 {pct * 100:.0f}th percentile for this area")
    if dom is not None:
        lines.append(f"📅 {dom} days on market")
    if value_add is not None and value_add > 0:
        lines.append(f"💎 Market discount: ₪{value_add:,.0f}")
    if motivation is not None and motivation >= 70:
        lines.append(f"🔥 Motivated seller (score {motivation:.0f}/100)")
    if deal.get("url"):
        lines.append(f'<a href="{deal["url"]}">View listing →</a>')

    return "\n".join(lines)
