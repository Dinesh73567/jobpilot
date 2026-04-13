"""
Test a single Naukri job apply — isolates the chatbot flow so we can iterate fast.
Usage: python test_single_apply.py <job_url>
"""
import asyncio
import sys
import os
from src.config_manager import load as load_config
from src.scraper.base import create_browser, random_delay
from src.scraper.naukri import login as naukri_login, apply_job, _handle_chatbot
from src.filter_engine import RawJob


async def main():
    if len(sys.argv) < 2:
        print("Usage: python test_single_apply.py <naukri-job-url>")
        return

    url = sys.argv[1]
    config = load_config()
    config.headless = False

    playwright, browser, context, page = await create_browser(config)

    try:
        if not await naukri_login(page, config):
            print("Login failed")
            return

        # Build a minimal RawJob for apply_job
        job = RawJob(
            platform="naukri",
            job_id=url.split("-")[-1],
            title="Test Apply",
            company="Test",
            location="",
            salary_text="",
            salary_min=None,
            salary_max=None,
            experience_text="",
            experience_min=None,
            experience_max=None,
            required_skills=[],
            apply_type="naukri_apply",
            job_url=url,
        )

        result = await apply_job(page, job, config)
        print(f"\n=== RESULT: {result} ===\n")

        # If stuck, dump the current chatbot DOM for inspection
        if result in ("chatbot_stuck", "failed"):
            tag = os.environ.get("DUMP_TAG", "default")
            drawer = await page.query_selector(".chatbot_MessageContainer")
            if drawer:
                html = await drawer.evaluate("el => el.outerHTML")
                with open(f"output/stuck_{tag}.html", "w", encoding="utf-8") as f:
                    f.write(html)
                print(f"Dumped DOM to output/stuck_{tag}.html")
            await page.screenshot(path=f"output/stuck_{tag}.png", full_page=True)
            print(f"Screenshot: output/stuck_{tag}.png")

        await asyncio.sleep(6)

    finally:
        await browser.close()
        await playwright.stop()


asyncio.run(main())
