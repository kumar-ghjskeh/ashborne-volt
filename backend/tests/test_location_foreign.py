"""Guardrail: an explicit foreign country must override an ambiguous US-city
name so foreign jobs never leak into the USA list (the Cambridge UK -> MA bug),
while genuine US and multi-region-with-US-office postings stay USA."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parents[2]))

import pytest

from backend.app.location_utils import parse_location

NON_USA = [
    "Cambridge, United Kingdom",
    "London, United Kingdom",
    "Richmond, BC, Canada",          # collides with Richmond, VA
    "Toronto, Ontario, Canada",
    "Bangalore, Karnataka, India",
    "Hsinchu City, Hsinchu County, Taiwan",
    "Munich, Germany",
]

USA = [
    "Cambridge, MA",
    "San Diego, California, United States of America",
    "Santa Clara, California",
    "Boise, ID",
    "Hillsboro, OR",
    "Austin, Texas, United States; Cork, Ireland",   # multi-region w/ US office
    "Remote",
    "Remote - US",
]


@pytest.mark.parametrize("loc", NON_USA)
def test_foreign_jobs_excluded(loc):
    assert parse_location(loc).is_usa is False, f"{loc!r} wrongly classed USA"


@pytest.mark.parametrize("loc", USA)
def test_usa_jobs_kept(loc):
    assert parse_location(loc).is_usa is True, f"{loc!r} wrongly excluded from USA"
