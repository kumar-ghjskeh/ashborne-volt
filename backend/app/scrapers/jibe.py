"""iCIMS Jibe career-site scraper (``careers.<company>.com/api/jobs``).

Many large employers front their iCIMS tenant with a Jibe site: the iCIMS
search page then answers with a bare JavaScript redirect to it, which is why the
plain iCIMS adapter sees an empty page. The Jibe site serves a public JSON API
that already includes the full description, location and posted date, so one
paginated listing is the whole scrape — no per-job detail requests.

Config:
    jibe_host   e.g. "careers.pplweb.com" or "jobs.constellationenergy.com"
    jibe_path   optional API path prefix when the site is mounted under one
                (default "" → https://HOST/api/jobs)
"""

from __future__ import annotations

import asyncio
import logging
from datetime import datetime

from .base import BaseScraper, JobData

logger = logging.getLogger(__name__)

PAGE_SIZE = 100
MAX_PAGES = 40          # 4,000 postings — far beyond any single employer here


def _location(d: dict) -> str:
    parts = [d.get("city"), d.get("state"), d.get("country")]
    loc = ", ".join(p for p in parts if p)
    return loc or d.get("full_location") or d.get("location_name") or ""


def _posted(s: str | None):
    if not s:
        return None
    for fmt in ("%Y-%m-%dT%H:%M:%S%z", "%Y-%m-%dT%H:%M:%S.%f%z", "%Y-%m-%d"):
        try:
            return datetime.strptime(s, fmt)
        except ValueError:
            continue
    return None


class JibeScraper(BaseScraper):
    async def fetch_jobs(self) -> list[JobData]:
        host = (self.config.get("jibe_host") or "").replace("https://", "").replace("http://", "").strip("/")
        if not host:
            logger.warning("%s: missing jibe_host", self.company_name)
            return []
        prefix = (self.config.get("jibe_path") or "").strip("/")
        api = f"https://{host}/{prefix + '/' if prefix else ''}api/jobs"
        # Same WAF quirk as plain iCIMS: a bare UA is served, a full one can be blocked.
        headers = {"User-Agent": "Mozilla/5.0", "Accept": "application/json"}

        jobs: list[JobData] = []
        seen: set[str] = set()
        total = None
        for page in range(1, MAX_PAGES + 1):
            data = await self._get_json(api, params={"page": page, "limit": PAGE_SIZE,
                                                      "sortBy": "posted_date", "descending": "true"},
                                        headers=headers)
            items = data.get("jobs") or []
            total = data.get("totalCount", total)
            for item in items:
                d = item.get("data", item)
                rid = str(d.get("req_id") or d.get("slug") or "")
                if not rid or rid in seen:
                    continue
                seen.add(rid)
                # The posting page on the Jibe site (readable without a login);
                # `apply_url` points at an iCIMS login wall, so it is the fallback.
                job_url = f"https://{host}/jobs/{d.get('slug') or rid}" if (d.get("slug") or rid) else ""
                desc = d.get("description") or ""
                jobs.append(JobData(
                    job_title=d.get("title", ""),
                    apply_url=job_url or d.get("apply_url") or "",
                    location=_location(d),
                    job_id=rid,
                    source_url=api,
                    posted_date=_posted(d.get("posted_date")),
                    description_snippet=desc[:600],
                    full_description_text=desc,
                ))
            if not items or (total is not None and len(seen) >= int(total)):
                break
            await asyncio.sleep(0.5)
        logger.info("%s: jibe listed %d of %s", self.company_name, len(jobs), total)
        return self._filter_relevant(jobs)
