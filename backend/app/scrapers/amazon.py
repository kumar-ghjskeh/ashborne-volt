"""Amazon Jobs scraper using their public search JSON API."""

from __future__ import annotations

import asyncio
import logging
from datetime import datetime

from .base import BaseScraper, JobData
from ..taxonomy import DEFAULT_SEARCH_TERMS as _EE_TERMS

logger = logging.getLogger(__name__)

SEARCH_URL = "https://www.amazon.jobs/en/search.json"


class AmazonScraper(BaseScraper):
    async def fetch_jobs(self) -> list[JobData]:
        keywords = self.config.get("search_keywords", list(_EE_TERMS))
        jobs: list[JobData] = []
        seen: set[str] = set()

        for kw in keywords[:4]:
            fetched = await self._search(kw, seen)
            jobs.extend(fetched)
            await asyncio.sleep(2)

        return self._filter_relevant(jobs)

    async def _search(self, keyword: str, seen: set[str]) -> list[JobData]:
        jobs: list[JobData] = []
        offset = 0

        while True:
            try:
                data = await self._get_json(
                    SEARCH_URL,
                    params={
                        "base_query": keyword,
                        "loc_query": "United States",
                        "offset": offset,
                        "result_limit": 10,
                        "sort": "recent",
                        "normalized_country_code[]": "USA",
                    },
                )
            except Exception as e:
                logger.error("Amazon fetch failed kw=%s: %s", keyword, e)
                break

            items = data.get("jobs", [])
            if not items:
                break

            for item in items:
                job_id = item.get("id_icims", "") or item.get("id", "")
                if job_id and job_id in seen:
                    continue
                if job_id:
                    seen.add(str(job_id))

                title = item.get("title", "")
                location = item.get("location", "")
                apply_url = "https://www.amazon.jobs" + item.get("job_path", "")
                description = item.get("description", "")
                basic_quals = item.get("basic_qualifications", "")
                full_desc = (description + " " + basic_quals).strip()
                snippet = full_desc[:500]

                posted_str = item.get("posted_date", "")
                posted = None
                if posted_str:
                    try:
                        posted = datetime.strptime(posted_str, "%B %d, %Y")
                    except Exception:
                        pass

                jobs.append(JobData(
                    job_title=title,
                    apply_url=apply_url,
                    location=location,
                    job_id=str(job_id),
                    source_url="https://www.amazon.jobs",
                    posted_date=posted,
                    description_snippet=snippet,
                    full_description_text=full_desc,
                ))

            hits_count = data.get("hits", 0)
            offset += 10
            if offset >= hits_count or offset >= 100:
                break
            await asyncio.sleep(1)

        return jobs
