"""Meta endpoints: neighborhoods, health-led, freshness."""
import os
from datetime import datetime, timedelta
from typing import Optional

import sqlite_utils
from fastapi import APIRouter, Depends

from scanner.api.deps import DISABLED_SOURCES, disabled_sources_clause, get_database

router = APIRouter(prefix="/api/meta", tags=["meta"])


@router.post("/ping-telegram")
def ping_telegram():
    """Send a Telegram message with the public URL. Used to verify the
    Telegram pipeline on demand (e.g. right after a fresh deploy)."""
    from scanner.alerts.telegram import send_alert

    url = os.getenv("PUBLIC_URL", "(PUBLIC_URL not set)")
    ok = send_alert(
        f"🏓 <b>Apartment Scanner is live</b>\n\n🌐 {url}\n\n"
        f"Sent on demand via /api/meta/ping-telegram."
    )
    return {"sent": ok, "url": url}


@router.get("/neighborhoods")
def neighborhoods(
    city: Optional[str] = None,
    db: sqlite_utils.Database = Depends(get_database),
):
    """Distinct neighborhoods, optionally restricted to a city. Madlan-only
    (Yad2 doesn't carry neighborhood data)."""
    sql = (
        "SELECT DISTINCT neighborhood FROM listings "
        f"WHERE neighborhood IS NOT NULL AND neighborhood != ''{disabled_sources_clause()}"
    )
    params: list = []
    if city:
        sql += " AND city = ?"
        params.append(city)
    sql += " ORDER BY neighborhood"
    rows = db.execute(sql, params).fetchall()
    return [r[0] for r in rows]


@router.get("/cities")
def cities(db: sqlite_utils.Database = Depends(get_database)):
    rows = db.execute(
        f"SELECT city, COUNT(*) FROM listings WHERE is_active = 1{disabled_sources_clause()} "
        "GROUP BY city ORDER BY 2 DESC"
    ).fetchall()
    return [{"city": r[0], "count": r[1]} for r in rows]


@router.get("/health")
def health_led(db: sqlite_utils.Database = Depends(get_database)):
    """Per-source 🟢/🟡/🔴 health for the heartbeat indicator.

    Thresholds (per user spec):
    - 🟢 green   < 1 hour since last successful run
    - 🟡 yellow  1 – 24 hours
    - 🔴 red     ≥ 24 hours, or last run errored, or no runs yet
    Disabled sources (DISABLED_SOURCES) are hidden from the LED.
    """
    sources = [
        s for s in ("yad2", "yad2_sold", "madlan", "nadlan", "pinui_binui")
        if s not in DISABLED_SOURCES
    ]
    out = []
    now = datetime.now()
    for src in sources:
        row = db.execute(
            "SELECT status, ended_at, captcha_detected FROM run_history "
            "WHERE source = ? ORDER BY ended_at DESC LIMIT 1",
            [src],
        ).fetchone()
        if not row:
            out.append({"source": src, "status": "red", "reason": "no runs", "ended_at": None})
            continue
        status, ended_at, captcha = row[0], row[1], (row[2] or 0)
        try:
            ended = datetime.fromisoformat((ended_at or "").replace("Z", ""))
        except (ValueError, AttributeError):
            ended = None
        age_h = (now - ended).total_seconds() / 3600 if ended else None
        led = "red"
        reason = ""
        if status == "success" and age_h is not None:
            if age_h < 1:
                led = "green"
            elif age_h < 24:
                led = "yellow"
                reason = f"{age_h:.0f}h since last success"
            else:
                led = "red"
                reason = f"{age_h:.0f}h since last success"
        elif captcha:
            led = "red"
            reason = "CAPTCHA blocked"
        else:
            led = "red"
            reason = f"last run: {status}"
        out.append({
            "source": src,
            "status": led,
            "reason": reason,
            "ended_at": ended_at,
            "age_hours": round(age_h, 1) if age_h is not None else None,
        })
    return out


@router.get("/status")
def status(db: sqlite_utils.Database = Depends(get_database)):
    """Consolidated system status for the website's hidden Status view — the
    info that used to be pushed to Telegram: recent scrape runs, per-mode
    listing counts, and enrichment coverage."""
    def scalar(sql, params=None):
        try:
            return db.execute(sql, params or []).fetchone()[0]
        except Exception:
            return None

    runs = []
    try:
        for r in db.execute(
            "SELECT source, status, ended_at, rows_scraped, rows_inserted, "
            "error_message, captcha_detected FROM run_history "
            "ORDER BY ended_at DESC LIMIT 25"
        ).fetchall():
            runs.append({
                "source": r[0], "status": r[1], "ended_at": r[2],
                "rows_scraped": r[3], "rows_inserted": r[4],
                "error": r[5], "captcha": bool(r[6] or 0),
            })
    except Exception:
        pass

    counts = {
        "sale": scalar("SELECT COUNT(*) FROM listings WHERE deal_type='sale' AND is_active=1"),
        "rent": scalar("SELECT COUNT(*) FROM listings WHERE deal_type='rent' AND is_active=1"),
        "transactions": scalar("SELECT COUNT(*) FROM transactions"),
    }
    enrichment = {
        "rent_with_costs": scalar(
            "SELECT COUNT(*) FROM listings WHERE deal_type='rent' AND (vaad_bayit IS NOT NULL OR arnona IS NOT NULL)"
        ),
        "rent_with_amenities": scalar(
            "SELECT COUNT(*) FROM listings WHERE deal_type='rent' AND has_elevator IS NOT NULL"
        ),
    }
    return {
        "server_time": datetime.now().isoformat(timespec="seconds"),
        "counts": counts,
        "enrichment": enrichment,
        "recent_runs": runs,
    }


@router.get("/freshness")
def freshness(db: sqlite_utils.Database = Depends(get_database)):
    """Last successful run timestamp + row counts per source."""
    rows = db.execute(
        "SELECT source, MAX(ended_at) AS last_ok, COUNT(*) AS runs "
        "FROM run_history WHERE status = 'success' GROUP BY source"
    ).fetchall()
    by_source = {r[0]: {"last_success": r[1], "successful_runs": r[2]} for r in rows}

    counts = {
        "active_listings": db.execute(
            f"SELECT COUNT(*) FROM listings WHERE is_active = 1{disabled_sources_clause()}"
        ).fetchone()[0],
        "transactions": db.execute("SELECT COUNT(*) FROM transactions").fetchone()[0],
        "zones": db.execute("SELECT COUNT(*) FROM pinui_binui_zones").fetchone()[0],
    }
    return {"sources": by_source, "counts": counts}
