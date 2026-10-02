"""The static corpus: what scrapes write, what the browser reads.

There is no hosted database for job data. Each scrape shard rebuilds a scratch
SQLite database from the published files, scrapes its own slice of companies into
it, and writes a *shard file*. One publish job then merges every shard into the
published corpus and commits it; Vercel serves it from its CDN.

Published layout (``frontend/public/data``)::

    jobs.json           what the browser downloads: ACTIVE, US-visible postings
                        with list/filter fields only, plus companies and run log
    state.json          scraper bookkeeping the browser never fetches: postings
                        that are possibly removed, retired, or outside the US —
                        kept so removal counters and first-seen dates survive
    details/NN.json     description bodies in DETAIL_CHUNKS files, keyed by id;
                        opening a posting downloads one chunk, not all of them

Rules that keep this correct at scale (each one is a bug Ashborne Silicon hit):

* **Ids are stable.** ``id`` is derived from the content fingerprint, not from a
  database row, so two shards can never hand the same id to different postings
  and a browser bookmark survives every rebuild.
* **A shard owns its companies.** Merging replaces every row of the shard's
  companies with the shard's rows. Rows are never "unioned back", so a posting a
  shard retired or purged cannot be resurrected from the previous file.
* **Retired rows never reach the browser.** They live in state.json.
"""

from __future__ import annotations

import gzip
import hashlib
import json
import logging
import re
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Iterable

from sqlmodel import Session, select

from .database import engine
from .models import ActiveStatus, Company, JobPosting, ScrapeRun
from .scrape_engine import EMPTY_STALL_THRESHOLD, ERROR_QUARANTINE_THRESHOLD
from .services.dedupe import make_fingerprint
from .taxonomy import HIDDEN_CATEGORIES as _TAXONOMY_HIDDEN, OUT_OF_SCOPE

logger = logging.getLogger(__name__)

SCHEMA = 2
DETAIL_CHUNKS = 16
RUNS_KEPT = 30
# Active postings nobody has re-seen in this long are retired at merge time. The
# per-company removal counter only runs for companies a shard visited, so a
# company dropped from the config would otherwise stay "hiring" forever.
STALE_DAYS = 21
# Retired rows are forgotten after this long. A repost after that is a new opening.
PURGE_DAYS = 60

# Fields the job list, filters, sorting and the detail header read.
LIST_FIELDS = (
    "id", "key", "dup_group", "company", "company_category", "company_priority",
    "job_title", "normalized_title", "role_category", "experience_level",
    "is_entry_level", "is_candidate_friendly", "is_senior",
    "years_required_min", "years_required_max",
    "location", "display_location", "remote_status", "is_usa", "is_remote_usa",
    "country", "state", "location_confidence", "location_label",
    "job_id_from_company", "apply_url", "ats_platform", "apply_url_status",
    "posted_date", "posted_date_known", "first_seen_at", "last_seen_at",
    "match_score", "new_grad_fit", "experienced_fit", "matched_keywords",
    "job_skills", "relevance_reason", "description_snippet",
    "eligibility_risk", "eligibility_terms", "requirement_tags",
    # A model @property, not a column. Missing it once made the H1B filter
    # compare against undefined and match every job.
    "sponsors_h1b",
    "seniority_confidence", "classification_confidence", "data_quality_score",
    "source_reliability", "missed_scrapes",
)

# What a non-browseable row keeps. Everything here is load-bearing for the
# removal state machine or for re-matching the posting on the next scrape.
STATE_FIELDS = (
    "key", "company", "job_title", "location", "job_id_from_company", "apply_url",
    "active_status", "missed_scrapes", "removed_at", "first_seen_at", "last_seen_at",
    "posted_date", "is_usa", "location_confidence",
)

# Categories the default view hides. MUST match frontend/src/lib/categories.ts.
HIDDEN_CATEGORIES = set(_TAXONOMY_HIDDEN) | {"Software / Compiler"}


# ── helpers ───────────────────────────────────────────────────────────────────

