"""SQLModel ORM models for all database tables."""

from __future__ import annotations

from datetime import datetime, timezone
from enum import Enum
from typing import Optional

from sqlalchemy import Column, DateTime, ForeignKey, Integer
from sqlalchemy.types import TypeDecorator
from sqlmodel import Field, SQLModel


class UtcDateTime(TypeDecorator):
    """A DateTime column that cannot hold a naive value.

    Coercing here rather than at each call site is deliberate. Timestamps reach
    these models from many directions — scraper date parsers, restored snapshots,
    tests — and four scrapers (amazon, avature, giants, jobs2web) build theirs
    with ``strptime``, which is naive. Fixing callers one at a time is how this
    bug kept coming back: sqlmodel 0.0.47 started rejecting naive datetimes and
    every scrape died for nine days, having passed locally on 0.0.38.

    Anything naive is read as UTC, which is what it always meant.
    """

    impl = DateTime(timezone=True)
    cache_ok = True

    def process_bind_param(self, value, dialect):
        if isinstance(value, datetime) and value.tzinfo is None:
            return value.replace(tzinfo=timezone.utc)
        return value

    def process_result_value(self, value, dialect):
        if isinstance(value, datetime) and value.tzinfo is None:
            return value.replace(tzinfo=timezone.utc)
        return value


def utcnow() -> datetime:
    """Timezone-aware UTC now — the ONLY datetime factory the models may use.

    Every stored timestamp used to default to ``datetime.utcnow()``, which is
    naive, while the rest of the codebase compares against
    ``datetime.now(timezone.utc)``, which is aware. Mixing the two is a latent
    type error that sits dormant until a dependency tightens validation — which
    sqlmodel 0.0.47 did, with "Datetime values must have timezone information",
    killing every scrape on every engine.

    Keeping one factory here means the naive/aware split cannot reappear one
    field at a time. tests/test_datetime_awareness.py enforces it.
    """
    return datetime.now(timezone.utc)



class ActiveStatus(str, Enum):
    active = "active"
    possibly_removed = "possibly_removed"
    removed = "removed"
    applied = "applied"
    ignored = "ignored"
    saved = "saved"


class ExperienceLevel(str, Enum):
    new_grad = "New Grad"
    entry_level = "Entry Level"
    zero_to_three = "0-3 Years"
    candidate_friendly = "Candidate Friendly"
    mid_level = "Mid-Level"
    senior = "Senior"
    unknown = "Unknown"


class RoleCategory(str, Enum):
    """EE job categories. Values MUST equal the constants in app/taxonomy.py,
    which is the authority; this enum only exists so the column has a type."""
    power = "Power Systems"
    energy = "Renewable Energy"
    industrial = "Industrial & Plant"
    controls = "Controls & Automation"
    instrumentation = "Instrumentation"
    design = "Electrical Design"
    machines = "Electrical Machines"
    power_electronics = "Power Electronics"
    rf = "RF & Communications"
    emc = "EMC / EMI"
    infrastructure = "Buildings & Infrastructure"
    transport = "Transportation & Aerospace"
    other = "Other EE"
    out_of_scope = "Out of Scope"
    unknown = "Unknown"


class RemoteStatus(str, Enum):
    remote = "Remote"
    hybrid = "Hybrid"
    onsite = "Onsite"
    unknown = "Unknown"


class Company(SQLModel, table=True):
    __tablename__ = "companies"

    id: Optional[int] = Field(default=None, primary_key=True)
    name: str = Field(index=True, unique=True)
    category: str
    priority: str  # S, A, B, C
    careers_url: str
    company_search_url: str = ""
    ats_platform: str
    # Utility, OEM, EPC / Consulting, Renewables, Data Centers, Aerospace & Defense…
    sector: str = ""
    enabled: bool = True
    last_scraped_at: Optional[datetime] = Field(default=None, sa_type=UtcDateTime)
    scrape_error_count: int = 0
    # Consecutive runs where the source answered successfully but returned NOTHING.
    # The silent failure mode, and the one that matters for DOM scraping: when a
    # selector stops matching, the adapter raises nothing, returns an empty list,
    # and the run counts the company as scraped. scrape_error_count stays 0, so
    # quarantine never sees it and the company simply reads "no openings" forever.
    # A genuinely empty board looks identical for one run, which is why this is a
    # counter to surface rather than grounds to quarantine.
    consecutive_empty_scrapes: int = 0
    notes: str = ""


