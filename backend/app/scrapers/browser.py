"""Real-browser Workday scraper.

Some Workday tenants (Cadence, KLA, Applied Materials, Microchip, …) serve a
fake "Workday is currently unavailable" maintenance page to any server-side
HTTP client — the plain httpx :class:`WorkdayScraper` only ever sees that, so
those companies were stuck as "direct-search" links.

A *real* Chromium session loads the careers SPA normally. Once the page has
loaded and established the tenant's cookies, the very same CXS JSON endpoints
return 200 when called through the browser's request context. So this scraper
**subclasses** :class:`WorkdayScraper` and overrides only its two HTTP helpers
to route through Playwright's :class:`APIRequestContext` — every bit of the
pagination, relevance-gating and per-job detail enrichment is reused unchanged.

This engine is **not** wired into the httpx scheduler/registry. It is driven by
the standalone local runner (``python -m backend.app.run_browser_scrape``) and
never imported by the FastAPI web service, so the free Render tier — which has
no Chromium and not enough RAM to run one — is completely unaffected.
"""

from __future__ import annotations

import contextlib
import json
import logging
from typing import Any

from .eightfold import EightfoldScraper
from .workday import WorkdayScraper

logger = logging.getLogger(__name__)

USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/148.0.0.0 Safari/537.36"
)

# Patch the most obvious headless tell so the careers SPA renders normally.
_STEALTH_INIT = "Object.defineProperty(navigator,'webdriver',{get:()=>undefined})"


class BrowserBlockedError(RuntimeError):
    """Raised when a tenant still serves the anti-bot maintenance page even in a
    real browser (almost always a wrong career-site slug)."""


class BrowserWorkdayScraper(WorkdayScraper):
    """Workday scraper that performs every HTTP call through a live browser
    session instead of httpx. Construct with a Playwright ``BrowserContext``."""

    def __init__(self, company_config: dict, context: Any):
        super().__init__(company_config)
        self._ctx = context

    async def fetch_jobs(self) -> list:
        # Establish the tenant session first, then run the inherited Workday
        # pipeline (which calls our overridden _post_json / _get_json).
        await self._prime_session()
        return await super().fetch_jobs()

    async def _prime_session(self) -> None:
        """Load the careers SPA so the context picks up the tenant's cookies.
        Bails out loudly if the tenant bounces us to the maintenance page."""
        tenant = self.config.get("workday_tenant", "")
        instance = self.config.get("workday_instance", "wd1")
        career_site = self.config.get("workday_career_site", "External")
        spa_url = f"https://{tenant}.{instance}.myworkdayjobs.com/{career_site}"

        page = await self._ctx.new_page()
        try:
            await page.goto(spa_url, wait_until="domcontentloaded", timeout=45000)
            await page.wait_for_timeout(3500)  # let the SPA + any bot-check settle
            if "maintenance" in page.url or "unavailable" in (await page.title()).lower():
                raise BrowserBlockedError(
                    f"{self.company_name}: tenant served maintenance page "
                    f"(check workday_career_site={career_site!r})"
                )
        finally:
            with contextlib.suppress(Exception):
                await page.close()

    def _wd_headers(self) -> dict[str, str]:
        tenant = self.config.get("workday_tenant", "")
        instance = self.config.get("workday_instance", "wd1")
        career_site = self.config.get("workday_career_site", "External")
        root = f"https://{tenant}.{instance}.myworkdayjobs.com"
        return {
            "Content-Type": "application/json",
            "Accept": "application/json",
            "Origin": root,
            "Referer": f"{root}/{career_site}",
        }

    # --- HTTP helpers routed through the browser session ---------------------

    async def _post_json(self, url: str, payload: dict, **kwargs) -> Any:
        resp = await self._ctx.request.post(
            url, data=json.dumps(payload), headers=self._wd_headers(), timeout=45000
        )
        if not resp.ok:
            raise BrowserBlockedError(f"CXS POST {url} -> HTTP {resp.status}")
        return await resp.json()

    async def _get_json(self, url: str, **kwargs) -> Any:
        resp = await self._ctx.request.get(
            url, headers={"Accept": "application/json"}, timeout=45000
        )
        if not resp.ok:
            raise BrowserBlockedError(f"CXS GET {url} -> HTTP {resp.status}")
        return await resp.json()


class BrowserEightfoldScraper(EightfoldScraper):
    """Eightfold scraper that performs every HTTP call through a live browser
    session (the pcsx API 403s any plain server-side client)."""

    def __init__(self, company_config: dict, context: Any):
        super().__init__(company_config)
        self._ctx = context

    async def fetch_jobs(self) -> list:
        await self._prime_session()
        return await super().fetch_jobs()

    async def _prime_session(self) -> None:
        tenant = self.config.get("eightfold_tenant", "")
        domain = self.config.get("eightfold_domain", "")
        url = f"https://{tenant}.eightfold.ai/careers?domain={domain}"
        page = await self._ctx.new_page()
        try:
            await page.goto(url, wait_until="domcontentloaded", timeout=45000)
            await page.wait_for_timeout(3500)
            if "unavailable" in (await page.title()).lower():
                raise BrowserBlockedError(f"{self.company_name}: careers page unavailable")
        finally:
            with contextlib.suppress(Exception):
                await page.close()

    async def _get_json(self, url: str, **kwargs) -> Any:
        resp = await self._ctx.request.get(
            url, headers={"Accept": "application/json"}, timeout=45000
        )
        if not resp.ok:
            raise BrowserBlockedError(f"Eightfold GET {url} -> HTTP {resp.status}")
        return await resp.json()


def browser_scraper_for(company_config: dict, context: Any):
    """Pick the right browser-backed scraper for a company by ATS platform."""
    ats = (company_config.get("ats_platform") or "").lower()
    # Big-tech career SPAs (Apple/Google/…) are DOM-scraped, not API-through-browser.
    from .giants import giant_browser_scraper_for
    giant = giant_browser_scraper_for(company_config, context)
    if giant is not None:
        return giant
    if ats == "eightfold":
        return BrowserEightfoldScraper(company_config, context)
    if ats == "generic":
        # Without this branch a `generic` company fell through to the Workday
        # scraper, which is simply the wrong adapter — and since playwright is only
        # installed by the giants workflow, the GenericScraper's own Playwright
        # fallback raised ImportError in the main scrape. So the entire `generic`
        # cohort could only ever get a plain-HTTP pass, and the careers pages that
        # render their listing in JS returned nothing. Routed here, they get a real
        # browser, which is the only way those pages produce anything.
        from .generic import GenericScraper
        return GenericScraper(company_config)
    return BrowserWorkdayScraper(company_config, context)


@contextlib.asynccontextmanager
async def browser_context(headless: bool = True):
    """Yield a ready-to-use Playwright ``BrowserContext`` (and tear it all down
    afterwards). Importing Playwright lazily keeps it an optional dependency."""
    from playwright.async_api import async_playwright

    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=headless)
        context = await browser.new_context(
            user_agent=USER_AGENT,
            locale="en-US",
            viewport={"width": 1366, "height": 900},
        )
        await context.add_init_script(_STEALTH_INIT)
        try:
            yield context
        finally:
            with contextlib.suppress(Exception):
                await context.close()
            with contextlib.suppress(Exception):
                await browser.close()
