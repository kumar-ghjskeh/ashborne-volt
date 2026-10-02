"""iCIMS career-site scraper.

iCIMS used to expose a JSON feed at ``/jobs/search?...&pr=json``. That feed is
gone — the endpoint now answers with HTML regardless — so this parses the
rendered search results instead. The markup is a stable, server-rendered
template shared across iCIMS tenants:

    <li class="iCIMS_JobCardItem">
      <div class="col-xs-6 header left"> … US-CA-Irvine </div>
      <div class="col-xs-12 title">
        <a href="https://HOST/jobs/3044/senior-…-engineer/job?in_iframe=1">
          <h3>Senior Principal Digital Design Engineer</h3>
      <div class="col-xs-12 description"> … </div>

No browser is needed: the results are in the initial HTML response.

Config keys (either works; ``icims_host`` is preferred):
    icims_host   full hostname, e.g. "careersus-maxlinear.icims.com"
    icims_portal legacy short form; expanded to "careers-{portal}.icims.com"

The full host matters — tenants are NOT uniformly "careers-{name}". MaxLinear's
public board is ``careersus-maxlinear``, while plain ``maxlinear.icims.com`` is
an OAuth-gated internal portal that returns a login redirect.
"""

from __future__ import annotations

import html
import logging
import re
from urllib.parse import unquote

from .base import BaseScraper, JobData
from ..taxonomy import DEFAULT_SEARCH_TERMS as _EE_TERMS

logger = logging.getLogger(__name__)

# One <li class="iCIMS_JobCardItem"> … </li> block per posting.
_CARD_RE = re.compile(r'<li[^>]*class="[^"]*iCIMS_JobCardItem[^"]*"[^>]*>(.*?)</li>', re.S | re.I)
# The posting link carries the requisition id and a title slug.
_LINK_RE = re.compile(r'href="(?P<url>[^"]*?/jobs/(?P<jid>\d+)/(?P<slug>[^/"]+)/job[^"]*)"', re.I)
# Real title text — preferred over the slug, which is lowercased and escaped.
_TITLE_RE = re.compile(r'<h3[^>]*>(?P<title>.*?)</h3>', re.S | re.I)
# Location sits in the card header, before the title block.
_LOC_RE = re.compile(
    r'<div[^>]*class="[^"]*header\s+left[^"]*"[^>]*>(?P<loc>.*?)</div>', re.S | re.I
)
_DESC_RE = re.compile(
    r'<div[^>]*class="[^"]*col-xs-12\s+description[^"]*"[^>]*>(?P<desc>.*?)</div>', re.S | re.I
)
_TAG_RE = re.compile(r"<[^>]+>")
_JIBE_REDIRECT = re.compile(r"window\.top\.location\.href\s*=\s*'https?:\\?/\\?/([^']+)'")

# iCIMS sits behind a WAF that answers 405 to a full browser User-Agent string
# (the project default) but serves the page normally to a bare "Mozilla/5.0".
# Verified by isolating one header at a time: UA is the only trigger — Accept,
# Accept-Language and the Sec-Fetch-* headers make no difference. Counter-
# intuitive, but reproducible, and this is a plain public GET of a page any
# visitor can load — no login, no paywall, no evasion beyond not looking like a
# headless-Chrome fingerprint the WAF over-blocks.
_UA_OVERRIDE = {"User-Agent": "Mozilla/5.0"}


def _text(fragment: str) -> str:
    """HTML fragment -> collapsed plain text."""
    if not fragment:
        return ""
    txt = _TAG_RE.sub(" ", fragment)
    txt = html.unescape(txt)
    # iCIMS ships a "Job Locations"/"Title" screen-reader label inside the same
    # element as the value; drop it so it can't end up in the location string.
    txt = re.sub(r"\b(Job Locations?|Title|Category)\b", " ", txt)
    return re.sub(r"\s+", " ", txt).strip()


_HEADER_FIELD_RE = re.compile(
    r'<dt[^>]*class="[^"]*iCIMS_JobHeaderField[^"]*"[^>]*>(?P<label>.*?)</dt>\s*'
    r'<dd[^>]*class="[^"]*iCIMS_JobHeaderData[^"]*"[^>]*>(?P<value>.*?)</dd>',
    re.S | re.I,
)


def _header_location(card: str) -> str:
    """The other iCIMS template: no header-left location, but labelled
    City / State / Country (or Location) fields in iCIMS_JobHeaderGroup."""
    fields: dict[str, str] = {}
    for m in _HEADER_FIELD_RE.finditer(card):
        label = _TAG_RE.sub(" ", m.group("label"))
        label = re.sub(r"\s+", " ", html.unescape(label)).strip().lower()
        value = re.sub(r"\s+", " ", html.unescape(_TAG_RE.sub(" ", m.group("value")))).strip()
        if value:
            fields.setdefault(label, value)
    if fields.get("location") or fields.get("job locations"):
        return _clean_location(fields.get("location") or fields.get("job locations"))
    city, state, country = fields.get("city", ""), fields.get("state", ""), fields.get("country", "")
    if city or state:
        return ", ".join(p for p in (city, state, country or "United States") if p)
    return country


