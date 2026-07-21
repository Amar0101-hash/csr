import { useEffect, useState } from 'react'
import { api } from '../api'

// Interactive "template section <- source nodes" star.
// - edges animate, flowing INTO the section node (sources feed the section)
// - hovering a node spotlights it (everything else dims) and shows a preview card
// - clicking a node opens the side-by-side SourceViewer focused on that passage
// Pure SVG: deterministic layout, no physics jitter for a small star.
export default function LineageGraph({ number, onOpenSource }) {
  const [g, setG] = useState(null)
  const [hover, setHover] = useState(null) // hovered source node

  useEffect(() => { setHover(null); if (number) api.graph(number).then(setG) }, [number])
  if (!g) return null

  const src = (g.nodes || []).filter((n) => n.type === 'source')
  if (!src.length) {
    return <div style={{ color: 'var(--muted)' }}>No linked source nodes (coverage gap).</div>
  }

  const W = 900
  const H = Math.max(380, 150 + src.length * 24)
  const cx = W / 2, cy = H / 2
  const R = Math.min(cx, cy) - 115
  const edgeOf = (id) => (g.edges || []).find((e) => e.target === id) || {}
  const maxScore = Math.max(...src.map((n) => edgeOf(n.id).score || 0), 0.0001)

  const pos = (i) => {
    const a = -Math.PI / 2 + (2 * Math.PI * i) / src.length
    return [cx + R * Math.cos(a), cy + R * Math.sin(a), a]
  }
  const labelFor = (x, y, a, r) => {
    if (Math.abs(Math.cos(a)) >= 0.35) {
      const right = Math.cos(a) > 0
      return { x: x + (right ? r + 8 : -(r + 8)), y1: y - 1, y2: y + 11,
               anchor: right ? 'start' : 'end' }
    }
    const below = Math.sin(a) > 0
    return { x, y1: below ? y + r + 14 : y - (r + 18), y2: below ? y + r + 26 : y - (r + 6),
             anchor: 'middle' }
  }
  const cleanName = (n) => {
    const raw = (n.label || '').startsWith(n.doc)
      ? (n.label || '').slice(n.doc.length).replace(/^\s*·\s*/, '')
      : (n.label || '')
    return (n.kind === 'table' ? '▦ ' : '') + raw.slice(0, 30)
  }
  // node's source path: strip the "[table] " tag the caption may carry
  const pathOf = (n) => n.path || null

  return (
    <div className="lg-wrap">
      <svg width="100%" viewBox={`0 0 ${W} ${H}`}
           className={'lineage' + (hover ? ' spot' : '')}>
        {src.map((n, i) => {
          const [x, y] = pos(i)
          const rel = (edgeOf(n.id).score || 0) / maxScore
          return (
            <line key={'e' + n.id} x1={x} y1={y} x2={cx} y2={cy}
                  className={'ledge' + (hover?.id === n.id ? ' hot' : '')}
                  stroke={n.color} strokeWidth={1.5 + 4.5 * rel}
                  strokeLinecap="round" />
          )
        })}
        {src.map((n, i) => {
          const [x, y, a] = pos(i)
          const score = edgeOf(n.id).score || 0
          const rel = score / maxScore
          const r = 7 + 7 * rel
          const lb = labelFor(x, y, a, r)
          return (
            <g key={'n' + n.id}
               className={'lnode' + (hover?.id === n.id ? ' hover' : '')}
               style={{ animationDelay: `${i * 55}ms` }}
               onMouseEnter={() => setHover({ ...n, x, y, score })}
               onMouseLeave={() => setHover(null)}
               onClick={() => onOpenSource?.(n.doc, pathOf(n))}>
              <circle cx={x} cy={y} r={r + 7} className="halo" fill={n.color} />
              <circle cx={x} cy={y} r={r} fill={n.color} stroke="#fff" strokeWidth="2.5" />
              <text x={lb.x} y={lb.y1} fontSize="11.5" fontWeight="600" textAnchor={lb.anchor}>
                {cleanName(n)}
              </text>
              <text x={lb.x} y={lb.y2} fontSize="10" textAnchor={lb.anchor} className="lmuted">
                {n.doc} · {score.toFixed(2)}
              </text>
            </g>
          )
        })}
        <g className="lcenter">
          <circle cx={cx} cy={cy} r="30" className="cpulse" />
          <circle cx={cx} cy={cy} r="30" fill="#dbeafe" />
          <circle cx={cx} cy={cy} r="22" fill="#2563eb" />
          <text x={cx} y={cy + 4} fontSize="11.5" fontWeight="700" fill="#fff" textAnchor="middle">
            {g.section.number}
          </text>
        </g>
      </svg>

      {hover && (
        <div className="lg-card"
             style={{ left: `${(100 * hover.x) / W}%`, top: `${(100 * hover.y) / H}%` }}>
          <div className="lg-card-head">
            <span className="dot" style={{ background: hover.color }} />
            <b>{hover.doc}</b>
            <span className="role">{hover.kind}</span>
            <span className="score">{hover.score.toFixed(3)}</span>
          </div>
          <div className="lg-card-name">{cleanName(hover)}</div>
          {hover.preview && <div className="lg-card-prev">{hover.preview}</div>}
          <div className="lg-card-cta">click to open side-by-side source view →</div>
        </div>
      )}
    </div>
  )
}
