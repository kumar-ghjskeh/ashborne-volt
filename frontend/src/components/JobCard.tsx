import { safeUrl } from '../lib/utils'
import type { Job } from '../lib/types'
import { Icon } from './Icon'
import { matchColor } from './ScoreGauge'
import { CompanyLogo } from './CompanyLogo'
import { freshness } from '../lib/datetime'

interface Props {
  job: Job
  selected: boolean
  onClick: () => void
  onQuickAction: (action: 'saved' | 'applied' | 'ignored') => void
  extraLocations?: string[]
  resumeMatch?: number
  /** Active Resume-Matches sort. When 'resume_match', the headline ring shows the
   *  Resume Match % so the dominant number matches the list order. */
  ringMetric?: string
}

// New Grad Fit ring colour — gold only for a true Excellent (90+) fit.
function ngColor(s: number) {
  if (s >= 90) return 'var(--accent-gold)'
  if (s >= 75) return 'var(--primary)'
  if (s >= 60) return 'var(--teal)'
  if (s >= 46) return 'var(--warning)'
  return 'var(--text-tertiary)'
}
function expPill(level: string): string {
  switch (level) {
    case 'New Grad': return 'pill-success'
    case 'Entry Level': case 'Junior': return 'pill-teal'
    case 'Associate': case '0-3 Years': case 'Candidate Friendly': return 'pill-primary'
    case 'Mid-Level': return 'pill-neutral'
    case 'Senior': case 'Staff': case 'Principal': case 'Lead': case 'Manager': return 'pill-danger'
    default: return 'pill-neutral'
  }
}
function locationPill(label: string): string {
  if (label === 'Remote - USA') return 'pill-success'
  if (label === 'Hybrid') return 'pill-warning'
  if (label === 'Multi-location USA') return 'pill-primary'
  return 'pill-neutral'
}
const isNew = (d: string) => Date.now() - new Date(d).getTime() < 24 * 60 * 60 * 1000

