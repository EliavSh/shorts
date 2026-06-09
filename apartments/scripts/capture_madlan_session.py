"""
Capture Madlan session — opens headed browser, USER solves CAPTCHA, saves
session every 5 seconds so we don't lose it if interrupted.

Run: python scripts/capture_madlan_session.py
"""
import asyncio
import json
import sys
from pathlib import Path
from playwright.async_api import async_playwright

if sys.stdout.encoding and sys.stdout.encoding.lower() not in ("utf-8", "utf8"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

URL = "https://www.madlan.co.il/for-sale/%D7%AA%D7%9C-%D7%90%D7%91%D7%99%D7%91-%D7%99%D7%A4%D7%95-%D7%99%D7%A9%D7%A8%D7%90%D7%9C?tracking_search_source=map&isMapExpanded=true&marketplace=residential"
SESSION_FILE = Path("data/sessions/madlan.json")
INTERCEPT_FILE = Path("debug_madlan_intercept_session.json")
SESSION_FILE.parent.mkdir(parents=True, exist_ok=True)

CAPTURED = {"requests": [], "responses": []}


async def periodic_save(context, stop_event):
    """Save session + intercept every 5 seconds."""
    n = 0
    while not stop_event.is_set():
        try:
            await context.storage_state(path=str(SESSION_FILE))
            with open(INTERCEPT_FILE, "w", encoding="utf-8") as f:
                json.dump(CAPTURED, f, ensure_ascii=False, indent=2)
            n += 1
            sys.stdout.write(f"  [save #{n}] cookies={len((await context.storage_state())['cookies'])} reqs={len(CAPTURED['requests'])}\n")
            sys.stdout.flush()
        except Exception as e:
            sys.stdout.write(f"  [save error] {e}\n"); sys.stdout.flush()
        try:
            await asyncio.wait_for(stop_event.wait(), timeout=5.0)
        except asyncio.TimeoutError:
            pass


async def main():
    async with async_playwright() as p:
        browser = await p.chromium.launch(
            headless=False,
            args=["--no-sandbox", "--disable-blink-features=AutomationControlled"],
        )
        storage = str(SESSION_FILE) if SESSION_FILE.exists() else None
        context = await browser.new_context(
            storage_state=storage,
            user_agent=(
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
            ),
            locale="he-IL", timezone_id="Asia/Jerusalem",
            viewport={"width": 1440, "height": 900},
        )
        page = await context.new_page()

        async def on_request(req):
            url = req.url
            if "/api2" in url or "/api3" in url:
                body_str = req.post_data or ""
                try:
                    body_json = json.loads(body_str) if body_str else {}
                except Exception:
                    body_json = {}
                op = body_json.get("operationName", "?")
                CAPTURED["requests"].append({
                    "url": url, "op": op,
                    "headers": dict(req.headers), "body": body_json,
                })

        async def on_response(resp):
            url = resp.url
            if "/api2" in url or "/api3" in url:
                try:
                    body = await resp.json()
                except Exception:
                    body = {}
                op = "?"
                for r in reversed(CAPTURED["requests"]):
                    if r["url"] == url:
                        op = r["op"]; break
                CAPTURED["responses"].append({
                    "url": url, "status": resp.status, "op": op, "body": body,
                })

        page.on("request", on_request)
        page.on("response", on_response)

        sys.stdout.write(f"Loading map URL...\n"); sys.stdout.flush()
        try:
            await page.goto(URL, wait_until="domcontentloaded", timeout=60000)
        except Exception as e:
            sys.stdout.write(f"goto error (continuing): {e}\n"); sys.stdout.flush()

        sys.stdout.write("\n" + "="*60 + "\n")
        sys.stdout.write("Solve CAPTCHA, wait for listings, scroll/pan map.\n")
        sys.stdout.write("Session saves every 5 seconds. Safe to kill anytime.\n")
        sys.stdout.write("Will auto-stop after 3 minutes.\n")
        sys.stdout.write("="*60 + "\n"); sys.stdout.flush()

        stop_event = asyncio.Event()
        saver_task = asyncio.create_task(periodic_save(context, stop_event))

        try:
            await asyncio.sleep(180)
        finally:
            stop_event.set()
            await saver_task
            # Final save
            await context.storage_state(path=str(SESSION_FILE))
            with open(INTERCEPT_FILE, "w", encoding="utf-8") as f:
                json.dump(CAPTURED, f, ensure_ascii=False, indent=2)
            sys.stdout.write(f"\n✓ Final save done. {len(CAPTURED['requests'])} reqs captured.\n")
            sys.stdout.flush()

        ops = {}
        for r in CAPTURED["requests"]:
            ops[r["op"]] = ops.get(r["op"], 0) + 1
        sys.stdout.write("\nOperations:\n")
        for op, c in sorted(ops.items(), key=lambda x: -x[1]):
            sys.stdout.write(f"  {c}x {op}\n")
        sys.stdout.flush()

        await browser.close()


asyncio.run(main())
