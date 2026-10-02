import { useEffect, useState } from 'react'
import { facetsFromCorpus } from '../lib/corpus'
import { CATEGORIES, CATEGORY_BLURBS } from '../lib/categories'

interface Props {
  value?: string
  onChange: (category: string) => void
  /** Bumped when the corpus reloads, so counts refresh. */
  stamp?: string
}

/**
 * Browse-by-category strip above the job list: the twelve EE categories with
 * live counts. Clicking one filters the list; clicking it again clears it.
 */
export function CategoryBar({ value, onChange, stamp }: Props) {
  const [counts, setCounts] = useState<Record<string, number>>({})
  const [total, setTotal] = useState(0)

  useEffect(() => {
    let cancelled = false
    facetsFromCorpus(true)
      .then((f) => {
        if (cancelled) return
        const m: Record<string, number> = {}
        for (const r of f.role_categories) m[r.value] = r.count
        setCounts(m)
        setTotal(Object.values(m).reduce((a, b) => a + b, 0))
      })
      .catch(() => {/* list still works without counts */})
    return () => { cancelled = true }
  }, [stamp])

  const chip = (label: string, active: boolean, count: number | undefined, onClick: () => void, title?: string) => (
    <button
      key={label}
      onClick={onClick}
      title={title}
      aria-pressed={active}
      style={{
        flex: '0 0 auto', display: 'inline-flex', alignItems: 'center', gap: 6,
        padding: '6px 11px', borderRadius: 999, cursor: 'pointer', whiteSpace: 'nowrap',
        fontSize: 12.5, fontWeight: active ? 700 : 600,
        border: active ? '1px solid var(--primary-mid)' : '1px solid var(--border)',
        background: active ? 'var(--primary-light)' : 'var(--surface)',
        color: active ? 'var(--primary)' : 'var(--text-secondary)',
      }}
    >
      {label}
      {count !== undefined && (
        <span style={{ fontSize: 11, fontWeight: 700, color: active ? 'var(--primary)' : 'var(--text-tertiary)' }}>
          {count}
        </span>
      )}
    </button>
  )

  return (
    <nav aria-label="Browse by category"
      style={{ display: 'flex', gap: 6, overflowX: 'auto', padding: '2px 0 10px', marginBottom: 4, scrollbarWidth: 'thin' }}>
      {chip('All EE', !value, total || undefined, () => onChange(''))}
      {CATEGORIES.map((c) =>
        chip(c, value === c, counts[c] ?? 0, () => onChange(value === c ? '' : c), CATEGORY_BLURBS[c]))}
    </nav>
  )
}
