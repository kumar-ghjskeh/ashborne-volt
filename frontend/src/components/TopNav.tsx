import { useEffect, useRef, useState } from 'react'
import type { AnalyticsSummary, SearchSuggestion } from '../lib/types'
import type { Theme } from '../lib/theme'
import { useIsMobile } from '../lib/useIsMobile'
import { suggestionsFromCorpus } from '../lib/corpus'
import { Icon, type IconName } from './Icon'

export type Tab = 'all' | 'resume' | 'entry-level' | 'best' | 'saved' | 'applied' | 'companies' | 'health'

interface Props {
  activeTab: Tab
  onTabChange: (t: Tab) => void
  analytics: AnalyticsSummary | null
  onRefresh: () => void
  refreshing: boolean
  search: string
  onSearch: (q: string) => void
  theme: Theme
  onToggleTheme: () => void
}

const TABS: { id: Tab; label: string; badge?: (a: AnalyticsSummary) => number; icon: IconName }[] = [
  { id: 'all',         label: 'All Jobs',       icon: 'list' },
  { id: 'resume',      label: 'Resume Matches', icon: 'target' },
  { id: 'entry-level', label: 'New Grad',       badge: (a) => a.entry_level_count, icon: 'graduation' },
  { id: 'saved',       label: 'Saved',          badge: (a) => a.saved_count,       icon: 'bookmark' },
  { id: 'applied',     label: 'Applied',        badge: (a) => a.applied_count,     icon: 'checkCircle' },
  { id: 'companies',   label: 'Companies',      icon: 'building' },
  { id: 'health',      label: 'Data Health',    icon: 'activity' },
]

