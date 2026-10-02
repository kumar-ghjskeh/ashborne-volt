"""Read-only production diagnostic. Confirms (1) why senior roles leak into the
New Grad / entry-level tab, (2) the USA / software / count breakdown behind the
dashboard-vs-data-health discrepancy, (3) how many stored classification flags
are stale vs. a fresh re-classification, and (4) posted_date coverage (needed for
the 'Posted Within' filter to be accurate).

    DATABASE_URL="<render external url>" py -m backend.scripts.diagnose_filters
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

if __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from sqlmodel import Session, select  # noqa: E402

from backend.app.database import engine  # noqa: E402
from backend.app.models import JobPosting  # noqa: E402
from backend.app.scoring import (  # noqa: E402
    classify_seniority, classify_seniority_flags, detect_years_required,
    is_candidate_friendly_job, new_grad_fit_score,
)

SENIOR_TITLE = re.compile(
    r"\b(senior|sr\.?|staff|principal|lead|architect|director|manager|"
    r"distinguished|fellow|expert)\b", re.I)


def main() -> None:
    print(f"DB dialect: {engine.dialect.name}\n")
    with Session(engine) as s:
        jobs = s.exec(select(JobPosting)).all()

    active = [j for j in jobs if j.active_status == "active"]
    print(f"TOTAL jobs           : {len(jobs)}")
    print(f"ACTIVE jobs          : {len(active)}")
    print(f"  is_usa True        : {sum(1 for j in active if j.is_usa)}")
    print(f"  is_usa False       : {sum(1 for j in active if not j.is_usa)}")
    print(f"  loc_conf == 0      : {sum(1 for j in active if (j.location_confidence or 0) == 0)}")
    print(f"  software_only      : {sum(1 for j in active if j.is_software_only)}")
    print(f"  is_senior          : {sum(1 for j in active if j.is_senior)}")
    print(f"  posted_date set    : {sum(1 for j in active if j.posted_date)}")
    print(f"  posted_date NULL   : {sum(1 for j in active if not j.posted_date)}")

    usa_view = [j for j in active
                if (j.is_usa or (j.location_confidence or 0) == 0) and not j.is_software_only]
    print(f"\nUSA_VIEW (dashboard) : {len(usa_view)}")
    print(f"  posted_date set    : {sum(1 for j in usa_view if j.posted_date)}")

    # Current entry-level tab query
    cur_entry = [j for j in usa_view
                 if not j.is_senior and (j.is_entry_level or j.is_candidate_friendly)]
    print(f"\nCurrent entry-tab    : {len(cur_entry)}")
    leak = [j for j in cur_entry if SENIOR_TITLE.search(j.job_title or "")]
    leak_lowfit = [j for j in cur_entry if (j.new_grad_fit or 0) < 60]
    print(f"  senior-title leak  : {len(leak)}")
    print(f"  new_grad_fit < 60  : {len(leak_lowfit)}")
    print("  Sample leaks (title | stored sen/ent/cf | exp_level | ng_fit):")
    for j in leak[:15]:
        print(f"   - {(j.job_title or '')[:46]:46} | "
              f"sen={int(j.is_senior)} ent={int(j.is_entry_level)} cf={int(j.is_candidate_friendly)} | "
              f"{(j.experience_level or '?')[:10]:10} | ng={j.new_grad_fit}")

    # If the tab gated on new_grad_fit >= 60 instead:
    ng_gate = [j for j in usa_view if (j.new_grad_fit or 0) >= 60]
    ng_gate_leak = [j for j in ng_gate if SENIOR_TITLE.search(j.job_title or "")]
    print(f"\nIf gated ng_fit>=60  : {len(ng_gate)} jobs, senior-title leak={len(ng_gate_leak)}")
    for j in ng_gate_leak[:10]:
        print(f"   - {(j.job_title or '')[:46]:46} | ng={j.new_grad_fit} exp={j.experience_level}")

    # Stale-flag audit: re-classify and count mismatches
    mism_senior = mism_entry = mism_level = mism_ngfit = mism_cf = 0
    senior_now_false = []  # stored is_senior True but fresh says False, etc.
    for j in active:
        title, desc = j.job_title or "", j.cleaned_description or ""
        is_entry, is_senior = classify_seniority_flags(title, desc)
        level, _ = classify_seniority(title, desc)
        ymin, _ = detect_years_required(desc)
        cf = is_candidate_friendly_job(title, desc, j.company_priority or "C", j.ats_platform or "")
        ng = new_grad_fit_score(level, is_senior, is_entry, cf, ymin, title, desc)
        if is_senior != bool(j.is_senior):
            mism_senior += 1
            if is_senior and not j.is_senior:
                senior_now_false.append(j)
        if is_entry != bool(j.is_entry_level):
            mism_entry += 1
        if level != (j.experience_level or ""):
            mism_level += 1
        if cf != bool(j.is_candidate_friendly):
            mism_cf += 1
        if ng != (j.new_grad_fit or 0):
            mism_ngfit += 1
    print("\nSTALE FLAG AUDIT (stored vs fresh, active jobs):")
    print(f"  is_senior mismatch        : {mism_senior}  (stored False but really senior: {len(senior_now_false)})")
    print(f"  is_entry_level mismatch   : {mism_entry}")
    print(f"  is_candidate_friendly mism: {mism_cf}")
    print(f"  experience_level mismatch : {mism_level}")
    print(f"  new_grad_fit mismatch     : {mism_ngfit}")
    print("  Sample stored-False-but-senior (these leak into New Grad tab today):")
    for j in senior_now_false[:12]:
        print(f"   - {(j.job_title or '')[:50]:50} | ng={j.new_grad_fit} ent={int(j.is_entry_level)} cf={int(j.is_candidate_friendly)}")


if __name__ == "__main__":
    main()
