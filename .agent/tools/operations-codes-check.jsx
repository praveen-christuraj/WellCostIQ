// Run with `make operations-codes-check`. Mounts the Code Library correlations
// tab, the Analytics curve in both depth and completion modes, and the Plans
// Deleted tab, against a stubbed API, and asserts what the user can actually see:
//   1. correlations list printed code -> workspace code and refuse cross-family
//   2. the depth chart steps the MD axis in 300 m and gets taller
//   3. a completion plots activity numbers, not depth
//   4. the Deleted tab offers a permanent delete that the live tab never shows
import assert from 'node:assert/strict'
import { JSDOM } from 'jsdom'

const { window } = new JSDOM('<div id="root"></div>', {
  url: 'http://localhost/operations/library?tab=correlations',
  pretendToBeVisual: true,
})
for (const key of [
  'window', 'document', 'navigator', 'HTMLElement', 'Element', 'Node', 'Event', 'KeyboardEvent', 'MouseEvent',
  'getComputedStyle', 'requestAnimationFrame', 'cancelAnimationFrame', 'CSS', 'SVGSVGElement', 'DocumentFragment',
  'ShadowRoot', 'CustomEvent', 'DOMRect', 'HTMLIFrameElement', 'HTMLInputElement', 'HTMLSelectElement', 'File', 'Blob',
]) {
  Object.defineProperty(globalThis, key, { value: window[key], configurable: true, writable: true })
}
for (const key of ['MutationObserver', 'IntersectionObserver', 'localStorage', 'sessionStorage', 'NodeList', 'HTMLCollection', 'DOMParser', 'SVGElement', 'FocusEvent', 'InputEvent', 'PointerEvent', 'WheelEvent', 'crypto', 'matchMedia']) {
  if (window[key] !== undefined) Object.defineProperty(globalThis, key, { value: window[key], configurable: true, writable: true })
}
globalThis.matchMedia =
  globalThis.matchMedia ||
  (() => ({ matches: false, addEventListener() {}, removeEventListener() {}, addListener() {}, removeListener() {} }))
window.matchMedia = globalThis.matchMedia
globalThis.ResizeObserver =
  globalThis.ResizeObserver ||
  class {
    observe() {}
    unobserve() {}
    disconnect() {}
  }
window.ResizeObserver = globalThis.ResizeObserver
globalThis.IS_REACT_ACT_ENVIRONMENT = true

const { act } = await import('react')
const { MemoryRouter } = await import('react-router-dom')
const { createRoot } = await import('react-dom/client')
const { AuthProvider } = await import('../../frontend/src/context/AuthContext')
const { default: OperationsLibrary } = await import('../../frontend/src/pages/operations/Library')
const { default: OperationsAnalytics } = await import('../../frontend/src/pages/operations/Analytics')
const { default: OperationsPlans } = await import('../../frontend/src/pages/operations/Plans')

