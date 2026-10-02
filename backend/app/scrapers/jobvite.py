"""Jobvite Engage career-site scraper (Cloudflare-walled), via curl_cffi.

Some Jobvite Engage sites (Ampere, Synaptics, ...) sit behind Cloudflare, which
serves a "Just a moment" challenge to plain httpx AND blocks the data XHR even in
a real headless browser. The one thing that gets through cleanly is a Chrome
TLS/JA3 fingerprint, which `curl_cffi` (impersonate="chrome") provides — no
browser needed.

The listing is server-rendered HTML at ``/search/jobs?q={kw}&page={n}`` with
canonical Jobvite anchors ``/jobs/{id}-{slug}`` + a location span. We parse those
(relevance-gate on title) and optionally enrich descriptions from each job page.

curl_cffi is an OPTIONAL dependency imported lazily, and these companies are
``engine: cf`` (driven by the local runner, never the cloud httpx scheduler), so
the Render web tier is unaffected if curl_cffi isn't installed there.
"""

from __future__ import annotations

import asyncio
import html as _html
import logging
import re

from .base import BaseScraper, JobData
from ..taxonomy import DEFAULT_SEARCH_TERMS as _EE_TERMS

logger = logging.getLogger(__name__)

DEFAULT_TERMS = list(_EE_TERMS)
MAX_PAGES = 10
DETAIL_CAP = 40

# The location lives in the column whose label span says "Location:"; capture
# everything after that span up to the closing </div> (it spans several lines).
_LOC_RE = re.compile(r'Location:\s*</span>([\s\S]*?)</div>', re.I)


def _clean_loc(raw: str) -> str:
    txt = re.sub(r"<[^>]+>", " ", raw or "")
    txt = re.sub(r"\s+", " ", txt).strip()
    return txt.strip(" ,")


def _impersonated_get(url: str):
    """Lazy curl_cffi GET with a Chrome TLS fingerprint (bypasses Cloudflare)."""
    from curl_cffi import requests as creq  # lazy: optional dependency
    return creq.get(url, impersonate="chrome", timeout=25,
                    headers={"Accept": "text/html,application/json"})


def _strip_html(s: str) -> str:
    return re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", s or "")).strip()


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


class JobviteScraper(BaseScraper):
    async def fetch_jobs(self) -> list[JobData]:
        host = (self.config.get("jobvite_host", "") or "").replace("https://", "").strip("/")
        if not host:
            logger.warning("%s: missing jobvite_host config", self.company_name)
            return []
        terms = self.config.get("search_keywords", DEFAULT_TERMS)[:4]
        seen: set[str] = set()
        jobs: list[JobData] = []
        for term in terms:
            try:
                await asyncio.to_thread(self._search_sync, host, term, seen, jobs)
            except Exception as e:
                logger.error("Jobvite search failed %s term=%s: %s", self.company_name, term, e)
        relevant = self._filter_relevant(jobs)
        try:
            await asyncio.to_thread(self._enrich_sync, relevant[:DETAIL_CAP])
        except Exception as e:
            logger.debug("Jobvite enrich failed %s: %s", self.company_name, e)
        return relevant

    def _search_sync(self, host: str, term: str, seen: set, jobs: list) -> None:
        anchor_re = re.compile(
            rf'<a href="(https://{re.escape(host)}/jobs/(\d+)-[^"]*)">([^<]+)</a>', re.I)
        for page in range(1, MAX_PAGES + 1):
            url = f"https://{host}/search/jobs?q={term}&page={page}"
            r = _impersonated_get(url)
            if r.status_code != 200:
                break
            text = r.text
            matches = list(anchor_re.finditer(text))
            if not matches:
                break
            added = 0
            for i, m in enumerate(matches):
                apply_url, jid, title = m.group(1), m.group(2), _html.unescape(m.group(3).strip())
                if not jid or jid in seen:
                    continue
                seen.add(jid)
                added += 1
                end = matches[i + 1].start() if i + 1 < len(matches) else len(text)
                lm = _LOC_RE.search(text[m.end():end])
                location = _html.unescape(_clean_loc(lm.group(1))) if lm else ""
                jobs.append(JobData(
                    job_title=title, apply_url=apply_url, location=location,
                    job_id=jid, source_url=f"https://{host}/search/jobs",
                ))
            if added == 0:
                break

    def _enrich_sync(self, jobs: list) -> None:
        for j in jobs:
            try:
                r = _impersonated_get(j.apply_url)
                if r.status_code != 200:
                    continue
                m = re.search(r'<meta name="description" content="([^"]+)"', r.text, re.I)
                desc = _html.unescape(m.group(1)) if m else ""
                # The full posting body lives in a Jobvite content container.
                bm = re.search(r'(<div[^>]*jv-job-detail-description[^>]*>[\s\S]*?</div>)', r.text, re.I)
                body = _strip_html(bm.group(1)) if bm else ""
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
