"""Eightfold AI careers scraper (the ``pcsx`` public search API).

Qualcomm (and many others) run careers on Eightfold. The site's own search
endpoint returns clean JSON:
  list:   https://{tenant}.eightfold.ai/api/pcsx/search?domain={domain}&query=&start=&num=
  detail: https://{tenant}.eightfold.ai/api/pcsx/position_details?position_id=&domain=

The endpoints 403 for plain server-side clients (anti-bot), so this base class
holds the parsing/pagination and the *browser* subclass
(:class:`~.browser.BrowserEightfoldScraper`) routes the HTTP through a real
Chromium session. Same split as the Workday adapter.
"""

from __future__ import annotations

import asyncio
import logging
import re
from datetime import datetime, timezone
from urllib.parse import quote

from .base import BaseScraper, JobData
from ..taxonomy import DEFAULT_SEARCH_TERMS as _EE_TERMS

logger = logging.getLogger(__name__)

SEARCH_URL = "https://{tenant}.eightfold.ai/api/pcsx/search"
DETAIL_URL = "https://{tenant}.eightfold.ai/api/pcsx/position_details"
PAGE = 20
MAX_RESULTS = 200      # cap per search term
DETAIL_CAP = 90        # max per-job description fetches

DEFAULT_TERMS = list(_EE_TERMS)
_MODE_RE = re.compile(r"\s*\((?:on-?site|remote|hybrid)\)", re.I)


def _strip_html(html: str) -> str:
    return re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", html or "")).strip()


def _clean_title(name: str, location: str) -> str:
    """Eightfold names embed work-mode + location ('Title (Onsite) - Cork,
    Ireland'); trim them so the stored title is just the role."""
    t = _MODE_RE.sub("", name or "").strip()
    if location and " - " in t:
        head, _, tail = t.rpartition(" - ")
        tail_city = tail.split(",")[0].strip().lower()
        # Drop the trailing " - <location>" only when it really is the job's
        # location (its city appears in the locations field), never a real title.
        if tail_city and tail_city in location.lower():
            t = head.strip()
    return t


class EightfoldScraper(BaseScraper):
    async def fetch_jobs(self) -> list[JobData]:
        tenant = self.config.get("eightfold_tenant", "")
        domain = self.config.get("eightfold_domain", "")
        if not tenant or not domain:
            logger.warning("%s: missing eightfold_tenant/eightfold_domain", self.company_name)
            return []

        terms = self.config.get("search_keywords", DEFAULT_TERMS)[:3]
        seen: set[str] = set()
        jobs: list[JobData] = []
        for term in terms:
            await self._search(tenant, domain, term, seen, jobs)
            await asyncio.sleep(1)

        relevant = self._filter_relevant(jobs)
        await self._enrich_details(relevant, tenant, domain)
        return relevant

    async def _search(self, tenant: str, domain: str, term: str,
                      seen: set[str], jobs: list[JobData]) -> None:
        start = 0
        base = SEARCH_URL.format(tenant=tenant)
        while True:
            url = (f"{base}?domain={domain}&query={quote(term)}"
                   f"&start={start}&num={PAGE}&sort_by=relevance")
            try:
                payload = await self._get_json(url)
            except Exception as e:
                logger.error("Eightfold search failed %s term=%s: %s", self.company_name, term, e)
                break
            data = payload.get("data") or {}
            positions = data.get("positions") or []
            if not positions:
                break
            for q in positions:
                pid = str(q.get("id", ""))
                if not pid or pid in seen:
                    continue
                seen.add(pid)
                locs = q.get("locations") or []
                location = "; ".join(locs) if isinstance(locs, list) else str(locs)
                purl = q.get("positionUrl") or f"/careers/job/{pid}"
                posted = None
                ts = q.get("postedTs") or q.get("creationTs")
                if ts:
                    try:
                        posted = datetime.fromtimestamp(int(ts), tz=timezone.utc)
                    except Exception:
                        pass
                jobs.append(JobData(
                    job_title=_clean_title(q.get("name", ""), location),
                    apply_url=f"https://{tenant}.eightfold.ai{purl}?domain={domain}",
                    location=location,
                    job_id=pid,
                    source_url=base,
                    posted_date=posted,
                ))
            total = data.get("count", 0)
            start += PAGE
            if start >= total or start >= MAX_RESULTS:
                break
            await asyncio.sleep(0.5)

    async def _enrich_details(self, jobs: list[JobData], tenant: str, domain: str) -> None:
        base = DETAIL_URL.format(tenant=tenant)
        for j in jobs[:DETAIL_CAP]:
            try:
                dd = await self._get_json(f"{base}?position_id={j.job_id}&domain={domain}")
                data = dd.get("data") or dd
                desc = data.get("jobDescription", "") if isinstance(data, dict) else ""
                if desc:
                    j.full_description_text = desc
                    j.description_snippet = _strip_html(desc)[:600]
                pub = data.get("publicUrl") if isinstance(data, dict) else None
                if pub:
                    j.apply_url = pub
            except Exception as e:
                logger.debug("Eightfold detail failed %s: %s", j.job_id, e)
            await asyncio.sleep(0.3)
