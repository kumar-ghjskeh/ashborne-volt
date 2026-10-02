import { useCallback, useEffect, useRef, useState } from 'react'
import './index.css'
import { CompaniesPage } from './components/CompaniesPage'
import { ActiveFilters } from './components/ActiveFilters'
import { FilterSidebar } from './components/FilterSidebar'
import { JobCard } from './components/JobCard'
import { JobDetailsPanel } from './components/JobDetailsPanel'
import { Pagination } from './components/Pagination'
import { ScrapeHealth } from './components/ScrapeHealth'
import { SummaryCards } from './components/SummaryCards'
import { TopNav, type Tab } from './components/TopNav'
import { Icon } from './components/Icon'
import { ResumeIntel } from './components/ResumeIntel'
import { LegalModal, type LegalTab } from './components/LegalModal'
import { groupByCanonical } from './lib/dedupe'
import { useTheme } from './lib/theme'
import { useIsMobile } from './lib/useIsMobile'
import { loadCorpus, loadDetails, clearCorpusCache } from './lib/corpus'
import { CategoryBar } from './components/CategoryBar'
import { HIDDEN_CATEGORIES } from './lib/categories'
import { queryJobs, effectiveDate } from './lib/query'
import { freshness } from './lib/datetime'
import * as userState from './lib/userState'
import { exportMarkedJobs } from './lib/csv'
import { getMatchScores } from './lib/resume'
import type { AnalyticsSummary, Filters, Job, PaginatedResponse } from './lib/types'

const PAGE_SIZE = 50

const footerLinkStyle: React.CSSProperties = {
  background: 'none', border: 'none', padding: 0, cursor: 'pointer',
  color: 'var(--text-secondary)', fontSize: 12, fontWeight: 600, textDecoration: 'underline',
}

const TAB_LABELS: Partial<Record<Tab, string>> = {
  'all': 'verified jobs',
  'resume': 'jobs ranked by resume match',
  'entry-level': 'new-grad & entry-level jobs',
  'best': 'high-fit jobs',
  'saved': 'saved jobs',
  'applied': 'applied jobs',
}

function SkeletonCard() {
  return (
    <div style={{ background: 'var(--surface)', border: '1px solid var(--border)', borderRadius: 8, padding: '15px 16px' }}>
      <div style={{ display: 'flex', gap: 12, alignItems: 'flex-start' }}>
        <div className="skeleton" style={{ width: 46, height: 46, borderRadius: 10, flexShrink: 0 }} />
        <div style={{ flex: 1, display: 'flex', flexDirection: 'column', gap: 8 }}>
          <div className="skeleton" style={{ height: 16, borderRadius: 4, width: '70%' }} />
          <div className="skeleton" style={{ height: 12, borderRadius: 4, width: '40%' }} />
        </div>
        <div className="skeleton" style={{ width: 52, height: 52, borderRadius: '50%', flexShrink: 0 }} />
      </div>
      <div style={{ display: 'flex', gap: 6, marginTop: 12 }}>
        {[60, 80, 70].map((w, i) => <div key={i} className="skeleton" style={{ height: 22, width: w, borderRadius: 4 }} />)}
      </div>
    </div>
  )
}

