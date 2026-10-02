"""The static corpus: shard merging, stable ids, chunked details, health counters.

Each test pins a failure mode that cost Ashborne Silicon real outages or wrong
numbers. No network; the config is replaced with a tiny in-memory catalog.
"""

from __future__ import annotations

import inspect
import json
from datetime import datetime, timedelta, timezone

import pytest

from backend.app import config as app_config
from backend.app import snapshot
from backend.app.scrape_engine import EMPTY_STALL_THRESHOLD, ERROR_QUARANTINE_THRESHOLD

NOW = datetime(2026, 10, 1, 12, tzinfo=timezone.utc)
CATALOG = [
    {"name": "Grid Co", "category": "Utility", "priority": "A", "sector": "Utility",
     "careers_url": "https://grid.example/careers", "ats_platform": "workday"},
    {"name": "Volt OEM", "category": "OEM", "priority": "S", "sector": "OEM",
     "careers_url": "https://oem.example/careers", "ats_platform": "greenhouse"},
]


@pytest.fixture(autouse=True)
def _catalog(monkeypatch):
    monkeypatch.setattr(app_config, "load_all_companies", lambda: [dict(c) for c in CATALOG])


def _row(company, title, jid, seen=NOW, status="active", **kw):
    key = snapshot.make_fingerprint(company, title, "Raleigh, NC", jid, "")
    row = {"key": key, "id": snapshot.stable_id(key), "company": company, "job_title": title,
           "location": "Raleigh, NC", "job_id_from_company": jid, "apply_url": f"https://x/{jid}",
           "active_status": status, "last_seen_at": seen.isoformat(), "first_seen_at": seen.isoformat(),
           "is_usa": True, "location_confidence": 0.9, "role_category": "Power Systems",
           "dup_group": key[:12]}
    row.update(kw)
    return row


def _shard(companies, jobs=(), state=(), details=None, health=None, runs=()):
    return {"schema": snapshot.SCHEMA, "companies": companies, "jobs": list(jobs),
            "state": list(state), "details": details or {}, "health": health or {}, "runs": list(runs)}


# ── merge semantics ──────────────────────────────────────────────────────────

def test_shard_is_authoritative_for_its_companies():
    """A posting the shard no longer reports must NOT come back from the old file.
    Union-merging resurrected retired rows forever on Ashborne Silicon."""
    old = _row("Grid Co", "Substation Engineer", "1")
    kept_other = _row("Volt OEM", "Power Electronics Engineer", "9")
    published = {"jobs": [old, kept_other], "state": [], "details": {}, "companies": [], "runs": []}
    fresh = _row("Grid Co", "Protection Engineer", "2")
    merged = snapshot.merge_shards(published, [_shard(["Grid Co"], jobs=[fresh])], now=NOW)
    titles = {r["job_title"] for r in merged["jobs"]}
    assert titles == {"Protection Engineer", "Power Electronics Engineer"}


def test_failed_shard_leaves_previous_rows_live():
    """A shard that produced no file is simply absent; its companies keep their rows."""
    published = {"jobs": [_row("Grid Co", "Substation Engineer", "1")], "state": [],
                 "details": {}, "companies": [], "runs": []}
    merged = snapshot.merge_shards(published, [_shard(["Volt OEM"])], now=NOW)
    assert [r["job_title"] for r in merged["jobs"]] == ["Substation Engineer"]


def test_unscraped_company_goes_stale_then_is_purged():
    stale = _row("Grid Co", "Distribution Engineer", "3", seen=NOW - timedelta(days=snapshot.STALE_DAYS + 1))
    published = {"jobs": [stale], "state": [], "details": {}, "companies": [], "runs": []}
    merged = snapshot.merge_shards(published, [], now=NOW)
    assert merged["jobs"] == []
    assert merged["state"][0]["active_status"] == "removed"

    later = NOW + timedelta(days=snapshot.PURGE_DAYS + 1)
    again = snapshot.merge_shards({**merged, "companies": []}, [], now=later)
    assert again["state"] == [], "a long-retired row must eventually be forgotten"


def test_company_dropped_from_config_disappears():
    published = {"jobs": [_row("Gone Inc", "Electrical Engineer", "5")], "state": [],
                 "details": {}, "companies": [], "runs": []}
    assert snapshot.merge_shards(published, [], now=NOW)["jobs"] == []


