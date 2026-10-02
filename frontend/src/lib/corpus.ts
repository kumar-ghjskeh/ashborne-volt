/**
 * The job corpus, served as a static file instead of queried from a database.
 *
 * The whole corpus is ~270 KB gzipped, so the browser fetches it once and then
 * filters, searches, sorts and paginates locally. That is faster than the round
 * trip it replaces (no cold start, no cross-country hop) and it removes the
 * component that repeatedly took this app down: a metered database whose free
 * transfer quota the app kept exhausting.
 *
 * Descriptions live in a second file, fetched lazily the first time a posting is
 * opened, so the initial load stays small.
 */
import type { Job } from './types'
import { HIDDEN_CATEGORIES } from './categories'
import { registerCompanyDomains } from '../components/CompanyLogo'

export interface CorpusCompany {
  name: string
  category: string
  priority: string
  sector?: string
  hq?: string
  domain?: string
  unique_jobs?: number
  careers_url: string
  ats_platform: string
  engine: string
  enabled: boolean
  usa_active_jobs: number
  total_active_jobs: number
  viewable_jobs: number
  entry_level_jobs: number
  new_jobs_today: number
  parser_confidence: number
  /** True when the source is actually producing postings — the honest signal,
   *  rather than merely being listed in the config. */
  auto_connected: boolean
  scrape_status: string
  last_scraped_at: string | null
  scrape_error_count: number
  consecutive_empty_scrapes?: number
  quarantined?: boolean
}

export interface CorpusRun {
  id: number
  started_at: string
  finished_at: string | null
  companies_scraped: number
  jobs_found: number
  new_jobs: number
  removed_jobs: number
  errors: number
  triggered_by: string
}

export interface Corpus {
  generated_at: string
  count: number
  unique_count?: number
  jobs: Job[]
  companies: CorpusCompany[]
  runs: CorpusRun[]
}

// Cache-busted per deploy so a fresh snapshot is picked up immediately, while
// repeat visits within a deploy are served from the browser cache.
const BUILD = (import.meta as { env?: Record<string, string> }).env?.VITE_BUILD_ID || ''
const JOBS_URL = `/data/jobs.json${BUILD ? `?v=${BUILD}` : ''}`
// Descriptions are split into DETAIL_CHUNKS files by id, so opening one posting
// downloads ~1/16 of the bodies instead of all of them.
const DETAIL_CHUNKS = 16
const chunkUrl = (i: number) => `/data/details/${String(i).padStart(2, '0')}.json${BUILD ? `?v=${BUILD}` : ''}`

let _corpus: Promise<Corpus> | null = null
let _details: Promise<Record<string, string>> | null = null
const _chunks = new Map<number, Promise<Record<string, string>>>()

function loadChunk(i: number): Promise<Record<string, string>> {
  let p = _chunks.get(i)
  if (!p) {
    p = fetch(chunkUrl(i))
      .then((r) => (r.ok ? r.json() : { descriptions: {} }))
      .then((d: { descriptions?: Record<string, string> }) => d.descriptions || {})
      .catch(() => {
        _chunks.delete(i)
        return {}
      })
    _chunks.set(i, p)
  }
  return p
}

/** One posting's description — fetches only the chunk that holds it. */
export async function loadDetail(id: number | string): Promise<string> {
  const n = Number(id)
  if (!Number.isFinite(n)) return ''
  const chunk = await loadChunk(n % DETAIL_CHUNKS)
  return chunk[String(id)] || ''
}

/** The corpus, fetched once per page load. */
export function loadCorpus(): Promise<Corpus> {
  if (!_corpus) {
    _corpus = fetch(JOBS_URL)
      .then((r) => {
        if (!r.ok) throw new Error(`corpus ${r.status}`)
        return r.json()
      })
      .then((d: Corpus) => {
        // Only ACTIVE postings are browseable. possibly_removed rows are carried
        // in the file so the scraper's miss counter survives a rebuild — they are
        // not jobs the user should see.
        d.jobs = (d.jobs || []).filter(
          (j) => String((j as unknown as Record<string, unknown>).active_status ?? 'active') === 'active',
        )
        d.count = d.jobs.length
        registerCompanyDomains(d.companies || [])
        return d
      })
      .catch((e) => {
        _corpus = null // let a later call retry rather than caching the failure
        throw e
      })
  }
  return _corpus
}