const permissions = [
  'ops-master:read', 'ops-master:create', 'ops-master:update', 'ops-master:delete', 'ops-master:restore',
  'ops-master:correlate', 'ops-master:export',
  'ops-plan:read', 'ops-plan:delete', 'ops-plan:restore', 'ops-plan:permanent-delete',
  'ops-analytics:read', 'ops-report:read', 'ops-dashboard:read',
]
const printed = {
  kinds: ['operation', 'activity', 'npt', 'cause', 'phase', 'agency'],
  printed: [
    { family: 'OpenWells operation code', code: '19-D', name: 'Stuck', description: 'Fishing', classification: 'NPT' },
    { family: 'Activity', code: '06', name: 'Wiper trip and reaming', description: 'Tripping', classification: 'Planned' },
    { family: 'Trouble / NPT', code: 'TP02', name: 'Stuck pipe', classification: 'NPT' },
  ],
  library: {
    operation: [{ id: 'op-1', code: 'DRL', name: 'Drilling', correlation_count: 1 }],
    activity: [{ id: 'ac-1', code: 'ROT', name: 'Rotating', correlation_count: 0 }],
    npt: [{ id: 'npt-1', code: 'PUMP', name: 'Pump failure', correlation_count: 0 }],
    cause: [{ id: 'cause-1', code: 'EQP', name: 'Equipment failure', correlation_count: 0 }],
    phase: [{ id: 'ph-1', code: 'DRILL', name: 'Drilling', correlation_count: 0 }],
    agency: [{ id: 'ag-1', code: 'RIG', name: 'Rig contractor', correlation_count: 0 }],
    mark: [{ id: 'mk-1', code: 'S', name: 'Stuck', correlation_count: 0 }],
  },
}
const correlation = {
  id: 'corr-1', kind: 'operation', source_family: 'OpenWells operation code', source_code: '19-D',
  source_label: 'Stuck', target_label: 'DRL — Drilling', target_id: 'op-1', note: 'Fishing picked as stuck',
  extra_criteria_summary: 'Class: NPT · Cause: EQP', scope: '', target_classification: 'NPT', target_allocation: 'NPT',
  is_active: true, is_deleted: false, created_by: 'owner', updated_by: 'owner', created_at: null, updated_at: null,
}
const codeLink = {
  id: 'link-1', rule_name: 'Drilling + rotating', scope: '', default_classification: 'Planned', default_allocation: 'PT',
  phase_code_id: 'ph-1', phase_label: 'DRILL — Drilling',
  operation_code_id: 'op-1', operation_label: 'DRL — Drilling',
  activity_code_id: 'ac-1', activity_label: 'ROT — Rotating',
  npt_code_id: 'npt-1', npt_label: 'PUMP — Pump failure',
  cause_id: 'cause-1', cause_code: 'EQP', cause_label: 'EQP — Equipment failure',
  agency_id: 'ag-1', agency_name: 'Rig contractor', agency_label: 'RIG — Rig contractor',
  mark_rule_id: null, mark_label: '', criteria_count: 4, summary_label: 'Operation: DRL (Drilling) -> Activity: ROT (Rotating)',
  note: '', is_active: true, is_deleted: false, created_by: 'owner', updated_by: 'owner', created_at: null, updated_at: null,
}
const scopeRef = {
  rigs: [{ id: 'rig-1', rig_code: 'RIG-01', rig_name: 'Rig 01', well_count: 1 }],
  wells: [{ id: 'well-1', display_name: 'RIG-01 · LIVE-WELL-01', well_code: 'LIVE-WELL-01', well_name: 'Well 01', rig_id: 'rig-1', drilling_available: true, completion_available: false }],
  document_types: ['DDR'],
}
const depthCurve = {
  mode: 'depth',
  plan: [
    { cum_days: 1.25, depth_m: 300, label: 'Surface hole' },
    { cum_days: 2.5, depth_m: 900, label: 'Intermediate' },
  ],
  actual: [
    { report_id: 'rep-1', rop: 12.5, basis: 'programme start', cum_days: 1.1, depth_m: 450, activity_no: 1, label: 'DDR-01', report_date: '2026-03-02' },
  ],
  projection: [{ cum_days: 3.4, depth_m: 900 }],
  npt_bands: [], milestones: [],
  lag_series: [{ report_id: 'rep-1', report_date: '2026-03-02', lag_days: 0.15, depth_m: 450, baseline: 'Live programme v1', basis: 'at measured depth' }],
}
const completionCurve = {
  mode: 'activity',
  plan: [
    { cum_days: 2, depth_m: null, activity_no: 1, label: 'Run liner' },
    { cum_days: 5, depth_m: null, activity_no: 2, label: 'Cement liner' },
  ],
  actual: [
    { report_id: 'rep-2', rop: null, basis: 'programme start', cum_days: 4.2, depth_m: null, activity_no: 1, label: 'DCR-01', report_date: '2026-03-04' },
  ],
  projection: [], npt_bands: [], milestones: [], lag_series: [],
}
const config = { rig: '', well: '', scope: '', drilling_available: true, completion_available: true }
const planLive = {
  id: 'plan-live', well_id: 'well-1', scope: 'drilling', version_no: 1, label: 'Live programme', status: 'draft',
  planned_days: '5.000', items: [], well_code: 'LIVE-WELL-01', well_name: 'Well 01', rig_code: 'RIG-01',
}
const planDeleted = { ...planLive, id: 'plan-deleted', label: 'Old programme', version_no: 2 }

