"""Phase 5: seniority-filter remap, keyword senior-gate lift, multi-resume
activation, and the applications CSV export. Isolated in-memory DB; handlers
called directly (no TestClient / scheduler)."""

import sys
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parents[2]))

import json

from sqlmodel import Session, SQLModel, create_engine

from backend.app import main as M
from backend.app.models import JobPosting, ResumeProfile


def _session() -> Session:
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False})
    SQLModel.metadata.create_all(engine)
    return Session(engine)


def _job(**kw) -> JobPosting:
    base = dict(
        company="Acme", job_title="Design Verification Engineer", apply_url="https://x/y",
        safe_apply_url="https://x/y", cleaned_description="UVM SystemVerilog", matched_keywords="uvm",
        role_category="Design Verification", experience_level="Unknown", state="CA",
        location="Santa Clara, CA", ats_platform="greenhouse", active_status="active",
        is_usa=True, is_software_only=False, is_senior=False, is_entry_level=False,
        is_candidate_friendly=False, company_priority="A", match_score=70, location_confidence=0.9,
        data_quality_score=80, first_seen_at=datetime.utcnow(),
    )
    base.update(kw)
    return JobPosting(**base)


def _seed(s, jobs):
    for j in jobs:
        s.add(j)
    s.commit()


# ── Seniority filter remap (the Entry Level / Junior = 0 bug) ────────────────

def test_entry_level_chip_is_exact():
    """Each seniority chip returns EXACTLY its level. The "Entry Level" chip must
    NOT pull in New Grad (a separate chip) or Unknown-but-flagged jobs — that
    lumping was the bug. The broad entry+candidate-friendly pool lives in the
    New Grad TAB (/jobs/entry-level), not the chip."""
    s = _session()
    _seed(s, [
        _job(experience_level="Entry Level", is_entry_level=True),  # the only match
        _job(experience_level="New Grad", is_entry_level=True),     # different chip
        _job(experience_level="Senior", is_senior=True),           # not entry
    ])
    items, n = M._build_job_query(s, page=1, limit=50, level_filter="Entry Level")
    assert n == 1 and all(j.experience_level == "Entry Level" for j in items)


def test_junior_chip_is_exact():
    s = _session()
    _seed(s, [
        _job(experience_level="Junior", is_candidate_friendly=True),  # the only match
        _job(experience_level="Unknown", is_candidate_friendly=True),  # candidate-friendly != Junior
        _job(experience_level="Senior", is_senior=True),              # excluded
    ])
    items, n = M._build_job_query(s, page=1, limit=50, level_filter="Junior")
    assert n == 1 and all(j.experience_level == "Junior" for j in items)


# ── Keyword search lifts the non-senior gate ─────────────────────────────────

def test_keyword_search_includes_senior_roles():
    s = _session()
    _seed(s, [
        _job(company="Marvell", job_title="DV Engineer", is_senior=False),
        _job(company="Marvell", job_title="Principal DV Engineer", is_senior=True),
    ])
    # default (no keyword) → senior excluded
    _, plain = M._build_job_query(s, page=1, limit=50)
    assert plain == 1
    # keyword search → both, senior included
    _, searched = M._build_job_query(s, page=1, limit=50, keyword="marvell")
    assert searched == 2


# ── Multi-resume activation ──────────────────────────────────────────────────

def test_activate_switches_active_resume():
    s = _session()
    a = ResumeProfile(filename="a", label="DV/UVM", is_active=True,
                      profile_json=json.dumps({"all_skills": ["uvm"]}))
    b = ResumeProfile(filename="b", label="RTL", is_active=False,
                      profile_json=json.dumps({"all_skills": ["verilog"]}))
    s.add(a); s.add(b); s.commit(); s.refresh(a); s.refresh(b)

    assert M._active_resume(s).id == a.id
    M.activate_resume(b.id, s)
    assert M._active_resume(s).id == b.id
    # exactly one active
    actives = [r for r in (a, b) if (s.refresh(r) or r.is_active)]
    assert len(actives) == 1
    # resume_id override resolves a specific (non-active) profile
    assert M._current_profile(s, a.id) == {"all_skills": ["uvm"]}


def test_delete_active_promotes_another():
    s = _session()
    a = ResumeProfile(filename="a", is_active=True, profile_json="{}")
    b = ResumeProfile(filename="b", is_active=False, profile_json="{}")
    s.add(a); s.add(b); s.commit(); s.refresh(a)
    M.delete_resume_one(a.id, s)
    assert M._active_resume(s) is not None      # b auto-promoted
    assert M._active_resume(s).filename == "b"


# ── Applications CSV export ──────────────────────────────────────────────────

def test_csv_export_contains_tracked_jobs():
    s = _session()
    _seed(s, [
        _job(company="Etched", active_status="applied", application_status="Interview"),
        _job(company="MatX", active_status="saved"),
        _job(company="NVIDIA", active_status="active"),   # untouched → excluded
    ])
    resp = M.export_applications(s)
    body = resp.body.decode() if isinstance(resp.body, (bytes, bytearray)) else str(resp.body)
    assert "Company,Title" in body          # header
    assert "Etched" in body and "MatX" in body
    assert "NVIDIA" not in body             # untouched job excluded
