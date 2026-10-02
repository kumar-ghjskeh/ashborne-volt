import type { Filters } from '../lib/types'
import { Icon } from './Icon'

// LinkedIn/Indeed-style active-filter chips: every applied filter is shown as a
// removable chip, plus a Clear-all. Rendered on every filter tab so the user
// always sees exactly what's narrowing the list (the #1 cause of "filters feel
// inconsistent" was not being able to see what was active, especially after
// switching tabs).

function postedLabel(h: number): string {
  if (h < 24) return `Posted ≤ ${h}h`
  const d = Math.round(h / 24)
  return d === 1 ? 'Posted ≤ 1 day' : `Posted ≤ ${d} days`
}

const LABELS: Record<string, (v: unknown) => string> = {
  keyword: (v) => `“${v}”`,
  company: (v) => String(v),
  priority: (v) => `Tier ${v}`,
  role_category: (v) => String(v),
  remote: (v) => String(v),
  state: (v) => String(v),
  min_score: (v) => `New Grad Fit ≥ ${v}`,
  posted_within_hours: (v) => postedLabel(Number(v)),
  h1b_only: () => 'H1B sponsor-friendly',
  role_flags: (v) => String(v),
}

const SKIP = new Set([
  'usa_only', 'include_senior', 'include_software', 'include_adjacent',
  'sort_by', 'sort_order', 'view', 'status', 'new_since_hours', 'experience_level',
  'is_entry_level',
])

export function ActiveFilters({ filters, onChange }: { filters: Filters; onChange: (f: Filters) => void }) {
  const set = (patch: Partial<Filters>) => onChange({ ...filters, ...patch })
  const chips: { key: string; label: string; clear: () => void }[] = []

  for (const [k, v] of Object.entries(filters)) {
    if (v === undefined || v === '' || v === false || v === null) continue
    if (SKIP.has(k)) continue
    if (k === 'level_filter') {
      for (const lv of String(v).split(',').filter(Boolean)) {
        chips.push({
          key: `lv-${lv}`, label: lv,
          clear: () => {
            const next = String(v).split(',').filter((x) => x && x !== lv)
            set({ level_filter: next.join(',') || undefined })
          },
        })
      }
      continue
    }
    const fn = LABELS[k]
    if (!fn) continue
    chips.push({ key: k, label: fn(v), clear: () => set({ [k]: undefined } as Partial<Filters>) })
  }

  if (!chips.length) return null

  const clearAll = () =>
    onChange({
      usa_only: filters.usa_only, include_senior: filters.include_senior,
      sort_by: filters.sort_by, sort_order: filters.sort_order,
    })

  const chipStyle: React.CSSProperties = {
    display: 'inline-flex', alignItems: 'center', gap: 5,
    background: 'color-mix(in srgb, var(--primary) 12%, transparent)',
    color: 'var(--primary)', border: '1px solid color-mix(in srgb, var(--primary) 35%, transparent)',
    borderRadius: 999, padding: '3px 8px 3px 10px', fontSize: 12, fontWeight: 600,
    cursor: 'pointer',
  }

  return (
    <div style={{ display: 'flex', flexWrap: 'wrap', gap: 6, alignItems: 'center', marginBottom: 12 }}>
      <span style={{ fontSize: 12, color: 'var(--text-secondary)', fontWeight: 700 }}>Active filters:</span>
      {chips.map((c) => (
        <button key={c.key} onClick={c.clear} style={chipStyle} title={`Remove ${c.label}`}>
          {c.label} <Icon name="x" size={11} color="var(--primary)" />
        </button>
      ))}
      <button
        onClick={clearAll}
        style={{
          background: 'none', border: 'none', color: 'var(--text-secondary)',
          fontSize: 12, fontWeight: 700, cursor: 'pointer', textDecoration: 'underline',
          padding: '3px 4px',
        }}
      >
        Clear all
      </button>
    </div>
  )
}
