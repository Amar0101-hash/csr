// Render generated section content the way the source document is shown:
// clean paragraphs + real tables (parsed from markdown pipe syntax), instead of
// a raw monospace blob. Read-only; the editor is a separate toggle.

function parseBlocks(text) {
  const blocks = []
  let table = null
  let para = []
  const flushPara = () => {
    if (para.length) { blocks.push({ type: 'p', text: para.join('\n') }); para = [] }
  }
  const flushTable = () => {
    if (table?.length) blocks.push({ type: 'table', rows: table })
    table = null
  }
  for (const ln of (text || '').split('\n')) {
    const t = ln.trim()
    if (t.startsWith('|') && t.endsWith('|')) {
      flushPara()
      const cells = t.split('|').slice(1, -1).map((c) => c.trim())
      if (cells.length && cells.every((c) => /^:?-{2,}:?$/.test(c))) continue // md separator row
      if (!table) table = []
      table.push(cells)
    } else if (!t) {
      flushTable(); flushPara()
    } else {
      flushTable(); para.push(ln)
    }
  }
  flushPara(); flushTable()
  return blocks
}

export default function RenderedContent({ text }) {
  if (!text || !text.trim()) {
    return <div className="rc-empty">Not generated yet — click <b>Regenerate section</b>.</div>
  }
  const blocks = parseBlocks(text)
  return (
    <div className="rendered">
      {blocks.map((b, i) =>
        b.type === 'table' ? (
          <table className="srctable" key={i}>
            <tbody>
              {b.rows.map((r, ri) => (
                <tr key={ri}>{r.map((c, ci) => <td key={ci}>{c}</td>)}</tr>
              ))}
            </tbody>
          </table>
        ) : (
          <p className="rc-para" key={i}>{b.text}</p>
        ))}
    </div>
  )
}