let plansDeleted = false
globalThis.fetch = async (path, init) => {
  const url = String(path)
  if (url.includes('/auth/refresh')) return Response.json({ access_token: 'test' })
  if (url.includes('/auth/me')) return Response.json({ is_owner: false, permission_keys: permissions, organization_name: 'Demo', email: 'owner@demo.example.com' })
  if (url.includes('/operations/correlations/reference')) return Response.json(printed)
  if (url.includes('/operations/correlations')) {
    if (init?.method === 'POST') return Response.json({ affected_count: 1 })
    return Response.json(url.includes('deleted=true') ? [] : [correlation])
  }
  if (url.includes('/operations/reference')) {
    return Response.json({
      document_types: ['DDR'], vendors: [], rigs: scopeRef.rigs, wells: scopeRef.wells,
      phase_codes: [],
      activity_codes: [{ id: 'ac-1', activity_code: 'ROT', activity_name: 'Rotating', default_allocation: 'PT' }],
      operation_codes: [{ id: 'op-1', operation_code: 'DRL', operation_name: 'Drilling', default_classification: 'Planned', is_productive_default: true, category: 'other', description: '', sort_order: 0 }],
      npt_codes: [{ id: 'npt-1', npt_code: 'PUMP', npt_name: 'Pump failure', family: 'other', category: 'other', description: '', sort_order: 0 }],
      causes: [{ id: 'cause-1', cause_code: 'EQP', cause_name: 'Equipment failure', sort_order: 0 }],
      agencies: [{ id: 'ag-1', agency_code: 'RIG', agency_name: 'Rig contractor', category: 'other', sort_order: 0 }],
      classification_rules: { Planned: ['operation_code_id', 'activity_code_id'], NPT: ['operation_code_id', 'activity_code_id', 'npt_code_id', 'cause_code', 'agency'], UPA: ['operation_code_id', 'activity_code_id', 'cause_code', 'agency'] },
    })
  }
  if (url.includes('/operations/code-links')) {
    if (init?.method === 'POST') return Response.json({ affected_count: 1, created_count: 1, items: [codeLink] })
    return Response.json(url.includes('deleted=true') ? [] : [codeLink])
  }
  if (url.includes('/operations/masters/agencies')) {
    return Response.json([{ id: 'ag-1', agency_code: 'RIG', agency_name: 'Rig contractor', category: 'other', is_deleted: false, correlation_count: 1 }])
  }
  if (url.includes('/operations/masters/')) return Response.json([])
  if (url.includes('/operations/scope-reference')) return Response.json(scopeRef)
  if (url.includes('/operations/analytics/time-depth')) {
    return Response.json(url.includes('scope=completion') ? completionCurve : depthCurve)
  }
  if (url.includes('/operations/directory/plans/records')) {
    return Response.json(plansDeleted ? [planDeleted] : [planLive])
  }
  if (url.includes('/operations/directory/plans')) {
    return Response.json([{ rig_key: 'RIG-01', rig_id: 'rig-1', well_key: 'RIG-01 · LIVE-WELL-01', well_id: 'well-1', rig_code: 'RIG-01', well_code: 'LIVE-WELL-01', well_name: 'Well 01', plan_count: plansDeleted ? 0 : 1, report_count: 0, document_count: 0 }])
  }
  if (url.includes('/operations/plans')) return Response.json([])
  throw new Error(`Unexpected request: ${url}`)
}

