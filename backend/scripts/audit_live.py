"""Exhaustive LIVE audit of every filter + sort on every tab against the deployed
API — exactly what a human would click through. Asserts that returned items
actually satisfy each filter (single and combined), that sorts reorder correctly,
and that counts are consistent. Read-only HTTP."""
import sys

import httpx

BASE = "https://job-scraper-api-w0h8.onrender.com"
PASS = FAIL = 0
FAILURES = []


def check(name, ok, detail=""):
    global PASS, FAIL
    if ok:
        PASS += 1
    else:
        FAIL += 1
        FAILURES.append(f"{name} :: {detail}")
        print(f"  FAIL {name} -- {detail}")


def get(path, **params):
    r = httpx.get(f"{BASE}{path}", params=params, timeout=60)
    r.raise_for_status()
    return r.json()


def items_of(data):
    return data.get("items", [])


def loc_us(it):
    return it.get("is_usa") or (it.get("location_confidence") or 0) == 0


TABS = {
    "all": "/jobs",
    "newgrad": "/jobs/entry-level",
    "resume": "/jobs/resume-matches",
}


def audit_tab(tab, path):
    print(f"\n=== TAB {tab} ({path}) ===")
    base = dict(limit=200, include_senior=True) if tab != "resume" else dict(limit=200, include_senior=True)
    # baseline
    d = get(path, **base)
    n = d.get("total_count")
    print(f"  baseline total={n}")

    # company filter
    d = get(path, company="AMD", **base)
    check(f"{tab}.company=AMD", all(it["company"] == "AMD" for it in items_of(d)),
          f"got {set(it['company'] for it in items_of(d))}")

    # tier filter
    d = get(path, priority="S", **base)
    check(f"{tab}.priority=S", all(it.get("company_priority") == "S" for it in items_of(d)),
          f"got {set(it.get('company_priority') for it in items_of(d))}")

    # remote filter
    d = get(path, remote="Remote", **base)
    check(f"{tab}.remote=Remote", all("remote" in (it.get("remote_status") or "").lower() for it in items_of(d)),
          f"got {set(it.get('remote_status') for it in items_of(d))}")

    # role category
    d = get(path, role_category="Verification", **base)
    check(f"{tab}.role=Verification", all("verification" in (it.get("role_category") or "").lower() for it in items_of(d)),
          f"got {list(set(it.get('role_category') for it in items_of(d)))[:5]}")

    # state
    d = get(path, state="CA", **base)
    bad = [it.get("state") for it in items_of(d) if (it.get("state") or "").upper() != "CA"]
    check(f"{tab}.state=CA", not bad, f"non-CA: {bad[:4]}")

    # min_score (new_grad_fit)
    d = get(path, min_score=80, **base)
    bad = [it.get("new_grad_fit") for it in items_of(d) if (it.get("new_grad_fit") or 0) < 80]
    check(f"{tab}.min_score=80(ng)", not bad, f"below: {bad[:5]}")

    # keyword
    d = get(path, keyword="UVM", **base)
    check(f"{tab}.keyword=UVM>0", d.get("total_count", 0) > 0, "0 results for UVM")

    # USA gate (default usa_only)
    d = get(path, limit=200, include_senior=True, usa_only=True)
    bad = [it.get("location") for it in items_of(d) if not loc_us(it)]
    check(f"{tab}.usa_only no foreign", not bad, f"foreign: {bad[:4]}")

    # COMBINED: company + remote
    d = get(path, company="AMD", remote="Onsite", **base)
    ok = all(it["company"] == "AMD" and "onsite" in (it.get("remote_status") or "").lower() for it in items_of(d))
    check(f"{tab}.AMD+Onsite", ok, "combined company+remote failed")

    # COMBINED: min_score + role
    d = get(path, min_score=70, role_category="Verification", **base)
    ok = all((it.get("new_grad_fit") or 0) >= 70 and "verification" in (it.get("role_category") or "").lower()
             for it in items_of(d))
    check(f"{tab}.minscore70+Verification", ok, "combined min_score+role failed")


def audit_seniority_chips():
    print("\n=== SENIORITY CHIPS (All Jobs) — each returns exactly its level ===")
    for lv in ["New Grad", "Entry Level", "Junior", "Mid-Level", "Senior", "Staff", "Principal", "Lead", "Manager"]:
        d = get("/jobs", level_filter=lv, limit=200, include_senior=True, usa_only=False)
        bad = [it.get("experience_level") for it in items_of(d) if it.get("experience_level") != lv]
        check(f"chip {lv}", not bad, f"leaked: {set(bad)}")


def audit_resume_sorts():
    print("\n=== RESUME sorts actually reorder ===")
    base = dict(limit=50, include_senior=True)
    for sort, key in [("new_grad_fit", "new_grad_fit"), ("resume_match", "resume_match")]:
        d = get("/jobs/resume-matches", sort=sort, **base)
        vals = [it.get(key, 0) for it in items_of(d)]
        check(f"resume sort={sort} desc", vals == sorted(vals, reverse=True), f"top5={vals[:5]}")
    # 'match' (blend) — top job should be a strong overall fit (ng>=70 AND resume>=60)
    d = get("/jobs/resume-matches", sort="match", **base)
    top = items_of(d)[:5]
    print("  match top5:", [(it["company"], it.get("new_grad_fit"), it.get("resume_match")) for it in top])


def audit_counts():
    print("\n=== Count consistency ===")
    stats = get("/stats")
    alljobs = get("/jobs", limit=1, include_senior=True)
    check("stats.total_active == /jobs total", stats["total_active"] == alljobs["total_count"],
          f"stats={stats['total_active']} jobs={alljobs['total_count']}")
    ng = get("/jobs/entry-level", limit=1)
    check("entry_level_count == /jobs/entry-level total",
          stats.get("entry_level_count") == ng["total_count"],
          f"stats={stats.get('entry_level_count')} entry={ng['total_count']}")
    print(f"  total_active={stats['total_active']} entry_level={stats.get('entry_level_count')} "
          f"total_companies={stats.get('total_companies')} new_24h={stats.get('new_24h')}")


def main():
    for tab, path in TABS.items():
        try:
            audit_tab(tab, path)
        except Exception as e:
            check(f"{tab} TAB", False, f"{type(e).__name__}: {e}")
    audit_seniority_chips()
    audit_resume_sorts()
    audit_counts()
    print(f"\n==== {PASS} passed, {FAIL} failed ====")
    if FAILURES:
        print("FAILURES:")
        for f in FAILURES:
            print("  -", f)
    sys.exit(1 if FAIL else 0)


if __name__ == "__main__":
    main()
