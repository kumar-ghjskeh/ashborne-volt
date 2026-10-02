"""
Backfill relevance_reason for existing jobs that have empty string.
Run with: python backfill_relevance.py
"""
import sys
import os
sys.path.insert(0, os.path.dirname(__file__))

import json
import sqlite3
from app.scoring import build_relevance_reason

DB_PATH = os.path.join(os.path.dirname(__file__), "..", "data", "jobs.db")


def run_backfill():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    cur = conn.cursor()

    cur.execute("""
        SELECT id, job_title, cleaned_description, description_snippet, score_breakdown_json
        FROM job_postings
        WHERE (relevance_reason IS NULL OR relevance_reason = '')
          AND active_status = 'active'
    """)
    rows = cur.fetchall()
    print(f"Found {len(rows)} jobs needing relevance_reason backfill")

    updated = 0
    for i, row in enumerate(rows):
        title = row["job_title"] or ""
        desc = row["cleaned_description"] or row["description_snippet"] or ""
        try:
            breakdown = json.loads(row["score_breakdown_json"]) if row["score_breakdown_json"] else {}
        except (json.JSONDecodeError, TypeError):
            breakdown = {}
        reason = build_relevance_reason(title, desc, breakdown)
        if reason:
            cur.execute(
                "UPDATE job_postings SET relevance_reason = ? WHERE id = ?",
                (reason, row["id"]),
            )
            updated += 1
        if (i + 1) % 100 == 0:
            conn.commit()
            print(f"  Progress: {i + 1}/{len(rows)}")

    conn.commit()
    conn.close()
    print(f"Backfilled {updated} / {len(rows)} jobs")
    print("Done.")


if __name__ == "__main__":
    run_backfill()
