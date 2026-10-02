"""Eightfold adapter: parses the pcsx search + position_details JSON into
relevant JobData (clean title, apply URL, location, posted date, description).
HTTP is faked — no network / no browser."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parents[2]))

import asyncio

from backend.app.scrapers.eightfold import EightfoldScraper, _clean_title

_SEARCH = {
    "data": {
        "count": 2,
        "positions": [
            {"id": "111", "name": "Electrical Engineer (Onsite) - San Diego, California",
             "locations": ["San Diego, California, United States"],
             "postedTs": 1775520000, "positionUrl": "/careers/job/111"},
            {"id": "222", "name": "Marketing Manager",  # irrelevant -> gate drops
             "locations": ["Austin, Texas"], "postedTs": 1775520000,
             "positionUrl": "/careers/job/222"},
        ],
    }
}
_DETAIL = {"data": {"jobDescription": "<p>Build UVM testbenches and verify RTL.</p>",
                    "publicUrl": "https://careers.qualcomm.com/careers/job/111"}}


def test_clean_title_strips_mode_and_location():
    assert _clean_title("Substation Engineer (Onsite) - Cork, Ireland", "Cork, Ireland") == "Substation Engineer"
    assert _clean_title("Controls Engineer", "") == "Controls Engineer"


def test_eightfold_parses_search_and_detail():
    scraper = EightfoldScraper(
        {"name": "Qualcomm", "eightfold_tenant": "qualcomm",
         "eightfold_domain": "qualcomm.com", "priority": "S",
         "search_keywords": ["verification"]})

    async def fake_get_json(url, **kwargs):
        return _DETAIL if "position_details" in url else _SEARCH

    scraper._get_json = fake_get_json  # type: ignore[assignment]

    async def go():
        async with scraper:
            return await scraper.fetch_jobs()

    jobs = asyncio.run(go())
    assert len(jobs) == 1                       # only the DV role survives the gate
    j = jobs[0]
    assert j.job_title == "Electrical Engineer"   # mode + location trimmed
    assert j.job_id == "111"
    assert j.location.startswith("San Diego")
    assert j.posted_date is not None and j.posted_date.year == 2026
    # apply URL upgraded to the detail's branded publicUrl
    assert j.apply_url == "https://careers.qualcomm.com/careers/job/111"
    assert "UVM" in (j.full_description_text or "")
