"""Avature (TSMC) + Radancy (Synopsys) HTML parsers — extract id/title/location
per card, relevance-gate non-RTL/DV rows, and parse posted dates. curl_cffi is
monkeypatched (no network)."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parents[2]))

import asyncio

from backend.app.scrapers.avature import AvatureScraper
from backend.app.scrapers.radancy import RadancyScraper


class _Resp:
    def __init__(self, status, text):
        self.status_code = status
        self.text = text


# ── Avature (TSMC) ────────────────────────────────────────────────────────────
_AV = """
<span>2 Jobs</span>
<article id="article--1"><div class="article__header__text"><h3 class="title">
<a class="link" href="https://careers.tsmc.com/en_US/careers/JobDetail?jobId=383&source=x">
Substation Design Engineer</a></h3></div>
<div class="article__header__text__subtitle">USA-California</div></article>
<article id="article--2"><div class="article__header__text"><h3 class="title">
<a class="link" href="https://careers.tsmc.com/en_US/careers/JobDetail?jobId=384&source=x">
Recruiter (HR)</a></h3></div>
<div class="article__header__text__subtitle">Taiwan</div></article>
"""


def test_avature_parses_cards(monkeypatch):
    sc = AvatureScraper({"name": "TSMC", "avature_host": "careers.tsmc.com",
                         "search_keywords": ["verification"]})
    monkeypatch.setattr(sc, "_get", lambda url: _Resp(200, _AV if "jobOffset=0" in url else "<html></html>"))
    monkeypatch.setattr(sc, "_enrich", lambda jobs: None)
    jobs = asyncio.run(sc.fetch_jobs())
    titles = {j.job_title for j in jobs}
    assert "Substation Design Engineer" in titles
    assert "Recruiter (HR)" not in titles          # relevance gate dropped it
    dv = next(j for j in jobs if j.job_id == "383")
    assert dv.location == "USA-California"
    assert dv.apply_url.endswith("jobId=383&source=x")


# ── Radancy (Synopsys) ────────────────────────────────────────────────────────
_RAD = """
<li class="search-results-list__list-item">
<a class="sr-job-link" href="/job/austin/asic-dv-engineer/44408/111" data-job-id="111">
<h2>Protection and Control Engineer<img src="x.png"></h2></a>
<div class="sr-wrapper"><span class="job-location"><img src="pin.png">Austin, Texas</span>
<span class="job-date-posted"><strong>Posted: </strong>05/20/2026</span></div></li>
<li class="search-results-list__list-item">
<a class="sr-job-link" href="/job/bengaluru/senior-dft/44408/222" data-job-id="222">
<h2>Senior Power Systems Engineer<img src="x.png"></h2></a>
<div class="sr-wrapper"><span class="job-location"><img src="pin.png">Bengaluru, India</span></div></li>
"""


def test_radancy_parses_cards(monkeypatch):
    sc = RadancyScraper({"name": "Synopsys", "radancy_host": "careers.synopsys.com",
                         "search_keywords": ["verification"]})
    monkeypatch.setattr(sc, "_get", lambda url: _Resp(200, _RAD if "p=1" in url else "<html></html>"))
    monkeypatch.setattr(sc, "_enrich", lambda jobs, host: None)
    jobs = asyncio.run(sc.fetch_jobs())
    assert {j.job_id for j in jobs} == {"111", "222"}
    us = next(j for j in jobs if j.job_id == "111")
    assert us.job_title == "Protection and Control Engineer"
    assert us.location == "Austin, Texas"          # location after the inner <img>
    assert us.posted_date is not None and us.posted_date.month == 5
    assert us.apply_url == "https://careers.synopsys.com/job/austin/asic-dv-engineer/44408/111"