def _iso(v: Any) -> Any:
    """ISO-8601 with an explicit offset; a bare timestamp is read as local time
    by browsers, which once rendered "updated -3.7h ago"."""
    if not isinstance(v, datetime):
        return v
    return (v.replace(tzinfo=timezone.utc) if v.tzinfo is None else v).isoformat()


def _parse_aware(v) -> datetime | None:
    if not v:
        return None
    try:
        d = datetime.fromisoformat(str(v))
    except ValueError:
        return None
    return d.replace(tzinfo=timezone.utc) if d.tzinfo is None else d


def stable_id(key: str) -> int:
    """A JS-safe integer (52 bits) derived from the posting fingerprint."""
    return int(key[:13], 16)


def detail_chunk(job_id: int | str) -> int:
    return int(job_id) % DETAIL_CHUNKS


_SIG_STRIP = re.compile(r"[^a-z]+")


def dup_group_key(company: str, normalized_title: str, description: str) -> str:
    """Rows sharing this key are one opening: the same requisition at several
    sites, or a repost under a new id. Built from the company, the normalised
    title and a signature of the description with digits and punctuation removed
    — so a "+N locations" card never merges two different teams that happen to
    share a generic title like "Electrical Engineer II"."""
    body = _SIG_STRIP.sub(" ", (description or "").lower())
    sig = hashlib.sha1(" ".join(body.split())[:700].encode()).hexdigest()[:10] if body.strip() else ""
    raw = f"{(company or '').lower().strip()}|{(normalized_title or '').strip()}|{sig}"
    return hashlib.sha1(raw.encode()).hexdigest()[:12]


def _browseable(row: dict) -> bool:
    """Shown to users: active, in (or possibly in) the US, and in scope."""
    if str(row.get("active_status") or "active") != "active":
        return False
    if row.get("role_category") in (OUT_OF_SCOPE, "Software / Compiler"):
        return False
    return bool(row.get("is_usa")) or not row.get("location_confidence")


def company_tallies(rows: Iterable[dict]) -> dict[str, dict]:
    """Per-company counts over browseable rows. ONE function for build and merge,
    so the two publish paths can never disagree about a company's numbers."""
    day_ago = datetime.now(timezone.utc) - timedelta(hours=24)
    stats: dict[str, dict] = {}
    groups: dict[str, set] = {}
    for row in rows:
        if not _browseable(row):
            continue
        name = row.get("company", "")
        st = stats.setdefault(name, {"total": 0, "usa": 0, "viewable": 0, "entry": 0,
                                     "new_today": 0, "unique": 0, "quality": []})
        st["total"] += 1
        if row.get("is_usa"):
            st["usa"] += 1
            if row.get("role_category") not in HIDDEN_CATEGORIES:
                st["viewable"] += 1
                groups.setdefault(name, set()).add(row.get("dup_group") or row.get("key"))
                if row.get("is_entry_level") or row.get("is_candidate_friendly"):
                    st["entry"] += 1
                eff = _parse_aware(row.get("posted_date") if row.get("posted_date_known") else None) \
                    or _parse_aware(row.get("first_seen_at"))
                if eff and eff >= day_ago:
                    st["new_today"] += 1
        if row.get("data_quality_score"):
            st["quality"].append(int(row["data_quality_score"]))
    for name, g in groups.items():
        stats[name]["unique"] = len(g)
    return stats


def logo_domain(cfg: dict) -> str:
    """The company's web domain, for its logo: an explicit `domain:` in the
    catalog, else the careers URL's registrable domain (careers.gevernova.com ->
    gevernova.com). Job-board hosts say nothing about the brand, so they yield ""."""
    from urllib.parse import urlparse

    if cfg.get("domain"):
        return str(cfg["domain"]).strip().lower()
    host = urlparse(cfg.get("careers_url") or "").netloc.lower().split(":")[0]
    if not host or any(b in host for b in ("myworkdayjobs", "icims", "greenhouse", "lever.co",
                                            "ashbyhq", "smartrecruiters", "eightfold", "jobvite")):
        return ""
    labels = host.split(".")
    return ".".join(labels[-2:]) if len(labels) >= 2 else host


