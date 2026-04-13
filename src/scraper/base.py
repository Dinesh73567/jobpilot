import asyncio
import random
from playwright.async_api import async_playwright, Browser, BrowserContext, Page
from src.logger import get_logger

logger = get_logger("scraper.base")

USER_AGENTS = [
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:125.0) Gecko/20100101 Firefox/125.0",
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
]

VIEWPORTS = [
    {"width": 1280, "height": 800},
    {"width": 1366, "height": 768},
    {"width": 1920, "height": 1080},
    {"width": 1440, "height": 900},
]


async def create_browser(config):
    """Launch Playwright browser with stealth settings."""
    playwright = await async_playwright().start()

    browser = await playwright.chromium.launch(
        headless=config.headless,
        args=[
            "--no-sandbox",
            "--disable-setuid-sandbox",
            "--disable-blink-features=AutomationControlled",
        ]
    )

    context = await browser.new_context(
        user_agent=random.choice(USER_AGENTS),
        viewport=random.choice(VIEWPORTS),
        locale="en-IN",
        timezone_id="Asia/Kolkata",
    )

    # Apply stealth patches to avoid bot detection
    await context.add_init_script("""
        Object.defineProperty(navigator, 'webdriver', { get: () => undefined });
        Object.defineProperty(navigator, 'plugins', { get: () => [1, 2, 3] });
        Object.defineProperty(navigator, 'languages', { get: () => ['en-IN', 'en'] });
        window.chrome = { runtime: {} };
    """)

    page = await context.new_page()
    page.set_default_timeout(config.timeout_sec * 1000)

    logger.info(f"Browser launched (headless={config.headless})")
    return playwright, browser, context, page


async def random_delay(min_sec: float = 0.5, max_sec: float = 2.5):
    """Wait a random amount of time to mimic human behaviour."""
    delay = random.uniform(min_sec, max_sec)
    await asyncio.sleep(delay)


async def safe_click(page: Page, selector: str, delay_min: float = 0.5, delay_max: float = 1.5):
    """Click an element with a human-like delay before and after."""
    await random_delay(delay_min, delay_max)
    element = await page.wait_for_selector(selector, state="visible")
    await element.scroll_into_view_if_needed()
    await random_delay(0.2, 0.5)
    await element.click()
    await random_delay(delay_min, delay_max)


async def safe_type(page: Page, selector: str, text: str):
    """Type text character by character with random delays (human-like)."""
    await random_delay(0.3, 0.8)
    element = await page.wait_for_selector(selector, state="visible")
    await element.click()
    await random_delay(0.1, 0.3)

    for char in text:
        await element.type(char, delay=random.randint(50, 180))

    await random_delay(0.3, 0.8)
