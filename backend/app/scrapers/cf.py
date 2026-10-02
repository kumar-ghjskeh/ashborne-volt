"""curl_cffi scrape engine — the browserless replacement for the Playwright
engine.

A Chrome TLS/JA3 fingerprint (curl_cffi impersonate="chrome") gets past the
anti-bot walls that previously needed a real browser: Workday's fake maintenance
page / 422, Eightfold's 403, and Cloudflare. These subclasses reuse ALL of the
existing Workday / Eightfold pagination + relevance + detail logic and only swap
the HTTP transport — so there's no browser, no Chromium, and the whole thing runs
on a tiny cloud/CI box (e.g. the GitHub Actions 24/7 schedule).

Jobvite (already curl_cffi-native) is dispatched here too. curl_cffi is imported
lazily so importing this module never requires it.
"""

from __future__ import annotations

import asyncio
from typing import Any

from .base import BaseScraper
from .eightfold import EightfoldScraper
from .workday import WorkdayScraper


def _cffi_get(url: str, headers: dict | None = None) -> Any:
    from curl_cffi import requests as creq  # lazy: optional dependency
    r = creq.get(url, impersonate="chrome", timeout=30,
                 headers={"Accept": "application/json", **(headers or {})})
    r.raise_for_status()
    return r.json()


def _cffi_post(url: str, payload: dict, headers: dict | None = None) -> Any:
    from curl_cffi import requests as creq
    r = creq.post(url, json=payload, impersonate="chrome", timeout=30,
                  headers={"Accept": "application/json",
                           "Content-Type": "application/json", **(headers or {})})
    r.raise_for_status()
    return r.json()


class CfWorkdayScraper(WorkdayScraper):
    """Workday CXS via curl_cffi instead of httpx — bypasses the 422/maintenance
    anti-bot without a browser."""

    async def _post_json(self, url: str, payload: dict, **_) -> Any:
        return await asyncio.to_thread(_cffi_post, url, payload)

    async def _get_json(self, url: str, **_) -> Any:
        return await asyncio.to_thread(_cffi_get, url)


class CfEightfoldScraper(EightfoldScraper):
    """Eightfold pcsx via curl_cffi (the API 403s plain httpx)."""

    async def _get_json(self, url: str, **_) -> Any:
        return await asyncio.to_thread(_cffi_get, url)


def cf_scraper_for(company_config: dict) -> BaseScraper:
    """Pick the curl_cffi-backed scraper for an engine:cf company by ATS."""
    from . import get_scraper  # local import avoids a cycle
    ats = (company_config.get("ats_platform") or "").lower()
    if ats == "workday":
        return CfWorkdayScraper(company_config)
    if ats == "eightfold":
        return CfEightfoldScraper(company_config)
    # jobvite + avature are curl_cffi-native (see get_scraper); clean-API fallback
    return get_scraper(company_config)
