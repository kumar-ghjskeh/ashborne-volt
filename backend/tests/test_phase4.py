"""Phase 4: full-text search, watchlists, daily digest, application tracking,
tier-based sync. All tests run against an isolated in-memory SQLite DB and call
the API handler functions directly (no TestClient / no scheduler side-effects)."""

import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parents[2]))

import pytest
from sqlmodel import Session, SQLModel, create_engine

from backend.app import main as M
from backend.app.models import JobPosting
from backend.app.scheduler import TIER_INTERVALS
from backend.app.services.digest import build_digest, _render_html


def _session() -> Session:
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False})
    SQLModel.metadata.create_all(engine)
    return Session(engine)


def _job(**kw) -> JobPosting:
    """A relevant, viewable, active USA job by default. Override per test."""
    base = dict(
        company="Acme", job_title="Design Verification Engineer", apply_url="https://x/y",
        safe_apply_url="https://x/y", cleaned_description="UVM SystemVerilog testbench",
        matched_keywords="uvm, systemverilog", role_category="Design Verification",
        experience_level="Entry Level", state="CA", location="Santa Clara, CA",
        ats_platform="greenhouse", active_status="active", is_usa=True,
        is_software_only=False, is_senior=False, is_entry_level=False,
        company_priority="A", match_score=70, location_confidence=0.9,
        data_quality_score=80, eligibility_risk="",
        first_seen_at=datetime.utcnow(),
    )
    base.update(kw)
    return JobPosting(**base)


def _seed(session, jobs):
    for j in jobs:
        session.add(j)
    session.commit()


# ── 4A: Portable full-text search ────────────────────────────────────────────

def test_search_single_token_matches_title():
    s = _session()
    _seed(s, [
        _job(job_title="Design Verification Engineer"),
        _job(job_title="Analog Layout Engineer", cleaned_description="spice",
             matched_keywords="", role_category="Analog Design"),
    ])
    _, total = M._build_job_query(s, page=1, limit=50, keyword="verification")
    assert total == 1


def test_search_multi_token_is_AND_across_tokens():
    s = _session()
    _seed(s, [
        _job(job_title="UVM AXI Verification", cleaned_description="axi uvm coverage"),
        _job(job_title="UVM PCIe Verification", cleaned_description="pcie uvm coverage"),
    ])
    # Both tokens must appear somewhere → only the AXI job qualifies.
    _, both = M._build_job_query(s, page=1, limit=50, keyword="uvm axi")
    assert both == 1
    _, just_uvm = M._build_job_query(s, page=1, limit=50, keyword="uvm")
    assert just_uvm == 2


def test_search_tokens_match_across_different_fields():
    s = _session()
    # "nvidia" only in company, "formal" only in role_category — a token may match
    # any field, so this single job satisfies both tokens.
    _seed(s, [
        _job(company="NVIDIA", job_title="Engineer", cleaned_description="rtl",
             matched_keywords="", role_category="Formal Verification"),
        _job(company="Intel", role_category="Design Verification"),
    ])
    _, total = M._build_job_query(s, page=1, limit=50, keyword="nvidia formal")
    assert total == 1


def test_search_matches_company_and_state_fields():
    s = _session()
    _seed(s, [_job(company="Cerebras", state="TX", location="Austin, TX")])
    assert M._build_job_query(s, page=1, limit=50, keyword="cerebras")[1] == 1
    assert M._build_job_query(s, page=1, limit=50, keyword="austin")[1] == 1


# ── 4B: Watchlist counts ─────────────────────────────────────────────────────

def test_watchlist_counts_total_and_new():
    s = _session()
    old = datetime.utcnow() - timedelta(days=10)
    _seed(s, [
        _job(state="CA", matched_keywords="uvm", first_seen_at=datetime.utcnow()),   # new
        _job(state="CA", matched_keywords="uvm", first_seen_at=old),                 # old
        _job(state="TX", matched_keywords="uvm", first_seen_at=datetime.utcnow()),   # different state
    ])
    since = datetime.utcnow() - timedelta(hours=24)
    total, new = M._wl_counts(s, {"keyword": "uvm", "state": "CA"}, since)
    assert total == 2          # both CA jobs match the saved filter
    assert new == 1            # only one CA job is newer than `since`


def test_watchlist_ignores_unknown_filter_keys():
    s = _session()
    _seed(s, [_job(state="CA")])
    # bogus keys must be dropped, not crash the query
    total, _ = M._wl_counts(s, {"state": "CA", "totally_made_up": "x"}, datetime.utcnow() - timedelta(hours=1))
    assert total == 1


# ── 4C: Daily digest ─────────────────────────────────────────────────────────

def test_digest_counts_segments():
    s = _session()
    old = datetime.utcnow() - timedelta(days=5)
    _seed(s, [
        _job(company_priority="S", match_score=95),                       # new S-tier + apply-today
        _job(is_entry_level=True, match_score=60),                        # new grad
        _job(match_score=85),                                             # apply-today
        _job(eligibility_risk="high", match_score=88),                   # elig risk + apply-today
        _job(first_seen_at=old, match_score=90),                         # NOT new (old)
        _job(is_software_only=True, match_score=99),                     # excluded (software)
    ])
    d = build_digest(s)
    c = d["counts"]
    assert c["new_24h"] == 4            # 4 fresh, non-software jobs
    assert c["new_stier"] == 1
    assert c["new_entry_level"] == 1
    assert c["eligibility_risk"] == 1
    assert c["apply_today"] >= 3        # the three score>=80 fresh jobs
    # software-only job must never surface
    assert all(j["company"] != "" for j in d["apply_today"])
    # HTML render must not throw and must include the brand header
    assert "Ashborne Silicon" in _render_html(d)


def test_digest_apply_today_excludes_senior():
    s = _session()
    _seed(s, [_job(is_senior=True, match_score=99, job_title="Principal DV Engineer")])
    d = build_digest(s)
    assert d["counts"]["apply_today"] == 0


# ── 4D: Application tracking pipeline ─────────────────────────────────────────

def test_status_update_sets_pipeline_and_autoapplies():
    s = _session()
    j = _job()
    _seed(s, [j])
    M.update_job_status(j.id, M.StatusUpdate(
        application_status="Interview", resume_version_used="DV/UVM v3",
        follow_up_date="2026-07-01", confirmation_id="REQ-42", recruiter_contact="jane@acme.com",
    ), s)
    s.refresh(j)
    assert j.application_status == "Interview"
    assert j.applied_at is not None            # pipeline stage auto-sets applied_at
    assert j.active_status == "applied"
    assert j.resume_version_used == "DV/UVM v3"
    assert j.follow_up_date == "2026-07-01"
    assert j.confirmation_id == "REQ-42"
    assert j.recruiter_contact == "jane@acme.com"


def test_status_update_saved_does_not_autoapply():
    s = _session()
    j = _job()
    _seed(s, [j])
    M.update_job_status(j.id, M.StatusUpdate(application_status="Saved"), s)
    s.refresh(j)
    assert j.applied_at is None
    assert j.active_status == "active"


# ── 4F: Tier-based sync cadence ──────────────────────────────────────────────

def test_tier_intervals_are_ordered_by_priority():
    assert TIER_INTERVALS["S"] < TIER_INTERVALS["A"] < TIER_INTERVALS["B"] < TIER_INTERVALS["C"]
    assert TIER_INTERVALS["S"] == 45
    assert TIER_INTERVALS["C"] == 1440


if __name__ == "__main__":  # pragma: no cover
    sys.exit(pytest.main([__file__, "-v"]))
