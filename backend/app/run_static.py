"""One scrape shard — the unit the scrape workflow runs in parallel.

    1. build a scratch SQLite database in the runner's temp dir
    2. seed it with the published rows of THIS shard's companies only
    3. scrape those companies (httpx, curl_cffi and/or browser engines)
    4. re-run the classifier over every row, so taxonomy fixes are retroactive
    5. write a shard file; the publish job merges every shard into the corpus

Environment:

    SHARD        "0".."N-1", "browser", or "all" (default: a full local run)
    SHARD_COUNT  how many numbered shards the plan uses (default: auto)
    SHARD_OUT    shard file to write; when unset with SHARD=all, the result is
                 merged straight into DATA_DIR (handy for local runs)
    DATA_DIR     the published corpus (default frontend/public/data)

    SHARD=0 SHARD_COUNT=4 SHARD_OUT=out/shard-0.json python -m backend.app.run_static
"""
from __future__ import annotations

import asyncio
import logging
import os
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger("run_static")

DATA_DIR = Path(os.getenv("DATA_DIR", "frontend/public/data"))
SHARD = os.getenv("SHARD", "all").strip()
SHARD_COUNT = int(os.getenv("SHARD_COUNT", "0") or 0) or None
SHARD_OUT = os.getenv("SHARD_OUT", "").strip()


def _use_scratch_db() -> Path:
    """Point the app at a throwaway SQLite file BEFORE app.database is imported."""
    scratch = Path(os.getenv("RUNNER_TEMP", tempfile.gettempdir())) / f"volt_scrape_{SHARD}.db"
    if scratch.exists():
        scratch.unlink()
    os.environ["DATABASE_URL"] = f"sqlite:///{scratch.as_posix()}"
    return scratch


async def _run() -> int:
    from .config import load_all_companies
    from .database import init_db
    from .scrape_engine import reclassify_rows, run_scrape
    from .sharding import companies_for, engine_of, scraped_by_ci
    from .snapshot import load_snapshot_into_db, publish, seed_companies_into_db, write_shard

    started = datetime.now(timezone.utc)
    names = companies_for(SHARD, SHARD_COUNT)
    cfgs = [c for c in load_all_companies()
            if scraped_by_ci(c) and (names is None or c["name"] in names)]
    by_engine: dict[str, set[str]] = {}
    for c in cfgs:
        by_engine.setdefault(engine_of(c), set()).add(c["name"])
    logger.info("shard %s: %d companies (%s)", SHARD, len(cfgs),
                ", ".join(f"{k}={len(v)}" for k, v in sorted(by_engine.items())))

    init_db()
    load_snapshot_into_db(DATA_DIR, names)
    seed_companies_into_db(DATA_DIR, names)

    failures: list[str] = []
    scraped = 0
    if by_engine.get("httpx"):
        try:
            run = await run_scrape(triggered_by="static", only=by_engine["httpx"])
            scraped += run.companies_scraped
        except Exception as e:
            logger.exception("httpx pass FAILED")
            failures.append(f"httpx: {e}")
    if by_engine.get("cf"):
        try:
            from .run_cf_scrape import main as cf_main
            scraped += await cf_main(by_engine["cf"]) or 0
        except Exception as e:
            logger.exception("curl_cffi pass FAILED")
            failures.append(f"curl_cffi: {e}")
    if by_engine.get("browser"):
        try:
            from .run_browser_scrape import run_browser_scrape
            scraped += await run_browser_scrape(headless=True, names=by_engine["browser"])
        except Exception as e:
            logger.exception("browser pass FAILED")
            failures.append(f"browser: {e}")

    if cfgs and not scraped:
        # Publishing after a total failure would replace good rows with stale
        # ones counted as missed. Leave the previous corpus live instead.
        raise RuntimeError("no company scraped successfully: " + ("; ".join(failures) or "unknown"))

    reclassify_rows(names)

    from sqlmodel import Session, select
    from .database import engine
    from .models import ScrapeRun
    with Session(engine) as s:
        run_ids = {r.id for r in s.exec(select(ScrapeRun)).all()
                   if r.started_at and r.started_at >= started}

    if SHARD_OUT:
        write_shard(SHARD_OUT, names, run_ids)
    elif names is None:
        tmp = Path(os.getenv("RUNNER_TEMP", tempfile.gettempdir())) / "volt_shard_all.json"
        write_shard(tmp, None, run_ids)
        publish(DATA_DIR, [tmp])
    else:
        raise RuntimeError("SHARD_OUT is required when SHARD is not 'all'")

    if failures:
        logger.error("finished with failures: %s", "; ".join(failures))
    return scraped


def main() -> None:
    _use_scratch_db()
    try:
        asyncio.run(_run())
    except Exception as e:
        logger.error("shard %s failed: %s", SHARD, e)
        sys.exit(1)


if __name__ == "__main__":
    main()
