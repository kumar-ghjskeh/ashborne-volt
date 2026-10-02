import { safeUrl } from '../lib/utils'
import { useEffect, useRef, useState } from 'react'
import { loadCorpus, loadDetail } from '../lib/corpus'
import { siblingsOf } from '../lib/query'
import { getJobMatchDetail } from '../lib/resume'
import * as userState from '../lib/userState'
import { fmtDateLong, freshness } from '../lib/datetime'
import type { Job, JobMatch } from '../lib/types'
import { Icon } from './Icon'
import { InterviewPrepAI } from './InterviewPrepAI'
import { ResumeStudio } from './ResumeStudio'
import { ScoreGauge, matchColor, priorityColor } from './ScoreGauge'

interface Props {
  job: Job | null
  onClose: () => void
  onUpdate: () => void
  /** Open another job (used by the Similar-jobs list). */
  onSelectJob?: (job: Job) => void
  /** When rendered as a full-screen sheet on mobile: fill the sheet, no sticky/border. */
  mobile?: boolean
}

type DetailTab = 'overview' | 'match' | 'score' | 'description' | 'tailor' | 'similar' | 'source' | 'notes'

const TIER_STYLE: Record<string, string> = {
  'Safe to Add': 'pill-success',
  'Reword Only': 'pill-primary',
  'Learn First': 'pill-warning',
  'Do Not Add': 'pill-danger',
}

const fieldLabel: React.CSSProperties = {
  fontSize: 11, fontWeight: 700, color: 'var(--text-secondary)',
  textTransform: 'uppercase', letterSpacing: '0.04em', display: 'block', marginBottom: 6,
}
const fieldInput: React.CSSProperties = {
  width: '100%', border: '1px solid var(--border)', borderRadius: 8,
  padding: '8px 12px', fontSize: 13, background: 'var(--surface)',
  color: 'var(--text-primary)', outline: 'none',
}

function scoreColor(score: number): string {
  // Semantic tokens, not fixed hex: these are drawn on --surface, which inverts
  // with the theme. The old values were tuned for the light page only and went
  // nearly unreadable against the dark one.
  if (score >= 85) return 'var(--success)'
  if (score >= 75) return 'var(--primary)'
  if (score >= 65) return 'var(--teal)'
  if (score >= 50) return 'var(--accent-gold)'
  return 'var(--text-muted)'
}

function MetaRow({ label, value }: { label: string; value: React.ReactNode }) {
  return (
    <div style={{
      display: 'flex', flexDirection: 'column',
      background: 'var(--bg)', borderRadius: 8, padding: '10px 12px',
    }}>
      <span style={{
        fontSize: 11, color: 'var(--text-muted)', fontWeight: 600,
        textTransform: 'uppercase', letterSpacing: '0.04em', marginBottom: 3,
      }}>
        {label}
      </span>
      <span style={{ fontSize: 13, color: 'var(--text)', fontWeight: 500, wordBreak: 'break-all' }}>
        {value || '—'}
      </span>
    </div>
  )
}

// New Grad Fit colour — gold only for a true Excellent (90+).
function ngColor(s: number) {
  if (s >= 90) return 'var(--accent-gold)'
  if (s >= 75) return 'var(--primary)'
  if (s >= 60) return 'var(--teal)'
  if (s >= 46) return 'var(--warning)'
  return 'var(--text-tertiary)'
}

function ScoreBar({ score, max = 100 }: { score: number; max?: number }) {
  const pct = Math.min(100, (score / max) * 100)
  const color = scoreColor(score)
  return (
    <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
      <div style={{
        flex: 1, height: 6, background: 'var(--border)', borderRadius: 3, overflow: 'hidden',
      }}>
        <div style={{
          width: `${pct}%`, height: '100%', background: color,
          borderRadius: 3, transition: 'width 0.4s ease',
        }} />
      </div>
      <span style={{ fontSize: 12, fontWeight: 600, color, minWidth: 28, textAlign: 'right' }}>
        {score}
      </span>
    </div>
  )
}

const fmt = (d: string | null) => fmtDateLong(d)

function MiniStat({ label, value, color }: { label: string; value: string; color: string }) {
  return (
    <div style={{ flex: '1 1 90px', background: 'var(--surface-muted)', borderRadius: 8, padding: '9px 12px', minWidth: 0 }}>
      <div style={{ fontSize: 18, fontWeight: 800, color, lineHeight: 1 }}>{value}</div>
      <div style={{ fontSize: 10.5, color: 'var(--text-secondary)', fontWeight: 600, marginTop: 3, textTransform: 'uppercase', letterSpacing: '0.04em' }}>{label}</div>
    </div>
  )
}

