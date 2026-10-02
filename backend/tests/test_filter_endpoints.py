"""The same filter contract must apply across /jobs, /jobs/entry-level and
/jobs/resume-matches. Regression: resume-matches and entry-level used to ignore
most filters (company/keyword/level/min-score) — now all three route through the
shared _build_job_query."""

import json
import sys
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parents[2]))

from sqlmodel import Session, SQLModel, create_engine

from backend.app import main as M
from backend.app.models import JobPosting, ResumeProfile


def _job(**kw) -> JobPosting:
    base = dict(
        company="Acme", job_title="Design Verification Engineer", apply_url="https://x/y",
        cleaned_description="UVM SystemVerilog", matched_keywords="uvm",
        role_category="Design Verification", experience_level="New Grad", state="CA",
        location="Santa Clara, CA", ats_platform="greenhouse", active_status="active",
        is_usa=True, is_software_only=False, is_senior=False, is_entry_level=True,
        is_candidate_friendly=False, company_priority="A", match_score=70,
        new_grad_fit=80, experienced_fit=40, location_confidence=0.9,
        first_seen_at=datetime.utcnow(),
    )
    base.update(kw)
    return JobPosting(**base)


def _seed() -> Session:
    eng = create_engine("sqlite://", connect_args={"check_same_thread": False})
    SQLModel.metadata.create_all(eng)
    s = Session(eng)
    s.add_all([
        _job(company="Acme", new_grad_fit=90, remote_status="Remote", role_category="Design Verification"),
        _job(company="Acme", new_grad_fit=70, remote_status="Onsite", role_category="RTL Design"),
        _job(company="Acme", is_senior=True, is_entry_level=False, experience_level="Senior", new_grad_fit=45),
        _job(company="Other", new_grad_fit=85, remote_status="Remote", role_category="Design Verification"),
        _job(company="Acme", is_usa=False, location="Cambridge, United Kingdom",
             location_confidence=0.9, new_grad_fit=88),  # non-US -> must be excluded
    ])
    prof = {"all_skills": ["UVM", "SystemVerilog"], "role_focus": "Design Verification",
            "years_experience": 0.0, "methodologies": ["UVM"], "hdls": ["SystemVerilog"],
            "concepts": [], "tools": [], "projects": [], "project_signals": []}
    s.add(ResumeProfile(is_active=True, profile_json=json.dumps(prof)))
    s.commit()
    return s


def test_company_filter_applies_in_all_tabs():
    s = _seed()
    jobs = M.list_jobs(s, company="Acme", include_senior=True, limit=50)
    assert jobs["items"] and all(j.company == "Acme" for j in jobs["items"])
    entry = M.entry_level_jobs(s, company="Acme", limit=50)
    assert entry["items"] and all(j.company == "Acme" for j in entry["items"])
    # Resume Matches previously ignored company entirely — must now respect it.
    rm = M.resume_matches(s, company="Acme", include_senior=True, limit=50)
    assert rm["items"] and all(it["company"] == "Acme" for it in rm["items"])


def test_usa_gate_in_all_tabs_excludes_uk():
    s = _seed()
    for items in (M.list_jobs(s, include_senior=True, limit=50)["items"],
                  M.entry_level_jobs(s, limit=50)["items"]):
        assert all("United Kingdom" not in (j.location or "") for j in items)
    rm = M.resume_matches(s, include_senior=True, limit=50)
    assert all("United Kingdom" not in (it.get("location") or "") for it in rm["items"])


def test_min_score_on_new_grad_fit_in_entry_and_resume():
    s = _seed()
    entry = M.entry_level_jobs(s, min_score=85, limit=50)
    assert all(j.new_grad_fit >= 85 for j in entry["items"])
    rm = M.resume_matches(s, min_score=85, include_senior=True, limit=50)
    assert all(it["new_grad_fit"] >= 85 for it in rm["items"])


def test_entry_level_excludes_senior_and_sort_works():
    s = _seed()
    entry = M.entry_level_jobs(s, sort_by="new_grad_fit", limit=50)
    assert all(not j.is_senior for j in entry["items"])           # entry gate holds
    fits = [j.new_grad_fit for j in entry["items"]]
    assert fits == sorted(fits, reverse=True)                     # sort honoured


def test_resume_matches_keyword_and_sort():
    s = _seed()
    rm = M.resume_matches(s, keyword="nonexistent-xyz", include_senior=True, limit=50)
    assert rm["total_count"] == 0                                 # keyword actually filters
    ng = M.resume_matches(s, sort="new_grad_fit", include_senior=True, limit=50)
    fits = [it["new_grad_fit"] for it in ng["items"]]
    assert fits == sorted(fits, reverse=True)


# ── COMBINED filters must AND together identically on every tab ────────────────

def test_combined_company_and_remote_all_tabs():
    s = _seed()
    # Acme + Remote -> only Acme remote jobs, on every tab.
    j = M.list_jobs(s, company="Acme", remote="Remote", include_senior=True, limit=50)["items"]
    assert j and all(x.company == "Acme" and "remote" in (x.remote_status or "").lower() for x in j)
    e = M.entry_level_jobs(s, company="Acme", remote="Remote", limit=50)["items"]
    assert all(x.company == "Acme" and "remote" in (x.remote_status or "").lower() for x in e)
    r = M.resume_matches(s, company="Acme", remote="Remote", include_senior=True, limit=50)["items"]
    assert all(x["company"] == "Acme" and "remote" in (x.get("remote_status") or "").lower() for x in r)


def test_combined_minscore_and_role_all_tabs():
    s = _seed()
    for items in (M.list_jobs(s, min_score=80, role_category="Verification", include_senior=True, limit=50)["items"],
                  M.entry_level_jobs(s, min_score=80, role_category="Verification", limit=50)["items"]):
        assert all((x.new_grad_fit or 0) >= 80 and "verification" in (x.role_category or "").lower() for x in items)
    r = M.resume_matches(s, min_score=80, role_category="Verification", include_senior=True, limit=50)["items"]
    assert all((x["new_grad_fit"] or 0) >= 80 and "verification" in (x.get("role_category") or "").lower() for x in r)


def test_resume_sorts_each_reorder_distinctly():
    s = _seed()
    for sort, key in (("new_grad_fit", "new_grad_fit"), ("resume_match", "resume_match")):
        items = M.resume_matches(s, sort=sort, include_senior=True, limit=50)["items"]
        vals = [it[key] for it in items]
        assert vals == sorted(vals, reverse=True), f"{sort} not descending: {vals}"


def test_list_jobs_sort_by_options_work():
    s = _seed()
    for sort_by, attr in (("new_grad_fit", "new_grad_fit"), ("match_score", "match_score")):
        items = M.list_jobs(s, sort_by=sort_by, include_senior=True, limit=50)["items"]
        vals = [getattr(j, attr) for j in items]
        assert vals == sorted(vals, reverse=True), f"{sort_by} not descending"


def test_counts_match_list_total_across_tabs():
    """The total_count a tab reports must equal the number of items it would return
    unfiltered (no silent count/list divergence)."""
    s = _seed()
    for fn in (lambda: M.list_jobs(s, include_senior=True, limit=500),
               lambda: M.entry_level_jobs(s, limit=500)):
        d = fn()
        assert d["total_count"] == len(d["items"])
    rm = M.resume_matches(s, include_senior=True, limit=500)
    assert rm["total_count"] == len(rm["items"])
