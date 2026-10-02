"""Résumé parsing and the match engine (incl. safe-tailoring tiers), EE edition."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parents[2]))

from backend.app import taxonomy as tx
from backend.app.resume_match import compute_match
from backend.app.resume_parser import parse_resume

SAMPLE = (
    b"Jordan Lee\n"
    b"BS Electrical Engineering, Expected May 2026\n"
    b"EIT certified (passed FE exam)\n"
    b"Skills: ETAP, AutoCAD Electrical, MATLAB, Python, short circuit and arc flash studies, "
    b"load flow, protective relay settings, NEC, IEEE 1584, DNP3, substation one-line diagrams\n"
    b"Projects:\n"
    b"- Substation Protection Coordination Study for a 69 kV distribution substation\n"
    b"- Solar PV Microgrid Design with battery storage\n"
    b"- Three-phase Inverter Control in Simulink\n"
    b"Experience: Power Systems Engineering Intern\n"
)


def _profile():
    return parse_resume(SAMPLE, "resume.txt").to_dict()


def test_parse_skills_and_focus():
    p = parse_resume(SAMPLE, "resume.txt")
    for skill in ("ETAP", "Short Circuit Analysis", "Arc Flash Analysis", "Load Flow",
                  "NEC / NFPA 70", "IEEE 1584", "DNP3", "Single-Line Diagrams"):
        assert skill in p.all_skills, skill
    assert p.degree == "BS"
    assert "EIT / FE" in p.licenses
    assert p.role_focus == tx.POWER
    assert len(p.projects) >= 2


def _job(**kw):
    base = {"match_score": 80, "is_candidate_friendly": True, "eligibility_risk": "low",
            "sponsors_h1b": True, "is_fresh": True, "matched_keywords": ""}
    base.update(kw)
    return base


def test_match_power_job_has_matched_skills():
    job = _job(
        job_title="Protection & Controls Engineer",
        cleaned_description=("Perform short circuit, arc flash and coordination studies in ETAP; "
                             "develop protective relay settings; DNP3 SCADA integration; NEC and IEEE 1584."),
        role_category=tx.POWER,
    )
    m = compute_match(_profile(), job)
    assert "ETAP" in m["matched_skills"] and "Arc Flash Analysis" in m["matched_skills"]
    assert m["resume_match"] > 0
    assert m["recommended_resume"] == f"{tx.POWER} Résumé"
    assert m["interview_prep"]["technical_topics"]
    assert m["interview_prep"]["rounds"]


def test_tailoring_never_fabricates_tools():
    """A tool the résumé has never used must never be Safe to Add."""
    job = _job(
        job_title="Transmission Planning Engineer",
        cleaned_description="Run PSS/E steady-state and dynamic studies; PSCAD EMT modelling.",
        role_category=tx.POWER, is_candidate_friendly=False,
    )
    m = compute_match(_profile(), job)
    psse = [s for s in m["tailoring_suggestions"] if s["skill"] == "PSS/E"]
    assert psse, "PSS/E should appear as a missing skill"
    assert psse[0]["tier"] in ("Do Not Add", "Learn First")


def test_reword_for_equivalent_skill():
    """Protective Device Coordination missing but ETAP present → Reword Only."""
    job = _job(
        job_title="Power Systems Engineer",
        cleaned_description="Protective device coordination and TCC curves for industrial clients.",
        role_category=tx.POWER,
    )
    m = compute_match(_profile(), job)
    coord = [s for s in m["tailoring_suggestions"] if s["skill"] == "Protective Device Coordination"]
    if coord:
        assert coord[0]["tier"] == "Reword Only"


def test_matched_projects_detected():
    job = _job(
        job_title="Renewable Energy Engineer",
        cleaned_description="Design solar PV plants with battery energy storage and microgrid controls.",
        role_category=tx.ENERGY,
    )
    m = compute_match(_profile(), job)
    assert len(m["matched_projects"]) >= 1


def test_domain_alignment_neighbours():
    p = _profile()
    same = compute_match(p, _job(job_title="Substation Engineer", cleaned_description="substation",
                                 role_category=tx.POWER), lite=True)
    far = compute_match(p, _job(job_title="Antenna Engineer", cleaned_description="antenna HFSS",
                                role_category=tx.RF), lite=True)
    assert same["match_breakdown"]["domain"] > far["match_breakdown"]["domain"]
