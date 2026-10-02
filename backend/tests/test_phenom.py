"""Phenom adapter: parses the /api/jobs payload, appends country so the location
gate can tell US from foreign, parses the ISO posted date, and dedupes by req_id."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parents[2]))

import asyncio

from backend.app.scrapers.phenom import PhenomScraper, _location, _parse_posted


def test_parse_posted_iso_offset():
    d = _parse_posted("2026-06-11T22:13:00+0000")
    assert d is not None and d.year == 2026 and d.month == 6 and d.day == 11
    assert _parse_posted("") is None


def test_location_appends_country():
    assert _location({"full_location": "San Jose, California", "country": "United States"}) \
        == "San Jose, California, United States"
    # already contains country -> not duplicated
    assert _location({"full_location": "Austin, Texas, United States", "country": "United States"}) \
        == "Austin, Texas, United States"
    # falls back to city/state
    assert _location({"city": "Hyderabad", "state": "Telangana", "country": "India"}) \
        == "Hyderabad, Telangana, India"


def _page(jobs, total):
    return {"jobs": [{"data": d} for d in jobs], "totalCount": total}


def test_fetch_parses_and_dedupes(monkeypatch):
    sc = PhenomScraper({"name": "AMD", "phenom_host": "careers.amd.com",
                        "search_keywords": ["verification"]})
    calls = {"n": 0}

    async def fake_get_json(url, params=None, **kw):
        calls["n"] += 1
        # Same req_id returned twice -> must dedupe to one job.
        return _page([
            {"req_id": "111", "title": "Electrical Engineer",
             "full_location": "Austin, Texas", "country": "United States",
             "description": "<p>UVM SystemVerilog</p>", "posted_date": "2026-06-01T10:00:00+0000",
             "apply_url": "https://careers-amd.icims.com/jobs/111/login"},
            {"req_id": "111", "title": "Electrical Engineer (dup)",
             "full_location": "Austin, Texas", "country": "United States",
             "description": "x"},
            {"req_id": "222", "title": "Sales Manager",   # culled by relevance gate
             "full_location": "Austin, Texas", "country": "United States", "description": "y"},
        ], total=2)

    monkeypatch.setattr(sc, "_get_json", fake_get_json)
    jobs = asyncio.run(sc.fetch_jobs())
    titles = [j.job_title for j in jobs]
    assert "Electrical Engineer" in titles
    assert "Sales Manager" not in titles            # relevance gate dropped it
    assert sum(1 for t in titles if t.startswith("Electrical Engineer")) == 1  # deduped
    dv = next(j for j in jobs if j.job_id == "111")
    assert dv.location == "Austin, Texas, United States"
    assert dv.posted_date is not None and dv.apply_url.endswith("/111/login")
    assert "UVM" in dv.description_snippet
