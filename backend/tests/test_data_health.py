"""Data Health run hygiene: maintain_scrape_runs deletes zombie 'running' rows
(crashed runners stuck with no finished_at) and FIFO-prunes to the most recent 15,
without ever deleting a run that is still legitimately in progress."""

import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parents[2]))

from sqlmodel import Session, SQLModel, create_engine, select

from backend.app.models import ScrapeRun
from backend.app.scrape_engine import maintain_scrape_runs


def _session() -> Session:
    eng = create_engine("sqlite://", connect_args={"check_same_thread": False})
    SQLModel.metadata.create_all(eng)
    return Session(eng)


def test_deletes_zombie_runs_but_keeps_recent_running():
    s = _session()
    now = datetime.utcnow()
    # zombie: started 3h ago, never finished
    zombie = ScrapeRun(triggered_by="browser", started_at=now - timedelta(hours=3), finished_at=None)
    # legit in-progress: started 5 min ago, not finished
    running = ScrapeRun(triggered_by="manual", started_at=now - timedelta(minutes=5), finished_at=None)
    done = ScrapeRun(triggered_by="cf", started_at=now - timedelta(minutes=30), finished_at=now)
    for r in (zombie, running, done):
        s.add(r)
    s.commit()

    maintain_scrape_runs(s)
    kept = s.exec(select(ScrapeRun)).all()
    triggers = {r.triggered_by for r in kept}
    assert "browser" not in triggers          # zombie deleted
    assert "manual" in triggers                # recent running preserved
    assert "cf" in triggers                    # finished preserved


def test_fifo_prunes_to_fifteen():
    s = _session()
    # Aware: timestamps are stored as aware UTC, so a naive base would compare
    # unequal to the value that comes back even though it is the same instant.
    base = datetime.now(timezone.utc)
    for i in range(25):
        s.add(ScrapeRun(triggered_by="manual",
                        started_at=base - timedelta(minutes=i),
                        finished_at=base - timedelta(minutes=i) + timedelta(minutes=2)))
    s.commit()

    maintain_scrape_runs(s, keep=15)
    kept = s.exec(select(ScrapeRun).order_by(ScrapeRun.started_at)).all()
    assert len(kept) == 15
    # the 15 most RECENT are kept (oldest pruned)
    newest = max(r.started_at for r in kept)
    oldest_kept = min(r.started_at for r in kept)
    assert newest == base
    assert oldest_kept == base - timedelta(minutes=14)
