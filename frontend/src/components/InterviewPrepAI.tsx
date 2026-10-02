import { useState } from 'react'
import type { Job } from '../lib/types'
import { buildInterviewPrompt, generateInterviewPrep } from '../lib/studio'
import { Icon } from './Icon'

// On-demand, company+role-specific interview prep — copy the prompt into your
// Claude/ChatGPT Pro chat, or generate it in-app with the free Gemini key.
export function InterviewPrepAI({ job }: { job: Job }) {
  const [copied, setCopied] = useState(false)
  const [copying, setCopying] = useState(false)
  const [generating, setGenerating] = useState(false)
  const [text, setText] = useState('')
  const [error, setError] = useState('')

  async function copyPrompt() {
    setCopying(true)
    try {
      const { prompt } = await buildInterviewPrompt(job)
      await navigator.clipboard.writeText(prompt)
      setCopied(true); setTimeout(() => setCopied(false), 2200)
    } finally { setCopying(false) }
  }

  async function generate() {
    setGenerating(true); setError(''); setText('')
    try {
      const { text } = await generateInterviewPrep(job)
      setText(text)
    } catch (e: unknown) {
      const msg = (e as { response?: { data?: { detail?: string } } })?.response?.data?.detail
      setError(msg || 'Generation failed. Please try again.')
    } finally { setGenerating(false) }
  }

  return (
    <div style={{ marginTop: 14, background: 'var(--surface-muted)', border: '1px solid var(--border)', borderRadius: 10, padding: '12px 14px' }}>
      <div style={{ fontSize: 12.5, fontWeight: 700, color: 'var(--text-primary)', marginBottom: 4 }}>
        AI deep prep — specific to {' '}this company &amp; role
      </div>
      <div style={{ fontSize: 11.5, color: 'var(--text-secondary)', marginBottom: 10, lineHeight: 1.6 }}>
        Get a detailed prep guide — likely rounds, per-round questions, coding problems, and a 1-week plan — written for this exact company and role. Either <strong>Copy the prompt</strong> into your Claude/ChatGPT chat, or <strong>Generate</strong> it here with Gemini.
      </div>
      <div style={{ display: 'flex', gap: 7, flexWrap: 'wrap' }}>
        <button onClick={copyPrompt} disabled={copying} className="btn btn-outline" style={{ fontSize: 12 }}>
          <Icon name={copied ? 'check' : 'copy'} size={13} /> {copied ? 'Copied' : copying ? 'Preparing…' : 'Copy prep prompt'}
        </button>
        <a href="https://claude.ai/new" target="_blank" rel="noopener noreferrer" className="btn btn-outline" style={{ fontSize: 12, textDecoration: 'none' }}>
          Open Claude <Icon name="external" size={12} />
        </a>
        <button onClick={generate} disabled={generating} className="btn btn-primary" style={{ fontSize: 12 }}>
          <Icon name="sparkles" size={13} color="var(--on-primary)" /> {generating ? 'Generating…' : 'Generate with Gemini'}
        </button>
      </div>
      {error && (
        <div style={{ marginTop: 10, fontSize: 12, color: 'var(--warning)', background: 'var(--warning-light)', border: '1px solid var(--warning-border)', borderRadius: 7, padding: '8px 10px' }}>{error}</div>
      )}
      {text && (
        <div style={{ marginTop: 12, fontSize: 12.5, color: 'var(--text)', lineHeight: 1.7, whiteSpace: 'pre-wrap', wordBreak: 'break-word', maxHeight: 460, overflowY: 'auto', background: 'var(--surface)', border: '1px solid var(--border)', borderRadius: 8, padding: '11px 13px' }}>
          {text}
        </div>
      )}
    </div>
  )
}
