"""Dump the entire chatbot section + surrounding page HTML after clicking a radio option."""
import asyncio
import sys
from src.config_manager import load as load_config
from src.scraper.base import create_browser, random_delay
from src.scraper.naukri import login as naukri_login

URL = sys.argv[1]

async def main():
    config = load_config()
    config.headless = False
    playwright, browser, context, page = await create_browser(config)
    try:
        await naukri_login(page, config)
        await page.goto(URL, wait_until="domcontentloaded")
        await random_delay(3, 4)
        apply_btn = await page.query_selector("button#apply-button, button.apply-button, button:has-text('Apply')")
        await apply_btn.click()
        await random_delay(4, 6)

        # Click the "2 Months" radio label
        label = await page.query_selector("label[for='2 Months']")
        if label:
            await label.click()
            print("Clicked '2 Months' label")
            await asyncio.sleep(2)
        else:
            print("Label not found, trying radio input")
            radio = await page.query_selector("input[value='2 Months']")
            if radio:
                await radio.click()
                print("Clicked '2 Months' radio")
                await asyncio.sleep(2)

        # Now dump the whole chatbot + any nearby submit buttons
        chatbot = await page.query_selector(".chatbot_MessageContainer")
        if chatbot:
            html = await chatbot.evaluate("""el => {
              // also grab parent to see any sibling buttons
              const parent = el.parentElement;
              return parent ? parent.outerHTML : el.outerHTML;
            }""")
            with open("output/post_click_chatbot.html", "w") as f:
                f.write(html)
            print(f"Dumped {len(html)} chars to output/post_click_chatbot.html")

        # Also look for any button with "save" or "submit" text on the page
        buttons = await page.query_selector_all("button, div[role='button']")
        print(f"\nAll buttons on page ({len(buttons)}):")
        for btn in buttons[:30]:
            try:
                if await btn.is_visible():
                    text = (await btn.inner_text()).strip()
                    cls = await btn.get_attribute("class") or ""
                    if text and len(text) < 60:
                        print(f"  - '{text}' [class={cls[:60]}]")
            except:
                pass

        await asyncio.sleep(5)
    finally:
        await browser.close()
        await playwright.stop()

asyncio.run(main())
