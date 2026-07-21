import { useEffect, useState } from 'react'
import { api, DOC_COLORS } from '../api'

// Explainability for the hybrid's graph half: the clinical concepts that tie this
// section's sources together across documents. A concept shown with more than one
// role (DEFINES / DESCRIBES / MEASURES) is a genuine cross-document bridge — the
// same signal the concept-graph retrieval rewards.
const ROLE_ORDER = ['DEFINES', 'DESCRIBES', 'MEASURES', 'RELATES_TO']
const ROLE_LABEL = { DEFINES: 'Defined', DESCRIBES: 'Described', MEASURES: 'Measured' }
const KIND_LABEL = {
  endpoint: 'endpoint', analysis_set: 'analysis set', visit: 'visit',
  design: 'design', safety: 'safety', conduct: 'conduct', measure: 'measure',
}

export default function ConceptBridges({ number, onOpenSource }) {
  const [data, setData] = useState(null)

  useEffect(() => {
    if (!number) return
    setData(null)
    api.concepts(number).then(setData).catch(() => setData({ bridges: [] }))
  }, [number])

  if (!data) return <div className="empty small">Loading concept bridges…</div>
  if (!data.bridges?.length) {
    return (
      <div style={{ color: 'var(--muted)' }}>
        No cross-document concept bridges among this section's sources — the graph
        signal adds little here, so the hybrid leans on vector + full-text.
      </div>
    )
  }

  return (
    <div className="cbridges">
      <div className="cbridges-lead">
        {data.bridges.length} clinical concept{data.bridges.length > 1 ? 's' : ''} link
        this section's sources across documents. Rarer concepts (top) make the
        strongest links; each column is a document role the graph connects.
      </div>
      {data.bridges.map((b) => (
        <div className="cbridge" key={b.key}>
          <div className="cbridge-head">
            <span className="cbridge-name">{b.name}</span>
            <span className="cbridge-kind">{KIND_LABEL[b.kind] || b.kind}</span>
            <span className="cbridge-roles">{b.n_roles} roles bridged</span>
          </div>
          <div className="cbridge-roles-grid">
            {ROLE_ORDER.filter((r) => b.roles[r]).map((role) => (
              <div className="cbridge-col" key={role}>
                <div className="cbridge-role">{ROLE_LABEL[role] || role}</div>
                {dedupeDocs(b.roles[role]).map((s, i) => (
                  <button className="cbridge-src" key={i}
                          title={`${s.doc} · ${s.path} — open side-by-side`}
                          onClick={() => onOpenSource?.(s.doc, s.path)}>
                    <span className="dot" style={{ background: DOC_COLORS[s.doc] || '#94a3b8' }} />
                    <span className="cbridge-doc">{s.doc}</span>
                    <span className="cbridge-path">{leaf(s.path)}</span>
                  </button>
                ))}
              </div>
            ))}
          </div>
        </div>
      ))}
    </div>
  )
}

// one source per (doc, leaf-heading) so a concept mentioned by many chunks of the
// same section doesn't repeat.
function dedupeDocs(list) {
  const seen = new Set()
  const out = []
  for (const s of list) {
    const key = `${s.doc}|${leaf(s.path)}`
    if (seen.has(key)) continue
    seen.add(key)
    out.push(s)
  }
  return out.slice(0, 6)
}

function leaf(path) {
  if (!path) return ''
  const parts = String(path).split(' > ')
  return parts[parts.length - 1].replace(/:\s*$/, '').slice(0, 40)
}
