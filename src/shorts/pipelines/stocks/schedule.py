"""Auto-pilot generation schedule — the single source of truth the web app uses
to show a countdown to the next scheduled clip.

The authoritative trigger is the GitHub Actions cron in
`.github/workflows/autopilot.yml` (it POSTs `/stocks/autopilot/tick`). That YAML
and `SCHEDULE_UTC_HOURS` below MUST be kept in sync — if they drift, only the
dashboard countdown is wrong, the renders still fire on the GitHub schedule.
"""
from __future__ import annotations

from datetime import datetime, time, timedelta, timezone

# Mirror of the cron hours in .github/workflows/autopilot.yml (all UTC). The
# workflow adds a random 0–60 min jitter, so the real render times drift up to an
# hour past these — the dashboard countdown is therefore approximate. One render
# per slot → up to 6 clips/day; keep daily_target >= 6 so the cap doesn't throttle.
SCHEDULE_UTC_HOURS: tuple[int, ...] = (0, 4, 8, 12, 16, 20)


def next_runs(n: int = 3, *, now: datetime | None = None) -> list[datetime]:
    """The next `n` upcoming scheduled run times, as UTC tz-aware datetimes.

    Walks forward from `now` (default: current UTC), across day boundaries, so
    e.g. just after 10:00 UTC the first entry is 16:00 UTC today.
    """
    now = (now or datetime.now(timezone.utc)).astimezone(timezone.utc)
    hours = sorted(set(h for h in SCHEDULE_UTC_HOURS if 0 <= h <= 23))
    if not hours:
        return []

    out: list[datetime] = []
    day = now.date()
    # Scan today first, then following days, until we've collected `n`.
    while len(out) < n:
        for h in hours:
            slot = datetime.combine(day, time(hour=h), tzinfo=timezone.utc)
            if slot > now:
                out.append(slot)
                if len(out) >= n:
                    break
        day = day + timedelta(days=1)
    return out
