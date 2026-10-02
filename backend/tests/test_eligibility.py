"""Tests for eligibility/export-control risk detection and H1B signal."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parents[2]))

from backend.app.eligibility import detect_eligibility_risk, sponsors_h1b


def test_high_risk_citizenship():
    risk, terms = detect_eligibility_risk(
        "Applicants must be a U.S. citizen due to government contract requirements."
    )
    assert risk == "high"
    assert any("citizen" in t.lower() for t in terms)


def test_high_risk_clearance():
    risk, _ = detect_eligibility_risk("Active TS/SCI security clearance required.")
    assert risk == "high"


def test_medium_risk_itar():
    risk, terms = detect_eligibility_risk(
        "This role involves ITAR-controlled technology and export control compliance."
    )
    assert risk == "medium"
    assert any("ITAR" in t or "export" in t.lower() for t in terms)


def test_medium_risk_green_card():
    risk, _ = detect_eligibility_risk("Must be a U.S. person or permanent resident (green card).")
    assert risk == "medium"


def test_low_risk_normal_job():
    risk, terms = detect_eligibility_risk(
        "Seeking a Design Verification Engineer with SystemVerilog and UVM experience."
    )
    assert risk == "low"
    assert terms == []


def test_empty_description():
    assert detect_eligibility_risk("") == ("low", [])


def test_h1b_known_sponsor():
    assert sponsors_h1b("GE Vernova") is True
    assert sponsors_h1b("Burns & McDonnell") is True


def test_h1b_non_sponsor():
    assert sponsors_h1b("Anduril") is False
    assert sponsors_h1b("Lockheed Martin") is False


def test_h1b_unknown():
    assert sponsors_h1b("Some Random Startup XYZ") is None
