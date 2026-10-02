# Ashborne Volt — working notes for Claude

US electrical-engineering job board. Cloned from Ashborne Silicon
(`D:\Job Scraper\rtl-dv-job-radar`) on 2026-10-01; fully separate repo, Vercel,
Render and Neon. Owner: entry-level focus, senior roles shown too.

## Rules that are not obvious from the code

- **Never build regexes through a shell heredoc.** Backslashes collapse (`\b`
  becomes a backspace byte that greps invisibly). Use the Edit/Write tools, or
  write a patch script to a file and run it with `py`.
- `backend/app/taxonomy.py` is the authority for categories; the frontend mirror
  is `frontend/src/lib/categories.ts`, tied by `tests/test_category_sync.py`.
  Every misfiled real title becomes a case in `tests/test_taxonomy_golden.py`.
- Tests import `backend.app.*` (not `app.*`) — mixing the two loads the SQLModel
  tables twice and errors.
- Publishing is shard-authoritative (`snapshot.merge_shards`): never reintroduce
  a union merge of job rows; it resurrects retired postings.
- `details/NN.json` is keyed by the stable id (`snapshot.stable_id(key)`), never
  by a database row id.
- The public API answers only `security.PUBLIC_ROUTES`. Adding an endpoint the
  frontend calls means adding it there (a test checks they exist in main.py).
- Workday: `total` is only reported on the first page; detail records carry the
  country when the list only names a city.
- Every catalog company must be classified for H1B in `eligibility.py`
  (sponsor / non-sponsor / unverified) — `tests/test_h1b_filter.py` enforces it.
- Commit only when the owner asks; never commit secrets. The VAPID private key
  lives in `C:\Users\saith\Ashborne-Volt-Secrets\` (not in the repo, not synced).
