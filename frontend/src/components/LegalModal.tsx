import { useState } from 'react'
import * as userState from '../lib/userState'
import * as studio from '../lib/studio'
import { storeResume, getStoredResume } from '../lib/resume'
import { Icon } from './Icon'

export type LegalTab = 'privacy' | 'terms' | 'data'

const APP = 'Ashborne Volt'
const UPDATED = 'August 2026'

const h: React.CSSProperties = { fontSize: 14, fontWeight: 700, color: 'var(--text-primary)', margin: '16px 0 6px' }
const p: React.CSSProperties = { fontSize: 12.5, color: 'var(--text-secondary)', lineHeight: 1.65, margin: '0 0 8px' }
const li: React.CSSProperties = { fontSize: 12.5, color: 'var(--text-secondary)', lineHeight: 1.6, marginBottom: 4 }

function Privacy() {
  return (
    <div>
      <p style={p}><strong>{APP}</strong> — Privacy Policy. Last updated {UPDATED}.</p>
      <p style={p}>{APP} helps you discover US electrical-engineering jobs and tailor your résumé to them. This policy explains what we store and your choices.</p>
      <div style={h}>What we store</div>
      <ul style={{ margin: 0, paddingLeft: 18 }}>
        <li style={li}><strong>Résumés you upload</strong> and the skills/experience parsed from them, used to match and score jobs for you.</li>
        <li style={li}><strong>Your master résumé LaTeX</strong> and tailoring instructions (if you save them in Résumé Studio).</li>
        <li style={li}><strong>Preferences</strong> — saved searches / job alerts, and a push-notification subscription if you enable alerts.</li>
      </ul>
      <div style={h}>What we do NOT do</div>
      <ul style={{ margin: 0, paddingLeft: 18 }}>
        <li style={li}>No advertising, no selling of your data, no third-party tracking.</li>
        <li style={li}>No payment information is collected.</li>
      </ul>
      <div style={h}>Third parties</div>
      <ul style={{ margin: 0, paddingLeft: 18 }}>
        <li style={li}><strong>Job listings</strong> are aggregated from companies' own public career sites/APIs.</li>
        <li style={li}><strong>AI résumé tailoring</strong> (optional): if you generate in-app, your résumé + the job description are sent to Google Gemini to produce the tailored text. If you use the Copy-prompt path, nothing is sent by us — you paste it into your own Claude/ChatGPT.</li>
        <li style={li}><strong>PDF compilation</strong> (optional): if you click Download PDF, the tailored LaTeX is sent to a hosted LaTeX compiler to render the PDF.</li>
        <li style={li}><strong>Hosting</strong>: the app runs on standard cloud infrastructure (frontend, backend API, and database).</li>
      </ul>
      <div style={h}>Your rights & choices</div>
      <p style={p}>You can delete all your stored data at any time from the <strong>Delete my data</strong> tab in this dialog (or the footer link). Deletion is immediate and permanent.</p>
      <p style={{ ...p, color: 'var(--text-tertiary)', fontSize: 11.5, marginTop: 14 }}>This is a general privacy notice. Before publishing to an app store, have it reviewed against the requirements of your jurisdiction and the store's policies.</p>
    </div>
  )
}

function Terms() {
  return (
    <div>
      <p style={p}><strong>{APP}</strong> — Terms of Service. Last updated {UPDATED}.</p>
      <div style={h}>The service</div>
      <p style={p}>{APP} aggregates publicly-posted electrical-engineering job listings and provides résumé-matching and AI-assisted tailoring tools. It is an independent tool and is <strong>not affiliated with, endorsed by, or acting on behalf of any employer</strong> whose jobs are listed.</p>
      <div style={h}>Job data accuracy</div>
      <p style={p}>Listings are collected automatically and may be incomplete, outdated, or occasionally misclassified. Always confirm the role, requirements, and application details on the employer's official page before applying. We provide the data "as is," without warranty.</p>
      <div style={h}>Résumé tools</div>
      <p style={p}>Résumé tailoring is AI-assisted. Always review the generated content for accuracy and truthfulness before using it — never submit fabricated experience. You are responsible for the résumés you create and submit.</p>
      <div style={h}>Acceptable use</div>
      <ul style={{ margin: 0, paddingLeft: 18 }}>
        <li style={li}>Use the app for your personal job search only.</li>
        <li style={li}>Don't attempt to disrupt, scrape, or overload the service.</li>
      </ul>
      <div style={h}>Liability</div>
      <p style={p}>To the maximum extent permitted by law, {APP} is provided without warranties and is not liable for any loss arising from use of the service, including reliance on job data or AI-generated résumé content.</p>
      <p style={{ ...p, color: 'var(--text-tertiary)', fontSize: 11.5, marginTop: 14 }}>This is a general terms template, not legal advice. Have it reviewed before an app-store launch.</p>
    </div>
  )
}

