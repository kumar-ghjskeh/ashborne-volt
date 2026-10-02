"""SmartRecruiters adapter: parses the public Posting API (list + detail) into
relevant JobData with clean apply URLs, real posted dates, and descriptions.
HTTP is faked — no network."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parents[2]))

import asyncio

from backend.app.scrapers.smartrecruiters import SmartRecruitersScraper

_LIST = {
    "totalFound": 2,
    "content": [
        {"id": "111", "name": "Power Electronics Engineer",
         "releasedDate": "2026-05-01T10:00:00.000Z",
         "location": {"city": "Santa Clara", "region": "CA", "country": "us",
                      "fullLocation": "Santa Clara, CA, United States"},
         "company": {"identifier": "AristaNetworks", "name": "Arista Networks"}},
        {"id": "222", "name": "Office Manager",   # irrelevant — gate should drop
         "releasedDate": "2026-05-02T10:00:00.000Z",
         "location": {"fullLocation": "Dublin, Ireland"},
         "company": {"identifier": "AristaNetworks"}},
    ],
}
_DETAIL = {
    "postingUrl": "https://jobs.smartrecruiters.com/AristaNetworks/111-fpga-design-engineer",
    "jobAd": {"sections": {
        "jobDescription": {"text": "<p>Design and verify FPGA RTL for Ethernet switches.</p>"},
        "qualifications": {"text": "<p>SystemVerilog, UVM.</p>"},
    }},
}


def test_smartrecruiters_parses_list_and_detail():
    scraper = SmartRecruitersScraper(
        {"name": "Arista Networks", "smartrecruiters_company": "aristanetworks",
         "priority": "A"})

    async def fake_get_json(url, **kwargs):
        return _DETAIL if url.endswith("/111") else _LIST

    scraper._get_json = fake_get_json  # type: ignore[assignment]

    async def go():
        async with scraper:
            return await scraper.fetch_jobs()

    jobs = asyncio.run(go())

    # Only the FPGA role survives the RTL/DV relevance gate
    assert len(jobs) == 1
    j = jobs[0]
    assert j.job_title == "Power Electronics Engineer"
    assert j.job_id == "111"
    # apply URL upgraded to the detail's clean postingUrl
    assert j.apply_url == "https://jobs.smartrecruiters.com/AristaNetworks/111-fpga-design-engineer"
    assert j.location == "Santa Clara, CA, United States"
    assert j.posted_date is not None and j.posted_date.year == 2026
    assert "FPGA RTL" in (j.full_description_text or "")
