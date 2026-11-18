// Run with `make operations-overview-check`. Mount the page with both current and
// older dashboard rows so an absent block list cannot take down the whole route.
import assert from 'node:assert/strict'
import { JSDOM } from 'jsdom'

const { window } = new JSDOM('<div id="root"></div>', { url: 'http://localhost/operations', pretendToBeVisual: true })
for (const key of ['window', 'document', 'HTMLElement', 'DocumentFragment', 'Element', 'Node', 'getComputedStyle']) {
  globalThis[key] = window[key]
}
globalThis.IS_REACT_ACT_ENVIRONMENT = true

const { act } = await import('react')
const {MemoryRouter} = await import('react-router-dom')
const { createRoot } = await import('react-dom/client')
const { AuthProvider } = await import('../../frontend/src/context/AuthContext')
const { default: OperationsOverview } = await import('../../frontend/src/pages/operations/Overview')

const header = { well_code_snapshot: 'W-01', rig_name_snapshot: 'Rig A', report_date: '2026-11-17', scope: 'drilling', report_type: 'DDR', status: 'draft', depth_end_m: '1200' }
const recent_reports = [
  { ...header, id: 'logged', blocks: [{ id: 'b1' }, { id: 'b2' }] },
  { ...header, id: 'empty', blocks: [] },
  { ...header, id: 'legacy', _blocks: [{ id: 'b3' }] },
]
const kpis = {
  total_reports: 3, draft_reports: 3, approved_reports: 0, submitted_reports: 0, reports_awaiting_review: 0,
  total_logged_hours: 6, planned_hours: 6, npt_hours: 0, upa_hours: 0, unaccounted_hours: 0,
  wells_covered: 1, wells_total: 1, avg_rop: null, lag_days: null, npt_pct: 0, productive_pct: 100, data_quality_score: 100,
}
globalThis.fetch = async path => {
  if (path === '/api/v1/operations/dashboard') return Response.json({ kpis, recent_reports, daily_trend: [], npt_by_code: [], npt_by_agency: [], missing_reports: [] })
  if (path === '/api/v1/operations/scope-reference') return Response.json({ rigs: [], wells: [] })
  if (path === '/api/v1/auth/refresh') return Response.json({access_token:'test'})
  if (path === '/api/v1/auth/me') return Response.json({is_owner:false,permission_keys:['ops-dashboard:read','ops-report:read']})
  throw new Error(`Unexpected request: ${path}`)
}

const root = createRoot(document.getElementById('root'))
await act(async () => root.render(<AuthProvider><MemoryRouter><OperationsOverview /></MemoryRouter></AuthProvider>))
for (const [id, count] of [['logged', '2 blocks'], ['empty', '0 blocks'], ['legacy', 'Block count unavailable']]) {
  const open = document.querySelector(`a[href="/operations/reports/${id}"]`)
  assert.ok(open, `Report ${id} should still open from Recent reports`)
  assert.ok(open.parentElement.textContent.includes(count), `Report ${id} should show ${count}`)
}
await act(async () => root.unmount())
window.close()
console.log('Well Operations Overview: populated, empty and legacy recent reports passed.')
process.exit(0)
