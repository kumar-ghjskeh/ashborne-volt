"""Lever public postings API scraper."""

from __future__ import annotations

import logging
from datetime import datetime, timezone

from .base import BaseScraper, JobData

logger = logging.getLogger(__name__)

API_BASE = "https://api.lever.co/v0/postings/{company}"


class LeverScraper(BaseScraper):
    async def fetch_jobs(self) -> list[JobData]:
        company_slug = self.config.get("lever_company", "")
        if not company_slug:
            logger.warning("%s: missing lever_company config", self.company_name)
            return []

        url = API_BASE.format(company=company_slug)
        try:
            data = await self._get_json(url, params={"mode": "json"})
        except Exception as e:
            logger.error("Lever fetch failed for %s: %s", self.company_name, e)
            raise

        if not isinstance(data, list):
            return []

        jobs: list[JobData] = []
        for item in data:
            title = item.get("text", "")
            job_id = item.get("id", "")
            apply_url = item.get("hostedUrl", "") or item.get("applyUrl", "")
            location_obj = item.get("categories", {})
            location = location_obj.get("location", "") if isinstance(location_obj, dict) else ""

            created_ts = item.get("createdAt")
            posted = None
            if created_ts:
                try:
                    posted = datetime.fromtimestamp(created_ts / 1000, tz=timezone.utc)
                except Exception:
                    pass

            lists_data = item.get("lists", [])
            description_parts: list[str] = []
            for lst in lists_data:
                content = lst.get("content", "")
                description_parts.append(_strip_html(content))
            description = " ".join(description_parts)
            snippet = description[:500]

            jobs.append(
                JobData(
                    job_title=title,
                    apply_url=apply_url,
                    location=location,
                    job_id=job_id,
                    source_url=f"https://jobs.lever.co/{company_slug}",
                    posted_date=posted,
                    description_snippet=snippet,
                    full_description_text=description,
                )
            )

        return self._filter_relevant(jobs)


def _strip_html(html: str) -> str:
    import re
    text = re.sub(r"<[^>]+>", " ", html or "")
    return re.sub(r"\s+", " ", text).strip()
