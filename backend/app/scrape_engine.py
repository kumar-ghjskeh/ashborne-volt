"""Scrape orchestration engine — runs all companies and persists results."""

from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timedelta, timezone

from sqlalchemy import delete as sa_delete
from sqlalchemy.orm import load_only
from sqlmodel import Session, col, select

from .apply_url import process_apply_url
from .config import load_companies, load_schedule
from .database import engine
from .description_cleaner import clean_html_description, truncate_description_cleanly
from .eligibility import detect_eligibility_risk
from .location_utils import location_from_apply_url, parse_location
from .models import ActiveStatus, Company, JobPosting, ScrapeError, ScrapeRun
from .scrapers import get_scraper
from .quality import (
    canonical_location_label,
    compute_data_quality,
    source_reliability,
)
from .scoring import (
    build_relevance_reason,
    calculate_match_score,
    classify_role_flags,
    classify_seniority,
    classify_seniority_flags,
    detect_experience_level,
    detect_remote_status,
    detect_role_category,
    detect_years_required,
    experienced_fit_score,
    is_candidate_friendly_job,
    is_software_only,
    new_grad_fit_score,
    normalize_title,
    relevance_verdict,
    score_breakdown_json,
    score_to_label,
)
from .taxonomy import requirement_tags
from .services.alerts import send_alerts
from .services.dedupe import find_existing
from .services.notion_sync import sync_job_to_notion

logger = logging.getLogger(__name__)

# After this many consecutive failed runs a source is auto-quarantined (skipped)
# so broken endpoints never keep throwing errors into the dashboard.
ERROR_QUARANTINE_THRESHOLD = 8

# After this many consecutive runs that SUCCEED but return zero postings, a source
# is reported as stalled. Not quarantined: a board really can be empty, and
# skipping it would mean never noticing when it refills. At 8 runs/day this is
# about a day and a half of silence, which no active employer sustains.
EMPTY_STALL_THRESHOLD = 12


def _sane_posted_date(d, now):
    """Trust a scraper-provided posted date only if it's a plausible PAST date.
    A future date (Workday sometimes returns scheduled-publish dates) or absurdly
    ancient one (parser noise) is rejected so the card honestly falls back to the
    first-seen 'Added ~' label instead of showing a wrong 'Posted' date."""
    if not d:
        return None
    dd = d if d.tzinfo else d.replace(tzinfo=timezone.utc)
    if dd.date() > now.date():              # posting date is in the future
        return None
    if dd < now - timedelta(days=5 * 365):  # >5 yrs old → almost certainly noise
        return None
    # Return the AWARE value, not the original: several scrapers build their
    # dates with strptime, which is naive, and every posted_date passes through
    # here. The column type coerces too, but leaking naive values out of this
    # gate makes every downstream comparison a latent bug.
    return dd


