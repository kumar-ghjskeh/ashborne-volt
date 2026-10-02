"""Greenhouse public JSON API scraper."""

from __future__ import annotations

import logging
from datetime import datetime

from .base import BaseScraper, JobData

logger = logging.getLogger(__name__)

API_BASE = "https://boards-api.greenhouse.io/v1/boards/{board}/jobs"


class GreenhouseScraper(BaseScraper):
    async def fetch_jobs(self) -> list[JobData]:
        board = self.config.get("greenhouse_board", "")
        if not board:
            logger.warning("%s: missing greenhouse_board config", self.company_name)
            return []

        url = API_BASE.format(board=board)
        try:
            data = await self._get_json(url, params={"content": "true"})
        except Exception as e:
            logger.error("Greenhouse fetch failed for %s: %s", self.company_name, e)
            raise

        jobs: list[JobData] = []
        for item in data.get("jobs", []):
            title = item.get("title", "")
            job_id = str(item.get("id", ""))
            apply_url = item.get("absolute_url", "")
            location_obj = item.get("location", {})
            location = location_obj.get("name", "") if isinstance(location_obj, dict) else ""

            # Updated-at from Greenhouse
            updated_at = item.get("updated_at") or item.get("published_at")
            posted = None
            if updated_at:
                try:
                    posted = datetime.fromisoformat(updated_at.replace("Z", "+00:00"))
                except Exception:
                    pass

            # Content / description
            content = item.get("content", "") or ""
            snippet = _strip_html(content)[:500]

            jobs.append(
                JobData(
                    job_title=title,
                    apply_url=apply_url,
                    location=location,
                    job_id=job_id,
                    source_url=f"https://boards.greenhouse.io/{board}",
                    posted_date=posted,
                    description_snippet=snippet,
                    full_description_text=_strip_html(content),
                )
            )

        return self._filter_relevant(jobs)


def _strip_html(html: str) -> str:
    """Very simple HTML → text for snippet extraction."""
    import re
    text = re.sub(r"<[^>]+>", " ", html)
    text = re.sub(r"\s+", " ", text)
    return text.strip()
