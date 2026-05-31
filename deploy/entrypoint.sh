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

exec "$@"
