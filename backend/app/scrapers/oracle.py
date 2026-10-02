"""Oracle Recruiting Cloud (ORC / Oracle HCM CandidateExperience) scraper.

Large enterprises (Texas Instruments, …) run careers on Oracle Recruiting Cloud,
which exposes a public JSON API at
``{host}/hcmRestApi/resources/latest/recruitingCEJobRequisitions``. Config keys:
``oracle_host`` (e.g. ``edbz.fa.us2.oraclecloud.com``) and ``oracle_site``
(the site code, usually ``CX``). Found per company via a one-time browser
network-capture; scraping itself is a plain JSON GET (cloud-friendly, free).
"""
from __future__ import annotations

import logging
import urllib.parse
from datetime import datetime

from .base import BaseScraper, JobData
from ..taxonomy import DEFAULT_SEARCH_TERMS as _EE_TERMS

logger = logging.getLogger(__name__)

DEFAULT_TERMS = list(_EE_TERMS)


class OracleHcmScraper(BaseScraper):
    async def fetch_jobs(self) -> list[JobData]:
        host = self.config.get("oracle_host", "")
        site = self.config.get("oracle_site", "CX")
        if not host:
            logger.warning("%s: missing oracle_host config", self.company_name)
            return []

        base = f"https://{host}"
        terms = self.config.get("search_keywords", DEFAULT_TERMS)[:4]
        seen: dict[str, JobData] = {}

        for kw in terms:
            finder = f'findReqs;siteNumber={site},keyword="{kw}",limit=200,sortBy=POSTING_DATES_DESC'
            url = (f"{base}/hcmRestApi/resources/latest/recruitingCEJobRequisitions"
                   f"?onlyData=true&expand=requisitionList.secondaryLocations,requisitionList.workLocation"
                   f"&finder={urllib.parse.quote(finder, safe=';,=')}")
            try:
                data = await self._get_json(url)
            except Exception as e:
                logger.warning("%s: Oracle HCM search failed for %r: %s", self.company_name, kw, e)
                continue

            items = data.get("items") or []
            if not items:
                continue
            for j in items[0].get("requisitionList", []):
                jid = str(j.get("Id") or "")
                if not jid or jid in seen:
                    continue
                title = j.get("Title", "")
                posted = None
                pd = j.get("PostedDate")
                if pd:
                    try:
                        posted = datetime.fromisoformat(pd)
                    except Exception:
                        pass
                snippet = (j.get("ShortDescriptionStr") or "").strip() or title
                seen[jid] = JobData(
                    job_title=title,
                    apply_url=f"{base}/hcmUI/CandidateExperience/en/sites/{site}/job/{jid}",
                    location=j.get("PrimaryLocation", ""),
                    job_id=jid,
                    source_url=f"{base}/hcmUI/CandidateExperience/en/sites/{site}",
                    posted_date=posted,
                    description_snippet=snippet,
                    full_description_text="",
                )

        return self._filter_relevant(list(seen.values()))
