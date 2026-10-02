"""Avature career-site scraper (TSMC, Synopsys, ...), via curl_cffi.

Avature sites (careers.{company}.com) sit behind Cloudflare and render a
server-side job list at ``/careers/SearchJobs/?jobRecordsPerPage=10&jobOffset=N``
— 10 jobs per page, canonical ``/careers/JobDetail?jobId={id}`` anchors, a
``subtitle`` element with the location, and an "N Jobs" total. The keyword filter
is ignored, so we page through everything and apply the title relevance gate +
location gate ourselves (e.g. TSMC is mostly Taiwan — only the US fab roles pass).

curl_cffi (Chrome TLS impersonation) is what gets past Cloudflare, so this runs as
engine:cf (local runner / GitHub Actions), never the cloud httpx scheduler.
curl_cffi is imported lazily.
"""

from __future__ import annotations

import asyncio
import html as _html
import logging
import re

from .base import BaseScraper, JobData

logger = logging.getLogger(__name__)

PAGE = 10              # Avature fixes the page size at 10
MAX_PAGES = 80         # safety cap (~800 jobs)
DETAIL_CAP = 40

_ANCHOR_RE = re.compile(r'<a[^>]*href="(https?://[^"]*?/careers/JobDetail\?jobId=(\d+)[^"]*)"[^>]*>([\s\S]*?)</a>', re.I)
_SUBTITLE_RE = re.compile(r'subtitle[^>]*>([\s\S]{0,200}?)</', re.I)
_TOTAL_RE = re.compile(r'(\d[\d,]*)\s*(?:Jobs|Results|Openings|Positions)', re.I)


def _text(html_fragment: str) -> str:
    return _html.unescape(re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", html_fragment or "")).strip())


def _parse_iso(s: str):
    """Parse a JSON-LD datePosted ("2026-02-17T20:54:33Z" or "2026-02-17")."""
    import datetime as _dt
    s = (s or "").strip()
    if not s:
        return None
    try:
        return _dt.datetime.fromisoformat(s.replace("Z", "+00:00"))
    except Exception:
        try:
            return _dt.datetime.strptime(s[:10], "%Y-%m-%d")
        except Exception:
            return None


class AvatureScraper(BaseScraper):
    async def fetch_jobs(self) -> list[JobData]:
        host = (self.config.get("avature_host", "") or "").replace("https://", "").strip("/")
        if not host:
            logger.warning("%s: missing avature_host config", self.company_name)
            return []
        seen: set[str] = set()
        jobs: list[JobData] = []
        try:
            await asyncio.to_thread(self._page_through, host, seen, jobs)
        except Exception as e:
            logger.error("Avature search failed %s: %s", self.company_name, e)
        relevant = self._filter_relevant(jobs)
        try:
            await asyncio.to_thread(self._enrich, relevant[:DETAIL_CAP])
        except Exception as e:
            logger.debug("Avature enrich failed %s: %s", self.company_name, e)
        return relevant

    def _get(self, url: str):
        from curl_cffi import requests as creq  # lazy: optional dependency
        return creq.get(url, impersonate="chrome", timeout=30,
                        headers={"Accept": "text/html"})

    def _page_through(self, host: str, seen: set, jobs: list) -> None:
        base = f"https://{host}/careers/SearchJobs/?jobRecordsPerPage={PAGE}&jobOffset="
        total = None
        for page in range(MAX_PAGES):
            r = self._get(base + str(page * PAGE))
            if r.status_code != 200:
                break
            text = r.text
            if total is None:
                m = _TOTAL_RE.search(text)
                total = int(m.group(1).replace(",", "")) if m else None
            matches = list(_ANCHOR_RE.finditer(text))
            if not matches:
                break
            added = 0
            for i, m in enumerate(matches):
                apply_url, jid, title = m.group(1), m.group(2), _text(m.group(3))
                if not jid or jid in seen or not title:
                    continue
                seen.add(jid)
                added += 1
                end = matches[i + 1].start() if i + 1 < len(matches) else len(text)
                sm = _SUBTITLE_RE.search(text[m.end():end])
                location = _text(sm.group(1)) if sm else ""
                jobs.append(JobData(
                    job_title=title, apply_url=apply_url, location=location,
                    job_id=jid, source_url=f"https://{host}/careers/SearchJobs",
                ))
            if added == 0:
                break
            if total is not None and (page + 1) * PAGE >= total:
                break

    def _enrich(self, jobs: list) -> None:
        for j in jobs:
            try:
                r = self._get(j.apply_url)
                if r.status_code != 200:
                    continue
                m = re.search(r'<meta name="description" content="([^"]+)"', r.text, re.I)
                desc = _html.unescape(m.group(1)) if m else ""
                bm = re.search(r'(<div[^>]*(?:jobdescription|job-description|article__content)[^>]*>[\s\S]*?</div>)',
                               r.text, re.I)
                body = _text(bm.group(1)) if bm else ""
                full = body or desc
                if full:
                    j.full_description_text = full
                    j.description_snippet = full[:600]
                dm = re.search(r'"datePosted"\s*:\s*"([^"]+)"', r.text)
                if dm:
                    pd = _parse_iso(dm.group(1))
                    if pd:
                        j.posted_date = pd
            except Exception:
                continue
