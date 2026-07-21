// In-browser preview of the assembled report — the actual .docx rendered to HTML.
export default function ReportPreview({ state, onClose }) {
  if (!state) return null
  return (
    <div className="modal-overlay" onClick={onClose}>
      <div className="modal preview-modal" onClick={(e) => e.stopPropagation()}>
        <div className="modal-head">
          <b>Report preview</b>
          <span className="modal-sub">rendered from the assembled .docx</span>
          <button className="ghost hclose" onClick={onClose}>✕ Close</button>
        </div>
        <div className="preview-body">
          {state === 'loading'
            ? <div className="empty">Building preview…</div>
            : <div className="docx-preview" dangerouslySetInnerHTML={{ __html: state }} />}
        </div>
      </div>
    </div>
  )
}