async def persist_company_results(
    company_cfg: dict, raw_jobs: list, removed_threshold: int
) -> tuple[int, int]:
    """Persist one company's scraped jobs and reconcile removals.

    Upserts each raw job (refreshing descriptions / posted dates / apply URLs on
    existing rows, fully scoring new ones), marks postings that have disappeared
    across enough consecutive scrapes as removed, and resets the company's scrape
    status. Returns ``(new_jobs, removed_jobs)``.

    Shared by both the httpx scheduler (:func:`run_scrape`) and the local
    browser engine runner so persistence/scoring stays identical across engines.
    """
    company_name = company_cfg["name"]
    now = datetime.now(timezone.utc)
    found_ids: set[str] = set()
    new_count = 0

    with Session(engine) as session:
        for raw in raw_jobs:
            job_id_str = raw.job_id or ""
            found_ids.add(job_id_str or raw.apply_url)
            posted = _sane_posted_date(raw.posted_date, now)  # validated (no future/noise)

            existing = find_existing(
                session,
                company=company_name,
                job_title=raw.job_title,
                location=raw.location,
                job_id=job_id_str,
                apply_url=raw.apply_url,
            )

            if existing:
                existing.last_seen_at = now
                existing.active_status = ActiveStatus.active
                existing.missed_scrapes = 0
                # Upgrade to a fuller description when the scraper now returns
                # one (e.g. the Phase 5 Workday detail fetch), and backfill a
                # real posted date when it was previously unknown.
                raw_desc = raw.full_description_text or raw.description_snippet or ""
                if raw_desc:
                    cleaned = clean_html_description(raw_desc)
                    if len(cleaned) > len(existing.cleaned_description or "") + 50:
                        existing.cleaned_description = cleaned
                        if raw.full_description_text:
                            existing.full_description_text = raw.full_description_text
                        existing.description_snippet = truncate_description_cleanly(cleaned, length=300)
                        existing.data_quality_status = "ok"
                if posted and not existing.posted_date:
                    existing.posted_date = posted
                    existing.posted_date_known = True
                # Heal a previously-stored future/garbage date if the source has
                # since corrected it (or the validator now rejects it).
                elif existing.posted_date and _sane_posted_date(existing.posted_date, now) is None:
                    existing.posted_date = posted
                    existing.posted_date_known = posted is not None
                # Refresh the apply URL with the current logic so existing rows
                # pick up the Workday deep-link fix (no more dead fallbacks).
                url_result = process_apply_url(
                    raw.apply_url, company_cfg.get("ats_platform", ""), company_name,
                    careers_url=company_cfg.get("careers_url", ""),
                )
                if url_result.safe_apply_url:
                    existing.apply_url = url_result.safe_apply_url
                    existing.safe_apply_url = url_result.safe_apply_url
                    existing.original_apply_url = url_result.original_apply_url or existing.original_apply_url
                    existing.apply_url_status = url_result.apply_url_status
                    existing.apply_url_reason = url_result.apply_url_reason
                session.add(existing)
            else:
                # Clean HTML from description before any processing
                raw_desc = raw.full_description_text or raw.description_snippet or ""
                cleaned_desc = clean_html_description(raw_desc)

                # Final gate, now with the description. Adapters may pass along a
                # discipline-free title ("Project Engineer") for exactly this
                # check; the body decides whether it is electrical work.
                if not relevance_verdict(raw.job_title, cleaned_desc).relevant:
                    found_ids.discard(job_id_str or raw.apply_url)
                    continue
                new_count += 1
                snippet = truncate_description_cleanly(
                    raw.description_snippet or raw_desc, length=300
                )

                # Location parsing. Workday-style sources hand back a roll-up
                # ("2 Locations") for multi-site reqs, which parses to "unknown"
                # and then rides the USA-or-unknown view regardless of where the
                # job really is. The apply URL still names the primary site, so
                # fall back to it — free, and it both surfaces a real place and
                # correctly excludes the foreign reqs hiding in that bucket.
                loc_result = parse_location(raw.location, snippet)
                if loc_result.confidence == 0.0:
                    recovered = location_from_apply_url(raw.apply_url or "")
                    if recovered:
                        from_url = parse_location(recovered, snippet)
                        if from_url.confidence > 0.0:
                            loc_result = from_url
                            raw.location = recovered

                # Apply URL safety
                url_result = process_apply_url(
                    raw.apply_url,
                    company_cfg.get("ats_platform", ""),
                    company_name,
                    careers_url=company_cfg.get("careers_url", ""),
                )

                # Scoring (uses cleaned text for accuracy)
                score, matched_kws, breakdown = calculate_match_score(
                    job_title=raw.job_title,
                    description=cleaned_desc,
                    company_priority=company_cfg.get("priority", "C"),
                    location=raw.location,
                    is_usa=loc_result.is_usa,
                    first_seen_recently=True,
                    ats_platform=company_cfg.get("ats_platform", ""),
                )

                exp = detect_experience_level(raw.job_title, cleaned_desc)
                role_cat = detect_role_category(raw.job_title, cleaned_desc)
                remote_status = detect_remote_status(raw.location, cleaned_desc)
                ymin, ymax = detect_years_required(cleaned_desc)
                is_entry, is_senior = classify_seniority_flags(raw.job_title, cleaned_desc)
                is_cand_friendly = is_candidate_friendly_job(
                    raw.job_title, cleaned_desc,
                    company_cfg.get("priority", "C"),
                    company_cfg.get("ats_platform", ""),
                )
                role_flags = classify_role_flags(raw.job_title, cleaned_desc)
                sw_only = is_software_only(raw.job_title, cleaned_desc)
                hw_sw = role_flags.get("is_hardware_software_codesign", False)
                relevance = build_relevance_reason(raw.job_title, cleaned_desc, breakdown)
                elig_risk, elig_terms = detect_eligibility_risk(cleaned_desc)

                # Phase 2: granular seniority, location label, data quality
                sen_level, sen_conf = classify_seniority(raw.job_title, cleaned_desc)
                role_known = bool(role_cat) and role_cat != "Unknown"
                src_rel = source_reliability(company_cfg.get("ats_platform", ""))
                posted_known = posted is not None
                loc_label = canonical_location_label(
                    raw.location, loc_result.is_usa, loc_result.is_remote_usa,
                    remote_status, loc_result.confidence,
                )
                dq_score, class_conf = compute_data_quality(
                    has_description=bool(cleaned_desc),
                    location_confidence=loc_result.confidence,
                    posted_known=posted_known,
                    apply_status=url_result.apply_url_status,
                    role_known=role_known,
                    seniority_confidence=sen_conf,
                )

                # Job-intrinsic fit scores (primary ranking signal).
                ng_fit = new_grad_fit_score(
                    sen_level, is_senior, is_entry, is_cand_friendly, ymin,
                    raw.job_title, cleaned_desc,
                )
                ex_fit = experienced_fit_score(sen_level, is_senior, ymin)

                # Precompute the résumé-matching skill set so matching never has
                # to run the full keyword taxonomy over this posting at request time.
                from .resume_match import extract_job_skills
                jskills = ",".join(extract_job_skills(
                    " ".join([raw.job_title, cleaned_desc or "", ", ".join(matched_kws)])
                ))

                import json
                job = JobPosting(
                    company=company_name,
                    company_category=company_cfg.get("category", ""),
                    company_priority=company_cfg.get("priority", "C"),
                    job_title=raw.job_title,
                    normalized_title=normalize_title(raw.job_title),
                    role_category=role_cat,
                    experience_level=sen_level,
                    is_entry_level=is_entry,
                    is_candidate_friendly=is_cand_friendly,
                    is_senior=is_senior,
                    years_required_min=ymin,
                    years_required_max=ymax,
                    location=raw.location,
                    location_raw=raw.location,
                    remote_status=remote_status,
                    is_usa=loc_result.is_usa,
                    is_remote_usa=loc_result.is_remote_usa,
                    country=loc_result.country,
                    state=loc_result.state,
                    city=loc_result.city,
                    location_confidence=loc_result.confidence,
                    job_id_from_company=job_id_str,
                    apply_url=url_result.safe_apply_url or raw.apply_url,
                    original_apply_url=url_result.original_apply_url,
                    safe_apply_url=url_result.safe_apply_url,
                    apply_url_status=url_result.apply_url_status,
                    apply_url_reason=url_result.apply_url_reason,
                    source_url=raw.source_url,
                    ats_platform=company_cfg.get("ats_platform", ""),
                    posted_date=posted,
                    first_seen_at=now,
                    last_seen_at=now,
                    active_status=ActiveStatus.active,
                    match_score=score,
                    new_grad_fit=ng_fit,
                    experienced_fit=ex_fit,
                    matched_keywords=", ".join(matched_kws),
                    job_skills=jskills,
                    score_breakdown_json=score_breakdown_json(breakdown),
                    relevance_score_label=score_to_label(score),
                    description_snippet=snippet,
                    full_description_text=raw.full_description_text or "",
                    cleaned_description=cleaned_desc,
                    role_flags_json=json.dumps(role_flags),
                    is_software_only=sw_only,
                    is_hardware_software_codesign=hw_sw,
                    relevance_reason=relevance,
                    matched_positive_terms_json=json.dumps(matched_kws),
                    data_quality_status="ok" if cleaned_desc else "no_description",
                    eligibility_risk=elig_risk,
                    eligibility_terms=", ".join(elig_terms),
                    requirement_tags=", ".join(requirement_tags(cleaned_desc)),
                    seniority_confidence=sen_conf,
                    classification_confidence=class_conf,
                    data_quality_score=dq_score,
                    source_reliability=src_rel,
                    location_label=loc_label,
                    posted_date_known=posted_known,
                )
                session.add(job)
                session.commit()
                session.refresh(job)

                await send_alerts(job)
                await sync_job_to_notion(job)

        session.commit()

    # Only reconcile removals when the scrape actually returned jobs for this
    # company — an empty result is almost always a transient hiccup, not the
    # company closing every posting at once.
    removed_count = 0
    if found_ids:
        removed_count = await _update_removed_status(
            company_name, found_ids, removed_threshold
        )

    with Session(engine) as session:
        co = session.exec(select(Company).where(Company.name == company_name)).first()
        if co:
            co.last_scraped_at = now
            co.scrape_error_count = 0  # reset on success — self-healing
            session.add(co)
            session.commit()

    return new_count, removed_count


