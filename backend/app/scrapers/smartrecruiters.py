"""SmartRecruiters public Posting API scraper.

SmartRecruiters exposes a clean, unauthenticated REST API:
  list:   https://api.smartrecruiters.com/v1/companies/{slug}/postings
  detail: https://api.smartrecruiters.com/v1/companies/{slug}/postings/{id}
The list omits descriptions, so (like the Workday adapter) we title-gate first
and then enrich only the relevant survivors with the per-posting detail call.
"""

from __future__ import annotations

import asyncio
import logging
import re
from datetime import datetime

from .base import BaseScraper, JobData

logger = logging.getLogger(__name__)

LIST_URL = "https://api.smartrecruiters.com/v1/companies/{slug}/postings"
DETAIL_URL = "https://api.smartrecruiters.com/v1/companies/{slug}/postings/{pid}"
PAGE = 100          # max postings per list page
MAX_LIST = 1000     # safety cap on total postings paged
DETAIL_CAP = 60     # max per-posting detail fetches (descriptions)


def _parse_date(s: str):
    if not s:
        return None
    try:
        return datetime.fromisoformat(s.replace("Z", "+00:00"))
    except Exception:
        return None


def _strip_html(html: str) -> str:
    text = re.sub(r"<[^>]+>", " ", html or "")
    return re.sub(r"\s+", " ", text).strip()


class SmartRecruitersScraper(BaseScraper):
    async def fetch_jobs(self) -> list[JobData]:
        slug = self.config.get("smartrecruiters_company", "")
        if not slug:
            logger.warning("%s: missing smartrecruiters_company config", self.company_name)
            return []

        items = await self._fetch_list(slug)
        jobs: list[JobData] = []
        for it in items:
            title = (it.get("name") or "").strip()
            pid = str(it.get("id", ""))
            if not title or not pid:
                continue
            loc = it.get("location") or {}
            location = loc.get("fullLocation") or ", ".join(
                p for p in (loc.get("city"), loc.get("region"),
                            (loc.get("country") or "").upper()) if p
            )
            ident = (it.get("company") or {}).get("identifier", slug)
            jobs.append(JobData(
                job_title=title,
                apply_url=f"https://jobs.smartrecruiters.com/{ident}/{pid}",
                location=location,
                job_id=pid,
                source_url=LIST_URL.format(slug=slug),
                posted_date=_parse_date(it.get("releasedDate", "")),
            ))

        relevant = self._filter_relevant(jobs)
        await self._enrich_details(relevant, slug)
        return relevant

    async def _fetch_list(self, slug: str) -> list[dict]:
        items: list[dict] = []
        offset = 0
        while True:
            try:
                data = await self._get_json(
                    LIST_URL.format(slug=slug),
                    params={"limit": PAGE, "offset": offset},
                )
            except Exception as e:
                logger.error("SmartRecruiters list failed for %s: %s", self.company_name, e)
                if offset == 0:
                    raise
                break
            content = data.get("content", []) or []
            items.extend(content)
            total = data.get("totalFound", 0)
            offset += PAGE
            if not content or offset >= total or offset >= MAX_LIST:
                break
            await asyncio.sleep(0.5)
        return items

    async def _enrich_details(self, jobs: list[JobData], slug: str) -> None:
        for j in jobs[:DETAIL_CAP]:
            try:
                det = await self._get_json(DETAIL_URL.format(slug=slug, pid=j.job_id))
                sections = (det.get("jobAd") or {}).get("sections") or {}
                parts = [
                    (sections.get(k) or {}).get("text", "")
                    for k in ("jobDescription", "qualifications", "additionalInformation")
                ]
                desc = "\n".join(p for p in parts if p)
                if desc:
                    j.full_description_text = desc
                    j.description_snippet = _strip_html(desc)[:600]
                posting_url = det.get("postingUrl")
                if posting_url:
                    j.apply_url = posting_url
            except Exception as e:
                logger.debug("SmartRecruiters detail failed %s: %s", j.job_id, e)
            await asyncio.sleep(0.2)
