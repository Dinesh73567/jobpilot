import asyncio
from src.config_manager import load as load_config
from src.scraper.base import create_browser, safe_type, safe_click, random_delay

async def test_naukri_login():
    config = load_config()
    config.headless = False  # Show the browser so you can see what's happening

    playwright, browser, context, page = await create_browser(config)

    try:
        print("Opening Naukri login page...")
        await page.goto("https://www.naukri.com/nlogin/login", wait_until="domcontentloaded")
        await random_delay(2, 3)

        print("Typing email...")
        # Naukri's login form uses placeholder-based selectors
        await safe_type(page, 'input[placeholder*="Email" i]', config.naukri_email)

        print("Typing password...")
        await safe_type(page, 'input[placeholder*="password" i]', config.naukri_password)

        print("Clicking login button...")
        await safe_click(page, 'button[type="submit"]')

        await random_delay(4, 6)

        # Check if login succeeded — Naukri redirects to mnjuser/homepage or similar
        current_url = page.url
        print(f"Current URL after login: {current_url}")

        if "mnjuser" in current_url or "homepage" in current_url or "nlogin" not in current_url:
            print("Naukri login SUCCESSFUL!")
        elif "captcha" in current_url.lower() or "verify" in current_url.lower():
            print("Naukri is asking for verification (CAPTCHA). Check the browser window.")
        else:
            # Check for error messages on the page
            error_text = await page.locator('text=/invalid|incorrect|error/i').first.text_content() \
                if await page.locator('text=/invalid|incorrect|error/i').count() > 0 else None
            if error_text:
                print(f"Login failed with error: {error_text}")
            else:
                print(f"Still on login page — check browser window for details")

        print("\nKeeping browser open for 10 seconds so you can inspect...")
        await asyncio.sleep(10)

    finally:
        await browser.close()
        await playwright.stop()

asyncio.run(test_naukri_login())
