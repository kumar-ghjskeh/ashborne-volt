"""Exercise EVERY filter against the real production data using the live query
builder (_build_job_query) and the resume-match sort, asserting correctness like
a human clicking through the UI. Read-only (SELECT only). Prints PASS/FAIL per
filter so there are no false test passes.

    DATABASE_URL="<render external url>" py -m backend.scripts.audit_all_filters
"""

from __future__ import annotations

import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

if __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from sqlmodel import Session  # noqa: E402

from backend.app import main as M  # noqa: E402
from backend.app.database import engine  # noqa: E402
from backend.app.models import JobPosting  # noqa: E402

PASS, FAIL = 0, 0


def check(name: str, ok: bool, detail: str = "") -> None:
    global PASS, FAIL
    if ok:
        PASS += 1
        print(f"  PASS  {name}")
    else:
        FAIL += 1
        print(f"  FAIL  {name}  -- {detail}")


def main() -> None:
    s = Session(engine)
    print("=== SENIORITY CHIPS (each must return EXACTLY its level) ===")
    for lv in ["New Grad", "Entry Level", "Junior", "Associate", "Mid-Level",
               "Senior", "Staff", "Principal", "Lead", "Manager"]:
        items, n = M._build_job_query(s, page=1, limit=500, level_filter=lv,
                                      include_senior=True, usa_only=False)
        wrong = [j.job_title for j in items if j.experience_level != lv]
        check(f"chip {lv} (n={n})", not wrong, f"{len(wrong)} wrong, e.g. {wrong[:2]}")

    print("\n=== New Grad vs Entry Level must be DISJOINT sets ===")
    ng, _ = M._build_job_query(s, page=1, limit=500, level_filter="New Grad", include_senior=True, usa_only=False)
    el, _ = M._build_job_query(s, page=1, limit=500, level_filter="Entry Level", include_senior=True, usa_only=False)
    ng_ids, el_ids = {j.id for j in ng}, {j.id for j in el}
    check("New Grad ∩ Entry Level == empty", not (ng_ids & el_ids), f"overlap {len(ng_ids & el_ids)}")

    print("\n=== SENIOR GATE (default excludes is_senior) ===")
    items, n = M._build_job_query(s, page=1, limit=500, include_senior=False, usa_only=False)
    check("default gate: no is_senior", all(not j.is_senior for j in items),
          f"{sum(1 for j in items if j.is_senior)} senior leaked")
    items, n = M._build_job_query(s, page=1, limit=500, include_senior=True, usa_only=False)
    check("include_senior=True returns senior too", any(j.is_senior for j in items))

    print("\n=== USA gate ===")
    items, _ = M._build_job_query(s, page=1, limit=900, usa_only=True, include_senior=True)
    bad = [j.location for j in items if not (j.is_usa or (j.location_confidence or 0) == 0)]
    check("usa_only: only USA or unknown-location", not bad, f"{len(bad)} foreign leaked, e.g. {bad[:2]}")

    print("\n=== POSTED WITHIN (must use posted_date, not first_seen_at) ===")
    counts = {}
    for h in (24, 168, 720, 2160):
        _, n = M._build_job_query(s, page=1, limit=1, posted_within_hours=h,
                                  include_senior=True, usa_only=False)
        counts[h] = n
    mono = counts[24] <= counts[168] <= counts[720] <= counts[2160]
    check(f"monotonic by window {counts}", mono)
    items, _ = M._build_job_query(s, page=1, limit=500, posted_within_hours=720,
                                  include_senior=True, usa_only=False)
    cutoff = datetime.now(timezone.utc) - timedelta(hours=720)
    def _aware(d):
        return d if d.tzinfo else d.replace(tzinfo=timezone.utc)
    bad = [j.job_title for j in items if j.posted_date and _aware(j.posted_date) < cutoff]
    check("all within window actually posted in window", not bad, f"{len(bad)} too old")
    nulls = [j for j in items if not j.posted_date]
    check("posted-within excludes unknown posted_date", not nulls, f"{len(nulls)} NULL leaked")

    print("\n=== MIN SCORE (re-based on New Grad Fit) ===")
    items, _ = M._build_job_query(s, page=1, limit=500, min_score=75, include_senior=True, usa_only=False)
    bad = [j.new_grad_fit for j in items if (j.new_grad_fit or 0) < 75]
    check("min_score=75: all new_grad_fit>=75", not bad, f"{len(bad)} below")

    print("\n=== STATE / REMOTE / ROLE / COMPANY / KEYWORD ===")
    items, _ = M._build_job_query(s, page=1, limit=500, state="CA", include_senior=True, usa_only=False)
    bad = [j.state for j in items if (j.state or "").upper() != "CA"]
    check("state=CA: all CA", not bad, f"{len(bad)} non-CA, e.g. {bad[:3]}")

    items, _ = M._build_job_query(s, page=1, limit=500, remote="Remote", include_senior=True, usa_only=False)
    bad = [j.remote_status for j in items if "remote" not in (j.remote_status or "").lower()]
    check("remote=Remote: all remote", not bad, f"{len(bad)} non-remote")

    items, _ = M._build_job_query(s, page=1, limit=500, role_category="Verification", include_senior=True, usa_only=False)
    bad = [j.role_category for j in items if "verification" not in (j.role_category or "").lower()]
    check("role=Verification: all verification", not bad, f"{len(bad)} off-role")

    items, _ = M._build_job_query(s, page=1, limit=500, keyword="UVM", include_senior=True, usa_only=False)
    def _has_kw(j):
        # Mirror the filter: substring in high-signal fields, OR whole-word in the
        # free-text description / snippet.
        substr = " ".join([j.job_title or "", j.normalized_title or "", j.company or "",
                            j.matched_keywords or "", j.role_category or "",
                            j.experience_level or "", j.state or "", j.location or "",
                            j.ats_platform or ""]).lower()
        if "uvm" in substr:
            return True
        for f in (j.cleaned_description or "", j.description_snippet or ""):
            if " uvm " in f" {f.lower()} ":
                return True
        return False
    bad = [j.job_title for j in items if not _has_kw(j)]
    check(f"keyword=UVM (n={len(items)}): all genuinely contain uvm", not bad, f"{len(bad)} missing, e.g. {bad[:3]}")

    # pick a real company present in data
    any_co = s.exec(__import__("sqlmodel").select(JobPosting.company)).first()
    if any_co:
        items, _ = M._build_job_query(s, page=1, limit=500, company=any_co, include_senior=True, usa_only=False)
        bad = [j.company for j in items if j.company != any_co]
        check(f"company={any_co}: all match", not bad, f"{len(bad)} other")

    print("\n=== RESUME 'BEST MATCH' SORT respects level (no senior at top) ===")
    profile = M._current_profile(s)
    if profile:
        from backend.app.resume_match import compute_match
        conds = [JobPosting.active_status == "active",
                 (JobPosting.is_usa == True) | (JobPosting.location_confidence == 0.0),
                 JobPosting.is_software_only == False]
        jobs = s.exec(__import__("sqlmodel").select(JobPosting).where(*conds)).all()
        scored = []
        for job in jobs:
            m = compute_match(profile, M._job_match_input(job))
            scored.append({"title": job.job_title, "rm": m["resume_match"],
                           "ng": m["new_grad_fit"], "sen": job.is_senior,
                           "aps": m["apply_priority_score"]})
        scored.sort(key=lambda it: (it["aps"], it["rm"]), reverse=True)
        top10 = scored[:10]
        senior_in_top = [it["title"] for it in top10 if it["sen"]]
        check("no is_senior job in resume Best-match top 10", not senior_in_top,
              f"{senior_in_top}")
        print("   Top 6 (best match):")
        for it in scored[:6]:
            print(f"     {it['title'][:46]:46} rm={it['rm']} ng={it['ng']} aps={it['aps']} sen={it['sen']}")

    s.close()
    print(f"\n==== {PASS} passed, {FAIL} failed ====")
    sys.exit(1 if FAIL else 0)


if __name__ == "__main__":
    main()