def _company_entries(cfgs: list[dict], health: dict[str, dict], rows: list[dict]) -> list[dict]:
    stats = company_tallies(rows)
    out = []
    for c in cfgs:
        name = c.get("name", "")
        st = stats.get(name, {})
        h = health.get(name, {})
        quality = st.get("quality") or []
        errs = int(h.get("scrape_error_count") or 0)
        empties = int(h.get("consecutive_empty_scrapes") or 0)
        total = st.get("total", 0)
        out.append({
            "name": name,
            "category": c.get("category", ""),
            "priority": c.get("priority", "C"),
            "sector": c.get("sector", ""),
            "hq": c.get("hq", ""),
            "domain": logo_domain(c),
            "careers_url": c.get("careers_url", ""),
            "ats_platform": c.get("ats_platform", ""),
            "engine": c.get("engine", ""),
            "enabled": bool(c.get("enabled", True)),
            "total_active_jobs": total,
            "usa_active_jobs": st.get("usa", 0),
            "viewable_jobs": st.get("viewable", 0),
            "unique_jobs": st.get("unique", 0),
            "entry_level_jobs": st.get("entry", 0),
            "new_jobs_today": st.get("new_today", 0),
            "parser_confidence": round(sum(quality) / len(quality)) if quality else 0,
            "auto_connected": total > 0,
            "scrape_status": (
                "quarantined" if errs >= ERROR_QUARANTINE_THRESHOLD
                else "error" if errs > 2
                else "stalled" if empties >= EMPTY_STALL_THRESHOLD
                else "ok" if total else "idle"
            ),
            "consecutive_empty_scrapes": empties,
            "quarantined": errs >= ERROR_QUARANTINE_THRESHOLD,
            "last_scraped_at": h.get("last_scraped_at"),
            "scrape_error_count": errs,
        })
    return out


# ── Building a shard from the scratch database ───────────────────────────────

def build_shard(session: Session, companies: set[str] | None = None,
                run_ids: set[int] | None = None) -> dict:
    """Everything one scrape run knows about its companies.

    ``companies`` limits the export to the shard's own companies (None = all).
    """
    stmt = select(JobPosting)
    if companies is not None:
        stmt = stmt.where(JobPosting.company.in_(sorted(companies)))
    rows: list[dict] = []
    state: list[dict] = []
    details: dict[str, str] = {}
    for j in session.exec(stmt).all():
        key = make_fingerprint(j.company or "", j.job_title or "", j.location or "",
                               j.job_id_from_company or "", j.apply_url or "")
        full = {f: _iso(getattr(j, f, None)) for f in LIST_FIELDS if f not in ("id", "key", "dup_group")}
        full["key"] = key
        full["id"] = stable_id(key)
        full["active_status"] = j.active_status
        full["dup_group"] = dup_group_key(j.company, j.normalized_title, j.cleaned_description)
        full["removed_at"] = _iso(j.removed_at)
        if j.role_category in (OUT_OF_SCOPE, "Software / Compiler"):
            # Reclassified out of scope: forget it. If it is still posted, the
            # scraper's own gate will keep it out next time.
            continue
        if _browseable(full):
            row = {k: v for k, v in full.items() if k in LIST_FIELDS}
            rows.append(row)
            body = (j.cleaned_description or "").strip()
            if body:
                details[str(row["id"])] = body
        else:
            state.append({k: full.get(k) for k in STATE_FIELDS})

    health = {}
    cstmt = select(Company)
    if companies is not None:
        cstmt = cstmt.where(Company.name.in_(sorted(companies)))
    for c in session.exec(cstmt).all():
        health[c.name] = {
            "last_scraped_at": _iso(c.last_scraped_at),
            "scrape_error_count": c.scrape_error_count,
            "consecutive_empty_scrapes": c.consecutive_empty_scrapes,
        }

    rstmt = select(ScrapeRun).order_by(ScrapeRun.started_at.desc())
    runs = []
    for r in session.exec(rstmt).all():
        if run_ids is not None and r.id not in run_ids:
            continue
        runs.append({"started_at": _iso(r.started_at), "finished_at": _iso(r.finished_at),
                     "companies_scraped": r.companies_scraped, "jobs_found": r.jobs_found,
                     "new_jobs": r.new_jobs, "removed_jobs": r.removed_jobs,
                     "errors": r.errors, "triggered_by": r.triggered_by})

    return {
        "schema": SCHEMA,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "companies": sorted(companies) if companies is not None else None,
        "jobs": rows,
        "state": state,
        "details": details,
        "health": health,
        "runs": runs,
    }


