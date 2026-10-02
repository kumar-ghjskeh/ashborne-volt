/**
 * CSV export, built in the browser.
 *
 * The rows are already here — saved/applied jobs come from the corpus overlaid
 * with your own marks — so there is no server to ask for a file, and no
 * database behind one either.
 */
import type { Job } from './types'
import { loadCorpus } from './corpus'
import { applyMark } from './userState'

const COLUMNS: [keyof Job | string, string][] = [
  ['company', 'Company'],
  ['job_title', 'Job Title'],
  ['location', 'Location'],
  ['application_status', 'Status'],
  ['saved_at', 'Saved'],
  ['applied_at', 'Applied'],
  ['follow_up_date', 'Follow Up'],
  ['confirmation_id', 'Confirmation'],
  ['recruiter_contact', 'Recruiter'],
  ['notes', 'Notes'],
  ['apply_url', 'Apply URL'],
]

/** Quote a field only when it contains a comma, quote or line break. */
function escapeField(value: unknown): string {
  const raw = value == null ? '' : String(value)
  const needsQuotes =
    raw.includes(',') || raw.includes('"') || raw.includes('\n') || raw.includes('\r')
  return needsQuotes ? `"${raw.split('"').join('""')}"` : raw
}

export function exportApplicationsCsv(jobs: Job[]): void {
  const rows = [
    COLUMNS.map(([, header]) => header).join(','),
    ...jobs.map((job) =>
      COLUMNS.map(([key]) => escapeField((job as unknown as Record<string, unknown>)[key])).join(','),
    ),
  ]
  // CRLF so Excel opens it cleanly on Windows.
  const blob = new Blob([rows.join('\r\n')], { type: 'text/csv;charset=utf-8' })
  const url = URL.createObjectURL(blob)
  const link = document.createElement('a')
  link.href = url
  link.download = `volt-applications-${new Date().toISOString().slice(0, 10)}.csv`
  link.click()
  setTimeout(() => URL.revokeObjectURL(url), 1000)
}

/**
 * Export your Saved or Applied list without needing the caller to hold the rows.
 * Reads the corpus and overlays your marks, so it works from anywhere in the UI.
 */
export async function exportMarkedJobs(which: 'saved' | 'applied'): Promise<void> {
  const corpus = await loadCorpus()
  const rows = corpus.jobs
    .map((j) => applyMark(j))
    .filter((j) => j.active_status === which)
  exportApplicationsCsv(rows as Job[])
}
