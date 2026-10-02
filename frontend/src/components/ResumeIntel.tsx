import { useCallback, useEffect, useRef, useState } from 'react'
import { parseResumeFile, getStoredResume, storeResume, getSkillGaps } from '../lib/resume'
import type { ResumeProfile, ResumeVersion, SkillGap } from '../lib/types'
import { Icon } from './Icon'

interface Props {
  onChanged: () => void
}

const ACCEPT = '.pdf,.docx,.txt,.tex'

export function ResumeIntel({ onChanged }: Props) {
  const [versions, setVersions] = useState<ResumeVersion[]>([])
  const [profile, setProfile] = useState<ResumeProfile | null>(null)
  const [filename, setFilename] = useState('')
  const [gaps, setGaps] = useState<SkillGap[]>([])
  const [highMatch, setHighMatch] = useState(0)
  const [uploading, setUploading] = useState(false)
  const [error, setError] = useState('')
  const [drag, setDrag] = useState(false)
  const [busy, setBusy] = useState(false)
  const inputRef = useRef<HTMLInputElement>(null)

  const loadGaps = useCallback(async () => {
    // Gaps are computed from the corpus already in the browser — no request.
    try { setGaps(await getSkillGaps()); setHighMatch(0) } catch { /* */ }
  }, [])

  const loadAll = useCallback(async () => {
    try {
      // One résumé, held in this browser. There is no server-side résumé store
      // any more, so the "versions" list is just the current one (or none).
      const cur = getStoredResume()
      const vs = cur ? [{ id: 1, label: cur.label, filename: cur.filename, is_active: true,
                          uploaded_at: cur.uploaded_at, role_focus: cur.profile.role_focus || '',
                          skill_count: (cur.profile.all_skills || []).length }] : []
      setVersions(vs)
      const r = { profile: cur ? cur.profile : null, filename: cur?.filename, label: cur?.label }
      setProfile(r.profile)
      setFilename(r.filename || '')
      if (r.profile) loadGaps(); else { setGaps([]); setHighMatch(0) }
    } catch { /* */ }
  }, [loadGaps])

  useEffect(() => { loadAll() }, [loadAll])

  async function handleFile(file: File, label?: string) {
    setUploading(true); setError('')
    try {
      await parseResumeFile(file, label || '')
      await loadAll()
      onChanged()
    } catch (e: unknown) {
      setError(e instanceof Error ? e.message : 'Upload failed')
    } finally {
      setUploading(false)
    }
  }

  function pickFile(asNewVersion: boolean) {
    const input = inputRef.current
    if (!input) return
    input.onchange = () => {
      const f = input.files?.[0]
      if (!f) return
      const label = asNewVersion
        ? (window.prompt('Name this résumé version (e.g. "Power Systems", "Controls"):') || '').trim()
        : ''
      handleFile(f, label)
      input.value = ''
    }
    input.click()
  }

  async function selectVersion(id: number) {
    if (busy) return
    setBusy(true)
    try { void id; await loadAll(); onChanged() } finally { setBusy(false) }  // single browser-held résumé
  }

  async function deleteVersion(id: number) {
    if (busy) return
    setBusy(true)
    try { void id; storeResume(null); await loadAll(); onChanged() } finally { setBusy(false) }
  }

  async function removeAll() {
    if (busy) return
    if (!window.confirm('Delete all resume versions? Job matches will be turned off until you upload again.')) return
    setBusy(true)
    try { storeResume(null); await loadAll(); onChanged() } finally { setBusy(false) }
  }

  const maxGap = gaps.length ? gaps[0].count : 1

  return (
    <aside style={{
      width: 'var(--sidebar-width)', flexShrink: 0, background: 'var(--surface)',
      border: '1px solid var(--border)', borderRadius: 'var(--radius)',
      position: 'sticky', top: 'calc(var(--nav-height) + 8px)',
      maxHeight: 'calc(100vh - var(--nav-height) - 24px)', overflowY: 'auto', alignSelf: 'flex-start',
    }}>
      <input ref={inputRef} type="file" accept={ACCEPT} style={{ display: 'none' }} />
      <div style={{ padding: '14px 16px' }}>
        {versions.length === 0 ? (
          <>
            <div style={{ fontWeight: 700, fontSize: 14, color: 'var(--text-primary)', marginBottom: 4 }}>Resume Intelligence</div>
            <div style={{ fontSize: 12, color: 'var(--text-secondary)', marginBottom: 14, lineHeight: 1.5 }}>
              Upload your resume to rank every job by fit, see matched &amp; missing skills, and get safe tailoring advice. It stays private on your backend.
            </div>
            <div
              onClick={() => pickFile(false)}
              onDragOver={(e) => { e.preventDefault(); setDrag(true) }}
              onDragLeave={() => setDrag(false)}
              onDrop={(e) => { e.preventDefault(); setDrag(false); const f = e.dataTransfer.files?.[0]; if (f) handleFile(f) }}
              style={{
                border: `2px dashed ${drag ? 'var(--primary)' : 'var(--border-strong)'}`,
                background: drag ? 'var(--primary-light)' : 'var(--surface-muted)',
                borderRadius: 10, padding: '28px 16px', textAlign: 'center', cursor: 'pointer',
                transition: 'all 0.15s',
              }}
            >
              {uploading ? (
                <div style={{ display: 'flex', flexDirection: 'column', alignItems: 'center', gap: 8 }}>
                  <span className="spin"><Icon name="refresh" size={22} color="var(--primary)" /></span>
                  <span style={{ fontSize: 12.5, color: 'var(--text-secondary)' }}>Parsing resume…</span>
                </div>
              ) : (
                <>
                  <Icon name="fileText" size={28} color="var(--primary)" />
                  <div style={{ fontSize: 13, fontWeight: 600, color: 'var(--text-primary)', marginTop: 8 }}>Drop your resume or click</div>
                  <div style={{ fontSize: 11, color: 'var(--text-tertiary)', marginTop: 3 }}>PDF · DOCX · TXT · TeX</div>
                </>
              )}
            </div>
            {error && <div style={{ fontSize: 11.5, color: 'var(--danger)', marginTop: 8 }}>{error}</div>}
          </>
        ) : (
          <>
            {/* Resume version manager — the ACTIVE version is what every job is
                ranked & compared against. Switch to re-score everything. */}
            <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 8 }}>
              <div style={{ fontWeight: 700, fontSize: 14, color: 'var(--text-primary)' }}>Resume Versions</div>
              <div style={{ display: 'flex', alignItems: 'center', gap: 10 }}>
                <button onClick={() => pickFile(true)} title="Add another resume version"
                  style={{ background: 'none', border: 'none', color: 'var(--primary)', fontSize: 11.5, fontWeight: 700, cursor: 'pointer', padding: 0, display: 'inline-flex', alignItems: 'center', gap: 3 }}>
                  <Icon name="fileText" size={12} color="var(--primary)" /> Add
                </button>
                <button onClick={removeAll} title="Delete all resume versions"
                  style={{ background: 'none', border: 'none', color: 'var(--text-tertiary)', fontSize: 11.5, fontWeight: 700, cursor: 'pointer', padding: 0 }}>
                  Remove all
                </button>
              </div>
            </div>
            <div style={{ display: 'flex', flexDirection: 'column', gap: 5, marginBottom: 14 }}>
              {versions.map((v) => {
                const active = v.is_active
                return (
                  <div key={v.id}
                    style={{
                      display: 'flex', alignItems: 'center', gap: 7, padding: '7px 9px', borderRadius: 8,
                      border: `1px solid ${active ? 'var(--primary-mid)' : 'var(--border)'}`,
                      background: active ? 'var(--primary-light)' : 'var(--surface-muted)',
                    }}>
                    <button onClick={() => selectVersion(v.id)} title={active ? 'Active' : 'Use this resume'}
                      style={{ flex: 1, minWidth: 0, textAlign: 'left', background: 'none', border: 'none', cursor: 'pointer', padding: 0, display: 'flex', alignItems: 'center', gap: 7 }}>
                      <span style={{
                        width: 9, height: 9, borderRadius: '50%', flexShrink: 0,
                        background: active ? 'var(--primary)' : 'transparent',
                        border: active ? 'none' : '1.5px solid var(--border-strong)',
                      }} />
                      <span style={{ minWidth: 0 }}>
                        <span style={{ display: 'block', fontSize: 12.5, fontWeight: active ? 700 : 600, color: active ? 'var(--primary)' : 'var(--text-primary)', whiteSpace: 'nowrap', overflow: 'hidden', textOverflow: 'ellipsis' }}>{v.label}</span>
                        <span style={{ display: 'block', fontSize: 10.5, color: 'var(--text-tertiary)' }}>{v.skill_count} skills{active ? ' · active' : ''}</span>
                      </span>
                    </button>
                    <button onClick={() => deleteVersion(v.id)} title="Delete this version"
                      style={{ background: 'none', border: 'none', cursor: 'pointer', color: 'var(--text-tertiary)', padding: 0, display: 'flex' }}>
                      <Icon name="x" size={12} />
                    </button>
                  </div>
                )
              })}
            </div>

            {profile && (
              <div style={{ background: 'var(--surface-muted)', borderRadius: 8, padding: '10px 12px', marginBottom: 14 }}>
                <div style={{ fontSize: 12.5, fontWeight: 700, color: 'var(--text-primary)' }}>{profile.role_focus}</div>
                <div style={{ fontSize: 11.5, color: 'var(--text-secondary)', marginTop: 2 }}>
                  {[profile.degree, profile.grad_date].filter(Boolean).join(' · ') || filename}
                </div>
                <div style={{ display: 'flex', flexWrap: 'wrap', gap: 4, marginTop: 8 }}>
                  {profile.all_skills.slice(0, 12).map((s) => (
                    <span key={s} className="skill-chip" style={{ fontSize: 10 }}>{s}</span>
                  ))}
                  {profile.all_skills.length > 12 && (
                    <span style={{ fontSize: 10.5, color: 'var(--text-tertiary)', alignSelf: 'center' }}>+{profile.all_skills.length - 12}</span>
                  )}
                </div>
                {profile.projects.length > 0 && (
                  <div style={{ fontSize: 11, color: 'var(--text-tertiary)', marginTop: 8 }}>{profile.projects.length} projects detected</div>
                )}
              </div>
            )}

            <div style={{ fontSize: 11, color: 'var(--text-tertiary)', marginBottom: 12, lineHeight: 1.5 }}>
              Click any job to see how it matches the <strong style={{ color: 'var(--primary)' }}>active</strong> resume — switch versions above to re-score everything.
            </div>

            <div className="section-header">Skill Gaps · top missing</div>
            {gaps.length === 0 ? (
              <div style={{ fontSize: 11.5, color: 'var(--text-tertiary)' }}>No common gaps across your high-match jobs.</div>
            ) : (
              <>
                <div style={{ fontSize: 11, color: 'var(--text-tertiary)', marginBottom: 8 }}>across {highMatch} high-match jobs</div>
                <div style={{ display: 'flex', flexDirection: 'column', gap: 7 }}>
                  {gaps.slice(0, 8).map((g) => (
                    <div key={g.skill} style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
                      <span style={{ fontSize: 11.5, color: 'var(--text-secondary)', width: 96, flexShrink: 0, whiteSpace: 'nowrap', overflow: 'hidden', textOverflow: 'ellipsis' }}>{g.skill}</span>
                      <div style={{ flex: 1, height: 6, background: 'var(--surface-muted)', borderRadius: 3, overflow: 'hidden' }}>
                        <div style={{ width: `${Math.round(100 * g.count / maxGap)}%`, height: '100%', background: 'var(--warning)', borderRadius: 3 }} />
                      </div>
                      <span style={{ fontSize: 11, color: 'var(--text-tertiary)', width: 18, textAlign: 'right' }}>{g.count}</span>
                    </div>
                  ))}
                </div>
              </>
            )}
            {error && <div style={{ fontSize: 11.5, color: 'var(--danger)', marginTop: 10 }}>{error}</div>}
          </>
        )}
      </div>
    </aside>
  )
}
