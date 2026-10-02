"""Phase 2: granular seniority classification, data quality, location labels."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parents[2]))

from backend.app.scoring import classify_seniority
from backend.app.quality import (
    source_reliability,
    canonical_location_label,
    compute_data_quality,
)


def test_seniority_staff():
    level, conf = classify_seniority("Staff Design Verification Engineer")
    assert level == "Staff" and conf >= 90


def test_seniority_principal():
    level, _ = classify_seniority("Principal RTL Design Engineer")
    assert level == "Principal"


def test_seniority_manager():
    level, _ = classify_seniority("Engineering Manager, Silicon Verification")
    assert level == "Manager"


def test_seniority_new_grad():
    level, conf = classify_seniority("Design Verification Engineer, New College Grad 2026")
    assert level == "New Grad" and conf >= 85


def test_seniority_entry_engineer_one():
    level, _ = classify_seniority("ASIC Engineer I")
    assert level == "Entry Level"


def test_seniority_years_inference():
    level, _ = classify_seniority("Verification Engineer", "Requires 7+ years of experience")
    assert level == "Senior"


def test_seniority_unknown_is_low_confidence():
    level, conf = classify_seniority("Design Verification Engineer")
    assert level == "Unknown" and conf <= 40


def test_source_reliability():
    assert source_reliability("greenhouse") == "High"
    assert source_reliability("workday") == "High"
    assert source_reliability("custom") == "Low"


def test_location_label_remote_usa():
    assert canonical_location_label("Remote - United States", True, True, "Remote", 0.65) == "Remote - USA"


def test_location_label_multi():
    assert canonical_location_label("Austin, TX; Santa Clara, CA", True, False, "Onsite", 0.9) == "Multi-location USA"


def test_location_label_unknown():
    assert canonical_location_label("", False, False, "Unknown", 0.0) == "Location Unknown"


def test_data_quality_full_vs_sparse():
    full, cc_full = compute_data_quality(
        has_description=True, location_confidence=0.9, posted_known=True,
        apply_status="ok", role_known=True, seniority_confidence=92,
    )
    sparse, cc_sparse = compute_data_quality(
        has_description=False, location_confidence=0.0, posted_known=False,
        apply_status="", role_known=False, seniority_confidence=30,
    )
    assert full > sparse
    assert cc_full > cc_sparse
