import { useEffect, useState } from 'react'
import { api } from '../api'

export default function SectionList({ selected, onSelect, refresh }) {
  const [rows, setRows] = useState([])

  useEffect(() => { api.sections().then(setRows) }, [refresh])

  const toggle = async (e, s) => {
    e.stopPropagation()
    const excluded = !s.excluded
    if (excluded && !window.confirm(
      `Remove ${s.number} ${s.title} from the document?\n\nIt will be skipped by ` +
      'generation and left out of the .docx/PDF. It stays in this list (greyed ' +
      'out) with an "Add back" button, so a mistake is one click to undo.'
    )) return
    await api.setExcluded(s.number, excluded)
    setRows(await api.sections())
  }

  const removed = rows.filter((s) => s.excluded).length

  return (
    <aside id="sidebar">
      {removed > 0 && (
        <div className="removed-note">
          {removed} section{removed > 1 ? 's' : ''} removed from the document —
          use <span className="pillbtn demo">↩ Add back</span> to restore.
        </div>
      )}
      {rows.map((s) => (
        <div
          key={s.number}
          className={'srow lvl' + (s.level || 1) + (s.number === selected ? ' active' : '')
            + (s.excluded ? ' excluded' : '')}
          onClick={() => onSelect(s.number)}
        >
          <span className="snum">{s.number}</span>
          <span className="stitle">{s.title}</span>
          {!s.excluded && s.approved &&
            <span className="okmark" title="approved">✓</span>}
          {!s.excluded && !s.approved && s.has_content &&
            <span title="has content (draft)" style={{ color: 'var(--ok)' }}>●</span>}
          {s.excluded ? (
            <button className="pillbtn" title="Restore this section into the document"
                    onClick={(e) => toggle(e, s)}>↩ Add back</button>
          ) : (
            <button className="rowbtn" title="Remove from document (not applicable to this study)"
                    onClick={(e) => toggle(e, s)}>✕</button>
          )}
        </div>
      ))}
    </aside>
  )
}
