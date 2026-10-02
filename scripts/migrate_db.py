"""
Safe SQLite migration — adds new columns to existing tables without losing data.
Run once before restarting the backend after the upgrade.
"""

import shutil
import sqlite3
from datetime import datetime
from pathlib import Path

DB_PATH = Path(__file__).parents[1] / "data" / "jobs.db"

NEW_JOB_COLUMNS = [
    ("is_usa",               "INTEGER DEFAULT 0"),
    ("is_remote_usa",        "INTEGER DEFAULT 0"),
    ("country",              "TEXT DEFAULT ''"),
    ("state",                "TEXT DEFAULT ''"),
    ("city",                 "TEXT DEFAULT ''"),
    ("location_raw",         "TEXT DEFAULT ''"),
    ("location_confidence",  "REAL DEFAULT 0.0"),
    ("is_entry_level",       "INTEGER DEFAULT 0"),
    ("is_candidate_friendly","INTEGER DEFAULT 0"),
    ("is_senior",            "INTEGER DEFAULT 0"),
    ("score_breakdown_json", "TEXT DEFAULT ''"),
    ("relevance_score_label","TEXT DEFAULT ''"),
    ("safe_apply_url",       "TEXT DEFAULT ''"),
    ("apply_url_status",     "TEXT DEFAULT ''"),
    ("apply_url_reason",     "TEXT DEFAULT ''"),
    ("original_apply_url",   "TEXT DEFAULT ''"),
    ("saved_at",             "TEXT"),
    ("applied_at",           "TEXT"),
    ("ignored_at",           "TEXT"),
]

NEW_RUN_COLUMNS = [
    ("removed_jobs", "INTEGER DEFAULT 0"),
]


def get_existing_columns(conn: sqlite3.Connection, table: str) -> set[str]:
    cur = conn.execute(f"PRAGMA table_info({table})")
    return {row[1] for row in cur.fetchall()}


def migrate():
    if not DB_PATH.exists():
        print(f"Database not found at {DB_PATH} — nothing to migrate.")
        return

    # Backup before touching anything
    backup_path = DB_PATH.with_suffix(f".backup_{datetime.now().strftime('%Y%m%d_%H%M%S')}.db")
    shutil.copy2(DB_PATH, backup_path)
    print(f"Backup created: {backup_path}")

    with sqlite3.connect(DB_PATH) as conn:
        conn.execute("PRAGMA journal_mode=WAL")
        existing_job_cols = get_existing_columns(conn, "job_postings")
        existing_run_cols = get_existing_columns(conn, "scrape_runs")

        added = 0
        for col_name, col_def in NEW_JOB_COLUMNS:
            if col_name not in existing_job_cols:
                sql = f"ALTER TABLE job_postings ADD COLUMN {col_name} {col_def}"
                conn.execute(sql)
                print(f"  + job_postings.{col_name}")
                added += 1

        for col_name, col_def in NEW_RUN_COLUMNS:
            if col_name not in existing_run_cols:
                sql = f"ALTER TABLE scrape_runs ADD COLUMN {col_name} {col_def}"
                conn.execute(sql)
                print(f"  + scrape_runs.{col_name}")
                added += 1

        conn.commit()

    if added == 0:
        print("No new columns needed — database is already up to date.")
    else:
        print(f"Migration complete. {added} column(s) added.")


if __name__ == "__main__":
    migrate()