# The only columns the scrape-side bookkeeping queries read or write. Job rows
# carry two very large text columns (full_description_text, cleaned_description);
# loading them for bookkeeping moved megabytes per scrape for no reason and
# exhausted the database's monthly data-transfer quota twice. Anything added here
# must be genuinely needed by those loops.
_SCRAPE_LIGHT_COLS = (
    JobPosting.id,
    JobPosting.company,
    JobPosting.job_id_from_company,
    JobPosting.apply_url,
    JobPosting.active_status,
    JobPosting.missed_scrapes,
    JobPosting.removed_at,
    JobPosting.last_seen_at,
)


def maintain_scrape_runs(session: Session, keep: int = 20, stale_minutes: int = 60) -> None:
    """Keep the Data Health run history clean and trustworthy:

    1. Delete *zombie* runs — ones that never recorded ``finished_at`` and started
       more than ``stale_minutes`` ago (a runner crashed/was killed mid-run, so the
       row is stuck showing "running" forever and carries no useful data).
    2. FIFO-prune to the most recent ``keep`` *finished* runs (never deletes a run
       that is still legitimately in progress).

    IMPORTANT: ``scrape_errors.scrape_run_id`` references ``scrape_runs.id`` with
    no ON DELETE rule, so the child rows MUST be removed first. Deleting a run
    that still had errors attached raised ForeignKeyViolation, and because this
    runs at the very START of every scrape, that one bad row killed every scrape
    on every engine before a single company was fetched — silently, in the two
    passes that catch their own exceptions. Keep the child delete ahead of the
    parent delete.
    """
    # Aware, to match the stored values. A naive cutoff here is what sqlmodel
    # 0.0.47 began rejecting outright — and because this runs at the very start
    # of every scrape, it killed every engine before a company was fetched.
    cutoff = datetime.now(timezone.utc) - timedelta(minutes=stale_minutes)
    doomed: list[ScrapeRun] = list(session.exec(
        select(ScrapeRun).where(ScrapeRun.finished_at == None, ScrapeRun.started_at < cutoff)  # noqa: E711
    ).all())
    all_runs = session.exec(
        select(ScrapeRun).order_by(col(ScrapeRun.started_at).desc())
    ).all()
    doomed += [r for r in all_runs[keep:] if r.finished_at is not None]

    doomed_ids = {r.id for r in doomed if r.id is not None}
    if doomed_ids:
        # Children first, in one statement — see the note above.
        session.execute(
            sa_delete(ScrapeError).where(col(ScrapeError.scrape_run_id).in_(doomed_ids))
        )
    for r in doomed:
        session.delete(r)
    session.commit()


