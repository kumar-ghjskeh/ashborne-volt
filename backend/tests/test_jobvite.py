"""Jobvite Engage parser: extracts id/title/location/apply-url from the
server-rendered /search/jobs HTML, decodes entities, and the relevance gate
drops non-RTL/DV rows. Network (curl_cffi) is monkeypatched."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parents[2]))

import asyncio

from backend.app.scrapers import jobvite
from backend.app.scrapers.jobvite import JobviteScraper

HOST = "careers.amperecomputing.com"

# Two job cards in the real Jobvite Engage layout: one DV (US), one sales (drop),
# one DV (India).
_PAGE1 = f"""
<h3 class="heading-6 space-none"><a href="https://{HOST}/jobs/111-ip-design-verification-engineer">Instrumentation &amp; Controls Engineer</a></h3></div>
<div class="large-3 columns"><span class="hide-for-large">Category: </span>Verification &amp; Validation</div>
<div class="large-3 columns"><span class="hide">Location: </span>
    Santa Clara,
    CA,
    United States
</div>
<h3 class="heading-6 space-none"><a href="https://{HOST}/jobs/222-regional-sales-manager">Regional Sales Manager</a></h3></div>
<div class="large-3 columns"><span class="hide">Location: </span> Austin, TX, United States </div>
<h3 class="heading-6 space-none"><a href="https://{HOST}/jobs/333-soc-design-verification-engineer">Power Systems Engineer</a></h3></div>
<div class="large-3 columns"><span class="hide">Location: </span> Bangalore, KA, India </div>
"""


class _Resp:
    def __init__(self, status, text):
        self.status_code = status
        self.text = text


def test_jobvite_parses_cards(monkeypatch):
    def fake_get(url):
        if "/search/jobs" in url and "page=1" in url:
            return _Resp(200, _PAGE1)
        if "/search/jobs" in url:
            return _Resp(200, "<html>no jobs</html>")  # page>=2 stops pagination
        return _Resp(200, '<meta name="description" content="Build UVM testbenches.">')

    monkeypatch.setattr(jobvite, "_impersonated_get", fake_get)
    sc = JobviteScraper({"name": "Ampere", "jobvite_host": HOST,
                         "search_keywords": ["verification"]})
    jobs = asyncio.run(sc.fetch_jobs())
    titles = {j.job_title for j in jobs}
    assert "Instrumentation & Controls Engineer" in titles      # entity decoded
    assert "Power Systems Engineer" in titles
    assert "Regional Sales Manager" not in titles             # relevance gate dropped it

    dv = next(j for j in jobs if j.job_id == "111")
    assert dv.location == "Santa Clara, CA, United States"     # location column, cleaned
    assert dv.apply_url == f"https://{HOST}/jobs/111-ip-design-verification-engineer"
    assert "UVM" in (dv.description_snippet or "")             # enriched from job page


def test_jobvite_missing_host_returns_empty():
    sc = JobviteScraper({"name": "X", "jobvite_host": ""})
    assert asyncio.run(sc.fetch_jobs()) == []
