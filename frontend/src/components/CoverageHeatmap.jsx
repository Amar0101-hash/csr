import { useEffect, useState } from 'react'
import { api } from '../api'

const TIER = (n) => (n === 0 ? 'gap' : n < 4 ? 'low' : n < 8 ? 'mid' : 'good')
const LABEL = { gap: 'No source (gap)', low: '1–3 sources', mid: '4–7 sources', good: '8+ well covered' }

export default function CoverageHeatmap({ onOpen }) {
  const [rows, setRows] = useState([])
  useEffect(() => { api.coverage().then(setRows) }, [])

  const gaps = rows.filter((r) => r.sources === 0).length
  const max = Math.max(12, ...rows.map((r) => r.sources || 0))

  return (
    <div className="cov-wrap">
      <div className="cov-head">
        <div className="cov-legend">
          {['gap', 'low', 'mid', 'good'].map((t) => (
            <span key={t} className="cov-leg"><span className={'cov-swatch ' + t} />{LABEL[t]}</span>
          ))}
        </div>
        <div className="cov-hint">
          {gaps > 0 && <b className="cov-gapcount">{gaps} gap{gaps > 1 ? 's' : ''} to review · </b>}
          click a card to open the section
        </div>
      </div>
      <div className="cov-grid">
        {rows.map((r) => {
          const t = TIER(r.sources)
          return (
            <div key={r.number} className={'covcard ' + t} onClick={() => onOpen(r.number)}>
              <div className="covcard-top">
                <span className="covnum">{r.number}</span>
                <span className={'covcount ' + t}>{r.sources === 0 ? 'gap' : `${r.sources} src`}</span>
              </div>
              <div className="covtitle">{r.title}</div>
              <div className="covbar">
                <span className={t} style={{ width: `${Math.max(6, Math.min(100, (100 * r.sources) / max))}%` }} />
              </div>
            </div>
          )
        })}
      </div>
    </div>
  )
}