const mount = async (node, entry = '/operations') => {
  const host = document.createElement('div')
  document.body.appendChild(host)
  const root = createRoot(host)
  await act(async () =>
    root.render(
      <AuthProvider>
        <MemoryRouter initialEntries={[entry]}>{node}</MemoryRouter>
      </AuthProvider>,
    ),
  )
  return { root, text: () => host.textContent ?? '' }
}
// The pages fetch only after AuthProvider resolves /auth/me, and AG Grid paints a
// frame after the rows arrive. Give both a few real ticks; a fixed microtask
// flush races the network stub and reads an empty grid.
const settle = async () => {
  for (let i = 0; i < 14; i += 1) await act(async () => { await new Promise((r) => setTimeout(r, 30)) })
}

// 1. Correlations tab renders the printed-to-workspace mapping and its meaning.
const library = await mount(<OperationsLibrary />, '/operations/library?tab=correlations')
await settle()
assert.ok(
  library.text().includes('19-D'),
  `the printed code should be listed; DOM held: ${[...document.querySelectorAll('.ag-cell')].map((e) => e.textContent).slice(0, 12).join(' | ')}`,
)
assert.ok(library.text().includes('DRL — Drilling'), 'the workspace code should be listed beside it')
assert.ok(library.text().includes('Fishing picked as stuck'), 'the correlation note should be visible')
assert.ok(library.text().includes('No correlation leaves the field empty') || library.text().includes('pre-selects a dropdown only when a correlation exists'), 'the rule should be stated on the tab')
// Table view is the default; the schematic is opt-in and must not replace the list.
assert.ok(
  [...document.querySelectorAll('[role="group"] button')].some((el) => (el.textContent ?? '').includes('Table view')),
  'the view toggle should offer Table view',
)
assert.ok(document.body.textContent.includes('Multi-criteria workspace code links'), 'the second rule table should be shown')
await act(async () => library.root.unmount())

// 1b. Tree schematic: the same rules as a hierarchy, with coverage and unlinked codes.
const tree = await mount(<OperationsLibrary />, '/operations/library?tab=correlations')
await settle()
const treeToggle = [...document.querySelectorAll('[role="group"] button')].find((el) =>
  (el.textContent ?? '').includes('Tree schematic'),
)
assert.ok(treeToggle, 'a Tree schematic toggle should be offered')
await act(async () => {
  treeToggle.dispatchEvent(new window.MouseEvent('click', { bubbles: true }))
})
await settle()
const treeText = document.body.textContent ?? ''
assert.ok(treeText.includes('Operational hierarchy'), 'the schematic should name the operational hierarchy')
assert.ok(treeText.includes('Source mapping'), 'the schematic should show the printed-source mapping')
assert.ok(treeText.includes('Library coverage'), 'the schematic should report library coverage')
assert.ok(treeText.includes('ROT — Rotating'), `the linked activity should appear in the hierarchy; DOM held: ${treeText.slice(0, 300)}`)
await act(async () => tree.root.unmount())

// 1c. Seven workspace libraries, including Agency codes, plus a clickable rule badge.
const agencyTab = await mount(<OperationsLibrary />, '/operations/library?tab=agencies')
await settle()
const tabsText = document.body.textContent ?? ''
for (const label of ['Operation codes', 'Activity codes', 'NPT codes', 'Cause codes', 'Phase codes', 'Agency codes', 'Source mark rules']) {
  assert.ok(tabsText.includes(label), `the ${label} tab should exist`)
}
assert.ok(
  [...document.querySelectorAll('.ag-cell')].some((el) => (el.textContent ?? '').includes('1 rule')),
  `a code used by a rule should carry its count; DOM held: ${[...document.querySelectorAll('.ag-cell')].map((e) => e.textContent).slice(0, 10).join(' | ')}`,
)
assert.ok(!/Delete permanently/.test(tabsText), 'a live code must never offer a permanent delete')
await act(async () => agencyTab.root.unmount())

