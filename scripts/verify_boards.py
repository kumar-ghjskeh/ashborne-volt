"""Measure what a job board would actually contribute before enabling it.

For each board: how many postings it lists, how many the EE classifier keeps on
title alone, how many more are "maybe" (decided by description), how many are
in the US, and which categories they fall into. Prints a YAML entry for boards
worth enabling.

    py scripts/verify_boards.py "Duke Energy|workday|dukeenergy.wd1/search"
    py scripts/verify_boards.py --file boards.txt

Board specs (one per line in --file):
    Name|workday|tenant.wdN/site
    Name|greenhouse|board
    Name|lever|company
    Name|ashby|org
    Name|smartrecruiters|company
    Name|icims|host
"""
from __future__ import annotations

import asyncio
import json
import sys
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from backend.app import taxonomy as tx  # noqa: E402
from backend.app.location_utils import parse_location  # noqa: E402
from backend.app.scrapers import get_scraper  # noqa: E402
from backend.app.scrapers.workday import CXS_URL, LIMIT, WorkdayScraper, find_facets  # noqa: E402


def cfg_for(name: str, ats: str, spec: str) -> dict:
    c = {"name": name, "ats_platform": ats}
    if ats == "workday":
        host, site = spec.split("/", 1)
        tenant, inst = host.split(".")[:2]
        c.update(workday_tenant=tenant, workday_instance=inst, workday_career_site=site)
    elif ats == "greenhouse":
        c["greenhouse_board"] = spec
    elif ats == "lever":
        c["lever_company"] = spec
    elif ats == "ashby":
        c["ashby_org"] = spec
    elif ats == "smartrecruiters":
        c["smartrecruiters_company"] = spec
    elif ats == "eightfold":
        tenant, domain = spec.split("/", 1)
        c.update(eightfold_tenant=tenant, eightfold_domain=domain)
    elif ats == "jibe":
        c["jibe_host"] = spec
    elif ats == "icims":
        c["icims_host"] = spec if spec.startswith("http") else f"https://{spec}"
    return c


async def workday_titles(cfg: dict) -> tuple[list[tuple[str, str]], int, str]:
    s = WorkdayScraper(cfg)
    t, i, site = cfg["workday_tenant"], cfg["workday_instance"], cfg["workday_career_site"]
    base = CXS_URL.format(tenant=t, instance=i, career_site=site)
    root = f"https://{t}.{i}.myworkdayjobs.com"
    s.client.headers.update({"Origin": root, "Referer": f"{root}/{site}"})
    try:
        first = await s._post_json(base, {"appliedFacets": {}, "limit": LIMIT, "offset": 0, "searchText": ""})
        total = int(first.get("total") or 0)
        facets = find_facets(first.get("facets")) if total > 600 else {}
        rows = await s._scan(base, "", facets, set(), 0, 1500)
        mode = "faceted" if facets else "full"
        return [(r.job_title, r.location) for r in rows], total, mode
    finally:
        await s.client.aclose()


async def adapter_titles(cfg: dict) -> tuple[list[tuple[str, str]], int, str]:
    # Generic adapters filter internally; bypass that to count everything listed.
    from backend.app.scrapers import base as base_mod
    orig = base_mod.BaseScraper._filter_relevant
    base_mod.BaseScraper._filter_relevant = lambda self, jobs, keep_maybe=False: jobs
    try:
        async with get_scraper(cfg) as s:
            jobs = await s.fetch_jobs()
    finally:
        base_mod.BaseScraper._filter_relevant = orig
    return [(j.job_title, j.location) for j in jobs], len(jobs), "list"


async def verify(name: str, ats: str, spec: str) -> dict:
    cfg = cfg_for(name, ats, spec)
    try:
        rows, total, mode = await (workday_titles(cfg) if ats == "workday" else adapter_titles(cfg))
    except Exception as e:
        return {"name": name, "ats": ats, "spec": spec, "error": f"{type(e).__name__}: {e}"[:160]}
    keep = maybe = us_keep = 0
    cats: Counter = Counter()
    samples = []
    for title, loc in rows:
        v = tx.classify(title)
        is_us = parse_location(loc or "", "").is_usa
        if v.relevant:
            keep += 1
            us_keep += is_us
            cats[v.category] += 1
            if len(samples) < 6:
                samples.append(title)
        elif v.needs_description:
            maybe += 1
    return {"name": name, "ats": ats, "spec": spec, "board": total, "listed": len(rows),
            "mode": mode, "keep": keep, "us_keep": us_keep, "maybe": maybe,
            "categories": dict(cats.most_common()), "samples": samples}


def main() -> None:
    args = sys.argv[1:]
    specs: list[str] = []
    if args and args[0].startswith("--file="):
        specs = [ln.strip() for ln in Path(args[0].split("=", 1)[1]).read_text(encoding="utf-8").splitlines()
                 if ln.strip() and not ln.startswith("#")]
    else:
        specs = args
    for spec in specs:
        name, ats, s = spec.split("|", 2)
        r = asyncio.run(verify(name.strip(), ats.strip(), s.strip()))
        print(json.dumps(r, ensure_ascii=False), flush=True)


if __name__ == "__main__":
    main()
