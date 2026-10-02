"""Guardrails for the New Grad / Experienced fit scores: a senior/4+yr role can
never read as an Excellent new-grad fit, true entry roles score 100, and USA is
no longer part of the relevance score."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parents[2]))

from backend.app.scoring import (
    calculate_match_score, experienced_fit_score, new_grad_fit_label,
    new_grad_fit_score, overall_recommendation,
)


def test_staff_and_senior_capped_for_new_grad():
    staff = new_grad_fit_score("Staff", True, False, False, 4, "CPU DV Engineer (Staff)")
    assert staff <= 45 and overall_recommendation(staff) == "Not Entry-Level Fit"
    senior = new_grad_fit_score("Senior", True, False, False, None, "Senior Verification Engineer")
    assert senior <= 55
    principal = new_grad_fit_score("Principal", True, False, False, 8, "Principal Engineer")
    assert principal <= 45


def test_four_plus_years_capped():
    assert new_grad_fit_score("Mid-Level", False, False, False, 4, "Verification Engineer") <= 60


def test_senior_title_not_lifted_by_newgrad_friendly_description():
    """A senior TITLE must hard-cap even when the JD mentions 'recent graduate' /
    'university grad' — the new-grad-friendly exception can't override an explicit
    senior rank (regression: a Principal role read as ng=75)."""
    jd = "Work with recent graduate hires; university graduate program mentorship."
    assert new_grad_fit_score("Principal", True, False, False, None,
                              "Principal Digital Design Engineer", jd) <= 45
    assert new_grad_fit_score("Senior", True, False, False, None,
                              "Senior Verification Engineer", jd) <= 55
    assert new_grad_fit_score("Staff", True, False, False, 5,
                              "Staff Design Verification Engineer", jd) <= 45
    # A genuinely inferred-senior role with NO senior title CAN still recover.
    assert new_grad_fit_score("Senior", True, False, False, None,
                              "Verification Engineer, New College Grad", jd) >= 75


def test_true_entry_scores_excellent():
    ng = new_grad_fit_score("New Grad", False, True, True, None, "New Grad DV Engineer")
    assert ng == 100 and new_grad_fit_label(ng) == "Excellent"
    assert overall_recommendation(ng) == "Excellent New Grad Fit"


def test_experienced_fit_high_for_senior():
    assert experienced_fit_score("Staff", True, 5) >= 90
    assert experienced_fit_score("New Grad", False, None) < 50


def test_usa_not_in_relevance_score():
    """Relevance must be identical whether or not the job is in the USA — USA is a
    hard gate, not a score booster."""
    args = dict(job_title="RTL Design Verification Engineer",
                description="systemverilog uvm verification", company_priority="A",
                location="Anywhere", first_seen_recently=False)
    usa = calculate_match_score(is_usa=True, **args)[0]
    non = calculate_match_score(is_usa=False, **args)[0]
    assert usa == non
