# Ashborne Volt

Company-direct **electrical engineering jobs in the USA** — power systems,
renewables, controls, instrumentation, power electronics, machines, RF, EMC,
buildings & data centers, and transportation & aerospace — scraped straight from
employers' own job boards, classified, de-duplicated and résumé-matched.

Sister project of Ashborne Silicon (RTL/DV jobs); same architecture, separate
everything.

## How it works

```
GitHub Actions (every 3 h)
  plan ─▶ guard (tests) ─▶ scrape shards in parallel ─▶ publish (one commit)
                                │                            │
                     each shard scrapes its            frontend/public/data/
                     own companies into a              jobs.json · state.json ·
                     scratch SQLite, writes            details/00-15.json
                     a shard file                            │
                                                      Vercel redeploys ─▶ browser
                                                      (filters/search run locally)

Render API (Virginia) ──▶ Neon Postgres (us-east-1)
  résumé parse & match, prompt assembly, Gemini generation, PDF compile,
  push subscriptions. Jobs never touch the database.
```

* **Jobs are static files.** No database meter to exhaust, nothing to keep awake;
  a failed scrape leaves the last good data live.
* **Sharded scraping.** Companies are grouped by the job-board host they hit and
  packed into parallel jobs, so the catalog can grow to hundreds of employers.
* **Each shard owns its companies.** The publish step replaces their rows
  wholesale — a retired posting can never be resurrected by a merge.

## The classifier

`backend/app/taxonomy.py` decides whether a posting is an EE engineering job and
which of 12 categories it belongs to — title first, with explicit exclusions for
false friends (Power BI, SOX controls, data protection, electricians, chip design,
software). `backend/tests/test_taxonomy_golden.py` holds hand-labelled real titles
that every change must keep passing.

## Duplicates

1. Same requisition → one row (company + ATS requisition id).
2. Same apply URL → one row.
3. One opening at several sites / reposted → one card with "+N locations"
   (`dup_group` = company + normalised title + description signature).
4. Staffing agencies and job aggregators are never scraped.

## Local development

```bash
# backend
cd backend && py -m pip install -r requirements.lock.txt
py -m pytest -q
py -m uvicorn app.main:app --port 8000

# frontend (proxies /api to :8000)
cd frontend && npm ci && npm run dev

# a full local scrape into frontend/public/data
py -m backend.app.run_static

# measure a job board before adding it
py scripts/verify_boards.py "Duke Energy|workday|dukeenergy.wd1/search"
```

## Adding a company

1. Find its board: `py scripts/find_ats_browser.py --candidates=file.csv`
   (renders the careers page and captures the job-board calls).
2. Measure it: `py scripts/verify_boards.py "Name|workday|tenant.wd1/Site"`.
3. Add it to `config/companies.yaml` (about ten lines, no code) and classify its
   H1B sponsorship in `backend/app/eligibility.py` — a test enforces both.

See `DEPLOYMENT.md` for hosting and `SECURITY.md` for the security model.
