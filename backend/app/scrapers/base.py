"""Abstract base scraper with shared HTTP utilities."""

from __future__ import annotations

import asyncio
import logging
from abc import ABC, abstractmethod
from typing import Any

import httpx

from ..config import settings

logger = logging.getLogger(__name__)

DEFAULT_HEADERS = {
    "User-Agent": settings.scraper_user_agent,
    "Accept": "application/json, text/html, */*",
    "Accept-Language": "en-US,en;q=0.9",
    "Sec-Fetch-Mode": "cors",
    "Sec-Fetch-Site": "same-origin",
}


class JobData:
    """Raw job data returned by scrapers before DB persistence."""

    __slots__ = (
        "job_id", "job_title", "location", "apply_url", "source_url",
        "posted_date", "description_snippet", "full_description_text",
    )

    def __init__(
        self,
        job_title: str,
        apply_url: str,
        location: str = "",
        job_id: str = "",
        source_url: str = "",
        posted_date: Any = None,
        description_snippet: str = "",
        full_description_text: str = "",
    ):
        self.job_title = job_title
        self.apply_url = apply_url
        self.location = location
        self.job_id = job_id
        self.source_url = source_url
        self.posted_date = posted_date
        self.description_snippet = description_snippet
        self.full_description_text = full_description_text


class BaseScraper(ABC):
    def __init__(self, company_config: dict):
        self.config = company_config
        self.company_name: str = company_config["name"]
        self.client = httpx.AsyncClient(
            headers=DEFAULT_HEADERS,
            timeout=settings.request_timeout_seconds,
            follow_redirects=True,
        )

    async def __aenter__(self):
        return self

    async def __aexit__(self, *_):
        await self.client.aclose()

    @abstractmethod
    async def fetch_jobs(self) -> list[JobData]:
        """Return list of raw JobData objects for this company."""

    async def _get_json(self, url: str, **kwargs) -> Any:
        await asyncio.sleep(settings.request_timeout_seconds * 0)  # yield
        resp = await self.client.get(url, **kwargs)
        resp.raise_for_status()
        return resp.json()

    async def _post_json(self, url: str, payload: dict, **kwargs) -> Any:
        resp = await self.client.post(url, json=payload, **kwargs)
        resp.raise_for_status()
        return resp.json()

    def _keywords_match(self, text: str, keywords: list[str]) -> bool:
        text_l = text.lower()
        return any(kw.lower() in text_l for kw in keywords)

    # Discipline-free titles ("Project Engineer") kept for a description fetch,
    # per company per run. Bounded so a board full of generic titles cannot turn
    # one company into hundreds of detail requests.
    MAYBE_CAP = 40

    def _filter_relevant(self, jobs: list[JobData], keep_maybe: bool = False) -> list[JobData]:
        """Keep only electrical-engineering postings (title-first gate).

        With ``keep_maybe`` a title the classifier could not decide without a
        description ("Project Engineer", "Field Engineer") is kept too, so an
        adapter that fetches descriptions afterwards can re-judge it with
        ``_filter_relevant`` again. Adapters without a detail fetch leave it off:
        an undecidable title is dropped rather than guessed.
        """
        from ..scoring import relevance_verdict

        relevant: list[JobData] = []
        maybes = 0
        for j in jobs:
            v = relevance_verdict(j.job_title, j.full_description_text or j.description_snippet or "")
            if v.relevant:
                relevant.append(j)
            elif keep_maybe and v.needs_description and maybes < self.MAYBE_CAP \
                    and not (j.full_description_text or j.description_snippet):
                relevant.append(j)
                maybes += 1
        return relevant
