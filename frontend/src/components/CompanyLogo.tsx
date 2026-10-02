import { useEffect, useState } from 'react'

// Company -> web domain, filled from the corpus's company list (each catalog
// entry carries `domain`, derived from its careers URL or set explicitly). No
// hard-coded map: a newly added employer gets its logo with no frontend change.
const DOMAINS = new Map<string, string>()
const listeners = new Set<() => void>()

export function registerCompanyDomains(companies: { name: string; domain?: string }[]): void {
  let changed = false
  for (const c of companies) {
    const d = (c.domain || '').trim().toLowerCase()
    if (d && /^[a-z0-9.-]+\.[a-z]{2,}$/.test(d) && DOMAINS.get(c.name.toLowerCase().trim()) !== d) {
      DOMAINS.set(c.name.toLowerCase().trim(), d)
      changed = true
    }
  }
  if (changed) listeners.forEach((fn) => fn())
}

// Resilient logo sources, tried in order. icon.horse returns the real brand logo
// for both giants and startups (Clearbit's old API is discontinued); Google's
// favicon service is the always-on fallback; then a letter tile.
function sources(domain: string): string[] {
  return [
    `https://icon.horse/icon/${domain}`,
    `https://www.google.com/s2/favicons?domain=${domain}&sz=128`,
  ]
}

interface Props {
  company: string
  size?: number
  radius?: number
}

export function CompanyLogo({ company, size = 46, radius = 10 }: Props) {
  const [, bump] = useState(0)
  useEffect(() => {
    const fn = () => bump((n) => n + 1)
    listeners.add(fn)
    return () => { listeners.delete(fn) }
  }, [])
  const domain = DOMAINS.get(company.toLowerCase().trim())
  const [stage, setStage] = useState(0)
  useEffect(() => { setStage(0) }, [domain])

  const letter = company.charAt(0).toUpperCase()
  const fallback = (
    <div style={{
      width: size, height: size, borderRadius: radius, background: 'var(--primary-light)',
      border: '1px solid var(--primary-mid)', display: 'flex', alignItems: 'center',
      justifyContent: 'center', fontSize: size * 0.4, fontWeight: 800, color: 'var(--primary)',
      flexShrink: 0, letterSpacing: '-0.02em',
    }}>
      {letter}
    </div>
  )

  const urls = domain ? sources(domain) : []
  if (!domain || stage >= urls.length) return fallback

  return (
    <div style={{
      // --logo-tile, not hard white: vendor marks need a light backing, but a
      // pure-white square punches a hole in the dark page, so the shade has to
      // be tunable per theme. (--brand-tile is the DARK tile for our own logo.)
      width: size, height: size, borderRadius: radius, background: 'var(--logo-tile)',
      border: '1px solid var(--border)', display: 'flex', alignItems: 'center',
      justifyContent: 'center', flexShrink: 0, overflow: 'hidden',
    }}>
      <img
        key={stage}
        src={urls[stage]}
        alt={company}
        width={size * 0.74} height={size * 0.74}
        style={{ objectFit: 'contain' }}
        onError={() => setStage((s) => s + 1)}
        loading="lazy"
      />
    </div>
  )
}