function EmptyState({ tab, query, offline }: { tab: Tab; query?: string; offline?: boolean }) {
  // The backend is unreachable or erroring. Saying "no jobs match your filters"
  // here blames the user's filters for an outage and sends them fiddling with
  // controls that cannot help — so say what is actually wrong.
  if (offline) {
    return (
      <div style={{ background: 'var(--surface)', border: '1px solid var(--warning-border)', borderRadius: 8, padding: '52px 24px', textAlign: 'center' }}>
        <div style={{
          width: 56, height: 56, borderRadius: '50%', background: 'var(--warning-light)',
          display: 'flex', alignItems: 'center', justifyContent: 'center', margin: '0 auto 14px',
        }}>
          <Icon name="activity" size={26} color="var(--warning)" />
        </div>
        <div style={{ fontSize: 16, fontWeight: 700, color: 'var(--text-primary)', marginBottom: 8 }}>
          Can&rsquo;t reach the job service
        </div>
        <div style={{ fontSize: 13, color: 'var(--text-secondary)', maxWidth: 460, margin: '0 auto 16px', lineHeight: 1.6 }}>
          Your filters are fine &mdash; the server isn&rsquo;t responding, so nothing can be listed
          right now. This retries by itself; saved jobs and your r&eacute;sum&eacute; are unaffected.
          Check <strong>Data Health</strong> for the current status.
        </div>
      </div>
    )
  }
  // Active company/keyword search that returned nothing → likely an untracked
  // company (e.g. AMD). Be explicit and offer a direct careers search.
  if (query && query.trim() && ['all', 'best', 'entry-level'].includes(tab)) {
    const q = query.trim()
    const careers = `https://www.google.com/search?q=${encodeURIComponent(`${q} "electrical engineer" jobs careers`)}`
    return (
      <div style={{ background: 'var(--surface)', border: '1px solid var(--border)', borderRadius: 8, padding: '52px 24px', textAlign: 'center' }}>
        <div style={{
          width: 56, height: 56, borderRadius: '50%', background: 'var(--surface-muted)',
          display: 'flex', alignItems: 'center', justifyContent: 'center', margin: '0 auto 14px',
        }}>
          <Icon name="search" size={26} color="var(--text-tertiary)" />
        </div>
        <div style={{ fontSize: 16, fontWeight: 700, color: 'var(--text-primary)', marginBottom: 8 }}>
          No tracked jobs match “{q}”
        </div>
        <div style={{ fontSize: 13, color: 'var(--text-secondary)', maxWidth: 420, margin: '0 auto 16px', lineHeight: 1.6 }}>
          We may not track this company yet, or it has no open electrical-engineering roles right now.
          You can search their careers site directly.
        </div>
        <a href={careers} target="_blank" rel="noopener noreferrer" className="btn btn-outline" style={{ textDecoration: 'none' }}>
          Search “{q}” roles directly <Icon name="external" size={14} />
        </a>
      </div>
    )
  }
  const msgs: Partial<Record<Tab, { title: string; sub: string }>> = {
    'entry-level': { title: 'No new-grad jobs match your filters', sub: 'Try widening filters or refresh jobs to pull the latest postings.' },
    'saved': { title: 'No saved jobs', sub: 'Click the bookmark icon on any job to save it for later.' },
    'applied': { title: 'No applied jobs', sub: "Mark jobs as 'Applied' to track your applications here." },
    'all': { title: 'No jobs match your filters', sub: 'Try widening your filters or clearing the search.' },
    'resume': { title: 'Upload your resume to see matches', sub: 'Use the panel on the left to upload your resume — every job will be ranked by how well it fits you.' },
  }
  const msg = msgs[tab] || { title: 'No results', sub: 'Try changing your filters.' }
  return (
    <div style={{ background: 'var(--surface)', border: '1px solid var(--border)', borderRadius: 8, padding: '56px 24px', textAlign: 'center' }}>
      <div style={{
        width: 56, height: 56, borderRadius: '50%', background: 'var(--surface-muted)',
        display: 'flex', alignItems: 'center', justifyContent: 'center', margin: '0 auto 14px',
      }}>
        <Icon name="search" size={26} color="var(--text-tertiary)" />
      </div>
      <div style={{ fontSize: 16, fontWeight: 700, color: 'var(--text-primary)', marginBottom: 8 }}>{msg.title}</div>
      <div style={{ fontSize: 13, color: 'var(--text-secondary)', maxWidth: 360, margin: '0 auto' }}>{msg.sub}</div>
    </div>
  )
}

