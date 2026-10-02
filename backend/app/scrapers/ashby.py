"""Ashby public job board API scraper.

Uses the documented public posting API:
    https://api.ashbyhq.com/posting-api/job-board/{org}
which returns a stable ``{"jobs": [...]}`` payload — no browser, no auth.
"""

from __future__ import annotations

import logging
from datetime import datetime

from .base import BaseScraper, JobData

logger = logging.getLogger(__name__)

API_BASE = "https://api.ashbyhq.com/posting-api/job-board/{org}"


class AshbyScraper(BaseScraper):
    async def fetch_jobs(self) -> list[JobData]:
        org = self.config.get("ashby_org", "")
        if not org:
            logger.warning("%s: missing ashby_org config", self.company_name)
            return []

        url = API_BASE.format(org=org)
        data = await self._get_json(url, params={"includeCompensation": "false"})

        postings = data.get("jobs", []) if isinstance(data, dict) else []
        jobs: list[JobData] = []

        for item in postings:
            if item.get("isListed") is False:
                continue

            title = item.get("title", "")
            job_id = str(item.get("id", ""))
            apply_url = item.get("jobUrl", "") or item.get("applyUrl", "")

            location = item.get("location", "") or ""
            if not location:
                sec = item.get("secondaryLocations", []) or []
                if sec:
                    location = sec[0].get("locationName", "") or sec[0].get("location", "")
            if item.get("isRemote") and "remote" not in location.lower():
                location = f"{location} (Remote)".strip()

            published = item.get("publishedAt") or item.get("updatedAt")
            posted = None
            if published:
                try:
                    posted = datetime.fromisoformat(published.replace("Z", "+00:00"))
                except Exception:
                    pass

            description = item.get("descriptionPlain", "") or ""
            snippet = description[:500]

            jobs.append(
                JobData(
                    job_title=title,
                    apply_url=apply_url,
                    location=location,
                    job_id=job_id,
                    source_url=f"https://jobs.ashbyhq.com/{org}",
                    posted_date=posted,
                    description_snippet=snippet,
                    full_description_text=description,
                )
            )

        return self._filter_relevant(jobs)
