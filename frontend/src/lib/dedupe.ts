import type { Job } from './types'

export interface JobGroup {
  job: Job              // canonical (highest-scoring) posting for the role
  extraLocations: string[]  // additional USA locations of the same role
}

/**
 * Collapse postings that are the same role at one company but differ only by
 * location into a single canonical card, so the list isn't padded with
 * duplicates (one utility requisition posted at four substations).
 * Grouping key = dup_group from the scraper: company + normalised title + a
 * signature of the description, so two different teams that share a generic
 * title ("Electrical Engineer II") stay separate cards. Falls back to
 * company + title for rows without one.
 */
export function groupByCanonical(jobs: Job[]): JobGroup[] {
  const groups = new Map<string, Job[]>()
  const order: string[] = []

  for (const j of jobs) {
    const title = (j.normalized_title || j.job_title || '').toLowerCase().trim()
    const key = j.dup_group || `${j.company.toLowerCase().trim()}|${title}`
    if (!groups.has(key)) { groups.set(key, []); order.push(key) }
    groups.get(key)!.push(j)
  }

  return order.map((key) => {
    const items = groups.get(key)!
    // The representative MUST be the first-appearing member. The server returns
    // the list already sorted by the active criterion (resume_match, new-grad
    // fit, …), so the first member of a group is its best-ranked instance — and
    // the group is positioned at exactly that member's rank. Picking any other
    // member (e.g. highest match_score) would display a value that doesn't match
    // the card's position, making an 80% match appear above an 86% one.
    const primary = items[0]
    const locations = Array.from(
      new Set(items.map((i) => i.location).filter((l): l is string => !!l && l.trim().length > 0))
    )
    const extraLocations = locations.filter((l) => l !== primary.location)
    return { job: primary, extraLocations }
  })
}
