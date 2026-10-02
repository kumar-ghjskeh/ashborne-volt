"""Ad-hoc end-to-end test of a scraper adapter against a live company config.
    py -m backend.scripts.try_adapter phenom AMD
"""
from __future__ import annotations

import asyncio
import sys
from pathlib import Path

if __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from backend.app.config import load_all_companies  # noqa: E402
from backend.app.location_utils import parse_location  # noqa: E402
from backend.app.scrapers import get_scraper  # noqa: E402


def _ascii(s: str) -> str:
    return (s or "").encode("ascii", "replace").decode("ascii")


async def run(company_name: str) -> None:
    companies = load_all_companies()
    cfg = next((c for c in companies if c["name"].lower() == company_name.lower()), None)
    if not cfg:
        print(f"company {company_name!r} not found in config"); return
    print(f"Config: ats={cfg.get('ats_platform')} -> {cfg.get('phenom_host') or cfg.get('jobvite_company') or ''}")
    async with get_scraper(cfg) as sc:
        jobs = await sc.fetch_jobs()
    usa = 0
    for j in jobs:
        loc = parse_location(j.location, j.full_description_text or "")
        if loc.is_usa:
            usa += 1
    print(f"relevant jobs: {len(jobs)}   USA: {usa}")
    print("--- sample (first 15) ---")
    for j in jobs[:15]:
        loc = parse_location(j.location, "")
        tag = "US" if loc.is_usa else "--"
        print(f"  [{tag}] {_ascii(j.job_title)[:46]:46} | {_ascii(j.location)[:28]:28} | "
              f"posted={j.posted_date} | {_ascii(j.apply_url)[:54]}")


if __name__ == "__main__":
    name = sys.argv[2] if len(sys.argv) > 2 else (sys.argv[1] if len(sys.argv) > 1 else "AMD")
    asyncio.run(run(name))
