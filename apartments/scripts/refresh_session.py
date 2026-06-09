"""Open a browser window for manual CAPTCHA solve, then save the session."""
import asyncio
import sys
from pathlib import Path

# Add project root to path
sys.path.insert(0, str(Path(__file__).parent.parent))

from playwright.async_api import async_playwright

SESSIONS_DIR = Path("data/sessions")

URLS = {
    "yad2": "https://www.yad2.co.il/realestate/forsale",
    "nadlan": "https://www.nadlan.gov.il/",
}


async def main(site: str = "yad2"):
    SESSIONS_DIR.mkdir(parents=True, exist_ok=True)
    session_file = SESSIONS_DIR / f"{site}.json"
    url = URLS[site]

    print(f"\n{'='*50}")
    print(f"Opening {site} — {url}")
    print(f"{'='*50}")
    print("A Chrome window will open. Solve any CAPTCHA if needed.")
    print("When the listings page loads normally, come back here and press ENTER.")
    print()

    async with async_playwright() as pw:
        browser = await pw.chromium.launch(
            headless=False,
            args=["--start-maximized"],
        )
        context = await browser.new_context(
            user_agent=(
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/124.0.0.0 Safari/537.36"
            ),
            viewport=None,  # use maximized window size
            locale="he-IL",
            timezone_id="Asia/Jerusalem",
        )

        page = await context.new_page()
        await page.goto(url, wait_until="domcontentloaded", timeout=30000)
        print(f"Browser opened. Waiting for you...")

        # Wait for user to press ENTER (runs in thread so browser stays open)
        await asyncio.to_thread(input, "\n>>> Press ENTER once you see normal listings: ")

        # Save session
        await context.storage_state(path=str(session_file))
        print(f"\n✅ Session saved to {session_file}")
        print("Future scrapes will run headless automatically.\n")

        await browser.close()


if __name__ == "__main__":
    site = sys.argv[1] if len(sys.argv) > 1 else "yad2"
    asyncio.run(main(site))