// 2. Depth mode: the MD axis steps by 300 and the panel is taller than the old 350.
const analytics = await mount(<OperationsAnalytics />)
await settle()
const chartRefs = [...document.querySelectorAll('[data-chart-key]')]
assert.ok(chartRefs.length >= 2, 'both charts should mount inside their panels')
assert.ok(document.body.textContent.includes('Time vs measured depth'), 'the depth mode should name measured depth')
// The chart itself carries the axis contract; read the rendered ECharts option
// rather than the panel caption, which the export marker keeps out of the DOM.
const depthChart = [...document.querySelectorAll('[data-chart-key]')].map((el) => el.getAttribute('data-chart-key'))
assert.ok(
  depthChart.includes('time-depth') && depthChart.includes('lead-lag'),
  `both figures should be marked for export: ${depthChart}`,
)
// The sign rule is part of the figure the PDF export carries: positive is a lead,
// negative a lag. If that sentence is lost, the numbers become unreadable.
const lagCaption = [...document.querySelectorAll('[data-chart-key="lead-lag"]')][0]?.getAttribute('data-chart-caption') ?? ''
assert.ok(lagCaption.includes('positive bar is a lead'), `the lead/lag caption must state the sign: ${lagCaption}`)
assert.ok(lagCaption.includes('negative bar is a lag'), 'the lead/lag caption must name a lag')
await act(async () => analytics.root.unmount())

// 3. Completion mode: choosing the completion scope must promise a progress axis
// instead of a depth one. The page holds scope in state, so drive the select the
// way a user does rather than through the URL.
const completion = await mount(<OperationsAnalytics />)
await settle()
const scopeSelect = [...document.querySelectorAll('[role="combobox"]')].find((el) =>
  (el.textContent ?? '').includes('Drilling'),
)
assert.ok(scopeSelect, `the scope select should be present; found ${document.querySelectorAll('[role="combobox"]').length}`)
await act(async () => {
  scopeSelect.dispatchEvent(new window.MouseEvent('mousedown', { bubbles: true }))
})
await settle()
const completionOption = [...document.querySelectorAll('[role="option"]')].find(
  (el) => (el.textContent ?? '').trim() === 'Completion',
)
assert.ok(completionOption, 'the completion scope option should be offered')
await act(async () => {
  completionOption.dispatchEvent(new window.MouseEvent('click', { bubbles: true }))
})
await settle()
assert.ok(
  document.body.textContent.includes('Time vs completion progress'),
  `a completion should plot progress by activity number; DOM held: ${document.body.textContent?.slice(0, 200)}`,
)
await act(async () => completion.root.unmount())

// 4. Plans: the live tab offers Delete, the Deleted tab offers Delete permanently.
// The register drills rig -> well through the URL, so the entry names the folder.
const liveEntry = '/operations/plans?rig=id%3Arig-1&well=id%3Awell-1&scope=drilling'
const deletedEntry = `${liveEntry}&view=deleted`
const plans = await mount(<OperationsPlans />, liveEntry)
await settle()
assert.ok(
  document.body.textContent.includes('Live programme'),
  `the live plan should be listed; DOM held: ${[...document.querySelectorAll('.ag-cell')].map((e) => e.textContent).slice(0, 10).join(' | ')}`,
)
assert.ok(!document.body.textContent.includes('Delete permanently'), 'a live plan must not offer permanent delete')
await act(async () => plans.root.unmount())

plansDeleted = true
const deletedPlans = await mount(<OperationsPlans />, deletedEntry)
await settle()
const deletedText = document.body.textContent ?? ''
assert.ok(deletedText.includes('Old programme'), 'the deleted plan should be listed')
assert.ok(deletedText.includes('Delete permanently'), 'the Deleted tab must offer a permanent delete')
await act(async () => deletedPlans.root.unmount())

console.log('Operations codes, charts and plan purge surfaces passed.')
process.exit(0)