export function TopNav({
  activeTab, onTabChange, analytics, onRefresh, refreshing, search, onSearch, theme, onToggleTheme,
}: Props) {
  const [q, setQ] = useState(search)
  const isMobile = useIsMobile()

  // ── Autocomplete ────────────────────────────────────────────────────────────
  const [sugs, setSugs] = useState<SearchSuggestion[]>([])
  const [open, setOpen] = useState(false)
  const [active, setActive] = useState(-1)   // -1 = "use what I typed"
  const boxRef = useRef<HTMLDivElement | null>(null)
  const skipNextFetch = useRef(false)        // set when we fill the box on select

  // Keep the box in sync when the query is cleared/changed from outside.
  useEffect(() => { setQ(search) }, [search])

  // Debounced fetch; the in-flight request is aborted whenever the user types
  // again, so a slow response can never overwrite a newer one.
  useEffect(() => {
    if (skipNextFetch.current) { skipNextFetch.current = false; return }
    const term = q.trim()
    if (term.length < 2) { setSugs([]); setOpen(false); return }
    const ctl = new AbortController()
    const t = setTimeout(() => {
      suggestionsFromCorpus(term)
        .then((s) => { setSugs(s); setOpen(s.length > 0); setActive(-1) })
        .catch(() => { /* aborted or offline — keep the previous list */ })
    }, 160)
    return () => { clearTimeout(t); ctl.abort() }
  }, [q])

  // Close on any click outside the search box.
  useEffect(() => {
    if (!open) return
    const onDown = (e: MouseEvent) => {
      if (boxRef.current && !boxRef.current.contains(e.target as Node)) setOpen(false)
    }
    document.addEventListener('mousedown', onDown)
    return () => document.removeEventListener('mousedown', onDown)
  }, [open])

  function submit(term: string) {
    skipNextFetch.current = true      // don't reopen the menu for the text we just set
    setQ(term)
    setOpen(false)
    setActive(-1)
    onSearch(term.trim())
  }

  function onKeyDown(e: React.KeyboardEvent<HTMLInputElement>) {
    if (!open || sugs.length === 0) return
    if (e.key === 'ArrowDown') {
      e.preventDefault(); setActive((i) => (i + 1) % sugs.length)
    } else if (e.key === 'ArrowUp') {
      e.preventDefault(); setActive((i) => (i <= 0 ? sugs.length - 1 : i - 1))
    } else if (e.key === 'Enter') {
      // Enter with a highlighted row picks it; otherwise the typed text wins.
      if (active >= 0) { e.preventDefault(); submit(sugs[active].value) }
    } else if (e.key === 'Escape') {
      setOpen(false); setActive(-1)
    }
  }

  const SUG_META: Record<SearchSuggestion['type'], { icon: IconName; label: string }> = {
    company: { icon: 'building', label: 'Company' },
    title:   { icon: 'list',     label: 'Role' },
    skill:   { icon: 'target',   label: 'Category' },
  }

  return (
    <header style={{ position: 'sticky', top: 0, zIndex: 200, background: 'var(--surface)', borderBottom: '1px solid var(--border)' }}>
      {/* Brand + search + actions */}
      <div style={{
        display: 'flex', alignItems: 'center', gap: isMobile ? 8 : 18,
        padding: isMobile ? '8px 12px' : '10px 24px', maxWidth: 1640, margin: '0 auto',
      }}>
        {/* Brand */}
        <div style={{ display: 'flex', alignItems: 'center', gap: 11, flexShrink: 0 }}>
          <div style={{
            width: isMobile ? 36 : 40, height: isMobile ? 36 : 40, borderRadius: 10, background: 'var(--brand-tile)',
            display: 'flex', alignItems: 'center', justifyContent: 'center',
            overflow: 'hidden', boxShadow: '0 2px 8px rgba(0,0,0,0.25)',
            border: '1px solid rgba(255,255,255,0.06)', flexShrink: 0,
          }}>
            <img src="/volt-logo.png" alt="Ashborne Volt"
              style={{ width: isMobile ? 30 : 34, height: isMobile ? 30 : 34, objectFit: 'contain' }} />
          </div>
          {!isMobile && (
            <div style={{ fontWeight: 800, fontSize: 17, color: 'var(--text-primary)', lineHeight: 1.1, letterSpacing: '-0.02em' }}>
              Ashborne Volt
            </div>
          )}
        </div>

        {/* Search */}
        <div ref={boxRef} style={{ flex: 1, maxWidth: isMobile ? undefined : 540, position: 'relative' }}>
        <form
          onSubmit={(e) => { e.preventDefault(); submit(active >= 0 && sugs[active] ? sugs[active].value : q) }}
          style={{ position: 'relative' }}
        >
          <span style={{ position: 'absolute', left: 12, top: '50%', transform: 'translateY(-50%)', color: 'var(--text-tertiary)', display: 'flex' }}>
            <Icon name="search" size={16} />
          </span>
          <input
            value={q}
            onChange={(e) => setQ(e.target.value)}
            onKeyDown={onKeyDown}
            onFocus={(e) => {
              e.currentTarget.style.borderColor = 'var(--primary)'
              if (sugs.length > 0) setOpen(true)
            }}
            onBlur={(e) => { e.currentTarget.style.borderColor = 'var(--border)' }}
            placeholder={isMobile ? 'Search jobs…' : 'Search by title, company, skill, protocol, or state…'}
            role="combobox"
            aria-expanded={open}
            aria-controls="search-suggestions"
            aria-autocomplete="list"
            aria-activedescendant={active >= 0 ? `search-sug-${active}` : undefined}
            autoComplete="off"
            style={{
              width: '100%', height: 38, paddingLeft: 36, paddingRight: q ? 64 : 14,
              background: 'var(--surface-muted)', border: '1px solid var(--border)',
              borderRadius: open ? '18px 18px 0 0' : 999,
              fontSize: 13.5, color: 'var(--text-primary)', outline: 'none',
              transition: 'background 0.14s, border-color 0.14s',
            }}
          />
          {q && (
            <button type="button" onClick={() => { setQ(''); setSugs([]); setOpen(false); onSearch('') }}
              style={{
                position: 'absolute', right: 8, top: '50%', transform: 'translateY(-50%)',
                background: 'var(--surface)', border: '1px solid var(--border)', borderRadius: '50%',
                width: 22, height: 22, cursor: 'pointer', display: 'flex',
                alignItems: 'center', justifyContent: 'center', color: 'var(--text-secondary)',
              }}>
              <Icon name="x" size={13} />
            </button>
          )}
        </form>

        {open && sugs.length > 0 && (
          <ul
            id="search-suggestions"
            role="listbox"
            style={{
              position: 'absolute', top: '100%', left: 0, right: 0, zIndex: 300,
              margin: 0, padding: '4px 0', listStyle: 'none',
              background: 'var(--surface)', border: '1px solid var(--border)',
              borderTop: 'none', borderRadius: '0 0 12px 12px',
              boxShadow: '0 10px 28px rgba(0,0,0,0.16)',
              maxHeight: 340, overflowY: 'auto',
            }}
          >
            {sugs.map((s, i) => {
              const meta = SUG_META[s.type]
              return (
                <li
                  key={`${s.type}:${s.value}`}
                  id={`search-sug-${i}`}
                  role="option"
                  aria-selected={i === active}
                  onMouseEnter={() => setActive(i)}
                  // mousedown, not click: the input's blur would otherwise close
                  // the menu before the click ever lands.
                  onMouseDown={(e) => { e.preventDefault(); submit(s.value) }}
                  style={{
                    display: 'flex', alignItems: 'center', gap: 9,
                    padding: '7px 12px', cursor: 'pointer', fontSize: 13,
                    background: i === active ? 'var(--surface-muted)' : 'transparent',
                    color: 'var(--text-primary)',
                  }}
                >
                  <span style={{ display: 'flex', color: 'var(--text-tertiary)', flexShrink: 0 }}>
                    <Icon name={meta.icon} size={14} />
                  </span>
                  <span style={{ flex: 1, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>
                    {s.value}
                  </span>
                  <span style={{ fontSize: 10.5, color: 'var(--text-tertiary)', flexShrink: 0 }}>
                    {meta.label}
                  </span>
                  <span style={{
                    fontSize: 10.5, fontWeight: 700, color: 'var(--text-secondary)',
                    background: 'var(--surface-muted)', border: '1px solid var(--border)',
                    borderRadius: 999, padding: '1px 7px', flexShrink: 0, minWidth: 26,
                    textAlign: 'center',
                  }}>
                    {s.count}
                  </span>
                </li>
              )
            })}
          </ul>
        )}
        </div>

        {!isMobile && <div style={{ flex: 1 }} />}

        {/* Theme toggle */}
        <button
          onClick={onToggleTheme}
          title={theme === 'light' ? 'Switch to dark mode' : 'Switch to light mode'}
          aria-label="Toggle theme"
          style={{
            width: 38, height: 38, borderRadius: 10, cursor: 'pointer', flexShrink: 0,
            background: 'var(--surface-muted)', border: '1px solid var(--border)',
            color: 'var(--text-secondary)', display: 'flex', alignItems: 'center', justifyContent: 'center',
            transition: 'background 0.14s, color 0.14s',
          }}
          onMouseEnter={(e) => { e.currentTarget.style.color = 'var(--text-primary)' }}
          onMouseLeave={(e) => { e.currentTarget.style.color = 'var(--text-secondary)' }}
        >
          <Icon name={theme === 'light' ? 'moon' : 'sun'} size={18} />
        </button>

        {/* Refresh — icon-only on mobile to save horizontal space */}
        <button
          onClick={onRefresh}
          disabled={refreshing}
          className="btn btn-primary"
          title="Refresh jobs"
          style={isMobile ? { width: 38, height: 38, padding: 0, justifyContent: 'center', flexShrink: 0 } : undefined}
        >
          {refreshing ? (
            <><span className="spin"><Icon name="refresh" size={15} color="var(--on-primary)" /></span>{!isMobile && ' Updating…'}</>
          ) : (
            <><Icon name="refresh" size={15} color="var(--on-primary)" />{!isMobile && ' Refresh Jobs'}</>
          )}
        </button>
      </div>

      {/* Tabs */}
      <div style={{ borderTop: '1px solid var(--border)' }}>
        <div style={{
          display: 'flex', alignItems: 'center', padding: isMobile ? '0 8px' : '0 24px',
          overflowX: 'auto', gap: 4, maxWidth: 1640, margin: '0 auto',
        }}>
          {TABS.map((t) => {
            const badge = analytics && t.badge ? t.badge(analytics) : null
            const active = activeTab === t.id
            return (
              <button
                key={t.id}
                onClick={() => onTabChange(t.id)}
                style={{
                  background: 'none', border: 'none',
                  borderBottom: active ? '2.5px solid var(--primary)' : '2.5px solid transparent',
                  color: active ? 'var(--primary)' : 'var(--text-secondary)',
                  padding: '11px 12px', cursor: 'pointer', fontSize: 13,
                  fontWeight: active ? 700 : 500, whiteSpace: 'nowrap',
                  display: 'flex', alignItems: 'center', gap: 7,
                  transition: 'color 0.12s, border-color 0.12s', marginBottom: -1,
                }}
                onMouseEnter={(e) => { if (!active) e.currentTarget.style.color = 'var(--text-primary)' }}
                onMouseLeave={(e) => { if (!active) e.currentTarget.style.color = 'var(--text-secondary)' }}
              >
                <Icon name={t.icon} size={16} color={active ? 'var(--primary)' : 'currentColor'} />
                {t.label}
                {badge !== null && badge > 0 && (
                  <span style={{
                    background: active ? 'var(--primary)' : 'var(--surface-muted)',
                    color: active ? 'var(--on-primary)' : 'var(--text-secondary)',
                    borderRadius: 999, padding: '1px 7px', fontSize: 11, fontWeight: 700,
                    lineHeight: '16px', border: active ? 'none' : '1px solid var(--border)',
                  }}>
                    {badge > 999 ? '999+' : badge}
                  </span>
                )}
              </button>
            )
          })}
        </div>
      </div>
    </header>
  )
}
