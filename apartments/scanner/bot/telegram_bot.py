"""Bidirectional Telegram bot — runs on the Linux server as a systemd service.

Commands:
  /status   — DB stats + current tunnel URL
  /url      — current Cloudflare tunnel URL
  /scrape [source]  — trigger cron_scrape.py (madlan | yad2 | yad2_sold)
  /captcha <source> — launch noVNC browser for CAPTCHA solving from phone
  /ask <prompt>     — run claude -p "<prompt>" in the repo, reply with output
  <any text>        — treated as /ask

Security: only responds to TELEGRAM_CHAT_ID.
"""
import asyncio
import logging
import os
import re
import sqlite3
import subprocess
import urllib.request
from pathlib import Path

from dotenv import load_dotenv
from telegram import Update
from telegram.ext import Application, CommandHandler, ContextTypes, MessageHandler, filters

load_dotenv()

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(levelname)s: %(message)s")
logger = logging.getLogger("apartment_bot")

TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "")
ALLOWED_CHAT_ID = int(os.getenv("TELEGRAM_CHAT_ID", "0"))
REPO = Path(__file__).resolve().parents[2]
DB_PATH = Path(os.getenv("DATA_DIR", str(REPO / "data"))) / "apartments.db"
CLOUDFLARED_LOG = REPO / "data" / "cloudflared.log"
PYTHON = Path(os.getenv("PYTHON_BIN", "python3"))


def _check_auth(update: Update) -> bool:
    return update.effective_chat.id == ALLOWED_CHAT_ID


def _get_tunnel_url() -> str:
    # On Fly.io (or any fixed-URL deploy) PUBLIC_URL is set and stable — prefer it.
    public_url = os.getenv("PUBLIC_URL")
    if public_url:
        return public_url
    # On the Linux server the URL comes from the rotating cloudflared tunnel log.
    try:
        text = CLOUDFLARED_LOG.read_text(errors="replace")
        urls = re.findall(r"https://[^\s]+\.trycloudflare\.com", text)
        return urls[-1] if urls else "tunnel URL not found (is cloudflared running?)"
    except Exception:
        return "could not read cloudflared log"


def _db_stats() -> str:
    try:
        db = sqlite3.connect(f"file:{DB_PATH}?mode=ro", uri=True)
        listings = db.execute("SELECT COUNT(*) FROM listings WHERE is_active=1").fetchone()[0]
        txns = db.execute("SELECT COUNT(*) FROM transactions").fetchone()[0]
        last_run = db.execute(
            "SELECT source, ended_at, status, rows_inserted FROM run_history ORDER BY ended_at DESC LIMIT 1"
        ).fetchone()
        db.close()
        last = f"{last_run[0]} @ {last_run[1][:16]} → {last_run[2]} (+{last_run[3]})" if last_run else "no runs yet"
        return f"listings: {listings:,}\ntransactions: {txns:,}\nlast scrape: {last}"
    except Exception as e:
        return f"DB error: {e}"


