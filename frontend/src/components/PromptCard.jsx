import { useState } from 'react'

// Shows the exact prompt sent to the LLM for this section, with versions:
// v0 is the default (auto-built) prompt; regenerating with a custom instruction
// adds a version. The active version is the one used going forward — the user can
// pin any version as active.
export default function PromptCard({ data, onPin, onUseInstruction }) {
  const [selId, setSelId] = useState(null)
  const [open, setOpen] = useState(false)

  const versions = data?.versions || []
  if (!versions.length) {
    return (
      <div className="card">
        <h3>Prompt sent to the LLM</h3>
        <div style={{ color: 'var(--muted)' }}>
          No prompt recorded yet — generate this section to capture the default prompt.
        </div>
      </div>
    )
  }
  const sel = selId != null ? selId : data.active
  const cur = versions.find((v) => v.id === sel) || versions[0]
  const isActive = data.active === cur.id

  return (
    <div className="card">
      <div className="card-head">
        <h3>Prompt sent to the LLM &nbsp;<span className="badge method">{cur.kind || 'prose'}</span></h3>
        <div style={{ display: 'flex', gap: 8, alignItems: 'center' }}>
          <select className="cmode" value={sel} onChange={(e) => setSelId(Number(e.target.value))}>
            {versions.map((v) => (
              <option key={v.id} value={v.id}>
                v{v.id} · {v.label}{v.id === data.active ? ' — active' : ''}
              </option>
            ))}
          </select>
          {isActive
            ? <span className="badge ok">active</span>
            : <button className="linkbtn" onClick={() => onPin?.(cur.id)}>Pin as active</button>}
        </div>
      </div>

      {cur.custom_instruction
        ? (
          <div className="prompt-instr">
            <b>Custom instruction:</b> “{cur.custom_instruction}”
            {onUseInstruction && (
              <button className="linkbtn" style={{ marginLeft: 8 }}
                      onClick={() => onUseInstruction(cur.custom_instruction)}>
                load into regenerate box
              </button>
            )}
          </div>
        )
        : <div className="prompt-instr">Default prompt (no custom instruction).</div>}

      <button className="linkbtn" onClick={() => setOpen((o) => !o)}>
        {open ? 'hide' : 'show'} prompt sent (guidance + retrieved sources)
      </button>
      {open && <pre className="cypher">{cur.user}</pre>}
    </div>
  )
}
