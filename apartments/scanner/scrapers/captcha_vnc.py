"""CAPTCHA handling: screenshot alerts and on-demand noVNC browser sessions.

Flow:
  Scraper detects CAPTCHA  →  send_screenshot_alert()  →  user sees screenshot
  User sends /captcha <source>  →  bot calls launch_novnc_session()
  noVNC URL sent to Telegram  →  user opens on phone, solves captcha
  Session saved  →  user sends /scrape <source> to retry
"""
import asyncio
import logging
import os
import re
import subprocess
import tempfile
from pathlib import Path

import httpx

logger = logging.getLogger(__name__)

_TOKEN = lambda: os.getenv("TELEGRAM_BOT_TOKEN", "")
_CHAT = lambda: os.getenv("TELEGRAM_CHAT_ID", "")

SITE_URLS = {
    "madlan": (
        "https://www.madlan.co.il/for-sale/"
        "%D7%AA%D7%9C-%D7%90%D7%91%D7%99%D7%91-%D7%99%D7%A4%D7%95-%D7%99%D7%A9%D7%A8%D7%90%D7%9C"
        "?tracking_search_source=new_search&marketplace=residential"
    ),
    "yad2": "https://www.yad2.co.il/realestate/forsale",
}

# Domains that indicate a CAPTCHA / blocking page
CAPTCHA_DOMAINS = ("perfdrive.com", "captcha", "challenge", "px-captcha")

XVFB_DISPLAY = ":99"
VNC_PORT = 5900
NOVNC_PORT = 6080
NOVNC_WEB = "/usr/share/novnc"


def _tg_post(endpoint: str, **kwargs) -> bool:
    token = _TOKEN()
    chat = _CHAT()
    if not token or not chat:
        return False
    try:
        resp = httpx.post(
            f"https://api.telegram.org/bot{token}/{endpoint}",
            timeout=15,
            **kwargs,
        )
        return resp.status_code == 200
    except Exception as e:
        logger.error("Telegram %s failed: %s", endpoint, e)
        return False


def _send_text(text: str) -> bool:
    return _tg_post(
        "sendMessage",
        data={
            "chat_id": _CHAT(),
            "text": text,
            "parse_mode": "HTML",
            "disable_web_page_preview": "true",
        },
    )


async def send_screenshot_alert(page, source: str) -> bool:
    """Take a Playwright screenshot and send it to Telegram.

    Instructs the user to run /captcha <source> to open a noVNC session.
    """
    try:
        screenshot_bytes = await page.screenshot(full_page=False)
    except Exception as e:
        logger.warning("Screenshot failed: %s", e)
        # Fall back to text-only alert
        return _send_text(
            f"🔒 <b>{source} CAPTCHA detected</b>\n\n"
            f"Send <code>/captcha {source}</code> to open a browser and solve it."
        )

    caption = (
        f"🔒 <b>{source} CAPTCHA detected</b>\n\n"
        f"Send <code>/captcha {source}</code> to open a browser on your phone and solve it."
    )
    return _tg_post(
        "sendPhoto",
        data={"chat_id": _CHAT(), "caption": caption, "parse_mode": "HTML"},
        files={"photo": ("screenshot.png", screenshot_bytes, "image/png")},
    )


