// Thin API client for the FastAPI backend (proxied via Vite in dev).
const j = (r) => r.json()

export const api = {
  sections: () => fetch('/api/sections').then(j),
  section: (n) => fetch(`/api/sections/${encodeURIComponent(n)}`).then(j),
  graph: (n) => fetch(`/api/graph/${encodeURIComponent(n)}`).then(j),
  concepts: (n) => fetch(`/api/concepts/${encodeURIComponent(n)}`).then(j),
  coverage: () => fetch('/api/coverage').then(j),
  generate: (n, custom_prompt, preview = false, method = 'hybrid') =>
    fetch(`/api/sections/${encodeURIComponent(n)}/generate`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ custom_prompt, preview, method }),
    }).then(j),
  acceptRegen: (n, payload) =>
    fetch(`/api/sections/${encodeURIComponent(n)}/accept`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(payload),
    }).then(j),
  audit: (n) => fetch(`/api/audit/${encodeURIComponent(n)}`).then(j),
  prompts: (n) => fetch(`/api/sections/${encodeURIComponent(n)}/prompts`).then(j),
  setActivePrompt: (n, version_id) =>
    fetch(`/api/sections/${encodeURIComponent(n)}/prompts/active`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ version_id }),
    }).then(j),
  numbersAudit: () => fetch('/api/numbers-audit').then(j),
  source: (doc) => fetch(`/api/source/${encodeURIComponent(doc)}`).then(j),
  save: (n, content) =>
    fetch(`/api/sections/${encodeURIComponent(n)}/save`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ content }),
    }).then(j),
  reportPreview: () => fetch('/api/report/preview').then(j),
  version: () => fetch('/api/version').then(j),
  approveSection: (n, approved) =>
    fetch(`/api/sections/${encodeURIComponent(n)}/approve`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ approved }),
    }).then(j),
  approveDoc: () => fetch('/api/version/approve', { method: 'POST' }).then(j),
  setExcluded: (n, excluded) =>
    fetch(`/api/sections/${encodeURIComponent(n)}/exclude`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ excluded }),
    }).then(j),
  generateFull: (effort = 'medium', method = 'hybrid') =>
    fetch('/api/report/generate', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ effort, method }),
    }).then(j),
  genStatus: () => fetch('/api/report/generate/status').then(j),
  compare: (query, graph_mode, k = 8) =>
    fetch('/api/compare', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ query, graph_mode, k }),
    }).then(j),
}

export const DOC_COLORS = {
  protocol: '#3b82f6', sap: '#a78bfa', mop: '#22d3ee',
  tfl_effectiveness: '#34d399', tfl_safety: '#f87171',
  tfl_conduct: '#fbbf24', tfl_listings: '#a3e635',
}

export const covColor = (n) =>
  n === 0 ? '#ef4444' : n < 4 ? '#f59e0b' : n < 8 ? '#eab308' : '#22c55e'
