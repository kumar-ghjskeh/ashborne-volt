/**
 * Client-side job querying — the exact semantics the API used to apply.
 *
 * This mirrors `_build_job_query` in backend/app/main.py. Filtering ~1,500 rows
 * in JS is instant, so moving it into the browser removes a network round trip
 * per keystroke rather than adding work. The rules below are deliberately kept
 * one-to-one with the server so results do not quietly drift:
 *
 *   - USA-only is STRICT: a posting must be positively identified as US.
 *   - The default view hides the categories in lib/categories.ts HIDDEN_CATEGORIES.
 *   - Recency uses the effective date — the real posted date when the source
 *     published one, else when we first saw it — so undated sources (Google,
 *     Meta) are not invisible, and the filter agrees with the card's own label.
 *   - Search ranks title hits above body mentions, because broad domain terms
 *     ("power") otherwise match most of the corpus and the top result is wrong.
 *   - One card per company+role; siblings at other sites collapse into it.
 */
import type { Filters, Job } from './types'
// One shared set (lib/categories.ts), kept equal to the backend by a test —
// three drifting copies of this list made filter counts disagree on Ashborne Silicon.
import { HIDDEN_CATEGORIES } from './categories'

const lc = (s: unknown) => String(s ?? '').toLowerCase()

/** Real posted date when known, else first-seen. Mirrors _effective_date(). */
export function effectiveDate(j: Job): number {
  const raw =
    (j.posted_date && j.posted_date_known !== false ? j.posted_date : null) || j.first_seen_at
  const t = raw ? Date.parse(String(raw)) : NaN
  return Number.isNaN(t) ? 0 : t
}

/** Ranks how well a row answers the query. Mirrors _keyword_rank(). */
export function keywordRank(j: Job, query: string): number {
  const q = query.trim().toLowerCase()
  if (!q) return 0
  const toks = q.split(/\s+/).filter(Boolean)
  const title = lc(j.job_title)
  const ntitle = lc(j.normalized_title)
  const company = lc(j.company)
  if (title.includes(q)) return 100
  if (ntitle.includes(q)) return 92
  if (company.includes(q)) return 88
  if (toks.length > 1 && toks.every((t) => title.includes(t))) return 75
  if (lc(j.matched_keywords).includes(q)) return 60
  if (lc(j.role_category).includes(q)) return 55
  if (toks.some((t) => title.includes(t))) return 40
  return 10
}

/** Fields a free-text query searches, mirroring the server's field list. */
function haystack(j: Job, bodies?: Record<string, string>): string {
  return [
    j.job_title,
    j.normalized_title,
    j.company,
    j.matched_keywords,
    j.role_category,
    j.experience_level,
    j.state,
    j.location,
    j.ats_platform,
    j.job_skills,
    j.description_snippet,
    bodies?.[String(j.id)] || '',
  ]
    .map(lc)
    .join(' ')
}

export function matchesFilters(j: Job, f: Filters, bodies?: Record<string, string>): boolean {
  // USA-only, strict. "Location unknown" is not "in the US".
  if (f.usa_only !== false && !j.is_usa) return false
  if (!f.include_software && j.is_software_only) return false
  if (!f.include_adjacent && HIDDEN_CATEGORIES.has(String(j.role_category))) return false
  if (f.include_senior === false && j.is_senior) return false

  if (f.company && lc(j.company) !== lc(f.company)) return false
  if (f.priority && String(j.company_priority) !== String(f.priority)) return false
  if (f.role_category && String(j.role_category) !== String(f.role_category)) return false
  if (f.state && lc(j.state) !== lc(f.state)) return false
  if (f.remote && !lc(j.remote_status).includes(lc(f.remote))) return false
  if (f.min_score != null && (j.new_grad_fit ?? 0) < Number(f.min_score)) return false
  // H1B: STRICT — only employers known to sponsor, and only postings whose own
  // text does not demand citizenship, a green card or ITAR access. The old line
  // was `j.sponsors_h1b === false`, which (a) let every unknown employer through
  // and (b) read a field the corpus never carried, so it matched everything.
  if (f.h1b_only) {
    if (j.sponsors_h1b !== true) return false
    const risk = lc(j.eligibility_risk || 'low')
    if (risk === 'high' || risk === 'medium') return false
  }

  if (f.level_filter) {
    const want = lc(f.level_filter)
    if (want === 'entry' && !(j.is_entry_level || j.is_candidate_friendly)) return false
    if (want === 'senior' && !j.is_senior) return false
  }
  if (f.posted_within_hours) {
    if (effectiveDate(j) < Date.now() - Number(f.posted_within_hours) * 3600_000) return false
  }
  if (f.new_since_hours) {
    if (Date.parse(String(j.first_seen_at)) < Date.now() - Number(f.new_since_hours) * 3600_000) {
      return false
    }
  }
  if (f.keyword && f.keyword.trim()) {
    const hay = haystack(j, bodies)
    // Every token must appear somewhere — an AND of tokens, as the server did.
    const ok = f.keyword
      .trim()
      .toLowerCase()
      .split(/\s+/)
      .every((t) => hay.includes(t))
    if (!ok) return false
  }
  if (f.skills) {
    const need = String(f.skills)
      .split(',')
      .map((s) => s.trim().toLowerCase())
      .filter(Boolean)
    const hay = `${lc(j.job_skills)} ${lc(j.matched_keywords)} ${lc(j.description_snippet)}`
    if (!need.every((s) => hay.includes(s))) return false
  }
  return true
}

