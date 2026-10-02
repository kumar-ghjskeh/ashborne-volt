"""Local runner for ``engine: cf`` companies — Cloudflare-walled sites scraped
via curl_cffi (Chrome TLS impersonation). Mirrors the browser runner: it scrapes
each cf company with its registered adapter and persists through the shared
``persist_company_results`` pipeline (identical scoring/dedup as the cloud).

Never imported by the FastAPI web service or the httpx scheduler, so the Render
tier (no curl_cffi needed) is unaffected.

    DATABASE_URL="<prod url>" python -m backend.app.run_cf_scrape
    python -m backend.app.run_cf_scrape --only "Ampere Computing"
"""
from __future__ import annotations

import argparse
import asyncio
import logging
from datetime import datetime, timezone

from sqlmodel import Session

from .config import load_cf_companies, load_schedule
from .database import engine, init_db
from .models import ScrapeRun
from .scrape_engine import (
    is_quarantined, maintain_scrape_runs, persist_company_results, record_company_outcome,
)
from .scrapers.cf import cf_scraper_for

logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
logger = logging.getLogger("run_cf_scrape")


async def main(only: list[str] | set[str] | None = None) -> int:
    init_db()
    threshold = load_schedule().get("removed_job_threshold", 4)
    companies = load_cf_companies()
    if only is not None:
        wanted = {n.lower() for n in only}
        companies = [c for c in companies if c["name"].lower() in wanted]
    if not companies:
        print("No engine:cf companies matched."); return 0

    # Log this as a ScrapeRun so curl_cffi scrapes show up in Data Health like the
    # httpx/browser runs (and clean up zombie/old runs first).
    run = ScrapeRun(triggered_by="cf")
    with Session(engine) as s:
        maintain_scrape_runs(s)
        s.add(run); s.commit(); s.refresh(run)
        run_id = run.id

    print(f"cf runner: {len(companies)} company(ies)")
    found = new_total = removed_total = errors = scraped = 0
    for cfg in companies:
        name = cfg["name"]
        if is_quarantined(name):
            print(f"  {name}: skipped (quarantined)")
            continue
        try:
            async with cf_scraper_for(cfg) as sc:
                raw = await sc.fetch_jobs()
            new, removed = await persist_company_results(cfg, raw, threshold)
            found += len(raw); new_total += new; removed_total += removed; scraped += 1
            record_company_outcome(run_id, name, found=len(raw))
            print(f"  {name}: fetched={len(raw)} new={new} removed={removed}")
        except Exception as e:
            errors += 1
            record_company_outcome(run_id, name, error=e)
            print(f"  {name}: FAILED {type(e).__name__}: {e}")

    with Session(engine) as s:
        r = s.get(ScrapeRun, run_id)
        if r:
            r.finished_at = datetime.now(timezone.utc)
            r.companies_scraped = scraped
            r.jobs_found = found
            r.new_jobs = new_total
            r.removed_jobs = removed_total
            r.errors = errors
            s.add(r); s.commit()
    return scraped


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--only", nargs="*", help="Only scrape these company names")
    args = ap.parse_args()
    asyncio.run(main(args.only))
