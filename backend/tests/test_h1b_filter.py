"""The H1B filter must show only jobs an H1B candidate can actually apply to.

This filter was completely non-functional in the live app. `sponsors_h1b` is a
model @property and was never listed in snapshot.LIST_FIELDS, so the published
corpus carried no sponsorship signal at all. The frontend tested
`j.sponsors_h1b === false` against a field that was always `undefined`, which is
never equal to `false` — so every job passed and the filter appeared to work
while doing nothing.

Underneath that sat a second bug: the lookup was exact set membership on a
lowercased name, so "cadence" never matched the catalog's "Cadence Design
Systems" and "renesas" never matched "Renesas Electronics". 22 of 54 producing
companies, 101 US jobs, resolved to unknown.

The requirement is strict: only employers known to sponsor, and only postings
whose own text does not demand citizenship, a green card, or ITAR access.
"""

from __future__ import annotations

import io
from pathlib import Path

import yaml

from backend.app.eligibility import (
    _norm,
    detect_eligibility_risk,
    h1b_accessible,
    sponsors_h1b,
)
from backend.app.snapshot import LIST_FIELDS

CFG = Path(__file__).resolve().parents[2] / "config" / "companies.yaml"


def test_sponsorship_signal_is_exported_to_the_corpus():
    """Without this the filter has nothing to read and silently matches all."""
    assert "sponsors_h1b" in LIST_FIELDS, (
        "sponsors_h1b is missing from snapshot.LIST_FIELDS. The app is served "
        "from the corpus, so a signal that is not exported does not exist as far "
        "as the UI is concerned — and the H1B filter degrades to a no-op."
    )


def test_multiword_company_names_resolve():
    """The exact-match bug: these all reported unknown before normalisation."""
    for name in (
        "Schneider Electric",
        "Burns & McDonnell",
        "Black & Veatch",
        "Skyworks Solutions",
        "Texas Instruments Incorporated",
        "Keysight Technologies, Inc.",
    ):
        assert sponsors_h1b(name) is True, (
            f"{name!r} resolves to {sponsors_h1b(name)!r}. Multi-word and "
            "suffixed names must normalise to the same key as the curated list."
        )


def test_normalisation_is_idempotent_and_suffix_insensitive():
    assert _norm("Keysight Technologies") == _norm("keysight technologies, inc.")
    assert _norm("Keysight") == _norm("Keysight Technologies")
    assert _norm(_norm("Analog Devices")) == _norm("Analog Devices")
    # Different businesses of one group stay distinct.
    assert _norm("Siemens Energy") != _norm("Siemens")
    assert _norm("Hitachi Energy") != _norm("Hitachi Rail")


def test_unknown_employer_is_not_treated_as_a_yes():
    """Strictness is the whole requirement: unknown must not pass the filter."""
    assert sponsors_h1b("Some Company We Have Never Heard Of") is None
    assert h1b_accessible("Some Company We Have Never Heard Of", "low") is False


def test_defense_primes_are_excluded():
    for name in ("Lockheed Martin", "Northrop Grumman", "L3Harris", "Boeing",
                 "Collins Aerospace", "Leidos", "SpaceX", "Tennessee Valley Authority"):
        assert sponsors_h1b(name) is False, f"{name} must be marked non-sponsoring"
        assert h1b_accessible(name, "low") is False


def test_job_text_overrides_a_sponsoring_employer():
    """GE Vernova sponsors broadly, but a req demanding citizenship is still closed.

    Both 'high' (citizenship / clearance) and 'medium' (green card / US person /
    ITAR) block an H1B holder, so both must fail.
    """
    assert h1b_accessible("GE Vernova", "low") is True
    assert h1b_accessible("GE Vernova", "high") is False
    assert h1b_accessible("GE Vernova", "medium") is False
    assert h1b_accessible("GE Vernova", None) is True, "absent risk means no blocker found"


def test_the_blocking_signal_is_actually_detectable_from_real_wording():
    """Guard the chain end to end: wording -> risk level -> filter decision."""
    for text, expect in (
        ("Applicants must be a U.S. citizen to qualify.", "high"),
        ("Position requires an active security clearance.", "high"),
        ("Must be a U.S. person as defined by ITAR.", "medium"),
        ("Experience with ETAP and relay settings required.", "low"),
    ):
        risk, _terms = detect_eligibility_risk(text)
        assert risk == expect, f"{text!r} -> {risk!r}, expected {expect!r}"
    blocked, _ = detect_eligibility_risk("Must be a U.S. citizen.")
    assert h1b_accessible("Hitachi Energy", blocked) is False
    clean, _ = detect_eligibility_risk("ETAP and relay settings required.")
    assert h1b_accessible("Hitachi Energy", clean) is True


def test_every_catalog_company_is_classified():
    """An unclassified company is invisible under a strict filter, so adding one
    without classifying it silently drops its jobs from the H1B view."""
    with CFG.open(encoding="utf-8") as fh:
        companies = yaml.safe_load(fh)["companies"]
    from backend.app.eligibility import is_classified
    unclassified = [c["name"] for c in companies if not is_classified(c.get("name", ""))]
    assert not unclassified, (
        "These catalog companies have no sponsorship classification, so a strict "
        "H1B filter hides every job they produce:\n  " + "\n  ".join(unclassified)
        + "\nAdd each to _SPONSOR_NAMES, _NON_SPONSOR_NAMES or _UNVERIFIED_NAMES in eligibility.py."
    )