async def cmd_status(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not _check_auth(update):
        return
    url = _get_tunnel_url()
    stats = _db_stats()
    await update.message.reply_text(f"🏠 Apartment Scanner\n\n{stats}\n\n🌐 {url}")


async def cmd_url(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not _check_auth(update):
        return
    await update.message.reply_text(f"🌐 {_get_tunnel_url()}")


async def cmd_scrape(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not _check_auth(update):
        return
    valid = ("madlan", "yad2", "yad2_sold")
    source = context.args[0] if context.args else "yad2_sold"
    if source not in valid:
        await update.message.reply_text(f"Unknown source. Use: {', '.join(valid)}")
        return
    await update.message.reply_text(f"⏳ Starting {source} scrape...")
    try:
        result = subprocess.run(
            [str(PYTHON), "-m", "scripts.cron_scrape", "--source", source],
            cwd=str(REPO),
            capture_output=True, text=True, timeout=600,
        )
        out = (result.stdout + result.stderr)[-1500:]
        status = "✅" if result.returncode == 0 else "❌"
        await update.message.reply_text(f"{status} {source} done\n\n{out}")
    except subprocess.TimeoutExpired:
        await update.message.reply_text("⏱ Scrape timed out after 10 min")
    except Exception as e:
        await update.message.reply_text(f"❌ Error: {e}")


async def cmd_captcha(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not _check_auth(update):
        return
    valid = ("madlan", "yad2")
    source = context.args[0] if context.args else ""
    if source not in valid:
        await update.message.reply_text(f"Usage: /captcha <source>  (sources: {', '.join(valid)})")
        return
    await update.message.reply_text(f"⏳ Launching noVNC for {source}... (takes ~10s to start)")
    try:
        import sys
        sys.path.insert(0, str(REPO))
        from scanner.scrapers.captcha_vnc import launch_novnc_session
        # Run in a background task so the bot stays responsive
        asyncio.create_task(launch_novnc_session(source))
    except Exception as e:
        await update.message.reply_text(f"❌ Error launching noVNC: {e}")


async def cmd_ask(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not _check_auth(update):
        return
    prompt = " ".join(context.args) if context.args else ""
    if not prompt:
        await update.message.reply_text("Usage: /ask <your question or instruction>")
        return
    await _run_claude(update, prompt)


async def handle_text(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not _check_auth(update):
        return
    prompt = update.message.text or ""
    if prompt.startswith("/"):
        return
    await _run_claude(update, prompt)


async def _run_claude(update: Update, prompt: str):
    await update.message.reply_text("🤖 Claude is working...")
    try:
        result = subprocess.run(
            ["claude", "--dangerously-skip-permissions", "-p", prompt],
            cwd=str(REPO),
            capture_output=True, text=True, timeout=300,
            env={**os.environ, "ANTHROPIC_API_KEY": os.getenv("ANTHROPIC_API_KEY", "")},
        )
        output = (result.stdout or result.stderr or "no output").strip()
        # Split into ≤4000-char chunks so Telegram doesn't reject long replies
        chunk_size = 4000
        chunks = [output[i:i+chunk_size] for i in range(0, max(len(output), 1), chunk_size)]
        for chunk in chunks[:5]:  # max 5 messages
            await update.message.reply_text(chunk)
        if len(chunks) > 5:
            await update.message.reply_text(f"… (truncated, {len(chunks)-5} more chunks)")
    except FileNotFoundError:
        await update.message.reply_text("❌ `claude` CLI not found. Install: npm install -g @anthropic-ai/claude-code")
    except subprocess.TimeoutExpired:
        await update.message.reply_text("⏱ Claude timed out (5 min)")
    except Exception as e:
        await update.message.reply_text(f"❌ Error: {e}")


async def _warmup_and_notify(app) -> None:
    """Fires once after the bot connects. Warms up the API and sends the startup message."""
    # Give cloudflared and uvicorn a moment to finish starting
    await asyncio.sleep(5)

    # Warm up the API server (fire-and-forget, ignore failures)
    api_ok = False
    try:
        with urllib.request.urlopen("http://localhost:8000/api/health", timeout=5) as r:
            api_ok = r.status == 200
    except Exception:
        pass

    url = _get_tunnel_url()
    stats = _db_stats()
    api_status = "✅ API up" if api_ok else "⚠️ API not responding"
    msg = f"🏠 Apartment Scanner started\n\n{api_status}\n\n{stats}\n\n🌐 {url}"
    try:
        await app.bot.send_message(chat_id=ALLOWED_CHAT_ID, text=msg)
    except Exception as e:
        logger.warning("Could not send startup message: %s", e)


def main():
    if not TOKEN:
        raise RuntimeError("TELEGRAM_BOT_TOKEN not set")
    app = Application.builder().token(TOKEN).post_init(_warmup_and_notify).build()
    app.add_handler(CommandHandler("status", cmd_status))
    app.add_handler(CommandHandler("url", cmd_url))
    app.add_handler(CommandHandler("scrape", cmd_scrape))
    app.add_handler(CommandHandler("captcha", cmd_captcha))
    app.add_handler(CommandHandler("ask", cmd_ask))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_text))
    logger.info("Bot started. Listening for messages from chat_id=%d", ALLOWED_CHAT_ID)
    app.run_polling(drop_pending_updates=True)


if __name__ == "__main__":
    main()
