# Security

## Reporting a vulnerability

Please use GitHub's **private vulnerability reporting** (Security tab → "Report a
vulnerability"). Do not open a public issue.

## Model

**Secrets** live only in the Render environment and GitHub Actions secrets —
never in this repository, never in chat. GitHub secret scanning with push
protection blocks commits that contain credentials, and `gitleaks` runs in CI.
The VAPID *public* key in `backend/app/config.py` is public by design.

**Scraped content is untrusted.**
* Descriptions are rendered as text by React (no `innerHTML` anywhere).
* Every outbound link passes `safeUrl()` — only `http(s)` URLs reach an `href`.
* Job text sent to Gemini is passed as data inside a prompt, and the output is
  rendered as text.

**Frontend** (`frontend/vercel.json`): strict Content-Security-Policy (the single
inline script is allowed by SHA-256, checked in CI by `scripts/check_csp.py`),
HSTS, `frame-ancestors 'none'`, nosniff, strict referrer policy.

**API** (`backend/app/security.py`):
* route allowlist — only the endpoints the app uses answer; everything else is 404
* CORS limited to the production domain and this project's Vercel previews,
  without credentials
* per-IP rate limits, strictest on the Gemini and PDF endpoints
* request-size cap before the body is read; per-field size caps on prompts
* no interactive API docs on the public service

**Privacy.** Your résumé is parsed and kept in your browser (localStorage). The
API parses and scores it statelessly and stores nothing. Saved jobs, notes and
searches are also browser-only. Optional PDF compilation sends the LaTeX to a
third-party compiler (latex.ytotech.com).

**Supply chain.** Python installs from an exact lock file; npm from
`package-lock.json` via `npm ci`. GitHub Actions are pinned to commit SHAs.
Dependabot, `pip-audit`, `npm audit` and CodeQL run continuously.

**Scraping etiquette.** Only employers' public job-board endpoints, one request
at a time per host, with delays and back-off. No job aggregators, no logins, no
CAPTCHAs bypassed.
