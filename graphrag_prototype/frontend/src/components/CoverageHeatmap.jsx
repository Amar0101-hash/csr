import { useEffect, useState } from 'react'
import { api, covColor } from '../api'

export default function CoverageHeatmap({ onOpen }) {
  const [rows, setRows] = useState([])
  useEffect(() => { api.coverage().then(setRows) }, [])

  return (
    <div className="heatmap-wrap">
      <div className="legend">
        <span><span className="swatch" style={{ background: '#ef4444' }} />gap (0)</span>
        <span><span className="swatch" style={{ background: '#f59e0b' }} />1–3</span>
        <span><span className="swatch" style={{ background: '#eab308' }} />4–7</span>
        <span><span className="swatch" style={{ background: '#22c55e' }} />8+</span>
        <span style={{ marginLeft: 'auto' }}>click a cell to open the section</span>
      </div>
      <div className="heatmap">
        {rows.map((r) => (
          <div key={r.number} className="cell"
               style={{ background: covColor(r.sources) }}
               onClick={() => onOpen(r.number)}>
            <div className="n">§{r.number} · {r.sources} src</div>
            <div className="t">{r.title}</div>
          </div>
        ))}
      </div>
    </div>
  )
}
