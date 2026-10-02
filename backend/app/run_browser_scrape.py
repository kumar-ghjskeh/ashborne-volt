"""Local real-browser scrape runner.

Drives the Playwright-backed :class:`BrowserWorkdayScraper` over every company
marked ``engine: browser`` in ``companies.yaml`` and persists results with the
exact same scoring/dedup/removal pipeline as the httpx scheduler.

Run it on your own machine (Chromium required); it writes to whatever
``DATABASE_URL`` is configured:

    # local SQLite (default) — safe for testing
    py -m backend.app.run_browser_scrape

    # write straight to the live site's Postgres
    #   set DATABASE_URL to Render's *External* connection string in backend/.env
    py -m backend.app.run_browser_scrape

Flags:
    --headed       show the browser window (default: headless)
    --only NAME    scrape just one company (case-insensitive substring match)
"""

from __future__ import annotations

import argparse
import asyncio
import logging
import sys
from datetime import datetime, timezone
from pathlib import Path

# Allow `py backend/app/run_browser_scrape.py` as well as `-m`.
if __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from sqlmodel import Session  # noqa: E402

from backend.app.config import load_browser_companies, load_schedule  # noqa: E402
from backend.app.database import engine, init_db  # noqa: E402
from backend.app.models import ScrapeRun  # noqa: E402
from backend.app.scrape_engine import (  # noqa: E402
    is_quarantined,
    persist_company_results,
    record_company_outcome,
)
from backend.app.scrapers.browser import (  # noqa: E402
    browser_context,
    browser_scraper_for,
)

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger("browser_scrape")


async def run_browser_scrape(headless: bool = True, only: str | None = None,
                             names: set[str] | None = None) -> int:
    """Scrape every ``engine: browser`` company (or a subset). Returns the number
    of companies that scraped successfully."""
    init_db()

    companies = load_browser_companies()
    if only:
        companies = [c for c in companies if only.lower() in c["name"].lower()]
    if names is not None:
        companies = [c for c in companies if c["name"] in names]
    if not companies:
        logger.warning("No engine:browser companies matched — nothing to do.")
        return 0

    removed_threshold = load_schedule().get("removed_job_threshold", 4)

    run = ScrapeRun(triggered_by="browser")
    with Session(engine) as session:
        from .scrape_engine import maintain_scrape_runs
        maintain_scrape_runs(session)
        session.add(run)
        session.commit()
        session.refresh(run)
        run_id = run.id

    logger.info("Browser scrape starting for %d companies: %s",
                len(companies), ", ".join(c["name"] for c in companies))

    total_found = total_new = total_removed = total_errors = scraped = 0

    async with browser_context(headless=headless) as ctx:
        for cfg in companies:
            name = cfg["name"]
            if is_quarantined(name):
                logger.warning("  %-22s skipped (quarantined)", name)
                continue
            try:
                scraper = browser_scraper_for(cfg, ctx)
                async with scraper:
                    raw_jobs = await scraper.fetch_jobs()
                new_count, removed_count = await persist_company_results(
                    cfg, raw_jobs, removed_threshold
                )
                scraped += 1
                total_found += len(raw_jobs)
                total_new += new_count
                total_removed += removed_count
                # A DOM scrape fails by returning nothing rather than raising, so
                # the empty-run counter is the only alarm a broken selector trips.
                record_company_outcome(run_id, name, found=len(raw_jobs))
                logger.info("  %-22s found=%-3d new=%-3d removed=%-3d",
                            name, len(raw_jobs), new_count, removed_count)
            except Exception as e:
                total_errors += 1
                logger.error("  %-22s FAILED: %s", name, e)
                record_company_outcome(run_id, name, error=e)

    with Session(engine) as session:
        run_obj = session.get(ScrapeRun, run_id)
        if run_obj:
            run_obj.finished_at = datetime.now(timezone.utc)
            run_obj.companies_scraped = scraped
            run_obj.jobs_found = total_found
            run_obj.new_jobs = total_new
            run_obj.removed_jobs = total_removed
            run_obj.errors = total_errors
            session.add(run_obj)
            session.commit()

    logger.info("Browser scrape done — companies=%d found=%d new=%d removed=%d errors=%d",
                scraped, total_found, total_new, total_removed, total_errors)
    return scraped


def main() -> None:
    ap = argparse.ArgumentParser(description="Local real-browser Workday scraper")
    ap.add_argument("--headed", action="store_true", help="show the browser window")
    ap.add_argument("--only", metavar="NAME", help="scrape one company (substring match)")
    args = ap.parse_args()
    asyncio.run(run_browser_scrape(headless=not args.headed, only=args.only))


if __name__ == "__main__":
    main()