function ResultsSummary({ tab, loading, total, page, totalPages, analytics }: {
  tab: Tab; loading: boolean; total: number; page: number; totalPages: number; analytics: AnalyticsSummary | null
}) {
  const label = TAB_LABELS[tab] || 'jobs'
  return (
    <div style={{ marginBottom: 12 }}>
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'baseline', flexWrap: 'wrap', gap: 8 }}>
        <div style={{ fontSize: 15, color: 'var(--text-primary)' }}>
          {loading ? <span style={{ color: 'var(--text-secondary)' }}>Loading…</span> : (
            <><strong style={{ fontWeight: 800 }}>{total.toLocaleString()}</strong> <span style={{ color: 'var(--text-secondary)' }}>{label}</span></>
          )}
        </div>
        <div style={{ display: 'flex', alignItems: 'center', gap: 12 }}>
          {(tab === 'applied' || tab === 'saved') && total > 0 && (
            <button
              onClick={() => exportMarkedJobs(tab === 'applied' ? 'applied' : 'saved')}
              style={{ fontSize: 12, fontWeight: 700, color: 'var(--primary)', display: 'inline-flex', alignItems: 'center', gap: 4, background: 'none', border: 'none', cursor: 'pointer', padding: 0 }}>
              <Icon name="external" size={12} color="var(--primary)" /> Export CSV
            </button>
          )}
          {total > 0 && totalPages > 1 && (
            <span style={{ fontSize: 12, color: 'var(--text-tertiary)' }}>Page {page} of {totalPages}</span>
          )}
        </div>
      </div>
      {!loading && analytics && total > 0 && (
        <div style={{ display: 'flex', gap: 14, marginTop: 6, flexWrap: 'wrap', fontSize: 12, color: 'var(--text-secondary)' }}>
          <span><strong style={{ color: 'var(--success)' }}>{analytics.new_24h}</strong> new today</span>
          <span><strong style={{ color: 'var(--accent-gold)' }}>{analytics.high_score_count}</strong> high-fit</span>
          <span><strong style={{ color: 'var(--primary)' }}>{analytics.strict_entry_count ?? analytics.entry_level_count}</strong> truly entry-level</span>
          <span><strong style={{ color: 'var(--text-primary)' }}>{analytics.total_companies}</strong> companies tracked</span>
        </div>
      )}
      {!loading && tab === 'entry-level' && analytics && (
        <div style={{ marginTop: 6, fontSize: 12, color: 'var(--text-tertiary)' }}>
          <strong style={{ color: 'var(--teal)' }}>{analytics.strict_entry_count ?? 0}</strong> explicitly entry-level ·{' '}
          <strong style={{ color: 'var(--primary)' }}>{analytics.candidate_friendly_count ?? 0}</strong> likely-junior (non-senior EE roles at top employers — check each job's seniority confidence)
        </div>
      )}
    </div>
  )
}

