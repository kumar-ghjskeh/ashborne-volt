import { useEffect, useState } from 'react'

/**
 * Tracks whether the viewport is below `breakpoint` px (default 820 — the point
 * at which the 3-column desktop layout stops fitting). Used to switch filters to
 * a drawer and the job-details panel to a full-screen sheet on phones/tablets.
 */
export function useIsMobile(breakpoint = 820): boolean {
  const query = `(max-width: ${breakpoint}px)`
  const [isMobile, setIsMobile] = useState<boolean>(
    () => typeof window !== 'undefined' && window.matchMedia(query).matches,
  )

  useEffect(() => {
    const mql = window.matchMedia(query)
    const onChange = () => setIsMobile(mql.matches)
    onChange()
    mql.addEventListener('change', onChange)
    return () => mql.removeEventListener('change', onChange)
  }, [query])

  return isMobile
}
