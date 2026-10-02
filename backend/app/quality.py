"""Per-job data-quality, classification-confidence, source-reliability and
canonical location labelling. Lightweight — no network calls."""

from __future__ import annotations

import re

from .location_utils import US_STATE_ABBREVIATIONS, US_STATE_NAMES


def source_reliability(ats_platform: str) -> str:
    """How trustworthy the source feed is. Public structured ATS APIs are High."""
    a = (ats_platform or "").lower()
    if a in ("greenhouse", "lever", "ashby", "workday"):
        return "High"
    if a in ("icims", "smartrecruiters", "successfactors", "eightfold"):
        return "Medium"
    return "Low"


def _count_distinct_states(location_raw: str) -> int:
    loc = (location_raw or "")
    found: set[str] = set()
    for abbr in US_STATE_ABBREVIATIONS:
        if re.search(r"(?:^|[\s,/(;])(" + abbr + r")(?:[\s,/);.]|$)", loc):
            found.add(abbr)
    low = loc.lower()
    for name, abbr in US_STATE_NAMES.items():
        if name in low:
            found.add(abbr)
    return len(found)


def canonical_location_label(
    location_raw: str,
    is_usa: bool,
    is_remote_usa: bool,
    remote_status: str,
    location_confidence: float,
) -> str:
    """Return one canonical label: Onsite | Hybrid | Remote - USA |
    Multi-location USA | Location Unknown | Non-USA Excluded."""
    if not is_usa and location_confidence > 0.8:
        return "Non-USA Excluded"
    if location_confidence == 0 and not (location_raw or "").strip():
        return "Location Unknown"
    if _count_distinct_states(location_raw or "") >= 2:
        return "Multi-location USA"
    if is_remote_usa or remote_status == "Remote":
        return "Remote - USA"
    if remote_status == "Hybrid":
        return "Hybrid"
    if remote_status == "Onsite":
        return "Onsite"
    if location_confidence == 0:
        return "Location Unknown"
    return "Onsite"


def compute_data_quality(
    *,
    has_description: bool,
    location_confidence: float,
    posted_known: bool,
    apply_status: str,
    role_known: bool,
    seniority_confidence: int,
) -> tuple[int, int]:
    """Return (data_quality_score, classification_confidence), both 0-100.

    data_quality reflects how complete/trustworthy the record is.
    classification_confidence reflects how sure we are about role + seniority.
    """
    q = 10  # base: came from a tracked, structured source
    q += 30 if has_description else 0
    q += 25 if location_confidence >= 0.8 else (12 if location_confidence > 0 else 0)
    q += 20 if posted_known else 8
    q += 15 if apply_status in ("ok", "") else 5
    q = min(100, q)

    cc = 40 if role_known else 15
    cc += int(seniority_confidence * 0.4)          # up to ~40
    cc += 20 if has_description else 5
    cc = min(100, cc)
    return q, cc
