import { useEffect, useState } from 'react'
import { loadCorpus } from '../lib/corpus'
import { parseApiDate } from '../lib/datetime'
import type { AnalyticsSummary, Company, PipelineHealth, ScrapeRun } from '../lib/types'

const TZ_OPTIONS: { label: string; value: string }[] = [
  { label: 'My local time', value: 'local' },
  { label: 'Eastern (ET)', value: 'America/New_York' },
  { label: 'Central (CT)', value: 'America/Chicago' },
  { label: 'Mountain (MT)', value: 'America/Denver' },
  { label: 'Pacific (PT)', value: 'America/Los_Angeles' },
]
const RUNS_PREVIEW = 20

/** Is scraping actually happening? Derived from the snapshot's run history and
 *  its generation time, so a stalled pipeline is visible in the app rather than
 *  only in a workflow email — the thing that let a three-day outage go unnoticed. */
function pipelineFromSnapshot(generatedAt: string, runs: ScrapeRun[]): PipelineHealth {
  const now = Date.now()
  const ageH = (iso?: string | null) =>
    iso ? Math.round(((now - Date.parse(iso)) / 3600_000) * 10) / 10 : null
  const engines = ([
    ['static', 3, ['static', 'github-actions']],
    ['browser', 8, ['browser']],
    ['cf', 3, ['cf']],
  ] as [string, number, string[]][]).map(([engine, cadence, names]) => {
    const last = runs.find((r) => names.includes(r.triggered_by) && r.finished_at && r.companies_scraped > 0)
    const h = ageH(last?.started_at)
    const status: 'ok' | 'stale' | 'down' =
      h == null ? 'down' : h <= cadence * 2 ? 'ok' : h <= cadence * 4 ? 'stale' : 'down'
    return {
      engine, cadence_hours: cadence, status,
      hours_since_last_good_run: h,
      last_good_run_at: last?.started_at ?? null,
      companies_scraped: last?.companies_scraped ?? 0,
      new_jobs: last?.new_jobs ?? 0,
    }
  })
  // The headline reflects whether jobs are STILL ARRIVING, not the worst single
  // engine. Taking the worst meant one stalled source printed "Scraping has
  // stopped" in red while the other two had just pulled 49 companies minutes
  // earlier — alarming and simply untrue. Only "nothing is getting through"
  // deserves the red state; one source behind is degraded, and the engine chips
  // below say exactly which.
  const working = engines.filter((e) => e.status === 'ok').length
  const corpusAgeH = ageH(generatedAt)
  const corpusFresh = corpusAgeH != null && corpusAgeH <= 12
  const status: 'ok' | 'stale' | 'down' =
    working === engines.length ? 'ok'
    : working > 0 || corpusFresh ? 'stale'
    : 'down'
  return {
    status, engines,
    last_job_seen_at: generatedAt,
    hours_since_any_job_seen: corpusAgeH,
  }
}

// The pipeline reports engines by their internal identifiers; these are the
// names a reader should actually see.
const ENGINE_LABELS: Record<string, string> = {
  static: 'Standard career APIs',
  'github-actions': 'Standard career APIs',
  cf: 'Protected career sites',
  browser: 'Large-employer sites',
}

// Module-level cache so re-opening Data Health paints instantly while it
// refreshes in the background (survives tab switches within a session).
let _healthCache: { runs: ScrapeRun[]; companies: Company[]; analytics: AnalyticsSummary | null } | null = null

