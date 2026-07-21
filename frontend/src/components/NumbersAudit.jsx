import { useEffect, useState } from 'react'
import { api, DOC_COLORS } from '../api'

// Document-wide fact check: every material number in every generated section,
// green if it appears verbatim in a linked source, red if not. Sections with
// problems float to the top.
export default function NumbersAudit({ onOpen }) {
  const [d, setD] = useState(null)

  useEffect(() => { api.numbersAudit().then(setD) }, [])

  if (!d) return <div className="heatmap-wrap"><div className="empty">Checking every number…</div></div>

  const pct = d.total ? Math.round((100 * d.supported) / d.total) : 100
  const issues = d.sections.filter((s) => s.supported < s.total)

  return (
    <div className="heatmap-wrap">
      <div className="legend">
        <span className="badge ok">{d.supported} supported</span>
        <span className={'badge ' + (d.total - d.supported ? 'warn' : 'ok')}>
          {d.total - d.supported} unsupported
        </span>
        <span className="badge">{pct}% of all material numbers trace to a source</span>
        <span className="badge">{issues.length} section{issues.length === 1 ? '' : 's'} need review</span>
        <span style={{ marginLeft: 'auto' }}>
          <span className="numchip ok demo">123</span> found in source&nbsp;&nbsp;
          <span className="numchip bad demo">456</span> not found — verify manually
        </span>
      </div>

      {d.sections.map((s) => (
        <div className="numrow" key={s.number}>
          <div className="numrow-head" onClick={() => onOpen(s.number)}
               title="Open this section">
            <span className="snum">{s.number}</span>
            <b>{s.title}</b>
            <span className={'badge ' + (s.supported < s.total ? 'warn' : 'ok')}
                  style={{ marginLeft: 'auto' }}>
              {s.supported}/{s.total} grounded
            </span>
          </div>
          <div className="numchips">
            {s.numbers.map((n, i) => (
              <span key={i}
                    className={'numchip ' + (n.supported ? 'ok' : 'bad')}
                    title={n.supported
                      ? `found in ${n.doc} · ${n.path}`
                      : 'not found in any linked source — verify manually'}>
                {n.value}
                {n.supported && <span className="numsrc"
                      style={{ background: DOC_COLORS[n.doc] || '#94a3b8' }} />}
              </span>
            ))}
          </div>
        </div>
      ))}
      {!d.sections.length && (
        <div className="empty">No generated sections with material numbers yet.</div>
      )}
    </div>
  )
}
