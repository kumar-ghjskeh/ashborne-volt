"""FastAPI application — Ashborne Volt API (résumé + AI helpers; jobs are static files)."""

from __future__ import annotations

import json
import logging
import time
from datetime import datetime, timedelta, timezone
from typing import Annotated, Any, Optional

from fastapi import BackgroundTasks, Depends, FastAPI, File, Form, HTTPException, Query, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from sqlalchemy import and_, case, tuple_
from sqlalchemy.orm import defer
from sqlmodel import Session, col, func, select

from .config import settings
from .database import get_session, init_db
from .models import ActiveStatus, Company, JobPosting, PushSubscription, ResumeProfile, ScrapeError, ScrapeRun, Setting, Watchlist
from .scheduler import create_scheduler

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

app = FastAPI(title="Ashborne Volt API", version="1.0.0",
              # No interactive docs on the public service: they are not in the
              # route allowlist anyway, and advertising the legacy routes helps nobody.
              docs_url=None, redoc_url=None, openapi_url=None)

from .security import VERCEL_PREVIEW_ORIGIN, HardeningMiddleware  # noqa: E402

# Order matters: Starlette runs the LAST-added middleware first, so CORS wraps
# the hardening layer and even a 404/429 carries CORS headers the browser can read.
app.add_middleware(HardeningMiddleware, enforce_allowlist=settings.enforce_route_allowlist)
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins,
    # This project's own Vercel preview deployments only.
    allow_origin_regex=VERCEL_PREVIEW_ORIGIN,
    # No cookies or auth headers are used, so credentials stay off.
    allow_credentials=False,
    allow_methods=["GET", "POST", "OPTIONS"],
    allow_headers=["Content-Type"],
    max_age=86400,
)


def _seed_and_maintain() -> None:
    """One-time boot DB work: ensure schema, sync the company directory, and
    prune stale scrape-run rows. Isolated so the startup handler can call it
    inside a guard — a transient DB outage must never abort app startup."""
    init_db()
    from .config import load_all_companies
    from .database import engine
    # Seed the directory with EVERY company (enabled + disabled "Direct search"),
    # so the Companies page always lists them all and keeps their config in sync.
    with Session(engine) as session:
        for cfg in load_all_companies():
            existing = session.exec(select(Company).where(Company.name == cfg["name"])).first()
            if not existing:
                session.add(Company(
                    name=cfg["name"],
                    category=cfg.get("category", ""),
                    priority=cfg.get("priority", "C"),
                    careers_url=cfg.get("careers_url", ""),
                    company_search_url=cfg.get("company_search_url", ""),
                    ats_platform=cfg.get("ats_platform", "generic"),
                    enabled=cfg.get("enabled", True),
                ))
            else:
                # Keep mutable config fields in sync with the YAML.
                existing.category = cfg.get("category", existing.category)
                existing.priority = cfg.get("priority", existing.priority)
                existing.careers_url = cfg.get("careers_url", existing.careers_url)
                existing.company_search_url = cfg.get("company_search_url", getattr(existing, "company_search_url", ""))
                existing.ats_platform = cfg.get("ats_platform", existing.ats_platform)
                existing.enabled = cfg.get("enabled", existing.enabled)
                session.add(existing)
        session.commit()
        # Clean up the run history on every boot: drop zombie "running" rows left
        # by a crashed runner and FIFO-prune to the most recent 15.
        from .scrape_engine import maintain_scrape_runs
        maintain_scrape_runs(session)


@app.on_event("startup")
async def startup():
    # CRITICAL: the startup handler must never raise. If it does, uvicorn aborts
    # with "Application startup failed" (exit code 3) and the host (Render) just
    # restarts into the same crash loop forever — taking down even /health. A
    # database that's briefly unreachable (cold Postgres, expired free instance,
    # rotated credentials) is exactly the kind of thing that used to kill the
    # whole service; instead we log it, come up healthy, and let the scheduled
    # scrapes reconcile the DB once it's back.
    try:
        _seed_and_maintain()
    except Exception:
        logger.exception("Startup DB seeding failed — serving in degraded mode; "
                         "scheduled scrapes will reconcile once the DB is reachable")

    # The in-process APScheduler is OFF by default. All scraping now runs in
    # GitHub Actions (scrape.yml, 6×/day) writing straight to Postgres, so the
    # web service should be a lean READ-ONLY API. Running scrapes here would peg
    # the tiny free instance's CPU/RAM and make /health time out (Render's 5s
    # health check → "server failure" emails) while slowing every request. Set
    # ENABLE_SCHEDULER=true only on a host that is meant to do its own scraping.
    if settings.enable_scheduler:
        try:
            scheduler = create_scheduler()
            scheduler.start()
            logger.info("In-process scheduler started (ENABLE_SCHEDULER=true)")
        except Exception:
            logger.exception("Scheduler failed to start — API still serving")
    else:
        logger.info("Scheduler disabled — scraping handled externally (GitHub Actions)")

    # On a fresh cloud deploy, populate the database without waiting for the
    # first scheduled run. Empty DB → scrape; already-populated → skip.
    if settings.run_scrape_on_startup:
        import asyncio
        from .database import engine

        async def _initial_scrape():
            await asyncio.sleep(5)  # let the server finish coming up
            try:
                with Session(engine) as s:
                    count = s.exec(select(func.count(JobPosting.id))).one()
                if count == 0:
                    logger.info("Empty database on startup — running initial scrape")
                    from .scrape_engine import run_scrape
                    await run_scrape(triggered_by="startup")
            except Exception:
                logger.exception("Initial startup scrape failed — non-fatal")

        asyncio.create_task(_initial_scrape())


@app.on_event("shutdown")
async def shutdown():
    from .scheduler import get_scheduler
    s = get_scheduler()
    if s:
        s.shutdown(wait=False)


# ── Response models ────────────────────────────────────────────────────────────

class JobResponse(BaseModel):
    id: int
    company: str
    company_category: str
    company_priority: str
    job_title: str
    normalized_title: str = ""
    role_category: str
    experience_level: str
    is_entry_level: bool
    is_candidate_friendly: bool
    is_senior: bool
    location: str
    location_raw: str = ""
    display_location: str = ""
    remote_status: str
    is_usa: bool
    is_remote_usa: bool
    country: str = ""
    state: str = ""
    city: str = ""
    location_confidence: float = 0.0
    match_score: int
    relevance_score_label: str = ""
    new_grad_fit: int = 0
    experienced_fit: int = 0
    new_grad_fit_label: str = ""
    overall_recommendation: str = ""
    matched_keywords: str
    score_breakdown_json: str = ""
    active_status: str
    apply_url: str
    safe_apply_url: str = ""
    apply_url_status: str = ""
    apply_url_reason: str = ""
    original_apply_url: str = ""
    source_url: str = ""
    posted_date: Optional[datetime]
    first_seen_at: datetime
    last_seen_at: datetime
    removed_at: Optional[datetime]
    saved_at: Optional[datetime]
    applied_at: Optional[datetime]
    ignored_at: Optional[datetime] = None
    description_snippet: str
    full_description_text: str = ""
    cleaned_description: str = ""
    ats_platform: str
    notes: str
    application_status: str
    resume_version_used: str = ""
    follow_up_date: str = ""
    confirmation_id: str = ""
    recruiter_contact: str = ""
    years_required_min: Optional[int]
    years_required_max: Optional[int]
    job_id_from_company: str = ""
    missed_scrapes: int = 0
    # New enrichment fields
    role_flags_json: str = ""
    is_software_only: bool = False
    is_hardware_software_codesign: bool = False
    relevance_reason: str = ""
    exclusion_reason: str = ""
    matched_positive_terms_json: str = ""
    data_quality_status: str = ""
    # Eligibility / sponsorship (Phase 1)
    eligibility_risk: str = ""
    eligibility_terms: str = ""
    sponsors_h1b: Optional[bool] = None
    # Classification confidence & data quality (Phase 2)
    seniority_confidence: int = 0
    classification_confidence: int = 0
    data_quality_score: int = 0
    source_reliability: str = ""
    location_label: str = ""
    posted_date_known: bool = False
    # How many open requisitions this card stands for (1 = just itself). Set when
    # role grouping is on, so the card can say "+N locations" truthfully.
    group_count: int = 1

    model_config = {"from_attributes": True}


class PaginatedJobResponse(BaseModel):
    items: list[JobResponse]
    total_count: int
    page: int
    limit: int
    total_pages: int
    has_next: bool
    has_prev: bool


class StatusUpdate(BaseModel):
    active_status: Optional[str] = None
    application_status: Optional[str] = None
    notes: Optional[str] = None
    resume_version_used: Optional[str] = None
    follow_up_date: Optional[str] = None
    confirmation_id: Optional[str] = None
    recruiter_contact: Optional[str] = None


class CompanyResponse(BaseModel):
    id: int
    name: str
    category: str
    priority: str
    careers_url: str
    company_search_url: str = ""
    ats_platform: str
    enabled: bool
    last_scraped_at: Optional[datetime]
    scrape_error_count: int
    notes: str = ""
    total_active_jobs: int = 0
    relevant_active_jobs: int = 0
    viewable_jobs: int = 0
    usa_active_jobs: int = 0
    entry_level_jobs: int = 0
    new_jobs_today: int = 0
    scrape_status: str = "unknown"

    model_config = {"from_attributes": True}


class ScrapeRunResponse(BaseModel):
    id: int
    started_at: datetime
    finished_at: Optional[datetime]
    companies_scraped: int
    jobs_found: int
    new_jobs: int
    removed_jobs: int
    errors: int
    triggered_by: str

    model_config = {"from_attributes": True}


# ── Session dep ────────────────────────────────────────────────────────────────

SessionDep = Annotated[Session, Depends(get_session)]
VALID_STATUSES = {s.value for s in ActiveStatus}


# ── Job filter builder ─────────────────────────────────────────────────────────


def _effective_date():
    """The single source of truth for "how fresh is this job?".

    Uses the company's real posted date when the source gave us one, and falls
    back to when WE first saw it otherwise. This is exactly what the job card
    already shows ("Posted 3d ago" vs "Added 3d ago"), so the recency FILTER,
    the recency SORT and the card text can never disagree with each other.

    Before this existed, recency filtering keyed off ``posted_date`` alone,
    which silently hid every job from sources that don't publish a post date
    (Google, Meta, …) from every "posted within" window and dumped them at the
    bottom of "newest first". Undated jobs are not stale jobs — they're jobs
    whose age we know from discovery instead of from the source.
    """
    return func.coalesce(JobPosting.posted_date, JobPosting.first_seen_at)


def _keyword_rank(keyword: str):
    """How well does a row actually answer the query? (higher = better)

    Keyword matching deliberately reaches into the full description so deep
    terms ("coverage closure", "PCIe") still hit — but that means a broad term
    like "RTL" matches ~70% of the corpus, and without a relevance key the
    "best" result for "physical design" was whatever scored highest for new
    grads (a Design Verification role). Title hits must outrank body mentions.

    Tiers: whole-phrase title hit > company name > all tokens in the title >
    curated keyword/category hit > single token in title > description-only.
    """
    from sqlmodel import or_ as sql_or

    kw = " ".join(keyword.split())
    phrase = f"%{kw}%"
    toks = [t for t in kw.split() if t]
    title = col(JobPosting.job_title)
    ntitle = col(JobPosting.normalized_title)

    whens = [
        (title.ilike(phrase), 100),
        (ntitle.ilike(phrase), 92),
        (col(JobPosting.company).ilike(phrase), 88),
    ]
    if len(toks) > 1:
        # All tokens present in the title, any order ("verification design").
        whens.append((and_(*[title.ilike(f"%{t}%") for t in toks]), 75))
    whens += [
        (col(JobPosting.matched_keywords).ilike(phrase), 60),
        (col(JobPosting.role_category).ilike(phrase), 55),
    ]
    if toks:
        whens.append((sql_or(*[title.ilike(f"%{t}%") for t in toks]), 40))
    return case(*whens, else_=10)