export function JobDetailsPanel({ job, onClose, onUpdate, onSelectJob, mobile = false }: Props) {
  const [detailTab, setDetailTab] = useState<DetailTab>('overview')
  const [notes, setNotes] = useState('')
  const [appStatus, setAppStatus] = useState('')
  const [resumeUsed, setResumeUsed] = useState('')
  const [followUp, setFollowUp] = useState('')
  const [confirmId, setConfirmId] = useState('')
  const [recruiter, setRecruiter] = useState('')
  const [saving, setSaving] = useState(false)
  const [copied, setCopied] = useState(false)
  const [matchData, setMatchData] = useState<JobMatch | null>(null)
  const [matchLoading, setMatchLoading] = useState(false)
  const [similar, setSimilar] = useState<Job[]>([])
  const [similarLoading, setSimilarLoading] = useState(false)
  // Full description is fetched on demand (list rows omit it to cut DB egress).
  const [fullText, setFullText] = useState<string>('')
  const [siblings, setSiblings] = useState<{ id: number; location: string; state: string; apply_url: string; remote_status: string }[]>([])
  // Draggable panel width (desktop). Persisted so it sticks across sessions.
  const [panelWidth, setPanelWidth] = useState<number>(() => {
    const v = Number(localStorage.getItem('volt-panel-width'))
    return v >= 320 && v <= 1000 ? v : 384
  })
  const widthRef = useRef(panelWidth)
  const [resizeHover, setResizeHover] = useState(false)

  function startResize(e: React.MouseEvent) {
    e.preventDefault()
    const startX = e.clientX
    const startW = widthRef.current
    const onMove = (ev: MouseEvent) => {
      const max = Math.min(1000, window.innerWidth - 460)
      const w = Math.min(Math.max(startW + (startX - ev.clientX), 320), max)
      widthRef.current = w
      setPanelWidth(w)
    }
    const onUp = () => {
      window.removeEventListener('mousemove', onMove)
      window.removeEventListener('mouseup', onUp)
      document.body.style.userSelect = ''
      document.body.style.cursor = ''
      localStorage.setItem('volt-panel-width', String(Math.round(widthRef.current)))
    }
    window.addEventListener('mousemove', onMove)
    window.addEventListener('mouseup', onUp)
    document.body.style.userSelect = 'none'
    document.body.style.cursor = 'col-resize'
  }

  useEffect(() => {
    if (!job) { setMatchData(null); return }
    let cancelled = false
    setMatchLoading(true); setMatchData(null)
    getJobMatchDetail(job)
      .then((m) => { if (!cancelled) setMatchData(m as unknown as JobMatch | null) })
      .catch(() => { if (!cancelled) setMatchData(null) })
      .finally(() => { if (!cancelled) setMatchLoading(false) })
    return () => { cancelled = true }
  }, [job?.id]) // eslint-disable-line react-hooks/exhaustive-deps

  // Sibling requisitions for the same role at other sites. The list collapses
  // these into one card, so this is where they stay reachable.
  useEffect(() => {
    if (!job) { setSiblings([]); return }
    let cancelled = false
    setSiblings([])
    if ((job.group_count ?? 1) > 1) {
      loadCorpus()
        .then((c) => {
          if (cancelled) return
          setSiblings(siblingsOf(c.jobs, job).map((x) => ({
            id: x.id, location: x.location || '', state: x.state || '',
            apply_url: x.apply_url, remote_status: x.remote_status || '',
          })))
        })
        .catch(() => { if (!cancelled) setSiblings([]) })
    }
    return () => { cancelled = true }
  }, [job?.id]) // eslint-disable-line react-hooks/exhaustive-deps

  useEffect(() => {
    if (!job) { setSimilar([]); return }
    let cancelled = false
    setSimilarLoading(true); setSimilar([])
    // "More like this": overlapping skills and role category, ranked by overlap.
    // Computed over the corpus already in memory.
    loadCorpus()
      .then((c) => {
        if (cancelled) return
        const mine = new Set(String(job.job_skills || '').split(',').map((x) => x.trim()).filter(Boolean))
        setSimilar(
          c.jobs
            .filter((x) => x.id !== job.id && x.is_usa && !x.is_software_only)
            .map((x) => ({
              x,
              score: String(x.job_skills || '').split(',').filter((k) => mine.has(k.trim())).length
                + (x.role_category === job.role_category ? 2 : 0),
            }))
            .filter((r) => r.score > 0)
            .sort((a, b) => b.score - a.score || (b.x.new_grad_fit ?? 0) - (a.x.new_grad_fit ?? 0))
            .slice(0, 6)
            .map((r) => r.x),
        )
      })
      .catch(() => { if (!cancelled) setSimilar([]) })
      .finally(() => { if (!cancelled) setSimilarLoading(false) })
    return () => { cancelled = true }
  }, [job?.id]) // eslint-disable-line react-hooks/exhaustive-deps

  // Fetch the full job (incl. the heavy description) only when a job is opened —
  // list responses omit it. Seed from any text already on the list object.
  useEffect(() => {
    if (!job) { setFullText(''); return }
    let cancelled = false
    setFullText(job.cleaned_description || job.full_description_text || '')
    // Bodies are kept out of the corpus file so opening the app stays cheap;
    // they load once, lazily, the first time a posting is opened.
    loadDetail(job.id)
      .then((body) => {
        if (!cancelled && body) setFullText(body)
      })
      .catch(() => { /* keep the seed/snippet */ })
    return () => { cancelled = true }
  }, [job?.id]) // eslint-disable-line react-hooks/exhaustive-deps

  const [lastJobId, setLastJobId] = useState<number | null>(null)
  if (job && job.id !== lastJobId) {
    setLastJobId(job.id)
    setNotes(job.notes || '')
    setAppStatus(job.application_status || '')
    setResumeUsed(job.resume_version_used || '')
    setFollowUp(job.follow_up_date || '')
    setConfirmId(job.confirmation_id || '')
    setRecruiter(job.recruiter_contact || '')
    setDetailTab('overview')
  }

  if (!job) return null

  // Your marks and notes are yours, so they are stored in this browser keyed by
  // the posting's content fingerprint — which survives the corpus being rebuilt
  // by every scrape, unlike its row id.
  async function handleSetStatus(status: string) {
    if (job!.key) userState.setStatus(job!.key, status as userState.JobStatus)
    onUpdate()
  }

  async function handleSaveNotes() {
    setSaving(true)
    try {
      if (job!.key) {
        userState.patchMark(job!.key, {
          notes, resume_version_used: resumeUsed, follow_up_date: followUp,
          confirmation_id: confirmId, recruiter_contact: recruiter,
        })
      }
      onUpdate()
    } finally {
      setSaving(false)
    }
  }

  function handleCopyTitle() {
    navigator.clipboard.writeText(job!.job_title).then(() => {
      setCopied(true)
      setTimeout(() => setCopied(false), 2000)
    })
  }

  let scoreBreakdown: Record<string, number> = {}
  try {
    if (job.score_breakdown_json) scoreBreakdown = JSON.parse(job.score_breakdown_json)
  } catch { /* ignore */ }

  const keywords = job.matched_keywords
    ? job.matched_keywords.split(',').map((k) => k.trim())
        .filter((k) => k && !/^(usa|us|united states|priority-[a-d]|recent|fresh|new)$/i.test(k))
    : []

  const DETAIL_TABS: { id: DetailTab; label: string }[] = [
    { id: 'overview', label: 'Overview' },
    { id: 'match', label: 'Match' },
    { id: 'score', label: 'Score' },
    { id: 'description', label: 'Description' },
    { id: 'tailor', label: 'Tailor' },
    { id: 'similar', label: similar.length ? `Similar (${similar.length})` : 'Similar' },
    { id: 'source', label: 'Source' },
    { id: 'notes', label: 'Application' },
  ]

  const rootStyle: React.CSSProperties = mobile
    ? {
        width: '100%', flex: 1, minHeight: 0,
        background: 'var(--surface)',
        display: 'flex', flexDirection: 'column',
        overflow: 'hidden',
      }
    : {
        width: panelWidth, flexShrink: 0,
        background: 'var(--surface)',
        border: '1px solid var(--border)',
        borderRadius: 10,
        display: 'flex', flexDirection: 'column',
        position: 'sticky', top: 'calc(var(--nav-height) + 8px)',
        maxHeight: 'calc(100vh - var(--nav-height) - 24px)',
        overflow: 'hidden',
        alignSelf: 'flex-start',
        boxShadow: '0 4px 24px rgba(0,0,0,0.06)',
      }

  return (
    <aside style={rootStyle}>
      {/* Drag-to-resize handle on the panel's left edge (desktop only). */}
      {!mobile && (
        <div
          onMouseDown={startResize}
          onMouseEnter={() => setResizeHover(true)}
          onMouseLeave={() => setResizeHover(false)}
          title="Drag to resize"
          style={{
            position: 'absolute', left: 0, top: 0, bottom: 0, width: 10, zIndex: 6,
            cursor: 'col-resize', display: 'flex', alignItems: 'center', justifyContent: 'center',
          }}
        >
          <div style={{ width: 3, height: 44, borderRadius: 3, background: resizeHover ? 'var(--primary)' : 'transparent', transition: 'background 0.15s' }} />
        </div>
      )}
      {/* Panel header */}
      <div style={{
        padding: '16px 20px 12px',
        borderBottom: '1px solid var(--border)',
        flexShrink: 0,
      }}>
        <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start' }}>
          <div style={{ flex: 1, minWidth: 0, marginRight: 8 }}>
            <h3 style={{
              margin: '0 0 4px', fontSize: 15, fontWeight: 700,
              color: 'var(--text)', lineHeight: 1.3, wordBreak: 'break-word',
            }}>
              {job.job_title}
            </h3>
            <div style={{ fontSize: 13, color: 'var(--text-muted)' }}>
              {job.company} · {job.location || 'Location TBD'}
            </div>
          </div>
          <div style={{ display: 'flex', gap: 4, flexShrink: 0 }}>
            <button
              onClick={handleCopyTitle}
              title="Copy job title"
              style={{
                background: copied ? 'var(--success-light)' : 'var(--surface-sunken)',
                border: '1px solid var(--border)', borderRadius: 6,
                padding: '5px 9px', fontSize: 11, cursor: 'pointer', fontWeight: 600,
                color: copied ? 'var(--success)' : 'var(--text-muted)',
                whiteSpace: 'nowrap', display: 'inline-flex', alignItems: 'center', gap: 4,
              }}
            >
              <Icon name={copied ? 'check' : 'copy'} size={12} /> {copied ? 'Copied' : 'Copy'}
            </button>
            <button
              onClick={onClose}
              title="Close"
              style={{
                background: 'var(--surface-sunken)', border: '1px solid var(--border)',
                borderRadius: 6, width: 28, height: 28, cursor: 'pointer', color: 'var(--text-muted)',
                display: 'flex', alignItems: 'center', justifyContent: 'center',
              }}
            ><Icon name="x" size={15} /></button>
          </div>
        </div>

        {/* Multi-score summary — New Grad Fit (primary), Resume Match, Experienced Fit */}
        <div style={{ marginTop: 12 }}>
          <div style={{ display: 'flex', gap: 14, alignItems: 'center', flexWrap: 'wrap' }}>
            <ScoreGauge value={job.new_grad_fit} label="New Grad Fit" color={ngColor(job.new_grad_fit)} />
            {matchData
              ? <ScoreGauge value={matchData.resume_match} label="Resume Match" color={matchColor(matchData.resume_match)} suffix="%" />
              : (!matchLoading && (
                  <div style={{ fontSize: 11, color: 'var(--text-tertiary)', maxWidth: 120, lineHeight: 1.4 }}>
                    Upload a resume in <strong style={{ color: 'var(--primary)' }}>Resume Matches</strong> for your match.
                  </div>
                ))}
            <ScoreGauge value={job.experienced_fit} label="Experienced Fit" color="var(--text-secondary)" />
          </div>
          {job.overall_recommendation && (
            <div style={{ marginTop: 11 }}>
              <span className="pill" style={{
                background: `color-mix(in srgb, ${ngColor(job.new_grad_fit)} 14%, transparent)`,
                color: ngColor(job.new_grad_fit), border: `1px solid ${ngColor(job.new_grad_fit)}`,
                fontWeight: 800, fontSize: 12, padding: '4px 10px',
              }}>
                {job.overall_recommendation}
              </span>
            </div>
          )}
          <div style={{ display: 'flex', gap: 6, marginTop: 12, flexWrap: 'wrap' }}>
            {matchData && (
              <span className={`pill ${matchData.apply_priority === 'High' ? 'pill-gold' : matchData.apply_priority === 'Medium' ? 'pill-primary' : 'pill-neutral'}`} style={{ fontWeight: 700 }}>
                <Icon name="bolt" size={11} /> {matchData.apply_priority} priority
              </span>
            )}
            {(job.is_entry_level || job.is_candidate_friendly) && <span className="pill pill-teal">Candidate Friendly</span>}
            {job.is_remote_usa && <span className="pill pill-success">Remote USA</span>}
            {job.sponsors_h1b === true && <span className="pill pill-teal"><Icon name="passport" size={11} /> Sponsors H1B</span>}
            {job.sponsors_h1b === false && <span className="pill pill-warning"><Icon name="passport" size={11} /> No H1B sponsorship</span>}
            {job.eligibility_risk === 'high' && <span className="pill pill-danger"><Icon name="shield" size={11} /> Citizenship/Clearance</span>}
            {job.eligibility_risk === 'medium' && <span className="pill pill-warning"><Icon name="shield" size={11} /> Eligibility — review</span>}
          </div>
        </div>

        {/* Action buttons */}
        <div style={{ display: 'flex', gap: 6, marginTop: 12, flexWrap: 'wrap' }}>
          <a
            href={safeUrl(job.safe_apply_url || job.apply_url)}
            target="_blank" rel="noopener noreferrer"
            className="btn btn-primary"
          >
            Apply Now <Icon name="external" size={14} color="var(--on-primary)" />
          </a>
          <button
            onClick={() => handleSetStatus(job.active_status === 'saved' ? 'active' : 'saved')}
            className="btn"
            style={{
              background: job.active_status === 'saved' ? 'var(--primary-light)' : 'var(--surface-sunken)',
              border: `1px solid ${job.active_status === 'saved' ? 'var(--primary-mid)' : 'var(--border)'}`,
              color: job.active_status === 'saved' ? 'var(--primary)' : 'var(--text-muted)',
            }}
          >
            <Icon name={job.active_status === 'saved' ? 'bookmarkFilled' : 'bookmark'} size={14} />
            {job.active_status === 'saved' ? 'Saved' : 'Save'}
          </button>
          <button
            onClick={() => handleSetStatus(job.active_status === 'applied' ? 'active' : 'applied')}
            className="btn"
            style={{
              background: job.active_status === 'applied' ? 'var(--success-light)' : 'var(--surface-sunken)',
              border: `1px solid ${job.active_status === 'applied' ? 'var(--success-border)' : 'var(--border)'}`,
              color: job.active_status === 'applied' ? 'var(--success)' : 'var(--text-muted)',
            }}
          >
            <Icon name="checkCircle" size={14} /> Applied
          </button>
          <button
            onClick={() => handleSetStatus('ignored')}
            className="btn btn-ghost"
            style={{ borderColor: 'var(--border)' }}
          >
            <Icon name="eyeOff" size={14} /> Ignore
          </button>
          <button
            onClick={() => setDetailTab('tailor')}
            className="btn"
            title="Tailor your résumé to this job"
            style={{
              background: detailTab === 'tailor' ? 'var(--primary)' : 'var(--primary-light)',
              border: `1px solid var(--primary-mid)`,
              color: detailTab === 'tailor' ? 'var(--on-primary)' : 'var(--primary)',
              fontWeight: 700,
            }}
          >
            <Icon name="sparkles" size={14} color={detailTab === 'tailor' ? 'var(--on-primary)' : 'var(--primary)'} /> Tailor Résumé
          </button>
        </div>
      </div>

      {/* Tabs */}
      <div style={{
        display: 'flex', borderBottom: '1px solid var(--border)',
        padding: '0 16px', flexShrink: 0, gap: 2,
        overflowX: 'auto',
      }}>
        {DETAIL_TABS.map(({ id, label }) => (
          <button
            key={id}
            onClick={() => setDetailTab(id)}
            style={{
              background: 'none', border: 'none',
              borderBottom: detailTab === id ? '2px solid var(--primary)' : '2px solid transparent',
              color: detailTab === id ? 'var(--primary)' : 'var(--text-muted)',
              padding: '8px 10px', cursor: 'pointer', fontSize: 12,
              fontWeight: detailTab === id ? 600 : 400,
              whiteSpace: 'nowrap',
            }}
          >
            {label}
          </button>
        ))}
      </div>

      {/* Scrollable content */}
      <div style={{ flex: 1, overflowY: 'auto', padding: '16px 20px' }}>

        {detailTab === 'overview' && (
          <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 8 }}>
            <MetaRow label="Company" value={job.company} />
            <MetaRow label="Priority" value={`${job.company_priority}-Tier`} />
            <MetaRow label="Role Category" value={job.role_category} />
            <MetaRow label="Experience" value={job.experience_level} />
            <MetaRow label="Work Mode" value={job.location_label || job.remote_status} />
            {siblings.length > 0 && (
              <div style={{ gridColumn: '1 / -1', marginTop: 2 }}>
                <div style={{ fontSize: 11, color: 'var(--text-tertiary)', marginBottom: 5 }}>
                  Also open at {siblings.length} other {siblings.length === 1 ? 'location' : 'locations'} — each is a
                  separate requisition with its own application
                </div>
                <div style={{ display: 'flex', flexWrap: 'wrap', gap: 6 }}>
                  {siblings.map((s) => (
                    <a
                      key={s.id}
                      href={safeUrl(s.apply_url)}
                      target="_blank"
                      rel="noopener noreferrer"
                      style={{
                        fontSize: 11.5, padding: '3px 9px', borderRadius: 999,
                        border: '1px solid var(--border)', background: 'var(--surface-muted)',
                        color: 'var(--text-secondary)', textDecoration: 'none',
                      }}
                    >
                      {s.location || 'Location TBD'}
                    </a>
                  ))}
                </div>
              </div>
            )}
            <MetaRow label="ATS Platform" value={job.ats_platform} />
            <MetaRow label="Source Reliability" value={job.source_reliability} />
            <MetaRow label="Seniority Confidence" value={job.seniority_confidence ? `${job.seniority_confidence}%` : '—'} />
            <MetaRow label="Classification Conf." value={job.classification_confidence ? `${job.classification_confidence}%` : '—'} />
            <MetaRow label="Data Quality" value={job.data_quality_score ? `${job.data_quality_score}%` : '—'} />
            <MetaRow label="Country" value={job.country || (job.is_usa ? 'USA' : '—')} />
            <MetaRow label="State" value={job.state} />
            {job.years_required_min !== null && (
              <MetaRow label="Years Required" value={
                job.years_required_max
                  ? `${job.years_required_min}–${job.years_required_max} yrs`
                  : `${job.years_required_min}+ yrs`
              } />
            )}
            <MetaRow label="Company Category" value={job.company_category} />
            <MetaRow label="First Seen" value={fmt(job.first_seen_at)} />
            <MetaRow label="Last Seen" value={fmt(job.last_seen_at)} />
            <MetaRow
              label="Posted Date"
              value={job.posted_date_known && job.posted_date
                ? fmt(job.posted_date)
                : 'Unknown — using first-seen'}
            />
            {job.saved_at && (
              <MetaRow label="Saved On" value={fmt(job.saved_at)} />
            )}
            {job.applied_at && (
              <MetaRow label="Applied On" value={fmt(job.applied_at)} />
            )}
          </div>
        )}

        {detailTab === 'match' && (
          <div>
            {matchLoading && (
              <div style={{ color: 'var(--text-tertiary)', fontSize: 12.5, textAlign: 'center', padding: '20px 0' }}>Computing your match…</div>
            )}
            {!matchLoading && !matchData && (
              <div style={{ textAlign: 'center', padding: '24px 8px' }}>
                <Icon name="fileText" size={30} color="var(--text-tertiary)" />
                <div style={{ fontSize: 14, fontWeight: 700, color: 'var(--text-primary)', marginTop: 12 }}>No resume uploaded</div>
                <div style={{ fontSize: 12.5, color: 'var(--text-secondary)', marginTop: 6, lineHeight: 1.6 }}>
                  Upload your resume in the <strong style={{ color: 'var(--primary)' }}>Resume Matches</strong> tab to see your match score, matched/missing skills, matching projects, safe tailoring advice, and interview prep for this job.
                </div>
              </div>
            )}
            {matchData && (
              <div style={{ display: 'flex', flexDirection: 'column', gap: 16 }}>
                <div style={{ display: 'flex', gap: 8 }}>
                  <MiniStat label="New Grad Fit" value={`${matchData.new_grad_fit ?? job.new_grad_fit}`} color={ngColor(matchData.new_grad_fit ?? job.new_grad_fit)} />
                  <MiniStat label="Resume Match" value={`${matchData.resume_match}%`} color={matchColor(matchData.resume_match)} />
                  <MiniStat label="Priority" value={matchData.apply_priority} color={priorityColor(matchData.apply_priority)} />
                </div>
                {(matchData.overall_recommendation || job.overall_recommendation) && (
                  <div style={{ fontSize: 12.5, color: 'var(--text-secondary)' }}>
                    Recommendation: <strong style={{ color: ngColor(matchData.new_grad_fit ?? job.new_grad_fit) }}>{matchData.overall_recommendation || job.overall_recommendation}</strong>
                  </div>
                )}

                {matchData.match_breakdown && (
                  <div>
                    <div className="section-header">How this match is scored</div>
                    <div style={{ display: 'flex', flexDirection: 'column', gap: 8 }}>
                      {([
                        ['Skills overlap', matchData.match_breakdown.skills],
                        ['Experience / level fit', matchData.match_breakdown.experience],
                        ['Project evidence', matchData.match_breakdown.projects],
                        ['Domain alignment', matchData.match_breakdown.domain],
                        ['Tool / protocol match', matchData.match_breakdown.tool_protocol ?? 0],
                      ] as [string, number][]).map(([label, val]) => (
                        <div key={label} style={{ display: 'flex', alignItems: 'center', gap: 10 }}>
                          <span style={{ fontSize: 11.5, color: 'var(--text-secondary)', width: 130, flexShrink: 0 }}>{label}</span>
                          <div style={{ flex: 1, height: 7, background: 'var(--surface-muted)', borderRadius: 4, overflow: 'hidden' }}>
                            <div style={{ width: `${val}%`, height: '100%', background: matchColor(val), borderRadius: 4, transition: 'width 0.4s ease' }} />
                          </div>
                          <span style={{ fontSize: 11.5, fontWeight: 700, color: matchColor(val), width: 30, textAlign: 'right' }}>{val}</span>
                        </div>
                      ))}
                    </div>
                  </div>
                )}

                <div style={{ background: 'var(--primary-light)', border: '1px solid var(--primary-mid)', borderRadius: 8, padding: '10px 12px' }}>
                  <div style={{ fontSize: 10.5, fontWeight: 700, color: 'var(--text-secondary)', textTransform: 'uppercase', letterSpacing: '0.05em' }}>Recommended resume version</div>
                  <div style={{ fontSize: 14, fontWeight: 700, color: 'var(--primary)', marginTop: 2 }}>{matchData.recommended_resume}</div>
                </div>

                {matchData.why_matches.length > 0 && (
                  <div>
                    <div className="section-header">Why this job matches</div>
                    <ul style={{ margin: 0, paddingLeft: 16, fontSize: 12.5, color: 'var(--text-secondary)', lineHeight: 1.7 }}>
                      {matchData.why_matches.map((w, i) => <li key={i}>{w}</li>)}
                    </ul>
                  </div>
                )}

                <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 12 }}>
                  <div>
                    <div className="section-header" style={{ color: 'var(--success)' }}>Matched · {matchData.matched_skills.length}</div>
                    <div style={{ display: 'flex', flexWrap: 'wrap', gap: 5 }}>
                      {matchData.matched_skills.length ? matchData.matched_skills.map((s) => (
                        <span key={s} className="pill pill-success"><Icon name="check" size={10} /> {s}</span>
                      )) : <span style={{ fontSize: 11.5, color: 'var(--text-tertiary)' }}>—</span>}
                    </div>
                  </div>
                  <div>
                    <div className="section-header" style={{ color: 'var(--warning)' }}>Missing · {matchData.missing_skills.length}</div>
                    <div style={{ display: 'flex', flexWrap: 'wrap', gap: 5 }}>
                      {matchData.missing_skills.length ? matchData.missing_skills.map((s) => (
                        <span key={s} className="pill pill-warning">{s}</span>
                      )) : <span style={{ fontSize: 11.5, color: 'var(--text-tertiary)' }}>none</span>}
                    </div>
                  </div>
                </div>

                {(matchData.matched_projects_detail?.length || matchData.matched_projects.length) > 0 && (
                  <div>
                    <div className="section-header">Your matching projects · what each one backs</div>
                    <div style={{ display: 'flex', flexDirection: 'column', gap: 6 }}>
                      {matchData.matched_projects_detail?.length ? (
                        matchData.matched_projects_detail.map((p, i) => (
                          <div key={i} style={{ background: 'var(--surface-muted)', borderRadius: 7, padding: '8px 11px' }}>
                            <div style={{ fontSize: 12.5, fontWeight: 700, color: 'var(--text-primary)', display: 'flex', gap: 7, alignItems: 'center' }}>
                              <Icon name="checkCircle" size={13} color="var(--success)" /> {p.title}
                            </div>
                            {p.backs.length > 0 && (
                              <div style={{ display: 'flex', gap: 5, flexWrap: 'wrap', marginTop: 6, paddingLeft: 20 }}>
                                <span style={{ fontSize: 11, color: 'var(--text-tertiary)' }}>Backs this role's</span>
                                {p.backs.map((b) => <span key={b} className="skill-chip" style={{ fontSize: 10.5 }}>{b}</span>)}
                              </div>
                            )}
                          </div>
                        ))
                      ) : (
                        matchData.matched_projects.map((p, i) => (
                          <div key={i} style={{ fontSize: 12, color: 'var(--text-secondary)', background: 'var(--surface-muted)', borderRadius: 6, padding: '7px 10px', display: 'flex', gap: 7, alignItems: 'flex-start' }}>
                            <Icon name="checkCircle" size={13} color="var(--success)" /> <span>{p}</span>
                          </div>
                        ))
                      )}
                    </div>
                  </div>
                )}

                {matchData.tailoring_suggestions.length > 0 && (
                  <div>
                    <div className="section-header">Safe resume tailoring</div>
                    <div style={{ display: 'flex', flexDirection: 'column', gap: 6 }}>
                      {matchData.tailoring_suggestions.map((s, i) => (
                        <div key={i} style={{ display: 'flex', gap: 8, alignItems: 'flex-start', background: 'var(--surface-muted)', borderRadius: 6, padding: '7px 10px' }}>
                          <span className={`pill ${TIER_STYLE[s.tier] || 'pill-neutral'}`} style={{ flexShrink: 0 }}>{s.tier}</span>
                          <div style={{ fontSize: 12, color: 'var(--text-secondary)', lineHeight: 1.5 }}>
                            <strong style={{ color: 'var(--text-primary)' }}>{s.skill}</strong> — {s.rationale}
                          </div>
                        </div>
                      ))}
                    </div>
                  </div>
                )}

                <div>
                  {matchData.interview_prep.company_focus && (
                    <div style={{ background: 'var(--primary-light)', border: '1px solid var(--primary-mid)', borderRadius: 8, padding: '9px 12px', marginBottom: 12, fontSize: 12, color: 'var(--primary)', lineHeight: 1.6 }}>
                      <strong>What {job.company} tends to test:</strong> {matchData.interview_prep.company_focus}
                    </div>
                  )}
                  {!!matchData.interview_prep.rounds?.length && (
                    <div style={{ marginBottom: 14 }}>
                      <div className="section-header">Likely interview rounds</div>
                      <div style={{ display: 'flex', flexDirection: 'column', gap: 7 }}>
                        {matchData.interview_prep.rounds!.map((r, i) => (
                          <div key={i} style={{ background: 'var(--surface-muted)', borderRadius: 7, padding: '8px 11px' }}>
                            <div style={{ fontSize: 12.5, fontWeight: 700, color: 'var(--text-primary)' }}>{r.name}</div>
                            <div style={{ fontSize: 11.5, color: 'var(--text-secondary)', marginTop: 2, lineHeight: 1.5 }}>{r.what}</div>
                          </div>
                        ))}
                      </div>
                    </div>
                  )}
                  <div className="section-header">Interview prep · likely technical topics</div>
                  <ul style={{ margin: 0, paddingLeft: 16, fontSize: 12.5, color: 'var(--text-secondary)', lineHeight: 1.7 }}>
                    {matchData.interview_prep.technical_topics.map((t, i) => <li key={i}>{t}</li>)}
                  </ul>
                  {matchData.interview_prep.resume_defense.length > 0 && (
                    <>
                      <div className="section-header" style={{ marginTop: 12 }}>Interview prep · defend your resume</div>
                      <ul style={{ margin: 0, paddingLeft: 16, fontSize: 12.5, color: 'var(--text-secondary)', lineHeight: 1.7 }}>
                        {matchData.interview_prep.resume_defense.map((t, i) => <li key={i}>{t}</li>)}
                      </ul>
                    </>
                  )}
                  <InterviewPrepAI job={job} />
                </div>
              </div>
            )}
          </div>
        )}

        {detailTab === 'score' && (
          <div>
            {/* Prominent verdict banner — the realistic, at-a-glance call. */}
            <div style={{
              background: `color-mix(in srgb, ${ngColor(job.new_grad_fit)} 12%, var(--surface))`,
              border: `1.5px solid ${ngColor(job.new_grad_fit)}`,
              borderRadius: 10, padding: '14px 16px', marginBottom: 16,
              display: 'flex', alignItems: 'center', gap: 13,
            }}>
              <div style={{
                width: 58, height: 58, borderRadius: '50%', flexShrink: 0,
                border: `3px solid ${ngColor(job.new_grad_fit)}`, background: 'var(--surface)',
                display: 'flex', flexDirection: 'column', alignItems: 'center', justifyContent: 'center',
              }}>
                <div style={{ fontSize: 20, fontWeight: 800, color: ngColor(job.new_grad_fit), lineHeight: 1 }}>{job.new_grad_fit}</div>
                <div style={{ fontSize: 7.5, fontWeight: 700, color: ngColor(job.new_grad_fit), letterSpacing: '0.03em', marginTop: 1 }}>NG FIT</div>
              </div>
              <div style={{ minWidth: 0 }}>
                <div style={{ fontSize: 15, fontWeight: 800, color: ngColor(job.new_grad_fit), lineHeight: 1.25 }}>
                  {job.overall_recommendation || 'Fit assessment'}
                </div>
                <div style={{ fontSize: 12, color: 'var(--text-secondary)', marginTop: 4, lineHeight: 1.5 }}>
                  {matchData
                    ? <><strong style={{ color: matchColor(matchData.resume_match) }}>{matchData.resume_match}%</strong> match for you · <strong style={{ color: priorityColor(matchData.apply_priority) }}>{matchData.apply_priority}</strong> apply priority · {job.experience_level}</>
                    : <>{job.experience_level} role · upload a résumé in <strong style={{ color: 'var(--primary)' }}>Resume Matches</strong> for your personalized match</>}
                </div>
              </div>
            </div>

            {/* Fit Score Breakdown */}
            <div style={{
              background: 'var(--primary-light)',
              border: '1px solid var(--primary-mid)',
              borderRadius: 8, padding: '10px 14px', marginBottom: 14,
              fontSize: 12, color: 'var(--primary)', lineHeight: 1.6,
            }}>
              <strong>Fit Score Breakdown</strong> — <strong>New Grad Fit</strong> is how
              realistic this role is for you; <strong>Resume Match</strong> is your skills
              overlap; <strong>Experienced Fit</strong> is how suited it is to an experienced
              candidate. USA location and eligibility are validation flags, not score boosters.
            </div>

            <div style={{ display: 'flex', gap: 8, marginBottom: 12, flexWrap: 'wrap' }}>
              <MiniStat label="New Grad Fit" value={`${job.new_grad_fit}`} color={ngColor(job.new_grad_fit)} />
              <MiniStat label="Experienced Fit" value={`${job.experienced_fit}`} color="var(--text-secondary)" />
              {matchData && <MiniStat label="Resume Match" value={`${matchData.resume_match}%`} color={matchColor(matchData.resume_match)} />}
            </div>
            {job.overall_recommendation && (
              <div style={{ marginBottom: 16 }}>
                <span className="pill" style={{
                  background: `color-mix(in srgb, ${ngColor(job.new_grad_fit)} 14%, transparent)`,
                  color: ngColor(job.new_grad_fit), border: `1px solid ${ngColor(job.new_grad_fit)}`,
                  fontWeight: 800, fontSize: 12, padding: '4px 10px',
                }}>{job.overall_recommendation}</span>
              </div>
            )}

            <div style={{ marginBottom: 16 }}>
              <div style={{
                fontSize: 11, fontWeight: 700, color: 'var(--text-muted)',
                textTransform: 'uppercase', letterSpacing: '0.04em', marginBottom: 6,
              }}>
                Role relevance · how clearly this is EE engineering work
              </div>
              <ScoreBar score={job.match_score} />
            </div>

            {keywords.length > 0 && (
              <div style={{ marginBottom: 16 }}>
                <div style={{
                  fontSize: 11, fontWeight: 700, color: 'var(--text-muted)',
                  textTransform: 'uppercase', letterSpacing: '0.04em', marginBottom: 8,
                }}>
                  Matched Keywords
                </div>
                <div style={{ display: 'flex', flexWrap: 'wrap', gap: 5 }}>
                  {keywords.map((kw) => (
                    <span key={kw} style={{
                      background: 'var(--primary-light)', color: 'var(--primary)',
                      fontSize: 12, padding: '3px 9px', borderRadius: 5, fontWeight: 500,
                    }}>
                      {kw}
                    </span>
                  ))}
                </div>
              </div>
            )}

            {Object.keys(scoreBreakdown).length > 0 ? (
              <div>
                <div style={{
                  fontSize: 11, fontWeight: 700, color: 'var(--text-muted)',
                  textTransform: 'uppercase', letterSpacing: '0.04em', marginBottom: 8,
                }}>
                  Score Breakdown
                </div>
                <div style={{ display: 'flex', flexDirection: 'column', gap: 6 }}>
                  {Object.entries(scoreBreakdown).map(([reason, pts]) => (
                    <div key={reason} style={{
                      display: 'flex', justifyContent: 'space-between',
                      alignItems: 'center', padding: '7px 12px',
                      background: (pts as number) > 0 ? 'var(--success-light)' : 'var(--danger-light)',
                      border: `1px solid ${(pts as number) > 0 ? 'var(--success-border)' : 'var(--danger-border)'}`,
                      borderRadius: 6,
                    }}>
                      <span style={{ fontSize: 12, color: 'var(--text)', flex: 1 }}>{reason}</span>
                      <span style={{
                        fontSize: 13, fontWeight: 700,
                        color: (pts as number) > 0 ? 'var(--success)' : 'var(--error)',
                        marginLeft: 8,
                      }}>
                        {(pts as number) > 0 ? `+${pts}` : pts}
                      </span>
                    </div>
                  ))}
                </div>
                {/* Total */}
                <div style={{
                  display: 'flex', justifyContent: 'space-between',
                  padding: '8px 12px', marginTop: 8,
                  background: `${scoreColor(job.match_score)}15`,
                  border: `1px solid ${scoreColor(job.match_score)}30`,
                  borderRadius: 6,
                }}>
                  <span style={{ fontSize: 13, fontWeight: 700, color: 'var(--text)' }}>
                    Final Score (capped 0–100)
                  </span>
                  <span style={{ fontSize: 15, fontWeight: 700, color: scoreColor(job.match_score) }}>
                    {job.match_score}
                  </span>
                </div>
              </div>
            ) : (
              <div style={{ color: 'var(--text-muted)', fontSize: 12, textAlign: 'center', padding: '16px 0' }}>
                Score breakdown not available for this job.
              </div>
            )}
          </div>
        )}

        {detailTab === 'description' && (
          <div>
            {job.relevance_reason && (
              <div style={{
                background: 'var(--primary-light)', border: '1px solid var(--primary-mid)',
                borderRadius: 8, padding: '8px 12px', marginBottom: 14,
                fontSize: 12, color: 'var(--primary)', lineHeight: 1.6,
              }}>
                <strong>Why this job:</strong> {job.relevance_reason}
              </div>
            )}
            {(fullText || job.description_snippet) ? (
              <div style={{
                fontSize: 13, color: 'var(--text)', lineHeight: 1.75,
                whiteSpace: 'pre-wrap', wordBreak: 'break-word',
              }}>
                {fullText || job.description_snippet}
              </div>
            ) : (
              <div style={{ color: 'var(--text-muted)', fontSize: 13, textAlign: 'center', paddingTop: 20 }}>
                No description available.
              </div>
            )}
          </div>
        )}

        {detailTab === 'tailor' && <ResumeStudio job={job} />}

        {detailTab === 'similar' && (
          <div>
            <div style={{ fontSize: 12.5, color: 'var(--text-secondary)', marginBottom: 12, lineHeight: 1.5 }}>
              Other open roles like <strong style={{ color: 'var(--text-primary)' }}>{job.job_title}</strong> — ranked by role, seniority, and skill overlap.
            </div>
            {similarLoading ? (
              <div style={{ color: 'var(--text-tertiary)', fontSize: 12.5, textAlign: 'center', padding: '20px 0' }}>Finding similar jobs…</div>
            ) : similar.length === 0 ? (
              <div style={{ color: 'var(--text-muted)', fontSize: 12.5, textAlign: 'center', padding: '20px 0' }}>No similar roles found right now.</div>
            ) : (
              <div style={{ display: 'flex', flexDirection: 'column', gap: 8 }}>
                {similar.map((s) => (
                  <button
                    key={s.id}
                    onClick={() => onSelectJob?.(s)}
                    style={{
                      textAlign: 'left', background: 'var(--surface-muted)', border: '1px solid var(--border)',
                      borderRadius: 8, padding: '10px 12px', cursor: 'pointer', width: '100%',
                      display: 'flex', alignItems: 'center', gap: 10,
                    }}
                  >
                    <div style={{
                      flexShrink: 0, width: 38, height: 38, borderRadius: '50%',
                      display: 'flex', alignItems: 'center', justifyContent: 'center',
                      background: `color-mix(in srgb, ${ngColor(s.new_grad_fit)} 16%, transparent)`,
                      color: ngColor(s.new_grad_fit), fontWeight: 800, fontSize: 13,
                    }}>{s.new_grad_fit}</div>
                    <div style={{ minWidth: 0, flex: 1 }}>
                      <div style={{ fontSize: 13, fontWeight: 600, color: 'var(--text-primary)', overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>
                        {s.job_title}
                      </div>
                      <div style={{ fontSize: 11.5, color: 'var(--text-secondary)', marginTop: 2, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>
                        {s.company} · {s.display_location || s.location || 'Location TBD'}
                      </div>
                    </div>
                    <Icon name="chevronRight" size={15} color="var(--text-tertiary)" />
                  </button>
                ))}
              </div>
            )}
          </div>
        )}

        {detailTab === 'source' && (() => {
          const fr = freshness(job.posted_date, job.posted_date_known, job.first_seen_at)
          const daysOpen = job.first_seen_at
            ? Math.max(0, Math.floor((Date.now() - new Date(job.first_seen_at).getTime()) / 86_400_000))
            : null
          const yrs = job.years_required_min != null
            ? (job.years_required_max != null && job.years_required_max !== job.years_required_min
                ? `${job.years_required_min}–${job.years_required_max} yrs`
                : `${job.years_required_min}+ yrs`)
            : 'Not specified'
          const h1b = job.sponsors_h1b === true ? 'Sponsors H1B'
            : job.sponsors_h1b === false ? 'No sponsorship' : 'Unknown'
          const chips: string[] = []
          if (job.is_entry_level) chips.push('Entry-level')
          if (job.is_candidate_friendly) chips.push('Candidate-friendly')
          ;(job.requirement_tags || '').split(',').map((t) => t.trim()).filter(Boolean)
            .forEach((t) => chips.push(t))
          const grid: React.CSSProperties = { display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 8 }
          return (
            <div style={{ display: 'flex', flexDirection: 'column', gap: 16 }}>
              {/* Posting timeline */}
              <div>
                <div className="section-header">Posting timeline</div>
                <div style={grid}>
                  <MetaRow label={fr.exact ? 'Posted' : 'Added (source gave no date)'} value={
                    <span>{fr.exact && job.posted_date ? fmt(job.posted_date) : fmt(job.first_seen_at)}
                      {fr.label && <span style={{ color: fr.isNew ? 'var(--success)' : 'var(--text-muted)', marginLeft: 6, fontWeight: 600, fontSize: 11.5 }}>· {fr.label}{!fr.exact && ' ~'}</span>}
                    </span>
                  } />
                  <MetaRow label="Actively listed" value={daysOpen != null ? `${daysOpen} day${daysOpen === 1 ? '' : 's'}` : '—'} />
                  <MetaRow label="First seen on radar" value={fmt(job.first_seen_at)} />
                  <MetaRow label="Last seen (still open)" value={fmt(job.last_seen_at)} />
                </div>
              </div>

              {/* Role details */}
              <div>
                <div className="section-header">Role details</div>
                <div style={grid}>
                  <MetaRow label="Role category" value={job.role_category} />
                  <MetaRow label="Experience level" value={
                    <span>{job.experience_level}{job.seniority_confidence ? <span style={{ color: 'var(--text-muted)', fontSize: 11.5 }}> · {job.seniority_confidence}% conf</span> : null}</span>
                  } />
                  <MetaRow label="Experience required" value={yrs} />
                  <MetaRow label="Role relevance" value={`${job.match_score}/100`} />
                </div>
                {chips.length > 0 && (
                  <div style={{ display: 'flex', flexWrap: 'wrap', gap: 5, marginTop: 8 }}>
                    {chips.map((c) => <span key={c} className="pill pill-neutral" style={{ fontSize: 11, textTransform: 'capitalize' }}>{c}</span>)}
                  </div>
                )}
                {job.relevance_reason && (
                  <div style={{ marginTop: 8, fontSize: 12, color: 'var(--text-secondary)', lineHeight: 1.6, background: 'var(--bg)', borderRadius: 8, padding: '9px 11px' }}>
                    <strong style={{ color: 'var(--text-primary)' }}>Why it's relevant:</strong> {job.relevance_reason}
                  </div>
                )}
              </div>

              {/* Eligibility & location */}
              <div>
                <div className="section-header">Eligibility &amp; location</div>
                <div style={grid}>
                  <MetaRow label="Location" value={job.display_location || job.location} />
                  <MetaRow label="Remote status" value={job.remote_status} />
                  <MetaRow label="H1B sponsorship" value={
                    <span style={{ color: job.sponsors_h1b === true ? 'var(--success)' : job.sponsors_h1b === false ? 'var(--warning)' : 'var(--text)', fontWeight: 600 }}>{h1b}</span>
                  } />
                  <MetaRow label="Eligibility risk" value={
                    <span style={{ color: job.eligibility_risk === 'high' ? 'var(--danger)' : job.eligibility_risk === 'medium' ? 'var(--warning)' : 'var(--success)', fontWeight: 600, textTransform: 'capitalize' }}>{job.eligibility_risk || 'low'}</span>
                  } />
                </div>
                {job.eligibility_terms && (
                  <div style={{ marginTop: 8, fontSize: 11.5, color: 'var(--text-tertiary)', lineHeight: 1.5 }}>
                    Flags: {job.eligibility_terms}
                  </div>
                )}
              </div>

              {/* Company */}
              <div>
                <div className="section-header">Company</div>
                <div style={grid}>
                  <MetaRow label="Company" value={job.company} />
                  <MetaRow label="Tier" value={`${job.company_priority}-Tier`} />
                  <MetaRow label="Category" value={job.company_category} />
                  <MetaRow label="Data quality" value={job.data_quality_score ? `${job.data_quality_score}/100` : '—'} />
                </div>
              </div>

              {/* Trust & provenance */}
              <div>
                <div className="section-header">Source &amp; provenance</div>
                <div style={grid}>
                  <MetaRow label="ATS platform" value={job.ats_platform} />
                  <MetaRow label="Source reliability" value={job.source_reliability} />
                  <MetaRow label="Classification conf." value={job.classification_confidence ? `${job.classification_confidence}%` : '—'} />
                  <MetaRow label="Location confidence" value={job.location_confidence > 0 ? `${Math.round(job.location_confidence * 100)}%` : '—'} />
                  <MetaRow label="Apply link status" value={
                    <span style={{ color: job.apply_url_status === 'ok' ? 'var(--success)' : 'var(--warning)', fontWeight: 600 }}>
                      {job.apply_url_status || '—'}{job.apply_url_reason ? <span style={{ color: 'var(--text-muted)', fontWeight: 400 }}> · {job.apply_url_reason}</span> : null}
                    </span>
                  } />
                  <MetaRow label="Company job ID" value={job.job_id_from_company || String(job.id)} />
                </div>
                <div style={{ display: 'flex', flexDirection: 'column', gap: 8, marginTop: 8 }}>
                  <div>
                    <div style={{ fontSize: 11, fontWeight: 700, color: 'var(--text-muted)', textTransform: 'uppercase', letterSpacing: '0.04em', marginBottom: 4 }}>Apply URL</div>
                    <a href={safeUrl(job.safe_apply_url || job.apply_url)} target="_blank" rel="noopener noreferrer" style={{ fontSize: 11, color: 'var(--primary)', wordBreak: 'break-all', display: 'block', lineHeight: 1.5 }}>{job.safe_apply_url || job.apply_url || '—'}</a>
                  </div>
                  {job.source_url && (
                    <div>
                      <div style={{ fontSize: 11, fontWeight: 700, color: 'var(--text-muted)', textTransform: 'uppercase', letterSpacing: '0.04em', marginBottom: 4 }}>Source URL</div>
                      <a href={safeUrl(job.source_url)} target="_blank" rel="noopener noreferrer" style={{ fontSize: 11, color: 'var(--primary)', wordBreak: 'break-all' }}>{job.source_url}</a>
                    </div>
                  )}
                </div>
              </div>
            </div>
          )
        })()}

        {detailTab === 'notes' && (
          <div style={{ display: 'flex', flexDirection: 'column', gap: 14 }}>
            <div>
              <label style={fieldLabel}>Application Stage</label>
              <select value={appStatus} onChange={(e) => setAppStatus(e.target.value)} style={fieldInput}>
                <option value="">— Not set —</option>
                {['Saved', 'Applied', 'Assessment', 'Interview', 'Rejected', 'Offer', 'Archived', 'Ignored'].map((s) => (
                  <option key={s} value={s}>{s}</option>
                ))}
              </select>
            </div>
            <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 10 }}>
              <div>
                <label style={fieldLabel}>Resume Used</label>
                <input value={resumeUsed} onChange={(e) => setResumeUsed(e.target.value)} placeholder="e.g. Power Systems v3" style={fieldInput} />
              </div>
              <div>
                <label style={fieldLabel}>Follow-up Date</label>
                <input type="date" value={followUp} onChange={(e) => setFollowUp(e.target.value)} style={fieldInput} />
              </div>
              <div>
                <label style={fieldLabel}>Confirmation ID</label>
                <input value={confirmId} onChange={(e) => setConfirmId(e.target.value)} placeholder="Req / app ID" style={fieldInput} />
              </div>
              <div>
                <label style={fieldLabel}>Recruiter Contact</label>
                <input value={recruiter} onChange={(e) => setRecruiter(e.target.value)} placeholder="Name / email" style={fieldInput} />
              </div>
            </div>

            <div>
              <label style={{
                fontSize: 11, fontWeight: 700, color: 'var(--text-muted)',
                textTransform: 'uppercase', letterSpacing: '0.04em',
                display: 'block', marginBottom: 6,
              }}>
                Personal Notes
              </label>
              <textarea
                value={notes}
                onChange={(e) => setNotes(e.target.value)}
                rows={5}
                placeholder="Add notes about this job, follow-ups, contacts..."
                style={{
                  width: '100%', border: '1px solid var(--border)',
                  borderRadius: 8, padding: '8px 12px', fontSize: 13,
                  background: 'var(--surface)', color: 'var(--text)',
                  outline: 'none', resize: 'vertical', fontFamily: 'inherit',
                }}
              />
            </div>

            <button
              onClick={handleSaveNotes}
              disabled={saving}
              style={{
                background: 'var(--primary)', color: 'var(--on-primary)',
                border: 'none', borderRadius: 8, padding: '9px 20px',
                fontSize: 13, fontWeight: 600,
                cursor: saving ? 'not-allowed' : 'pointer',
                opacity: saving ? 0.7 : 1, alignSelf: 'flex-start',
              }}
            >
              {saving ? 'Saving...' : 'Save Notes'}
            </button>
          </div>
        )}
      </div>
    </aside>
  )
}
