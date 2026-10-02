import { useCallback, useEffect, useState } from 'react'
import { facetsFromCorpus, loadCorpus } from '../lib/corpus'
import { queryJobs } from '../lib/query'
import * as studio from '../lib/studio'
import type { Filters, JobFacets, Watchlist } from '../lib/types'
import { Icon } from './Icon'
import { enablePushAlerts, pushPermission } from '../lib/push'
import { CATEGORIES, CATEGORY_BLURBS, QUICK_KEYWORDS } from '../lib/categories'

interface Props {
  filters: Filters
  onChange: (f: Filters) => void
  totalCount: number
  /** When rendered inside the mobile drawer: full-width, non-sticky, with a close button. */
  mobile?: boolean
  onClose?: () => void
  /** Hide the Sort-By control (the Resume Matches tab has its own resume-specific sort). */
  hideSort?: boolean
}

// The twelve EE categories (backend/app/taxonomy.py is the authority).
const QUICK_KWS = QUICK_KEYWORDS
const US_STATES = ['TX', 'CA', 'NC', 'FL', 'GA', 'PA', 'OH', 'IL', 'NY', 'AZ', 'CO', 'WA', 'VA', 'MI', 'MO', 'TN', 'SC', 'IN', 'MN', 'WI']
const SENIORITY_LEVELS = ['Intern', 'New Grad', 'Entry Level', 'Junior', 'Associate', 'Mid-Level', 'Senior', 'Staff', 'Principal', 'Lead', 'Manager']
const SENIOR_TIER = new Set(['Senior', 'Staff', 'Principal', 'Lead', 'Manager'])

const inp: React.CSSProperties = {
  width: '100%', background: 'var(--surface)',
  border: '1px solid var(--border)', borderRadius: 7,
  padding: '7px 10px', color: 'var(--text)', fontSize: 13,
  outline: 'none', transition: 'border-color 0.15s',
}

function SectionHead({ title }: { title: string }) {
  return (
    <div style={{
      fontSize: 10, fontWeight: 800, color: 'var(--text-muted)',
      letterSpacing: '0.08em', textTransform: 'uppercase', marginBottom: 8,
    }}>
      {title}
    </div>
  )
}

function Toggle({ on, onToggle, label, sub }: { on: boolean; onToggle: () => void; label: string; sub?: string }) {
  return (
    <label style={{
      display: 'flex', alignItems: 'center', gap: 10,
      cursor: 'pointer', userSelect: 'none', marginBottom: 12,
    }}>
      <div
        className="toggle-track"
        onClick={onToggle}
        style={{ background: on ? 'var(--primary)' : 'var(--border-strong)' }}
      >
        <div className="toggle-thumb" style={{ left: on ? 19 : 3 }} />
      </div>
      <div>
        <div style={{ fontSize: 13, fontWeight: 500, color: 'var(--text-primary)' }}>{label}</div>
        {sub && <div style={{ fontSize: 11, color: 'var(--text-tertiary)' }}>{sub}</div>}
      </div>
    </label>
  )
}