def with_known_ids(company_cfg: dict) -> dict:
    """A copy of the company config carrying the ids we already hold a
    description for, so adapters can skip their per-posting detail fetch.

    Steady state, almost every posting on a board is one we saw last run; this is
    what keeps request volume proportional to NEW postings instead of the board.
    """
    with Session(engine) as session:
        ids = session.exec(
            select(JobPosting.job_id_from_company).where(
                JobPosting.company == company_cfg["name"],
                JobPosting.job_id_from_company != "",
                JobPosting.cleaned_description != "",
            )
        ).all()
    return {**company_cfg, "_known_ids": set(ids)}


async def run_scrape(triggered_by: str = "scheduler", priorities: set[str] | None = None,
                     only: set[str] | None = None) -> ScrapeRun:
    """Scrape every httpx-engine company (or just ``only``) and persist results."""
    schedule_cfg = load_schedule()
    delay_between = schedule_cfg.get("rate_limit", {}).get("delay_between_companies_seconds", 5)
    # Keyword searches return a slightly different subset each run, so a posting
    # must be missing across several consecutive successful scrapes before it is
    # marked removed. Stops active/removed churn re-stamping "first seen".
    removed_threshold = schedule_cfg.get("removed_job_threshold", 4)

    run = ScrapeRun(triggered_by=triggered_by)
    with Session(engine) as session:
        maintain_scrape_runs(session)
        session.add(run)
        session.commit()
        session.refresh(run)
        run_id = run.id

    companies = load_companies()
    if priorities:
        companies = [c for c in companies if c.get("priority", "C") in priorities]
    if only is not None:
        companies = [c for c in companies if c["name"] in only]
    total_new = total_found = total_errors = total_removed = scraped_count = 0

    for company_cfg in companies:
        company_name = company_cfg["name"]
        # curl_cffi and browser companies have their own runners; fetching them
        # here only hits the anti-bot wall and counts an error every run.
        if company_cfg.get("engine") in ("browser", "cf"):
            continue
        if is_quarantined(company_name):
            logger.warning("Skipping %s — quarantined", company_name)
            continue

        try:
            async with get_scraper(with_known_ids(company_cfg)) as scraper:
                raw_jobs = await scraper.fetch_jobs()
            scraped_count += 1
            total_found += len(raw_jobs)
            new_count, removed_count = await persist_company_results(
                company_cfg, raw_jobs, removed_threshold
            )
            total_new += new_count
            total_removed += removed_count
            record_company_outcome(run_id, company_name, found=len(raw_jobs))
            logger.info("  %-34s found=%-4d new=%-4d removed=%d",
                        company_name, len(raw_jobs), new_count, removed_count)
        except Exception as e:
            total_errors += 1
            logger.error("Scrape failed for %s: %s", company_name, e, exc_info=True)
            record_company_outcome(run_id, company_name, error=e)

        await asyncio.sleep(delay_between)

    with Session(engine) as session:
        run_obj = session.get(ScrapeRun, run_id)
        if run_obj:
            run_obj.finished_at = datetime.now(timezone.utc)
            run_obj.companies_scraped = scraped_count
            run_obj.jobs_found = total_found
            run_obj.new_jobs = total_new
            run_obj.removed_jobs = total_removed
            run_obj.errors = total_errors
            session.add(run_obj)
            session.commit()
            # commit() expires every attribute, and this session is about to
            # close — so reload the values and detach the instance while they
            # are still readable. Returning it without this gives the caller an
            # object that raises DetachedInstanceError on the first attribute
            # read, which is exactly what made a fully successful 18-minute
            # scrape report as a failed one.
            session.refresh(run_obj)
            session.expunge(run_obj)
            return run_obj

    return run