def test_runs_are_unioned_by_identity_not_id():
    r1 = {"triggered_by": "static", "started_at": "2026-10-01T01:00:00+00:00"}
    r2 = {"triggered_by": "browser", "started_at": "2026-10-01T01:00:00+00:00"}
    published = {"jobs": [], "state": [], "details": {}, "companies": [], "runs": [r1]}
    merged = snapshot.merge_shards(published, [_shard([], runs=[r1, r2])], now=NOW)
    assert len(merged["runs"]) == 2


# ── ids, details, payload ────────────────────────────────────────────────────

def test_ids_are_stable_and_js_safe():
    key = snapshot.make_fingerprint("Grid Co", "Substation Engineer", "Raleigh, NC", "1", "")
    assert snapshot.stable_id(key) == snapshot.stable_id(key)
    assert snapshot.stable_id(key) < 2 ** 53


def test_published_roundtrip_with_chunked_details(tmp_path):
    rows = [_row("Grid Co", f"Engineer {i}", str(i)) for i in range(40)]
    details = {str(r["id"]): f"body {i}" for i, r in enumerate(rows)}
    retired = _row("Grid Co", "Old Role", "99", status="removed", removed_at=NOW.isoformat())
    corpus = {"jobs": rows, "state": [retired], "details": details,
              "health": {"Grid Co": {"scrape_error_count": 0}}, "companies": [], "runs": []}
    report = snapshot.write_published(tmp_path, corpus)
    assert report["count"] == 40
    chunks = list((tmp_path / "details").glob("*.json"))
    assert len(chunks) == snapshot.DETAIL_CHUNKS
    back = snapshot.read_published(tmp_path)
    assert back["details"] == details
    assert len(back["state"]) == 1
    jobs_json = json.loads((tmp_path / "jobs.json").read_text(encoding="utf-8"))
    # Retired rows never reach the browser payload.
    assert all(r["job_title"] != "Old Role" for r in jobs_json["jobs"])
    # Every published body sits in the chunk its id maps to.
    for jid in details:
        chunk = json.loads((tmp_path / "details" / f"{snapshot.detail_chunk(jid):02d}.json").read_text())
        assert jid in chunk["descriptions"]


def test_unique_count_collapses_duplicate_groups(tmp_path):
    a = _row("Grid Co", "Electrical Engineer II", "1", dup_group="g1")
    b = _row("Grid Co", "Electrical Engineer II", "2", dup_group="g1", location="Durham, NC")
    c = _row("Grid Co", "Electrical Engineer II", "3", dup_group="g2")
    report = snapshot.write_published(tmp_path, {"jobs": [a, b, c], "state": [], "details": {},
                                                 "health": {}, "companies": [], "runs": []})
    assert report["count"] == 3 and report["unique"] == 2


def test_dup_group_separates_different_teams_with_the_same_title():
    a = snapshot.dup_group_key("Grid Co", "electrical engineer ii", "Design substations, req 2026-114.")
    b = snapshot.dup_group_key("Grid Co", "electrical engineer ii", "Design substations, req 2027-981.")
    other = snapshot.dup_group_key("Grid Co", "electrical engineer ii", "Program PLCs for water plants.")
    assert a == b, "requisition numbers and dates alone must not split one opening"
    assert a != other, "two teams sharing a generic title are two openings"


# ── health counters ──────────────────────────────────────────────────────────

def test_health_drives_status_and_stall_is_not_quarantine(tmp_path):
    corpus = {"jobs": [], "state": [], "details": {}, "companies": [], "runs": [],
              "health": {"Grid Co": {"scrape_error_count": ERROR_QUARANTINE_THRESHOLD + 1},
                         "Volt OEM": {"consecutive_empty_scrapes": EMPTY_STALL_THRESHOLD + 3}}}
    snapshot.write_published(tmp_path, corpus)
    companies = {c["name"]: c for c in json.loads((tmp_path / "jobs.json").read_text())["companies"]}
    assert companies["Grid Co"]["scrape_status"] == "quarantined"
    assert companies["Volt OEM"]["scrape_status"] == "stalled"
    assert companies["Volt OEM"]["quarantined"] is False


def test_shard_refuses_to_publish_after_total_failure():
    """Writing a shard after every company failed would mark every posting missed."""
    from backend.app import run_static
    src = inspect.getsource(run_static._run)
    assert src.index("no company scraped successfully") < src.index("write_shard(")


def test_runners_share_one_health_recorder():
    from backend.app import run_browser_scrape, run_cf_scrape, scrape_engine
    for mod in (scrape_engine.run_scrape, run_cf_scrape.main, run_browser_scrape.run_browser_scrape):
        assert "record_company_outcome" in inspect.getsource(mod), mod.__name__
