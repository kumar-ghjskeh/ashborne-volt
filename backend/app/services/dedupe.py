"""Deduplication logic for job postings."""

from __future__ import annotations

import hashlib
import re
from typing import Optional

from sqlalchemy.orm import defer
from sqlmodel import Session, select

from ..models import JobPosting


def _norm(s: str) -> str:
    return re.sub(r"\s+", " ", (s or "").lower().strip())


def make_fingerprint(company: str, job_title: str, location: str, job_id: str = "", apply_url: str = "") -> str:
    """Stable fingerprint used to detect duplicates."""
    if job_id:
        key = f"{_norm(company)}|{job_id}"
    elif apply_url:
        key = f"{_norm(company)}|{_norm(apply_url)}"
    else:
        key = f"{_norm(company)}|{_norm(job_title)}|{_norm(location)}"
    return hashlib.sha256(key.encode()).hexdigest()[:16]


def find_existing(
    session: Session,
    company: str,
    job_title: str,
    location: str,
    job_id: str = "",
    apply_url: str = "",
) -> Optional[JobPosting]:
    """Return an existing matching job record, or None."""
    # Primary: match by company + job_id
    if job_id:
        # full_description_text is only ever WRITTEN by the caller, never read,
        # so never ship it over the wire on these lookups.
        stmt = select(JobPosting).where(
            JobPosting.company == company,
            JobPosting.job_id_from_company == job_id,
        ).options(defer(JobPosting.full_description_text))
        result = session.exec(stmt).first()
        if result:
            return result

    # Secondary: match by apply URL
    if apply_url:
        stmt = select(JobPosting).where(
            JobPosting.company == company,
            JobPosting.apply_url == apply_url,
        ).options(defer(JobPosting.full_description_text))
        result = session.exec(stmt).first()
        if result:
            return result

    # Tertiary: fuzzy title + location match.
    #
    # This used to SELECT every job for the company as full ORM rows — including
    # both large description columns — and it runs once per scraped job that
    # didn't match on id or URL. For a company with N postings that is O(N) full
    # rows per job, i.e. O(N^2) bytes per scrape, and it was a major reason the
    # database's monthly data-transfer quota kept being exhausted.
    #
    # Now it scans only the three fields the comparison needs, then loads the one
    # matching row in full.
    from ..scoring import normalize_title
    norm_title = normalize_title(job_title)
    norm_loc = _norm(location)

    rows = session.exec(
        select(JobPosting.id, JobPosting.job_title, JobPosting.location)
        .where(JobPosting.company == company)
    ).all()
    for row_id, row_title, row_loc in rows:
        if normalize_title(row_title) == norm_title and _norm(row_loc) == norm_loc:
            return session.get(JobPosting, row_id)

    return None
