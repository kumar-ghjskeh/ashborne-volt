"""APScheduler — tier-based sync frequency + daily email digest.

S-tier every 45 min, A-tier every 3 h, B-tier every 8 h, C-tier daily.
(On a host that sleeps when idle, e.g. Render free tier, these fire only while
the service is awake — keep it warm with an uptime pinger to run on schedule.)
"""

from __future__ import annotations

import logging

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger
from apscheduler.triggers.interval import IntervalTrigger

from .config import load_schedule

logger = logging.getLogger(__name__)

_scheduler: AsyncIOScheduler | None = None

# tier -> minutes between syncs
TIER_INTERVALS = {
    "S": 45,        # 30–60 min
    "A": 180,       # 2–4 h
    "B": 480,       # 6–12 h
    "C": 1440,      # daily
}


def create_scheduler() -> AsyncIOScheduler:
    global _scheduler
    cfg = load_schedule()
    tz = cfg.get("timezone", "America/New_York")
    _scheduler = AsyncIOScheduler(timezone=tz)

    def _tier_job(priorities: set[str]):
        async def _run():
            from .scrape_engine import run_scrape
            logger.info("Tier sync starting for %s", priorities)
            await run_scrape(triggered_by=f"scheduler:{'+'.join(sorted(priorities))}", priorities=priorities)
        return _run

    for tier, minutes in TIER_INTERVALS.items():
        _scheduler.add_job(
            _tier_job({tier}),
            IntervalTrigger(minutes=minutes, timezone=tz),
            id=f"sync_tier_{tier}",
            replace_existing=True,
            misfire_grace_time=600,
            max_instances=1,
        )
        logger.info("Scheduled %s-tier sync every %d min", tier, minutes)

    # Daily email digest at 07:00 local (sends only if SMTP configured).
    async def _digest():
        from .database import engine
        from sqlmodel import Session
        from .services.digest import build_digest, send_digest_email
        with Session(engine) as s:
            data = build_digest(s)
        await send_digest_email(data)

    _scheduler.add_job(
        _digest, CronTrigger(hour=7, minute=0, timezone=tz),
        id="daily_digest", replace_existing=True, misfire_grace_time=3600,
    )
    logger.info("Scheduled daily digest at 07:00 %s", tz)

    return _scheduler


def get_scheduler() -> AsyncIOScheduler | None:
    return _scheduler
