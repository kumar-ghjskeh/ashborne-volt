"""Database engine, session, and table initialisation."""

from __future__ import annotations

import logging
from pathlib import Path

from sqlmodel import Session, SQLModel, create_engine

from .config import settings

logger = logging.getLogger(__name__)


def _normalize_db_url(url: str) -> str:
    """Render/Heroku hand out ``postgres://`` URLs; SQLAlchemy needs
    ``postgresql+psycopg2://``. Normalise so the same code runs locally on
    SQLite and in production on Postgres."""
    if url.startswith("postgres://"):
        url = "postgresql+psycopg2://" + url[len("postgres://"):]
    elif url.startswith("postgresql://"):
        url = "postgresql+psycopg2://" + url[len("postgresql://"):]
    return url


DATABASE_URL = _normalize_db_url(settings.database_url)
_is_sqlite = DATABASE_URL.startswith("sqlite")

# SQLite needs check_same_thread=False; Postgres uses a pooled connection.
_connect_args = {"check_same_thread": False} if _is_sqlite else {}
_engine_kwargs: dict = {"echo": False, "connect_args": _connect_args}
if not _is_sqlite:
    _engine_kwargs.update(pool_pre_ping=True, pool_recycle=300)

engine = create_engine(DATABASE_URL, **_engine_kwargs)


def _ensure_scrape_errors_cascade() -> None:
    """Migrate an EXISTING Postgres database's scrape_errors FK to ON DELETE
    CASCADE.

    ``create_all`` never alters an existing table, so a database created before
    the model gained ``ondelete="CASCADE"`` keeps the old NO ACTION rule — the
    rule that let one orphaned error row abort every scrape for three days.
    Idempotent: it looks the constraint up by catalog (not by hardcoded name),
    does nothing when CASCADE is already in place, and clears any orphaned rows
    first so re-adding the constraint can't fail on stale data.
    """
    from sqlalchemy import text

    with engine.begin() as conn:
        exists = conn.execute(text("SELECT to_regclass('public.scrape_errors')")).scalar()
        if not exists:
            return
        # confdeltype: 'c' = CASCADE, 'a' = NO ACTION, 'r' = RESTRICT …
        rows = conn.execute(text("""
            SELECT conname, confdeltype
            FROM pg_constraint
            WHERE conrelid = 'public.scrape_errors'::regclass AND contype = 'f'
        """)).fetchall()
        for name, deltype in rows:
            if deltype == "c":
                continue
            conn.execute(text("""
                DELETE FROM scrape_errors
                WHERE scrape_run_id IS NOT NULL
                  AND scrape_run_id NOT IN (SELECT id FROM scrape_runs)
            """))
            conn.execute(text(f'ALTER TABLE scrape_errors DROP CONSTRAINT "{name}"'))
            conn.execute(text(
                f'ALTER TABLE scrape_errors ADD CONSTRAINT "{name}" '
                'FOREIGN KEY (scrape_run_id) REFERENCES scrape_runs(id) ON DELETE CASCADE'
            ))
            logger.info("Migrated FK %s to ON DELETE CASCADE", name)


def init_db() -> None:
    SQLModel.metadata.create_all(engine)
    # Postgres (Neon): create_all won't ALTER an existing table, so add new
    # columns idempotently. Keep this list current with additive model columns.
    if not _is_sqlite:
        from sqlalchemy import text
        _pg_add_columns = [
            ("job_postings", "job_skills", "TEXT NOT NULL DEFAULT ''"),
        ]
        try:
            with engine.begin() as conn:
                for tbl, col_name, decl in _pg_add_columns:
                    conn.execute(text(f'ALTER TABLE {tbl} ADD COLUMN IF NOT EXISTS {col_name} {decl}'))
        except Exception as e:
            logger.warning("Postgres column ensure warning: %s", e)
        try:
            _ensure_scrape_errors_cascade()
        except Exception as e:
            logger.warning("Postgres constraint ensure warning: %s", e)
    # Run SQLite column migrations for existing databases
    if settings.database_url.startswith("sqlite:///"):
        db_path = settings.database_url.replace("sqlite:///", "")
        db_file = Path(db_path)
        if db_file.exists():
            try:
                from .migration import run_migrations
                added = run_migrations(db_file)
                if added:
                    logger.info("Migration: added %d new column(s)", added)
            except Exception as e:
                logger.warning("Migration warning: %s", e)


def get_session():
    with Session(engine) as session:
        yield session