export function FilterSidebar({ filters, onChange, totalCount, mobile = false, onClose, hideSort = false }: Props) {
  const [facets, setFacets] = useState<JobFacets | null>(null)
  const [watchlists, setWatchlists] = useState<Watchlist[]>([])
  const [alertState, setAlertState] = useState<'idle' | 'enabling' | 'on' | 'error'>(
    () => (pushPermission() === 'granted' ? 'on' : 'idle'),
  )
  const [alertMsg, setAlertMsg] = useState('')

  // Saved searches are a named filter set plus the count when you last looked —
  // your data, a few KB, so it lives in this browser. "N new" is measured by
  // re-running the filters against the corpus, which is already in memory.
  const loadWatchlists = useCallback(() => {
    loadCorpus()
      .then((corpus) => {
        const active = corpus.jobs.filter((j) => String(j.active_status ?? 'active') === 'active')
        setWatchlists(
          studio.getWatchlists().map((w) => {
            const total = queryJobs(active, w.filters, 1, 1).total_count
            return {
              id: w.id, name: w.name, filters: w.filters,
              alert_enabled: w.alert_enabled, last_checked_at: w.last_checked_at,
              total, new_count: Math.max(0, total - (w.last_count ?? 0)),
            } as Watchlist
          }),
        )
      })
      .catch(() => {/* non-fatal */})
  }, [])

  useEffect(() => { loadWatchlists() }, [loadWatchlists])

  async function enableAlerts() {
    setAlertState('enabling'); setAlertMsg('')
    const r = await enablePushAlerts()
    if (r.ok) { setAlertState('on'); setAlertMsg('Alerts on — you’ll be notified of new matches.') }
    else { setAlertState('error'); setAlertMsg(r.message) }
  }

  async function saveWatchlist() {
    const name = window.prompt('Name this saved search (e.g. "Entry-level Power Systems in TX/NC"):')
    if (!name) return
    const clean = Object.fromEntries(Object.entries(filters).filter(([, v]) => v !== undefined && v !== '' && v !== false))
    const corpus = await loadCorpus()
    const active = corpus.jobs.filter((j) => String(j.active_status ?? 'active') === 'active')
    studio.createWatchlist(name, clean, queryJobs(active, clean, 1, 1).total_count)
    loadWatchlists()
  }
  async function applyWatchlist(w: Watchlist) {
    onChange({ usa_only: true, include_senior: true, ...w.filters })
    studio.checkWatchlist(w.id, w.total ?? 0)
    loadWatchlists()
  }
  async function removeWatchlist(id: number) {
    studio.deleteWatchlist(id)
    loadWatchlists()
  }

  useEffect(() => {
    facetsFromCorpus(filters.usa_only !== false, filters.include_software)
      .then(setFacets)
      .catch(() => {/* non-fatal */})
  }, [filters.usa_only, filters.include_software])

  const set = (k: keyof Filters, v: unknown) =>
    onChange({ ...filters, [k]: v === '' ? undefined : v })

  const selectedLevels = filters.level_filter ? filters.level_filter.split(',').filter(Boolean) : []
  function toggleLevel(lv: string) {
    const next = selectedLevels.includes(lv) ? selectedLevels.filter((x) => x !== lv) : [...selectedLevels, lv]
    const needSenior = next.some((l) => SENIOR_TIER.has(l))
    onChange({
      ...filters,
      level_filter: next.join(',') || undefined,
      include_senior: needSenior ? true : filters.include_senior,
    })
  }

  const hasFilters = Object.entries(filters).some(([k, v]) => {
    if (k === 'usa_only' && v === true) return false
    if (k === 'include_senior') return false  // always on now; not a user filter
    if (k === 'sort_by' || k === 'sort_order') return false
    return v !== undefined && v !== '' && v !== false
  })

  const rootStyle: React.CSSProperties = mobile
    ? { width: '100%', flexShrink: 0, background: 'var(--surface)' }
    : {
        width: 'var(--sidebar-width)', flexShrink: 0,
        background: 'var(--surface)',
        border: '1px solid var(--border)',
        borderRadius: 10,
        position: 'sticky', top: 'calc(var(--nav-height) + 8px)',
        maxHeight: 'calc(100vh - var(--nav-height) - 24px)',
        overflowY: 'auto', alignSelf: 'flex-start',
      }

  return (
    <aside style={rootStyle}>
      {/* Header */}
      <div style={{
        display: 'flex', justifyContent: 'space-between', alignItems: 'center',
        padding: '14px 16px 10px',
        borderBottom: '1px solid var(--border)',
        position: 'sticky', top: 0, background: 'var(--surface)', zIndex: 1,
      }}>
        <div style={{ display: 'flex', alignItems: 'center', gap: 10 }}>
          <span style={{ fontWeight: 700, fontSize: 14, color: 'var(--text)' }}>Filters</span>
          {facets && (
            <span style={{ fontSize: 12, color: 'var(--text-faint)' }}>
              {totalCount.toLocaleString()} jobs
            </span>
          )}
        </div>
        <div style={{ display: 'flex', alignItems: 'center', gap: 10 }}>
          {hasFilters && (
            <button
              onClick={() => onChange({ usa_only: true, include_senior: true })}
              style={{
                background: 'none', border: 'none', color: 'var(--primary)',
                fontSize: 12, fontWeight: 700, cursor: 'pointer', padding: 0,
              }}
            >
              Clear all
            </button>
          )}
          {mobile && onClose && (
            <button
              onClick={onClose}
              title="Done"
              style={{
                background: 'var(--surface-sunken)', border: '1px solid var(--border)',
                borderRadius: 6, width: 30, height: 30, cursor: 'pointer', color: 'var(--text-muted)',
                display: 'flex', alignItems: 'center', justifyContent: 'center',
              }}
            ><Icon name="x" size={16} /></button>
          )}
        </div>
      </div>

      <div style={{ padding: '12px 16px' }}>

        {/* Saved searches / watchlists */}
        <div style={{ marginBottom: 16 }}>
          <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 8 }}>
            <span style={{ fontSize: 10, fontWeight: 800, color: 'var(--text-secondary)', letterSpacing: '0.08em', textTransform: 'uppercase' }}>Saved Searches</span>
            <button onClick={saveWatchlist} title="Save current filters"
              style={{ background: 'none', border: 'none', color: 'var(--primary)', fontSize: 11.5, fontWeight: 700, cursor: 'pointer', padding: 0, display: 'inline-flex', alignItems: 'center', gap: 3 }}>
              <Icon name="bookmark" size={12} color="var(--primary)" /> Save
            </button>
          </div>
          {watchlists.length === 0 ? (
            <div style={{ fontSize: 11, color: 'var(--text-tertiary)' }}>Save a filter set to track new jobs.</div>
          ) : (
            <div style={{ display: 'flex', flexDirection: 'column', gap: 5 }}>
              {watchlists.map((w) => (
                <div key={w.id} style={{ display: 'flex', alignItems: 'center', gap: 6, background: 'var(--surface-muted)', borderRadius: 7, padding: '6px 9px' }}>
                  <button onClick={() => applyWatchlist(w)} style={{ flex: 1, minWidth: 0, textAlign: 'left', background: 'none', border: 'none', cursor: 'pointer', padding: 0, color: 'var(--text-primary)', fontSize: 12, fontWeight: 600, whiteSpace: 'nowrap', overflow: 'hidden', textOverflow: 'ellipsis' }}>
                    {w.name}
                  </button>
                  {w.new_count > 0 && (
                    <span className="pill pill-primary" style={{ fontSize: 9.5, fontWeight: 800 }}>{w.new_count} new</span>
                  )}
                  <span style={{ fontSize: 10.5, color: 'var(--text-tertiary)' }}>{w.total}</span>
                  <button onClick={() => removeWatchlist(w.id)} title="Delete" style={{ background: 'none', border: 'none', cursor: 'pointer', color: 'var(--text-tertiary)', padding: 0, display: 'flex' }}>
                    <Icon name="x" size={12} />
                  </button>
                </div>
              ))}
            </div>
          )}

          {/* Browser push alerts for saved searches (free). */}
          {pushPermission() !== 'unsupported' && (
            <div style={{ marginTop: 8 }}>
              {alertState === 'on' ? (
                <div style={{ fontSize: 11, color: 'var(--success)', display: 'inline-flex', alignItems: 'center', gap: 4, fontWeight: 600 }}>
                  <Icon name="bell" size={12} color="var(--success)" /> Alerts on
                </div>
              ) : (
                <button onClick={enableAlerts} disabled={alertState === 'enabling'}
                  style={{ background: 'none', border: 'none', color: 'var(--primary)', fontSize: 11.5, fontWeight: 700, cursor: 'pointer', padding: 0, display: 'inline-flex', alignItems: 'center', gap: 4 }}>
                  <Icon name="bell" size={12} color="var(--primary)" />
                  {alertState === 'enabling' ? 'Enabling…' : 'Enable new-job alerts'}
                </button>
              )}
              {alertMsg && (
                <div style={{ fontSize: 10.5, color: alertState === 'error' ? 'var(--warning)' : 'var(--text-tertiary)', marginTop: 3, lineHeight: 1.4 }}>{alertMsg}</div>
              )}
            </div>
          )}
        </div>

        {/* Sort — hidden on the Resume Matches tab (it has its own resume sort). */}
        {!hideSort && (
          <div style={{ marginBottom: 16 }}>
            <SectionHead title="Sort By" />
            <select
              value={filters.sort_by || 'new_grad_fit'}
              onChange={(e) => set('sort_by', e.target.value)}
              style={inp}
            >
              <option value="new_grad_fit">Best New Grad Fit</option>
              <option value="match_score">Most relevant</option>
              <option value="posted_date">Newest first</option>
              <option value="first_seen_at">Recently added to radar</option>
            </select>
          </div>
        )}

        {/* H1B sponsorship */}
        <div style={{ marginBottom: 14 }}>
          <Toggle
            on={!!filters.h1b_only}
            onToggle={() => set('h1b_only', !filters.h1b_only)}
            label="H1B sponsor-friendly"
            sub="Only companies that historically sponsor H1B"
          />
        </div>

        {/* Company Tier */}
        <div style={{ marginBottom: 16 }}>
          <SectionHead title="Company Tier" />
          <div style={{ display: 'flex', gap: 5, flexWrap: 'wrap' }}>
            {[
              { v: 'S', label: 'S — Dream', cls: 'tier-s' },
              { v: 'A', label: 'A — Target', cls: 'tier-a' },
              { v: 'B', label: 'B — Good', cls: 'tier-b' },
              { v: 'C', label: 'C — Backup', cls: 'tier-c' },
            ].map(({ v, label, cls }) => (
              <button
                key={v}
                onClick={() => set('priority', filters.priority === v ? '' : v)}
                className={filters.priority === v ? cls : ''}
                title={label}
                style={{
                  border: filters.priority === v ? '1.5px solid currentColor' : '1px solid var(--border)',
                  background: filters.priority === v ? undefined : 'var(--bg)',
                  borderRadius: 6, padding: '4px 10px',
                  fontSize: 12, fontWeight: 700, cursor: 'pointer',
                  color: filters.priority === v ? undefined : 'var(--text-muted)',
                }}
              >
                {v}
              </button>
            ))}
          </div>
        </div>

        {/* Seniority */}
        <div style={{ marginBottom: 16 }}>
          <SectionHead title="Seniority" />
          <div style={{ display: 'flex', gap: 5, flexWrap: 'wrap' }}>
            {SENIORITY_LEVELS.map((lv) => {
              const sel = selectedLevels.includes(lv)
              return (
                <button
                  key={lv}
                  onClick={() => toggleLevel(lv)}
                  style={{
                    border: sel ? '1px solid var(--primary-mid)' : '1px solid var(--border)',
                    background: sel ? 'var(--primary-light)' : 'var(--surface-muted)',
                    color: sel ? 'var(--primary)' : 'var(--text-secondary)',
                    borderRadius: 999, padding: '3px 9px', fontSize: 11, fontWeight: 600, cursor: 'pointer',
                  }}
                >
                  {lv}
                </button>
              )
            })}
          </div>
        </div>

        {/* Role Category */}
        <div style={{ marginBottom: 16 }}>
          <SectionHead title="Role Category" />
          <select
            value={filters.role_category || ''}
            onChange={(e) => set('role_category', e.target.value)}
            style={inp}
          >
            <option value="">All categories</option>
            {CATEGORIES.map((c) => {
              const f = facets?.role_categories.find((r) => r.value === c)
              return (
                <option key={c} value={c} title={CATEGORY_BLURBS[c]}>
                  {c}{f ? ` (${f.count})` : ''}
                </option>
              )
            })}
          </select>
        </div>

        {/* Remote Status */}
        <div style={{ marginBottom: 16 }}>
          <SectionHead title="Remote Status" />
          <div style={{ display: 'flex', gap: 5 }}>
            {['Remote', 'Hybrid', 'Onsite'].map((v) => {
              const active = filters.remote === v
              return (
                <button
                  key={v}
                  onClick={() => set('remote', active ? '' : v)}
                  className={active ? 'pill-primary' : ''}
                  style={{
                    flex: 1, border: active ? '1px solid var(--primary-mid)' : '1px solid var(--border)',
                    background: active ? undefined : 'var(--surface-muted)',
                    borderRadius: 6, padding: '5px 0', fontSize: 11, fontWeight: 600,
                    cursor: 'pointer', color: active ? 'var(--primary)' : 'var(--text-secondary)',
                    transition: 'all 0.1s',
                  }}
                >
                  {v}
                </button>
              )
            })}
          </div>
        </div>

        {/* Min Score */}
        <div style={{ marginBottom: 16 }}>
          <SectionHead title="Min Relevance Score" />
          <div style={{ display: 'flex', gap: 5, flexWrap: 'wrap' }}>
            {[0, 50, 65, 75, 85].map((n) => {
              const active = (filters.min_score ?? 0) === n
              return (
                <button
                  key={n}
                  onClick={() => set('min_score', active ? undefined : n === 0 ? undefined : n)}
                  style={{
                    background: active ? 'var(--primary)' : 'var(--bg)',
                    border: `1px solid ${active ? 'var(--primary)' : 'var(--border)'}`,
                    borderRadius: 6, padding: '4px 9px',
                    fontSize: 12, fontWeight: 600, cursor: 'pointer',
                    color: active ? 'var(--on-primary)' : 'var(--text-muted)',
                  }}
                >
                  {n === 0 ? 'Any' : `${n}+`}
                </button>
              )
            })}
          </div>
        </div>

        {/* New Since — matches the card's own freshness line: the real posted
            date when the source gives one, else when we first saw the job. */}
        <div style={{ marginBottom: 16 }}>
          <SectionHead title="Posted / Added Within" />
          <div style={{ fontSize: 10.5, color: 'var(--text-tertiary)', margin: '-4px 0 6px' }}>
            Matches the “Posted…／Added…” line on each card.
          </div>
          <select
            value={filters.posted_within_hours ?? ''}
            onChange={(e) => set('posted_within_hours', e.target.value ? Number(e.target.value) : undefined)}
            style={inp}
          >
            <option value="">All time</option>
            <option value="1">Last 1 hour</option>
            <option value="3">Last 3 hours</option>
            <option value="6">Last 6 hours</option>
            <option value="12">Last 12 hours</option>
            <option value="24">Last 24 hours</option>
            <option value="72">Last 3 days</option>
            <option value="168">Last 7 days</option>
            <option value="336">Last 14 days</option>
            <option value="720">Last 30 days</option>
          </select>
        </div>

        {/* US State */}
        <div style={{ marginBottom: 16 }}>
          <SectionHead title="US State" />
          <select
            value={filters.state || ''}
            onChange={(e) => set('state', e.target.value)}
            style={inp}
          >
            <option value="">All states</option>
            {US_STATES.map((s) => {
              const f = facets?.states.find((x) => x.value === s)
              return (
                <option key={s} value={s}>
                  {s}{f ? ` (${f.count})` : ''}
                </option>
              )
            })}
          </select>
        </div>

        {/* Quick Keyword Chips */}
        <div style={{ marginBottom: 8 }}>
          <SectionHead title="Quick Keywords" />
          <div style={{ display: 'flex', flexWrap: 'wrap', gap: 5 }}>
            {QUICK_KWS.map((kw) => {
              const active = filters.keyword === kw
              return (
                <button
                  key={kw}
                  onClick={() => set('keyword', active ? '' : kw)}
                  style={{
                    background: active ? 'var(--primary-light)' : 'var(--bg)',
                    border: `1px solid ${active ? 'var(--primary)' : 'var(--border)'}`,
                    borderRadius: 5, padding: '3px 8px',
                    fontSize: 11, fontWeight: 500, cursor: 'pointer',
                    color: active ? 'var(--primary)' : 'var(--text-muted)',
                  }}
                >
                  {kw}
                </button>
              )
            })}
          </div>
        </div>

        {/* Facet counts summary */}
        {facets && (
          <div style={{
            marginTop: 16, padding: '10px 12px',
            background: 'var(--bg)', borderRadius: 8,
            border: '1px solid var(--border)',
          }}>
            <div style={{ fontSize: 11, fontWeight: 700, color: 'var(--text-muted)', marginBottom: 8, letterSpacing: '0.05em', textTransform: 'uppercase' }}>
              Quick Stats
            </div>
            {[
              { label: 'True Entry-Level', value: facets.entry_level_count, color: 'var(--success)' },
              { label: 'Remote', value: facets.remote_count, color: 'var(--teal)' },
              { label: 'New Today', value: facets.new_24h_count, color: 'var(--primary)' },
            ].map(({ label, value, color }) => (
              <div key={label} style={{
                display: 'flex', justifyContent: 'space-between',
                alignItems: 'center', marginBottom: 5,
              }}>
                <span style={{ fontSize: 12, color: 'var(--text-muted)' }}>{label}</span>
                <span style={{ fontSize: 12, fontWeight: 700, color }}>{value}</span>
              </div>
            ))}
          </div>
        )}
      </div>
    </aside>
  )
}