export default function App() {
  const { theme, toggle: toggleTheme } = useTheme()
  const isMobile = useIsMobile()
  const [filtersOpen, setFiltersOpen] = useState(false)
  const [tab, setTab] = useState<Tab>('all')
  const [page, setPage] = useState(1)
  const [paginatedJobs, setPaginatedJobs] = useState<PaginatedResponse<Job> | null>(null)
  const [analytics, setAnalytics] = useState<AnalyticsSummary | null>(null)
  // Default shows every live role (incl. senior) — the New Grad tab + seniority
  // chips narrow it. include_senior stays true; the toggle was removed.
  const [filters, setFilters] = useState<Filters>({ usa_only: true, include_senior: true })
  const [search, setSearch] = useState('')
  const [selectedJob, setSelectedJob] = useState<Job | null>(null)
  const [loading, setLoading] = useState(true)
  const [refreshing, setRefreshing] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [legal, setLegal] = useState<LegalTab | null>(null)
  const [corpusStamp, setCorpusStamp] = useState<string>('')
  const [matchMap, setMatchMap] = useState<Record<string, { resume_match: number; apply_priority: string }>>({})
  // Default to New Grad Fit: for a new grad, "show me the roles I can realistically
  // get, best fit first" is the most intuitive ranking (a ng=100 New-College-Grad
  // role surfaces at the top instead of being buried by the resume-overlap blend).
  const [resumeSort, setResumeSort] = useState('new_grad_fit')
  const jobListRef = useRef<HTMLDivElement>(null)

  const NO_FETCH: Tab[] = ['companies', 'health']

  // Stale-while-revalidate cache so re-visiting a tab / page is instant (no
  // blank "Loading…"): we paint the cached result immediately, then refresh it
  // silently in the background. Mutations (refresh, save/apply, resume change)
  // clear it via reload().
  const jobsCache = useRef<Map<string, PaginatedResponse<Job>>>(new Map())

  // Analytics are counted off the corpus that is already in memory — the same
  // numbers the /analytics/summary endpoint returned, without the round trip.
  const loadAnalytics = useCallback(async () => {
    try {
      const corpus = await loadCorpus()
      setCorpusStamp(corpus.generated_at)
      const browseable = corpus.jobs.filter(
        (j) => j.is_usa && !j.is_software_only
          && !HIDDEN_CATEGORIES.has(String(j.role_category)),
      )
      const dayAgo = Date.now() - 24 * 3600_000
      setAnalytics({
        total_active: browseable.length,
        new_24h: browseable.filter((j) => effectiveDate(j) >= dayAgo).length,
        entry_level_count: browseable.filter((j) => j.is_entry_level || j.is_candidate_friendly).length,
        usa_count: browseable.length,
        remote_count: browseable.filter((j) => /remote/i.test(j.remote_status || '')).length,
        high_score_count: browseable.filter((j) => (j.new_grad_fit ?? 0) >= 65).length,
        saved_count: userState.countByStatus('saved'),
        applied_count: userState.countByStatus('applied'),
        total_companies: corpus.companies.filter((c) => c.enabled).length,
        last_run: (corpus.runs && corpus.runs[0]) || null,
      } as AnalyticsSummary)
    } catch { /* non-fatal */ }
  }, [])

  // Everything is answered from the static corpus fetched once per load: no
  // database, no per-keystroke round trip. The tabs differ only in which filters
  // they add on top, which is exactly what the API endpoints used to do.
  const fetchJobs = useCallback(async (): Promise<PaginatedResponse<Job>> => {
    const corpus = await loadCorpus()
    // A free-text query should search descriptions too, as the server did. Those
    // load lazily, so only pull them when there is actually something to search.
    const bodies = filters.keyword?.trim() ? await loadDetails() : undefined
    const withMarks = corpus.jobs.map((j) => userState.applyMark(j))

    if (tab === 'resume') {
      // Scores come from the stateless matcher (cached per corpus version), then
      // ranking and paging happen here — same order the endpoint produced.
      const scores = await getMatchScores()
      if (!scores.size) {
        return { items: [], total_count: 0, page: 1, limit: PAGE_SIZE,
                 total_pages: 1, has_next: false, has_prev: false,
                 no_resume: true } as PaginatedResponse<Job> & { no_resume: boolean }
      }
      const scored = withMarks
        .filter((j) => scores.has(j.id) && j.is_usa && !j.is_software_only)
        .map((j) => ({ ...j, ...scores.get(j.id)! }))
      const key = resumeSort === 'resume_match' ? 'resume_match'
        : resumeSort === 'new_grad_fit' ? 'new_grad_fit'
        : resumeSort === 'experience' ? 'experienced_fit'
        : 'apply_priority_score'
      const num = (j: unknown, f: string) => Number((j as Record<string, unknown>)[f] ?? 0)
      scored.sort((a, b) => (num(b, key) - num(a, key)) || (num(b, 'resume_match') - num(a, 'resume_match')))
      const total = scored.length
      const start = (page - 1) * PAGE_SIZE
      const totalPages = Math.max(1, Math.ceil(total / PAGE_SIZE))
      return { items: scored.slice(start, start + PAGE_SIZE) as Job[], total_count: total,
               page, limit: PAGE_SIZE, total_pages: totalPages,
               has_next: page < totalPages, has_prev: page > 1 }
    }

    if (tab === 'saved' || tab === 'applied') {
      // Your own lists: status comes from browser storage, and the relevance and
      // seniority gates are deliberately off — you chose these jobs explicitly.
      const wanted = tab === 'saved' ? 'saved' : 'applied'
      const mine = withMarks.filter((j) => j.active_status === wanted)
      return queryJobs(mine, { ...filters, usa_only: false, include_adjacent: true,
                               include_senior: true, group_roles: false }, page, PAGE_SIZE, bodies)
    }

    const tabFilters: Filters =
      tab === 'entry-level' ? { ...filters, level_filter: 'entry' }
      : tab === 'best'      ? { ...filters, min_score: Math.max(Number(filters.min_score ?? 0), 65) }
      : filters
    return queryJobs(withMarks, tabFilters, page, PAGE_SIZE, bodies)
  }, [tab, filters, page, resumeSort])

  const loadJobs = useCallback(async () => {
    if (NO_FETCH.includes(tab)) return
    const key = `${tab}|${JSON.stringify(filters)}|${page}|${resumeSort}`
    const cached = jobsCache.current.get(key)
    if (cached) {
      setPaginatedJobs(cached)   // instant paint from cache
      setLoading(false)
    } else {
      setLoading(true)
    }
    setError(null)
    try {
      const data = await fetchJobs()
      jobsCache.current.set(key, data)
      setPaginatedJobs(data)
      setSelectedJob((cur) => (cur ? data.items.find((j) => j.id === cur.id) ?? cur : cur))
      // Overlay resume-match badges on cards (non-resume tabs) — one batch call.
      if (tab !== 'resume' && data.items.length) {
        // Résumé badges come from the same cached scores; the board works fine
        // without a résumé, so a failure here must never surface as an error.
        getMatchScores()
          .then((scores) => {
            const map: Record<string, { resume_match: number; apply_priority: string }> = {}
            for (const j of data.items) {
              const m = scores.get(j.id)
              if (m) map[String(j.id)] = { resume_match: m.resume_match, apply_priority: m.apply_priority || '' }
            }
            setMatchMap(map)
          })
          .catch(() => setMatchMap({}))
      } else if (tab === 'resume') {
        setMatchMap({})
      }
    } catch (e: unknown) {
      if (!cached) setError(e instanceof Error ? e.message : 'Failed to load jobs')
    } finally {
      setLoading(false)
    }
  }, [tab, filters, page, resumeSort, fetchJobs]) // eslint-disable-line react-hooks/exhaustive-deps

  // Clears the cache and refetches — use after any mutation that changes data.
  const reload = useCallback(() => {
    jobsCache.current.clear()
    loadJobs(); loadAnalytics()
  }, [loadJobs, loadAnalytics])

  // Jobs refetch on tab / filter / page / sort change. Analytics is GLOBAL
  // (independent of tab) so it loads once on mount + after mutations — not on
  // every tab click, which removes a round-trip from each switch.
  useEffect(() => { loadJobs() }, [tab, filters, page, resumeSort]) // eslint-disable-line react-hooks/exhaustive-deps
  useEffect(() => { loadAnalytics() }, []) // eslint-disable-line react-hooks/exhaustive-deps

  // Lock body scroll while a mobile drawer or full-screen sheet is open.
  const sheetOpen = isMobile && selectedJob !== null
  useEffect(() => {
    const lock = filtersOpen || sheetOpen
    document.body.style.overflow = lock ? 'hidden' : ''
    return () => { document.body.style.overflow = '' }
  }, [filtersOpen, sheetOpen])

  // Leaving mobile (e.g. rotate to landscape / resize) should dismiss the drawer.
  useEffect(() => { if (!isMobile) setFiltersOpen(false) }, [isMobile])

  // Keyboard navigation (desktop power-user): j/k or ↑/↓ move through jobs,
  // Enter/o open, Esc closes the panel, s saves, a marks applied. Ignored while
  // typing in a field.
  useEffect(() => {
    if (isMobile) return
    function onKey(e: KeyboardEvent) {
      const t = e.target as HTMLElement | null
      if (t && (/^(INPUT|TEXTAREA|SELECT)$/.test(t.tagName) || t.isContentEditable)) return
      if (e.metaKey || e.ctrlKey || e.altKey) return
      const list = groupByCanonical(paginatedJobs?.items ?? []).map((g) => g.job)
      if (!list.length && e.key !== 'Escape') return
      const idx = selectedJob ? list.findIndex((j) => j.id === selectedJob.id) : -1
      if (e.key === 'j' || e.key === 'ArrowDown') {
        e.preventDefault(); setSelectedJob(list[Math.min(list.length - 1, idx + 1)] ?? list[0])
      } else if (e.key === 'k' || e.key === 'ArrowUp') {
        e.preventDefault(); setSelectedJob(idx <= 0 ? list[0] : list[idx - 1])
      } else if (e.key === 'Escape') {
        setSelectedJob(null)
      } else if (selectedJob && (e.key === 's' || e.key === 'a')) {
        e.preventDefault(); handleQuickAction(selectedJob, e.key === 's' ? 'saved' : 'applied')
      }
    }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [isMobile, paginatedJobs, selectedJob]) // eslint-disable-line react-hooks/exhaustive-deps

  function changeTab(t: Tab) { setTab(t); setPage(1); setSelectedJob(null); setFiltersOpen(false) }
  function changeFilters(f: Filters) { setFilters(f); setPage(1) }

  function handleSearch(q: string) {
    setSearch(q)
    setFilters((prev) => ({ ...prev, keyword: q || undefined }))
    setPage(1)
    if (q && NO_FETCH.includes(tab)) setTab('all')
  }

  function viewCompanyJobs(companyName: string) {
    // Reset to the canonical All-Jobs view (+ this company) so the list shown
    // matches the card's "View N Jobs" count exactly — no stale keyword/level
    // filters carried over from a previous search.
    setFilters({ usa_only: true, include_senior: true, company: companyName })
    setSearch('')
    setTab('all'); setPage(1); setSelectedJob(null)
  }

  function changePage(p: number) {
    setPage(p)
    jobListRef.current?.scrollTo({ top: 0, behavior: 'smooth' })
    window.scrollTo({ top: 0, behavior: 'smooth' })
  }

  // Scraping runs on a schedule in GitHub Actions (every 3h) and publishes a new
  // snapshot; there is no server to ask for one on demand. So "Refresh" means
  // "fetch the newest published snapshot", which is what a user actually wants
  // from this button — previously it asked a backend to start a scrape and then
  // polled for minutes, which now has nothing to talk to.
  async function handleRefresh() {
    setRefreshing(true)
    setError(null)
    try {
      clearCorpusCache()
      jobsCache.current.clear()
      const corpus = await loadCorpus()
      setCorpusStamp(corpus.generated_at)
      await Promise.all([loadJobs(), loadAnalytics()])
    } catch (e: unknown) {
      setError(e instanceof Error ? e.message : 'Could not reach the job data')
    } finally {
      setRefreshing(false)
    }
  }

  async function handleQuickAction(job: Job, action: 'saved' | 'applied' | 'ignored') {
    // Saved/applied marks are yours, not corpus data, so they live in the
    // browser keyed by the posting's fingerprint — which survives the corpus
    // being rebuilt by every scrape, unlike its row id.
    if (!job.key) return
    const newStatus = job.active_status === action ? 'active' : action
    userState.setStatus(job.key, newStatus as userState.JobStatus)
    reload()
  }

  // Resume Matches gets the filter sidebar too (consistent filtering across tabs).
  const showSidebar = !['companies', 'health', 'saved', 'applied'].includes(tab)
  const showPanel = selectedJob !== null
  const activeFilterCount = Object.entries(filters).filter(([k, v]) => {
    if (k === 'usa_only' && v === true) return false
    if (k === 'include_senior' && v === false) return false
    return v !== undefined && v !== '' && v !== false
  }).length
  const jobs = paginatedJobs?.items ?? []
  // Collapse multi-location duplicates of the same role into one canonical card.
  const grouped = groupByCanonical(jobs)

  return (
    <div style={{ minHeight: '100vh', background: 'var(--background)' }}>
      <TopNav
        activeTab={tab}
        onTabChange={changeTab}
        analytics={analytics}
        onRefresh={handleRefresh}
        refreshing={refreshing}
        search={search}
        onSearch={handleSearch}
        theme={theme}
        onToggleTheme={toggleTheme}
      />

      <main style={{ maxWidth: 1680, margin: '0 auto', padding: isMobile ? '12px 12px 40px' : '16px 20px 48px' }}>
        {error && (
          <div style={{
            background: 'var(--warning-light)', border: '1px solid var(--warning-border)',
            borderRadius: 8, padding: '10px 16px', marginBottom: 14, color: 'var(--warning)', fontSize: 13,
          }}>
            {jobs.length === 0
              ? <>Can’t reach the job service — nothing could be loaded. Retrying automatically. ({error})</>
              : <>Data sync delayed — showing the last successful results. Retrying automatically. ({error})</>}
          </div>
        )}

        {!['companies', 'health', 'resume'].includes(tab) && <SummaryCards analytics={analytics} />}

        {tab === 'companies' ? (
          <CompaniesPage onViewJobs={viewCompanyJobs} />
        ) : tab === 'health' ? (
          <div style={{ background: 'var(--surface)', border: '1px solid var(--border)', borderRadius: 10, padding: '20px 24px' }}>
            <ScrapeHealth />
          </div>
        ) : (
          <div style={{ display: 'flex', gap: isMobile ? 12 : 16, alignItems: 'flex-start', flexDirection: isMobile ? 'column' : 'row' }}>
            {tab === 'resume' ? (
              // Resume Matches: the résumé upload/version manager sits at the TOP of
              // the left column (dedicated, can't be missed), with the SAME filters
              // as every other tab stacked beneath it for consistent filtering.
              !isMobile && showSidebar ? (
                <div style={{ display: 'flex', flexDirection: 'column', gap: 16, flexShrink: 0 }}>
                  <ResumeIntel onChanged={reload} />
                  <FilterSidebar filters={filters} onChange={changeFilters} totalCount={paginatedJobs?.total_count ?? 0} hideSort />
                </div>
              ) : (
                <ResumeIntel onChanged={reload} />
              )
            ) : !isMobile && showSidebar ? (
              <FilterSidebar filters={filters} onChange={changeFilters} totalCount={paginatedJobs?.total_count ?? 0} />
            ) : null}

            <div style={{ flex: 1, minWidth: 0, width: isMobile ? '100%' : undefined }} ref={jobListRef}>
              {isMobile && showSidebar && (
                <div className="mobile-toolbar">
                  <button onClick={() => setFiltersOpen(true)}>
                    <Icon name="sliders" size={15} /> Filters
                    {activeFilterCount > 0 && (
                      <span className="pill pill-primary" style={{ fontSize: 10, fontWeight: 800, padding: '1px 7px' }}>{activeFilterCount}</span>
                    )}
                  </button>
                </div>
              )}
              {['all', 'entry-level', 'best'].includes(tab) && (
                <CategoryBar
                  value={filters.role_category}
                  stamp={corpusStamp}
                  onChange={(c) => changeFilters({ ...filters, role_category: c || undefined })}
                />
              )}
              <ResultsSummary
                tab={tab} loading={loading} analytics={analytics}
                total={paginatedJobs?.total_count ?? 0}
                page={paginatedJobs?.page ?? 1}
                totalPages={paginatedJobs?.total_pages ?? 1}
              />
              {/* Scraping is on a schedule now rather than on demand, so say how
                  fresh the data is — otherwise "Refresh" looks like it did
                  nothing when the corpus simply hasn't changed. */}
              {corpusStamp && !loading && (
                <div style={{ fontSize: 11.5, color: 'var(--text-tertiary)', margin: '-6px 0 10px' }}>
                  Job data updated {freshness(null, false, corpusStamp).label.replace('Added ', '')}
                  {' · refreshes automatically every 3 hours'}
                </div>
              )}

              {/* Active-filter chips — visible on every filter tab so the user always
                  sees (and can remove) exactly what's narrowing the list. */}
              {showSidebar && <ActiveFilters filters={filters} onChange={changeFilters} />}

              {tab === 'resume' && (
                <div style={{ display: 'flex', alignItems: 'center', gap: 8, marginBottom: 12 }}>
                  <span style={{ fontSize: 12.5, color: 'var(--text-secondary)', fontWeight: 600 }}>Sort by</span>
                  <select
                    value={resumeSort}
                    onChange={(e) => { setResumeSort(e.target.value); setPage(1) }}
                    style={{
                      background: 'var(--surface)', border: '1px solid var(--border)', borderRadius: 8,
                      padding: '6px 10px', fontSize: 12.5, color: 'var(--text-primary)', outline: 'none', cursor: 'pointer',
                    }}
                  >
                    <option value="new_grad_fit">Best New Grad Fit</option>
                    <option value="match">Best match (overall)</option>
                    <option value="resume_match">Best Resume Match</option>
                    <option value="apply_priority">Apply Priority</option>
                    <option value="newest">Newest posted</option>
                    <option value="recent">Recently added</option>
                  </select>
                </div>
              )}

              {loading ? (
                <div style={{ display: 'flex', flexDirection: 'column', gap: 8 }}>
                  {Array.from({ length: 6 }).map((_, i) => <SkeletonCard key={i} />)}
                </div>
              ) : jobs.length === 0 ? (
                <EmptyState tab={tab} query={filters.keyword} offline={!!error} />
              ) : (
                <div style={{ display: 'flex', flexDirection: 'column', gap: 8 }} className="animate-in">
                  {grouped.map((g) => (
                    <JobCard
                      key={g.job.id}
                      job={g.job}
                      extraLocations={g.extraLocations}
                      resumeMatch={tab === 'resume' ? g.job.resume_match : matchMap[String(g.job.id)]?.resume_match}
                      ringMetric={tab === 'resume' ? resumeSort : undefined}
                      selected={selectedJob?.id === g.job.id}
                      onClick={() => setSelectedJob(selectedJob?.id === g.job.id ? null : g.job)}
                      onQuickAction={(action) => handleQuickAction(g.job, action)}
                    />
                  ))}
                </div>
              )}

              {paginatedJobs && paginatedJobs.total_pages > 1 && (
                <Pagination
                  page={paginatedJobs.page}
                  totalPages={paginatedJobs.total_pages}
                  totalCount={paginatedJobs.total_count}
                  limit={PAGE_SIZE}
                  hasNext={paginatedJobs.has_next}
                  hasPrev={paginatedJobs.has_prev}
                  onPageChange={changePage}
                />
              )}
            </div>

            {!isMobile && showPanel && (
              <JobDetailsPanel job={selectedJob} onClose={() => setSelectedJob(null)} onUpdate={reload} onSelectJob={setSelectedJob} />
            )}
          </div>
        )}
        {/* Footer — legal + data controls (required for app-store publishing) */}
        <footer style={{ marginTop: 32, paddingTop: 16, borderTop: '1px solid var(--border)', display: 'flex', flexWrap: 'wrap', gap: 14, alignItems: 'center', justifyContent: 'center', fontSize: 12, color: 'var(--text-tertiary)' }}>
          <span>© {new Date().getFullYear()} Ashborne Volt</span>
          <span aria-hidden>·</span>
          <button onClick={() => setLegal('privacy')} style={footerLinkStyle}>Privacy</button>
          <button onClick={() => setLegal('terms')} style={footerLinkStyle}>Terms</button>
          <button onClick={() => setLegal('data')} style={footerLinkStyle}>Delete my data</button>
        </footer>
      </main>

      {legal && <LegalModal tab={legal} onChangeTab={setLegal} onClose={() => setLegal(null)} />}

      {/* ── Mobile: filters drawer ── */}
      {isMobile && filtersOpen && (
        <>
          <div className="mobile-backdrop" onClick={() => setFiltersOpen(false)} />
          <div className="mobile-drawer">
            <FilterSidebar
              mobile
              onClose={() => setFiltersOpen(false)}
              filters={filters}
              onChange={changeFilters}
              totalCount={paginatedJobs?.total_count ?? 0}
            />
          </div>
        </>
      )}

      {/* ── Mobile: job details full-screen sheet ── */}
      {isMobile && showPanel && (
        <div className="mobile-sheet">
          <JobDetailsPanel
            mobile
            job={selectedJob}
            onClose={() => setSelectedJob(null)}
            onUpdate={reload}
            onSelectJob={setSelectedJob}
          />
        </div>
      )}
    </div>
  )
}