def _build_job_query(
    session: Session,
    status: Optional[str] = None,
    company: Optional[str] = None,
    company_ids: Optional[str] = None,
    priority: Optional[str] = None,
    role_category: Optional[str] = None,
    experience_level: Optional[str] = None,
    level_filter: Optional[str] = None,
    remote: Optional[str] = None,
    min_score: Optional[int] = None,
    new_since_hours: Optional[int] = None,
    first_seen_days: Optional[int] = None,
    posted_within_hours: Optional[int] = None,
    keyword: Optional[str] = None,
    skills: Optional[str] = None,
    usa_only: bool = True,
    include_senior: bool = False,
    include_unknown_location: bool = False,
    include_software: bool = False,
    include_adjacent: bool = False,
    view: Optional[str] = None,
    role_flags: Optional[str] = None,
    state: Optional[str] = None,
    h1b_only: bool = False,
    relevant_only: bool = True,
    keep_cleaned: bool = False,
    group_roles: bool = False,
    sort_by: str = "new_grad_fit",
    sort_order: str = "desc",
    page: int = 1,
    limit: int = 50,
) -> tuple[list[JobPosting], int]:
    # Heavy full-text columns are the dominant DB egress (Resume Matches alone
    # pulls thousands of rows). List/ranking views never need the raw full text,
    # so defer it — the detail endpoint (session.get) still loads it on demand.
    # keep_cleaned=True keeps cleaned_description loaded for résumé-match ranking,
    # which reads it; it's blanked in that endpoint's response instead.

    stmt = select(JobPosting)
    conditions = []

    # Status filter (default: active only)
    target_status = status or ActiveStatus.active
    conditions.append(JobPosting.active_status == target_status)

    if company:
        conditions.append(col(JobPosting.company).ilike(f"%{company}%"))

    if company_ids:
        id_list = [int(i.strip()) for i in company_ids.split(",") if i.strip().isdigit()]
        if id_list:
            # Get company names for the IDs
            co_names = session.exec(
                select(Company.name).where(Company.id.in_(id_list))
            ).all()
            if co_names:
                conditions.append(col(JobPosting.company).in_(co_names))

    if priority:
        conditions.append(JobPosting.company_priority == priority)

    if role_category:
        conditions.append(col(JobPosting.role_category).ilike(f"%{role_category}%"))

    if experience_level:
        conditions.append(col(JobPosting.experience_level).ilike(f"%{experience_level}%"))

    if level_filter:
        levels = [lv.strip() for lv in level_filter.split(',') if lv.strip()]
        # Selecting a senior tier must lift the default senior gate below, or the
        # filter and the gate contradict and return zero results.
        if any(lv in ("Senior", "Staff", "Principal", "Lead", "Manager", "Director")
               for lv in levels):
            include_senior = True
        if levels:
            from sqlmodel import or_ as sql_or
            # Each seniority chip returns EXACTLY its level. classify_seniority now
            # emits every label the UI shows (New Grad / Entry Level / Junior /
            # Associate / Mid-Level / Senior / Staff / Principal / Lead / Manager)
            # and is_senior/is_entry are derived from it, so an exact
            # experience_level match is both precise and self-consistent — no more
            # "New Grad" and "Entry Level" chips returning the same lumped set.
            conditions.append(sql_or(*[
                col(JobPosting.experience_level) == lv for lv in levels
            ]))

    if remote:
        conditions.append(col(JobPosting.remote_status).ilike(f"%{remote}%"))

    if min_score is not None:
        # "Min score" filter is re-based on New Grad Fit — for this candidate,
        # "high score" means "realistic for a new grad", not intrinsic relevance.
        conditions.append(JobPosting.new_grad_fit >= min_score)

    # USA filter. Default is STRICT: a job must be positively identified as
    # being in the US. The opt-in escape hatch below also admits rows whose
    # location we could not parse at all — useful for triage, wrong for the
    # product, because "we don't know where this is" is not "this is in the US".
    # If a genuine US role goes missing, the fix is to teach US_CITIES the city
    # (see location_utils), NOT to re-open this hatch.
    if usa_only:
        if include_unknown_location:
            # USA jobs OR unknown location (confidence 0)
            conditions.append(
                (JobPosting.is_usa == True) | (JobPosting.location_confidence == 0.0)
            )
        else:
            conditions.append(JobPosting.is_usa == True)

    # Senior filter (exclude by default) — but an explicit keyword search should
    # surface ALL matching roles (e.g. searching a company name shows its senior
    # roles too), so the senior gate is lifted whenever a keyword is present.
    if not include_senior and not keyword:
        conditions.append(JobPosting.is_senior == False)

    if state:
        conditions.append(col(JobPosting.state).ilike(f"%{state}%"))

    if new_since_hours:
        cutoff = datetime.now(timezone.utc) - timedelta(hours=new_since_hours)
        conditions.append(JobPosting.first_seen_at >= cutoff)

    if first_seen_days:
        cutoff = datetime.now(timezone.utc) - timedelta(days=first_seen_days)
        conditions.append(JobPosting.first_seen_at >= cutoff)

    # "Posted / added within" uses the effective date (real posted date when the
    # source published one, else first-seen) so the window matches the freshness
    # the card actually shows and never hides undated sources. See
    # _effective_date().
    if posted_within_hours:
        cutoff = datetime.now(timezone.utc) - timedelta(hours=posted_within_hours)
        conditions.append(_effective_date() >= cutoff)

    if keyword:
        # Accurate multi-token search (portable SQLite + Postgres). Each token must
        # appear in at least one field (AND of tokens, OR of fields). High-signal
        # fields (company/title/skills/role/location) match as substrings; the FULL
        # free-text description is searched on WHOLE WORDS only — so e.g. "intel"
        # returns Intel, not every job whose description says "intelligence".
        from sqlalchemy import literal
        from sqlmodel import or_ as sql_or
        substr_fields = [
            JobPosting.job_title, JobPosting.normalized_title, JobPosting.company,
            JobPosting.matched_keywords, JobPosting.role_category,
            JobPosting.experience_level, JobPosting.state, JobPosting.location,
            JobPosting.ats_platform,
        ]
        # Search the COMPLETE description text (cleaned + full), so a term that only
        # appears deep in the posting (e.g. "PCIe", "coverage closure") still hits.
        word_fields = [
            JobPosting.cleaned_description, JobPosting.full_description_text,
            JobPosting.description_snippet,
        ]
        # Punctuation chars normalised to spaces before the word-boundary match so a
        # term adjacent to punctuation — "PCIe,", "(UVM)", "AXI/AHB", "coverage." —
        # still matches as a whole word. REPLACE is portable (SQLite + Postgres).
        _PUNCT = [",", ".", ";", ":", "(", ")", "/", "[", "]", "{", "}", "-", "|",
                  "\n", "\r", "\t", "\"", "'", "*", "•", "·"]

        def _word_in(field, token: str):
            expr = col(field)
            for ch in _PUNCT:
                expr = func.replace(expr, ch, " ")
            padded = literal(" ").concat(expr).concat(literal(" "))
            return padded.ilike(f"% {token} %")

        for tok in keyword.split():
            tok = tok.strip()
            if not tok:
                continue
            kw = f"%{tok}%"
            ors = [col(f).ilike(kw) for f in substr_fields]
            ors += [_word_in(f, tok) for f in word_fields]
            conditions.append(sql_or(*ors))

    if skills:
        for skill in skills.split(","):
            s = skill.strip()
            if s:
                kw = f"%{s}%"
                conditions.append(
                    col(JobPosting.matched_keywords).ilike(kw)
                    | col(JobPosting.description_snippet).ilike(kw)
                )

    # View-based presets
    if view == "entry_level":
        conditions.append(JobPosting.is_senior == False)
        conditions.append(
            (JobPosting.is_entry_level == True) | (JobPosting.is_candidate_friendly == True)
        )
    elif view == "best":
        conditions.append(JobPosting.new_grad_fit >= 65)
    elif view == "all_usa":
        pass  # usa_only already applied above
    elif view == "adjacent":
        include_adjacent = True
        include_senior = True

    # Exclude software-only roles unless explicitly requested
    if not include_software:
        conditions.append(JobPosting.is_software_only == False)

    # Relevance gate — keep discovery strictly on-motto (frontend semiconductor:
    # RTL design + verification/DV/ASIC and adjacent silicon-design categories).
    # Hides software, unclassifiable, and adjacent/backup roles so diversified
    # employers (equipment makers, etc.) can't introduce nuisance. Saved/Applied
    # tabs pass relevant_only=False since the user explicitly chose those jobs.
    if relevant_only:
        conditions.append(
            col(JobPosting.role_category).notin_(("Software / Compiler", "Unknown", "Adjacent / Backup"))
        )

    # Role flags filter: comma-separated list of flag names that must be True
    if role_flags:
        for flag_name in role_flags.split(","):
            flag_name = flag_name.strip()
            if flag_name and hasattr(JobPosting, flag_name):
                conditions.append(getattr(JobPosting, flag_name) == True)

    # H1B: STRICT — only employers known to sponsor, and only postings whose own
    # text does not demand citizenship, a green card or ITAR access.
    #
    # Must resolve real company names here rather than comparing against
    # _KNOWN_SPONSOR directly: that set holds NORMALISED names ("cadence"), so a
    # lower(company) IN (...) against it silently matches nothing for every
    # multi-word employer. Normalisation cannot run in SQL, so the catalog is
    # filtered in Python and the resulting actual names go into the IN clause.
    if h1b_only:
        from .config import load_all_companies
        from .eligibility import sponsors_h1b as _sponsors
        sponsor_names = [
            c["name"].lower() for c in load_all_companies()
            if _sponsors(c.get("name", "")) is True
        ]
        conditions.append(func.lower(col(JobPosting.company)).in_(sponsor_names))
        conditions.append(
            func.lower(col(JobPosting.eligibility_risk)).notin_(["high", "medium"])
        )

    for cond in conditions:
        stmt = stmt.where(cond)

    # Count total
    # Sort — default ranks by New Grad Fit (primary score for this candidate),
    # with role relevance and recency as natural tiebreakers.
    sort_col_map = {
        "new_grad_fit": JobPosting.new_grad_fit,
        "match_score": JobPosting.match_score,
        "experienced_fit": JobPosting.experienced_fit,
        "first_seen_at": JobPosting.first_seen_at,
        "last_seen_at": JobPosting.last_seen_at,
        # Newest-first ranks on the effective date so undated sources (Google,
        # Meta, …) sort by when we found them instead of being buried last.
        "posted_date": _effective_date(),
        "company": JobPosting.company,
        "job_title": JobPosting.job_title,
    }
    sort_col = sort_col_map.get(sort_by, JobPosting.new_grad_fit)
    # NULLS LAST is kept as a safety net for any nullable sort key; the recency
    # key is now COALESCE-backed so it is never null in practice. (No col() here:
    # the map holds SQL expressions as well as plain model columns, and both
    # expose .asc()/.desc() directly.)
    primary = sort_col.asc() if sort_order == "asc" else sort_col.desc()

    # With a search query, how well the row matches the query leads the ordering
    # — but only when the user hasn't explicitly picked a different sort. If they
    # chose "Newest first", that wins and relevance becomes the tiebreaker.
    order_keys = [primary.nulls_last()]
    if keyword:
        rank = _keyword_rank(keyword).desc()
        order_keys = [rank, *order_keys] if sort_by == "new_grad_fit" else [*order_keys, rank]
    order_keys = [
        *order_keys,
        col(JobPosting.match_score).desc(),
        col(JobPosting.first_seen_at).desc(),
    ]

    # Role grouping: big employers post ONE role at many sites as separate reqs
    # (Apple lists "Design Verification Engineer" 12 times). They are genuinely
    # distinct requisitions, so nothing is deleted — but shown raw they bury the
    # rest of the board under near-identical cards. Collapse them to one row per
    # (company, normalized title), keeping the best-ranked member as the one
    # shown; siblings are still reachable via /jobs/{id}/locations.
    #
    # Done with a window function rather than in the client because the client
    # only ever sees one page, so it can only collapse duplicates that happen to
    # land together — of 95 collapsible rows pool-wide it was catching 2. Doing
    # it in SQL also keeps total_count and pagination honest, and still transfers
    # only the page (grouping the full set client-side would multiply egress on
    # the hottest endpoint).
    if group_roles:
        role_key = func.lower(
            func.coalesce(col(JobPosting.normalized_title), col(JobPosting.job_title))
        )
        rn = func.row_number().over(
            partition_by=[func.lower(col(JobPosting.company)), role_key],
            order_by=order_keys,
        ).label("_rn")
        ranked = stmt.add_columns(rn).subquery()
        keep_ids = select(ranked.c.id).where(ranked.c._rn == 1)
        stmt = select(JobPosting).where(col(JobPosting.id).in_(keep_ids))

    stmt = stmt.order_by(*order_keys)

    count_stmt = select(func.count()).select_from(stmt.order_by(None).subquery())
    total_count = session.exec(count_stmt).one()

    # Defer heavy full-text columns so they aren't SELECTed (egress reduction).
    deferred = [JobPosting.full_description_text]
    if not keep_cleaned:
        deferred.append(JobPosting.cleaned_description)
    stmt = stmt.options(*[defer(c) for c in deferred])

    # Paginate
    offset = (page - 1) * limit
    stmt = stmt.offset(offset).limit(limit)
    items = session.exec(stmt).all()

    # Populate the deferred fields with "" directly in each instance's __dict__ so
    # response serialization reads the blank value instead of lazily re-querying
    # the column per row (which would defeat the point and cause N+1 queries).
    for job in items:
        job.__dict__["full_description_text"] = ""
        if not keep_cleaned:
            job.__dict__["cleaned_description"] = ""

    # How many reqs each surviving card represents. One aggregate over just the
    # page's (company, title) pairs — not the whole pool — so the "+N locations"
    # badge is accurate without a per-card round trip.
    if group_roles and items:
        keys = {(j.company.lower(), (j.normalized_title or j.job_title or "").lower()) for j in items}
        role_key = func.lower(
            func.coalesce(col(JobPosting.normalized_title), col(JobPosting.job_title))
        )
        counts = dict(
            (tuple(r[:2]), r[2])
            for r in session.exec(
                select(func.lower(col(JobPosting.company)), role_key, func.count())
                .where(
                    JobPosting.active_status == ActiveStatus.active,
                    tuple_(func.lower(col(JobPosting.company)), role_key).in_(list(keys)),
                )
                .group_by(func.lower(col(JobPosting.company)), role_key)
            ).all()
        )
        for job in items:
            k = (job.company.lower(), (job.normalized_title or job.job_title or "").lower())
            job.__dict__["group_count"] = counts.get(k, 1)

    return items, total_count


