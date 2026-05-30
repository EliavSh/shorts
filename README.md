# shorts

Unified content engine for short-form video pipelines. Two pipelines live in
one project and share infrastructure (review store, dashboard, YouTube
uploader, cost tracking, visual primitives, insight memory):

- **brawl** — Brawl Stars gameplay clips: discover→moment-detect→edit→review.
- **stocks** — finance Shorts: topic→script→tts→compose→review.

Each pipeline has its own rules, tests, brand config, and YouTube channel.
A single FastAPI dashboard hosts both under `/brawl/` and `/stocks/`.

## Repo layout

```
src/shorts/
├── cli.py                  # `shorts brawl ...`, `shorts stocks ...`, `shorts dashboard`, `shorts upload`
├── core/                   # shared infra (review store, dashboard factory, usage, publish, visuals, infra)
└── pipelines/
    ├── brawl/              # pipeline-specific: discovery/clips/edit/routes/templates
    └── stocks/             # pipeline-specific: data/script/voice/compose/visuals/routes/templates
config/
├── brawl/                  # config.yaml, brand.yaml, hype_terms.yaml
└── stocks/                 # config.yaml, brand_en.yaml
data/                       # gitignored; per-pipeline subdirs (output/, clip_cache/, usage.db, insights.json)
```

## Local dev

```powershell
cd C:\Users\eliavs\Claude\shorts
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -e .
copy .env.example .env       # fill in keys
$env:PYTHONIOENCODING='utf-8'

shorts --help                # see commands
shorts doctor                # health check
shorts dashboard             # http://127.0.0.1:8000
shorts brawl discover --days 7 --top 10
shorts brawl make-short "https://www.youtube.com/watch?v=..."
shorts stocks render-fixture nvda_q1fy27
shorts upload --pipeline=brawl <run_id>
```

Tests:

```powershell
.\.venv\Scripts\python.exe -m pytest src/shorts/pipelines -q
```

## Cloud deployment (Fly.io)

The dashboard + the pipelines run together in one Fly VM. Reviewers visit a
stable public URL, paste YouTube URLs, leave notes, and hit publish — nothing
runs on your laptop.

### One-time setup

```bash
# Install flyctl: https://fly.io/docs/hands-on/install-flyctl/
fly auth login

# From the shorts/ repo root
fly launch --no-deploy --copy-config
# (Answer the prompts; keep the existing fly.toml)

# Persistent volume — 5GB is enough for ~30 stocked clips
fly volumes create shorts_data --region fra --size 5

# Secrets — these become env vars inside the VM
fly secrets set \
  ANTHROPIC_API_KEY="..." \
  YOUTUBE_API_KEY="..." \
  BRAWL_YOUTUBE_CHANNEL_ID="..." \
  STOCKS_YOUTUBE_STAGING_CHANNEL_ID="..." \
  BRAWL_YOUTUBE_CLIENT_SECRET_PATH="/app/secrets/brawl_client.json" \
  BRAWL_YOUTUBE_TOKEN_PATH="/app/data/brawl_youtube_token.json" \
  STOCKS_YOUTUBE_CLIENT_SECRET_PATH="/app/secrets/stocks_client.json" \
  STOCKS_YOUTUBE_TOKEN_PATH="/app/data/stocks_youtube_token.json"

# YouTube OAuth: download the OAuth Desktop client JSON from each project's
# Google Cloud console, push them into the running VM's filesystem:
fly ssh sftp shell
# put /local/path/to/brawl_client.json /app/secrets/brawl_client.json
# put /local/path/to/stocks_client.json /app/secrets/stocks_client.json

# Deploy
fly deploy
```

After deploy, visit `https://shorts-review.fly.dev/` (the URL fly prints).

### What reviewers can do at the public URL

- **Home `/`** — pick brawl or stocks.
- **`/brawl/`** — paste a YouTube URL → cloud runs the full make-short pipeline →
  clip appears in the queue when done (~3 min). Click any clip to leave notes
  per version; submitting a note triggers a re-render and a new version
  appears side-by-side. Hit **Publish** to upload to the brawl YouTube channel.
- **`/brawl/feedback`** — write global rules that steer **all** future brawl
  renders (e.g. "captions are always too fast"). LLM-distilled insights from
  per-clip notes also land here automatically.
- **`/stocks/`** — generate today's daily render or re-render a named fixture;
  same notes + publish flow. Stocks publishes to its own channel.

The first **Publish** in each pipeline triggers an OAuth browser flow on the
VM (you'll need to SSH and `fly ssh console` to complete it). Subsequent
uploads use the saved refresh token.

### What's on the VM

- ffmpeg (apt package)
- yt-dlp (pip)
- imageio-ffmpeg (bundled portable ffmpeg as a fallback)
- Pillow + Pilmoji (text rendering)
- moviepy (stocks composer)
- Claude SDK + Google API client + ElevenLabs SDK

### Sizing notes

`performance-1x` with 2 GB RAM handles one clip at a time. Concurrent
generations may OOM — keep the request rate low or upgrade to `2x`.

## Pipeline status

| | brawl | stocks |
|---|---|---|
| Discovery / topic-picking | ✓ | ✓ |
| Pipeline-specific generation | ✓ make-short | ✓ run / render-fixture |
| Iteration via notes (per clip) | ✓ versioned regen | (pending — needs stocks to emit state.json) |
| Global feedback | ✓ | ✓ |
| Publish button → YouTube | ✓ | ✓ |
| YouTube channel | `BRAWL_YOUTUBE_CHANNEL_ID` | `STOCKS_YOUTUBE_STAGING_CHANNEL_ID` |
| Tests | 5 passing | 20 passing |