def write_shard(path: str | Path, companies: set[str] | None, run_ids: set[int] | None) -> dict:
    with Session(engine) as session:
        shard = build_shard(session, companies, run_ids)
    raw = json.dumps(shard, separators=(",", ":"), ensure_ascii=False).encode("utf-8")
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    Path(path).write_bytes(raw)
    logger.info("shard written: %d browseable, %d state rows, %d bodies, %.0f KB",
                len(shard["jobs"]), len(shard["state"]), len(shard["details"]), len(raw) / 1024)
    return {"jobs": len(shard["jobs"]), "state": len(shard["state"]), "bytes": len(raw)}


# ── Reading and writing the published corpus ─────────────────────────────────

def read_published(data_dir: str | Path) -> dict:
    """The published corpus as one in-memory structure (empty if none yet)."""
    d = Path(data_dir)
    out = {"jobs": [], "state": [], "details": {}, "companies": [], "runs": []}
    jp = d / "jobs.json"
    if jp.exists():
        payload = json.loads(jp.read_text(encoding="utf-8"))
        out["jobs"] = payload.get("jobs", [])
        out["companies"] = payload.get("companies", [])
        out["runs"] = payload.get("runs", [])
    sp = d / "state.json"
    if sp.exists():
        out["state"] = json.loads(sp.read_text(encoding="utf-8")).get("rows", [])
    for i in range(DETAIL_CHUNKS):
        cp = d / "details" / f"{i:02d}.json"
        if cp.exists():
            out["details"].update(json.loads(cp.read_text(encoding="utf-8")).get("descriptions", {}))
    return out


def write_published(data_dir: str | Path, corpus: dict) -> dict:
    """Write jobs.json, state.json and the detail chunks. Returns a size report."""
    from .config import load_all_companies

    d = Path(data_dir)
    (d / "details").mkdir(parents=True, exist_ok=True)
    now = datetime.now(timezone.utc).isoformat()
    jobs = sorted(corpus["jobs"], key=lambda r: (r.get("company", ""), r.get("job_title", ""), r.get("id", 0)))
    health = {c["name"]: c for c in corpus.get("companies", [])}
    health.update(corpus.get("health", {}))
    companies = _company_entries(load_all_companies(), health, jobs)
    visible = [r for r in jobs if r.get("is_usa") and r.get("role_category") not in HIDDEN_CATEGORIES]

    jobs_payload = {
        "schema": SCHEMA,
        "generated_at": now,
        "count": len(jobs),
        "unique_count": len({r.get("dup_group") or r.get("key") for r in visible}),
        "jobs": jobs,
        "companies": companies,
        "runs": corpus.get("runs", [])[:RUNS_KEPT],
    }
    state_payload = {"schema": SCHEMA, "generated_at": now,
                     "rows": sorted(corpus["state"], key=lambda r: (r.get("company", ""), r.get("key", "")))}

    live_ids = {str(r["id"]) for r in jobs}
    chunks: list[dict[str, str]] = [{} for _ in range(DETAIL_CHUNKS)]
    for jid, body in corpus["details"].items():
        if jid in live_ids:
            chunks[detail_chunk(jid)][jid] = body

    report: dict[str, Any] = {"count": jobs_payload["count"], "unique": jobs_payload["unique_count"]}
    for name, payload in (("jobs.json", jobs_payload), ("state.json", state_payload)):
        raw = json.dumps(payload, separators=(",", ":"), ensure_ascii=False).encode("utf-8")
        (d / name).write_bytes(raw)
        report[name] = {"bytes": len(raw), "gzip": len(gzip.compress(raw, 6))}
    detail_bytes = detail_gz = 0
    for i, chunk in enumerate(chunks):
        raw = json.dumps({"descriptions": dict(sorted(chunk.items()))},
                         separators=(",", ":"), ensure_ascii=False).encode("utf-8")
        (d / "details" / f"{i:02d}.json").write_bytes(raw)
        detail_bytes += len(raw)
        detail_gz += len(gzip.compress(raw, 6))
    report["details"] = {"bytes": detail_bytes, "gzip": detail_gz, "chunks": DETAIL_CHUNKS}
    logger.info(
        "published %s jobs (%s unique) — jobs.json %.0f KB (%.0f KB gz), state.json %.0f KB, "
        "details %.0f KB (%.0f KB gz)",
        report["count"], report["unique"], report["jobs.json"]["bytes"] / 1024,
        report["jobs.json"]["gzip"] / 1024, report["state.json"]["bytes"] / 1024,
        detail_bytes / 1024, detail_gz / 1024,
    )
    return report