def _paginate(items: list, total: int, page: int, limit: int) -> dict[str, Any]:
    total_pages = max(1, (total + limit - 1) // limit)
    return {
        "items": items,
        "total_count": total,
        "page": page,
        "limit": limit,
        "total_pages": total_pages,
        "has_next": page < total_pages,
        "has_prev": page > 1,
    }


# ── Job endpoints ──────────────────────────────────────────────────────────────

@app.get("/jobs", response_model=PaginatedJobResponse)
def list_jobs(
    session: SessionDep,
    page: int = 1,
    limit: int = Query(default=50, ge=1, le=200),
    status: Optional[str] = None,
    company: Optional[str] = None,
    company_ids: Optional[str] = None,
    priority: Optional[str] = None,
    role_category: Optional[str] = None,
    experience_level: Optional[str] = None,
    level_filter: Optional[str] = None,
    remote: Optional[str] = None,
    min_score: Optional[int] = None,
    new_since_hours: Optional[int] = None,
    first_seen_days: Optional[int] = None,
    posted_within_hours: Optional[int] = None,
    keyword: Optional[str] = None,
    skills: Optional[str] = None,
    usa_only: bool = True,
    include_senior: bool = False,
    include_unknown_location: bool = False,
    include_software: bool = False,
    include_adjacent: bool = False,
    view: Optional[str] = None,
    role_flags: Optional[str] = None,
    state: Optional[str] = None,
    h1b_only: bool = False,
    sort_by: str = "new_grad_fit",
    sort_order: str = "desc",
    group_roles: bool = True,
):
    items, total = _build_job_query(
        session, status=status, company=company, company_ids=company_ids,
        group_roles=group_roles,
        priority=priority, role_category=role_category, experience_level=experience_level,
        level_filter=level_filter,
        remote=remote, min_score=min_score, new_since_hours=new_since_hours,
        first_seen_days=first_seen_days, posted_within_hours=posted_within_hours,
        keyword=keyword, skills=skills,
        usa_only=usa_only, include_senior=include_senior,
        include_unknown_location=include_unknown_location,
        include_software=include_software, include_adjacent=include_adjacent,
        view=view, role_flags=role_flags,
        state=state, h1b_only=h1b_only, sort_by=sort_by, sort_order=sort_order, page=page, limit=limit,
    )
    return _paginate(items, total, page, limit)


@app.get("/jobs/new", response_model=PaginatedJobResponse)
def new_jobs(session: SessionDep, hours: int = 24, page: int = 1, limit: int = 50):
    items, total = _build_job_query(
        session, new_since_hours=hours, usa_only=False, include_senior=False,
        page=page, limit=limit,
    )
    return _paginate(items, total, page, limit)


@app.get("/jobs/best", response_model=PaginatedJobResponse)
def best_jobs(
    session: SessionDep,
    min_score: int = 65,
    page: int = 1,
    limit: int = Query(default=50, ge=1, le=200),
    keyword: Optional[str] = None,
    company: Optional[str] = None,
    priority: Optional[str] = None,
    role_category: Optional[str] = None,
    remote: Optional[str] = None,
    state: Optional[str] = None,
    new_since_hours: Optional[int] = None,
    usa_only: bool = True,
    include_senior: bool = False,
    include_software: bool = False,
):
    items, total = _build_job_query(
        session, min_score=min_score, usa_only=usa_only, include_senior=include_senior,
        include_software=include_software, keyword=keyword, company=company,
        priority=priority, role_category=role_category, remote=remote, state=state,
        new_since_hours=new_since_hours, sort_by="match_score", page=page, limit=limit,
    )
    return _paginate(items, total, page, limit)


@app.get("/jobs/entry-level", response_model=PaginatedJobResponse)
def entry_level_jobs(
    session: SessionDep,
    page: int = 1,
    limit: int = Query(default=50, ge=1, le=200),
    # ── Identical filter contract to /jobs ──
    status: Optional[str] = None,
    company: Optional[str] = None,
    company_ids: Optional[str] = None,
    priority: Optional[str] = None,
    role_category: Optional[str] = None,
    experience_level: Optional[str] = None,
    level_filter: Optional[str] = None,
    remote: Optional[str] = None,
    min_score: Optional[int] = None,
    new_since_hours: Optional[int] = None,
    first_seen_days: Optional[int] = None,
    posted_within_hours: Optional[int] = None,
    keyword: Optional[str] = None,
    skills: Optional[str] = None,
    usa_only: bool = True,
    include_unknown_location: bool = False,
    include_software: bool = False,
    role_flags: Optional[str] = None,
    state: Optional[str] = None,
    h1b_only: bool = False,
    sort_by: str = "new_grad_fit",
    sort_order: str = "desc",
):
    """New Grad tab — the SAME shared filter contract as /jobs (every chip, sort,
    posted-within, min-score-on-New-Grad-Fit, H1B, …), then the entry-level gate
    (view='entry_level': non-senior AND entry-level-or-candidate-friendly)."""
    items, total = _build_job_query(
        session, view="entry_level", status=status, company=company, company_ids=company_ids,
        priority=priority, role_category=role_category, experience_level=experience_level,
        level_filter=level_filter, remote=remote, min_score=min_score,
        new_since_hours=new_since_hours, first_seen_days=first_seen_days,
        posted_within_hours=posted_within_hours, keyword=keyword, skills=skills,
        usa_only=usa_only, include_unknown_location=include_unknown_location,
        include_software=include_software, role_flags=role_flags, state=state,
        h1b_only=h1b_only, sort_by=sort_by, sort_order=sort_order, page=page, limit=limit,
    )
    return _paginate(items, total, page, limit)


@app.get("/jobs/removed", response_model=PaginatedJobResponse)
def removed_jobs(session: SessionDep, page: int = 1, limit: int = 50):
    items, total = _build_job_query(
        session, status="removed", usa_only=False, include_senior=True,
        sort_by="last_seen_at", page=page, limit=limit,
    )
    return _paginate(items, total, page, limit)


@app.get("/jobs/saved", response_model=PaginatedJobResponse)
def saved_jobs(session: SessionDep, page: int = 1, limit: int = 50):
    items, total = _build_job_query(
        session, status="saved", usa_only=False, include_senior=True,
        relevant_only=False, page=page, limit=limit,
    )
    return _paginate(items, total, page, limit)


@app.get("/jobs/applied", response_model=PaginatedJobResponse)
def applied_jobs(session: SessionDep, page: int = 1, limit: int = 50):
    items, total = _build_job_query(
        session, status="applied", usa_only=False, include_senior=True,
        relevant_only=False, sort_by="applied_at", page=page, limit=limit,
    )
    return _paginate(items, total, page, limit)


@app.get("/jobs/facets")
def job_facets(session: SessionDep, usa_only: bool = True, include_software: bool = False):
    """Return available filter facets with counts for the active job pool."""
    base_conds = [JobPosting.active_status == "active"]
    if usa_only:
        base_conds.append(
            (JobPosting.is_usa == True) | (JobPosting.location_confidence == 0.0)
        )
    if not include_software:
        base_conds.append(JobPosting.is_software_only == False)
    # Same relevance gate as discovery, so facet counts/categories match what the
    # job list actually shows (no nuisance categories, no inflated counts).
    base_conds.append(
        col(JobPosting.role_category).notin_(("Software / Compiler", "Unknown", "Adjacent / Backup"))
    )

    def facet_count(extra_conds):
        stmt = select(func.count(JobPosting.id)).where(*base_conds, *extra_conds)
        return session.exec(stmt).one() or 0

    role_cats = session.exec(
        select(JobPosting.role_category, func.count(JobPosting.id))
        .where(*base_conds)
        .group_by(JobPosting.role_category)
        .order_by(func.count(JobPosting.id).desc())
    ).all()

    priorities = session.exec(
        select(JobPosting.company_priority, func.count(JobPosting.id))
        .where(*base_conds)
        .group_by(JobPosting.company_priority)
        .order_by(JobPosting.company_priority)
    ).all()

    remote_statuses = session.exec(
        select(JobPosting.remote_status, func.count(JobPosting.id))
        .where(*base_conds)
        .group_by(JobPosting.remote_status)
        .order_by(func.count(JobPosting.id).desc())
    ).all()

    states_raw = session.exec(
        select(JobPosting.state, func.count(JobPosting.id))
        .where(*base_conds, JobPosting.state != "")
        .group_by(JobPosting.state)
        .order_by(func.count(JobPosting.id).desc())
        .limit(15)
    ).all()

    return {
        "role_categories": [{"value": r, "count": c} for r, c in role_cats if r],
        "priorities": [{"value": p, "count": c} for p, c in priorities if p],
        "remote_statuses": [{"value": r, "count": c} for r, c in remote_statuses if r],
        "states": [{"value": s, "count": c} for s, c in states_raw],
        "entry_level_count": facet_count([
            (JobPosting.is_entry_level == True) | (JobPosting.is_candidate_friendly == True)
        ]),
        "candidate_friendly_count": facet_count([JobPosting.is_candidate_friendly == True]),
        "senior_count": facet_count([JobPosting.is_senior == True]),
        "remote_count": facet_count([col(JobPosting.remote_status).ilike("%remote%")]),
        # Same effective-date basis as the "posted / added within 24h" filter, so
        # the headline count and the filtered result can never disagree.
        "new_24h_count": facet_count([
            _effective_date() >= datetime.now(timezone.utc) - timedelta(hours=24)
        ]),
    }


@app.get("/jobs/search-suggestions")
def search_suggestions(q: str, session: SessionDep, limit: int = 8):
    """Typed, counted, prefix-ranked autocomplete suggestions.

    Each suggestion carries its kind ("company" / "title" / "skill") and how
    many jobs it would return, so the dropdown can label the row and the user
    can tell a dead end from a real one before pressing Enter. Only suggestions
    drawn from the browseable pool (active + US-or-unknown) are offered — never
    suggest a query that lands on an empty result page.

    Prefix matches rank above mid-string ones: typing "ver" should offer
    "Verification Engineer" before "Design Verification Engineer".
    """
    q = (q or "").strip()
    if len(q) < 2:
        return {"suggestions": []}

    pattern = f"%{q}%"
    prefix = f"{q}%"
    browseable = [
        JobPosting.active_status == "active",
        (JobPosting.is_usa == True) | (JobPosting.location_confidence == 0.0),  # noqa: E712
    ]
    # Rank 0 = starts with the query, 1 = contains it. Sorts before count.
    def _rank(field):
        return case((col(field).ilike(prefix), 0), else_=1)

    out: list[dict] = []
    seen: set[str] = set()

    # normalized_title is stored lowercased; title-casing it for display would
    # render the domain's acronyms as "Dft"/"Rtl"/"Soc", so restore those.
    _ACRONYMS = {
        "rtl", "dft", "dv", "soc", "asic", "uvm", "pcie", "cxl", "ai", "ml",
        "sta", "pd", "noc", "ip", "fpga", "io", "ddr", "hbm", "aps", "cpu",
        "gpu", "tpu", "eda", "vlsi", "ate", "slt", "phy", "usb", "axi", "amba",
    }

    def _pretty(value: str) -> str:
        if not value or not value.islower():
            return value
        return " ".join(
            w.upper() if w.strip("-/()") in _ACRONYMS else w.capitalize()
            for w in value.split()
        )

    def _collect(field, kind: str, cap: int) -> None:
        rank = _rank(field)
        rows = session.exec(
            select(field, func.count().label("n"), rank.label("r"))
            .where(col(field).ilike(pattern), *browseable)
            .group_by(field, rank)
            .order_by(rank.asc(), func.count().desc())
            .limit(cap)
        ).all()
        for value, n, _r in rows:
            key = (value or "").strip().lower()
            if not key or key in seen:
                continue
            seen.add(key)
            out.append({"value": _pretty(value), "type": kind, "count": n})

    # Companies first — an exact company name is the most decisive query.
    _collect(JobPosting.company, "company", 3)
    _collect(JobPosting.normalized_title, "title", limit)
    _collect(JobPosting.role_category, "skill", 3)

    # Companies keep their slot at the top; everything else by hit count.
    out.sort(key=lambda s: (s["type"] != "company", -s["count"]))
    return {"suggestions": out[:limit]}


# ── Resume intelligence (Phase 3) ────────────────────────────────────────────

def _active_resume(session: Session) -> Optional[ResumeProfile]:
    """The resume version marked active, else the most recent one."""
    rp = session.exec(
        select(ResumeProfile).where(ResumeProfile.is_active == True)  # noqa: E712
        .order_by(col(ResumeProfile.id).desc())
    ).first()
    if rp:
        return rp
    return session.exec(select(ResumeProfile).order_by(col(ResumeProfile.id).desc())).first()


def _current_profile(session: Session, resume_id: Optional[int] = None) -> Optional[dict]:
    """Parsed profile for a specific resume id, else the active resume."""
    rp = session.get(ResumeProfile, resume_id) if resume_id else _active_resume(session)
    if not rp or not rp.profile_json:
        return None
    try:
        return json.loads(rp.profile_json)
    except Exception:
        return None


# ── Résumé-ranking cache ──────────────────────────────────────────────────────
# Maps a (résumé, filters, sort) signature to the ranked [(job_id, match)] list.
# Only the ORDER and the per-job scores are cached — never job rows — so a page
# view after a hit reads just its 50 rows instead of re-reading every filtered
# job's description. TTL is short so a fresh scrape shows up quickly; the cache
# is also dropped outright whenever the résumé set changes.
_RANK_CACHE: dict[str, tuple[float, list[tuple[int, dict]]]] = {}
# The key carries a data version (see _data_version), so a completed scrape
# produces a different key and the old ranking is simply never consulted again.
# That makes correctness independent of the clock, and lets the TTL be long —
# it exists only to bound memory and to cover edits made outside a scrape.
_RANK_CACHE_TTL_SECONDS = 3600
_RANK_CACHE_MAX_ENTRIES = 24


def _data_version(session: Session) -> str:
    """Changes whenever a scrape finishes, so cached rankings retire by themselves.

    A time-based TTL alone was the wrong tool: views spread across the day would
    each land in a fresh window and re-read every filtered job's description,
    which is the cost this cache exists to avoid.
    """
    try:
        last = session.exec(
            select(func.max(ScrapeRun.id)).where(col(ScrapeRun.finished_at).is_not(None))
        ).one()
        return str(last or 0)
    except Exception:
        return "0"


def _profile_cache_id(session: Session, resume_id: Optional[int]) -> str:
    if resume_id:
        return str(resume_id)
    rp = _active_resume(session)
    return str(rp.id) if rp and rp.id else "none"


def _match_cache_key(*, profile_id: str, sort: str, parts: tuple) -> str:
    return "|".join([profile_id, sort or "match", *("" if p is None else str(p) for p in parts)])


def _rank_cache_get(key: str) -> Optional[list[tuple[int, dict]]]:
    hit = _RANK_CACHE.get(key)
    if not hit:
        return None
    ts, ranked = hit
    if (time.time() - ts) > _RANK_CACHE_TTL_SECONDS:
        _RANK_CACHE.pop(key, None)
        return None
    return ranked


def _rank_cache_put(key: str, ranked: list[tuple[int, dict]]) -> None:
    if len(_RANK_CACHE) >= _RANK_CACHE_MAX_ENTRIES:
        # Drop the oldest entry; this is a small bounded cache, not an LRU.
        oldest = min(_RANK_CACHE, key=lambda k: _RANK_CACHE[k][0])
        _RANK_CACHE.pop(oldest, None)
    _RANK_CACHE[key] = (time.time(), ranked)


def invalidate_rank_cache() -> None:
    """Drop every cached ranking — call when the résumé set changes."""
    _RANK_CACHE.clear()


def _serialize_ranked_page(session: Session, ranked: list[tuple[int, dict]],
                           page: int, limit: int) -> dict:
    """Build one page from a cached ranking, reading only that page's rows."""
    total = len(ranked)
    start = (page - 1) * limit
    window = ranked[start:start + limit]
    ids = [jid for jid, _ in window]
    rows = {}
    if ids:
        fetched = session.exec(
            select(JobPosting)
            .where(col(JobPosting.id).in_(ids))
            .options(defer(JobPosting.full_description_text), defer(JobPosting.cleaned_description))
        ).all()
        rows = {j.id: j for j in fetched}
    items = []
    for jid, m in window:
        job = rows.get(jid)
        if job is None:      # deleted since the ranking was computed
            continue
        job.__dict__["full_description_text"] = ""
        job.__dict__["cleaned_description"] = ""
        item = JobResponse.model_validate(job).model_dump()
        item["cleaned_description"] = ""
        item.update({k: m[k] for k in (
            "resume_match", "new_grad_fit", "experienced_fit", "overall_recommendation",
            "match_breakdown", "defensibility", "apply_priority", "apply_priority_score",
            "matched_skills", "missing_skills",
        ) if k in m})
        items.append(item)
    total_pages = max(1, (total + limit - 1) // limit)
    return {"items": items, "total_count": total, "page": page, "limit": limit,
            "total_pages": total_pages, "has_next": page < total_pages, "has_prev": page > 1}


def _job_match_input(job: JobPosting) -> dict:
    now = datetime.now(timezone.utc)
    fs = job.first_seen_at
    is_fresh = False
    if fs:
        if fs.tzinfo is None:
            fs = fs.replace(tzinfo=timezone.utc)
        is_fresh = (now - fs) < timedelta(hours=24)
    return {
        "job_title": job.job_title, "cleaned_description": job.cleaned_description,
        "matched_keywords": job.matched_keywords, "role_category": job.role_category,
        "job_skills": job.job_skills, "company": job.company, "company_priority": job.company_priority,
        "match_score": job.match_score, "is_candidate_friendly": job.is_candidate_friendly,
        "eligibility_risk": job.eligibility_risk, "sponsors_h1b": job.sponsors_h1b,
        "is_fresh": is_fresh,
        # Seniority context + stored job-intrinsic fit scores
        "experience_level": job.experience_level, "is_senior": job.is_senior,
        "is_entry_level": job.is_entry_level, "years_required_min": job.years_required_min,
        "new_grad_fit": job.new_grad_fit, "experienced_fit": job.experienced_fit,
    }


def _resume_brief(rp: ResumeProfile) -> dict:
    try:
        prof = json.loads(rp.profile_json) if rp.profile_json else {}
    except Exception:
        prof = {}
    return {
        "id": rp.id,
        "label": rp.label or (prof.get("role_focus") or rp.filename or f"Resume {rp.id}"),
        "filename": rp.filename,
        "is_active": rp.is_active,
        "uploaded_at": rp.uploaded_at,
        "role_focus": prof.get("role_focus", ""),
        "skill_count": len(prof.get("all_skills", []) or []),
    }


# ── Stateless résumé service ──────────────────────────────────────────────────
# The job corpus is now a static file and there is no database. Résumé matching
# stays in Python because it is 500 lines of tuned scoring that would drift if
# reimplemented — but it no longer STORES anything. The browser holds the parsed
# profile and sends it with each request, so these endpoints are pure functions:
# nothing to persist, nothing to exhaust, nothing to lose.

class ParsedResume(BaseModel):
    profile: dict
    filename: str = ""
    label: str = ""


@app.post("/resume/parse", response_model=ParsedResume)
async def parse_resume_stateless(file: UploadFile = File(...), label: str = Form(default="")):
    """PDF/DOCX in, parsed profile out. Nothing is written anywhere."""
    from .resume_parser import parse_resume
    data = await file.read()
    if len(data) > 8 * 1024 * 1024:
        raise HTTPException(status_code=413, detail="Resume too large (max 8 MB)")
    try:
        profile = parse_resume(data, file.filename or "resume.txt")
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"Could not parse resume: {e}")
    prof = profile.to_dict()
    return ParsedResume(
        profile=prof,
        filename=file.filename or "",
        label=(label or "").strip() or prof.get("role_focus", "") or (file.filename or ""),
    )


class MatchRequest(BaseModel):
    profile: dict
    jobs: list[dict]
    full: bool = False          # full=True returns the detail view's extras


@app.post("/resume/match")
def match_stateless(req: MatchRequest):
    """Score a batch of postings against a profile the caller supplies.

    The caller already has the corpus, so it sends the fields the scorer reads
    rather than the server re-fetching them. Capped so one request cannot be
    used to pin the free instance.
    """
    if not req.profile:
        raise HTTPException(status_code=400, detail="No résumé profile supplied")
    if len(req.jobs) > 4000:
        raise HTTPException(status_code=413, detail="Too many jobs in one request")
    from .resume_match import compute_match
    out = []
    for job in req.jobs:
        try:
            m = compute_match(req.profile, job, lite=not req.full)
        except Exception:
            continue                     # one bad row must not fail the batch
        m["id"] = job.get("id")
        out.append(m)
    return {"matches": out}


@app.get("/resume/skill-gaps-for")
def skill_gaps_stateless(skills: str = "", top: int = 12):
    """Kept for parity; the client computes gaps from the corpus it already has."""
    return {"gaps": []}


@app.post("/resume/upload")
async def upload_resume(session: SessionDep, file: UploadFile = File(...), label: str = Form(default="")):
    invalidate_rank_cache()  # résumé set changed → cached rankings are stale
    from .resume_parser import parse_resume
    data = await file.read()
    if len(data) > 8 * 1024 * 1024:
        raise HTTPException(status_code=413, detail="Resume too large (max 8 MB)")
    try:
        profile = parse_resume(data, file.filename or "resume.txt")
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"Could not parse resume: {e}")
    # New upload becomes the active version; demote the others (keep them).
    for other in session.exec(select(ResumeProfile)).all():
        if other.is_active:
            other.is_active = False
            session.add(other)
    prof_dict = profile.to_dict()
    rp = ResumeProfile(
        filename=file.filename or "",
        label=(label or "").strip() or prof_dict.get("role_focus", "") or (file.filename or ""),
        is_active=True,
        profile_json=json.dumps(prof_dict),
    )
    session.add(rp)
    session.commit()
    session.refresh(rp)
    return {"ok": True, "id": rp.id, "profile": prof_dict, "filename": file.filename, "label": rp.label}


