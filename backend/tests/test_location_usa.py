"""USA-only gating is a hard validation rule. These lock in the exact cases from
the reliability spec: UK/India must be excluded, US cities/states pass, Remote-US
is allowed, and ambiguous locations are NOT silently counted as USA."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parents[2]))

from backend.app.location_utils import parse_location


def usa(loc, desc=""):
    return parse_location(loc, desc).is_usa


def test_uk_canada_india_excluded():
    assert usa("Cambridge, United Kingdom") is False
    assert usa("Cambridge, UK") is False
    assert usa("Toronto, Ontario, Canada") is False
    assert usa("Bengaluru, India") is False
    assert usa("Bengaluru, KA, India") is False
    assert usa("Remote - India") is False


def test_us_cities_and_states_pass():
    assert usa("Cambridge, MA") is True
    assert usa("Austin, TX") is True
    assert usa("Mountain View, CA") is True
    assert usa("San Jose, California, United States") is True


def test_remote_usa_allowed():
    r1 = parse_location("Remote - United States")
    assert r1.is_usa is True
    r2 = parse_location("United States Remote")
    assert r2.is_usa is True
    r3 = parse_location("Remote, USA")
    assert r3.is_usa is True


def test_multi_location_usa_kept():
    # A multi-region posting that includes a US site must read as USA.
    assert usa("Austin, TX; Bengaluru, India") is True
    assert usa("San Jose, CA; Austin, TX") is True


def test_non_usa_remote_excluded():
    assert usa("Remote - United Kingdom") is False
    assert usa("Remote (Europe)") is False


def test_ambiguous_not_silently_usa():
    # A bare "Remote" with no country signal must NOT be confidently flagged USA.
    r = parse_location("Remote")
    assert not (r.is_usa and r.confidence >= 0.8)