async def _update_removed_status(company: str, seen_ids: set[str], threshold: int) -> int:
    removed_count = 0
    with Session(engine) as session:
        active_jobs = session.exec(
            select(JobPosting)
            .where(
                JobPosting.company == company,
                JobPosting.active_status.in_([ActiveStatus.active, ActiveStatus.possibly_removed]),
            )
            # This loop reads job_id_from_company/apply_url and writes
            # missed_scrapes/active_status/removed_at — nothing else. Loading
            # full rows here pulled every description for every active job of
            # every company on every scrape, which was the single largest
            # consumer of the database's data-transfer quota.
            .options(load_only(*_SCRAPE_LIGHT_COLS))
        ).all()

        for job in active_jobs:
            uid = job.job_id_from_company or job.apply_url
            if uid not in seen_ids:
                job.missed_scrapes += 1
                if job.missed_scrapes >= threshold:
                    job.active_status = ActiveStatus.removed
                    job.removed_at = datetime.now(timezone.utc)
                    removed_count += 1
                else:
                    job.active_status = ActiveStatus.possibly_removed
                session.add(job)

        session.commit()
    return removed_count


def reclassify_rows(companies: set[str] | None = None) -> dict[str, int]:
    """Re-derive every classifier output from title + description.

    Stored postings keep whatever the classifier said the day they were first
    seen, so a taxonomy fix would otherwise only ever reach new postings. This
    pass makes app/taxonomy.py retroactive: category, seniority, scores, flags
    and requirement badges are recomputed for every row each run. It is pure
    CPU over the scratch database (no network) and costs well under a second
    per thousand rows.

    Rows restored from state.json carry only bookkeeping fields; this is also
    what fills their classification back in when they come back to life.
    """
    import json as _json
    from .eligibility import detect_eligibility_risk as _elig

    changed = dropped = total = 0
    with Session(engine) as session:
        stmt = select(JobPosting)
        if companies is not None:
            stmt = stmt.where(col(JobPosting.company).in_(sorted(companies)))
        cfg_by_name = {c["name"]: c for c in load_companies()}
        for job in session.exec(stmt).all():
            total += 1
            desc = job.cleaned_description or ""
            title = job.job_title or ""
            cat = detect_role_category(title, desc)
            if job.role_category != cat:
                changed += 1
                if cat in ("Out of Scope", "Software / Compiler"):
                    dropped += 1
            cfg = cfg_by_name.get(job.company, {})
            priority = cfg.get("priority", job.company_priority or "C")
            job.role_category = cat
            job.normalized_title = normalize_title(title)
            level, conf = classify_seniority(title, desc)
            job.experience_level = level
            job.seniority_confidence = conf
            job.is_entry_level, job.is_senior = classify_seniority_flags(title, desc)
            job.years_required_min, job.years_required_max = detect_years_required(desc)
            job.is_candidate_friendly = is_candidate_friendly_job(
                title, desc, priority, job.ats_platform or "")
            score, kws, breakdown = calculate_match_score(
                title, desc, priority, job.location or "", is_usa=job.is_usa,
                ats_platform=job.ats_platform or "")
            job.match_score = score
            job.matched_keywords = ", ".join(kws)
            job.score_breakdown_json = score_breakdown_json(breakdown)
            job.relevance_score_label = score_to_label(score)
            job.relevance_reason = build_relevance_reason(title, desc, breakdown)
            job.role_flags_json = _json.dumps(classify_role_flags(title, desc))
            job.is_software_only = cat == "Software / Compiler"
            job.new_grad_fit = new_grad_fit_score(
                level, job.is_senior, job.is_entry_level, job.is_candidate_friendly,
                job.years_required_min, title, desc)
            job.experienced_fit = experienced_fit_score(level, job.is_senior, job.years_required_min)
            if desc:
                job.requirement_tags = ", ".join(requirement_tags(desc))
                risk, terms = _elig(desc)
                job.eligibility_risk, job.eligibility_terms = risk, ", ".join(terms)
            if job.location and not job.country and not job.state:
                loc = parse_location(job.location, job.description_snippet or "")
                job.is_usa, job.is_remote_usa = loc.is_usa, loc.is_remote_usa
                job.country, job.state, job.city = loc.country, loc.state, loc.city
                job.location_confidence = loc.confidence
            if not job.company_priority:
                job.company_priority = priority
                job.company_category = cfg.get("category", "")
            session.add(job)
        session.commit()
    logger.info("reclassified %d row(s): %d changed category, %d now out of scope",
                total, changed, dropped)
    return {"total": total, "changed": changed, "dropped": dropped}


