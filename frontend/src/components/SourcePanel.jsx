import { useState } from 'react'
import { DOC_COLORS } from '../api'

function Source({ s }) {
  const [open, setOpen] = useState(false)
  return (
    <div className="src">
      <div className="top" onClick={() => setOpen((o) => !o)}>
        <span className="dot" style={{ background: DOC_COLORS[s.doc] || '#94a3b8' }} />
        <b>{s.doc}</b>
        <span className="role">{s.role || s.method || ''}</span>
        <span className="score">{(s.score || 0).toFixed(3)}</span>
      </div>
      <div className="path">{s.path}{s.kind === 'table' ? '  ·  [table]' : ''}</div>
      {open && <div className="prev">{s.preview}</div>}
    </div>
  )
}

export default function SourcePanel({ sources }) {
  if (!sources?.length) return <div style={{ color: 'var(--muted)' }}>No linked sources.</div>
  return <>{sources.map((s) => <Source key={s.id} s={s} />)}</>
}
