"""SAP SuccessFactors career-site scraper (the standard "Career Site Builder"
search template: careers.<company>.com/search/?q=…).

The search results are server-rendered HTML, identical across tenants:

    <tr class="data-row">
      <a href="/job/RICHMOND-…-VA-23219/1333771700/" class="jobTitle-link">Title</a>
      <span class="jobLocation">RICHMOND, VA, US, 23219</span>
      <span class="jobDate">Sep 18, 2026</span>

25 rows per page, paged with `startrow`. Descriptions live on each job page
(`<span class="jobdescription">`), fetched only for postings we have not seen.

Config:
    successfactors_host   e.g. "careers.dominionenergy.com"
    search_keywords       optional; default ["engineer", "designer"]
"""

from __future__ import annotations

import asyncio
import html as html_mod
import logging
import re
from datetime import datetime

from .base import BaseScraper, JobData

logger = logging.getLogger(__name__)

PAGE = 25
MAX_PER_TERM = 1000
DETAIL_CAP = 120
DEFAULT_TERMS = ["engineer", "designer"]

_ROW_RE = re.compile(r'<tr class="data-row"[^>]*>(.*?)</tr>', re.S | re.I)
_LINK_RE = re.compile(r'<a[^>]*href="(?P<href>/job/[^"]*?/(?P<id>\d+)/)"[^>]*class="jobTitle-link"[^>]*>(?P<title>.*?)</a>'
                      r'|<a[^>]*class="jobTitle-link"[^>]*href="(?P<href2>/job/[^"]*?/(?P<id2>\d+)/)"[^>]*>(?P<title2>.*?)</a>',
                      re.S | re.I)
_LOC_RE = re.compile(r'<span class="jobLocation">\s*(.*?)\s*</span>', re.S | re.I)
_DATE_RE = re.compile(r'<span class="jobDate[^"]*">\s*(.*?)\s*</span>', re.S | re.I)
_TOTAL_RE = re.compile(r"of <b>(\d+)</b>", re.I)
_DESC_RE = re.compile(r'<span class="jobdescription"[^>]*>(.*?)</span>\s*</div>', re.S | re.I)
_TAG_RE = re.compile(r"<[^>]+>")


def _text(s: str) -> str:
    return re.sub(r"\s+", " ", html_mod.unescape(_TAG_RE.sub(" ", s or ""))).strip()


def _location(raw: str) -> str:
    """'RICHMOND, VA, US, 23219' -> 'Richmond, VA, United States'."""
    parts = [p.strip() for p in _text(raw).split(",") if p.strip()]
    parts = [p for p in parts if not re.fullmatch(r"\d{5}(-\d{4})?", p)]
    if parts and parts[-1].upper() in ("US", "USA"):
        parts[-1] = "United States"
    if parts:
        parts[0] = parts[0].title() if parts[0].isupper() else parts[0]
    return ", ".join(parts)


def _date(raw: str):
    t = _text(raw)
    for fmt in ("%b %d, %Y", "%m/%d/%Y", "%d %b %Y", "%Y-%m-%d"):
        try:
            return datetime.strptime(t, fmt)
        except ValueError:
            continue
    return None


class SuccessFactorsScraper(BaseScraper):
    async def fetch_jobs(self) -> list[JobData]:
        host = (self.config.get("successfactors_host") or "").replace("https://", "").replace("http://", "").strip("/")
        if not host:
            logger.warning("%s: missing successfactors_host", self.company_name)
            return []
        base = f"https://{host}"
        headers = {"User-Agent": "Mozilla/5.0", "Accept": "text/html"}
        terms = self.config.get("search_keywords") or DEFAULT_TERMS
        seen: dict[str, JobData] = {}

        for term in terms[:4]:
            start, total = 0, None
            while start < MAX_PER_TERM:
                resp = await self.client.get(f"{base}/search/", headers=headers, params={
                    "q": term, "startrow": start, "sortColumn": "referencedate", "sortDirection": "desc"})
                resp.raise_for_status()
                body = resp.text
                if total is None:
                    m = _TOTAL_RE.search(body)
                    total = int(m.group(1)) if m else 0
                rows = _ROW_RE.findall(body)
                if not rows:
                    break
                for row in rows:
                    link = _LINK_RE.search(row)
                    if not link:
                        continue
                    jid = link.group("id") or link.group("id2")
                    if jid in seen:
                        continue
                    href = link.group("href") or link.group("href2")
                    loc = _LOC_RE.search(row)
                    date = _DATE_RE.search(row)
                    seen[jid] = JobData(
                        job_title=_text(link.group("title") or link.group("title2")),
                        apply_url=base + html_mod.unescape(href),
                        location=_location(loc.group(1)) if loc else "",
                        job_id=jid,
                        source_url=f"{base}/search/",
                        posted_date=_date(date.group(1)) if date else None,
                    )
                start += PAGE
                if total is not None and start >= total:
                    break
                await asyncio.sleep(0.5)

        jobs = list(seen.values())
        relevant = self._filter_relevant(jobs, keep_maybe=True)
        await self._enrich(relevant, headers)
        known = self.config.get("_known_ids") or set()
        logger.info("%s: successfactors listed %d, kept %d", self.company_name, len(jobs), len(relevant))
        return [j for j in relevant if j.job_id in known] + \
            self._filter_relevant([j for j in relevant if j.job_id not in known])

    async def _enrich(self, jobs: list[JobData], headers: dict) -> None:
        known = self.config.get("_known_ids") or set()
        fetched = 0
        for j in jobs:
            if fetched >= DETAIL_CAP:
                break
            if j.job_id in known:
                continue
            fetched += 1
            try:
                resp = await self.client.get(j.apply_url, headers=headers)
                m = _DESC_RE.search(resp.text)
                if m:
                    j.full_description_text = m.group(1)
                    j.description_snippet = _text(m.group(1))[:600]
            except Exception as e:
                logger.debug("SuccessFactors detail failed %s: %s", j.apply_url, e)
            await asyncio.sleep(0.3)
