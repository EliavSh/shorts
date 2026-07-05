#!/bin/sh
# Container entrypoint — seed the Fly volume with bundled review clips on first
# boot (or when SEED_VERSION bumps), then exec the real command (uvicorn).
#
# The Fly volume at /app/data persists across deploys and is empty on a fresh
# app. Rendered clips can't be sftp'd up from a sandboxed dev box (no WireGuard
# websocket), so we ship them inside the image and unpack them here.
set -e

seed_pipeline() {
    name="$1"; archive="$2"; dest="$3"
    [ -f "$archive" ] || return 0
    want="${SEED_VERSION:-1}"
    marker="$(dirname "$dest")/.seed_version"
    have="$(cat "$marker" 2>/dev/null || echo none)"
    if [ "$want" = "$have" ]; then
        echo "[entrypoint] $name: seed v$have already applied — skip"
        return 0
    fi
    echo "[entrypoint] $name: seeding clips (v$want) -> $dest"
    mkdir -p "$dest"
    tar xzf "$archive" -C "$dest"
    echo "$want" > "$marker"
    echo "[entrypoint] $name: seeded $(ls -d "$dest"/*/ 2>/dev/null | wc -l) run dirs"
}

seed_pipeline stocks /app/deploy/seed/stocks_clips.tgz /app/data/stocks/output
seed_pipeline brawl  /app/deploy/seed/brawl_clips.tgz  /app/data/brawl/output

# Materialize YouTube OAuth credential files from base64 Fly secrets. OAuth
# can't run headless in the cloud, so the client + refresh token are minted
# locally and shipped up as secrets; we decode them to the paths the uploader
# expects (STOCKS_YOUTUBE_CLIENT_SECRET_PATH / _TOKEN_PATH = /app/secrets/...).
write_b64_secret() {
    var="$1"; dest="$2"
    val="$(printenv "$var" 2>/dev/null || true)"
    [ -n "$val" ] || return 0
    mkdir -p "$(dirname "$dest")"
    printf '%s' "$val" | base64 -d > "$dest"
    echo "[entrypoint] wrote $dest from \$$var ($(wc -c < "$dest") bytes)"
}
write_b64_secret STOCKS_YOUTUBE_CLIENT_JSON_B64 /app/secrets/stocks_youtube_client.json
write_b64_secret STOCKS_YOUTUBE_TOKEN_JSON_B64  /app/secrets/stocks_youtube_token.json
write_b64_secret BRAWL_YOUTUBE_CLIENT_JSON_B64  /app/secrets/brawl_youtube_client.json
write_b64_secret BRAWL_YOUTUBE_TOKEN_JSON_B64   /app/secrets/brawl_youtube_token.json

# ── Apartment scanner background services ────────────────────────────────────
# The scanner's SQLite DB + Playwright sessions live on the Fly volume.
mkdir -p /app/data/apartments/sessions

# Seed the Fly volume with a freshly-scraped snapshot baked into the image.
# yad2's Radware bot-check blocks Fly's datacenter IP, so scraping can't run on
# Fly — the DB is scraped on a residential machine and shipped in the image. A
# version marker means this overwrites the (empty) volume DB once per bump; raise
# APARTMENTS_SEED_VERSION to push a refreshed snapshot on the next deploy.
APT_DB=/app/data/apartments/apartments.db
APT_SEED=/app/deploy/seed/apartments_seed.db.gz
APT_MARKER=/app/data/apartments/.apartments_seed_version
APT_WANT="${APARTMENTS_SEED_VERSION:-1}"
if [ -f "$APT_SEED" ] && [ "$(cat "$APT_MARKER" 2>/dev/null || echo none)" != "$APT_WANT" ]; then
    echo "[entrypoint] apartments: seeding snapshot DB v$APT_WANT -> $APT_DB"
    gunzip -c "$APT_SEED" > "$APT_DB"
    echo "$APT_WANT" > "$APT_MARKER"
    echo "[entrypoint] apartments: seeded $(wc -c < "$APT_DB") bytes"
fi

# Telegram bot (long-polling) — only if credentials are present. It also sends a
# startup message with the public URL (PUBLIC_URL env).
if [ -n "$TELEGRAM_BOT_TOKEN" ] && [ -n "$TELEGRAM_CHAT_ID" ]; then
    echo "[entrypoint] starting apartment Telegram bot"
    python -m scanner.bot.telegram_bot &
else
    echo "[entrypoint] TELEGRAM_* not set — apartment bot not started"
fi

# Hourly scraper loop (best-effort; a failed cycle never kills the loop).
echo "[entrypoint] starting apartment scraper cron loop (hourly)"
(
    while true; do
        sleep 3600
        echo "[apartments-cron] running cron_scrape"
        (cd /app && python -m scripts.cron_scrape) >/dev/null 2>&1 \
            || echo "[apartments-cron] cycle failed, continuing"
    done
) &

exec "$@"
