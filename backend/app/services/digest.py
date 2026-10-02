"""Daily email digest — new jobs, high resume matches, apply-today, S-tier,
eligibility-risk. Generated from the DB; sent only when SMTP is configured."""

from __future__ import annotations

import json
import logging
from datetime import datetime, timedelta, timezone

from sqlmodel import Session, col, select

from ..config import settings
from ..database import engine
from ..models import JobPosting, ResumeProfile

logger = logging.getLogger(__name__)


def _job_brief(j: JobPosting) -> dict:
    return {
        "id": j.id, "company": j.company, "title": j.job_title,
        "location": j.location, "score": j.match_score,
        "role": j.role_category, "url": j.safe_apply_url or j.apply_url,
        "priority_tier": j.company_priority,
    }


def build_digest(session: Session) -> dict:
    now = datetime.now(timezone.utc)
    cutoff = now - timedelta(hours=24)

    def active(*extra):
        return session.exec(
            select(JobPosting).where(
                JobPosting.active_status == "active",
                JobPosting.is_software_only == False,  # noqa: E712
                *extra,
            )
        ).all()

    new_24h = [j for j in active(JobPosting.first_seen_at >= cutoff)]
    new_24h_usa = [j for j in new_24h if j.is_usa or j.location_confidence == 0.0]
    new_stier = [j for j in new_24h_usa if j.company_priority == "S" and not j.is_senior]
    new_entry = [j for j in new_24h_usa if (j.is_entry_level) and not j.is_senior]
    apply_today = sorted(
        [j for j in active((JobPosting.is_usa == True) | (JobPosting.location_confidence == 0.0))  # noqa: E712
         if not j.is_senior and j.match_score >= 80],
        key=lambda j: j.match_score, reverse=True,
    )[:8]
    elig_risk = [j for j in new_24h_usa if j.eligibility_risk in ("high", "medium")]

    # High resume matches (only if a resume is uploaded)
    high_matches: list[dict] = []
    rp = session.exec(select(ResumeProfile).order_by(col(ResumeProfile.id).desc())).first()
    if rp and rp.profile_json:
        try:
            from ..resume_match import compute_match
            profile = json.loads(rp.profile_json)
            pool = active((JobPosting.is_usa == True) | (JobPosting.location_confidence == 0.0))  # noqa: E712
            scored = []
            for j in pool:
                if j.is_senior:
                    continue
                m = compute_match(profile, {
                    "job_title": j.job_title, "cleaned_description": j.cleaned_description,
                    "matched_keywords": j.matched_keywords, "role_category": j.role_category,
                    "match_score": j.match_score, "is_candidate_friendly": j.is_candidate_friendly,
                    "eligibility_risk": j.eligibility_risk, "sponsors_h1b": None, "is_fresh": False,
                })
                scored.append((m["resume_match"], j))
            scored.sort(key=lambda x: x[0], reverse=True)
            high_matches = [{**_job_brief(j), "resume_match": rm} for rm, j in scored[:8] if rm >= 50]
        except Exception as e:  # noqa
            logger.warning("digest resume match failed: %s", e)

    return {
        "generated_at": now.isoformat(),
        "counts": {
            "new_24h": len(new_24h_usa),
            "new_stier": len(new_stier),
            "new_entry_level": len(new_entry),
            "apply_today": len(apply_today),
            "eligibility_risk": len(elig_risk),
            "high_resume_matches": len(high_matches),
        },
        "apply_today": [_job_brief(j) for j in apply_today],
        "new_stier": [_job_brief(j) for j in new_stier[:8]],
        "high_resume_matches": high_matches,
        "eligibility_risk": [_job_brief(j) for j in elig_risk[:6]],
    }


def _render_html(d: dict) -> str:
    c = d["counts"]

    def rows(items, show_match=False):
        out = ""
        for j in items:
            extra = f" · <b>{j.get('resume_match')}% match</b>" if show_match and j.get("resume_match") is not None else ""
            out += (f'<tr><td style="padding:8px 0;border-bottom:1px solid #eee">'
                    f'<a href="{j["url"]}" style="color:#2563EB;text-decoration:none;font-weight:600">{j["title"]}</a><br>'
                    f'<span style="color:#666;font-size:13px">{j["company"]} · {j["location"]} · score {j["score"]}{extra}</span></td></tr>')
        return out or '<tr><td style="color:#888;padding:8px 0">None today.</td></tr>'

    return f"""<div style="font-family:-apple-system,Segoe UI,Arial,sans-serif;max-width:600px;margin:auto;color:#111">
      <h2 style="color:#2563EB">Ashborne Silicon — Daily VLSI Digest</h2>
      <p style="color:#555">New in last 24h: <b>{c['new_24h']}</b> · High-fit (apply today): <b>{c['apply_today']}</b>
      · New grad: <b>{c['new_entry_level']}</b> · S-tier: <b>{c['new_stier']}</b>
      · Resume matches: <b>{c['high_resume_matches']}</b> · Eligibility-risk: <b>{c['eligibility_risk']}</b></p>
      <h3>Apply today (high-fit)</h3><table style="width:100%">{rows(d['apply_today'])}</table>
      {'<h3>Strong resume matches</h3><table style="width:100%">'+rows(d['high_resume_matches'],True)+'</table>' if d['high_resume_matches'] else ''}
      <h3>New S-tier roles</h3><table style="width:100%">{rows(d['new_stier'])}</table>
      <p style="color:#999;font-size:12px;margin-top:24px">You're receiving this because the Ashborne Silicon digest is enabled.</p>
    </div>"""


async def send_digest_email(d: dict):
    """Send the digest if SMTP is configured. Returns True (sent), False (failed),
    or None (not configured)."""
    if not (settings.smtp_host and settings.alert_email_to and settings.alert_email_from):
        return None
    try:
        import aiosmtplib
        from email.message import EmailMessage

        msg = EmailMessage()
        msg["From"] = settings.alert_email_from
        msg["To"] = settings.alert_email_to
        msg["Subject"] = "Ashborne Silicon — Daily VLSI Digest"
        msg.set_content("Your daily VLSI digest (view in an HTML-capable client).")
        msg.add_alternative(_render_html(d), subtype="html")

        await aiosmtplib.send(
            msg, hostname=settings.smtp_host, port=settings.smtp_port,
            username=settings.smtp_user or None, password=settings.smtp_password or None,
            start_tls=True,
        )
        return True
    except Exception as e:  # noqa
        logger.error("digest send failed: %s", e)
        return False
