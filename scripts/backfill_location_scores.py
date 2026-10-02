"""Backfill is_usa, is_entry_level, is_senior, safe_apply_url, score_breakdown_json
on existing job records that were inserted before Phase 2 migration."""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "backend"))

from app.apply_url import process_apply_url
from app.database import engine
from app.location_utils import parse_location
from app.models import JobPosting
from app.scoring import (
    calculate_match_score,
    classify_seniority_flags,
    detect_experience_level,
    detect_remote_status,
    detect_role_category,
    detect_years_required,
    is_candidate_friendly_job,
    normalize_title,
    score_breakdown_json,
    score_to_label,
)
from sqlmodel import Session, select


def backfill():
    with Session(engine) as session:
        jobs = session.exec(select(JobPosting)).all()
        print(f"Backfilling {len(jobs)} job records...")

        updated = 0
        for job in jobs:
            changed = False

            # Location
            if not job.is_usa and job.location:
                loc = parse_location(job.location, job.description_snippet)
                if loc.confidence > 0:
                    job.is_usa = loc.is_usa
                    job.is_remote_usa = loc.is_remote_usa
                    job.country = loc.country
                    job.state = loc.state
                    job.city = loc.city
                    job.location_confidence = loc.confidence
                    changed = True

            # Safe apply URL
            if not job.safe_apply_url and job.apply_url:
                url_result = process_apply_url(job.apply_url, job.ats_platform, job.company)
                job.safe_apply_url = url_result.safe_apply_url or job.apply_url
                job.apply_url_status = url_result.apply_url_status
                job.apply_url_reason = url_result.apply_url_reason
                job.original_apply_url = url_result.original_apply_url
                changed = True

            # Score breakdown (if missing)
            if not job.score_breakdown_json:
                score, matched_kws, breakdown = calculate_match_score(
                    job_title=job.job_title,
                    description=job.description_snippet,
                    company_priority=job.company_priority,
                    location=job.location,
                    is_usa=job.is_usa,
                    first_seen_recently=False,
                    ats_platform=job.ats_platform,
                )
                job.match_score = score
                job.matched_keywords = ", ".join(matched_kws)
                job.score_breakdown_json = score_breakdown_json(breakdown)
                job.relevance_score_label = score_to_label(score)
                changed = True

            # Seniority flags
            if not job.is_entry_level and not job.is_senior:
                is_entry, is_senior = classify_seniority_flags(job.job_title, job.description_snippet)
                job.is_entry_level = is_entry
                job.is_senior = is_senior
                changed = True

            # Candidate friendly
            if not job.is_candidate_friendly:
                job.is_candidate_friendly = is_candidate_friendly_job(
                    job.job_title, job.description_snippet,
                    job.company_priority, job.ats_platform,
                )
                changed = True

            # Experience level + role category
            if not job.experience_level or job.experience_level == "Unknown":
                job.experience_level = detect_experience_level(job.job_title, job.description_snippet)
                changed = True

            if not job.role_category or job.role_category == "Unknown":
                job.role_category = detect_role_category(job.job_title, job.description_snippet)
                changed = True

            # Remote status
            if not job.remote_status or job.remote_status == "Unknown":
                job.remote_status = detect_remote_status(job.location, job.description_snippet)
                changed = True

            # Years required
            if job.years_required_min is None and job.description_snippet:
                ymin, ymax = detect_years_required(job.description_snippet)
                job.years_required_min = ymin
                job.years_required_max = ymax
                if ymin is not None:
                    changed = True

            # Normalized title
            if not job.normalized_title:
                job.normalized_title = normalize_title(job.job_title)
                changed = True

            if changed:
                session.add(job)
                updated += 1

            if updated % 100 == 0 and updated > 0:
                session.commit()
                print(f"  ... {updated}/{len(jobs)} updated")

        session.commit()
        print(f"Done. Updated {updated} of {len(jobs)} records.")


if __name__ == "__main__":
    backfill()
