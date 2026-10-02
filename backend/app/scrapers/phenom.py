"""Phenom People career-site scraper (the ``/api/jobs`` public search API).

A large share of big semiconductor employers (AMD, and many others) front their
careers site with Phenom CMS. Phenom exposes a clean JSON search endpoint that
returns the FULL job description, precise posted date, structured location and an
apply URL right in the list payload — so no per-job detail fetch is needed:

    https://{host}/api/jobs?keywords={kw}&page={n}&limit={N}

Unlike Workday/Eightfold this responds 200 to a plain server-side client, so it
runs on the 24/7 cloud (httpx) with no browser engine. The careers host (e.g.
``careers.amd.com``) is set in config as ``phenom_host``.
"""

from __future__ import annotations

import asyncio
import logging
import re
from datetime import datetime

from .base import BaseScraper, JobData
from ..taxonomy import DEFAULT_SEARCH_TERMS as _EE_TERMS

logger = logging.getLogger(__name__)

PAGE = 50            # max page size the API honours (?limit=)
MAX_RESULTS = 250    # cap per search term (after that, gates cull the rest)
DEFAULT_TERMS = list(_EE_TERMS)


def _strip_html(html: str) -> str:
    return re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", html or "")).strip()


def _parse_posted(value: str):
    """Phenom posted_date is ISO 8601 with a +0000 offset, e.g.
    '2026-06-11T22:13:00+0000'."""
    if not value:
        return None
    v = value.strip()
    for fmt in ("%Y-%m-%dT%H:%M:%S%z", "%Y-%m-%dT%H:%M:%S.%f%z"):
        try:
            return datetime.strptime(v, fmt)
        except Exception:
            pass
    try:  # tolerate a trailing 'Z'
        return datetime.fromisoformat(v.replace("Z", "+00:00"))
    except Exception:
        return None


def _location(data: dict) -> str:
    """Build a parse_location-friendly string. Always append the country so the
    location gate can tell San Jose, US from Bangalore, India."""
    full = (data.get("full_location") or "").strip()
    city = (data.get("city") or "").strip()
    state = (data.get("state") or "").strip()
    country = (data.get("country") or "").strip()
    base = full or ", ".join(p for p in (city, state) if p)
    multi = data.get("multipleLocations") or []
    if not base and isinstance(multi, list) and multi:
        base = "; ".join(str(m) for m in multi[:3])
    if country and country.lower() not in base.lower():
        base = f"{base}, {country}" if base else country
    return base


class PhenomScraper(BaseScraper):
    async def fetch_jobs(self) -> list[JobData]:
        host = self.config.get("phenom_host", "")
        if not host:
            logger.warning("%s: missing phenom_host config", self.company_name)
            return []
        host = host.replace("https://", "").replace("http://", "").strip("/")
        base = f"https://{host}/api/jobs"

        terms = self.config.get("search_keywords", DEFAULT_TERMS)[:4]
        seen: set[str] = set()
        jobs: list[JobData] = []
        for term in terms:
            await self._search(base, host, term, seen, jobs)
            await asyncio.sleep(0.5)
        return self._filter_relevant(jobs)

    async def _search(self, base: str, host: str, term: str,
                      seen: set[str], jobs: list[JobData]) -> None:
        page = 1
        while True:
            try:
                payload = await self._get_json(
                    base, params={"keywords": term, "page": page, "limit": PAGE},
                )
            except Exception as e:
                logger.error("Phenom search failed %s term=%s: %s", self.company_name, term, e)
                break
            items = payload.get("jobs") or []
            if not items:
                break
            for it in items:
                data = it.get("data") or {}
                jid = str(data.get("req_id") or data.get("slug") or "")
                if not jid or jid in seen:
                    continue
                seen.add(jid)
                desc_html = data.get("description") or ""
                apply_url = (data.get("apply_url")
                             or f"https://{host}/careers-home/jobs/{jid}")
                jobs.append(JobData(
                    job_title=data.get("title", ""),
                    apply_url=apply_url,
                    location=_location(data),
                    job_id=jid,
                    source_url=base,
                    posted_date=_parse_posted(data.get("posted_date") or data.get("create_date") or ""),
                    description_snippet=_strip_html(desc_html)[:600],
                    full_description_text=desc_html,
                ))
            total = payload.get("totalCount") or payload.get("count") or 0
            if page * PAGE >= total or page * PAGE >= MAX_RESULTS:
                break
            page += 1
            await asyncio.sleep(0.4)