@app.get("/resumes")
def list_resumes(session: SessionDep):
    rows = session.exec(select(ResumeProfile).order_by(col(ResumeProfile.id).desc())).all()
    return [_resume_brief(r) for r in rows]


@app.get("/resume")
def get_resume(session: SessionDep):
    rp = _active_resume(session)
    if not rp or not rp.profile_json:
        return {"profile": None}
    return {"profile": json.loads(rp.profile_json), "filename": rp.filename,
            "uploaded_at": rp.uploaded_at, "id": rp.id, "label": rp.label}


@app.post("/resume/{resume_id}/activate")
def activate_resume(resume_id: int, session: SessionDep):
    invalidate_rank_cache()  # résumé set changed → cached rankings are stale
    target = session.get(ResumeProfile, resume_id)
    if not target:
        raise HTTPException(status_code=404, detail="Resume not found")
    for r in session.exec(select(ResumeProfile)).all():
        r.is_active = (r.id == resume_id)
        session.add(r)
    session.commit()
    return {"ok": True, "active_id": resume_id}


@app.delete("/resume/{resume_id}")
def delete_resume_one(resume_id: int, session: SessionDep):
    invalidate_rank_cache()  # résumé set changed → cached rankings are stale
    rp = session.get(ResumeProfile, resume_id)
    if rp:
        was_active = rp.is_active
        session.delete(rp)
        session.commit()
        if was_active:
            nxt = session.exec(select(ResumeProfile).order_by(col(ResumeProfile.id).desc())).first()
            if nxt:
                nxt.is_active = True
                session.add(nxt)
                session.commit()
    return {"ok": True}


