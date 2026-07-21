import { useEffect, useRef, useState } from 'react'
import { api, DOC_COLORS } from '../api'
import SourcePanel from './SourcePanel'
import LineageGraph from './LineageGraph'
import SourceViewer from './SourceViewer'
import RenderedContent from './RenderedContent'
import PromptCard from './PromptCard'

export default function SectionDetail({ number, method = 'hybrid', methods = [], onChanged }) {
  const [d, setD] = useState(null)
  const [body, setBody] = useState('')
  const [prompt, setPrompt] = useState('')
  const [status, setStatus] = useState('')
  const [busy, setBusy] = useState(false)
  const [proposal, setProposal] = useState(null) // previewed regeneration awaiting review
  const [audit, setAudit] = useState([])
  const [prompts, setPrompts] = useState(null)   // versioned prompts for this section
  const [srcView, setSrcView] = useState(null)   // {doc, path} -> source comparison modal
  const [secMethod, setSecMethod] = useState(method) // per-section retrieval strategy
  const [editing, setEditing] = useState(false)  // content view: rendered vs raw editor
  const promptRef = useRef(null)

  // auto-grow the custom-instruction textarea to fit its content
  const growPrompt = () => {
    const t = promptRef.current
    if (t) { t.style.height = 'auto'; t.style.height = `${Math.min(220, Math.max(64, t.scrollHeight))}px` }
  }
  useEffect(() => { growPrompt() }, [prompt, number])

  const load = () =>
    Promise.all([api.section(number), api.audit(number), api.prompts(number)])
      .then(([data, ev, pr]) => {
        setD(data); setBody(data.content || ''); setAudit(ev); setPrompts(pr)
        // pre-fill the regenerate box with the active version's instruction, so a
        // prompt the user liked persists as the default for the next run.
        const act = (pr.versions || []).find((v) => v.id === pr.active)
        setPrompt(act?.custom_instruction || '')
      })

  const pinPrompt = async (vid) => { await api.setActivePrompt(number, vid); await load() }

  useEffect(() => {
    if (!number) { setD(null); return }
    setStatus(''); setProposal(null); setSrcView(null); setEditing(false)
    load()
  }, [number])

  useEffect(() => { setSecMethod(method) }, [method])

  if (!number) {
    return (
      <main id="detail">
        <div className="empty">
          <div className="empty-title">Select a section on the left</div>
          <p>
            A new study starts empty — no content is shown until it has been generated.
          </p>
          <p>
            Use <b>⚡ Generate full document</b> (top left) to author every section from
            its linked sources, or open one section and <b>Regenerate section</b> to
            author it individually. Review each section, approve it (✓), and when all
            sections are approved the document can be promoted from a 0.x draft to an
            approved 1.0 release.
          </p>
        </div>
      </main>
    )
  }
  if (!d) return <main id="detail"><div className="empty">Loading…</div></main>

  const v = d.verification || {}
  const currentParas = new Set((d.content || '').split('\n\n').map((p) => p.trim()))

  const regenerate = async () => {
    setBusy(true); setStatus(`generating proposal (${secMethod})…`)
    const res = await api.generate(number, prompt, true, secMethod) // preview: nothing saved
    setBusy(false)
    if (!res.content) { setStatus(res.notes || 'no content'); return }
    setStatus(`proposal ready (${secMethod}) — review below`)
    setProposal(res)
  }
  const acceptProposal = async () => {
    await api.acceptRegen(number, {
      content: proposal.content,
      citations: proposal.citations || [],
      verification: proposal.verification || {},
    })
    setProposal(null); setStatus('accepted ✓')
    await load(); onChanged?.()
  }
  const save = async () => {
    await api.save(number, body)
    setStatus('saved ✓'); await load(); onChanged?.()
  }
  const approve = async () => {
    await api.approveSection(number, !d.approved)
    setStatus(d.approved ? 'approval removed' : 'approved ✓')
    await load(); onChanged?.()
  }

  return (
    <main id="detail">
      <h2 className="sec-title">{d.number}&ensp;{d.title}</h2>
      <div className="badges">
        {d.excluded && <span className="badge warn">excluded from document — restore it from the list (↩ Add back)</span>}
        {d.approved && <span className="badge ok">approved ✓</span>}
        <span className="badge">{d.sources.length} source nodes</span>
        {v.num_numbers != null &&
          <span className={'badge ' + (v.unsupported_count ? 'warn' : 'ok')}>{v.num_numbers} numbers</span>}
        {!!v.unsupported_count && <span className="badge warn">{v.unsupported_count} unsupported</span>}
        <span className={'badge ' + (d.content ? 'ok' : '')}>{d.content ? 'content ✓' : 'no content yet'}</span>
        {d.method_used && <span className="badge method">{d.method_used} RAG</span>}
      </div>

      <div className="card">
        <div className="card-head">
          <h3>Content <span className="status">{busy && <span className="spin blue" />}{status}</span></h3>
          {d.content && (
            <button className="linkbtn" onClick={() => { if (editing) save(); setEditing((e) => !e) }}>
              {editing ? 'Done editing' : '✎ Edit'}
            </button>
          )}
        </div>
        <div className="toolbar">
          <textarea ref={promptRef} className="prompt"
                    placeholder="Optional: custom instruction to regenerate — e.g. 'Summarise in 3 sentences and emphasise the noninferiority conclusion'"
                    value={prompt}
                    onChange={(e) => { setPrompt(e.target.value); growPrompt() }} />
          <select className="cmode" value={secMethod} disabled={busy}
                  title="Retrieval strategy for this regeneration"
                  onChange={(e) => setSecMethod(e.target.value)}>
            {(methods.length ? methods : [['hybrid', 'Hybrid RAG'], ['vector', 'Vector RAG'], ['graph', 'Graph RAG']])
              .map(([val, label]) => <option key={val} value={val}>{label}</option>)}
          </select>
          <button disabled={busy} onClick={regenerate}
                  title="Author a new draft as a PROPOSAL — nothing is overwritten until you accept it">
            Regenerate section
          </button>
          <button className={d.approved ? 'ghost' : 'approve-btn'}
                  disabled={busy || !d.content}
                  title={d.content ? (d.approved ? 'Remove approval (back to draft)' : 'Mark this section as reviewed & approved')
                                   : 'Generate content before approving'}
                  onClick={approve}>
            {d.approved ? 'Unapprove' : '✓ Approve'}
          </button>
        </div>
        {editing ? (
          <textarea className="body-area" placeholder="Not generated yet — click Regenerate section."
                    value={body} onChange={(e) => setBody(e.target.value)} />
        ) : (
          <RenderedContent text={body} />
        )}
      </div>

      {proposal && (
        <div className="card proposal">
          <h3>Proposed regeneration — review before it replaces anything</h3>
          <div className="prop-cols">
            <div className="prop-pane">
              <div className="srcpane-title">Current</div>
              {(d.content || '').split('\n\n').filter((p) => p.trim()).map((p, i) => (
                <p key={i} className="genpara">{p}</p>
              ))}
              {!d.content && <div style={{ color: 'var(--muted)' }}>— empty —</div>}
            </div>
            <div className="prop-pane">
              <div className="srcpane-title">Proposed &nbsp;<span className="newmark">▎new / changed</span></div>
              {proposal.content.split('\n\n').filter((p) => p.trim()).map((p, i) => (
                <p key={i} className={'genpara' + (currentParas.has(p.trim()) ? '' : ' newpara')}>{p}</p>
              ))}
            </div>
          </div>
          <div className="toolbar" style={{ marginTop: 12, marginBottom: 0 }}>
            <button onClick={acceptProposal}>✓ Accept &amp; replace</button>
            <button className="ghost" onClick={() => { setProposal(null); setStatus('proposal discarded') }}>
              Discard proposal
            </button>
            <span className="status">
              {proposal.citations?.length || 0} citations ·{' '}
              {proposal.verification?.unsupported_count
                ? `${proposal.verification.unsupported_count} unsupported numbers`
                : 'all numbers grounded'}
            </span>
          </div>
        </div>
      )}

      <PromptCard data={prompts} onPin={pinPrompt}
                  onUseInstruction={(ci) => { setPrompt(ci); setEditing(false) }} />

      <div className="card">
        <h3>Citations &nbsp;·&nbsp; grounded quotes behind this text ({(d.citations || []).length})</h3>
        {(d.citations || []).length ? (
          d.citations.map((c, i) => (
            <div className="src" key={i}>
              <div className="top">
                <span className="dot" style={{ background: DOC_COLORS[c.doc] || '#94a3b8' }} />
                <b>{c.doc}</b>
                <span className="path" style={{ margin: 0, flex: 1 }}>{c.path}</span>
                <button className="pillbtn" title="Open the source document with this quote highlighted"
                        onClick={() => setSrcView({ doc: c.doc, path: c.path })}>
                  view in source →
                </button>
              </div>
              <div className="prev">“{c.quote}”</div>
            </div>
          ))
        ) : (
          <div style={{ color: 'var(--muted)' }}>
            No citations yet — regenerate to produce grounded content.
          </div>
        )}
        {!!(v.unsupported_numbers?.length) && (
          <div className="cerr" style={{ marginTop: 8 }}>
            Numbers not found in any cited source: {v.unsupported_numbers.join(', ')}
          </div>
        )}
      </div>

      <div className="card">
        <h3>Source lineage &nbsp;·&nbsp; template section ← source nodes
          <span className="status">hover to preview · click a node to open it side-by-side</span></h3>
        <LineageGraph number={number}
                      onOpenSource={(doc, path) => setSrcView({ doc, path })} />
      </div>

      <div className="card">
        <h3>Source traceability (FILLED_BY)</h3>
        <SourcePanel sources={d.sources} />
      </div>

      <div className="card">
        <h3>Audit trail &nbsp;·&nbsp; how this section was authored ({audit.length})</h3>
        {audit.length ? audit.map((e, i) => (
          <div className="audit-row" key={i}>
            <span className="audit-ts">{e.ts}</span>
            <span className={'audit-ev ' + (e.event.includes('error') ? 'err' : e.event)}>{e.event}</span>
            <span className="audit-det">
              {e.model && `${e.model} · effort ${e.effort}`}
              {e.paragraphs != null && ` · ${e.paragraphs} paras, ${e.citations} citations`}
              {e.chars != null && ` · ${e.chars} chars`}
              {e.custom_prompt && ` · custom: “${String(e.custom_prompt).slice(0, 60)}”`}
              {e.error && ` · ${e.error}`}
            </span>
            {e.prompt && (
              <details className="audit-prompt">
                <summary>show exact prompt ({e.sources?.length || 0} source excerpts)</summary>
                <pre className="cypher">{e.prompt}</pre>
              </details>
            )}
          </div>
        )) : (
          <div style={{ color: 'var(--muted)' }}>
            No recorded events yet — the audit trail starts with the next generation, edit, or approval.
          </div>
        )}
      </div>

      {srcView && (
        <SourceViewer doc={srcView.doc} focusPath={srcView.path}
                      citations={d.citations} content={d.content}
                      section={{ number: d.number, title: d.title }}
                      onClose={() => setSrcView(null)} />
      )}
    </main>
  )
}