function DeleteData() {
  const [confirming, setConfirming] = useState(false)
  const [busy, setBusy] = useState(false)
  const [done, setDone] = useState<Record<string, number> | null>(null)
  const [err, setErr] = useState('')

  async function run() {
    setBusy(true); setErr('')
    try {
      // Everything the app holds about you now lives in this browser, so
      // deleting it is local and immediate — there is no server copy to ask.
      const counts = {
        saved_and_applied: Object.keys(userState.allMarks()).length,
        resume: getStoredResume() ? 1 : 0,
        saved_searches: studio.getWatchlists().length,
      }
      userState.clearState()
      studio.clearStudioData()
      storeResume(null)
      setDone(counts); setConfirming(false)
    } catch {
      setErr('Could not delete your data. Please try again.')
    } finally { setBusy(false) }
  }

  return (
    <div>
      <div style={h}>Delete my data</div>
      <p style={p}>This permanently erases everything the app has stored for you:</p>
      <ul style={{ margin: 0, paddingLeft: 18 }}>
        <li style={li}>All uploaded résumés and their parsed profiles</li>
        <li style={li}>Your saved master résumé (LaTeX) and tailoring instructions</li>
        <li style={li}>Saved searches / job alerts and any push subscription</li>
      </ul>
      <p style={{ ...p, marginTop: 8 }}>Public job listings are not personal data and are not affected. <strong>This cannot be undone.</strong></p>

      {done ? (
        <div style={{ marginTop: 12, fontSize: 12.5, color: 'var(--success)', background: 'var(--success-light, var(--surface-muted))', border: '1px solid var(--border)', borderRadius: 8, padding: '10px 12px' }}>
          Your data was deleted — {done.resumes} résumé(s), {done.settings} saved setting(s), {done.watchlists} saved search(es), {done.push_subscriptions} subscription(s).
        </div>
      ) : !confirming ? (
        <button onClick={() => setConfirming(true)} className="btn btn-outline" style={{ marginTop: 12, fontSize: 12.5, color: 'var(--danger)', borderColor: 'var(--danger)' }}>
          <Icon name="x" size={13} color="var(--danger)" /> Delete all my data
        </button>
      ) : (
        <div style={{ marginTop: 12, display: 'flex', gap: 8, alignItems: 'center', flexWrap: 'wrap' }}>
          <span style={{ fontSize: 12.5, color: 'var(--text-primary)', fontWeight: 600 }}>Are you sure?</span>
          <button onClick={run} disabled={busy} className="btn btn-primary" style={{ fontSize: 12.5, background: 'var(--danger)' }}>
            {busy ? 'Deleting…' : 'Yes, delete everything'}
          </button>
          <button onClick={() => setConfirming(false)} disabled={busy} className="btn btn-outline" style={{ fontSize: 12.5 }}>Cancel</button>
        </div>
      )}
      {err && <div style={{ marginTop: 10, fontSize: 12, color: 'var(--warning)' }}>{err}</div>}
    </div>
  )
}

export function LegalModal({ tab, onChangeTab, onClose }: { tab: LegalTab; onChangeTab: (t: LegalTab) => void; onClose: () => void }) {
  const tabs: { id: LegalTab; label: string }[] = [
    { id: 'privacy', label: 'Privacy' },
    { id: 'terms', label: 'Terms' },
    { id: 'data', label: 'Delete my data' },
  ]
  return (
    <div onClick={onClose} style={{ position: 'fixed', inset: 0, background: 'rgba(0,0,0,0.45)', zIndex: 1000, display: 'flex', alignItems: 'center', justifyContent: 'center', padding: 16 }}>
      <div onClick={(e) => e.stopPropagation()} style={{ background: 'var(--surface)', border: '1px solid var(--border)', borderRadius: 12, width: 'min(640px, 100%)', maxHeight: '85vh', display: 'flex', flexDirection: 'column', boxShadow: '0 20px 60px rgba(0,0,0,0.35)' }}>
        <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', padding: '12px 16px', borderBottom: '1px solid var(--border)' }}>
          <div style={{ display: 'flex', gap: 6 }}>
            {tabs.map((t) => (
              <button key={t.id} onClick={() => onChangeTab(t.id)} style={{
                background: tab === t.id ? 'var(--primary-light)' : 'transparent',
                color: tab === t.id ? 'var(--primary)' : 'var(--text-secondary)',
                border: 'none', borderRadius: 7, padding: '6px 11px', fontSize: 12.5, fontWeight: 700, cursor: 'pointer',
              }}>{t.label}</button>
            ))}
          </div>
          <button onClick={onClose} style={{ background: 'none', border: 'none', cursor: 'pointer', color: 'var(--text-muted)', padding: 4 }}><Icon name="x" size={18} /></button>
        </div>
        <div style={{ padding: '14px 18px', overflowY: 'auto' }}>
          {tab === 'privacy' && <Privacy />}
          {tab === 'terms' && <Terms />}
          {tab === 'data' && <DeleteData />}
        </div>
      </div>
    </div>
  )
}
