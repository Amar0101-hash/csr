import { useState } from 'react'
import { api, DOC_COLORS } from '../api'

// Side-by-side retrieval comparison of all three strategies for the same query:
// Vector RAG (LanceDB dense+FTS) vs Graph RAG (Neo4j) vs Hybrid RAG (vector + FTS
// + in-memory graph expansion, consensus-fused). Differences isolate the
// retrieval mechanism so you can judge which surfaces the right sources.

// Provenance chips are colour-coded; a multi-signal hit (e.g. "graph+vector")
// is the hybrid's consensus advantage and gets a highlighted chip.
function ProvChip({ p }) {
  const multi = p && p.includes('+')
  const graphOnly = p === 'graph'
  const cls = 'provchip' + (multi ? ' multi' : graphOnly ? ' graph' : '')
  return <span className={cls}>{p}</span>
}

function Hit({ h }) {
  return (
    <div className="src">
      <div className="top">
        <span className="dot" style={{ background: DOC_COLORS[h.doc] || '#64748b' }} />
        <b>{h.doc}</b>
        <span className="role">{h.kind}</span>
        {h.provenance && <ProvChip p={h.provenance} />}
        <span className="score">{h.score}</span>
      </div>
      <div className="path">{h.path}</div>
      {h.preview && <div className="prev">{h.preview}</div>}
    </div>
  )
}

function Column({ title, subtitle, data, cypherMode, highlight }) {
  return (
    <div className={'ccol' + (highlight ? ' highlight' : '')}>
      <div className="ccol-head">
        <h3>{title}</h3>
        <div className="ccol-sub">{subtitle}</div>
        <div className="ccol-badges">
          {data?.latency_ms != null && <span className="badge">{data.latency_ms} ms</span>}
          {data?.results && <span className="badge">{data.results.length} hits</span>}
          {data?.consensus != null && data.consensus > 0 &&
            <span className="badge ok">{data.consensus} multi-signal</span>}
          {data?.graph_only != null && data.graph_only > 0 &&
            <span className="badge">{data.graph_only} graph-only</span>}
        </div>
      </div>
      {!data && <div className="empty small">Run a query to see results.</div>}
      {data?.error && <div className="cerr">{String(data.error)}</div>}
      {data?.results?.map((h, i) => <Hit key={h.id || i} h={h} />)}
      {cypherMode && data?.cypher && (
        <>
          <div className="ccol-sub" style={{ margin: '8px 0 4px' }}>Generated Cypher</div>
          <pre className="cypher">{data.cypher}</pre>
          {data.rows && (
            <>
              <div className="ccol-sub" style={{ margin: '8px 0 4px' }}>
                Rows ({data.rows.length})
              </div>
              <pre className="cypher">{JSON.stringify(data.rows, null, 1)}</pre>
            </>
          )}
        </>
      )}
    </div>
  )
}

export default function Compare() {
  const [query, setQuery] = useState('')
  const [mode, setMode] = useState('vector')
  const [busy, setBusy] = useState(false)
  const [res, setRes] = useState(null)

  const run = async () => {
    if (!query.trim() || busy) return
    setBusy(true)
    try {
      setRes(await api.compare(query.trim(), mode))
    } catch (e) {
      setRes({ vector: { error: String(e) }, graph: { error: String(e) }, hybrid: { error: String(e) } })
    } finally {
      setBusy(false)
    }
  }

  return (
    <div className="compare-wrap">
      <div className="toolbar">
        <input
          className="cquery"
          placeholder='Ask the study sources, e.g. "primary effectiveness endpoint results"'
          value={query}
          onChange={(e) => setQuery(e.target.value)}
          onKeyDown={(e) => e.key === 'Enter' && run()}
        />
        <select value={mode} onChange={(e) => setMode(e.target.value)} className="cmode">
          <option value="vector">Graph side: Neo4j vector index</option>
          <option value="cypher">Graph side: LLM text-to-Cypher</option>
        </select>
        <button onClick={run} disabled={busy || !query.trim()}>
          {busy && <span className="spin" />}Compare
        </button>
      </div>

      <div className="compare-cols">
        <Column
          title="Vector RAG"
          subtitle="Main app — LanceDB vector + full-text, RRF fusion"
          data={res?.vector}
        />
        <Column
          title="Graph RAG"
          subtitle={mode === 'cypher'
            ? 'Prototype — LLM writes & runs read-only Cypher in Neo4j'
            : 'Prototype — Neo4j native vector index over the study graph'}
          data={res?.graph}
          cypherMode={mode === 'cypher'}
        />
        <Column
          title="Hybrid RAG"
          subtitle="Vector + FTS + concept-graph expansion, consensus-fused (RRF)"
          data={res?.hybrid}
          highlight
        />
      </div>
    </div>
  )
}