# ── Merging shards into the published corpus ─────────────────────────────────

def merge_shards(published: dict, shards: list[dict], now: datetime | None = None) -> dict:
    """Fold scrape shards into the published corpus.

    Each shard is AUTHORITATIVE for the companies it lists: every published row
    of those companies is dropped and replaced by the shard's rows. A shard with
    ``companies: None`` covers everything (a full local run).

    Then two global passes that no single shard can do:
      * active rows unseen for STALE_DAYS are retired (catches companies that no
        shard scrapes any more), and
      * retired rows older than PURGE_DAYS are forgotten.
    """
    from .config import load_all_companies

    now = now or datetime.now(timezone.utc)
    jobs = list(published.get("jobs", []))
    state = list(published.get("state", []))
    details = dict(published.get("details", {}))
    health: dict[str, dict] = {c["name"]: {k: c.get(k) for k in
                                           ("last_scraped_at", "scrape_error_count",
                                            "consecutive_empty_scrapes")}
                               for c in published.get("companies", [])}
    runs = list(published.get("runs", []))

    for shard in shards:
        owned = shard.get("companies")
        if owned is None:
            jobs, state = [], []
        else:
            mine = set(owned)
            jobs = [r for r in jobs if r.get("company") not in mine]
            state = [r for r in state if r.get("company") not in mine]
        jobs.extend(shard.get("jobs", []))
        state.extend(shard.get("state", []))
        details.update(shard.get("details", {}))
        health.update(shard.get("health", {}))
        runs.extend(shard.get("runs", []))

    # Only configured companies survive; one dropped from the YAML disappears.
    configured = {c.get("name") for c in load_all_companies()}
    jobs = [r for r in jobs if r.get("company") in configured]
    state = [r for r in state if r.get("company") in configured]

    stale_cut = now - timedelta(days=STALE_DAYS)
    purge_cut = now - timedelta(days=PURGE_DAYS)
    kept_jobs = []
    for r in jobs:
        seen = _parse_aware(r.get("last_seen_at"))
        if seen and seen < stale_cut:
            row = {k: r.get(k) for k in STATE_FIELDS}
            row["active_status"] = ActiveStatus.removed.value
            row["removed_at"] = now.isoformat()
            state.append(row)
        else:
            kept_jobs.append(r)
    jobs = kept_jobs
    state = [r for r in state
             if not (str(r.get("active_status")) == ActiveStatus.removed.value
                     and (_parse_aware(r.get("removed_at")) or now) < purge_cut)]

    # A key must appear once. If a company moved between shards mid-flight the
    # newest sighting wins.
    def _dedupe(rows: list[dict]) -> list[dict]:
        best: dict[str, dict] = {}
        for r in rows:
            k = r.get("key")
            if not k:
                continue
            if k not in best or str(r.get("last_seen_at") or "") >= str(best[k].get("last_seen_at") or ""):
                best[k] = r
        return list(best.values())

    jobs = _dedupe(jobs)
    live = {r["key"] for r in jobs}
    state = [r for r in _dedupe(state) if r["key"] not in live]

    by_run: dict[str, dict] = {}
    for r in runs:
        by_run[f"{r.get('triggered_by')}|{r.get('started_at')}"] = r
    runs = sorted(by_run.values(), key=lambda r: str(r.get("started_at") or ""), reverse=True)[:RUNS_KEPT]

    return {"jobs": jobs, "state": state, "details": details, "health": health,
            "companies": [{"name": n, **h} for n, h in health.items()], "runs": runs}


