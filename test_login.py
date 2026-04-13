import asyncio
from src.config_manager import load as load_config
from src.scraper.base import create_browser, safe_type, safe_click, random_delay

async def test_linkedin_login():
    config = load_config()
    config.headless = False  # Show the browser

    playwright, browser, context, page = await create_browser(config)

    try:
        print("Opening LinkedIn login page...")
        await page.goto("https://www.linkedin.com/login")
        await random_delay(1, 2)

        print("Typing email...")
        await safe_type(page, "#username", config.linkedin_email)

        print("Typing password...")
        await safe_type(page, "#password", config.linkedin_password)

        print("Clicking sign in...")
        await safe_click(page, '[data-litms-control-urn="login-submit"]')

        await random_delay(3, 5)

        # Check if login succeeded
        if "feed" in page.url or "mynetwork" in page.url:
            print("LinkedIn login SUCCESSFUL!")
        elif "checkpoint" in page.url or "challenge" in page.url:
            print("LinkedIn is asking for verification (CAPTCHA/2FA). Check the browser window.")
        else:
            print(f"Unknown page after login: {page.url}")

        await asyncio.sleep(5)  # Keep browser open for 5 seconds so you can see

    finally:
        await browser.close()
        await playwright.stop()

asyncio.run(test_linkedin_login())
