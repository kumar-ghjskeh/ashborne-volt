"""Every stored datetime must be timezone-aware.

The models originally defaulted to ``datetime.utcnow()`` (naive) while the rest
of the codebase compared against ``datetime.now(timezone.utc)`` (aware). Mixing
the two is a latent type error: it works until a dependency decides to validate
it. sqlmodel 0.0.47 did exactly that — "Datetime values must have timezone
information" — and because the offending comparison runs at the very start of
every scrape, in maintain_scrape_runs(), it killed every engine before a single
company was fetched. Nine days of failed runs, with the same code passing
locally on sqlmodel 0.0.38.

These tests make the class of bug visible at commit time rather than on a
scheduled run days later. They need no database.
"""

from __future__ import annotations

import inspect
import re
from datetime import datetime, timedelta, timezone

from backend.app import models, scrape_engine, snapshot

# Model fields that persist a timestamp. All of them must default to the shared
# aware factory.
_TIMESTAMP_MODELS = [
    models.JobPosting,
    models.ResumeProfile,
    models.Setting,
    models.Watchlist,
    models.ScrapeRun,
    models.ScrapeError,
]


def test_shared_factory_returns_aware_utc():
    now = models.utcnow()
    assert now.tzinfo is not None, "models.utcnow() must be timezone-aware"
    assert now.utcoffset() == timedelta(0), "models.utcnow() must be UTC"


def test_no_model_defaults_to_a_naive_datetime():
    """Catch a new field added with datetime.utcnow — the original mistake."""
    offenders: list[str] = []
    for model in _TIMESTAMP_MODELS:
        for name, field in model.model_fields.items():
            factory = getattr(field, "default_factory", None)
            if factory is None:
                continue
            try:
                value = factory()
            except Exception:
                continue
            if isinstance(value, datetime) and value.tzinfo is None:
                offenders.append(f"{model.__name__}.{name}")
    assert not offenders, (
        "These fields default to a NAIVE datetime: "
        + ", ".join(offenders)
        + ". Use models.utcnow(); a naive default is rejected by sqlmodel >=0.0.47 "
        "and silently breaks every comparison against an aware value."
    )


def test_source_does_not_reintroduce_utcnow():
    """datetime.utcnow() must not reappear in the scrape path.

    Checked on source because the failure only shows up at runtime, against a
    library version that may not be the one installed locally.
    """
    pattern = re.compile(r"datetime\.utcnow\s*\(")
    for module in (models, scrape_engine, snapshot):
        src = inspect.getsource(module)
        # Strip docstrings/comments: the history is deliberately described there.
        code = "\n".join(
            line for line in src.splitlines()
            if not line.lstrip().startswith("#") and "``" not in line
        )
        hits = [m for m in pattern.findall(code)]
        assert not hits, (
            f"{module.__name__} calls datetime.utcnow(). Use "
            "datetime.now(timezone.utc) (or models.utcnow() for a model default) "
            "so stored and compared values share one awareness."
        )


def test_zombie_run_cutoff_is_aware():
    """The exact comparison that broke: started_at < cutoff in maintain_scrape_runs."""
    src = inspect.getsource(scrape_engine.maintain_scrape_runs)
    assert "datetime.now(timezone.utc)" in src, (
        "maintain_scrape_runs builds its cutoff from a naive clock again. It "
        "compares against ScrapeRun.started_at, which is aware, and runs before "
        "any scraping — so getting this wrong takes down every engine at once."
    )


def test_snapshot_restores_aware_datetimes():
    """Snapshots written before the fix hold naive strings; restoring them must
    not reintroduce naive values into a freshly built database.

    Asserted on behaviour rather than on the source of one function: the parser
    was lifted out of load_snapshot_into_db to module scope so the company-health
    restore could share it, and a source-text check broke on that refactor while
    the guarantee itself was intact. Behaviour is what matters here.
    """
    assert hasattr(snapshot, "_parse_aware"), (
        "the shared timestamp parser is gone; whatever replaced it must still "
        "coerce naive values to UTC on the way into the database"
    )
    naive = snapshot._parse_aware("2026-01-01T00:00:00")
    assert naive is not None and naive.tzinfo is not None, (
        "a stored timestamp WITHOUT an offset was restored as naive. Older "
        "snapshots are written that way, so this reseeds the mixed-awareness bug "
        "that killed every scrape for nine days."
    )
    assert naive.utcoffset() == timedelta(0), "must be read as UTC, not local time"

    aware = snapshot._parse_aware("2026-01-01T00:00:00+05:30")
    assert aware is not None and aware.utcoffset() == timedelta(hours=5, minutes=30), (
        "an explicit offset must be preserved, not overwritten with UTC"
    )
    assert snapshot._parse_aware(None) is None
    assert snapshot._parse_aware("not a date") is None
