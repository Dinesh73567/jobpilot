"""
Diagnostic: open one chatbot job, click Apply, dump the drawer DOM so we can
fix selectors. Uses a TCS React Native job URL from the last live run.
"""
import asyncio
import sys
from src.config_manager import load as load_config
from src.scraper.base import create_browser, random_delay
from src.scraper.naukri import login as naukri_login

# One of the jobs that opened a chatbot in the last run
JOB_URL = sys.argv[1] if len(sys.argv) > 1 else \
    "https://www.naukri.com/job-listings-react-native-developer-tata-consultancy-services-bengaluru-3-to-5-years"


async def main():
    config = load_config()
    config.headless = False

    playwright, browser, context, page = await create_browser(config)

    try:
        if not await naukri_login(page, config):
            print("Login failed")
            return

        print(f"Navigating to {JOB_URL}")
        await page.goto(JOB_URL, wait_until="domcontentloaded")
        await random_delay(3, 4)

        # Click apply
        apply_btn = await page.query_selector("button#apply-button, button.apply-button, button:has-text('Apply')")
        if not apply_btn:
            print("No apply button found — URL may be stale")
            return

        btn_text = (await apply_btn.inner_text()).strip()
        print(f"Apply button text: '{btn_text}'")
        if "company site" in btn_text.lower():
            print("External redirect — pick a different URL")
            return

        await apply_btn.click()
        await random_delay(4, 6)

        # Dump the chatbot drawer
        drawer = await page.query_selector("#chatbot_Drawer, .chatbot_MessageContainer")
        if not drawer:
            print("No chatbot drawer opened")
            return

        outer = await drawer.evaluate("el => el.outerHTML")
        with open("output/chatbot_dom.html", "w", encoding="utf-8") as f:
            f.write(outer)
        print(f"Dumped {len(outer)} chars to output/chatbot_dom.html")

        # Screenshot for visual reference
        await page.screenshot(path="output/chatbot_screenshot.png", full_page=True)
        print("Screenshot saved: output/chatbot_screenshot.png")

        # Keep open 8s so you can see
        await asyncio.sleep(8)

    finally:
        await browser.close()
        await playwright.stop()


asyncio.run(main())
