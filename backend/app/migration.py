"""Safe SQLite migration — adds new columns to existing database without data loss."""

from __future__ import annotations

import logging
import sqlite3
from pathlib import Path

logger = logging.getLogger(__name__)

# New columns to add to each table: (table, column_name, column_def)
_MIGRATIONS: list[tuple[str, str, str]] = [
    # JobPosting new fields
    ("job_postings", "role_flags_json",              "TEXT NOT NULL DEFAULT ''"),
    ("job_postings", "is_software_only",             "INTEGER NOT NULL DEFAULT 0"),
    ("job_postings", "is_hardware_software_codesign","INTEGER NOT NULL DEFAULT 0"),
    ("job_postings", "cleaned_description",          "TEXT NOT NULL DEFAULT ''"),
    ("job_postings", "relevance_reason",             "TEXT NOT NULL DEFAULT ''"),
    ("job_postings", "exclusion_reason",             "TEXT NOT NULL DEFAULT ''"),
    ("job_postings", "matched_positive_terms_json",  "TEXT NOT NULL DEFAULT ''"),
    ("job_postings", "matched_negative_terms_json",  "TEXT NOT NULL DEFAULT ''"),
    ("job_postings", "data_quality_status",          "TEXT NOT NULL DEFAULT ''"),
    ("job_postings", "eligibility_risk",             "TEXT NOT NULL DEFAULT ''"),
    ("job_postings", "eligibility_terms",            "TEXT NOT NULL DEFAULT ''"),
    ("job_postings", "seniority_confidence",         "INTEGER NOT NULL DEFAULT 0"),
    ("job_postings", "classification_confidence",    "INTEGER NOT NULL DEFAULT 0"),
    ("job_postings", "data_quality_score",           "INTEGER NOT NULL DEFAULT 0"),
    ("job_postings", "source_reliability",           "TEXT NOT NULL DEFAULT ''"),
    ("job_postings", "location_label",               "TEXT NOT NULL DEFAULT ''"),
    ("job_postings", "posted_date_known",            "INTEGER NOT NULL DEFAULT 0"),
    ("job_postings", "follow_up_date",               "TEXT NOT NULL DEFAULT ''"),
    ("job_postings", "confirmation_id",              "TEXT NOT NULL DEFAULT ''"),
    ("job_postings", "recruiter_contact",            "TEXT NOT NULL DEFAULT ''"),
    ("job_postings", "new_grad_fit",                 "INTEGER NOT NULL DEFAULT 0"),
    ("job_postings", "experienced_fit",              "INTEGER NOT NULL DEFAULT 0"),
    ("job_postings", "requirement_tags",             "TEXT NOT NULL DEFAULT ''"),
    ("job_postings", "dup_group",                    "TEXT NOT NULL DEFAULT ''"),
    ("companies",    "sector",                       "TEXT NOT NULL DEFAULT ''"),
    # Company new fields
    ("companies",    "company_search_url",           "TEXT NOT NULL DEFAULT ''"),
    # Consecutive successful-but-empty scrapes — the silent failure counter.
    ("companies",    "consecutive_empty_scrapes",     "INTEGER NOT NULL DEFAULT 0"),
    # ResumeProfile new fields (multi-resume support)
    ("resume_profile", "label",                       "TEXT NOT NULL DEFAULT ''"),
    ("resume_profile", "is_active",                   "INTEGER NOT NULL DEFAULT 1"),
]


def run_migrations(db_path: str | Path) -> int:
    """Apply pending migrations. Returns count of columns added."""
    db_path = str(db_path)
    added = 0
    try:
        conn = sqlite3.connect(db_path)
        cur = conn.cursor()

        for table, col_name, col_def in _MIGRATIONS:
            # Check if column already exists
            cur.execute(f"PRAGMA table_info({table})")
            existing = {row[1] for row in cur.fetchall()}
            if col_name not in existing:
                cur.execute(f"ALTER TABLE {table} ADD COLUMN {col_name} {col_def}")
                logger.info("Added column %s.%s", table, col_name)
                added += 1

        conn.commit()
        conn.close()
    except Exception as e:
        logger.error("Migration failed: %s", e)
        raise

    return added
