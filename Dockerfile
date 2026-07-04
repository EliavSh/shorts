# ── Stage 1: Build the apartment-scanner React SPA ───────────────────────────
# Served under /apartments/ in the unified dashboard, so base + API URL are
# prefixed at build time.
FROM node:18-alpine AS apartments-frontend
WORKDIR /frontend
COPY apartments/frontend/package.json apartments/frontend/package-lock.json* ./
RUN npm install --prefer-offline --no-audit --no-fund
COPY apartments/frontend/ ./
ENV VITE_API_URL=/apartments/api
RUN npm run build

# ── Stage 2: Python runtime (shorts + apartment scanner) ─────────────────────
FROM python:3.12-slim

ENV PYTHONUNBUFFERED=1 \
    PYTHONIOENCODING=utf-8 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    PYTHONPATH=/app \
    HF_HOME=/app/data/hf-cache

WORKDIR /app

# System deps:
#   ffmpeg     — video composition
#   git        — needed by some pip pkgs (whisper)
#   libsndfile1, libsndfile1-dev — librosa/soundfile audio decode
#   curl       — healthchecks
#   xvfb, x11vnc, websockify, novnc — apartment scanner's remote CAPTCHA-solve
#     flow (scanner/scrapers/captcha_vnc.py): a headed browser runs on a virtual
#     display (Xvfb) and is streamed to the user's phone over noVNC so they can
#     solve a Yad2/Madlan CAPTCHA. novnc installs its web assets to
#     /usr/share/novnc (matches NOVNC_WEB in captcha_vnc.py).
RUN apt-get update && apt-get install -y --no-install-recommends \
      ffmpeg \
      git \
      curl \
      libsndfile1 \
      libsndfile1-dev \
      ca-certificates \
      xvfb \
      x11vnc \
      websockify \
      novnc \
  && rm -rf /var/lib/apt/lists/*

# cloudflared — quick tunnel that exposes the noVNC port to a public
# trycloudflare.com URL for the remote CAPTCHA-solve flow. Not in apt, so fetch
# the static binary (github.com is reachable from Fly's remote builder).
RUN curl -L https://github.com/cloudflare/cloudflared/releases/latest/download/cloudflared-linux-amd64 \
      -o /usr/local/bin/cloudflared \
  && chmod +x /usr/local/bin/cloudflared

COPY pyproject.toml README.md ./
COPY src/ src/
COPY config/ config/
COPY assets/ assets/
COPY deploy/ deploy/

RUN pip install --no-cache-dir -e .

# ── Apartment scanner: deps + package + scrapers' browser ────────────────────
COPY apartments/requirements.txt ./apartments/requirements.txt
RUN pip install --no-cache-dir -r apartments/requirements.txt
# Chromium only (scrapers don't need firefox/webkit); --with-deps pulls the
# system libraries Chromium needs on slim Debian.
RUN python -m playwright install chromium --with-deps

# scanner package (importable via PYTHONPATH=/app), its scripts, config, and SPA.
# scripts/ lands at /app/scripts so `python -m scripts.cron_scrape` resolves —
# that's how the Telegram bot's /scrape command and the hourly cron invoke it.
COPY apartments/scanner/ ./scanner/
COPY apartments/scripts/ ./scripts/
COPY apartments/config/ ./config/apartments/
COPY --from=apartments-frontend /frontend/dist ./apartments/frontend/dist

# Tell scanner.api.app where the SPA build lives (it's mounted under /apartments)
ENV SCANNER_FRONTEND_DIST=/app/apartments/frontend/dist \
    DATA_DIR=/app/data/apartments \
    SCANNER_DB_PATH=/app/data/apartments/apartments.db \
    PUBLIC_URL=https://shorts-review.fly.dev/apartments

# Stamp the build with the deploying commit so the dashboard can show which code
# is live. Placed after pip install so changing it doesn't bust the deps cache.
ARG GIT_SHA=dev
ENV APP_VERSION=$GIT_SHA

EXPOSE 8000

# Bump to force re-seeding the volume with refreshed review clips on next boot.
ENV SEED_VERSION=1

# Persistent data lives on a Fly volume mounted at /app/data
VOLUME ["/app/data"]

# Seed the volume with bundled review clips on first boot, then run uvicorn on
# the unified dashboard (entrypoint execs the CMD after seeding).
ENTRYPOINT ["sh", "/app/deploy/entrypoint.sh"]
CMD ["uvicorn", "shorts.core.dashboard.factory:app", "--host", "0.0.0.0", "--port", "8000"]
