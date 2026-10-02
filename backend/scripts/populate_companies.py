"""Scrape specific companies and persist them to whatever DATABASE_URL points at
(local SQLite by default, or prod when DATABASE_URL=<render external url>). Used
to populate newly-unlocked cloud companies without a full all-company scrape.

    DATABASE_URL="<prod url>" py -m backend.scripts.populate_companies AMD "Keysight Technologies"
"""
from __future__ import annotations

import asyncio
import sys
from pathlib import Path

if __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from backend.app.config import load_all_companies  # noqa: E402
from backend.app.database import engine  # noqa: E402
from backend.app.scrape_engine import persist_company_results  # noqa: E402
from backend.app.scrapers import get_scraper  # noqa: E402

REMOVED_THRESHOLD = 4


async def run(names: list[str]) -> None:
    print(f"DB dialect: {engine.dialect.name}")
    companies = {c["name"].lower(): c for c in load_all_companies()}
    for name in names:
        cfg = companies.get(name.lower())
        if not cfg:
            print(f"  {name}: NOT FOUND in config"); continue
        try:
            async with get_scraper(cfg) as sc:
                raw = await sc.fetch_jobs()
        except Exception as e:
            print(f"  {name}: scrape FAILED {type(e).__name__}: {e}"); continue
        new, removed = await persist_company_results(cfg, raw, REMOVED_THRESHOLD)
        print(f"  {name}: fetched={len(raw)} new={new} removed={removed}")


if __name__ == "__main__":
    targets = sys.argv[1:] or ["AMD", "Keysight Technologies"]
    asyncio.run(run(targets))