export function ScrapeHealth() {
  const [runs, setRuns] = useState<ScrapeRun[]>(() => _healthCache?.runs ?? [])
  const [companies, setCompanies] = useState<Company[]>(() => _healthCache?.companies ?? [])
  const [analytics] = useState<AnalyticsSummary | null>(() => _healthCache?.analytics ?? null)
  const [loading, setLoading] = useState(() => _healthCache === null)
  const [tz, setTz] = useState<string>(() => localStorage.getItem('volt-tz') || 'local')
  const [showAllRuns, setShowAllRuns] = useState(false)
  const [pipeline, setPipeline] = useState<PipelineHealth | null>(null)

  useEffect(() => {
    // Everything on this page comes from the published snapshot: the scrape runs
    // it recorded, the company roster, and a pipeline verdict derived from the
    // run history. No API, because there is no longer a server holding this.
    loadCorpus()
      .then((corpus) => {
        const runs = (corpus.runs || []) as unknown as ScrapeRun[]
        const companies = corpus.companies.map((c, i) => ({
          id: i + 1, name: c.name, category: c.category, priority: c.priority,
          careers_url: c.careers_url, company_search_url: '', ats_platform: c.ats_platform,
          enabled: c.enabled, last_scraped_at: c.last_scraped_at,
          scrape_error_count: c.scrape_error_count, notes: '',
          consecutive_empty_scrapes: c.consecutive_empty_scrapes,
          quarantined: c.quarantined,
          total_active_jobs: c.total_active_jobs, usa_active_jobs: c.usa_active_jobs,
          viewable_jobs: c.viewable_jobs, entry_level_jobs: c.entry_level_jobs,
          new_jobs_today: c.new_jobs_today, parser_confidence: c.parser_confidence,
          scrape_status: c.scrape_status, engine: c.engine,
          auto_connected: c.auto_connected,
        })) as unknown as Company[]
        _healthCache = { runs, companies, analytics: null }
        setRuns(runs); setCompanies(companies)
        setPipeline(pipelineFromSnapshot(corpus.generated_at, runs))
      })
      .catch(() => setPipeline(null))
      .finally(() => setLoading(false))
  }, [])

  function changeTz(v: string) { setTz(v); localStorage.setItem('volt-tz', v) }

  const fmt = (d: string | null) => {
    const date = parseApiDate(d)
    if (!date) return '—'
    const opts: Intl.DateTimeFormatOptions = { month: 'short', day: 'numeric', hour: '2-digit', minute: '2-digit' }
    if (tz !== 'local') opts.timeZone = tz
    return date.toLocaleString('en-US', opts)
  }

  const shownRuns = showAllRuns ? runs : runs.slice(0, RUNS_PREVIEW)

  const errCompanies = companies.filter((c) => c.scrape_error_count > 0)
    .sort((a, b) => b.scrape_error_count - a.scrape_error_count)

  // Sources needing attention, worst first. A quarantined source has been skipped
  // outright; a stalled one still runs and answers, but has returned nothing for
  // long enough that an empty board is no longer the likely explanation. Both
  // were invisible before — nothing created the Company rows these counts live
  // on, so every count was permanently zero and this panel could never fill.
  const needsAttention = companies
    .filter((c) => c.quarantined || c.scrape_status === 'stalled')
    .sort((a, b) =>
      Number(b.quarantined ?? false) - Number(a.quarantined ?? false) ||
      (b.consecutive_empty_scrapes ?? 0) - (a.consecutive_empty_scrapes ?? 0))

  if (loading) {
    return <div style={{ padding: 40, textAlign: 'center', color: 'var(--text-muted)' }}>Loading…</div>
  }

  return (
    <div>
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', flexWrap: 'wrap', gap: 12, marginBottom: 20 }}>
        <h2 style={{ fontSize: 18, fontWeight: 700, margin: 0, color: 'var(--text)' }}>
          Data Health
        </h2>
        <label style={{ display: 'inline-flex', alignItems: 'center', gap: 8, fontSize: 12.5, color: 'var(--text-secondary)' }}>
          Times in
          <select value={tz} onChange={(e) => changeTz(e.target.value)}
            style={{ background: 'var(--surface)', border: '1px solid var(--border)', borderRadius: 7, padding: '5px 9px', color: 'var(--text-primary)', fontSize: 12.5, outline: 'none' }}>
            {TZ_OPTIONS.map((o) => <option key={o.value} value={o.value}>{o.label}</option>)}
          </select>
        </label>
      </div>

      {/* Pipeline verdict — is scraping actually happening right now? A dead
          pipeline used to be invisible here: one workflow emailed, the other
          reported success while scraping nothing for three days. */}
      {pipeline && (() => {
        const behind = pipeline.engines.filter((e) => e.status !== 'ok')
        const naming = behind.map((e) => ENGINE_LABELS[e.engine] ?? e.engine).join(', ')
        const tone = pipeline.status === 'ok'
          ? { bg: 'rgba(34,197,94,0.10)', bd: 'var(--success)', fg: 'var(--success)',
              text: 'Scraping is healthy' }
          : pipeline.status === 'stale'
          ? { bg: 'rgba(234,179,8,0.10)', bd: 'var(--warning)', fg: 'var(--warning)',
              text: `Jobs are still arriving — ${naming} ${behind.length === 1 ? 'is' : 'are'} behind` }
          : { bg: 'rgba(239,68,68,0.10)', bd: 'var(--danger)', fg: 'var(--danger)',
              text: 'Scraping has stopped — no source is reporting' }
        return (
          <div style={{ background: tone.bg, border: `1px solid ${tone.bd}`, borderRadius: 10, padding: '12px 14px', marginBottom: 18 }}>
            <div style={{ display: 'flex', alignItems: 'center', gap: 8, marginBottom: 8 }}>
              <span style={{ width: 9, height: 9, borderRadius: '50%', background: tone.fg, flexShrink: 0 }} />
              <strong style={{ fontSize: 13.5, color: tone.fg }}>{tone.text}</strong>
              {pipeline.hours_since_any_job_seen != null && (
                <span style={{ fontSize: 12, color: 'var(--text-secondary)' }}>
                  · newest job seen {pipeline.hours_since_any_job_seen}h ago
                </span>
              )}
            </div>
            <div style={{ display: 'flex', gap: 8, flexWrap: 'wrap' }}>
              {pipeline.engines.map((e) => {
                const c = e.status === 'ok' ? 'var(--success)' : e.status === 'stale' ? 'var(--warning)' : 'var(--danger)'
                return (
                  <div key={e.engine} style={{
                    background: 'var(--surface)', border: '1px solid var(--border)', borderRadius: 8,
                    padding: '6px 10px', fontSize: 11.5, color: 'var(--text-secondary)',
                  }}>
                    <span style={{ color: c, fontWeight: 700 }}>{ENGINE_LABELS[e.engine] ?? e.engine}</span>
                    {' · '}
                    {e.hours_since_last_good_run == null
                      ? 'never run'
                      : `updated ${e.hours_since_last_good_run}h ago, every ${e.cadence_hours}h`}
                    {e.companies_scraped > 0
                      && ` · ${e.companies_scraped} companies, ${e.new_jobs} new`}
                  </div>
                )
              })}
            </div>
          </div>
        )
      })()}

      {/* Summary stats */}
      <div style={{ display: 'flex', gap: 10, marginBottom: 24, flexWrap: 'wrap' }}>
        {[
          { label: 'Total Runs', value: runs.length, color: 'var(--primary)' },
          { label: 'Auto-Connected', value: companies.filter(c => c.auto_connected ?? c.enabled).length, color: 'var(--success)' },
          { label: 'Companies with Errors', value: errCompanies.length, color: errCompanies.length > 0 ? 'var(--error)' : 'var(--success)' },
          { label: 'Last Run New Jobs', value: runs[0]?.new_jobs ?? 0, color: 'var(--teal)' },
        ].map(({ label, value, color }) => (
          <div key={label} style={{
            background: 'var(--surface)', border: '1px solid var(--border)',
            borderRadius: 10, padding: '12px 16px', minWidth: 130,
          }}>
            <div style={{ fontSize: 22, fontWeight: 700, color }}>{value}</div>
            <div style={{ fontSize: 12, color: 'var(--text-muted)', marginTop: 2 }}>{label}</div>
          </div>
        ))}
      </div>

      {/* Job inventory funnel — reconciles "Found" (postings scanned) with the
          USA-relevant count shown on the dashboard so the numbers aren't confusing. */}
      {analytics?.job_inventory && (() => {
        const inv = analytics.job_inventory!
        const steps = [
          { label: 'Tracked in database', value: inv.active, color: 'var(--primary)',
            note: `${inv.total_in_db} total ever scraped` },
          { label: 'Filtered out', value: inv.non_usa_filtered + inv.software_filtered, color: 'var(--warning)',
            note: `${inv.non_usa_filtered} outside the US · ${inv.software_filtered} software-only` },
          { label: 'Shown to you', value: inv.usa_relevant, color: 'var(--success)',
            note: 'US-based / remote-US hardware roles — matches the All Jobs count' },
        ]
        return (
          <div style={{ marginBottom: 24 }}>
            <h3 style={{ fontSize: 14, fontWeight: 700, margin: '0 0 4px', color: 'var(--text)' }}>
              Job Inventory
            </h3>
            <p style={{ fontSize: 12, color: 'var(--text-muted)', margin: '0 0 10px' }}>
              Why “Found” below is larger than the dashboard count: the scraper scans every posting,
              then keeps only US-based hardware roles for you.
            </p>
            <div style={{ display: 'flex', gap: 8, flexWrap: 'wrap', alignItems: 'stretch' }}>
              {steps.map((st, i) => (
                <div key={st.label} style={{ display: 'flex', alignItems: 'stretch', gap: 8 }}>
                  <div style={{
                    background: 'var(--surface)', border: '1px solid var(--border)',
                    borderRadius: 10, padding: '12px 16px', minWidth: 150, maxWidth: 220,
                  }}>
                    <div style={{ fontSize: 22, fontWeight: 700, color: st.color }}>{st.value}</div>
                    <div style={{ fontSize: 12.5, fontWeight: 600, color: 'var(--text)', marginTop: 2 }}>{st.label}</div>
                    <div style={{ fontSize: 11, color: 'var(--text-muted)', marginTop: 3, lineHeight: 1.35 }}>{st.note}</div>
                  </div>
                  {i < steps.length - 1 && (
                    <div style={{ alignSelf: 'center', color: 'var(--text-faint)', fontSize: 18 }}>→</div>
                  )}
                </div>
              ))}
            </div>
          </div>
        )
      })()}

      {/* Recent runs */}
      <h3 style={{ fontSize: 14, fontWeight: 700, margin: '0 0 4px', color: 'var(--text)' }}>
        Recent Scrape Runs
      </h3>
      <p style={{ fontSize: 12, color: 'var(--text-muted)', margin: '0 0 10px' }}>
        “Found” = total postings scanned that run (before US / hardware filtering), not jobs added.
      </p>
      <div style={{
        background: 'var(--surface)', border: '1px solid var(--border)',
        borderRadius: 10, overflow: 'hidden', marginBottom: 24,
      }}>
        <div style={{ overflowX: 'auto' }}>
          <table style={{ width: '100%', borderCollapse: 'collapse', fontSize: 13 }}>
            <thead>
              <tr style={{ borderBottom: '1px solid var(--border)', background: 'var(--bg)' }}>
                {['Started', 'Duration', 'Companies', 'Found', 'New', 'Removed', 'Errors', 'By'].map((h) => (
                  <th key={h} style={{
                    padding: '8px 12px', textAlign: 'left', color: 'var(--text-muted)',
                    fontWeight: 700, fontSize: 11, letterSpacing: '0.04em', textTransform: 'uppercase',
                  }}>
                    {h}
                  </th>
                ))}
              </tr>
            </thead>
            <tbody>
              {runs.length === 0 ? (
                <tr>
                  <td colSpan={8} style={{ padding: '20px', textAlign: 'center', color: 'var(--text-muted)' }}>
                    No scrape runs yet. Click "Run Scrape" to start.
                  </td>
                </tr>
              ) : shownRuns.map((r) => {
                const dur = r.finished_at
                  ? Math.round((new Date(r.finished_at).getTime() - new Date(r.started_at).getTime()) / 60000)
                  : null
                return (
                  <tr key={r.id} style={{ borderBottom: '1px solid var(--border)' }}>
                    <td style={td}>{fmt(r.started_at)}</td>
                    <td style={td}>{dur != null ? `${dur}m` : <span style={{ color: 'var(--warning)' }}>running</span>}</td>
                    <td style={td}>{r.companies_scraped}</td>
                    <td style={td}>{r.jobs_found}</td>
                    <td style={{ ...td, color: r.new_jobs > 0 ? 'var(--success)' : 'var(--text-muted)', fontWeight: r.new_jobs > 0 ? 600 : 400 }}>
                      {r.new_jobs > 0 ? `+${r.new_jobs}` : r.new_jobs}
                    </td>
                    <td style={{ ...td, color: r.removed_jobs > 0 ? 'var(--warning)' : 'var(--text-muted)' }}>
                      {r.removed_jobs ?? 0}
                    </td>
                    <td style={{ ...td, color: r.errors > 0 ? 'var(--error)' : 'var(--success)', fontWeight: r.errors > 0 ? 600 : 400 }}>
                      {r.errors}
                    </td>
                    <td style={{ ...td, color: 'var(--text-muted)', fontSize: 11 }}>{r.triggered_by}</td>
                  </tr>
                )
              })}
            </tbody>
          </table>
        </div>
        {runs.length > RUNS_PREVIEW && (
          <div style={{ borderTop: '1px solid var(--border)', textAlign: 'center', padding: '8px' }}>
            <button onClick={() => setShowAllRuns((s) => !s)}
              style={{ background: 'none', border: 'none', color: 'var(--primary)', fontSize: 12.5, fontWeight: 700, cursor: 'pointer' }}>
              {showAllRuns ? 'Show fewer' : `Show all ${runs.length} runs`}
            </button>
          </div>
        )}
      </div>

      {/* Sources needing attention: skipped outright, or answering with nothing. */}
      {needsAttention.length > 0 && (
        <div style={{ marginBottom: 24 }}>
          <h3 style={{ fontSize: 14, fontWeight: 700, margin: '0 0 4px', color: 'var(--warning)' }}>
            Sources Needing Attention ({needsAttention.length})
          </h3>
          <p style={{ fontSize: 12, color: 'var(--text-muted)', margin: '0 0 10px' }}>
            Quarantined sources are being skipped after repeated hard failures.
            Stalled sources still run and answer, but have returned nothing for long
            enough that “no openings” is no longer the likely explanation — usually a
            selector or endpoint that has moved.
          </p>
          <div style={{ display: 'flex', flexWrap: 'wrap', gap: 8 }}>
            {needsAttention.map((c) => {
              const q = Boolean(c.quarantined)
              return (
                <div key={c.id} style={{
                  background: q ? 'var(--danger-light)' : 'var(--warning-light)',
                  border: `1px solid ${q ? 'var(--danger-border)' : 'var(--warning-border)'}`,
                  borderRadius: 8, padding: '7px 12px', fontSize: 13,
                }}>
                  <span style={{ fontWeight: 600, color: 'var(--text)' }}>{c.name}</span>
                  <span style={{
                    color: q ? 'var(--error)' : 'var(--warning)', marginLeft: 8, fontSize: 12,
                  }}>
                    {q
                      ? `quarantined · ${c.scrape_error_count} failures`
                      : `stalled · ${c.consecutive_empty_scrapes ?? 0} empty runs`}
                  </span>
                </div>
              )
            })}
          </div>
        </div>
      )}

      {/* Error companies */}
      {errCompanies.length > 0 && (
        <div style={{ marginBottom: 24 }}>
          <h3 style={{ fontSize: 14, fontWeight: 700, margin: '0 0 10px', color: 'var(--error)' }}>
            Companies with Errors
          </h3>
          <div style={{ display: 'flex', flexWrap: 'wrap', gap: 8 }}>
            {errCompanies.map((c) => (
              <div key={c.id} style={{
                background: 'var(--danger-light)', border: '1px solid var(--danger-border)',
                borderRadius: 8, padding: '7px 12px', fontSize: 13,
              }}>
                <span style={{ fontWeight: 600, color: 'var(--text)' }}>{c.name}</span>
                <span style={{ color: 'var(--error)', marginLeft: 8, fontSize: 12 }}>
                  {c.scrape_error_count} error{c.scrape_error_count !== 1 ? 's' : ''}
                </span>
              </div>
            ))}
          </div>
        </div>
      )}

      {/* All auto-connected companies (httpx cloud + curl_cffi/browser runners) */}
      <h3 style={{ fontSize: 14, fontWeight: 700, margin: '0 0 10px', color: 'var(--text)' }}>
        Auto-Connected Companies ({companies.filter(c => c.auto_connected ?? c.enabled).length})
      </h3>
      <div style={{
        display: 'grid',
        gridTemplateColumns: 'repeat(auto-fill, minmax(200px, 1fr))',
        gap: 6,
      }}>
        {companies.filter(c => c.auto_connected ?? c.enabled).map((c) => {
          // A source is live when it is PRODUCING postings in the current
          // snapshot. Keying this off last_scraped_at showed every company grey,
          // because the scrape now runs against a scratch database that has no
          // company table to stamp — the jobs themselves are the real evidence.
          const live = (c.total_active_jobs ?? 0) > 0
          const erroring = (c.scrape_error_count ?? 0) > 0
          return (
            <div key={c.id} style={{
              background: 'var(--surface)', border: '1px solid var(--border)',
              borderRadius: 8, padding: '8px 12px',
              display: 'flex', justifyContent: 'space-between', alignItems: 'center',
            }}>
              <div style={{ minWidth: 0 }}>
                <div style={{ fontWeight: 500, fontSize: 13, color: 'var(--text)',
                  overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>
                  {c.name}
                </div>
                <div style={{ fontSize: 11, color: 'var(--text-muted)' }}>
                  {c.ats_platform}{c.engine ? ` · ${c.engine}` : ''}
                </div>
              </div>
              <div style={{ display: 'flex', alignItems: 'center', gap: 8, flexShrink: 0 }}>
                {live && (
                  <span style={{ fontSize: 11, fontWeight: 700, color: 'var(--text-secondary)' }}>
                    {c.viewable_jobs ?? 0}
                  </span>
                )}
                <span
                  style={{
                    width: 9, height: 9, borderRadius: '50%', flexShrink: 0,
                    background: erroring ? 'var(--danger)' : live ? 'var(--success)' : 'var(--text-faint)',
                    boxShadow: live && !erroring ? '0 0 0 3px rgba(34,197,94,0.18)' : 'none',
                  }}
                  title={
                    erroring ? `${c.scrape_error_count} scrape error(s)`
                    : live ? `Live — ${c.viewable_jobs ?? 0} US roles from ${c.total_active_jobs} postings`
                    : 'Connected, but no live postings right now'
                  }
                />
              </div>
            </div>
          )
        })}
      </div>
    </div>
  )
}

const td: React.CSSProperties = { padding: '8px 12px', color: 'var(--text)' }
