"""Seed or refresh the companies table from companies.yaml."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parents[1] / "backend"))

from app.config import load_companies
from app.database import engine, init_db
from app.models import Company
from sqlmodel import Session, select


def seed():
    init_db()
    companies = load_companies()
    with Session(engine) as session:
        added = 0
        updated = 0
        for cfg in companies:
            existing = session.exec(
                select(Company).where(Company.name == cfg["name"])
            ).first()
            if existing:
                existing.category = cfg.get("category", existing.category)
                existing.priority = cfg.get("priority", existing.priority)
                existing.careers_url = cfg.get("careers_url", existing.careers_url)
                existing.ats_platform = cfg.get("ats_platform", existing.ats_platform)
                existing.enabled = cfg.get("enabled", True)
                session.add(existing)
                updated += 1
            else:
                co = Company(
                    name=cfg["name"],
                    category=cfg.get("category", ""),
                    priority=cfg.get("priority", "C"),
                    careers_url=cfg.get("careers_url", ""),
                    ats_platform=cfg.get("ats_platform", "generic"),
                    enabled=cfg.get("enabled", True),
                )
                session.add(co)
                added += 1
        session.commit()
    print(f"Seeded: {added} added, {updated} updated")


if __name__ == "__main__":
    seed()
