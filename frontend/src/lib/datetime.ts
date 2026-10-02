// Centralised date parsing/formatting. The backend sends UTC timestamps WITHOUT
// a timezone marker (e.g. "2026-06-11T23:11:00"), which browsers wrongly treat as
// local time. We normalise here so every displayed time is correct.

/** Parse an API date string into a Date, interpreting it correctly:
 *  - date-only ("2026-06-10")        → local midnight (avoids an off-by-one day)
 *  - datetime without tz             → UTC (append Z)
 *  - datetime with tz                → as-is
 */
export function parseApiDate(s: string | null | undefined): Date | null {
  if (!s) return null
  if (/^\d{4}-\d{2}-\d{2}$/.test(s)) {
    const [y, m, d] = s.split('-').map(Number)
    return new Date(y, m - 1, d)
  }
  if (/\d{2}:\d{2}/.test(s) && !/[zZ]$|[+-]\d{2}:?\d{2}$/.test(s)) {
    return new Date(s + 'Z')
  }
  return new Date(s)
}

/** Short date, e.g. "Jun 10". */
export function fmtDate(s: string | null | undefined): string {
  const d = parseApiDate(s)
  return d ? d.toLocaleDateString('en-US', { month: 'short', day: 'numeric' }) : '—'
}

/** Date + year, e.g. "Jun 10, 2026". */
export function fmtDateLong(s: string | null | undefined): string {
  const d = parseApiDate(s)
  return d ? d.toLocaleDateString('en-US', { month: 'short', day: 'numeric', year: 'numeric' }) : '—'
}

export interface Freshness {
  label: string      // e.g. "Posted 3d ago" / "Added 5d ago"
  isNew: boolean     // posted/added within 3 days
  exact: boolean     // true = real posted date from the source; false = inferred from first-seen
  days: number
}

/** Honest relative freshness. Uses the real posted date when the source provided
 *  one ("Posted 3d ago"); otherwise falls back to when WE first saw it
 *  ("Added 5d ago") rather than pretending we know the post date. */
export function freshness(
  postedDate: string | null | undefined,
  postedKnown: boolean | undefined,
  firstSeen: string | null | undefined,
): Freshness {
  const exact = !!(postedKnown && postedDate)
  const src = parseApiDate(exact ? postedDate : firstSeen)
  if (!src) return { label: '', isNew: false, exact, days: Infinity }
  const days = Math.max(0, Math.floor((Date.now() - src.getTime()) / 86_400_000))
  const verb = exact ? 'Posted' : 'Added'
  let rel: string
  if (days <= 0) rel = 'today'
  else if (days === 1) rel = 'yesterday'
  else if (days < 7) rel = `${days}d ago`
  else if (days < 30) rel = `${Math.floor(days / 7)}w ago`
  else if (days < 365) rel = `${Math.floor(days / 30)}mo ago`
  else rel = `${Math.floor(days / 365)}y ago`
  return { label: `${verb} ${rel}`, isNew: days <= 3, exact, days }
}

/** Date + time in a chosen tz ("local" = browser zone), e.g. "Jun 11, 07:21 PM". */
export function fmtDateTime(s: string | null | undefined, tz = 'local'): string {
  const d = parseApiDate(s)
  if (!d) return '—'
  const opts: Intl.DateTimeFormatOptions = { month: 'short', day: 'numeric', hour: '2-digit', minute: '2-digit' }
  if (tz !== 'local') opts.timeZone = tz
  return d.toLocaleString('en-US', opts)
}