class JobPosting(SQLModel, table=True):
    __tablename__ = "job_postings"

    id: Optional[int] = Field(default=None, primary_key=True)

    # Identity
    company: str = Field(index=True)
    company_category: str = ""
    company_priority: str = ""

    # Title & classification
    job_title: str = Field(index=True)
    normalized_title: str = ""
    role_category: str = RoleCategory.unknown
    experience_level: str = ExperienceLevel.unknown

    # ── Seniority & entry-level flags ─────────────────────────────
    is_entry_level: bool = Field(default=False, index=True)
    is_candidate_friendly: bool = Field(default=False, index=True)
    is_senior: bool = Field(default=False, index=True)

    years_required_min: Optional[int] = None
    years_required_max: Optional[int] = None

    # ── Location (raw + parsed) ───────────────────────────────────
    location: str = ""
    location_raw: str = ""
    remote_status: str = RemoteStatus.unknown

    is_usa: bool = Field(default=False, index=True)
    is_remote_usa: bool = Field(default=False)
    country: str = ""
    state: str = Field(default="", index=True)
    city: str = ""
    location_confidence: float = 0.0

    # Source
    job_id_from_company: str = ""
    apply_url: str
    source_url: str = ""
    ats_platform: str = ""

    # ── Apply URL safety ──────────────────────────────────────────
    original_apply_url: str = ""
    safe_apply_url: str = ""
    apply_url_status: str = ""
    apply_url_reason: str = ""

    # Dates
    posted_date: Optional[datetime] = Field(default=None, sa_type=UtcDateTime)
    first_seen_at: datetime = Field(default_factory=utcnow, sa_type=UtcDateTime)
    last_seen_at: datetime = Field(default_factory=utcnow, sa_type=UtcDateTime)
    removed_at: Optional[datetime] = Field(default=None, sa_type=UtcDateTime)

    # Status
    active_status: str = Field(default=ActiveStatus.active, index=True)
    missed_scrapes: int = 0

    # ── Scoring ───────────────────────────────────────────────────
    match_score: int = 0   # intrinsic RTL/DV role relevance (USA not scored)
    matched_keywords: str = ""
    # Cache of the canonical skills/keywords extracted from this posting (comma-
    # separated), precomputed at scrape time so résumé matching doesn't re-run the
    # full keyword-taxonomy regex over every job on each request.
    job_skills: str = ""
    score_breakdown_json: str = ""
    relevance_score_label: str = ""
    # Job-intrinsic fit scores (resume-independent) — New Grad Fit is the primary
    # ranking score shown on the card ring; Experienced Fit is secondary.
    new_grad_fit: int = Field(default=0, index=True)
    experienced_fit: int = 0

    # Description
    description_snippet: str = ""
    full_description_text: str = ""

    # ── Role flags (JSON blob of 14 booleans) ─────────────────────
    role_flags_json: str = ""
    is_software_only: bool = Field(default=False, index=True)
    is_hardware_software_codesign: bool = Field(default=False)

    # ── Cleaned description (HTML stripped) ──────────────────────
    cleaned_description: str = ""

    # ── Relevance / exclusion reasoning ──────────────────────────
    relevance_reason: str = ""
    exclusion_reason: str = ""
    matched_positive_terms_json: str = ""
    matched_negative_terms_json: str = ""

    # ── Data quality ─────────────────────────────────────────────
    data_quality_status: str = ""

    # ── Eligibility / export-control (Phase 1) ───────────────────
    eligibility_risk: str = ""    # low | medium | high
    eligibility_terms: str = ""   # comma-separated matched categories
    # Gating requirements shown as badges: PE license, EIT / FE, NERC, Clearance,
    # Travel, On-call / storm duty (comma-separated, display order).
    requirement_tags: str = ""
    # Same requisition posted at several sites, or reposted under a new id:
    # rows sharing this key render as one card with "+N locations".
    dup_group: str = Field(default="", index=True)

    # ── Classification confidence & data quality (Phase 2) ───────
    seniority_confidence: int = 0       # 0-100
    classification_confidence: int = 0  # 0-100
    data_quality_score: int = 0         # 0-100
    source_reliability: str = ""        # High | Medium | Low
    location_label: str = ""            # Onsite | Hybrid | Remote - USA | …
    posted_date_known: bool = False     # True if posted_date came from source

    @property
    def sponsors_h1b(self) -> Optional[bool]:
        """Company-level H1B sponsorship signal (read by the API response)."""
        from .eligibility import sponsors_h1b as _lookup
        return _lookup(self.company)

    @property
    def new_grad_fit_label(self) -> str:
        """Short band label for the card ring (only 'Excellent' at 90+)."""
        from .scoring import new_grad_fit_label
        return new_grad_fit_label(self.new_grad_fit)

    @property
    def overall_recommendation(self) -> str:
        """Full recommendation label derived from New Grad Fit."""
        from .scoring import overall_recommendation
        return overall_recommendation(self.new_grad_fit)

    @property
    def display_location(self) -> str:
        """Clean, human location for the card. The parser already extracts a
        tidy city/state even from messy raw strings like
        'USA-CA Irvine Alton Parkway Bldg 2' (-> 'Irvine, CA'); fall back to the
        raw string with any trailing building/suite noise stripped."""
        import re
        if self.is_usa and self.city and self.state:
            return f"{self.city}, {self.state}"
        raw = (self.location or "").strip()
        raw = re.sub(r"\s+(?:Bldg|Building|Suite|Ste|Floor|Fl)\b.*$", "", raw, flags=re.I).strip()
        return raw or self.country or ""

    # ── User actions ──────────────────────────────────────────────
    application_status: str = ""   # Saved|Applied|Assessment|Interview|Rejected|Offer|Archived|Ignored
    notes: str = ""
    resume_version_used: str = ""
    saved_at: Optional[datetime] = Field(default=None, sa_type=UtcDateTime)
    applied_at: Optional[datetime] = Field(default=None, sa_type=UtcDateTime)
    ignored_at: Optional[datetime] = Field(default=None, sa_type=UtcDateTime)
    # Application-tracking pipeline (Phase 4)
    follow_up_date: str = ""
    confirmation_id: str = ""
    recruiter_contact: str = ""


