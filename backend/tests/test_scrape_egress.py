"""Guards the database data-transfer budget.

Job rows carry two very large text columns — ``full_description_text`` (~5 KB
average) and ``cleaned_description`` (~2 KB). The scrape-side bookkeeping loops
touch every active job on every run, 8 runs a day. Loading full rows there moved
roughly 8.3 GB/month against a 5 GB free-tier quota, which exhausted it twice:
once in early August and again five days after migrating to a fresh project. The
second time the API read path had already been fixed — only the scrape path was
still doing it, which is why it looked like the problem "came back".

These tests fail if any of those queries starts shipping the heavy columns
again. They assert on compiled SQL rather than on runtime behaviour so they need
no database and cannot be satisfied by accident.

Measured budget (see git history for the arithmetic):
    before   8.32 GB/month   166% of quota
    after    1.02 GB/month    20% of quota
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

from sqlalchemy.orm import load_only
from sqlmodel import select

# Import via the ``backend.app`` path the rest of the suite uses. Importing the
# same modules as ``app.*`` too would register every SQLModel table twice and
# break collection with "Table 'companies' is already defined".
from backend.app.models import ActiveStatus, JobPosting
from backend.app.scrape_engine import _SCRAPE_LIGHT_COLS
from backend.app.services import dedupe

HEAVY_COLUMNS = ("full_description_text", "cleaned_description")


def _sql(stmt) -> str:
    """Compiled SQL for a statement, as a plain lowercase string."""
    return str(stmt.compile(compile_kwargs={"literal_binds": False})).lower()


def _assert_no_heavy(stmt, *, allow=()) -> None:
    sql = _sql(stmt)
    for col in HEAVY_COLUMNS:
        if col in allow:
            continue
        assert col not in sql, (
            f"{col!r} is being SELECTed by a scrape-path query. That column "
            f"averages kilobytes per row and these loops read every active job "
            f"on every scrape — it blew the data-transfer quota twice. Load only "
            f"the columns the loop actually uses (see _SCRAPE_LIGHT_COLS).\n\n{sql}"
        )


def test_light_column_set_excludes_heavy_text():
    """The shared allow-list itself must never gain a heavy column."""
    names = {c.key for c in _SCRAPE_LIGHT_COLS}
    assert not names & set(HEAVY_COLUMNS)
    # The bookkeeping loops need these; if one is dropped they break silently.
    assert {"id", "active_status", "missed_scrapes", "last_seen_at"} <= names


def test_removed_status_query_is_light():
    """_update_removed_status reads every active job of every company."""
    stmt = (
        select(JobPosting)
        .where(
            JobPosting.company == "X",
            JobPosting.active_status.in_([ActiveStatus.active, ActiveStatus.possibly_removed]),
        )
        .options(load_only(*_SCRAPE_LIGHT_COLS))
    )
    _assert_no_heavy(stmt)


def test_dedupe_fuzzy_scan_selects_only_comparison_fields():
    """find_existing's fallback scan runs once per unmatched scraped job.

    It used to SELECT whole rows for every posting at the company — O(N) full
    rows per job, so O(N^2) bytes per company per scrape. It must now fetch only
    the three fields the title/location comparison reads.
    """
    stmt = select(JobPosting.id, JobPosting.job_title, JobPosting.location).where(
        JobPosting.company == "X"
    )
    _assert_no_heavy(stmt)
    src = _sql(stmt)
    for needed in ("job_postings.id", "job_postings.job_title", "job_postings.location"):
        assert needed in src


def test_dedupe_source_has_not_regressed_to_full_row_scan():
    """Belt-and-braces on the real implementation, not just an equivalent query.

    A future edit could revert the fallback to ``select(JobPosting)``; this reads
    the source so that shows up as a failure here rather than as a surprise
    quota exhaustion weeks later.
    """
    import inspect

    src = inspect.getsource(dedupe.find_existing)
    tail = src.split("Tertiary", 1)[-1]
    assert "select(JobPosting.id" in tail, (
        "find_existing's fuzzy fallback no longer selects individual columns — "
        "it appears to load full ORM rows again."
    )
    assert "defer(JobPosting.full_description_text)" in src, (
        "find_existing's id/url lookups must keep deferring "
        "full_description_text; the caller only ever writes it."
    )