async def launch_novnc_session(source: str) -> None:
    """Launch a noVNC session so the user can solve a CAPTCHA from their phone.

    Starts Xvfb + x11vnc + websockify/noVNC + cloudflared tunnel + headed
    Playwright browser. Sends the noVNC URL to Telegram, then waits up to 5 min
    for the CAPTCHA to be solved. On success, saves the browser session.
    """
    from .session_manager import get_context, save_session, close_all

    site_url = SITE_URLS.get(source)
    if not site_url:
        _send_text(f"❌ Unknown source: {source}")
        return

    procs: list[subprocess.Popen] = []
    playwright = browser = context = page = None
    tunnel_log_path: str | None = None
    old_display = os.environ.get("DISPLAY")

    def _kill_procs():
        for p in reversed(procs):
            try:
                p.terminate()
                p.wait(timeout=5)
            except Exception:
                pass

    try:
        _send_text(f"⏳ Starting noVNC session for <b>{source}</b>...")

        # Preflight: confirm the toolchain is actually in the image. Surfaces a
        # missing/broken Docker install immediately instead of hanging silently.
        import shutil
        missing = [b for b in ("Xvfb", "x11vnc", "websockify", "cloudflared")
                   if not shutil.which(b)]
        if not Path(NOVNC_WEB).exists():
            missing.append(f"{NOVNC_WEB} (noVNC web assets)")
        if missing:
            _send_text("❌ noVNC can't start — missing on server: " + ", ".join(missing))
            return

        def _check_alive(step: str) -> bool:
            """A just-started helper process that already exited = report and stop."""
            p = procs[-1]
            if p.poll() is not None:
                _send_text(f"❌ noVNC step failed: <b>{step}</b> exited (code {p.returncode})")
                return False
            return True

        # 1. Xvfb virtual display
        procs.append(subprocess.Popen(
            ["Xvfb", XVFB_DISPLAY, "-screen", "0", "1280x900x24"],
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
        ))
        await asyncio.sleep(1.5)
        if not _check_alive("Xvfb (virtual display)"):
            return

        # 2. x11vnc VNC server on the virtual display
        procs.append(subprocess.Popen(
            ["x11vnc", "-display", XVFB_DISPLAY, "-nopw", "-listen", "localhost",
             "-forever", "-rfbport", str(VNC_PORT)],
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
        ))
        await asyncio.sleep(1.5)
        if not _check_alive("x11vnc"):
            return

        # 3. noVNC websockify
        procs.append(subprocess.Popen(
            ["websockify", "--web", NOVNC_WEB,
             str(NOVNC_PORT), f"localhost:{VNC_PORT}"],
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
        ))
        await asyncio.sleep(2)
        if not _check_alive("websockify"):
            return

        # 4. Cloudflare tunnel to noVNC port → get URL
        _send_text("⏳ noVNC up — opening public tunnel (~10-30s)...")
        tunnel_log_fd, tunnel_log_path = tempfile.mkstemp(suffix=".log")
        os.close(tunnel_log_fd)
        tunnel_log_f = open(tunnel_log_path, "w")
        procs.append(subprocess.Popen(
            ["cloudflared", "tunnel", "--url", f"http://localhost:{NOVNC_PORT}",
             "--no-autoupdate"],
            stdout=tunnel_log_f, stderr=tunnel_log_f,
        ))
        tunnel_url = None
        for _ in range(30):
            await asyncio.sleep(2)
            try:
                content = Path(tunnel_log_path).read_text(errors="replace")
                urls = re.findall(r"https://[^\s]+\.trycloudflare\.com", content)
                if urls:
                    tunnel_url = urls[-1]
                    break
            except Exception:
                pass

        # No public URL = the link would be an unreachable localhost:6080. Abort
        # loudly with the cloudflared log tail so we can see why (rate-limit, etc.)
        # rather than sending a dead link.
        if not tunnel_url:
            tail = ""
            try:
                tail = Path(tunnel_log_path).read_text(errors="replace")[-500:]
            except Exception:
                pass
            _send_text("❌ cloudflared produced no public URL in 60s.\n\n" + (tail or "(empty log)"))
            return

        novnc_url = f"{tunnel_url}/vnc.html?autoconnect=1&resize=scale"

        # 5. Launch headed Playwright browser on the Xvfb display
        os.environ["DISPLAY"] = XVFB_DISPLAY
        playwright, browser, context = await get_context(
            source, headless=False, force_fresh=True
        )
        page = await context.new_page()
        await page.goto(site_url, wait_until="domcontentloaded", timeout=30000)

        # 6. Send noVNC URL to Telegram
        _send_text(
            f"🖥️ <b>{source} — open on your phone and solve the CAPTCHA</b>\n\n"
            f"{novnc_url}\n\n"
            f"Session saves automatically once the page loads normally (up to 5 min)."
        )

        # 7. Poll until CAPTCHA is gone or timeout
        solved = False
        for _ in range(150):  # 5 min × 2 s
            await asyncio.sleep(2)
            current_url = page.url
            if not any(d in current_url.lower() for d in CAPTCHA_DOMAINS):
                try:
                    content_len = await page.evaluate(
                        "() => document.body ? document.body.innerText.length : 0"
                    )
                    if content_len > 500:
                        solved = True
                        break
                except Exception:
                    pass

        if solved:
            await save_session(context, source)
            _send_text(
                f"✅ <b>{source} session saved!</b>\n"
                f"Send /scrape {source} to retry the scrape."
            )
            logger.info("noVNC CAPTCHA solved for %s", source)
        else:
            _send_text(f"⏱ noVNC timed out for {source}. Try /captcha {source} again.")
            logger.warning("noVNC timed out for %s", source)

    except Exception as e:
        logger.exception("launch_novnc_session failed for %s", source)
        _send_text(f"❌ noVNC error for {source}: {e}")
    finally:
        if old_display is None:
            os.environ.pop("DISPLAY", None)
        else:
            os.environ["DISPLAY"] = old_display

        if playwright and browser and context:
            try:
                await close_all(playwright, browser, context)
            except Exception:
                pass

        _kill_procs()

        if tunnel_log_path:
            try:
                Path(tunnel_log_path).unlink(missing_ok=True)
            except Exception:
                pass
