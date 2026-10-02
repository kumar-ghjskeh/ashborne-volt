interface Props {
  value: number
  label: string
  color: string
  size?: number
  suffix?: string
}

/** Compact radial score gauge (theme-aware). */
export function ScoreGauge({ value, label, color, size = 62, suffix = '' }: Props) {
  const stroke = 6
  const r = (size - stroke) / 2
  const circ = 2 * Math.PI * r
  const pct = Math.max(0, Math.min(100, value))
  const offset = circ * (1 - pct / 100)
  return (
    <div style={{ display: 'flex', flexDirection: 'column', alignItems: 'center', gap: 5 }}>
      <svg width={size} height={size} style={{ display: 'block' }}>
        <circle cx={size / 2} cy={size / 2} r={r} fill="none" stroke="var(--surface-muted)" strokeWidth={stroke} />
        <circle
          cx={size / 2} cy={size / 2} r={r} fill="none" stroke={color} strokeWidth={stroke}
          strokeLinecap="round" strokeDasharray={circ} strokeDashoffset={offset}
          transform={`rotate(-90 ${size / 2} ${size / 2})`}
          style={{ transition: 'stroke-dashoffset 0.5s ease' }}
        />
        <text x="50%" y="50%" textAnchor="middle" dominantBaseline="central"
          fontSize={size * 0.3} fontWeight="800" fill="var(--text-primary)">
          {Math.round(value)}{suffix}
        </text>
      </svg>
      <span style={{ fontSize: 10.5, color: 'var(--text-secondary)', fontWeight: 600, textAlign: 'center' }}>{label}</span>
    </div>
  )
}

export function priorityColor(p?: string): string {
  if (p === 'High') return 'var(--accent-gold)'
  if (p === 'Medium') return 'var(--primary)'
  return 'var(--text-tertiary)'
}

export function matchColor(v: number): string {
  if (v >= 75) return 'var(--success)'
  if (v >= 50) return 'var(--primary)'
  if (v >= 30) return 'var(--warning)'
  return 'var(--text-tertiary)'
}
