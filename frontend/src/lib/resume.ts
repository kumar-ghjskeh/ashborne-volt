/**
 * Résumé handling with no database behind it.
 *
 * Your parsed résumé profile lives in this browser. Scoring stays in Python —
 * it is ~500 lines of tuned logic and reimplementing it here would risk silent
 * drift on the feature you rely on most — but the service is now a pure
 * function: it is handed a profile and some postings and returns scores,
 * storing nothing.
 *
 * Results are cached against the corpus version and the profile, so switching
 * tabs, paging or re-sorting costs nothing. One request per scrape cycle.
 */
import axios from 'axios'
import type { Job, ResumeProfile } from './types'
import { loadCorpus, loadDetail } from './corpus'

const BASE = import.meta.env.VITE_API_BASE
  ? `${(import.meta.env.VITE_API_BASE as string).replace(/\/$/, '')}`
  : '/api'

const PROFILE_KEY = 'volt-resume-v1'

export interface StoredResume {
  profile: ResumeProfile
  filename: string
  label: string
  uploaded_at: string
}

export interface MatchScores {
  id: number
  resume_match: number
  new_grad_fit: number
  experienced_fit: number
  overall_recommendation?: string
  match_breakdown?: Record<string, number>
  defensibility?: number
  apply_priority?: string
  apply_priority_score?: number
  matched_skills?: string[]
  missing_skills?: string[]
}

export function getStoredResume(): StoredResume | null {
  try {
    const raw = localStorage.getItem(PROFILE_KEY)
    return raw ? (JSON.parse(raw) as StoredResume) : null
  } catch {
    return null
  }
}

export function storeResume(r: StoredResume | null): void {
  try {
    if (r) localStorage.setItem(PROFILE_KEY, JSON.stringify(r))
    else localStorage.removeItem(PROFILE_KEY)
  } catch {
    /* private window / storage blocked — the session still works in memory */
  }
  _matchCache = null
}

/** Parse a PDF/DOCX into a profile. The file is never stored server-side. */
export async function parseResumeFile(file: File, label = ''): Promise<StoredResume> {
  const fd = new FormData()
  fd.append('file', file)
  if (label) fd.append('label', label)
  const { data } = await axios.post(`${BASE}/resume/parse`, fd, {
    headers: { 'Content-Type': 'multipart/form-data' },
  })
  const stored: StoredResume = {
    profile: data.profile,
    filename: data.filename || file.name,
    label: data.label || file.name,
    uploaded_at: new Date().toISOString(),
  }
  storeResume(stored)
  return stored
}

// One cache entry: valid for a given corpus version + résumé.
let _matchCache: { key: string; scores: Map<number, MatchScores> } | null = null

/**
 * Scores for every browseable posting, keyed by job id.
 *
 * Full description text is sent when available so the scores match exactly what
 * the database-backed version produced — the request is ~1.5 MB, but it happens
 * once per scrape cycle rather than once per view, which is what the cache is
 * for. Returns an empty map when no résumé is loaded.
 */
export async function getMatchScores(): Promise<Map<number, MatchScores>> {
  const stored = getStoredResume()
  if (!stored) return new Map()

  const corpus = await loadCorpus()
  const cacheKey = `${corpus.generated_at}|${stored.uploaded_at}`
  if (_matchCache && _matchCache.key === cacheKey) return _matchCache.scores

  const jobs = corpus.jobs
    .filter((j) => j.is_usa && !j.is_software_only)
    .map((j) => ({
      id: j.id,
      job_title: j.job_title,
      cleaned_description: j.description_snippet || '',
      matched_keywords: j.matched_keywords || '',
      role_category: j.role_category || '',
      job_skills: j.job_skills || '',
      company: j.company,
      company_priority: j.company_priority || 'C',
      match_score: j.match_score ?? 0,
      is_candidate_friendly: !!j.is_candidate_friendly,
      eligibility_risk: j.eligibility_risk || '',
      sponsors_h1b: j.sponsors_h1b ?? null,
      experience_level: j.experience_level || '',
      is_senior: !!j.is_senior,
      new_grad_fit: j.new_grad_fit ?? 0,
      experienced_fit: j.experienced_fit ?? 0,
      first_seen_at: j.first_seen_at,
    }))

  const { data } = await axios.post(`${BASE}/resume/match`, { profile: stored.profile, jobs })
  const scores = new Map<number, MatchScores>()
  for (const m of (data.matches || []) as MatchScores[]) scores.set(m.id, m)
  _matchCache = { key: cacheKey, scores }
  return scores
}

/** Full detail scoring for one posting (why-it-matches, prep, tailoring). */
export async function getJobMatchDetail(job: Job): Promise<MatchScores | null> {
  const stored = getStoredResume()
  if (!stored) return null
  const body = await loadDetail(job.id).catch(() => '')
  const payload = {
    id: job.id,
    job_title: job.job_title,
    cleaned_description: body || job.description_snippet || '',
    matched_keywords: job.matched_keywords || '',
    role_category: job.role_category || '',
    job_skills: job.job_skills || '',
    company: job.company,
    company_priority: job.company_priority || 'C',
    match_score: job.match_score ?? 0,
    is_candidate_friendly: !!job.is_candidate_friendly,
    eligibility_risk: job.eligibility_risk || '',
    sponsors_h1b: job.sponsors_h1b ?? null,
    experience_level: job.experience_level || '',
    is_senior: !!job.is_senior,
    new_grad_fit: job.new_grad_fit ?? 0,
    experienced_fit: job.experienced_fit ?? 0,
    first_seen_at: job.first_seen_at,
  }
  const { data } = await axios.post(`${BASE}/resume/match`, {
    profile: stored.profile,
    jobs: [payload],
    full: true,
  })
  return (data.matches || [])[0] ?? null
}

/**
 * Skills the corpus asks for that the résumé doesn't mention, most common
 * first. Computed locally from the corpus — no request needed.
 */
export async function getSkillGaps(top = 12): Promise<{ skill: string; count: number }[]> {
  const stored = getStoredResume()
  if (!stored) return []
  const have = new Set((stored.profile.all_skills || []).map((s) => s.toLowerCase()))
  const corpus = await loadCorpus()
  const counts = new Map<string, number>()
  for (const j of corpus.jobs) {
    if (!j.is_usa) continue
    for (const raw of String(j.job_skills || '').split(',')) {
      const skill = raw.trim()
      if (!skill || have.has(skill.toLowerCase())) continue
      counts.set(skill, (counts.get(skill) || 0) + 1)
    }
  }
  return [...counts.entries()]
    .map(([skill, count]) => ({ skill, count }))
    .sort((a, b) => b.count - a.count)
    .slice(0, top)
}
