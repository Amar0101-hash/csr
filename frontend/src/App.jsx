import { useEffect, useRef, useState } from 'react'
import SectionList from './components/SectionList'
import SectionDetail from './components/SectionDetail'
import CoverageHeatmap from './components/CoverageHeatmap'
import Compare from './components/Compare'
import NumbersAudit from './components/NumbersAudit'
import { api } from './api'

export default function App() {
  const [tab, setTab] = useState('sections')
  const [selected, setSelected] = useState(null)
  const [refresh, setRefresh] = useState(0) // bump to reload the section list
  const [dl, setDl] = useState('') // which report format is downloading
  const [gen, setGen] = useState(null) // full-generation job status
  const [ver, setVer] = useState(null) // document version / approval state
  const [method, setMethod] = useState('hybrid') // retrieval strategy for generation
  const pollRef = useRef(null)

  useEffect(() => { api.version().then(setVer).catch(() => {}) }, [refresh])

  const poll = async () => {
    clearTimeout(pollRef.current)
    const s = await api.genStatus().catch(() => null)
    if (!s) return
    setGen(s)
    setRefresh((x) => x + 1) // section rows update: spinner -> green dot as each finishes
    if (s.running) pollRef.current = setTimeout(poll, 2000)
  }
  // pick up an already-running job on page load, then poll while it runs
  useEffect(() => { poll(); return () => clearTimeout(pollRef.current) }, [])

  const generateAll = async () => {
    if (gen?.running) return
    if (!window.confirm(
      `Generate the FULL document using ${method.toUpperCase()} RAG?\n\nThis re-authors `
      + 'every section and OVERWRITES current content, including your manual edits. It '
      + 'runs for several minutes and calls Claude once per section.'
    )) return
    const r = await api.generateFull('low', method).catch((e) => ({ error: String(e) }))
    if (r?.error) { alert(r.error); return }
    setGen({ running: true, done: 0, total: 0, current: [], errors: [] })
    poll()
  }

  const METHODS = [
    ['hybrid', 'Hybrid RAG'],
    ['vector', 'Vector RAG'],
    ['graph', 'Graph RAG'],
  ]

  const download = async (fmt) => {
    if (dl) return
    setDl(fmt)
    try {
      const r = await fetch(`/api/report/${fmt}`)
      if (!r.ok) {
        const e = await r.json().catch(() => ({}))
        alert(e.error || `Download failed (HTTP ${r.status})`)
        return
      }
      const url = URL.createObjectURL(await r.blob())
      const a = document.createElement('a')
      a.href = url
      a.download = `GraphRAG_Report.${fmt}`
      a.click()
      URL.revokeObjectURL(url)
    } finally {
      setDl('')
    }
  }

  const approveDoc = async () => {
    if (!window.confirm(
      `All ${ver.total} sections are approved.\n\nPromote the document to version `
      + `${(ver.major || 0) + 1}.0 (approved release)?`
    )) return
    const r = await api.approveDoc().catch((e) => ({ error: String(e) }))
    if (r?.error) { alert(r.error); return }
    setRefresh((x) => x + 1)
  }

  return (
    <>
      <header>
        <h1><span>CSR</span> GraphRAG Explorer</h1>
        {ver && (
          <span className={'vbadge ' + ver.state}
                title={`${ver.approved}/${ver.total} sections approved · ${ver.with_content}/${ver.total} have content`}>
            v{ver.major}.{ver.minor} · {ver.state}
            {ver.state !== 'empty' && ` · ${ver.approved}/${ver.total} approved`}
          </span>
        )}
        <div className="dl-btns">
          {ver?.can_approve && (
            <button className="hbtn approve" onClick={approveDoc}
                    title="Every section is approved — promote to the next major version">
              ✓ Approve document → v{(ver.major || 0) + 1}.0
            </button>
          )}
          <select className="cmode hmethod" value={method}
                  disabled={gen?.running}
                  title="Retrieval strategy used for generation"
                  onChange={(e) => setMethod(e.target.value)}>
            {METHODS.map(([v, label]) => <option key={v} value={v}>{label}</option>)}
          </select>
          <button className="hbtn" disabled={gen?.running} onClick={generateAll}
                  title="Author every section with the selected RAG method (overwrites current content)">
            {gen?.running
              ? <><span className="spin" />Generating {gen.done}/{gen.total}…</>
              : '⚡ Generate full document'}
          </button>
          {!gen?.running && gen?.errors?.length > 0 && (
            <span className="badge warn" title={gen.errors.join('\n')}>
              {gen.errors.length} section{gen.errors.length > 1 ? 's' : ''} failed
            </span>
          )}
          <button className="hbtn" disabled={!!dl} onClick={() => download('docx')}>
            {dl === 'docx' ? <span className="spin" /> : '⬇ '}Report .docx
          </button>
          <button className="hbtn" disabled={!!dl} onClick={() => download('pdf')}>
            {dl === 'pdf' ? <span className="spin" /> : '⬇ '}Report PDF
          </button>
        </div>
        <div className="tabs">
          <div className={'tab' + (tab === 'sections' ? ' active' : '')}
               onClick={() => setTab('sections')}>Sections</div>
          <div className={'tab' + (tab === 'coverage' ? ' active' : '')}
               onClick={() => setTab('coverage')}>Coverage heatmap</div>
          <div className={'tab' + (tab === 'numbers' ? ' active' : '')}
               onClick={() => setTab('numbers')}>Numbers audit</div>
          <div className={'tab' + (tab === 'compare' ? ' active' : '')}
               onClick={() => setTab('compare')}>Compare RAG</div>
        </div>
      </header>

      {gen?.running && (
        <div className="gprog" title={`authoring: ${(gen.current || []).join('  ')}`}>
          <div style={{ width: `${(100 * gen.done) / Math.max(1, gen.total)}%` }} />
        </div>
      )}

      {tab === 'sections' ? (
        <div className="view">
          <SectionList selected={selected} onSelect={setSelected} refresh={refresh} gen={gen} />
          <SectionDetail number={selected} method={method} methods={METHODS}
                         onChanged={() => setRefresh((x) => x + 1)} />
        </div>
      ) : tab === 'coverage' ? (
        <CoverageHeatmap
          onOpen={(n) => { setSelected(n); setTab('sections') }}
        />
      ) : tab === 'numbers' ? (
        <NumbersAudit
          onOpen={(n) => { setSelected(n); setTab('sections') }}
        />
      ) : (
        <Compare />
      )}
    </>
  )
}
