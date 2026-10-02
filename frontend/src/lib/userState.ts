/**
 * Your own data — saved/applied marks, notes, follow-ups — kept in the browser.
 *
 * The job corpus is public information rebuilt by every scrape, so it lives in a
 * static file. This is the part that is genuinely yours, and it is a few KB, so
 * it lives in localStorage rather than requiring a database the app would
 * otherwise not need at all.
 *
 * Marks are keyed by the posting's content FINGERPRINT, never its row id. Ids
 * are reassigned whenever the corpus is rebuilt from scratch; the fingerprint is
 * derived from company + title + location + source id, so a job you saved stays
 * saved across rebuilds. That property is the whole reason this design is safe.
 *
 * Everything is wrapped in try/catch: private windows, cleared site data and
 * storage-blocking settings all make localStorage throw rather than return null,
 * and losing your marks must never take the app down with it.
 */

export type JobStatus = 'saved' | 'applied' | 'ignored' | 'active'

export interface JobMark {
  status: JobStatus
  notes?: string
  saved_at?: string | null
  applied_at?: string | null
  ignored_at?: string | null
  follow_up_date?: string
  confirmation_id?: string
  recruiter_contact?: string
  resume_version_used?: string
}

export interface UserState {
  version: 1
  marks: Record<string, JobMark>
}

const STORAGE_KEY = 'volt-user-state-v1'
const EMPTY: UserState = { version: 1, marks: {} }

let _cache: UserState | null = null
const listeners = new Set<() => void>()

function read(): UserState {
  if (_cache) return _cache
  try {
    const raw = localStorage.getItem(STORAGE_KEY)
    const parsed = raw ? (JSON.parse(raw) as UserState) : null
    _cache = parsed && parsed.marks ? { version: 1, marks: parsed.marks } : { ...EMPTY }
  } catch {
    _cache = { ...EMPTY }
  }
  return _cache
}

function write(next: UserState): void {
  _cache = next
  try {
    localStorage.setItem(STORAGE_KEY, JSON.stringify(next))
  } catch {
    /* storage full or blocked — keep the in-memory copy so the session still works */
  }
  listeners.forEach((fn) => {
    try {
      fn()
    } catch {
      /* a bad listener must not stop the others */
    }
  })
}

/** Subscribe to changes; returns an unsubscribe function. */
export function subscribe(fn: () => void): () => void {
  listeners.add(fn)
  return () => listeners.delete(fn)
}

export function getMark(key: string): JobMark | undefined {
  return read().marks[key]
}

export function allMarks(): Record<string, JobMark> {
  return read().marks
}

/** Set (or clear) a job's status. Passing 'active' removes the mark entirely. */
export function setStatus(key: string, status: JobStatus): void {
  const state = read()
  const marks = { ...state.marks }
  if (status === 'active') {
    delete marks[key]
  } else {
    const now = new Date().toISOString()
    const prev = marks[key] || ({ status } as JobMark)
    marks[key] = {
      ...prev,
      status,
      saved_at: status === 'saved' ? now : prev.saved_at ?? null,
      applied_at: status === 'applied' ? now : prev.applied_at ?? null,
      ignored_at: status === 'ignored' ? now : prev.ignored_at ?? null,
    }
  }
  write({ version: 1, marks })
}

/** Merge arbitrary fields (notes, follow-up date, …) into a job's mark. */
export function patchMark(key: string, patch: Partial<JobMark>): void {
  const state = read()
  const prev = state.marks[key] || ({ status: 'active' } as JobMark)
  write({ version: 1, marks: { ...state.marks, [key]: { ...prev, ...patch } } })
}

export function countByStatus(status: JobStatus): number {
  const marks = read().marks
  return Object.keys(marks).reduce((n, k) => (marks[k].status === status ? n + 1 : n), 0)
}

/** Everything the user owns, as a portable file. */
export function exportState(): string {
  return JSON.stringify({ ...read(), exported_at: new Date().toISOString() }, null, 2)
}

/**
 * Merge an exported file back in. Merge rather than replace, so importing on a
 * second device adds to what is already there instead of wiping it.
 */
export function importState(json: string): { imported: number } {
  const incoming = JSON.parse(json) as Partial<UserState>
  if (!incoming || typeof incoming !== 'object' || !incoming.marks) {
    throw new Error('Not a valid Ashborne Volt backup file')
  }
  const state = read()
  const merged = { ...state.marks }
  let imported = 0
  for (const [key, mark] of Object.entries(incoming.marks)) {
    if (!mark || typeof mark !== 'object') continue
    merged[key] = { ...merged[key], ...mark }
    imported += 1
  }
  write({ version: 1, marks: merged })
  return { imported }
}

export function clearState(): void {
  write({ ...EMPTY, marks: {} })
}

/** Overlay a job with the user's own fields, so the UI reads one shape. */
export function applyMark<T extends { key?: string; id: number }>(job: T): T {
  const key = job.key
  const mark = key ? read().marks[key] : undefined
  if (!mark) return job
  return {
    ...job,
    active_status: mark.status,
    application_status: mark.status === 'applied' ? 'Applied' : mark.status === 'saved' ? 'Saved' : '',
    notes: mark.notes ?? '',
    saved_at: mark.saved_at ?? null,
    applied_at: mark.applied_at ?? null,
    ignored_at: mark.ignored_at ?? null,
    follow_up_date: mark.follow_up_date ?? '',
    confirmation_id: mark.confirmation_id ?? '',
    recruiter_contact: mark.recruiter_contact ?? '',
    resume_version_used: mark.resume_version_used ?? '',
  }
}