class ResumeProfile(SQLModel, table=True):
    """Store for the user's parsed resume profiles. Multiple versions are kept
    (e.g. 'DV/UVM', 'RTL Design'); exactly one is marked active. Only the
    extracted profile is kept — the raw file is discarded after parse."""
    __tablename__ = "resume_profile"

    id: Optional[int] = Field(default=None, primary_key=True)
    filename: str = ""
    label: str = ""              # user-facing version name, e.g. "DV/UVM v3"
    is_active: bool = True       # the version used for default ranking/badges
    profile_json: str = ""       # JSON of ResumeProfileData
    uploaded_at: datetime = Field(default_factory=utcnow, sa_type=UtcDateTime)


class Setting(SQLModel, table=True):
    """Generic single-user key/value store (e.g. the master résumé LaTeX and the
    default tailoring instructions used by Résumé Studio)."""
    __tablename__ = "settings"

    key: str = Field(primary_key=True)
    value: str = ""
    updated_at: datetime = Field(default_factory=utcnow, sa_type=UtcDateTime)


class PushSubscription(SQLModel, table=True):
    """A browser Web-Push subscription (one per device/browser that opted in).
    Used to deliver saved-search alerts as native notifications, for free (VAPID)."""
    __tablename__ = "push_subscriptions"

    id: Optional[int] = Field(default=None, primary_key=True)
    endpoint: str = Field(index=True, unique=True)
    p256dh: str = ""
    auth: str = ""
    created_at: datetime = Field(default_factory=utcnow, sa_type=UtcDateTime)


class Watchlist(SQLModel, table=True):
    """A saved search (filter set) with new-since-last-check tracking."""
    __tablename__ = "watchlists"

    id: Optional[int] = Field(default=None, primary_key=True)
    name: str
    filters_json: str = ""          # JSON of the saved filter set
    alert_enabled: bool = True
    last_checked_at: datetime = Field(default_factory=utcnow, sa_type=UtcDateTime)
    created_at: datetime = Field(default_factory=utcnow, sa_type=UtcDateTime)


class ScrapeRun(SQLModel, table=True):
    __tablename__ = "scrape_runs"

    id: Optional[int] = Field(default=None, primary_key=True)
    started_at: datetime = Field(default_factory=utcnow, sa_type=UtcDateTime)
    finished_at: Optional[datetime] = Field(default=None, sa_type=UtcDateTime)
    companies_scraped: int = 0
    jobs_found: int = 0
    new_jobs: int = 0
    removed_jobs: int = 0
    errors: int = 0
    triggered_by: str = "scheduler"


class ScrapeError(SQLModel, table=True):
    __tablename__ = "scrape_errors"

    id: Optional[int] = Field(default=None, primary_key=True)
    # ON DELETE CASCADE, declared at the schema level. Pruning a scrape_run with
    # errors attached used to raise ForeignKeyViolation, and because pruning runs
    # at the start of every scrape, one un-prunable row silently killed ALL
    # scraping for three days. The pruning code deletes these children itself
    # too — this is the database refusing to let that bug exist again.
    # Existing Postgres databases are migrated in database.init_db().
    scrape_run_id: Optional[int] = Field(
        default=None,
        sa_column=Column(Integer, ForeignKey("scrape_runs.id", ondelete="CASCADE"), nullable=True),
    )
    company: str
    error_message: str
    error_type: str = ""
    occurred_at: datetime = Field(default_factory=utcnow, sa_type=UtcDateTime)
