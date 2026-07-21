import { useEffect, useRef, useState } from 'react'
import { api, DOC_COLORS } from '../api'

// Side-by-side provenance view: the generated section on the left, the FULL
// source document on the right — rendered like a document (real headings and
// tables, not raw chunk text) — scrolled to the cited passage with the quoted
// text highlighted green. The text shown is exactly what the model retrieved,
// so highlights are always faithful; "Original file" opens the real .docx.

function Highlighted({ text, quotes }) {
  let segs = [{ t: text, hl: false }]
  for (const q of quotes) {
    // exact match first, then progressively shorter prefixes (LLM quotes are
    // sometimes lightly paraphrased at the tail)
    const probes = [q, q.slice(0, 160), q.slice(0, 80)]
      .map((x) => x.trim()).filter((x) => x.length > 20)
    for (const p of probes) {
      let placed = false
      const next = []
      for (const seg of segs) {
        if (seg.hl || placed) { next.push(seg); continue }
        const i = seg.t.indexOf(p)
        if (i === -1) { next.push(seg); continue }
        if (i > 0) next.push({ t: seg.t.slice(0, i), hl: false })
        next.push({ t: seg.t.slice(i, i + p.length), hl: true })
        if (i + p.length < seg.t.length) next.push({ t: seg.t.slice(i + p.length), hl: false })
        placed = true
      }
      segs = next
      if (placed) break
    }
  }
  return (
    <>
      {segs.map((s, i) =>
        s.hl ? <mark key={i} className="hl">{s.t}</mark> : <span key={i}>{s.t}</span>)}
    </>
  )
}

// Split a chunk's raw text into paragraph and markdown-table blocks so tables
// render as real tables instead of pipe syntax.
function parseBlocks(text) {
  const blocks = []
  let table = null
  let para = []
  const flushPara = () => {
    if (para.length) { blocks.push({ type: 'p', text: para.join('\n') }); para = [] }
  }
  const flushTable = () => {
    if (table?.length) blocks.push({ type: 'table', rows: table })
    table = null
  }
  for (const ln of text.split('\n')) {
    const t = ln.trim()
    if (t.startsWith('|') && t.endsWith('|')) {
      flushPara()
      const cells = t.split('|').slice(1, -1).map((c) => c.trim())
      if (cells.length && cells.every((c) => /^:?-{2,}:?$/.test(c))) continue
      if (!table) table = []
      table.push(cells)
    } else {
      flushTable()
      if (!t) flushPara()
      else para.push(ln)
    }
  }
  flushPara(); flushTable()
  return blocks
}

function SourceTable({ rows, quotes }) {
  const hlCell = (c) => c.length > 3 && quotes.some((q) => q.includes(c))
  return (
    <table className="srctable">
      <tbody>
        {rows.map((r, i) => (
          <tr key={i}>
            {r.map((c, j) => (
              <td key={j} className={hlCell(c) ? 'cellhl' : ''}>{c}</td>
            ))}
          </tr>
        ))}
      </tbody>
    </table>
  )
}

export default function SourceViewer({ doc, focusPath, citations, section, content, onClose }) {
  const [src, setSrc] = useState(null)
  const focusRef = useRef(null)

  useEffect(() => { api.source(doc).then(setSrc) }, [doc])
  useEffect(() => {
    if (src && focusRef.current) {
      focusRef.current.scrollIntoView({ behavior: 'smooth', block: 'start' })
    }
  }, [src])

  const docQuotes = (citations || []).filter((c) => c.doc === doc)
  const citedPaths = new Set(docQuotes.map((c) => c.path))
  const quotesFor = (path) =>
    docQuotes.filter((c) => c.path === path).map((c) => c.quote)

  let focusSet = false
  const isFocus = (path) => {
    if (focusSet || path !== focusPath) return false
    focusSet = true
    return true
  }
  const leafOf = (path) => (path.includes(' > ') ? path.split(' > ').pop().trim() : path)

  let prevLeaf = null

  return (
    <div className="modal-overlay" onClick={onClose}>
      <div className="modal" onClick={(e) => e.stopPropagation()}>
        <div className="modal-head">
          <span className="dot" style={{ background: DOC_COLORS[doc] || '#94a3b8' }} />
          <b>Source comparison</b>
          <span className="modal-sub">
            {section.number} {section.title} &nbsp;⟷&nbsp; {doc}
            &nbsp;·&nbsp; <mark className="hl demo">green</mark> = cited in this section
          </span>
          <button className="ghost hclose"
                  title="Download the original .docx source file"
                  onClick={() => window.open(`/api/source/${encodeURIComponent(doc)}/file`)}>
            ⬇ Original file
          </button>
          <button className="ghost hclose" onClick={onClose}>✕ Close</button>
        </div>
        <div className="modal-body">
          <div className="srcpane">
            <div className="srcpane-title">Generated — {section.number} {section.title}</div>
            {(content || '').split('\n\n').filter((p) => p.trim()).map((p, i) => (
              <p key={i} className="genpara">{p}</p>
            ))}
            {!content && <div style={{ color: 'var(--muted)' }}>No content generated yet.</div>}
          </div>
          <div className="srcpane">
            <div className="srcpane-title">Source document — {doc} (as retrieved, document order)</div>
            {!src && <div style={{ color: 'var(--muted)' }}>Loading source…</div>}
            {src?.sections?.map((s) => {
              const cited = citedPaths.has(s.path)
              const quotes = cited ? quotesFor(s.path) : []
              const leaf = leafOf(s.path)
              const showHead = leaf !== prevLeaf
              prevLeaf = leaf
              return (
                <div key={s.id} ref={isFocus(s.path) ? focusRef : null}
                     className={'srcblock' + (cited ? ' cited' : '')}>
                  {showHead && leaf.toLowerCase() !== doc.toLowerCase() && (
                    <div className="srchead">{leaf}</div>
                  )}
                  {cited && <span className="citedtag">cited</span>}
                  {parseBlocks(s.text).map((b, i) =>
                    b.type === 'table'
                      ? <SourceTable key={i} rows={b.rows} quotes={quotes} />
                      : (
                        <p key={i} className="srcpara">
                          {cited ? <Highlighted text={b.text} quotes={quotes} /> : b.text}
                        </p>
                      ))}
                </div>
              )
            })}
          </div>
        </div>
      </div>
    </div>
  )
}
