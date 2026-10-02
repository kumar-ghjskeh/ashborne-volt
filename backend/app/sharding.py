"""Split the company catalog across parallel scrape jobs.

Why shard at all: one job scrapes about 19 s per company, and GitHub Actions
jobs are capped by a timeout. On Ashborne Silicon a single job broke at roughly
90 companies; Volt's catalog is meant to be several times that. Parallel shards
keep each job short, and one failing shard costs only its own companies — the
publish step keeps their previous rows.

Rules:

* **Group by host, then pack groups.** Every company on a shared job-board host
  (all Greenhouse boards answer from boards-api.greenhouse.io) lands in the same
  shard, so that host only ever sees one client at a time. Workday tenants are
  separate hosts and spread freely.
* **Deterministic.** The same catalog and shard count always produce the same
  assignment, so a company's shard is stable between runs and logs are
  comparable.
* **Browser companies get their own shard** — only that job installs Chromium.
"""

from __future__ import annotations

import math
from urllib.parse import urlparse

from .config import load_all_companies

# Rough relative cost of one company per platform (detail fetches dominate).
_COST = {"workday": 3, "oracle": 2, "eightfold": 2, "icims": 2, "phenom": 2, "jobs2web": 2}
TARGET_COST_PER_SHARD = 36
MAX_SHARDS = 16


def engine_of(cfg: dict) -> str:
    return cfg.get("engine") or "httpx"


def scraped_by_ci(cfg: dict) -> bool:
    """Would any CI runner scrape this company? cf/browser companies are picked by
    their engine flag regardless of ``enabled`` (they used to be kept disabled so
    the httpx pass skipped them)."""
    return bool(cfg.get("enabled", True)) or engine_of(cfg) in ("cf", "browser")


def host_group(cfg: dict) -> str:
    """The host this company's scraper talks to."""
    p = (cfg.get("ats_platform") or "").lower()
    if p == "workday":
        return f"{cfg.get('workday_tenant', '')}.{cfg.get('workday_instance', 'wd1')}.myworkdayjobs.com"
    if p in ("greenhouse", "lever", "ashby", "smartrecruiters", "eightfold", "amazon"):
        return p
    for key in ("icims_host", "oracle_host", "jobs2web_host", "phenom_host", "radancy_host",
                "avature_host", "jobvite_host"):
        if cfg.get(key):
            return urlparse(str(cfg[key]) if "//" in str(cfg[key]) else f"https://{cfg[key]}").netloc
    return urlparse(cfg.get("careers_url", "")).netloc or cfg.get("name", "")


def _cost(cfg: dict) -> int:
    return _COST.get((cfg.get("ats_platform") or "").lower(), 1)


def plan(companies: list[dict] | None = None, shard_count: int | None = None) -> dict[str, list[str]]:
    """Return {shard_id: [company names]}. Shard ids are "0".."N-1" plus
    "browser" when any browser company exists."""
    cfgs = [c for c in (companies if companies is not None else load_all_companies())
            if scraped_by_ci(c)]
    browser = sorted(c["name"] for c in cfgs if engine_of(c) == "browser")
    rest = [c for c in cfgs if engine_of(c) != "browser"]

    groups: dict[str, list[dict]] = {}
    for c in rest:
        groups.setdefault(host_group(c), []).append(c)

    total = sum(_cost(c) for c in rest)
    if shard_count is None:
        shard_count = max(1, min(MAX_SHARDS, math.ceil(total / TARGET_COST_PER_SHARD)))

    bins: list[list[str]] = [[] for _ in range(shard_count)]
    load = [0] * shard_count
    # Largest groups first, ties by host name — stable greedy packing.
    for host, members in sorted(groups.items(), key=lambda kv: (-sum(_cost(c) for c in kv[1]), kv[0])):
        i = min(range(shard_count), key=lambda k: (load[k], k))
        bins[i].extend(sorted(c["name"] for c in members))
        load[i] += sum(_cost(c) for c in members)

    out = {str(i): sorted(b) for i, b in enumerate(bins)}
    if browser:
        out["browser"] = browser
    return out


def companies_for(shard: str, shard_count: int | None = None) -> set[str] | None:
    """Company names for one shard id; None means "all" (a full local run)."""
    if shard in ("", "all"):
        return None
    return set(plan(shard_count=shard_count).get(shard, []))


if __name__ == "__main__":
    import json
    import sys

    p = plan(shard_count=int(sys.argv[1]) if len(sys.argv) > 1 else None)
    # The workflow's matrix reads this line.
    print(json.dumps(sorted(p.keys(), key=lambda k: (k == "browser", k.zfill(3)))))
