const ET_OPTS: Intl.DateTimeFormatOptions = { timeZone: 'America/New_York' }

export function formatET(d: string | null | undefined): string {
  if (!d) return '—'
  const date = new Date(d)
  if (isNaN(date.getTime())) return '—'
  return date.toLocaleString('en-US', {
    ...ET_OPTS, month: 'short', day: 'numeric', year: 'numeric',
  }) + ' ET'
}

export function formatETCompact(d: string | null | undefined): string {
  if (!d) return '—'
  const date = new Date(d)
  if (isNaN(date.getTime())) return '—'
  return date.toLocaleString('en-US', {
    ...ET_OPTS, month: 'short', day: 'numeric',
  }) + ' ET'
}

export function formatETFull(d: string | null | undefined): string {
  if (!d) return '—'
  const date = new Date(d)
  if (isNaN(date.getTime())) return '—'
  return date.toLocaleString('en-US', {
    ...ET_OPTS, month: 'short', day: 'numeric', year: 'numeric',
    hour: '2-digit', minute: '2-digit',
  }) + ' ET'
}


/**
 * Only http(s) links leave the app. Apply and careers URLs come from scraped
 * third-party pages, so a `javascript:` or `data:` URL must never reach an href.
 */
export function safeUrl(url: string | null | undefined): string {
  const u = String(url ?? '').trim()
  return /^https?:\/\//i.test(u) ? u : '#'
}