export function JobCard({ job, selected, onClick, onQuickAction, extraLocations = [], resumeMatch, ringMetric }: Props) {
  const fresh = isNew(job.first_seen_at)
  // Honest freshness: real posted date when known ("Posted 3d ago"), else when we
  // first saw it ("Added 5d ago"). Drives the relative line at the card footer.
  const fr = freshness(job.posted_date, job.posted_date_known, job.first_seen_at)
  const saved = job.active_status === 'saved'
  const rm = resumeMatch ?? job.resume_match
  const ng = job.new_grad_fit ?? 0
  const ngLabel = job.new_grad_fit_label || ''
  // Headline ring: normally New Grad Fit. But when the list is sorted by Best
  // Resume Match, the ring shows Resume Match so the dominant number matches the
  // order (otherwise a card with a lower NG-fit but higher resume-match looks
  // out of order). The other metric stays visible as the small pill.
  const ringIsRm = ringMetric === 'resume_match' && rm !== undefined && rm !== null
  const ringVal = ringIsRm ? (rm as number) : ng
  const ringColor = ringIsRm ? matchColor(rm as number) : ngColor(ng)
  const ringLabel = ringIsRm ? 'Match' : ngLabel
  const ringTitle = ringIsRm
    ? `Resume Match ${rm}%`
    : `New Grad Fit ${ng} — ${job.overall_recommendation || ngLabel}`
  const risk = job.eligibility_risk
  const h1b = job.sponsors_h1b
  // Clearance is already shown by the eligibility pill above.
  const reqTags = (job.requirement_tags || '').split(',').map((t) => t.trim())
    .filter((t) => t && !(t === 'Clearance' && risk === 'high'))

  // Drop scoring artifacts (USA is the default, priority/recency aren't skills) so
  // the chips read as real skills/protocols only.
  const NOISE_KW = /^(usa|us|united states|priority-[a-d]|recent|fresh|new)$/i
  const keywords = job.matched_keywords
    ? job.matched_keywords.split(',').map((k) => k.trim()).filter((k) => k && !NOISE_KW.test(k)).slice(0, 6)
    : []
  // List rows no longer carry the full description (egress reduction) — use the
  // small snippet for the card preview; the detail panel fetches the full text.
  const snippet = job.description_snippet || ''

  return (
    <div className={`job-card${selected ? ' selected' : ''}`} onClick={onClick}>
      {/* Top row */}
      <div style={{ display: 'flex', gap: 13, alignItems: 'flex-start' }}>
        <CompanyLogo company={job.company} size={46} radius={10} />

        <div style={{ flex: 1, minWidth: 0 }}>
          <div style={{ display: 'flex', alignItems: 'baseline', gap: 7 }}>
            <div style={{ fontSize: 14.5, fontWeight: 700, color: 'var(--text-primary)', lineHeight: 1.35, flex: 1, minWidth: 0 }}>
              {job.job_title}
            </div>
            {fresh && <span className="pill pill-primary" style={{ fontWeight: 800, letterSpacing: '0.05em', fontSize: 10 }}>NEW</span>}
          </div>
          <div style={{ display: 'flex', alignItems: 'center', gap: 7, marginTop: 4, flexWrap: 'wrap' }}>
            <span style={{ fontSize: 13, color: 'var(--text-primary)', fontWeight: 600 }}>{job.company}</span>
            <span className={`badge tier-${(job.company_priority || 'c').toLowerCase()}`}>{job.company_priority}</span>
            {ringIsRm ? (
              <span className="pill" style={{ background: 'transparent', color: ngColor(ng), border: `1px solid ${ngColor(ng)}`, fontWeight: 700, fontSize: 10.5 }}>
                <Icon name="target" size={10} color={ngColor(ng)} /> NG Fit {ng}
              </span>
            ) : rm !== undefined && rm !== null && (
              <span className="pill" style={{ background: 'transparent', color: matchColor(rm), border: `1px solid ${matchColor(rm)}`, fontWeight: 700, fontSize: 10.5 }}>
                <Icon name="target" size={10} color={matchColor(rm)} /> Resume {rm}%
              </span>
            )}
            {job.ats_platform && <span style={{ fontSize: 11.5, color: 'var(--text-tertiary)' }}>via {job.ats_platform}</span>}
          </div>
        </div>

        {/* Headline score ring — New Grad Fit, or Resume Match when sorted by it */}
        <div
          title={ringTitle}
          style={{
            width: 54, height: 54, borderRadius: '50%', background: 'var(--surface-muted)',
            border: `2.5px solid ${ringColor}`, display: 'flex', flexDirection: 'column',
            alignItems: 'center', justifyContent: 'center', flexShrink: 0, textAlign: 'center',
          }}>
          <div style={{ fontSize: 16, fontWeight: 800, color: ringColor, lineHeight: 1 }}>{ringIsRm ? `${ringVal}%` : ringVal}</div>
          <div style={{ fontSize: 7.5, color: ringColor, fontWeight: 700, letterSpacing: '0.01em', marginTop: 1, padding: '0 2px' }}>
            {ringLabel}
          </div>
        </div>
      </div>

      {/* Meta badges */}
      <div style={{ display: 'flex', gap: 7, marginTop: 11, flexWrap: 'wrap', alignItems: 'center' }}>
        {job.location && (
          <span style={{ fontSize: 12, color: 'var(--text-secondary)', display: 'flex', alignItems: 'center', gap: 4 }}>
            <Icon name="mapPin" size={13} color="var(--text-tertiary)" /> {job.display_location || job.location}
            {(() => {
              // Prefer the server's group_count: it counts every sibling req in
              // the whole result set, while extraLocations only ever saw the
              // current page. Falls back to the page-local value.
              const extra = Math.max((job.group_count ?? 1) - 1, extraLocations.length)
              return extra > 0 ? (
                <span style={{ color: 'var(--primary)', fontWeight: 600 }}>
                  &nbsp;+{extra} {extra === 1 ? 'location' : 'locations'}
                </span>
              ) : null
            })()}
          </span>
        )}
        {job.location_label && job.location_label !== 'Location Unknown' ? (
          <span className={`pill ${locationPill(job.location_label)}`}>{job.location_label}</span>
        ) : job.remote_status && job.remote_status !== 'Unknown' ? (
          <span className={`pill ${locationPill(job.remote_status)}`}>{job.remote_status}</span>
        ) : null}
        {job.experience_level && job.experience_level !== 'Unknown' && (
          <span className={`pill ${expPill(job.experience_level)}`}>{job.experience_level}</span>
        )}
        {job.role_category && job.role_category !== 'Unknown' && (
          <span className="pill pill-neutral">{job.role_category}</span>
        )}
        {risk === 'high' && <span className="pill pill-danger"><Icon name="shield" size={11} /> Citizenship/Clearance</span>}
        {risk === 'medium' && <span className="pill pill-warning"><Icon name="shield" size={11} /> Eligibility — review</span>}
        {h1b === true && <span className="pill pill-teal"><Icon name="passport" size={11} /> Sponsors H1B</span>}
        {h1b === false && <span className="pill pill-warning"><Icon name="passport" size={11} /> No H1B sponsorship</span>}
        {reqTags.map((t) => (
          <span key={t} className="pill pill-neutral" title="Requirement stated in the posting">{t}</span>
        ))}
      </div>

      {keywords.length > 0 && (
        <div style={{ display: 'flex', gap: 5, marginTop: 10, flexWrap: 'wrap' }}>
          {keywords.map((kw) => <span key={kw} className="skill-chip">{kw}</span>)}
        </div>
      )}

      {snippet && (
        <div style={{
          marginTop: 10, fontSize: 12.5, color: 'var(--text-secondary)', lineHeight: 1.55,
          display: '-webkit-box', WebkitLineClamp: 2, WebkitBoxOrient: 'vertical', overflow: 'hidden',
        }}>{snippet}</div>
      )}

      {/* Bottom */}
      <div style={{
        display: 'flex', justifyContent: 'space-between', alignItems: 'center',
        marginTop: 12, paddingTop: 11, borderTop: '1px solid var(--border)',
      }}>
        <div style={{ display: 'flex', gap: 9, alignItems: 'center' }}>
          {saved && <span style={{ fontSize: 11.5, color: 'var(--primary)', fontWeight: 700, display: 'flex', alignItems: 'center', gap: 3 }}><Icon name="bookmarkFilled" size={12} color="var(--primary)" /> Saved</span>}
          {job.active_status === 'applied' && <span style={{ fontSize: 11.5, color: 'var(--success)', fontWeight: 700, display: 'flex', alignItems: 'center', gap: 3 }}><Icon name="checkCircle" size={12} color="var(--success)" /> Applied</span>}
          {job.active_status === 'ignored' && <span style={{ fontSize: 11.5, color: 'var(--text-tertiary)', fontWeight: 600 }}>Ignored</span>}
          {fr.label && (
            <span
              title={fr.exact ? 'Posting date from the source' : 'Date the role first appeared on our radar (source did not provide a post date)'}
              style={{ fontSize: 11.5, fontWeight: fr.isNew ? 700 : 400, color: fr.isNew ? 'var(--success)' : 'var(--text-tertiary)', display: 'inline-flex', alignItems: 'center', gap: 3 }}
            >
              <Icon name="clock" size={11} color={fr.isNew ? 'var(--success)' : 'var(--text-tertiary)'} />
              {fr.label}{!fr.exact && <span style={{ opacity: 0.7 }}>~</span>}
            </span>
          )}
        </div>

        <div style={{ display: 'flex', gap: 7 }}>
          <button
            onClick={(e) => { e.stopPropagation(); onQuickAction('saved') }}
            title={saved ? 'Unsave' : 'Save job'}
            style={{
              background: saved ? 'var(--primary-light)' : 'var(--surface-muted)',
              border: `1px solid ${saved ? 'var(--primary-mid)' : 'var(--border)'}`,
              borderRadius: 7, padding: '6px 9px', cursor: 'pointer', display: 'flex', alignItems: 'center',
            }}
          >
            <Icon name={saved ? 'bookmarkFilled' : 'bookmark'} size={15} color={saved ? 'var(--primary)' : 'var(--text-secondary)'} />
          </button>
          <a
            href={safeUrl(job.safe_apply_url || job.apply_url)}
            target="_blank" rel="noopener noreferrer"
            onClick={(e) => e.stopPropagation()}
            className="btn btn-primary"
            style={{ padding: '6px 14px', fontSize: 12.5 }}
          >
            Apply <Icon name="external" size={13} color="var(--on-primary)" />
          </a>
        </div>
      </div>
    </div>
  )
}
