"""Optional Notion sync — pushes high-score jobs to a Notion database."""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from ..config import settings

if TYPE_CHECKING:
    from ..models import JobPosting

logger = logging.getLogger(__name__)


def _notion_enabled() -> bool:
    return bool(settings.notion_api_key and settings.notion_database_id)


async def sync_job_to_notion(job: "JobPosting") -> None:
    """Push a single job to Notion (only if score >= 70 and Notion is configured)."""
    if not _notion_enabled():
        return
    if job.match_score < 70:
        return

    try:
        from notion_client import AsyncClient
        notion = AsyncClient(auth=settings.notion_api_key)

        # Check if already exists by searching for the apply_url property
        existing = await notion.databases.query(
            database_id=settings.notion_database_id,
            filter={"property": "Apply URL", "url": {"equals": job.apply_url}},
        )
        if existing.get("results"):
            # Update status if needed
            page_id = existing["results"][0]["id"]
            await notion.pages.update(
                page_id=page_id,
                properties={
                    "Status": {"select": {"name": job.active_status}},
                    "Last Seen": {"date": {"start": job.last_seen_at.isoformat()}},
                },
            )
            return

        await notion.pages.create(
            parent={"database_id": settings.notion_database_id},
            properties={
                "Job Title": {"title": [{"text": {"content": job.job_title}}]},
                "Company": {"rich_text": [{"text": {"content": job.company}}]},
                "Location": {"rich_text": [{"text": {"content": job.location}}]},
                "Match Score": {"number": job.match_score},
                "Priority": {"select": {"name": job.company_priority}},
                "Experience": {"select": {"name": job.experience_level}},
                "Role Category": {"select": {"name": job.role_category}},
                "Apply URL": {"url": job.apply_url},
                "Status": {"select": {"name": job.active_status}},
                "Keywords": {"rich_text": [{"text": {"content": job.matched_keywords}}]},
                "First Seen": {"date": {"start": job.first_seen_at.isoformat()}},
            },
        )
        logger.info("Synced to Notion: %s @ %s", job.job_title, job.company)

    except Exception as e:
        logger.warning("Notion sync failed for job %s: %s", job.id, e)
