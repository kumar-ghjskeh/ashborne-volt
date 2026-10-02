"""jobs2web / SAP SuccessFactors RMK career-site scraper.

Many large enterprises (Qorvo, Teradyne, …) run their careers on the jobs2web /
SuccessFactors Recruiting-Marketing platform, which exposes a public JSON search
at ``{host}/services/jobs/search``. Config key: ``jobs2web_host`` (e.g.
``careers.qorvo.com``). No per-job detail fetch — the title-first relevance gate
and the listing metadata are enough to surface the role with an apply link.
"""
from __future__ import annotations

import logging
from datetime import datetime

from .base import BaseScraper, JobData
from ..taxonomy import DEFAULT_SEARCH_TERMS as _EE_TERMS

logger = logging.getLogger(__name__)

DEFAULT_TERMS = list(_EE_TERMS)


class Jobs2WebScraper(BaseScraper):
    async def fetch_jobs(self) -> list[JobData]:
        host = self.config.get("jobs2web_host", "")
        if not host:
            logger.warning("%s: missing jobs2web_host config", self.company_name)
            return []

        base = f"https://{host}"
        url = f"{base}/services/jobs/search"
        headers = {
            "Content-Type": "application/json", "Accept": "application/json",
            "Origin": base, "Referer": f"{base}/jobs/",
        }
        terms = self.config.get("search_keywords", DEFAULT_TERMS)[:4]
        seen: dict[str, JobData] = {}

        for kw in terms:
            body = {
                "page": 0, "keywords": kw, "locationsearch": "",
                "sortby": "referencedate", "sortdir": "desc",
                "recordsperpage": 100, "startrow": 0, "filterquery": {},
            }
            try:
                data = await self._post_json(url, body, headers=headers)
            except Exception as e:
                logger.warning("%s: jobs2web search failed for %r: %s", self.company_name, kw, e)
                continue

            for j in data.get("jobList", []):
                jid = str(j.get("id") or "")
                if not jid or jid in seen:
                    continue
                title = j.get("title", "")
                urltitle = j.get("urltitle") or j.get("internalurltitle") or ""
                posted = None
                raw_date = (j.get("referencedate") or "").replace("[UTC]", "").replace("Z", "+00:00")
                if raw_date:
                    try:
                        posted = datetime.fromisoformat(raw_date)
                    except Exception:
                        pass
                apply_url = f"{base}/job/{urltitle}/{jid}/" if urltitle else f"{base}/jobs/{jid}"
                seen[jid] = JobData(
                    job_title=title,
                    apply_url=apply_url,
                    location=j.get("location", "") or j.get("city", ""),
                    job_id=jid,
                    source_url=f"{base}/jobs/",
                    posted_date=posted,
                    description_snippet=title,
                    full_description_text="",
                )

        return self._filter_relevant(list(seen.values()))
