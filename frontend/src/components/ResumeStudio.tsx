import { useEffect, useRef, useState } from 'react'
import { api } from '../lib/api'
import { getMasterResume, saveMasterResume, buildTailorPrompt, generateTailored } from '../lib/studio'
import type { Job } from '../lib/types'
import { Icon } from './Icon'

// Master résumé + instructions are global (set once, reused for every job), so we
// cache them at module scope and only hit the API the first time.
let _master: { master_latex: string; instructions: string; gemini_enabled: boolean } | null = null

const sectionLabel: React.CSSProperties = {
  fontSize: 11, fontWeight: 700, color: 'var(--text-secondary)',
  textTransform: 'uppercase', letterSpacing: '0.05em', marginBottom: 8, display: 'block',
}
const ta: React.CSSProperties = {
  width: '100%', border: '1px solid var(--border)', borderRadius: 8, padding: '9px 11px',
  fontSize: 12, fontFamily: 'ui-monospace, SFMono-Regular, Menlo, monospace',
  background: 'var(--surface)', color: 'var(--text-primary)', outline: 'none',
  resize: 'vertical', lineHeight: 1.5,
}

export function ResumeStudio({ job }: { job: Job }) {
  const [masterLatex, setMasterLatex] = useState('')
  const [instructions, setInstructions] = useState('')
  const [geminiEnabled, setGeminiEnabled] = useState(false)
  const [missing, setMissing] = useState<string[]>([])
  const [loadingKw, setLoadingKw] = useState(true)
  const [savedMaster, setSavedMaster] = useState(false)
  const [copiedPrompt, setCopiedPrompt] = useState(false)
  const [copyingPrompt, setCopyingPrompt] = useState(false)
  const [generating, setGenerating] = useState(false)
  const [genError, setGenError] = useState('')
  // The single shared output — filled by Gemini OR pasted from Claude/ChatGPT.
  const [tailored, setTailored] = useState('')
  const [copiedTex, setCopiedTex] = useState(false)
  const [pdfBusy, setPdfBusy] = useState(false)
  const [pdfMsg, setPdfMsg] = useState('')
  const loadedMaster = useRef(false)

  // Load the saved master résumé once per session.
  useEffect(() => {
    if (_master) {
      setMasterLatex(_master.master_latex); setInstructions(_master.instructions)
      setGeminiEnabled(_master.gemini_enabled); loadedMaster.current = true
      return
    }
    // Your master LaTeX and tailoring instructions are your data and a few KB,
    // so they live in this browser rather than needing a server to hold them.
    const m = { ...getMasterResume(), gemini_enabled: false }
    _master = m
    setMasterLatex(m.master_latex); setInstructions(m.instructions); setGeminiEnabled(false)
    loadedMaster.current = true
  }, [])

  // Per-job: fetch the keywords this role wants (accurate, bound to this job id).
  useEffect(() => {
    let cancelled = false
    setLoadingKw(true); setMissing([]); setTailored(''); setGenError(''); setPdfMsg('')
    buildTailorPrompt(job, {})
      .then((r) => { if (!cancelled) setMissing(r.missing_keywords || []) })
      .catch(() => { if (!cancelled) setMissing([]) })
      .finally(() => { if (!cancelled) setLoadingKw(false) })
    return () => { cancelled = true }
  }, [job.id])

  async function saveMaster() {
    saveMasterResume(masterLatex, instructions)
    _master = { master_latex: masterLatex, instructions, gemini_enabled: geminiEnabled }
    setSavedMaster(true); setTimeout(() => setSavedMaster(false), 2000)
  }

  async function copyPrompt() {
    setCopyingPrompt(true)
    try {
      const { prompt } = await buildTailorPrompt(job, { master_latex: masterLatex, instructions })
      await navigator.clipboard.writeText(prompt)
      setCopiedPrompt(true); setTimeout(() => setCopiedPrompt(false), 2200)
    } finally { setCopyingPrompt(false) }
  }

  async function generateGemini() {
    setGenerating(true); setGenError(''); setPdfMsg('')
    try {
      const { latex } = await generateTailored(job, { master_latex: masterLatex, instructions })
      setTailored(latex)
    } catch (e: unknown) {
      const msg = (e as { response?: { data?: { detail?: string } } })?.response?.data?.detail
      setGenError(msg || 'Generation failed. Please try again.')
    } finally { setGenerating(false) }
  }

  function copyTex() {
    navigator.clipboard.writeText(tailored).then(() => {
      setCopiedTex(true); setTimeout(() => setCopiedTex(false), 2000)
    })
  }

  function downloadTex() {
    const blob = new Blob([tailored], { type: 'text/plain;charset=utf-8' })
    triggerDownload(blob, 'tailored-resume.tex')
  }

  // Open the LaTeX in a fresh Overleaf project (reliable compile + download).
  function openInOverleaf() {
    const form = document.createElement('form')
    form.method = 'POST'; form.action = 'https://www.overleaf.com/docs'
    form.target = '_blank'; form.style.display = 'none'
    const snip = document.createElement('textarea')
    snip.name = 'snip'; snip.value = tailored; form.appendChild(snip)
    const eng = document.createElement('input')
    eng.type = 'hidden'; eng.name = 'engine'; eng.value = 'pdflatex'; form.appendChild(eng)
    document.body.appendChild(form); form.submit(); document.body.removeChild(form)
  }

  // One-click PDF via the hosted compiler; falls back to Overleaf on any failure.
  async function downloadPdf() {
    setPdfBusy(true); setPdfMsg('')
    try {
      const blob = await api.compileResumePdf(tailored)
      triggerDownload(blob, 'tailored-resume.pdf')
      setPdfMsg('PDF downloaded.')
    } catch {
      setPdfMsg('The PDF compiler was unavailable — opening Overleaf instead (press Recompile → Download).')
      openInOverleaf()
    } finally {
      setPdfBusy(false)
      setTimeout(() => setPdfMsg(''), 6000)
    }
  }

  function triggerDownload(blob: Blob, filename: string) {
    const url = URL.createObjectURL(blob)
    const a = document.createElement('a')
    a.href = url; a.download = filename
    document.body.appendChild(a); a.click(); document.body.removeChild(a)
    setTimeout(() => URL.revokeObjectURL(url), 1000)
  }

  const hasMaster = masterLatex.trim().length > 0
  const hasTailored = tailored.trim().length > 0
  const linkBtn: React.CSSProperties = {
    background: 'none', border: 'none', color: 'var(--primary)', fontSize: 11.5,
    fontWeight: 700, cursor: 'pointer', padding: 0, display: 'inline-flex', alignItems: 'center', gap: 4,
  }

  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 18 }}>
      <div style={{
        background: 'var(--primary-light)', border: '1px solid var(--primary-mid)',
        borderRadius: 8, padding: '9px 12px', fontSize: 12, color: 'var(--primary)', lineHeight: 1.6,
      }}>
        <strong>Résumé Studio</strong> tailors your résumé to <strong>this</strong> role — keeping your exact LaTeX template and integrating its keywords truthfully. Generate below, then download the PDF.
      </div>

      {/* Keywords this role wants */}
      <div>
        <span style={sectionLabel}>Keywords this role wants</span>
        {loadingKw ? (
          <div style={{ fontSize: 12, color: 'var(--text-tertiary)' }}>Analyzing this job…</div>
        ) : missing.length ? (
          <div style={{ display: 'flex', flexWrap: 'wrap', gap: 5 }}>
            {missing.map((k) => <span key={k} className="pill pill-warning" style={{ fontSize: 11 }}>{k}</span>)}
          </div>
        ) : (
          <div style={{ fontSize: 11.5, color: 'var(--text-tertiary)' }}>Upload a résumé in <strong style={{ color: 'var(--primary)' }}>Resume Matches</strong> to see the exact gaps for this job — the tailoring still works from the job description.</div>
        )}
      </div>

      {/* Master résumé */}
      <div>
        <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginBottom: 8 }}>
          <span style={{ ...sectionLabel, marginBottom: 0 }}>Your master résumé (LaTeX)</span>
          <button onClick={saveMaster} disabled={!hasMaster} style={{ ...linkBtn, color: hasMaster ? 'var(--primary)' : 'var(--text-tertiary)', cursor: hasMaster ? 'pointer' : 'default' }}>
            <Icon name={savedMaster ? 'check' : 'bookmark'} size={12} /> {savedMaster ? 'Saved' : 'Save as my master'}
          </button>
        </div>
        <textarea value={masterLatex} onChange={(e) => setMasterLatex(e.target.value)} rows={6}
          placeholder="Paste your Overleaf résumé LaTeX here. Saved once and reused for every job — edit anytime." style={ta} />
        <div style={{ fontSize: 10.5, color: 'var(--text-tertiary)', marginTop: 4 }}>
          Stored once and reused for every job. Update it whenever your real résumé changes.
        </div>
      </div>

      {/* Optional instructions */}
      <div>
        <span style={sectionLabel}>Tailoring instructions (optional)</span>
        <textarea value={instructions} onChange={(e) => setInstructions(e.target.value)} rows={2}
          placeholder="e.g. Keep it to one page. Emphasize ETAP studies and protection & controls." style={{ ...ta, fontFamily: 'inherit', fontSize: 12.5 }} />
      </div>

      {/* Generate */}
      <div style={{ background: 'var(--surface-muted)', border: '1px solid var(--border)', borderRadius: 10, padding: '13px 14px' }}>
        <div style={{ fontSize: 12.5, fontWeight: 700, color: 'var(--text-primary)', marginBottom: 8 }}>Generate your tailored résumé</div>

        {/* Primary — Claude / ChatGPT */}
        <div style={{ fontSize: 11.5, color: 'var(--text-secondary)', marginBottom: 8, lineHeight: 1.6 }}>
          <strong style={{ color: 'var(--text-primary)' }}>Best quality —</strong> click <strong>Copy prompt</strong>, open <strong>Claude</strong> or <strong>ChatGPT</strong>, paste (Ctrl + V) and send. It replies with your tailored résumé as LaTeX — paste that into the box below.
        </div>
        <div style={{ display: 'flex', gap: 7, flexWrap: 'wrap', marginBottom: geminiEnabled ? 12 : 0 }}>
          <button onClick={copyPrompt} disabled={copyingPrompt} className="btn btn-primary" style={{ fontSize: 12.5 }}>
            <Icon name={copiedPrompt ? 'check' : 'copy'} size={14} color="var(--on-primary)" /> {copiedPrompt ? 'Prompt copied' : copyingPrompt ? 'Preparing…' : 'Copy prompt'}
          </button>
          <a href="https://claude.ai/new" target="_blank" rel="noopener noreferrer" className="btn btn-outline" style={{ fontSize: 12.5, textDecoration: 'none' }}>
            Open Claude <Icon name="external" size={13} />
          </a>
          <a href="https://chatgpt.com/" target="_blank" rel="noopener noreferrer" className="btn btn-outline" style={{ fontSize: 12.5, textDecoration: 'none' }}>
            Open ChatGPT <Icon name="external" size={13} />
          </a>
        </div>

        {/* Secondary — Gemini one-click */}
        {geminiEnabled ? (
          <div style={{ borderTop: '1px dashed var(--border)', paddingTop: 11 }}>
            <div style={{ fontSize: 11.5, color: 'var(--text-secondary)', marginBottom: 8, lineHeight: 1.6 }}>
              <strong style={{ color: 'var(--text-primary)' }}>Or instantly —</strong> generate it here with Gemini (free, one click; fills the box below).
            </div>
            <button onClick={generateGemini} disabled={generating || !hasMaster} className="btn btn-outline" style={{ fontSize: 12.5 }}>
              <Icon name="sparkles" size={14} /> {generating ? 'Generating…' : 'Generate with Gemini'}
            </button>
            {!hasMaster && <span style={{ fontSize: 11, color: 'var(--text-tertiary)', marginLeft: 8 }}>Paste your master résumé first.</span>}
            {genError && (
              <div style={{ marginTop: 10, fontSize: 12, color: 'var(--warning)', background: 'var(--warning-light)', border: '1px solid var(--warning-border)', borderRadius: 7, padding: '8px 10px' }}>{genError}</div>
            )}
          </div>
        ) : (
          <div style={{ borderTop: '1px dashed var(--border)', paddingTop: 11, fontSize: 11, color: 'var(--text-tertiary)', lineHeight: 1.6 }}>
            Want one-click in-app generation too? Add a free <strong>GEMINI_API_KEY</strong> (aistudio.google.com/apikey) to the backend. The Claude/ChatGPT path above works without it.
          </div>
        )}
      </div>

      {/* Shared output → download */}
      <div>
        <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 6 }}>
          <span style={{ ...sectionLabel, marginBottom: 0 }}>Tailored résumé (LaTeX)</span>
          {hasTailored && (
            <button onClick={copyTex} style={linkBtn}>
              <Icon name={copiedTex ? 'check' : 'copy'} size={12} /> {copiedTex ? 'Copied' : 'Copy'}
            </button>
          )}
        </div>
        <textarea value={tailored} onChange={(e) => setTailored(e.target.value)} rows={9}
          placeholder="Paste the tailored LaTeX from Claude/ChatGPT here — or use Generate with Gemini above. Then download the PDF." style={ta} />
        <div style={{ display: 'flex', gap: 8, flexWrap: 'wrap', marginTop: 8 }}>
          <button onClick={downloadPdf} disabled={!hasTailored || pdfBusy} className="btn btn-primary" style={{ fontSize: 12.5 }}>
            <Icon name="download" size={14} color="var(--on-primary)" /> {pdfBusy ? 'Compiling PDF…' : 'Download PDF'}
          </button>
          <button onClick={openInOverleaf} disabled={!hasTailored} className="btn btn-outline" style={{ fontSize: 12.5 }}>
            <Icon name="external" size={13} /> Open in Overleaf
          </button>
          <button onClick={downloadTex} disabled={!hasTailored} className="btn btn-outline" style={{ fontSize: 12.5 }}>
            <Icon name="download" size={13} /> Download .tex
          </button>
        </div>
        {pdfMsg && (
          <div style={{ marginTop: 8, fontSize: 11.5, color: 'var(--text-secondary)' }}>{pdfMsg}</div>
        )}
        <div style={{ fontSize: 10.5, color: 'var(--text-tertiary)', marginTop: 6 }}>
          <strong>Download PDF</strong> compiles it for you. If the compiler is busy, it opens Overleaf so you can compile there — your template always works in Overleaf.
        </div>
      </div>
    </div>
  )
}
