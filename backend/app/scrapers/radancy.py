"""Radancy (TalentBrew) career-site scraper (Synopsys, ...), via curl_cffi.

Radancy sites (careers.{company}.com) sit behind Cloudflare and render
keyword-filtered results at ``/search-jobs/{keyword}?p={n}``. Each result is an
``<a class="sr-job-link" href="/job/{city}/{slug}/{org}/{id}"><h2>{title}</h2></a>``
with a "City, State" location element in the card. curl_cffi (Chrome TLS) gets
past Cloudflare; this runs engine:cf. curl_cffi is imported lazily.
"""

from __future__ import annotations

import asyncio
import html as _html
import logging
import re
from datetime import datetime

from .base import BaseScraper, JobData
from ..taxonomy import DEFAULT_SEARCH_TERMS as _EE_TERMS

logger = logging.getLogger(__name__)

DEFAULT_TERMS = list(_EE_TERMS)
MAX_PAGES = 12
DETAIL_CAP = 40

_CARD_RE = re.compile(
    r'<a class="sr-job-link" href="(/job/[^"]+)"[^>]*data-job-id="(\d+)"[^>]*>\s*<h2>([\s\S]*?)</h2>', re.I)
# The location text follows an inner <img> pin icon inside the span.
_LOC_RE = re.compile(r'<span class="job-location">([\s\S]*?)</span>', re.I)
_DATE_RE = re.compile(r'job-date-posted"[^>]*>\s*<strong>[^<]*</strong>\s*([\d]{1,2}/[\d]{1,2}/[\d]{4})', re.I)


def _text(s: str) -> str:
    return _html.unescape(re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", s or "")).strip())


def _date(seg: str):
    m = _DATE_RE.search(seg)
    if not m:
        return None
    try:
        return datetime.strptime(m.group(1), "%m/%d/%Y")
    except Exception:
        return None


class RadancyScraper(BaseScraper):
    async def fetch_jobs(self) -> list[JobData]:
        host = (self.config.get("radancy_host", "") or "").replace("https://", "").strip("/")
        if not host:
            logger.warning("%s: missing radancy_host config", self.company_name)
            return []
        terms = self.config.get("search_keywords", DEFAULT_TERMS)[:4]
        seen: set[str] = set()
        jobs: list[JobData] = []
        for term in terms:
            try:
                await asyncio.to_thread(self._search, host, term, seen, jobs)
            except Exception as e:
                logger.error("Radancy search failed %s term=%s: %s", self.company_name, term, e)
        relevant = self._filter_relevant(jobs)
        try:
            await asyncio.to_thread(self._enrich, relevant[:DETAIL_CAP], host)
        except Exception as e:
            logger.debug("Radancy enrich failed %s: %s", self.company_name, e)
        return relevant

    def _get(self, url: str):
        from curl_cffi import requests as creq  # lazy: optional dependency
        return creq.get(url, impersonate="chrome", timeout=30, headers={"Accept": "text/html"})

    def _search(self, host: str, term: str, seen: set, jobs: list) -> None:
        slug = re.sub(r"\s+", "-", term.strip().lower())
        for page in range(1, MAX_PAGES + 1):
            url = f"https://{host}/search-jobs/{slug}?p={page}"
            r = self._get(url)
            if r.status_code != 200:
                break
            text = r.text
            matches = list(_CARD_RE.finditer(text))
            if not matches:
                break
            added = 0
            for i, m in enumerate(matches):
                href, jid, title = m.group(1), m.group(2), _text(m.group(3))
                if not jid or jid in seen or not title:
                    continue
                seen.add(jid)
                added += 1
                end = matches[i + 1].start() if i + 1 < len(matches) else len(text)
                seg = text[m.end():end]
                lm = _LOC_RE.search(seg)
                location = _text(lm.group(1)) if lm else ""
                jobs.append(JobData(
                    job_title=title, apply_url=f"https://{host}{href}", location=location,
                    job_id=jid, source_url=f"https://{host}/search-jobs",
                    posted_date=_date(seg),
                ))
            if added == 0:
                break

    def _enrich(self, jobs: list, host: str) -> None:
        for j in jobs:
            try:
                r = self._get(j.apply_url)
                if r.status_code != 200:
                    continue
                m = re.search(r'<meta name="description" content="([^"]+)"', r.text, re.I)
                desc = _html.unescape(m.group(1)) if m else ""
                bm = re.search(r'(<div[^>]*(?:job-description|ats-description|jd-info)[^>]*>[\s\S]*?</div>)',
                               r.text, re.I)
                body = _text(bm.group(1)) if bm else ""
                full = body or desc
                if full:
                    j.full_description_text = full
                    j.description_snippet = full[:600]
            except Exception:
                continue