const SORTERS: Record<string, (a: Job, b: Job) => number> = {
  new_grad_fit: (a, b) => (b.new_grad_fit ?? 0) - (a.new_grad_fit ?? 0),
  match_score: (a, b) => (b.match_score ?? 0) - (a.match_score ?? 0),
  experienced_fit: (a, b) => (b.experienced_fit ?? 0) - (a.experienced_fit ?? 0),
  posted_date: (a, b) => effectiveDate(b) - effectiveDate(a),
  first_seen_at: (a, b) =>
    Date.parse(String(b.first_seen_at)) - Date.parse(String(a.first_seen_at)),
  company: (a, b) => String(a.company).localeCompare(String(b.company)),
  job_title: (a, b) => String(a.job_title).localeCompare(String(b.job_title)),
}

export interface QueryResult {
  items: Job[]
  total_count: number
  page: number
  limit: number
  total_pages: number
  has_next: boolean
  has_prev: boolean
}

export function queryJobs(
  all: Job[],
  f: Filters,
  page = 1,
  limit = 50,
  bodies?: Record<string, string>,
): QueryResult {
  const kw = (f.keyword || '').trim()
  let rows = all.filter((j) => matchesFilters(j, f, bodies))

  const sortBy = f.sort_by || 'new_grad_fit'
  const primary = SORTERS[sortBy] || SORTERS.new_grad_fit
  rows.sort((a, b) => {
    // With a query, relevance leads — unless the user explicitly picked a sort,
    // in which case that wins and relevance becomes the tiebreaker.
    if (kw && sortBy === 'new_grad_fit') {
      const r = keywordRank(b, kw) - keywordRank(a, kw)
      if (r) return r
    }
    const p = primary(a, b)
    if (p) return p
    if (kw) {
      const r = keywordRank(b, kw) - keywordRank(a, kw)
      if (r) return r
    }
    return (b.match_score ?? 0) - (a.match_score ?? 0)
  })

  // One card per company+role. Siblings are real, separately-applicable reqs, so
  // nothing is dropped — the survivor carries the count and the rest stay
  // reachable through it.
  if (f.group_roles !== false) {
    const seen = new Map<string, Job>()
    const order: string[] = []
    for (const j of rows) {
      const key = `${lc(j.company)}|${lc(j.normalized_title || j.job_title)}`
      const hit = seen.get(key)
      if (hit) {
        hit.group_count = (hit.group_count ?? 1) + 1
      } else {
        seen.set(key, { ...j, group_count: 1 })
        order.push(key)
      }
    }
    rows = order.map((k) => seen.get(k)!)
  }

  const total = rows.length
  const total_pages = Math.max(1, Math.ceil(total / limit))
  const start = (page - 1) * limit
  return {
    items: rows.slice(start, start + limit),
    total_count: total,
    page,
    limit,
    total_pages,
    has_next: page < total_pages,
    has_prev: page > 1,
  }
}

/** Sibling requisitions for the same role at other sites. */
export function siblingsOf(all: Job[], job: Job): Job[] {
  const key = `${lc(job.company)}|${lc(job.normalized_title || job.job_title)}`
  return all.filter(
    (j) => j.id !== job.id && `${lc(j.company)}|${lc(j.normalized_title || j.job_title)}` === key,
  )
}
