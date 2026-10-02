import type { AnalyticsSummary } from '../lib/types'
import { Icon, type IconName } from './Icon'

interface Props {
  analytics: AnalyticsSummary | null
}

function Card({ label, value, sub, color, icon }: {
  label: string; value: number | string; sub?: string; color: string; icon: IconName
}) {
  return (
    <div style={{
      background: 'var(--surface)', border: '1px solid var(--border)',
      borderRadius: 'var(--radius)', padding: '14px 16px',
      display: 'flex', alignItems: 'center', gap: 13,
      flex: '1 1 150px', minWidth: 0, boxShadow: 'var(--shadow-sm)',
    }}>
      <div style={{
        width: 40, height: 40, borderRadius: 9, background: `color-mix(in srgb, ${color} 14%, transparent)`,
        display: 'flex', alignItems: 'center', justifyContent: 'center', flexShrink: 0,
      }}>
        <Icon name={icon} size={20} color={color} strokeWidth={2.1} />
      </div>
      <div style={{ minWidth: 0 }}>
        <div style={{ fontSize: 23, fontWeight: 700, color: 'var(--text-primary)', lineHeight: 1.05, letterSpacing: '-0.02em' }}>{value}</div>
        <div style={{ fontSize: 12, color: 'var(--text-secondary)', fontWeight: 600, marginTop: 2 }}>{label}</div>
        {sub && <div style={{ fontSize: 10.5, color: 'var(--text-tertiary)', marginTop: 1 }}>{sub}</div>}
      </div>
    </div>
  )
}

export function SummaryCards({ analytics }: Props) {
  if (!analytics) {
    return (
      <div style={{ display: 'flex', gap: 10, flexWrap: 'wrap', marginBottom: 16 }}>
        {Array.from({ length: 8 }).map((_, i) => (
          <div key={i} className="skeleton" style={{ height: 70, flex: '1 1 150px', borderRadius: 8 }} />
        ))}
      </div>
    )
  }

  return (
    <div style={{ display: 'flex', gap: 10, flexWrap: 'wrap', marginBottom: 16 }}>
      <Card label="Verified Active" value={analytics.total_active}      color="var(--success)" icon="checkCircle" sub="Company-direct roles" />
      <Card label="New in 24h"      value={analytics.new_24h}           color="var(--primary)" icon="sparkles" sub={analytics.new_24h > 0 ? 'Fresh postings' : 'No new postings'} />
      <Card label="True Entry-Level" value={analytics.strict_entry_count ?? analytics.entry_level_count} color="var(--teal)" icon="graduation" sub={`+${analytics.candidate_friendly_count ?? 0} likely-junior`} />
      <Card label="Strong New-Grad Fits" value={analytics.strong_new_grad_count ?? 0} color="var(--success)" icon="graduation" sub="New Grad Fit ≥ 75" />
      <Card label="High Priority"   value={analytics.high_score_count}   color="var(--accent-gold)" icon="star" sub="New Grad Fit ≥ 70" />
      <Card label="Remote"          value={analytics.remote_count}       color="var(--teal)"    icon="home" />
      <Card label="Saved"           value={analytics.saved_count}        color="var(--primary)" icon="bookmark" />
      <Card label="Applied"         value={analytics.applied_count}      color="var(--success)" icon="checkCircle" />
    </div>
  )
}
