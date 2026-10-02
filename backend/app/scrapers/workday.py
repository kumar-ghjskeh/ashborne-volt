"""Workday career site scraper using the WD/CXS JSON API."""

from __future__ import annotations

import asyncio
import logging
import re
from datetime import datetime, timedelta, timezone

from .base import BaseScraper, JobData
from ..taxonomy import DEFAULT_SEARCH_TERMS as _EE_TERMS

logger = logging.getLogger(__name__)

# Workday undocumented public REST endpoint pattern
CXS_URL = "https://{tenant}.{instance}.myworkdayjobs.com/wday/cxs/{tenant}/{career_site}/jobs"

# Default search terms for electrical-engineering roles (see app/taxonomy.py)
DEFAULT_SEARCH_TERMS = list(_EE_TERMS)

LIMIT = 20            # Workday's page size ceiling
DETAIL_CAP = 150      # per-company detail fetches per run (new postings only)
# A board this small is cheaper to read whole than to search: ~30 requests, and
# nothing is lost to Workday's loose keyword matching (a search for "electrical
# engineer" on one utility returned dispatchers and contract managers).
FULL_SCAN_MAX = 600
# After the US + engineering facets, scan whole if at most this many remain.
FACETED_SCAN_MAX = 1500
TERM_CAP = 400        # per-term ceiling when we fall back to keyword search

# Workday's country id for the USA is the same on every tenant.
US_COUNTRY_ID = "bc33aa3152ec42d4995f4791a106ed09"
_US_NAMES = {"united states", "united states of america", "usa", "us"}


def find_facets(facets: list | None) -> dict[str, list[str]]:
    """Pick the US-country and engineering job-family facet values, if offered.

    Workday nests location facets (locationMainGroup -> locationCountry), and the
    parameter names vary by tenant, so match on descriptors rather than names.
    """
    applied: dict[str, list[str]] = {}

    def walk(fs):
        for f in fs or []:
            param = f.get("facetParameter") or ""
            pl = param.lower()
            for v in f.get("values") or []:
                if v.get("facetParameter"):
                    walk([v])
                    continue
                desc = (v.get("descriptor") or "").strip().lower()
                vid = v.get("id")
                if not vid:
                    continue
                if ("country" in pl or "location" in pl) and (desc in _US_NAMES or vid == US_COUNTRY_ID):
                    applied.setdefault(param, []).append(vid)
                elif any(k in pl for k in ("family", "category", "function", "discipline")) \
                        and "engineer" in desc:
                    applied.setdefault(param, []).append(vid)

    walk(facets)
    return applied


def _parse_relative_posted(s: str) -> datetime | None:
    """Workday lists ship a relative string ('Posted Yesterday', 'Posted 30+ Days
    Ago') rather than a date. Convert it to an approximate UTC datetime."""
    if not s:
        return None
    t = s.lower()
    now = datetime.now(timezone.utc)
    if "today" in t or "just posted" in t:
        return now
    if "yesterday" in t:
        return now - timedelta(days=1)
    m = re.search(r"(\d+)\+?\s*day", t)
    if m:
        return now - timedelta(days=int(m.group(1)))
    m = re.search(r"(\d+)\+?\s*week", t)
    if m:
        return now - timedelta(weeks=int(m.group(1)))
    m = re.search(r"(\d+)\+?\s*month", t)
    if m:
        return now - timedelta(days=30 * int(m.group(1)))
    return None