def _clean_location(raw: str) -> str:
    """iCIMS encodes locations as "US-CA-Irvine" / "US-TX-Austin".

    Rewritten to "Irvine, CA, United States" so the shared location parser sees
    a form it already understands, instead of failing and leaving the job with
    an unknown location (which, with USA-only now strict, would hide it).
    """
    loc = _text(raw)
    if not loc:
        return ""
    # Multi-site reqs list every location pipe-separated
    # ("US-CA-Carlsbad | US-CA-Irvine"). Prefer the first US one so the job is
    # correctly identified as US-based; fall back to the first entry.
    if "|" in loc:
        parts = [p.strip() for p in loc.split("|") if p.strip()]
        loc = next((p for p in parts if p.upper().startswith("US-")), parts[0] if parts else "")
    m = re.match(r"^\s*US[-–]([A-Z]{2})[-–](.+?)\s*$", loc)
    if m:
        state, city = m.group(1), m.group(2).strip()
        return f"{city}, {state}, United States"
    # Non-US tenants use the same shape ("IN-KA-Bangalore", "TW-Hsinchu").
    m = re.match(r"^\s*([A-Z]{2})[-–](?:[A-Z]{2}[-–])?(.+?)\s*$", loc)
    if m and m.group(1) != "US":
        return f"{m.group(2).strip()}, {m.group(1)}"
    return loc


class ICIMSScraper(BaseScraper):
    """Parses the rendered iCIMS job-search results page."""

    def _host(self) -> str:
        host = (self.config.get("icims_host") or "").strip().rstrip("/")
        if host:
            return host.replace("https://", "").replace("http://", "")
        portal = (self.config.get("icims_portal") or "").strip()
        return f"careers-{portal}.icims.com" if portal else ""

    async def fetch_jobs(self) -> list[JobData]:
        host = self._host()
        if not host:
            logger.warning("%s: missing icims_host / icims_portal config", self.company_name)
            return []

        base_url = f"https://{host}/jobs/search"
        keywords = self.config.get("search_keywords") or list(_EE_TERMS)
        jobs: list[JobData] = []
        seen: set[str] = set()

        for kw in keywords[:4]:
            try:
                resp = await self.client.get(
                    base_url,
                    params={"ss": "1", "searchKeyword": kw, "in_iframe": "1"},
                    headers=_UA_OVERRIDE,
                )
                resp.raise_for_status()
                body = resp.text
            except Exception as e:
                logger.error("iCIMS fetch failed for %s kw=%s: %s", self.company_name, kw, e)
                continue

            # Tenants fronted by a Jibe site answer with a bare JS redirect to it
            # (window.top.location.href = 'https://jobs.example.com/...'). That
            # site has a JSON API with full descriptions — hand over to it.
            redirect = _JIBE_REDIRECT.search(body)
            if redirect and "iCIMS_JobCardItem" not in body:
                from .jibe import JibeScraper
                jibe_host = redirect.group(1).replace("\\/", "/").split("/")[0]
                logger.info("%s: iCIMS redirects to Jibe site %s", self.company_name, jibe_host)
                sub = JibeScraper({**self.config, "jibe_host": jibe_host})
                try:
                    return await sub.fetch_jobs()
                finally:
                    await sub.client.aclose()

            for card in _CARD_RE.findall(body):
                link = _LINK_RE.search(card)
                if not link:
                    continue
                jid = link.group("jid")
                if jid in seen:
                    continue
                seen.add(jid)

                title_m = _TITLE_RE.search(card)
                title = _text(title_m.group("title")) if title_m else ""
                if not title:
                    # Fall back to the URL slug ("senior-rtl-design-engineer").
                    title = unquote(link.group("slug")).replace("-", " ").strip().title()
                if not title:
                    continue

                loc_m = _LOC_RE.search(card)
                desc_m = _DESC_RE.search(card)
                apply_url = html.unescape(link.group("url")).split("?")[0]

                jobs.append(JobData(
                    job_title=title,
                    apply_url=apply_url,
                    location=(_clean_location(loc_m.group("loc")) if loc_m else "")
                    or _header_location(card),
                    job_id=jid,
                    source_url=base_url,
                    description_snippet=_text(desc_m.group("desc"))[:400] if desc_m else "",
                ))

        return self._filter_relevant(jobs)
