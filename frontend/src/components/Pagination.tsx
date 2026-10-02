interface Props {
  page: number
  totalPages: number
  totalCount: number
  limit: number
  hasNext: boolean
  hasPrev: boolean
  onPageChange: (p: number) => void
}

export function Pagination({ page, totalPages, totalCount, limit, hasNext, hasPrev, onPageChange }: Props) {
  if (totalPages <= 1) return null

  const start = (page - 1) * limit + 1
  const end = Math.min(page * limit, totalCount)

  const btnStyle = (active: boolean, disabled: boolean): React.CSSProperties => ({
    background: active ? 'var(--primary)' : 'var(--surface)',
    color: active ? 'var(--on-primary)' : disabled ? 'var(--text-faint)' : 'var(--text)',
    border: `1px solid ${active ? 'var(--primary)' : 'var(--border)'}`,
    borderRadius: 6, padding: '5px 10px', fontSize: 13,
    cursor: disabled ? 'not-allowed' : 'pointer',
    fontWeight: active ? 600 : 400, minWidth: 36,
    opacity: disabled ? 0.5 : 1,
  })

  // Show a window of page numbers around current page
  const pageNums: (number | '...')[] = []
  if (totalPages <= 7) {
    for (let i = 1; i <= totalPages; i++) pageNums.push(i)
  } else {
    pageNums.push(1)
    if (page > 3) pageNums.push('...')
    for (let i = Math.max(2, page - 1); i <= Math.min(totalPages - 1, page + 1); i++) {
      pageNums.push(i)
    }
    if (page < totalPages - 2) pageNums.push('...')
    pageNums.push(totalPages)
  }

  return (
    <div style={{
      display: 'flex', alignItems: 'center', justifyContent: 'space-between',
      padding: '14px 0', marginTop: 12,
    }}>
      <div style={{ fontSize: 13, color: 'var(--text-muted)' }}>
        Showing <strong style={{ color: 'var(--text)' }}>{start}–{end}</strong> of{' '}
        <strong style={{ color: 'var(--text)' }}>{totalCount}</strong> jobs
      </div>

      <div style={{ display: 'flex', gap: 4, alignItems: 'center' }}>
        <button
          disabled={!hasPrev}
          onClick={() => onPageChange(page - 1)}
          style={btnStyle(false, !hasPrev)}
        >
          ← Prev
        </button>

        {pageNums.map((n, i) =>
          n === '...'
            ? <span key={`ellipsis-${i}`} style={{ padding: '0 6px', color: 'var(--text-faint)', fontSize: 13 }}>…</span>
            : (
              <button
                key={n}
                onClick={() => onPageChange(n)}
                style={btnStyle(n === page, false)}
              >
                {n}
              </button>
            )
        )}

        <button
          disabled={!hasNext}
          onClick={() => onPageChange(page + 1)}
          style={btnStyle(false, !hasNext)}
        >
          Next →
        </button>
      </div>
    </div>
  )
}