class WorkdayScraper(BaseScraper):
    """Adaptive Workday CXS scraper.

    1. One unfiltered request gives the board size and its facets.
    2. Small board (<= FULL_SCAN_MAX): read everything, classify locally.
    3. Big board: apply Workday's own US-country and engineering job-family
       facets server-side; read everything left if it is <= FACETED_SCAN_MAX.
    4. Still too big: keyword searches (with the facets) capped per term.

    Then the title gate runs, discipline-free titles are kept as "maybes", and
    only NEW postings get a detail fetch (description + exact posted date). The
    maybes are re-judged with their description.
    """

    async def fetch_jobs(self) -> list[JobData]:
        tenant = self.config.get("workday_tenant", "")
        instance = self.config.get("workday_instance", "wd1")
        career_site = self.config.get("workday_career_site", "External")
        if not tenant:
            logger.warning("%s: missing workday_tenant config", self.company_name)
            return []

        base_url = CXS_URL.format(tenant=tenant, instance=instance, career_site=career_site)
        # Workday answers 422 without a same-origin Origin/Referer.
        site_root = f"https://{tenant}.{instance}.myworkdayjobs.com"
        self.client.headers.update({
            "Origin": site_root,
            "Referer": f"{site_root}/{career_site}",
            "Sec-Fetch-Site": "same-origin",
        })

        seen: set[str] = set()
        first = await self._post_json(base_url, {"appliedFacets": {}, "limit": LIMIT,
                                                  "offset": 0, "searchText": ""})
        total = int(first.get("total") or 0)
        facets = {} if self.config.get("workday_no_facets") else find_facets(first.get("facets"))
        mode = "full"
        if total <= FULL_SCAN_MAX:
            jobs = self._rows(first.get("jobPostings", []), base_url, seen)
            jobs += await self._scan(base_url, "", {}, seen, start=LIMIT, cap=FULL_SCAN_MAX)
        else:
            faceted_total = total
            if facets:
                probe = await self._post_json(base_url, {"appliedFacets": facets, "limit": LIMIT,
                                                          "offset": 0, "searchText": ""})
                faceted_total = int(probe.get("total") or 0)
            if facets and faceted_total <= FACETED_SCAN_MAX:
                mode = "faceted"
                jobs = await self._scan(base_url, "", facets, seen, start=0, cap=FACETED_SCAN_MAX)
            else:
                mode = "search"
                terms = self.config.get("search_keywords") or DEFAULT_SEARCH_TERMS
                jobs = []
                for term in terms[: int(self.config.get("max_terms", 6))]:
                    jobs += await self._scan(base_url, term, facets, seen, start=0, cap=TERM_CAP)
                    await asyncio.sleep(1)

        relevant = self._filter_relevant(jobs, keep_maybe=True)
        logger.info("%s: workday %s mode, board=%d, listed=%d, kept=%d",
                    self.company_name, mode, total, len(jobs), len(relevant))
        await self._enrich_details(relevant, tenant, instance, career_site)
        # Re-judge with descriptions: maybes without EE content drop out here.
        known = self.config.get("_known_ids") or set()
        return [j for j in relevant if j.job_id in known] + \
            self._filter_relevant([j for j in relevant if j.job_id not in known])

    async def _scan(self, base_url: str, term: str, facets: dict, seen: set[str],
                    start: int, cap: int) -> list[JobData]:
        out: list[JobData] = []
        offset = start
        # Workday reports `total` on the first page only; later pages say 0.
        # Reading it per page stopped every scan after two pages.
        total = 0
        while offset < cap:
            try:
                data = await self._post_json(base_url, {"appliedFacets": facets, "limit": LIMIT,
                                                         "offset": offset, "searchText": term})
            except Exception as e:
                logger.error("Workday page failed for %s term=%r offset=%d: %s",
                             self.company_name, term, offset, e)
                if offset == start and not out:
                    raise
                break
            items = data.get("jobPostings", [])
            if not items:
                break
            out += self._rows(items, base_url, seen)
            offset += LIMIT
            total = max(total, int(data.get("total") or 0))
            if total and offset >= total:
                break
            await asyncio.sleep(0.5)
        return out

    def _rows(self, items: list, base_url: str, seen: set[str]) -> list[JobData]:
        tenant = self.config.get("workday_tenant", "")
        instance = self.config.get("workday_instance", "wd1")
        career_site = self.config.get("workday_career_site", "External")
        rows: list[JobData] = []
        for item in items:
            ext_path = item.get("externalPath", "")
            job_id = ext_path.split("/")[-1] if ext_path else ""
            if not job_id or job_id in seen:
                continue
            seen.add(job_id)
            apply_url = (f"https://{tenant}.{instance}.myworkdayjobs.com/{career_site}{ext_path}"
                         if ext_path else "")
            rows.append(JobData(
                job_title=item.get("title", ""),
                apply_url=apply_url,
                location=item.get("locationsText", "") or item.get("primaryLocation", ""),
                job_id=job_id,
                source_url=base_url,
                posted_date=_parse_relative_posted(item.get("postedOn", "")),
            ))
        return rows

    async def _enrich_details(self, jobs: list[JobData], tenant: str, instance: str,
                              career_site: str) -> None:
        """Description + exact start date for postings we have not seen before.

        Known postings already carry both; re-fetching them every run would be
        most of the request volume at scale.
        """
        from ..location_utils import parse_location
        from ..taxonomy import classify

        known = self.config.get("_known_ids") or set()
        site_root = f"https://{tenant}.{instance}.myworkdayjobs.com"
        prefix = f"{site_root}/{career_site}"

        def priority(j: JobData) -> int:
            loc = parse_location(j.location or "", "")
            if loc.confidence > 0 and not loc.is_usa:
                return 9                       # known foreign: never worth a fetch
            return 0 if classify(j.job_title).relevant else 1

        fetched = 0
        for j in sorted(jobs, key=priority):
            if fetched >= DETAIL_CAP:
                break
            if j.job_id in known or priority(j) == 9:
                continue
            ext_path = j.apply_url[len(prefix):] if j.apply_url.startswith(prefix) else ""
            if not ext_path:
                continue
            fetched += 1
            try:
                data = await self._get_json(f"{site_root}/wday/cxs/{tenant}/{career_site}{ext_path}")
                info = data.get("jobPostingInfo", {}) if isinstance(data, dict) else {}
                desc = info.get("jobDescription", "") or ""
                if desc:
                    j.full_description_text = desc
                    j.description_snippet = desc[:600]
                # Lists often say just "Niskayuna" or "3 Locations"; the detail
                # names the primary site and its country, which is what makes
                # the posting placeable as US or not.
                country = (info.get("country") or {}).get("descriptor") or \
                    ((info.get("jobRequisitionLocation") or {}).get("country") or {}).get("descriptor") or ""
                primary = info.get("location") or ""
                if primary and (not j.location or "location" in j.location.lower()):
                    j.location = primary
                if country and country.lower() not in (j.location or "").lower():
                    j.location = f"{j.location}, {country}" if j.location else country
                start = info.get("startDate", "")
                if start:
                    try:
                        j.posted_date = datetime.fromisoformat(start)
                    except Exception:
                        pass
            except Exception as e:
                logger.debug("Workday detail fetch failed %s: %s", j.apply_url, e)
            await asyncio.sleep(0.25)
