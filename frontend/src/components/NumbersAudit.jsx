import { useEffect, useState } from 'react'
import { api } from '../api'

// Document-wide fact check. Leads with what's actionable: the grounded % (hero),
// and per section the numbers that need manual verification — grounded numbers are
// collapsed so the reviewer sees the problems first. Status uses icons, not colour
// alone (✓ grounded, ⚠ verify).

function Tile({ value, label, tone, hero }) {
  return (
    <div className={'kpi' + (tone ? ' ' + tone : '') + (hero ? ' hero' : '')}>
      <div className="kpi-val">{value}</div>
      <div className="kpi-lbl">{label}</div>
    </div>
  )
}

function SectionCard({ s, onOpen }) {
  const [showGood, setShowGood] = useState(false)
  const bad = s.numbers.filter((n) => !n.supported)
  const good = s.numbers.filter((n) => n.supported)
  const ratio = Math.round((100 * s.supported) / s.total)
  const clean = bad.length === 0

  return (
    <div className={'auditcard' + (clean ? ' clean' : '')}>
      <div className="auditcard-head" onClick={() => onOpen(s.number)} title="Open this section">
        <span className="anum">{s.number}</span>
        <span className="atitle">{s.title}</span>
        <div className="ameter"><span className={clean ? 'ok' : 'part'} style={{ width: `${ratio}%` }} /></div>
        <span className={'aratio ' + (clean ? 'ok' : 'warn')}>{s.supported}/{s.total}</span>
      </div>

      {bad.length > 0 && (
        <div className="averify">
          <span className="averify-tag">⚠ Verify manually</span>
          {bad.map((n, i) => <span key={i} className="numchip bad">{n.value}</span>)}
        </div>
      )}

      {good.length > 0 && (
        <div className="agood">
          <span className="agood-tag">✓ {good.length} grounded</span>
          {showGood
            ? good.map((n, i) => (
                <span key={i} className="numchip ok" title={n.doc ? `found in ${n.doc}` : 'found in source'}>
                  {n.value}
                </span>))
            : <button className="linkbtn" onClick={() => setShowGood(true)}>show values</button>}
        </div>
      )}
    </div>
  )
}

export default function NumbersAudit({ onOpen }) {
  const [d, setD] = useState(null)
  useEffect(() => { api.numbersAudit().then(setD) }, [])

  if (!d) return <div className="audit-wrap"><div className="empty">Checking every number…</div></div>

  const pct = d.total ? Math.round((100 * d.supported) / d.total) : 100
  const unsupported = d.total - d.supported
  const issues = d.sections.filter((s) => s.supported < s.total)
  const tone = pct >= 95 ? 'ok' : pct >= 80 ? 'warn' : 'bad'

  return (
    <div className="audit-wrap">
      <div className="kpis">
        <Tile hero value={`${pct}%`} label="material numbers traced to a source" tone={tone} />
        <Tile value={d.supported} label="✓ supported" tone="ok" />
        <Tile value={unsupported} label="⚠ unsupported — verify" tone={unsupported ? 'bad' : 'ok'} />
        <Tile value={issues.length} label="sections to review" tone={issues.length ? 'warn' : 'ok'} />
      </div>

      <div className="audit-note">
        Every material number in the report, checked against the sources cited for its section.
        Sections needing review are listed first; open one to see the exact figures to verify.
      </div>

      {d.sections.map((s) => <SectionCard key={s.number} s={s} onOpen={onOpen} />)}
      {!d.sections.length && <div className="empty">No generated sections with material numbers yet.</div>}
    </div>
  )
}