/** Every description body — for full-text search and résumé ranking only.
 *  Opening a single posting should use loadDetail() instead. */
export function loadDetails(): Promise<Record<string, string>> {
  if (!_details) {
    _details = Promise.all(Array.from({ length: DETAIL_CHUNKS }, (_, i) => loadChunk(i)))
      .then((parts) => Object.assign({}, ...parts))
  }
  return _details
}

export function clearCorpusCache(): void {
  _corpus = null
  _details = null
  _chunks.clear()
}


/** Filter counts, computed from the corpus (was GET /jobs/facets). */
export async function facetsFromCorpus(usaOnly = true, includeSoftware = false) {
  const c = await loadCorpus()
  const rows = c.jobs.filter(
    (j) => (!usaOnly || j.is_usa) && (includeSoftware || !j.is_software_only)
      && !HIDDEN_CATEGORIES.has(String(j.role_category)),
  )
  const tally = (pick: (j: typeof rows[number]) => string) => {
    const m = new Map<string, number>()
    for (const j of rows) {
      const v = pick(j)
      if (v) m.set(v, (m.get(v) || 0) + 1)
    }
    return [...m.entries()].map(([value, count]) => ({ value, count }))
      .sort((a, b) => b.count - a.count)
  }
  const dayAgo = Date.now() - 24 * 3600_000
  const eff = (j: typeof rows[number]) =>
    Date.parse(String((j.posted_date && j.posted_date_known !== false ? j.posted_date : null) || j.first_seen_at))
  return {
    role_categories: tally((j) => j.role_category),
    priorities: tally((j) => j.company_priority),
    remote_statuses: tally((j) => j.remote_status),
    states: tally((j) => j.state),
    entry_level_count: rows.filter((j) => j.is_entry_level || j.is_candidate_friendly).length,
    candidate_friendly_count: rows.filter((j) => j.is_candidate_friendly).length,
    senior_count: rows.filter((j) => j.is_senior).length,
    remote_count: rows.filter((j) => /remote/i.test(j.remote_status || '')).length,
    new_24h_count: rows.filter((j) => eff(j) >= dayAgo).length,
  }
}

/** Typed, counted autocomplete suggestions (was GET /jobs/search-suggestions). */
export async function suggestionsFromCorpus(q: string, limit = 8) {
  const term = q.trim().toLowerCase()
  if (term.length < 2) return []
  const c = await loadCorpus()
  // Suggest only what a search can actually return: active, US, visible categories.
  const HIDDEN = HIDDEN_CATEGORIES
  const rows = c.jobs.filter(
    (j) =>
      j.is_usa &&
      !j.is_software_only &&
      (j.active_status ?? 'active') === 'active' &&
      !HIDDEN.has(String(j.role_category)),
  )
  const bucket = (pick: (j: typeof rows[number]) => string, type: 'company' | 'title' | 'skill') => {
    const m = new Map<string, number>()
    for (const j of rows) {
      const v = (pick(j) || '').trim()
      if (v && v.toLowerCase().includes(term)) m.set(v, (m.get(v) || 0) + 1)
    }
    return [...m.entries()].map(([value, count]) => ({
      value, type, count,
      rank: value.toLowerCase().startsWith(term) ? 0 : 1,
    }))
  }
  const all = [
    ...bucket((j) => j.company, 'company').sort((a, b) => a.rank - b.rank || b.count - a.count).slice(0, 3),
    ...bucket((j) => j.job_title, 'title').sort((a, b) => a.rank - b.rank || b.count - a.count).slice(0, limit),
    ...bucket((j) => j.role_category, 'skill').sort((a, b) => a.rank - b.rank || b.count - a.count).slice(0, 3),
  ]
  const seen = new Set<string>()
  return all
    .filter((s) => {
      const k = s.value.toLowerCase()
      if (seen.has(k)) return false
      seen.add(k)
      return true
    })
    .sort((a, b) => Number(a.type !== 'company') - Number(b.type !== 'company') || b.count - a.count)
    .slice(0, limit)
    .map(({ value, type, count }) => ({ value, type, count }))
}
