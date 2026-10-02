"""
Backfill safe_apply_url for existing Workday jobs.
Workday deep links expire — update them to use the company careers search page.
Run with: python backfill_workday_urls.py
"""
import sys
import os
sys.path.insert(0, os.path.dirname(__file__))

import sqlite3
from app.apply_url import process_apply_url

DB_PATH = os.path.join(os.path.dirname(__file__), "..", "data", "jobs.db")


def run_backfill():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    cur = conn.cursor()

    cur.execute("""
        SELECT id, apply_url, safe_apply_url, ats_platform, company
        FROM job_postings
        WHERE ats_platform = 'workday'
          OR apply_url LIKE '%myworkdayjobs.com%'
    """)
    rows = cur.fetchall()
    print(f"Found {len(rows)} Workday jobs to backfill")

    updated = 0
    for row in rows:
        result = process_apply_url(
            raw_url=row["apply_url"] or "",
            ats_platform=row["ats_platform"] or "",
            company_name=row["company"] or "",
        )
        if result.safe_apply_url and result.safe_apply_url != row["safe_apply_url"]:
            cur.execute(
                """UPDATE job_postings
                   SET safe_apply_url = ?, original_apply_url = ?,
                       apply_url_status = ?, apply_url_reason = ?
                   WHERE id = ?""",
                (result.safe_apply_url, result.original_apply_url,
                 result.apply_url_status, result.apply_url_reason, row["id"]),
            )
            updated += 1

    conn.commit()
    conn.close()
    print(f"Updated {updated} / {len(rows)} Workday jobs")
    print("Done.")


if __name__ == "__main__":
    run_backfill()
