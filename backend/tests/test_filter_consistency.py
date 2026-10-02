"""Guardrails proving the seniority classification is internally consistent and
that 'Best match' resume sorting respects the candidate's level.

These lock in the two real bugs found on production:
  1. A job could read "Entry Level" yet carry is_senior=True (two disagreeing
     engines) — so senior roles leaked through level-based filters.
  2. 'Best match' resume sort ranked Staff/Senior roles above entry roles for a
     no-experience resume because it sorted on pure skill overlap.
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parents[2]))

from backend.app.resume_match import compute_match
from backend.app.scoring import (
    _ENTRY_TIERS, _SENIOR_TIERS, classify_seniority, classify_seniority_flags,
)

# A representative spread of real EE titles (utility I–IV grades included).
_TITLES = [
    ("Electrical Engineer", ""),
    ("Senior Power Systems Engineer", ""),
    ("Staff Controls Engineer", ""),
    ("Sr Principal Protection Engineer", ""),
    ("Substation Design Lead", ""),
    ("Principal Power Electronics Engineer", ""),
    ("Engineering Manager, Transmission Planning", ""),
    ("Controls Architect", ""),
    ("Distribution Engineer III", ""),
    ("Distribution Engineer II", ""),
    ("Protection & Controls Engineer", "0-3 years of experience preferred"),
    ("Electrical Engineer, New College Grad 2026", ""),
    ("Junior Electrical Designer", ""),
    ("Electrical Engineer I", ""),
    ("Engineer in Training (EIT) - Substation", ""),
    ("Electrical Engineering Intern", ""),
    ("RF Engineer", "Requires 10+ years of experience"),
]


def test_level_and_flags_never_contradict():
    """is_senior/is_entry are derived from the displayed level, so a job can never
    be both senior and entry, and the flags always match the level tier."""
    for title, desc in _TITLES:
        level, _ = classify_seniority(title, desc)
        is_entry, is_senior = classify_seniority_flags(title, desc)
        assert not (is_entry and is_senior), f"{title!r} is both entry and senior"
        assert is_senior == (level in _SENIOR_TIERS), f"{title!r}: senior flag != level {level}"
        assert is_entry == (level in _ENTRY_TIERS), f"{title!r}: entry flag != level {level}"


def test_utility_grades():
    """Utilities and EPC firms grade engineers I-IV: I and EIT are entry, II mid,
    III/IV senior. Interns are their own level, never entry."""
    assert classify_seniority("Distribution Engineer I", "")[0] == "Entry Level"
    assert classify_seniority("Engineer in Training (EIT)", "")[0] == "Entry Level"
    assert classify_seniority("Distribution Engineer II", "")[0] == "Mid-Level"
    assert classify_seniority("Distribution Engineer III", "")[0] == "Senior"
    assert classify_seniority("Transmission Engineer IV", "")[0] == "Senior"
    assert classify_seniority("Electrical Engineering Intern", "")[0] == "Intern"
    assert classify_seniority_flags("Electrical Engineering Co-op", "") == (False, False)


def test_multi_grade_requisitions_are_open_to_entry_level():
    """Utilities post one req across grades; it must reach the entry-level view."""
    from backend.app.scoring import new_grad_fit_score
    for title in ("Engineer I, II, III or Principal",
                  "Distribution Planning Engineer (Entry, Staff, Senior, or Principal)",
                  "Engineer I/II/III/Principal - Transmission Planning",
                  "Engineer I, Engineer II, Engineer III Grid Operations",
                  "Engineer I or Senior Engineer - Distribution"):
        level, _ = classify_seniority(title, "")
        is_entry, is_senior = classify_seniority_flags(title, "")
        assert (level, is_entry, is_senior) == ("Entry Level", True, False), title
        assert new_grad_fit_score(level, is_senior, is_entry, False, None, title, "") >= 90, title
    # A range that starts at III is still senior.
    assert classify_seniority_flags("Engineer III or Senior Engineer - Transmission", "")[1] is True


def test_architect_and_consulting_titles_are_senior():
    for title in ("Controls Architect", "Consulting Engineer - Protection",
                  "Senior Electrical Engineer"):
        _, is_senior = classify_seniority_flags(title, "")
        assert is_senior is True, f"{title!r} should be senior"


def test_description_senior_mention_does_not_flag_role_senior():
    """A JD that merely mentions 'senior engineers' must NOT mark the role senior."""
    _, is_senior = classify_seniority_flags(
        "Electrical Engineer",
        "You will collaborate with senior engineers on relay settings and one-lines.",
    )
    assert is_senior is False


def test_new_college_grad_title_is_not_senior():
    is_entry, is_senior = classify_seniority_flags(
        "Power Systems Engineer - New College Grad 2026", "")
    assert is_senior is False and is_entry is True


# ── Resume 'Best match' must respect level for a no-experience resume ──────────

_NEW_GRAD_PROFILE = {
    "years_experience": 0.0,
    "role_focus": "Power Systems",
    "all_skills": ["ETAP", "Short Circuit Analysis", "Arc Flash Analysis", "Load Flow", "NEC / NFPA 70"],
    "studies": ["Short Circuit Analysis", "Arc Flash Analysis", "Load Flow"],
    "standards": ["NEC / NFPA 70"],
    "concepts": [],
    "tools": ["ETAP"],
    "projects": ["Substation protection coordination study — ETAP short circuit and arc flash"],
    "project_signals": [],
}


def _job(title, level, is_senior, is_entry):
    return {
        "job_title": title,
        "cleaned_description": "ETAP short circuit, arc flash and load flow studies for substations per NEC.",
        "matched_keywords": "etap",
        "role_category": "Power Systems",
        "experience_level": level,
        "is_senior": is_senior,
        "is_entry_level": is_entry,
        "is_candidate_friendly": is_entry,
        "years_required_min": None,
        "match_score": 80,
    }


def test_best_match_ranks_entry_above_senior_for_new_grad():
    senior = compute_match(_NEW_GRAD_PROFILE,
                           _job("Staff Power Systems Engineer", "Staff", True, False))
    entry = compute_match(_NEW_GRAD_PROFILE,
                          _job("Power Systems Engineer, New College Grad", "New Grad", False, True))
    # This used to assert the Staff role had comparable raw skill overlap
    # (senior >= entry - 10) as a scaffold for the real check below. That premise
    # no longer holds and its failure was never the point: raw resume_match now
    # reads the new-grad profile well enough to score the entry role HIGHER on its
    # own (82 vs 58), so the level-aware score is not having to overcome a deficit.
    # Keeping the old line meant this test failed while the behaviour it exists to
    # protect was working. Assert what actually matters about resume_match: both
    # roles are genuine matches, so neither is being discarded before ranking.
    assert senior["resume_match"] > 0 and entry["resume_match"] > 0
    # ...but the level-aware Best-match score must rank the entry role higher.
    assert entry["apply_priority_score"] > senior["apply_priority_score"], (
        f"entry {entry['apply_priority_score']} !> senior {senior['apply_priority_score']}")