@app.delete("/resume")
def delete_resume(session: SessionDep):
    invalidate_rank_cache()  # résumé set changed → cached rankings are stale
    """Delete all resume versions (legacy 'remove resume' action)."""
    for old in session.exec(select(ResumeProfile)).all():
        session.delete(old)
    session.commit()
    return {"ok": True}


@app.delete("/account/data")
def delete_all_my_data(session: SessionDep):
    invalidate_rank_cache()  # résumé set changed → cached rankings are stale
    """Erase all personal data stored by the app: uploaded résumés + parsed
    profiles, the saved master-résumé LaTeX / tailoring instructions, saved
    searches (watchlists), and push-notification subscriptions. Public job
    postings are not personal data and are unaffected. Backs the 'Delete my data'
    control required for app-store privacy compliance."""
    deleted = {"resumes": 0, "settings": 0, "watchlists": 0, "push_subscriptions": 0}
    for r in session.exec(select(ResumeProfile)).all():
        session.delete(r); deleted["resumes"] += 1
    for key in (_MASTER_LATEX_KEY, _TAILOR_INSTRUCTIONS_KEY):
        s = session.get(Setting, key)
        if s:
            session.delete(s); deleted["settings"] += 1
    for w in session.exec(select(Watchlist)).all():
        session.delete(w); deleted["watchlists"] += 1
    for ps in session.exec(select(PushSubscription)).all():
        session.delete(ps); deleted["push_subscriptions"] += 1
    session.commit()
    return {"ok": True, "deleted": deleted}


