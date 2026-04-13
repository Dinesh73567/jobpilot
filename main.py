import argparse
import asyncio
import sys
from src.config_manager import load as load_config, ConfigError
from src.tracker import Tracker
from src.logger import get_logger

logger = get_logger("main")


def parse_args():
    parser = argparse.ArgumentParser(description="JobPilot — Automated Job Application Bot")
    parser.add_argument(
        "--mode",
        choices=["manual", "scheduled", "background"],
        default="manual",
        help="Run mode: manual (once), scheduled (cron), background (continuous)"
    )
    parser.add_argument("--dry-run", action="store_true", help="Go through apply flow but don't submit")
    parser.add_argument("--visible", action="store_true", help="Show browser window (non-headless)")
    parser.add_argument(
        "--platform",
        choices=["naukri", "linkedin", "both"],
        default="naukri",
        help="Which platform(s) to run (default: naukri only)"
    )
    parser.add_argument("--config", default="config.yaml", help="Path to config file")
    return parser.parse_args()


async def run_once(config, tracker, platform: str):
    """One full cycle: scrape → filter → apply → log."""
    from src.scraper.base import create_browser
    from src.filter_engine import filter_jobs

    logger.info("=== Pipeline started ===")
    logger.info(f"Mode: {'DRY RUN' if config.dry_run else 'LIVE'} | Platform: {platform}")

    today_count = tracker.get_today_count()
    if today_count >= config.daily_apply_limit:
        logger.info(f"Daily limit reached ({today_count}/{config.daily_apply_limit}). Stopping.")
        return

    logger.info(f"Applied today so far: {today_count}/{config.daily_apply_limit}")

    playwright, browser, context, page = await create_browser(config)

    try:
        if platform in ("naukri", "both"):
            await _run_naukri(page, config, tracker)

        if platform in ("linkedin", "both"):
            logger.info("LinkedIn pipeline not built yet — skipping")

        logger.info(
            f"=== Pipeline complete. Applied today: "
            f"{tracker.get_today_count()}/{config.daily_apply_limit} ==="
        )
    finally:
        await browser.close()
        await playwright.stop()


async def _run_naukri(page, config, tracker):
    from src.scraper.naukri import login, search_jobs, apply_job
    from src.filter_engine import filter_jobs

    if not await login(page, config):
        logger.error("Naukri login failed. Stopping Naukri pipeline.")
        return

    raw_jobs = await search_jobs(page, config)
    logger.info(f"Naukri: {len(raw_jobs)} raw jobs found across all searches")

    filtered = filter_jobs(raw_jobs, config, tracker)

    for job in filtered:
        if tracker.get_today_count() >= config.daily_apply_limit:
            logger.info("Daily limit reached mid-run. Stopping.")
            break

        job_data = {**job.raw.__dict__, "skills_match_pct": job.skills_match_pct}

        if job.decision == "apply":
            status = await apply_job(page, job.raw, config)
            await tracker.log(job_data, status=status, reason=job.reason)
        else:
            await tracker.log(job_data, status=job.decision, reason=job.reason)


async def main():
    args = parse_args()

    try:
        config = load_config(args.config)
    except ConfigError as e:
        logger.error(f"Config error: {e}")
        sys.exit(1)

    if args.dry_run:
        config.dry_run = True
        logger.info("DRY RUN mode enabled — no real applications will be submitted")

    if args.visible:
        config.headless = False
        logger.info("Non-headless mode — browser window will be visible")

    tracker = Tracker(config.csv_path)

    logger.info(f"Starting JobPilot in [{args.mode}] mode (platform={args.platform})")

    if args.mode == "manual":
        await run_once(config, tracker, args.platform)
        logger.info("Manual run complete.")

    elif args.mode == "scheduled":
        from src.scheduler import start_scheduled
        start_scheduled(lambda: asyncio.create_task(run_once(config, tracker, args.platform)), config)

    elif args.mode == "background":
        from src.scheduler import start_background
        start_background(lambda: asyncio.create_task(run_once(config, tracker, args.platform)), config)


if __name__ == "__main__":
    asyncio.run(main())