def record_company_outcome(run_id: int | None, name: str, found: int | None = None,
                           error: Exception | None = None) -> None:
    """Update a company's health counters after one scrape attempt.

    Shared by every runner (httpx, curl_cffi, browser) so quarantine and stall
    detection behave identically everywhere. Before this existed the curl_cffi
    runner recorded nothing at all: a source that failed on every run there was
    never counted, never quarantined and never shown as broken.
    """
    with Session(engine) as session:
        co = session.exec(select(Company).where(Company.name == name)).first()
        if error is not None:
            session.add(ScrapeError(scrape_run_id=run_id, company=name,
                                    error_message=str(error)[:500],
                                    error_type=type(error).__name__))
            if co:
                co.scrape_error_count += 1
                session.add(co)
        elif co:
            co.last_scraped_at = datetime.now(timezone.utc)
            co.scrape_error_count = 0
            if found:
                co.consecutive_empty_scrapes = 0
            else:
                co.consecutive_empty_scrapes += 1
                if co.consecutive_empty_scrapes >= EMPTY_STALL_THRESHOLD:
                    logger.warning("%s has returned 0 postings for %d consecutive runs — "
                                   "likely a broken selector or a dead board",
                                   name, co.consecutive_empty_scrapes)
            session.add(co)
        session.commit()


def is_quarantined(name: str) -> bool:
    with Session(engine) as session:
        co = session.exec(select(Company).where(Company.name == name)).first()
        return bool(co and co.scrape_error_count >= ERROR_QUARANTINE_THRESHOLD)
