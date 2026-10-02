"""
One-shot backfill: clean description_snippet → cleaned_description for all
existing jobs that have raw HTML but empty cleaned_description.
Run with: python backfill_descriptions.py
"""
import sys
import os
sys.path.insert(0, os.path.dirname(__file__))

import sqlite3
from app.description_cleaner import clean_html_description

DB_PATH = os.path.join(os.path.dirname(__file__), "..", "data", "jobs.db")


def run_backfill():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    cur = conn.cursor()

    # Find jobs where cleaned_description is empty but description_snippet exists
    cur.execute("""
        SELECT id, description_snippet
        FROM job_postings
        WHERE (cleaned_description IS NULL OR cleaned_description = '')
          AND description_snippet IS NOT NULL
          AND description_snippet != ''
    """)
    rows = cur.fetchall()
    print(f"Found {len(rows)} jobs to backfill")

    updated = 0
    for row in rows:
        raw = row["description_snippet"]
        cleaned = clean_html_description(raw, max_length=4000)
        if cleaned and cleaned != raw:
            cur.execute(
                "UPDATE job_postings SET cleaned_description = ? WHERE id = ?",
                (cleaned, row["id"]),
            )
            updated += 1

    conn.commit()
    conn.close()
    print(f"Backfilled {updated} / {len(rows)} jobs")
    print("Done.")


if __name__ == "__main__":
    run_backfill()
