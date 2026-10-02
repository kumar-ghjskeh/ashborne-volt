"""Tests for deduplication fingerprinting."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parents[2]))

from backend.app.services.dedupe import make_fingerprint


def test_same_job_id_matches():
    fp1 = make_fingerprint("NVIDIA", "DV Engineer", "Santa Clara", job_id="12345")
    fp2 = make_fingerprint("NVIDIA", "DV Engineer", "Santa Clara", job_id="12345")
    assert fp1 == fp2


def test_different_job_id_differs():
    fp1 = make_fingerprint("NVIDIA", "DV Engineer", "Santa Clara", job_id="12345")
    fp2 = make_fingerprint("NVIDIA", "DV Engineer", "Santa Clara", job_id="99999")
    assert fp1 != fp2


def test_same_url_matches():
    url = "https://nvidia.wd5.myworkdayjobs.com/job/12345"
    fp1 = make_fingerprint("NVIDIA", "DV Engineer", "Santa Clara", apply_url=url)
    fp2 = make_fingerprint("NVIDIA", "DV Engineer", "Austin", apply_url=url)
    assert fp1 == fp2


def test_title_location_fallback():
    fp1 = make_fingerprint("AMD", "RTL Design Engineer", "Austin")
    fp2 = make_fingerprint("AMD", "RTL Design Engineer", "Austin")
    assert fp1 == fp2


def test_different_company_differs():
    fp1 = make_fingerprint("NVIDIA", "DV Engineer", "Santa Clara", job_id="12345")
    fp2 = make_fingerprint("AMD", "DV Engineer", "Santa Clara", job_id="12345")
    assert fp1 != fp2


def test_case_insensitive():
    fp1 = make_fingerprint("nvidia", "DV Engineer", "santa clara", job_id="abc")
    fp2 = make_fingerprint("NVIDIA", "DV Engineer", "Santa Clara", job_id="abc")
    assert fp1 == fp2
