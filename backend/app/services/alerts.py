"""Optional alert delivery — email, Discord, Telegram."""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

import httpx

from ..config import settings

if TYPE_CHECKING:
    from ..models import JobPosting

logger = logging.getLogger(__name__)


def _should_alert(job: "JobPosting") -> bool:
    from ..models import ExperienceLevel
    return (
        job.match_score >= 75
        and job.company_priority in ("S", "A")
        and job.experience_level in (ExperienceLevel.new_grad, ExperienceLevel.entry_level, ExperienceLevel.zero_to_three)
    )


def _format_message(job: "JobPosting") -> str:
    return (
        f"🔔 New RTL/DV Job Match!\n"
        f"Title:    {job.job_title}\n"
        f"Company:  {job.company} ({job.company_priority}-tier)\n"
        f"Location: {job.location}\n"
        f"Score:    {job.match_score}/100\n"
        f"Keywords: {job.matched_keywords}\n"
        f"Apply:    {job.apply_url}"
    )


async def send_alerts(job: "JobPosting") -> None:
    if not _should_alert(job):
        return
    msg = _format_message(job)
    if settings.discord_webhook_url:
        await _discord(msg)
    if settings.telegram_bot_token and settings.telegram_chat_id:
        await _telegram(msg)
    if settings.alert_email_to and settings.smtp_host:
        await _email(job, msg)


async def _discord(message: str) -> None:
    try:
        async with httpx.AsyncClient() as client:
            await client.post(
                settings.discord_webhook_url,
                json={"content": message},
                timeout=10,
            )
    except Exception as e:
        logger.warning("Discord alert failed: %s", e)


async def _telegram(message: str) -> None:
    try:
        url = f"https://api.telegram.org/bot{settings.telegram_bot_token}/sendMessage"
        async with httpx.AsyncClient() as client:
            await client.post(
                url,
                json={"chat_id": settings.telegram_chat_id, "text": message},
                timeout=10,
            )
    except Exception as e:
        logger.warning("Telegram alert failed: %s", e)


async def _email(job: "JobPosting", body: str) -> None:
    try:
        import aiosmtplib
        from email.mime.text import MIMEText

        msg = MIMEText(body)
        msg["Subject"] = f"[RTL Radar] {job.job_title} @ {job.company} (score {job.match_score})"
        msg["From"] = settings.alert_email_from
        msg["To"] = settings.alert_email_to

        await aiosmtplib.send(
            msg,
            hostname=settings.smtp_host,
            port=settings.smtp_port,
            username=settings.smtp_user or None,
            password=settings.smtp_password or None,
            start_tls=True,
        )
    except Exception as e:
        logger.warning("Email alert failed: %s", e)
