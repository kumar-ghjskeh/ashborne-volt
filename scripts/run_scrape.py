"""Manually trigger a full scrape cycle from the command line."""

import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parents[1] / "backend"))

from app.database import init_db
from app.scrape_engine import run_scrape


async def main():
    init_db()
    print("Starting manual scrape...")
    run = await run_scrape(triggered_by="manual")
    print(f"Done. {run.new_jobs} new jobs, {run.jobs_found} found, {run.errors} errors.")


if __name__ == "__main__":
    asyncio.run(main())
