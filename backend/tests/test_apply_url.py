"""Tests for safe apply URL processing."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parents[2]))

from backend.app.apply_url import process_apply_url


def test_greenhouse_url_direct():
    result = process_apply_url(
        "https://boards.greenhouse.io/nvidia/jobs/12345",
        ats_platform="greenhouse",
        company_name="NVIDIA",
    )
    assert result.apply_url_status == "ok"
    assert result.safe_apply_url == "https://boards.greenhouse.io/nvidia/jobs/12345"


def test_lever_url_direct():
    result = process_apply_url(
        "https://jobs.lever.co/amd/abc123",
        ats_platform="lever",
        company_name="AMD",
    )
    assert result.apply_url_status == "ok"
    assert "lever.co" in result.safe_apply_url


def test_workday_broken_en_us_fallback():
    result = process_apply_url(
        "https://nvidia.wd5.myworkdayjobs.com/en-US/NVIDIAExternalCareerSite/jobs",
        ats_platform="workday",
        company_name="NVIDIA",
    )
    assert result.apply_url_status == "fallback"
    assert "nvidia" in result.safe_apply_url.lower()


def test_workday_broken_wday_fallback():
    result = process_apply_url(
        "https://amd.wd5.myworkdayjobs.com/wday/cxs/amd/AMD/job/12345",
        ats_platform="workday",
        company_name="AMD",
    )
    assert result.apply_url_status == "fallback"
    assert result.safe_apply_url != ""


def test_tracking_params_stripped():
    url = "https://boards.greenhouse.io/company/jobs/99?gh_src=tracker&utm_source=linkedin"
    result = process_apply_url(url, ats_platform="greenhouse", company_name="Company")
    assert "utm_source" not in result.safe_apply_url
    assert "gh_src" not in result.safe_apply_url
    assert result.apply_url_status in ("ok", "stripped")


def test_no_url_with_known_company_fallback():
    result = process_apply_url("", ats_platform="workday", company_name="NVIDIA")
    assert result.apply_url_status == "fallback"
    assert result.safe_apply_url != ""


def test_no_url_unknown_company_dead():
    result = process_apply_url("", ats_platform="generic", company_name="Unknown Corp XYZ")
    assert result.apply_url_status == "dead"


def test_amazon_jobs_url_direct():
    result = process_apply_url(
        "https://www.amazon.jobs/en/jobs/1234567/hardware-engineer",
        ats_platform="amazon",
        company_name="Amazon",
    )
    assert result.apply_url_status == "ok"
