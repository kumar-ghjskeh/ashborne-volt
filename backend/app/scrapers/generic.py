"""Generic scraper: tries httpx first, falls back to Playwright for JS-heavy pages."""

from __future__ import annotations

import asyncio
import logging
import re

from bs4 import BeautifulSoup

from ..config import settings
from .base import BaseScraper, JobData

logger = logging.getLogger(__name__)

# Below this many postings from the plain-HTTP pass, escalate to Playwright.
# These careers pages mostly render their listing in JS, so a handful of
# server-rendered cards is a sign the real list was missed, not found.
PLAYWRIGHT_ESCALATION_THRESHOLD = 8


class GenericScraper(BaseScraper):
    """
    Fetches the careers_url and attempts to extract job listings from HTML.
    Useful as a fallback for companies without an ATS API.
    Parses common patterns (ul/li links, table rows, div cards).
    """

    async def fetch_jobs(self) -> list[JobData]:
        url = self.config.get("careers_url", "")
        if not url:
            return []

        keywords = self.config.get("search_keywords", [])

        # Try each keyword as a search parameter
        jobs: list[JobData] = []
        seen: set[str] = set()

        # Keyword breadth is per-company and defaults to the original two.
        #
        # Raising it to five was measured against Arm, Cisco and Quadric and changed
        # nothing — these sites do not take a `?q=` parameter, so the extra requests
        # fetched the same page repeatedly. Left configurable for a source where the
        # query string IS honoured, but not raised by default: 2.5x the requests
        # against the most failure-prone sources, for no observed gain, is a worse
        # trade than it looks.
        max_kw = int(self.config.get("generic_max_keywords", 2))
        for kw in (keywords[:max_kw] or [""]):
            try:
                fetched = await self._fetch_with_keyword(url, kw, seen)
                jobs.extend(fetched)
                await asyncio.sleep(1.5)
            except Exception as e:
                logger.warning("Generic scrape failed for %s kw=%s: %s", self.company_name, kw, e)

        # Escalate to Playwright when httpx produced LITTLE, not only when it
        # produced nothing. Most of these careers pages render their list in JS and
        # serve a near-empty shell to httpx, so a couple of stray server-rendered
        # cards used to suppress the pass that would have found the rest.
        # NOTE: this fallback is currently unreachable in CI, and that explains the
        # whole `generic` cohort returning nothing.
        #
        # playwright is declared only in requirements-browser.txt, which only
        # scrape-giants.yml installs — so in the main scrape the import below raises
        # ImportError. And giants cannot pick these companies up either, because
        # browser_scraper_for() routes by ats_platform and has no `generic` branch:
        # it falls through to BrowserWorkdayScraper, which is the wrong adapter.
        #
        # Net effect: a `generic` company gets the plain-HTTP pass only. Careers
        # pages that render their list in JS (Ambarella, Rivos, SiMa.ai, Enfabrica,
        # Esperanto) therefore return 0, while locally — with playwright present —
        # the same config finds real postings. Closing this needs a `generic` branch
        # in browser_scraper_for plus engine: browser on those entries.
        if len(jobs) < PLAYWRIGHT_ESCALATION_THRESHOLD:
            try:
                richer = await self._playwright_fetch(url, keywords, seen)
                if len(richer) > len(jobs):
                    jobs = richer
            except Exception as e:
                logger.error("Playwright scrape failed for %s: %s", self.company_name, e)
                # Only fatal when httpx found nothing either — otherwise keep what
                # we have rather than failing a company that partly worked.
                if not jobs:
                    raise

        return self._filter_relevant(jobs)

    async def _fetch_with_keyword(self, url: str, keyword: str, seen: set[str]) -> list[JobData]:
        params = {}
        if keyword:
            params["q"] = keyword

        resp = await self.client.get(url, params=params)
        resp.raise_for_status()
        return _parse_html_jobs(resp.text, url, seen)

    async def _playwright_fetch(self, url: str, keywords: list[str], seen: set[str]) -> list[JobData]:
        from playwright.async_api import async_playwright

        jobs: list[JobData] = []
        async with async_playwright() as pw:
            browser = await pw.chromium.launch(headless=settings.playwright_headless)
            page = await browser.new_page()
            await page.goto(url, wait_until="networkidle", timeout=30000)
            html = await page.content()
            await browser.close()

        jobs.extend(_parse_html_jobs(html, url, seen))
        return jobs


def _parse_html_jobs(html: str, source_url: str, seen: set[str]) -> list[JobData]:
    """Heuristic HTML parser — looks for job-card-like structures."""
    soup = BeautifulSoup(html, "html.parser")
    jobs: list[JobData] = []

    # Strategy 1: look for <li> or <div> containing a link with job-like text
    # Loose pre-filter on link text; the taxonomy gate decides for real later.
    job_keywords = re.compile(
        r"(electric|power|controls?|automation|instrument|substation|protection|"
        r"transmission|distribution|grid|energy|solar|wind|rf\b|antenna|emc|"
        r"motor|generator|inverter|scada|plc|engineer)",
        re.I,
    )

    for tag in soup.find_all(["li", "article", "div"], limit=300):
        a_tags = tag.find_all("a", href=True, recursive=False) or tag.find_all("a", href=True)
        for a in a_tags[:1]:
            title = a.get_text(strip=True)
            if len(title) < 8 or not job_keywords.search(title):
                continue
            href = a.get("href", "")
            if not href or href in seen:
                continue
            seen.add(href)

            # Resolve relative URLs
            if href.startswith("/"):
                from urllib.parse import urlparse
                parsed = urlparse(source_url)
                href = f"{parsed.scheme}://{parsed.netloc}{href}"

            # Look for location text nearby
            location = ""
            parent = tag.parent
            if parent:
                loc_span = parent.find(string=re.compile(r"\b(CA|TX|WA|NY|MA|Remote|United States)\b"))
                if loc_span:
                    location = str(loc_span).strip()

            jobs.append(JobData(
                job_title=title,
                apply_url=href,
                location=location,
                source_url=source_url,
            ))

    return jobs
