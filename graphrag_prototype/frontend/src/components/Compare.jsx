import { useState } from 'react'
import { api, DOC_COLORS } from '../api'

// Side-by-side retrieval comparison: Vector RAG (main app, LanceDB) vs
// Graph RAG (prototype, Neo4j). Third column is a placeholder until the
// proper hybrid retriever is built.

function Hit({ h }) {
  return (
    <div className="src">
      <div className="top">
        <span className="dot" style={{ background: DOC_COLORS[h.doc] || '#64748b' }} />
        <b>{h.doc}</b>
        <span className="role">{h.kind}</span>
        {h.provenance && <span className="role">{h.provenance}</span>}
        <span className="score">{h.score}</span>
      </div>
      <div className="path">{h.path}</div>
      {h.preview && <div className="prev">{h.preview}</div>}
    </div>
  )
}

function Column({ title, subtitle, data, cypherMode }) {
  return (
    <div className="ccol">
      <div className="ccol-head">
        <h3>{title}</h3>
        <div className="ccol-sub">{subtitle}</div>
        {data?.latency_ms != null && (
          <span className="badge">{data.latency_ms} ms</span>
        )}
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
      setRes({ vector: { error: String(e) }, graph: { error: String(e) } })
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
        <div className="ccol placeholder">
          <div className="ccol-head">
            <h3>Hybrid RAG</h3>
            <div className="ccol-sub">Vector + graph, fused properly</div>
          </div>
          <div className="empty small">Coming soon — will be built after the two-way comparison.</div>
        </div>
      </div>
    </div>
  )
}
