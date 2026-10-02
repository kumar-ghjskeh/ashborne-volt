"""One-off / re-runnable maintenance: re-parse the location of every active job
with the current location logic and persist the result.

Why: the scrape engine only classifies location when a job is first inserted —
existing rows keep whatever was computed at insert time. After the Phase 4
multi-region fix (a posting listed across countries that includes a US office now
counts as USA), this backfill applies that fix to the already-stored pool so
genuine US listings stop being hidden from the USA view.

Run:  py scripts/backfill_locations.py     (from the backend/ directory)
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parents[1]))

from sqlmodel import Session, select

from app.database import engine
from app.location_utils import parse_location
from app.models import ActiveStatus, JobPosting
from app.quality import canonical_location_label
from app.scoring import detect_remote_status


def main() -> None:
    flipped_to_usa = 0
    flipped_from_usa = 0
    changed = 0

    with Session(engine) as session:
        jobs = session.exec(
            select(JobPosting).where(JobPosting.active_status == ActiveStatus.active)
        ).all()

        for j in jobs:
            raw = j.location_raw or j.location or ""
            desc = j.cleaned_description or j.description_snippet or ""
            lr = parse_location(raw, desc)
            remote_status = detect_remote_status(raw, desc)
            label = canonical_location_label(
                raw, lr.is_usa, lr.is_remote_usa, remote_status, lr.confidence
            )

            before = (j.is_usa, j.state, j.city, round(j.location_confidence, 3), j.location_label)
            after = (lr.is_usa, lr.state, lr.city, round(lr.confidence, 3), label)
            if before == after:
                continue

            if (not j.is_usa) and lr.is_usa:
                flipped_to_usa += 1
            elif j.is_usa and (not lr.is_usa):
                flipped_from_usa += 1

            j.is_usa = lr.is_usa
            j.is_remote_usa = lr.is_remote_usa
            j.country = lr.country
            j.state = lr.state
            j.city = lr.city
            j.location_confidence = lr.confidence
            j.location_label = label
            session.add(j)
            changed += 1

        session.commit()

    print(
        f"Backfilled {len(jobs)} active jobs | {changed} updated | "
        f"{flipped_to_usa} -> USA | {flipped_from_usa} -> non-USA"
    )


if __name__ == "__main__":
    main()