@app.get("/jobs/resume-matches")
def resume_matches(session: SessionDep, page: int = 1, limit: int = Query(default=50, ge=1, le=200),
                   include_senior: bool = False, resume_id: Optional[int] = None, sort: str = "match",
                   # ── Same shared filter contract as /jobs ──
                   company: Optional[str] = None, company_ids: Optional[str] = None,
                   priority: Optional[str] = None, role_category: Optional[str] = None,
                   level_filter: Optional[str] = None, remote: Optional[str] = None,
                   min_score: Optional[int] = None, posted_within_hours: Optional[int] = None,
                   new_since_hours: Optional[int] = None, keyword: Optional[str] = None,
                   skills: Optional[str] = None, usa_only: bool = True,
                   include_unknown_location: bool = False, include_software: bool = False,
                   role_flags: Optional[str] = None, state: Optional[str] = None,
                   h1b_only: bool = False):
    profile = _current_profile(session, resume_id)
    if not profile:
        return {"items": [], "total_count": 0, "page": 1, "limit": limit,
                "total_pages": 1, "has_next": False, "has_prev": False, "no_resume": True}
    from .resume_match import compute_match
    # 1. Apply ALL active filters through the shared query builder (same contract as
    # /jobs), then 2. compute the resume match, then 3. rank. Pull the full filtered
    # set (high limit) so ranking/pagination happen over the filtered jobs.
    #
    # Ranking needs cleaned_description (~2.2 KB/row) for EVERY filtered job, so a
    # single view of this tab moves ~1.8 MB. That is fine once and ruinous on
    # repeat: paging, re-sorting and tab-switching all re-run it, and at ~50
    # views/day it alone exceeds the database's 5 GB monthly transfer quota —
    # the same quota that has been exhausted twice. So the ranked order is
    # cached and only the current page is re-read. See _rank_cache_get.
    cache_key = _match_cache_key(profile_id=_profile_cache_id(session, resume_id), sort=sort, parts=(
        _data_version(session),
        company, company_ids, priority, role_category, level_filter, remote, min_score,
        posted_within_hours, new_since_hours, keyword, skills, usa_only, include_senior,
        include_unknown_location, include_software, role_flags, state, h1b_only,
    ))
    cached = _rank_cache_get(cache_key)
    if cached is not None:
        return _serialize_ranked_page(session, cached, page, limit)

    jobs, _ = _build_job_query(
        session, company=company, company_ids=company_ids, priority=priority,
        role_category=role_category, level_filter=level_filter, remote=remote,
        min_score=min_score, posted_within_hours=posted_within_hours,
        new_since_hours=new_since_hours, keyword=keyword, skills=skills,
        usa_only=usa_only, include_senior=include_senior,
        include_unknown_location=include_unknown_location, include_software=include_software,
        role_flags=role_flags, state=state, h1b_only=h1b_only,
        keep_cleaned=True, page=1, limit=5000,   # ranking reads cleaned_description
    )
    # Score every filtered job with the LITE path (fast — no per-job interview
    # prep / suggestions), rank, then fully serialize ONLY the current page. This
    # keeps the endpoint responsive on the free tier even with hundreds of jobs.
    scored = [(job, compute_match(profile, _job_match_input(job), lite=True)) for job in jobs]
    bd = lambda m, k: (m.get("match_breakdown") or {}).get(k, 0)  # noqa: E731
    # "Newest posted": rank jobs with a REAL posted date first (by that date), then
    # undated jobs (by first-seen) — so an undated "Added today" never outranks a
    # genuinely "Posted yesterday" job. Tuple sorts with reverse=True.
    _fresh = lambda job: (1 if getattr(job, "posted_date", None) else 0,  # noqa: E731
                          str(getattr(job, "posted_date", None) or getattr(job, "first_seen_at", None) or ""))
    # Recruiter-grade sorts. New Grad Fit is the primary candidate signal; each
    # breaks ties on a second signal so the orderings are genuinely distinct.
    #   new_grad_fit — most realistic for a new grad first
    #   match        — level-aware apply-priority blend (default "Best match")
    #   resume_match — raw resume↔JD overlap, regardless of level
    #   apply_priority / experience — alias of the blend / level realism
    #   newest       — by trusted posted date
    #   recent       — by when we first saw it
    sort_keys = {
        "new_grad_fit": lambda t: (t[1]["new_grad_fit"], t[1]["resume_match"]),
        "match": lambda t: (t[1].get("apply_priority_score", 0), t[1]["resume_match"]),
        "resume_match": lambda t: (t[1]["resume_match"], t[1]["new_grad_fit"]),
        "apply_priority": lambda t: (t[1].get("apply_priority_score", 0), t[1]["new_grad_fit"]),
        "experience": lambda t: (bd(t[1], "experience"), t[1]["resume_match"]),
        "newest": lambda t: (_fresh(t[0]), t[1]["resume_match"]),
        "recent": lambda t: (str(getattr(t[0], "first_seen_at", None) or ""), t[1]["resume_match"]),
    }
    scored.sort(key=sort_keys.get(sort, sort_keys["match"]), reverse=True)
    # Cache the ranked order + scores so paging/re-sorting doesn't re-read every
    # filtered job's description (see the note at the query above).
    _rank_cache_put(cache_key, [(job.id, m) for job, m in scored if job.id is not None])
    total = len(scored)
    start = (page - 1) * limit
    page_items = []
    for job, m in scored[start:start + limit]:
        item = JobResponse.model_validate(job).model_dump()
        # cleaned_description was loaded for ranking; don't ship it (the detail
        # view fetches the full text on demand). Keeps the list payload small.
        item["cleaned_description"] = ""
        item["resume_match"] = m["resume_match"]
        item["new_grad_fit"] = m["new_grad_fit"]
        item["experienced_fit"] = m["experienced_fit"]
        item["overall_recommendation"] = m["overall_recommendation"]
        item["match_breakdown"] = m["match_breakdown"]
        item["defensibility"] = m["defensibility"]
        item["apply_priority"] = m["apply_priority"]
        item["apply_priority_score"] = m["apply_priority_score"]
        item["matched_skills"] = m["matched_skills"]
        item["missing_skills"] = m["missing_skills"]
        page_items.append(item)
    total_pages = max(1, (total + limit - 1) // limit)
    return {"items": page_items, "total_count": total, "page": page, "limit": limit,
            "total_pages": total_pages, "has_next": page < total_pages, "has_prev": page > 1}


@app.post("/jobs/match-batch")
def job_match_batch(payload: dict, session: SessionDep):
    profile = _current_profile(session)
    if not profile:
        return {"matches": {}}
    from .resume_match import compute_match
    ids = (payload.get("ids") or [])[:120]
    out: dict[str, Any] = {}
    for jid in ids:
        job = session.get(JobPosting, jid)
        if job:
            m = compute_match(profile, _job_match_input(job), lite=True)
            out[str(jid)] = {"resume_match": m["resume_match"], "apply_priority": m["apply_priority"]}
    return {"matches": out}


@app.get("/resume/skill-gaps")
def skill_gaps(session: SessionDep, min_match: int = 45):
    profile = _current_profile(session)
    if not profile:
        return {"gaps": [], "high_match_jobs": 0, "no_resume": True}
    from collections import Counter
    from .resume_match import compute_match
    conds = [JobPosting.active_status == "active",
             (JobPosting.is_usa == True) | (JobPosting.location_confidence == 0.0),
             JobPosting.is_software_only == False, JobPosting.is_senior == False]
    jobs = session.exec(select(JobPosting).where(*conds)).all()
    counter: Counter = Counter()
    n_high = 0
    for job in jobs:
        m = compute_match(profile, _job_match_input(job))
        if m["resume_match"] >= min_match:
            n_high += 1
            for sk in m["missing_skills"]:
                counter[sk] += 1
    gaps = [{"skill": s, "count": n} for s, n in counter.most_common(15)]
    return {"gaps": gaps, "high_match_jobs": n_high}


@app.get("/jobs/{job_id}/locations")
def job_locations(job_id: int, session: SessionDep):
    """Every OTHER open requisition for the same role at the same company.

    Role grouping shows one card per (company, title); this is how the card's
    "+N locations" expands. The siblings are real, separately-applicable reqs
    with their own apply URLs — grouping is a presentation choice, so nothing
    may become unreachable because of it.
    """
    job = session.get(JobPosting, job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")
    key = (job.normalized_title or job.job_title or "").lower()
    rows = session.exec(
        select(JobPosting)
        .where(
            func.lower(col(JobPosting.company)) == job.company.lower(),
            func.lower(func.coalesce(col(JobPosting.normalized_title), col(JobPosting.job_title))) == key,
            JobPosting.active_status == ActiveStatus.active,
            col(JobPosting.id) != job_id,
        )
        .order_by(col(JobPosting.location))
        .limit(50)
    ).all()
    return {
        "siblings": [
            {
                "id": r.id, "location": r.location or "", "state": r.state or "",
                "apply_url": r.apply_url, "posted_date": r.posted_date,
                "remote_status": r.remote_status or "",
            }
            for r in rows
        ]
    }


@app.get("/jobs/{job_id}/match")
def job_match(job_id: int, session: SessionDep, resume_id: Optional[int] = None):
    profile = _current_profile(session, resume_id)
    if not profile:
        raise HTTPException(status_code=404, detail="No resume uploaded")
    job = session.get(JobPosting, job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")
    from .resume_match import compute_match
    return compute_match(profile, _job_match_input(job))


@app.get("/jobs/{job_id}", response_model=JobResponse)
def get_job(job_id: int, session: SessionDep):
    job = session.get(JobPosting, job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")
    return job


@app.get("/jobs/{job_id}/similar", response_model=list[JobResponse])
def similar_jobs(job_id: int, session: SessionDep, limit: int = Query(default=6, ge=1, le=20)):
    """Content-based 'more like this': ranks active, USA-relevant roles that share
    this job's role category, seniority, company tier, and matched keywords.
    Cheap (one candidate query + in-Python scoring) — no ML/embeddings needed."""
    src = session.get(JobPosting, job_id)
    if not src:
        raise HTTPException(status_code=404, detail="Job not found")

    src_kws = {k.strip().lower() for k in (src.matched_keywords or "").split(",") if k.strip()}

    # Candidate pool: active, browseable (USA-or-unknown, non-software), and either
    # the same role category or the same company — keeps the scan small and relevant.
    pool = session.exec(
        select(JobPosting).where(
            JobPosting.active_status == ActiveStatus.active,
            JobPosting.id != src.id,
            (JobPosting.is_usa == True) | (JobPosting.location_confidence == 0.0),
            JobPosting.is_software_only == False,
            (JobPosting.role_category == src.role_category) | (JobPosting.company == src.company),
        ).limit(500)
    ).all()

    def score(j: JobPosting) -> tuple[int, int]:
        s = 0
        if j.role_category == src.role_category and src.role_category != "Unknown":
            s += 4
        if j.experience_level == src.experience_level:
            s += 2
        if j.is_senior == src.is_senior:
            s += 1
        if j.company_priority == src.company_priority:
            s += 1
        j_kws = {k.strip().lower() for k in (j.matched_keywords or "").split(",") if k.strip()}
        s += min(4, len(src_kws & j_kws))
        if j.company != src.company:   # mild nudge to broaden beyond the same company
            s += 1
        return (s, j.new_grad_fit)

    seen: set = set()
    out: list[JobPosting] = []
    for j in sorted(pool, key=score, reverse=True):
        key = (j.company, j.normalized_title or j.job_title.lower())
        if key in seen:
            continue
        seen.add(key)
        out.append(j)
        if len(out) >= limit:
            break
    return out


@app.patch("/jobs/{job_id}/status")
def update_job_status(job_id: int, update: StatusUpdate, session: SessionDep):
    job = session.get(JobPosting, job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")

    now = datetime.now(timezone.utc)
    if update.active_status:
        if update.active_status not in VALID_STATUSES:
            raise HTTPException(status_code=400, detail="Invalid status")
        job.active_status = update.active_status
        if update.active_status == "saved" and not job.saved_at:
            job.saved_at = now
        elif update.active_status == "applied" and not job.applied_at:
            job.applied_at = now
        elif update.active_status == "ignored" and not job.ignored_at:
            job.ignored_at = now

    if update.application_status is not None:
        job.application_status = update.application_status
        # Pipeline stage implies the job belongs in the Applied workspace.
        if update.application_status in ("Applied", "Assessment", "Interview", "Offer") and not job.applied_at:
            job.applied_at = now
            if job.active_status not in ("applied",):
                job.active_status = ActiveStatus.applied
    if update.notes is not None:
        job.notes = update.notes
    if update.resume_version_used is not None:
        job.resume_version_used = update.resume_version_used
    if update.follow_up_date is not None:
        job.follow_up_date = update.follow_up_date
    if update.confirmation_id is not None:
        job.confirmation_id = update.confirmation_id
    if update.recruiter_contact is not None:
        job.recruiter_contact = update.recruiter_contact

    session.add(job)
    session.commit()
    return {"ok": True}


# Keep old POST endpoint for backward compat
@app.post("/jobs/{job_id}/status")
def update_job_status_post(job_id: int, update: StatusUpdate, session: SessionDep):
    return update_job_status(job_id, update, session)


@app.patch("/jobs/{job_id}/notes")
def update_notes(job_id: int, notes: str, session: SessionDep):
    job = session.get(JobPosting, job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")
    job.notes = notes
    session.add(job)
    session.commit()
    return {"ok": True}


# ── Company endpoints ──────────────────────────────────────────────────────────

def _company_stats_map(session: Session) -> dict[str, dict]:
    """All per-company active-job aggregates in ONE grouped query, keyed by
    company name. Replaces ~7 queries PER company (≈600 round trips across 87
    companies — the reason the Companies / Data Health tabs took ages) with a
    single GROUP BY scan."""
    cutoff_24h = datetime.now(timezone.utc) - timedelta(hours=24)
    active = JobPosting.active_status == ActiveStatus.active
    rows = session.exec(
        select(
            JobPosting.company,
            func.count().label("total"),
            func.count().filter(JobPosting.is_usa == True).label("usa"),
            func.count().filter(
                (JobPosting.is_entry_level == True) | (JobPosting.is_candidate_friendly == True)
            ).label("entry"),
            func.count().filter(and_(
                JobPosting.is_usa == True,
                JobPosting.is_software_only == False,
                JobPosting.is_senior == False,
            )).label("relevant"),
            # viewable = EXACTLY what clicking "View Jobs" shows in All Jobs
            # (usa-or-unknown-location, non-software, senior included) so the
            # card count always equals the list the user then sees.
            func.count().filter(and_(
                (JobPosting.is_usa == True) | (JobPosting.location_confidence == 0.0),
                JobPosting.is_software_only == False,
            )).label("viewable"),
            func.count().filter(_effective_date() >= cutoff_24h).label("new_today"),
            func.avg(JobPosting.data_quality_score).label("avg_quality"),
        ).where(active).group_by(JobPosting.company)
    ).all()
    out: dict[str, dict] = {}
    for r in rows:
        out[r[0]] = {
            "total": r[1] or 0, "usa": r[2] or 0, "entry": r[3] or 0,
            "relevant": r[4] or 0, "viewable": r[5] or 0, "new_today": r[6] or 0,
            "parser_confidence": int(round(r[7])) if r[7] else 0,
        }
    return out


def _build_company_response(company: Company, stats: dict[str, dict], engine: str) -> dict:
    """Pure assembly from precomputed stats — does NO database queries. Pass the
    map from _company_stats_map() and the engine flag (computed once per request)."""
    s = stats.get(company.name, {})
    total = s.get("total", 0)
    relevant = s.get("relevant", 0)
    viewable = s.get("viewable", 0)
    usa = s.get("usa", 0)
    entry = s.get("entry", 0)
    new_today = s.get("new_today", 0)
    parser_confidence = s.get("parser_confidence", 0)

    # Scrape status
    if company.scrape_error_count > 3:
        scrape_status = "failed"
    elif company.scrape_error_count > 0:
        scrape_status = "warning"
    elif company.last_scraped_at:
        scrape_status = "healthy"
    else:
        scrape_status = "never"

    # Auto-connected = scraped automatically by SOME engine: the httpx cloud
    # scheduler (enabled:true) OR a local/CI runner (engine cf/browser). The latter
    # are enabled:false in the YAML so the cloud scheduler skips them, but they ARE
    # auto-scraped — so they must not be mislabeled "Direct search".
    auto_connected = bool(company.enabled) or engine in ("cf", "browser")

    return {
        "id": company.id,
        "name": company.name,
        "category": company.category,
        "priority": company.priority,
        "careers_url": company.careers_url,
        "company_search_url": getattr(company, "company_search_url", "") or "",
        "ats_platform": company.ats_platform,
        "enabled": company.enabled,
        "engine": engine,
        "auto_connected": auto_connected,
        "last_scraped_at": company.last_scraped_at,
        "scrape_error_count": company.scrape_error_count,
        "total_active_jobs": total,
        "relevant_active_jobs": relevant,
        "viewable_jobs": viewable,
        "usa_active_jobs": usa,
        "entry_level_jobs": entry,
        "new_jobs_today": new_today,
        "scrape_status": scrape_status,
        "parser_confidence": parser_confidence,
    }


@app.get("/companies")
def list_companies(session: SessionDep, with_counts: bool = True):
    companies = session.exec(select(Company).order_by(Company.priority, Company.name)).all()
    if with_counts:
        from .config import company_engines
        stats = _company_stats_map(session)
        engines = company_engines()
        return [_build_company_response(c, stats, engines.get(c.name.lower(), "")) for c in companies]
    return [{"id": c.id, "name": c.name, "category": c.category, "priority": c.priority,
             "careers_url": c.careers_url, "ats_platform": c.ats_platform,
             "enabled": c.enabled, "last_scraped_at": c.last_scraped_at} for c in companies]


@app.get("/companies/{company_id}")
def get_company(company_id: int, session: SessionDep):
    company = session.get(Company, company_id)
    if not company:
        raise HTTPException(status_code=404, detail="Company not found")
    from .config import company_engines
    stats = _company_stats_map(session)
    return _build_company_response(company, stats, company_engines().get(company.name.lower(), ""))


@app.get("/companies/{company_id}/jobs", response_model=PaginatedJobResponse)
def company_jobs(
    company_id: int,
    session: SessionDep,
    page: int = 1,
    limit: int = 50,
    usa_only: bool = False,
    include_senior: bool = True,
):
    company = session.get(Company, company_id)
    if not company:
        raise HTTPException(status_code=404, detail="Company not found")
    items, total = _build_job_query(
        session, company=company.name, usa_only=usa_only,
        include_senior=include_senior, page=page, limit=limit,
    )
    return _paginate(items, total, page, limit)


# ── Scrape endpoints ────────────────────────────────────────────────────────────

@app.get("/scrape-runs", response_model=list[ScrapeRunResponse])
def list_scrape_runs(session: SessionDep, limit: int = 20):
    stmt = select(ScrapeRun).order_by(col(ScrapeRun.started_at).desc()).limit(limit)
    return session.exec(stmt).all()


@app.post("/scrape/run-now")
async def trigger_scrape(background_tasks: BackgroundTasks):
    async def _run():
        from .scrape_engine import run_scrape
        await run_scrape(triggered_by="manual")
    background_tasks.add_task(_run)
    return {"message": "Scrape started", "triggered_by": "manual"}


@app.get("/scrape-errors")
def scrape_errors(session: SessionDep, limit: int = 50):
    stmt = select(ScrapeError).order_by(col(ScrapeError.occurred_at).desc()).limit(limit)
    return session.exec(stmt).all()


# How often each engine is scheduled to run, in hours. A run is only counted as
# healthy if it FINISHED and actually visited at least one company — a run that
# touched nothing is the exact shape the three-day silent outage had.
_ENGINE_CADENCE_HOURS = {
    "github-actions": 3,   # scrape.yml  — httpx pass
    "cf": 3,               # scrape.yml  — curl_cffi pass
    "browser": 8,          # scrape-giants.yml
}


def _pipeline_health(session: Session) -> dict:
    """Per-engine verdict on whether scraping is actually happening.

    Exists so a dead pipeline is visible in the app itself. The three-day outage
    was only noticed because one workflow happened to email; the other reported
    green while scraping nothing, and nothing in the UI contradicted it.
    """
    now = datetime.now(timezone.utc)
    engines: list[dict] = []
    worst = "ok"
    for name, cadence in _ENGINE_CADENCE_HOURS.items():
        last = session.exec(
            select(ScrapeRun)
            .where(
                ScrapeRun.triggered_by == name,
                col(ScrapeRun.finished_at).is_not(None),
                ScrapeRun.companies_scraped > 0,
            )
            .order_by(col(ScrapeRun.started_at).desc())
        ).first()
        if last is None:
            status, age_h = "down", None
        else:
            started = last.started_at
            if started.tzinfo is None:
                started = started.replace(tzinfo=timezone.utc)
            age_h = round((now - started).total_seconds() / 3600, 1)
            # One missed cycle is normal (a run can overlap or retry); two is a
            # warning; beyond four the engine is not running at all.
            status = "ok" if age_h <= cadence * 2 else ("stale" if age_h <= cadence * 4 else "down")
        if status == "down" or (status == "stale" and worst == "ok"):
            worst = status
        engines.append({
            "engine": name,
            "cadence_hours": cadence,
            "status": status,
            "hours_since_last_good_run": age_h,
            "last_good_run_at": last.started_at if last else None,
            "companies_scraped": last.companies_scraped if last else 0,
            "new_jobs": last.new_jobs if last else 0,
        })

    freshest = session.exec(select(func.max(JobPosting.last_seen_at))).one()
    if freshest is not None and freshest.tzinfo is None:
        freshest = freshest.replace(tzinfo=timezone.utc)
    return {
        "status": worst,
        "engines": engines,
        "last_job_seen_at": freshest,
        "hours_since_any_job_seen": (
            round((now - freshest).total_seconds() / 3600, 1) if freshest else None
        ),
    }


@app.get("/scrape-health")
def scrape_health(session: SessionDep):
    runs = session.exec(
        select(ScrapeRun).order_by(col(ScrapeRun.started_at).desc()).limit(20)
    ).all()
    recent_errors = session.exec(
        select(ScrapeError).order_by(col(ScrapeError.occurred_at).desc()).limit(20)
    ).all()
    from .config import company_engines
    companies = session.exec(select(Company)).all()
    stats = _company_stats_map(session)
    engines = company_engines()
    company_data = [_build_company_response(c, stats, engines.get(c.name.lower(), "")) for c in companies]

    return {
        "pipeline": _pipeline_health(session),
        "recent_runs": [
            {
                "id": r.id, "started_at": r.started_at, "finished_at": r.finished_at,
                "companies_scraped": r.companies_scraped, "jobs_found": r.jobs_found,
                "new_jobs": r.new_jobs, "removed_jobs": r.removed_jobs,
                "errors": r.errors, "triggered_by": r.triggered_by,
            }
            for r in runs
        ],
        "recent_errors": [
            {"company": e.company, "error_message": e.error_message, "occurred_at": e.occurred_at}
            for e in recent_errors
        ],
        "companies": company_data,
    }


# ── Stats / Analytics ──────────────────────────────────────────────────────────

@app.get("/analytics/summary")
def analytics_summary(session: SessionDep):
    now = datetime.now(timezone.utc)
    cutoff_24h = now - timedelta(hours=24)

    active_cond = JobPosting.active_status == ActiveStatus.active
    # USA-relevant browseable pool (USA or unknown-location, non-software) — the
    # SAME pool the All Jobs list shows, so "Verified Active" always equals the
    # list count and every card reconciles. USA is a hard gate here.
    usa_view = and_(
        (JobPosting.is_usa == True) | (JobPosting.location_confidence == 0.0),
        JobPosting.is_software_only == False,
    )

    # Each dashboard number is one COUNT(*) FILTER (WHERE …) column inside a
    # SINGLE query. Render (Oregon) and Neon (us-east) are far apart, so each
    # separate query cost a ~70 ms cross-country round trip — 16 of them made
    # this endpoint ~2.5 s. One query = one round trip = one table scan.
    specs = [
        ("total_active",       [active_cond, usa_view]),
        ("new_24h",            [active_cond, usa_view, _effective_date() >= cutoff_24h]),
        ("entry_level",        [active_cond, usa_view,
                                (JobPosting.is_entry_level == True) | (JobPosting.is_candidate_friendly == True),
                                JobPosting.is_senior == False]),
        ("strict_entry",       [active_cond, usa_view, JobPosting.is_entry_level == True, JobPosting.is_senior == False]),
        ("candidate_friendly", [active_cond, usa_view, JobPosting.is_candidate_friendly == True,
                                JobPosting.is_entry_level == False, JobPosting.is_senior == False]),
        ("usa_count",          [active_cond, JobPosting.is_usa == True]),
        ("remote_count",       [active_cond, usa_view, col(JobPosting.remote_status).in_(["Remote", "remote"])]),
        ("total_in_db",        []),
        ("active_all",         [active_cond]),
        ("non_usa_filtered",   [active_cond, JobPosting.is_usa == False, JobPosting.location_confidence != 0.0]),
        ("software_filtered",  [active_cond, JobPosting.is_software_only == True]),
        ("senior_filtered",    [active_cond, usa_view, JobPosting.is_senior == True]),
        ("high_score",         [active_cond, usa_view, JobPosting.new_grad_fit >= 70]),
        ("strong_new_grad",    [active_cond, usa_view, JobPosting.new_grad_fit >= 75]),
        ("saved",              [JobPosting.active_status == ActiveStatus.saved]),
        ("applied",            [JobPosting.active_status == ActiveStatus.applied]),
    ]
    cols = [
        (func.count().filter(and_(*conds)) if conds else func.count()).label(name)
        for name, conds in specs
    ]
    row = session.exec(select(*cols)).one()
    v = {name: (val or 0) for name, val in zip([s[0] for s in specs], row)}

    total_active = v["total_active"]
    new_24h = v["new_24h"]
    entry_level = v["entry_level"]
    strict_entry = v["strict_entry"]
    candidate_friendly = v["candidate_friendly"]
    usa_count = v["usa_count"]
    remote_count = v["remote_count"]
    high_score = v["high_score"]
    strong_new_grad = v["strong_new_grad"]
    saved = v["saved"]
    applied = v["applied"]

    # ── Inventory funnel (reconciles "Found N" on Data Health with the count
    # shown on the dashboard, so the numbers never look contradictory). ──
    job_inventory = {
        "scanned_last_run": None,          # filled from last_run below
        "total_in_db": v["total_in_db"],
        "active": v["active_all"],
        "usa_relevant": total_active,      # == the dashboard / All Jobs list count
        "non_usa_filtered": v["non_usa_filtered"],
        "software_filtered": v["software_filtered"],
        "senior_roles": v["senior_filtered"],
    }
    # Auto-connected = httpx cloud (enabled) + curl_cffi/browser runner companies.
    from .config import company_engines
    _engines = company_engines()
    total_companies = sum(
        1 for c in session.exec(select(Company)).all()
        if c.enabled or _engines.get(c.name.lower(), "") in ("cf", "browser")
    )

    last_run = session.exec(
        select(ScrapeRun).order_by(col(ScrapeRun.started_at).desc()).limit(1)
    ).first()
    if last_run:
        job_inventory["scanned_last_run"] = last_run.jobs_found

    return {
        "total_active": total_active,
        "new_24h": new_24h,
        "entry_level_count": entry_level,
        "strict_entry_count": strict_entry,
        "candidate_friendly_count": candidate_friendly,
        "usa_count": usa_count,
        "remote_count": remote_count,
        "high_score_count": high_score,
        "strong_new_grad_count": strong_new_grad,
        "saved_count": saved,
        "applied_count": applied,
        "total_companies": total_companies,
        "job_inventory": job_inventory,
        "last_run": {
            "id": last_run.id,
            "started_at": last_run.started_at,
            "finished_at": last_run.finished_at,
            "companies_scraped": last_run.companies_scraped,
            "jobs_found": last_run.jobs_found,
            "new_jobs": last_run.new_jobs,
            "removed_jobs": last_run.removed_jobs,
            "errors": last_run.errors,
            "triggered_by": last_run.triggered_by,
        } if last_run else None,
    }


@app.get("/stats")
def stats(session: SessionDep):
    return analytics_summary(session)


# ── Watchlists / saved searches (Phase 4) ────────────────────────────────────

class WatchlistCreate(BaseModel):
    name: str
    filters: dict = {}
    alert_enabled: bool = True


_WL_FILTER_KEYS = {
    "keyword", "role_category", "level_filter", "state", "priority", "remote",
    "min_score", "company", "usa_only", "include_senior", "role_flags",
}


def _wl_counts(session: Session, filters: dict, since: datetime) -> tuple[int, int]:
    f = {k: v for k, v in (filters or {}).items() if k in _WL_FILTER_KEYS and v not in (None, "", [])}
    _, total = _build_job_query(session, page=1, limit=1, **f)
    if since.tzinfo is None:
        since = since.replace(tzinfo=timezone.utc)
    hours = max(1, int((datetime.now(timezone.utc) - since).total_seconds() // 3600) + 1)
    _, new = _build_job_query(session, page=1, limit=1, new_since_hours=hours, **f)
    return total, new


@app.get("/watchlists")
def list_watchlists(session: SessionDep):
    wls = session.exec(select(Watchlist).order_by(col(Watchlist.created_at).desc())).all()
    out = []
    for w in wls:
        try:
            filters = json.loads(w.filters_json) if w.filters_json else {}
        except Exception:
            filters = {}
        total, new = _wl_counts(session, filters, w.last_checked_at)
        out.append({
            "id": w.id, "name": w.name, "filters": filters, "alert_enabled": w.alert_enabled,
            "last_checked_at": w.last_checked_at, "total": total, "new_count": new,
        })
    return out


@app.post("/watchlists")
def create_watchlist(payload: WatchlistCreate, session: SessionDep):
    w = Watchlist(name=payload.name, filters_json=json.dumps(payload.filters or {}), alert_enabled=payload.alert_enabled)
    session.add(w); session.commit(); session.refresh(w)
    return {"ok": True, "id": w.id}


@app.delete("/watchlists/{wl_id}")
def delete_watchlist(wl_id: int, session: SessionDep):
    w = session.get(Watchlist, wl_id)
    if w:
        session.delete(w); session.commit()
    return {"ok": True}


@app.post("/watchlists/{wl_id}/check")
def check_watchlist(wl_id: int, session: SessionDep):
    w = session.get(Watchlist, wl_id)
    if not w:
        raise HTTPException(status_code=404, detail="Watchlist not found")
    w.last_checked_at = datetime.now(timezone.utc)
    session.add(w); session.commit()
    return {"ok": True}


def check_watchlists_and_notify(session: Session) -> int:
    """For each alert-enabled saved search, find jobs newer than its last check
    that match its filters and push a notification. Advances last_checked_at so a
    match is only ever announced once. Returns the number of alerts sent. Called
    by the scraper (run_all) after each scrape — that's the only time data changes."""
    now = datetime.now(timezone.utc)
    sent = 0
    wls = session.exec(select(Watchlist).where(Watchlist.alert_enabled == True)).all()
    for w in wls:
        try:
            filters = json.loads(w.filters_json) if w.filters_json else {}
        except Exception:
            filters = {}
        f = {k: v for k, v in filters.items() if k in _WL_FILTER_KEYS and v not in (None, "", [])}
        since = w.last_checked_at
        if since.tzinfo is None:
            since = since.replace(tzinfo=timezone.utc)
        hours = max(1, int((now - since).total_seconds() // 3600) + 1)
        items, new = _build_job_query(session, page=1, limit=5, new_since_hours=hours,
                                      sort_by="first_seen_at", **f)
        if new > 0:
            from .services.push import notify_all
            top = items[0] if items else None
            title = f"{new} new {w.name} job{'s' if new != 1 else ''}"
            body = f"{top.job_title} @ {top.company}" if top else "New matches for your saved search"
            sent += 1 if notify_all(session, title=title, body=body, url="/", tag=f"wl-{w.id}") else 0
        w.last_checked_at = now
        session.add(w)
    session.commit()
    return sent


# ── Web Push (VAPID) — free saved-search alerts ───────────────────────────────

class PushSubIn(BaseModel):
    endpoint: str
    keys: dict = {}


@app.get("/push/public-key")
def push_public_key():
    return {"key": settings.vapid_public_key, "enabled": bool(settings.vapid_private_key)}


@app.post("/push/subscribe")
def push_subscribe(sub: PushSubIn, session: SessionDep):
    keys = sub.keys or {}
    existing = session.exec(
        select(PushSubscription).where(PushSubscription.endpoint == sub.endpoint)
    ).first()
    if existing:
        existing.p256dh = keys.get("p256dh", "")
        existing.auth = keys.get("auth", "")
        session.add(existing)
    else:
        session.add(PushSubscription(
            endpoint=sub.endpoint, p256dh=keys.get("p256dh", ""), auth=keys.get("auth", ""),
        ))
    session.commit()
    return {"ok": True}


@app.post("/push/test")
def push_test(session: SessionDep):
    from .services.push import notify_all
    n = notify_all(session, title="Ashborne Silicon",
                   body="🔔 Push notifications are working — you'll get alerts for your saved searches.",
                   url="/")
    return {"ok": True, "sent": n}


# ── Résumé Studio — per-job résumé tailoring ─────────────────────────────────

_MASTER_LATEX_KEY = "master_resume_latex"
_TAILOR_INSTRUCTIONS_KEY = "tailor_instructions"


def _get_setting(session: Session, key: str, default: str = "") -> str:
    s = session.get(Setting, key)
    return s.value if s else default


def _set_setting(session: Session, key: str, value: str) -> None:
    s = session.get(Setting, key)
    if s:
        s.value = value
        s.updated_at = datetime.now(timezone.utc)
    else:
        s = Setting(key=key, value=value)
    session.add(s)


def _missing_keywords_for(session: Session, job: JobPosting) -> list[str]:
    """The keywords/skills this job wants that the active résumé doesn't surface.
    Reuses the exact resume-match engine; falls back to the job's own matched
    keywords when no résumé is uploaded — so the feature is accurate either way."""
    profile = _current_profile(session)
    if profile:
        try:
            from .resume_match import compute_match
            result = compute_match(profile, _job_match_input(job))
            missing = [m for m in (result.get("missing_skills") or []) if m]
            if missing:
                return missing[:20]
        except Exception:
            logger.exception("missing-keyword computation failed; falling back to job keywords")
    # Fallback: the role-relevant terms the scraper already matched on this job.
    kws = [k.strip() for k in (job.matched_keywords or "").split(",") if k.strip()]
    NOISE = {"usa", "us", "united states", "recent", "fresh", "new"}
    return [k for k in kws if k.lower() not in NOISE and not k.lower().startswith("priority-")][:20]


class MasterResumeIn(BaseModel):
    master_latex: str = ""
    instructions: str = ""


def _gemini_enabled() -> bool:
    from .services.resume_studio import gemini_enabled
    return gemini_enabled()


@app.get("/resume-studio/master")
def get_master_resume(session: SessionDep):
    return {
        "master_latex": _get_setting(session, _MASTER_LATEX_KEY),
        "instructions": _get_setting(session, _TAILOR_INSTRUCTIONS_KEY),
        "gemini_enabled": _gemini_enabled(),
    }


@app.put("/resume-studio/master")
def save_master_resume(payload: MasterResumeIn, session: SessionDep):
    _set_setting(session, _MASTER_LATEX_KEY, payload.master_latex or "")
    _set_setting(session, _TAILOR_INSTRUCTIONS_KEY, payload.instructions or "")
    session.commit()
    return {"ok": True}


class TailorIn(BaseModel):
    master_latex: Optional[str] = None     # falls back to saved master when omitted
    instructions: Optional[str] = None


class CompileIn(BaseModel):
    latex: str


@app.post("/resume-studio/compile-pdf")
def compile_resume_pdf(payload: CompileIn):
    """Compile tailored LaTeX to a PDF via a free hosted compiler. On failure the
    frontend falls back to the Overleaf hand-off, so a 502 here is non-fatal."""
    _check_size(payload.latex)
    from fastapi import Response
    from .services.resume_studio import compile_latex_to_pdf
    try:
        pdf = compile_latex_to_pdf(payload.latex)
    except RuntimeError as e:
        raise HTTPException(status_code=502, detail=str(e))
    return Response(
        content=pdf, media_type="application/pdf",
        headers={"Content-Disposition": 'attachment; filename="tailored-resume.pdf"'},
    )


def _assemble_tailor(session: Session, job_id: int, payload: TailorIn):
    job = session.get(JobPosting, job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")
    master = payload.master_latex if payload.master_latex is not None else _get_setting(session, _MASTER_LATEX_KEY)
    instructions = payload.instructions if payload.instructions is not None else _get_setting(session, _TAILOR_INSTRUCTIONS_KEY)
    missing = _missing_keywords_for(session, job)
    from .services.resume_studio import build_tailor_prompt
    prompt = build_tailor_prompt(
        job_title=job.job_title, company=job.company,
        description=job.cleaned_description or job.full_description_text or job.description_snippet or "",
        master_latex=master or "", missing_keywords=missing, instructions=instructions or "",
    )
    return job, prompt, missing


# ── Stateless prompt builders ─────────────────────────────────────────────────
# These only ever assembled text from a job row and some user settings — no AI
# call, no persistence. The client now holds both, so it supplies them and these
# become pure functions, with no database to look the job up in.

class StatelessTailorIn(BaseModel):
    job_title: str
    company: str = ""
    description: str = ""
    master_latex: str = ""
    instructions: str = ""
    missing_keywords: list[str] = []


@app.post("/resume-studio/tailor-prompt")
def tailor_prompt_stateless(payload: StatelessTailorIn):
    """Copy-paste tailoring prompt for Claude/ChatGPT. Assembles text only."""
    from .services.resume_studio import build_tailor_prompt
    return {
        "prompt": build_tailor_prompt(
            job_title=payload.job_title, company=payload.company,
            description=payload.description, master_latex=payload.master_latex,
            missing_keywords=payload.missing_keywords, instructions=payload.instructions,
        ),
        "missing_keywords": payload.missing_keywords,
        "job_title": payload.job_title, "company": payload.company,
    }


class StatelessInterviewIn(BaseModel):
    job_title: str
    company: str = ""
    description: str = ""
    role_category: str = ""


@app.post("/resume-studio/interview-prompt")
def interview_prompt_stateless(payload: StatelessInterviewIn):
    """Copy-paste interview-prep prompt. Assembles text only."""
    from .services.resume_studio import build_interview_prompt
    return {
        "prompt": build_interview_prompt(
            job_title=payload.job_title, company=payload.company,
            description=payload.description, role_category=payload.role_category,
        )
    }


class TailorGenerateIn(StatelessTailorIn):
    pass


_MAX_PROMPT_FIELD = 60_000   # characters; a long JD plus a full LaTeX résumé fits


def _check_size(*fields: str) -> None:
    if any(len(f or "") > _MAX_PROMPT_FIELD for f in fields):
        raise HTTPException(status_code=413, detail="Input too long")


@app.post("/resume-studio/tailor/generate")
def tailor_generate_stateless(payload: TailorGenerateIn):
    """Tailored LaTeX via Gemini. The browser supplies the job and résumé;
    nothing is stored. Job text is untrusted input and is passed as data."""
    from .services.resume_studio import build_tailor_prompt, generate_with_gemini, gemini_enabled
    if not gemini_enabled():
        raise HTTPException(status_code=400, detail="In-app generation is not configured. Add a free GEMINI_API_KEY to enable it.")
    _check_size(payload.description, payload.master_latex, payload.instructions)
    prompt = build_tailor_prompt(
        job_title=payload.job_title[:300], company=payload.company[:200],
        description=payload.description, master_latex=payload.master_latex,
        missing_keywords=payload.missing_keywords[:40], instructions=payload.instructions,
    )
    try:
        latex = generate_with_gemini(prompt)
    except RuntimeError as e:
        raise HTTPException(status_code=502, detail=str(e))
    return {"latex": latex, "missing_keywords": payload.missing_keywords}


@app.post("/resume-studio/interview/generate")
def interview_generate_stateless(payload: StatelessInterviewIn):
    """Company-specific interview prep via Gemini, from browser-supplied job text."""
    from .services.resume_studio import build_interview_prompt, generate_with_gemini, gemini_enabled
    if not gemini_enabled():
        raise HTTPException(status_code=400, detail="In-app generation is not configured. Add a free GEMINI_API_KEY to enable it.")
    _check_size(payload.description)
    prompt = build_interview_prompt(
        job_title=payload.job_title[:300], company=payload.company[:200],
        description=payload.description, role_category=payload.role_category[:80],
    )
    try:
        text = generate_with_gemini(prompt)
    except RuntimeError as e:
        raise HTTPException(status_code=502, detail=str(e))
    return {"text": text}


@app.post("/jobs/{job_id}/tailor-prompt")
def tailor_prompt(job_id: int, payload: TailorIn, session: SessionDep):
    """Assemble the copy-paste prompt for Claude/ChatGPT (Option 1). No AI call."""
    job, prompt, missing = _assemble_tailor(session, job_id, payload)
    return {"prompt": prompt, "missing_keywords": missing,
            "job_title": job.job_title, "company": job.company}


@app.post("/jobs/{job_id}/tailor/generate")
def tailor_generate(job_id: int, payload: TailorIn, session: SessionDep):
    """Generate the tailored LaTeX in-app via Gemini (Option 2)."""
    from .services.resume_studio import generate_with_gemini, gemini_enabled
    if not gemini_enabled():
        raise HTTPException(status_code=400, detail="In-app generation is not configured. Add a free GEMINI_API_KEY to enable it.")
    _, prompt, missing = _assemble_tailor(session, job_id, payload)
    try:
        latex = generate_with_gemini(prompt)
    except RuntimeError as e:
        raise HTTPException(status_code=502, detail=str(e))
    return {"latex": latex, "missing_keywords": missing}


def _assemble_interview_prompt(session: Session, job_id: int) -> str:
    job = session.get(JobPosting, job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")
    from .services.resume_studio import build_interview_prompt
    return build_interview_prompt(
        job_title=job.job_title, company=job.company,
        description=job.cleaned_description or job.full_description_text or job.description_snippet or "",
        role_category=job.role_category or "",
    )


@app.post("/jobs/{job_id}/interview-prep-prompt")
def interview_prep_prompt(job_id: int, session: SessionDep):
    """Copy-paste prompt for company-specific interview prep (Claude/ChatGPT)."""
    return {"prompt": _assemble_interview_prompt(session, job_id)}


@app.post("/jobs/{job_id}/interview-prep/generate")
def interview_prep_generate(job_id: int, session: SessionDep):
    """Generate company-specific interview prep in-app via Gemini."""
    from .services.resume_studio import generate_with_gemini, gemini_enabled
    if not gemini_enabled():
        raise HTTPException(status_code=400, detail="In-app generation is not configured. Add a free GEMINI_API_KEY to enable it.")
    prompt = _assemble_interview_prompt(session, job_id)
    try:
        text = generate_with_gemini(prompt)
    except RuntimeError as e:
        raise HTTPException(status_code=502, detail=str(e))
    return {"text": text}


# ── Email digest (Phase 4) ───────────────────────────────────────────────────

@app.get("/digest/preview")
def digest_preview(session: SessionDep):
    from .services.digest import build_digest
    return build_digest(session)


@app.post("/digest/send")
async def digest_send(session: SessionDep):
    from .services.digest import build_digest, send_digest_email
    data = build_digest(session)
    ok = await send_digest_email(data)
    return {"sent": ok, "configured": ok is not None, **data}


@app.get("/export/applications.csv")
def export_applications(session: SessionDep):
    """Export every saved / applied / pipeline-tracked job as CSV for offline tracking."""
    import csv
    import io
    from fastapi import Response

    jobs = session.exec(
        select(JobPosting).where(
            (JobPosting.active_status.in_(["saved", "applied"]))  # type: ignore[attr-defined]
            | (col(JobPosting.application_status) != "")
        ).order_by(col(JobPosting.applied_at).desc(), col(JobPosting.saved_at).desc())
    ).all()

    buf = io.StringIO()
    w = csv.writer(buf)
    w.writerow([
        "Company", "Title", "Location", "Stage", "Status", "Relevance",
        "Resume Used", "Applied On", "Follow-up", "Confirmation ID",
        "Recruiter", "Apply URL", "Notes",
    ])
    for j in jobs:
        w.writerow([
            j.company, j.job_title, j.location, j.application_status or "", j.active_status,
            j.match_score, j.resume_version_used or "",
            j.applied_at.date().isoformat() if j.applied_at else "",
            j.follow_up_date or "", j.confirmation_id or "", j.recruiter_contact or "",
            j.safe_apply_url or j.apply_url, (j.notes or "").replace("\n", " "),
        ])
    return Response(
        content=buf.getvalue(),
        media_type="text/csv",
        headers={"Content-Disposition": "attachment; filename=ashborne-applications.csv"},
    )


@app.get("/health")
def health():
    """Liveness plus which optional features are configured — booleans only,
    never values, so the owner can confirm setup without exposing a secret."""
    db_ok = False
    try:
        from .database import engine
        with Session(engine) as s:
            s.exec(select(1)).one()
        db_ok = True
    except Exception:
        db_ok = False
    from .services.resume_studio import gemini_enabled
    return {
        "status": "ok",
        "app": "ashborne-volt",
        "version": "1.0.0",
        "db": "ok" if db_ok else "unavailable",
        "ai": "enabled" if gemini_enabled() else "disabled",
        "push": "enabled" if settings.vapid_private_key else "disabled",
    }
