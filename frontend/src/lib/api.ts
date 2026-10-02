import axios from 'axios'
import type { AnalyticsSummary, Company, Filters, Job, JobFacets, PaginatedResponse, ScrapeRun } from './types'

// Local dev → Vite proxies '/api' to http://localhost:8000.
// Production → set VITE_API_BASE to your Render backend URL in Vercel.
const BASE = import.meta.env.VITE_API_BASE
  ? `${(import.meta.env.VITE_API_BASE as string).replace(/\/$/, '')}`
  : '/api'

function clean(params: Record<string, unknown>) {
  Object.keys(params).forEach((k) => {
    if (params[k] === undefined || params[k] === '' || params[k] === null) delete params[k]
  })
  return params
}

export const api = {
  async getJobs(filters: Filters = {}, page = 1, limit = 25): Promise<PaginatedResponse<Job>> {
    const params = clean({ page, limit, ...filters } as Record<string, unknown>)
    const { data } = await axios.get(`${BASE}/jobs`, { params })
    return data
  },

  async getEntryLevelJobs(filters: Filters = {}, page = 1, limit = 25): Promise<PaginatedResponse<Job>> {
    const params = clean({ page, limit, ...filters } as Record<string, unknown>)
    const { data } = await axios.get(`${BASE}/jobs/entry-level`, { params })
    return data
  },

  async getBestJobs(filters: Filters = {}, page = 1, limit = 25): Promise<PaginatedResponse<Job>> {
    const params = clean({ page, limit, min_score: 65, ...filters } as Record<string, unknown>)
    const { data } = await axios.get(`${BASE}/jobs/best`, { params })
    return data
  },

  async getSavedJobs(page = 1, limit = 25): Promise<PaginatedResponse<Job>> {
    const { data } = await axios.get(`${BASE}/jobs/saved`, { params: { page, limit } })
    return data
  },

  async getAppliedJobs(page = 1, limit = 25): Promise<PaginatedResponse<Job>> {
    const { data } = await axios.get(`${BASE}/jobs/applied`, { params: { page, limit } })
    return data
  },

  async updateJobStatus(
    id: number,
    update: {
      active_status?: string; application_status?: string; notes?: string
      resume_version_used?: string; follow_up_date?: string
      confirmation_id?: string; recruiter_contact?: string
    }
  ): Promise<void> {
    await axios.patch(`${BASE}/jobs/${id}/status`, update)
  },

  // ── Watchlists (Phase 4) ──
  async getWatchlists(): Promise<import('./types').Watchlist[]> {
    const { data } = await axios.get(`${BASE}/watchlists`)
    return data
  },
  async createWatchlist(name: string, filters: Record<string, unknown>): Promise<void> {
    await axios.post(`${BASE}/watchlists`, { name, filters })
  },
  async deleteWatchlist(id: number): Promise<void> {
    await axios.delete(`${BASE}/watchlists/${id}`)
  },
  async checkWatchlist(id: number): Promise<void> {
    await axios.post(`${BASE}/watchlists/${id}/check`)
  },

  // ── Web Push alerts ──
  async getPushPublicKey(): Promise<{ key: string; enabled: boolean }> {
    const { data } = await axios.get(`${BASE}/push/public-key`)
    return data
  },
  async subscribePush(sub: PushSubscriptionJSON): Promise<void> {
    await axios.post(`${BASE}/push/subscribe`, { endpoint: sub.endpoint, keys: sub.keys })
  },

  /** Other open reqs for the same role at the same company — how a grouped
   *  card's "+N locations" expands. Grouping is presentation only, so every
   *  sibling stays individually reachable and applicable. */
  async getJobLocations(id: number): Promise<{ id: number; location: string; state: string; apply_url: string; remote_status: string }[]> {
    const { data } = await axios.get(`${BASE}/jobs/${id}/locations`)
    return data.siblings || []
  },

  async getJob(id: number): Promise<Job> {
    const { data } = await axios.get(`${BASE}/jobs/${id}`)
    return data
  },

  async getSimilarJobs(id: number, limit = 6): Promise<Job[]> {
    const { data } = await axios.get(`${BASE}/jobs/${id}/similar`, { params: { limit } })
    return data
  },

  async getCompanies(): Promise<Company[]> {
    const { data } = await axios.get(`${BASE}/companies`)
    return data
  },

  applicationsCsvUrl(): string {
    return `${BASE}/export/applications.csv`
  },

  async getScrapeRuns(): Promise<ScrapeRun[]> {
    const { data } = await axios.get(`${BASE}/scrape-runs`)
    return data
  },

  async getPipelineHealth(): Promise<import('./types').PipelineHealth | null> {
    const { data } = await axios.get(`${BASE}/scrape-health`)
    return data.pipeline ?? null
  },

  async triggerScrape(): Promise<void> {
    await axios.post(`${BASE}/scrape/run-now`)
  },

  async getAnalytics(): Promise<AnalyticsSummary> {
    const { data } = await axios.get(`${BASE}/analytics/summary`)
    return data
  },

  async getScrapeHealth() {
    const { data } = await axios.get(`${BASE}/scrape-health`)
    return data
  },

  async getScrapeErrors() {
    const { data } = await axios.get(`${BASE}/scrape-errors`)
    return data
  },

  async getFacets(usaOnly = true, includeSoftware = false): Promise<JobFacets> {
    const { data } = await axios.get(`${BASE}/jobs/facets`, {
      params: { usa_only: usaOnly, include_software: includeSoftware },
    })
    return data
  },

  async getSearchSuggestions(q: string, signal?: AbortSignal): Promise<import('./types').SearchSuggestion[]> {
    if (!q || q.trim().length < 2) return []
    const { data } = await axios.get(`${BASE}/jobs/search-suggestions`, { params: { q }, signal })
    return data.suggestions || []
  },

  // ── Resume intelligence (Phase 3 · multi-resume Phase 5) ──
  async uploadResume(file: File, label = ''): Promise<{ ok: boolean; id: number; profile: import('./types').ResumeProfile; filename: string; label: string }> {
    const fd = new FormData()
    fd.append('file', file)
    if (label) fd.append('label', label)
    const { data } = await axios.post(`${BASE}/resume/upload`, fd, {
      headers: { 'Content-Type': 'multipart/form-data' },
    })
    return data
  },

  async getResume(): Promise<{ profile: import('./types').ResumeProfile | null; filename?: string; id?: number; label?: string }> {
    const { data } = await axios.get(`${BASE}/resume`)
    return data
  },

  async getResumes(): Promise<import('./types').ResumeVersion[]> {
    const { data } = await axios.get(`${BASE}/resumes`)
    return data
  },

  async activateResume(id: number): Promise<void> {
    await axios.post(`${BASE}/resume/${id}/activate`)
  },

  async deleteResumeOne(id: number): Promise<void> {
    await axios.delete(`${BASE}/resume/${id}`)
  },

  async deleteResume(): Promise<void> {
    await axios.delete(`${BASE}/resume`)
  },

  async deleteAllMyData(): Promise<{ ok: boolean; deleted: Record<string, number> }> {
    const { data } = await axios.delete(`${BASE}/account/data`)
    return data
  },

  async getResumeMatches(page = 1, limit = 50, includeSenior = false, resumeId?: number, sort = 'match', filters: Filters = {}): Promise<PaginatedResponse<Job> & { no_resume?: boolean }> {
    // Forward the SAME active filters as the other tabs so Resume Matches respects
    // them (the backend routes them through the shared query builder). The tab's own
    // include_senior + sort take precedence over any in `filters`.
    const { data } = await axios.get(`${BASE}/jobs/resume-matches`, {
      params: clean({ ...filters, page, limit, include_senior: includeSenior, resume_id: resumeId, sort }),
    })
    return data
  },

  async getJobMatch(id: number, resumeId?: number): Promise<import('./types').JobMatch> {
    const { data } = await axios.get(`${BASE}/jobs/${id}/match`, { params: clean({ resume_id: resumeId }) })
    return data
  },

  async getMatchBatch(ids: number[]): Promise<Record<string, { resume_match: number; apply_priority: string }>> {
    if (!ids.length) return {}
    const { data } = await axios.post(`${BASE}/jobs/match-batch`, { ids })
    return data.matches || {}
  },

  async getSkillGaps(): Promise<{ gaps: import('./types').SkillGap[]; high_match_jobs: number; no_resume?: boolean }> {
    const { data } = await axios.get(`${BASE}/resume/skill-gaps`)
    return data
  },

  // ── Résumé Studio (per-job tailoring) ──
  async getMasterResume(): Promise<{ master_latex: string; instructions: string; gemini_enabled: boolean }> {
    const { data } = await axios.get(`${BASE}/resume-studio/master`)
    return data
  },
  async saveMasterResume(master_latex: string, instructions: string): Promise<void> {
    await axios.put(`${BASE}/resume-studio/master`, { master_latex, instructions })
  },
  async getTailorPrompt(jobId: number, body: { master_latex?: string; instructions?: string }): Promise<{ prompt: string; missing_keywords: string[]; job_title: string; company: string }> {
    const { data } = await axios.post(`${BASE}/jobs/${jobId}/tailor-prompt`, body)
    return data
  },
  async generateTailored(jobId: number, body: { master_latex?: string; instructions?: string }): Promise<{ latex: string; missing_keywords: string[] }> {
    const { data } = await axios.post(`${BASE}/jobs/${jobId}/tailor/generate`, body)
    return data
  },
  async compileResumePdf(latex: string): Promise<Blob> {
    const { data } = await axios.post(`${BASE}/resume-studio/compile-pdf`, { latex }, { responseType: 'blob' })
    return data
  },
  async getInterviewPrompt(jobId: number): Promise<{ prompt: string }> {
    const { data } = await axios.post(`${BASE}/jobs/${jobId}/interview-prep-prompt`, {})
    return data
  },
  async generateInterviewPrep(jobId: number): Promise<{ text: string }> {
    const { data } = await axios.post(`${BASE}/jobs/${jobId}/interview-prep/generate`, {})
    return data
  },
}