def publish(data_dir: str | Path, shard_paths: list[str | Path]) -> dict:
    """Merge shard files into the published corpus in ``data_dir`` and rewrite it."""
    shards = []
    for p in shard_paths:
        s = json.loads(Path(p).read_text(encoding="utf-8"))
        if s.get("schema") != SCHEMA:
            raise ValueError(f"{p}: unexpected shard schema {s.get('schema')!r}")
        shards.append(s)
    merged = merge_shards(read_published(data_dir), shards)
    return write_published(data_dir, merged)


# ── Seeding a scratch database from the published corpus ─────────────────────

def load_snapshot_into_db(data_dir: str | Path, companies: set[str] | None = None) -> int:
    """Seed an empty scratch database from the published corpus.

    ``companies`` restricts the seed to one shard's companies — the shard only
    ever touches those, and seeding the rest would cost time for nothing.
    """
    corpus = read_published(data_dir)
    _dt = _parse_aware
    cols = {c.name for c in JobPosting.__table__.columns}  # type: ignore[attr-defined]
    restored = 0
    with Session(engine) as session:
        for r in corpus["runs"]:
            session.add(ScrapeRun(
                started_at=_dt(r.get("started_at")) or datetime.now(timezone.utc),
                finished_at=_dt(r.get("finished_at")),
                companies_scraped=int(r.get("companies_scraped") or 0),
                jobs_found=int(r.get("jobs_found") or 0),
                new_jobs=int(r.get("new_jobs") or 0),
                removed_jobs=int(r.get("removed_jobs") or 0),
                errors=int(r.get("errors") or 0),
                triggered_by=str(r.get("triggered_by") or ""),
            ))
        for src in (corpus["jobs"], corpus["state"]):
            for row in src:
                if companies is not None and row.get("company") not in companies:
                    continue
                data = {k: v for k, v in row.items() if k in cols and k != "id"}
                for f in ("posted_date", "first_seen_at", "last_seen_at", "removed_at"):
                    if f in data:
                        data[f] = _dt(data[f])
                data.setdefault("first_seen_at", datetime.now(timezone.utc))
                data.setdefault("last_seen_at", datetime.now(timezone.utc))
                data.setdefault("active_status", ActiveStatus.active.value)
                body = corpus["details"].get(str(row.get("id", "")), "")
                if body:
                    data["cleaned_description"] = body
                session.add(JobPosting(**data))
                restored += 1
        session.commit()
    logger.info("seeded %d posting(s) from %s", restored, data_dir)
    return restored


def seed_companies_into_db(data_dir: str | Path, companies: set[str] | None = None) -> int:
    """Create Company rows with their health counters carried over.

    Without these rows quarantine never fires and error counts never accumulate
    (the scratch database is new every run). Config says which companies exist;
    the published corpus says how healthy each has been.
    """
    from .config import load_all_companies

    prior = {c.get("name", ""): c for c in read_published(data_dir).get("companies", [])}
    created = 0
    with Session(engine) as session:
        existing = {c.name for c in session.exec(select(Company)).all()}
        for cfg in load_all_companies():
            name = cfg.get("name", "")
            if not name or name in existing or (companies is not None and name not in companies):
                continue
            was = prior.get(name, {})
            session.add(Company(
                name=name,
                category=cfg.get("category", ""),
                priority=cfg.get("priority", "C"),
                careers_url=cfg.get("careers_url", ""),
                ats_platform=cfg.get("ats_platform", ""),
                sector=cfg.get("sector", ""),
                enabled=bool(cfg.get("enabled", True)),
                scrape_error_count=int(was.get("scrape_error_count") or 0),
                consecutive_empty_scrapes=int(was.get("consecutive_empty_scrapes") or 0),
                last_scraped_at=_parse_aware(was.get("last_scraped_at")),
                notes=cfg.get("notes", ""),
            ))
            created += 1
        session.commit()
    logger.info("seeded %d company row(s)", created)
    return created
