"""Volt-specific eligibility language: sponsorship refusals block the H1B view."""

import pytest

from backend.app.eligibility import detect_eligibility_risk, h1b_accessible


@pytest.mark.parametrize("text", [
    "Applicants must be authorized to work in the United States without sponsorship.",
    "We will not sponsor visas for this position.",
    "The company is unable to sponsor employment visas.",
    "Must be legally authorized to work in the US without current or future sponsorship.",
    "Visa sponsorship is not available for this role.",
    "This role is not eligible for visa sponsorship.",
])
def test_sponsorship_refusals_are_flagged(text):
    risk, labels = detect_eligibility_risk(text)
    assert risk == "medium" and "No visa sponsorship" in labels


def test_sponsorship_offer_is_not_a_refusal():
    risk, labels = detect_eligibility_risk("Visa sponsorship available for qualified candidates.")
    assert "No visa sponsorship" not in labels


def test_refusal_blocks_h1b_even_at_a_sponsoring_employer(monkeypatch):
    from backend.app import eligibility
    monkeypatch.setattr(eligibility, "sponsors_h1b", lambda c: True)
    risk, _ = detect_eligibility_risk("We will not sponsor visas for this position.")
    assert h1b_accessible("Any Co", risk) is False
