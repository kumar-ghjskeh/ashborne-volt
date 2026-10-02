/**
 * Resume Studio, watchlists and prompt building — the last pieces that still
 * needed a database.
 *
 * Your master LaTeX, tailoring instructions and saved searches are your data
 * and are a few KB, so they live in this browser alongside the résumé profile.
 * The prompt builders stay on the server because they are just text assembly
 * that already exists there — but they no longer look anything up: the client
 * supplies the job and the settings, so they are pure functions.
 */
import axios from 'axios'
import type { Filters, Job } from './types'
import { getStoredResume } from './resume'
import { loadDetail } from './corpus'

const BASE = import.meta.env.VITE_API_BASE
  ? `${(import.meta.env.VITE_API_BASE as string).replace(/\/$/, '')}`
  : '/api'

const MASTER_KEY = 'volt-master-latex-v1'
const INSTRUCTIONS_KEY = 'volt-tailor-instructions-v1'
const WATCHLIST_KEY = 'volt-watchlists-v1'

function read(key: string, fallback = ''): string {
  try {
    return localStorage.getItem(key) ?? fallback
  } catch {
    return fallback
  }
}

function write(key: string, value: string): void {
  try {
    localStorage.setItem(key, value)
  } catch {
    /* private window / storage blocked */
  }
}

// ── Resume Studio settings ────────────────────────────────────────────────────

export function getMasterResume(): { master_latex: string; instructions: string } {
  return { master_latex: read(MASTER_KEY), instructions: read(INSTRUCTIONS_KEY) }
}

export function saveMasterResume(masterLatex: string, instructions: string): void {
  write(MASTER_KEY, masterLatex)
  write(INSTRUCTIONS_KEY, instructions)
}

/** Skills this posting asks for that the résumé doesn't mention. */
async function missingKeywordsFor(job: Job): Promise<string[]> {
  const stored = getStoredResume()
  const have = new Set((stored?.profile.all_skills || []).map((s) => s.toLowerCase()))
  return String(job.job_skills || '')
    .split(',')
    .map((s) => s.trim())
    .filter((s) => s && !have.has(s.toLowerCase()))
    .slice(0, 12)
}

async function descriptionFor(job: Job): Promise<string> {
  const body = await loadDetail(job.id).catch(() => '')
  return body || job.cleaned_description || job.description_snippet || ''
}

export async function buildTailorPrompt(
  job: Job,
  opts: { master_latex?: string; instructions?: string } = {},
): Promise<{ prompt: string; missing_keywords: string[]; job_title: string; company: string }> {
  const saved = getMasterResume()
  const { data } = await axios.post(`${BASE}/resume-studio/tailor-prompt`, {
    job_title: job.job_title,
    company: job.company,
    description: await descriptionFor(job),
    master_latex: opts.master_latex ?? saved.master_latex,
    instructions: opts.instructions ?? saved.instructions,
    missing_keywords: await missingKeywordsFor(job),
  })
  return data
}

/** Tailored LaTeX via Gemini. The server stores nothing and looks nothing up:
 *  jobs live in static files, so the browser sends the posting itself. */
export async function generateTailored(
  job: Job,
  opts: { master_latex?: string; instructions?: string } = {},
): Promise<{ latex: string; missing_keywords: string[] }> {
  const saved = getMasterResume()
  const { data } = await axios.post(`${BASE}/resume-studio/tailor/generate`, {
    job_title: job.job_title,
    company: job.company,
    description: await descriptionFor(job),
    master_latex: opts.master_latex ?? saved.master_latex,
    instructions: opts.instructions ?? saved.instructions,
    missing_keywords: await missingKeywordsFor(job),
  })
  return data
}

/** Company-specific interview prep via Gemini, from the posting text. */
export async function generateInterviewPrep(job: Job): Promise<{ text: string }> {
  const { data } = await axios.post(`${BASE}/resume-studio/interview/generate`, {
    job_title: job.job_title,
    company: job.company,
    description: await descriptionFor(job),
    role_category: job.role_category || '',
  })
  return data
}

export async function buildInterviewPrompt(job: Job): Promise<{ prompt: string }> {
  const { data } = await axios.post(`${BASE}/resume-studio/interview-prompt`, {
    job_title: job.job_title,
    company: job.company,
    description: await descriptionFor(job),
    role_category: job.role_category || '',
  })
  return data
}

// ── Saved searches ────────────────────────────────────────────────────────────
// A watchlist is a named filter set plus the result count when you last looked,
// which is how "N new" is worked out. All of that is yours and tiny, so it lives
// here rather than requiring a server.

export interface StoredWatchlist {
  id: number
  name: string
  filters: Filters
  alert_enabled: boolean
  last_checked_at: string
  /** Result count at the last check — the baseline "N new" is measured against. */
  last_count: number
}

export function getWatchlists(): StoredWatchlist[] {
  try {
    const raw = read(WATCHLIST_KEY, '[]')
    const parsed = JSON.parse(raw)
    return Array.isArray(parsed) ? (parsed as StoredWatchlist[]) : []
  } catch {
    return []
  }
}

function saveWatchlists(list: StoredWatchlist[]): void {
  write(WATCHLIST_KEY, JSON.stringify(list))
}

export function createWatchlist(name: string, filters: Filters, currentCount = 0): StoredWatchlist {
  const list = getWatchlists()
  const item: StoredWatchlist = {
    id: Date.now(),
    name,
    filters,
    alert_enabled: false,
    last_checked_at: new Date().toISOString(),
    last_count: currentCount,
  }
  saveWatchlists([item, ...list])
  return item
}

export function deleteWatchlist(id: number): void {
  saveWatchlists(getWatchlists().filter((w) => w.id !== id))
}

/** Mark a watchlist as seen at its current result count. */
export function checkWatchlist(id: number, currentCount: number): void {
  saveWatchlists(
    getWatchlists().map((w) =>
      w.id === id ? { ...w, last_checked_at: new Date().toISOString(), last_count: currentCount } : w,
    ),
  )
}

/** Clears everything this browser holds for you. */
export function clearStudioData(): void {
  for (const k of [MASTER_KEY, INSTRUCTIONS_KEY, WATCHLIST_KEY]) {
    try {
      localStorage.removeItem(k)
    } catch {
      /* ignore */
    }
  }
}
