// Daily-sheet entry checks. Run with `make entry-checks-check` (after `make ui-check`, which installs jsdom):
// cd frontend && NODE_PATH="$PWD/node_modules" ./node_modules/.bin/esbuild \
// ../.agent/tools/entry-checks-check.jsx --bundle --platform=node --format=esm --jsx=automatic \
// --outfile=node_modules/.cache/entry-checks-check.mjs --external:jsdom && node node_modules/.cache/entry-checks-check.mjs
import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import { JSDOM } from 'jsdom'

const dom = new JSDOM('<html><body><div id="root"></div></body></html>', { pretendToBeVisual: true, url: 'http://localhost/' })
const w = dom.window
w.matchMedia = query => ({ matches: false, media: query, addListener() {}, removeListener() {}, addEventListener() {}, removeEventListener() {} })
for (const key of [
  'window', 'document', 'navigator', 'HTMLElement', 'Element', 'Node', 'Event', 'KeyboardEvent', 'MouseEvent',
  'getComputedStyle', 'requestAnimationFrame', 'cancelAnimationFrame', 'CSS', 'SVGSVGElement', 'DocumentFragment',
  'ShadowRoot', 'CustomEvent', 'DOMRect', 'HTMLIFrameElement', 'HTMLInputElement', 'HTMLSelectElement', 'HTMLTextAreaElement',
]) {
  Object.defineProperty(globalThis, key, { value: w[key], configurable: true, writable: true })
}
for (const key of ['MutationObserver', 'IntersectionObserver', 'localStorage', 'sessionStorage', 'NodeList', 'HTMLCollection', 'DOMParser', 'SVGElement', 'FocusEvent', 'InputEvent', 'PointerEvent', 'WheelEvent', 'crypto']) {
  if (w[key] !== undefined) Object.defineProperty(globalThis, key, { value: w[key], configurable: true, writable: true })
}
globalThis.ResizeObserver = globalThis.ResizeObserver || class { observe() {} unobserve() {} disconnect() {} }
globalThis.IS_REACT_ACT_ENVIRONMENT = true

// ---------------------------------------------------------------------------
// Fixtures: one Draft sheet with a Day Rate service and two mud chemicals.
// ---------------------------------------------------------------------------
const baseline = {
  id: 'baseline-1', rate_baseline_id: 'rate-baseline-1', afe_id: 'afe1', afe_code: 'AFE-1', afe_name: 'Drilling',
  standard_currency: 'USD', total_amount: '100000', locked_at: '2026-10-01T00:00:00Z', locked_by: 'Owner',
  afe_estimate_saved_at: '2026-10-01T00:00:00Z',
  catalogue_rates: [
    { id: 'chem1', item_kind: 'mud_chemical', category: 'Mud Chemicals', item_code: 'BARITE', item_name: 'Barite', description: '', uom: 'MT', captured_rate: '10', currency: 'USD', revision_number: 1, effective_date: '2026-10-01', display_name: 'BARITE · Barite' },
    { id: 'chem2', item_kind: 'mud_chemical', category: 'Mud Chemicals', item_code: 'BENT', item_name: 'Bentonite', description: '', uom: 'MT', captured_rate: '20', currency: 'USD', revision_number: 1, effective_date: '2026-10-01', display_name: 'BENT · Bentonite' },
  ],
  service_rates: [
    { id: 'rate1', service_id: 'svc1', source_afe_line_id: 'afe-line-1', service_code: 'MUD-LOG', service_name: 'Mud logging', charging_basis: 'Day Rate', rate_kind: 'day_rate', charge_category: 'Operation', hole_section_id: null, section_label: '', phase_id: null, phase_label: '', unit_rate: '100', currency: 'USD', display_name: 'MUD-LOG · Mud logging' },
  ],
  budget_lines: [],
  sections: [{ hole_section_id: 'sec1', section_code: '17-1/2', section_name: 'Surface hole', from_depth: '0', to_depth: '1000', total_days: '10', phases: [{ phase_id: 'ph1', phase_code: 'DRILL', phase_name: 'Drilling', days: '10' }] }],
  exchange_rates: {},
}
const reference = {
  rigs: [{ id: 'rig1', rig_code: 'RIG-1', rig_name: 'Rig one', display_name: 'RIG-1 · Rig one' }],
  wells: [{ id: 'well1', rig_id: 'rig1', well_code: 'W-1', well_name: 'Well one', display_name: 'W-1 · Well one', status: 'active', config_status: 'configured', completion_status: 'active', completion_config_status: 'configured', sections: [] }],
  afes: [{ id: 'afe1', well_id: 'well1', afe_code: 'AFE-1', afe_name: 'Drilling', afe_type: 'Drilling', status: 'approved', configuration_scope: 'drilling', standard_currency: 'USD', total_cost: '100000', estimate_saved_at: '2026-10-01', display_name: 'AFE-1 — Drilling' }],
  activities: [{ id: 'act1', activity_code: 'DRL', activity_name: 'Drilling', classification: 'Planned', is_planned: true, is_upa: false, is_npt: false, display_name: 'DRL · Drilling' }],
  sub_activities: [{ id: 'sub1', well_id: 'well1', activity_id: 'act1', sub_activity_code: 'SA1', sub_activity_name: 'Drill ahead', display_name: 'SA1 · Drill ahead' }],
  services: [{ id: 'svc1', service_code: 'MUD-LOG', service_name: 'Mud logging', display_name: 'MUD-LOG · Mud logging' }],
  catalogue_items: [], vendors: [], currencies: ['USD'],
  charge_categories: [], charge_bases: [], quantity_units: [], classifications: [], consumable_categories: [], other_expense_types: [],
}
const lineCommon = {
  activity_id: 'act1', hole_section_id: 'sec1', phase_id: 'ph1', sub_activity_id: 'sub1', vendor_id: null, party_name: '',
  currency: 'USD', override_rate: null, override_reason: '', remarks: '',
  activity_code: 'DRL', activity_name: 'Drilling', section_code: '17-1/2', section_name: 'Surface hole',
  phase_code: 'DRILL', phase_name: 'Drilling', sub_activity_code: 'SA1', sub_activity_name: 'Drill ahead',
  sub_activity_party: 'Operations', vendor_code: '', vendor_name: '', classification: 'Planned',
  exchange_rate: '1', usd_exchange_rate: '1', actual_depth: null, actual_depth_entered: null, actual_depth_unit: 'm',
  rate_source: 'Locked AFE rate', rate_revision_number: 1, rate_effective_date: '2026-10-01',
  baseline_budget_line_id: null, budget_key: 'budget:1', budget_name: 'AFE budget',
}
const serviceLine = (quantity = '24', unit = 'days') => ({
  ...lineCommon, id: 's1', quantity, quantity_unit: unit, service_id: 'svc1', service_code: 'MUD-LOG', service_name: 'Mud logging',
  charging_basis: 'Day Rate', charge_category: 'Operation', baseline_service_rate_id: 'rate1', cost_items: [],
  captured_rate: '100', effective_rate: '100', amount: '2400', standard_amount: '2400', usd_amount: '2400',
})
const chemicalLine = (id, itemId, code, name, quantity, rate) => ({
  ...lineCommon, id, quantity, quantity_unit: 'unit', category: 'Mud Chemicals', item_kind: 'mud_chemical', item_id: itemId,
  item_code: code, item_name: name, uom: 'MT', catalogue_rate_snapshot_id: `${itemId}-snap`,
  captured_rate: rate, effective_rate: rate, amount: String(Number(quantity) * Number(rate)),
  standard_amount: String(Number(quantity) * Number(rate)), usd_amount: String(Number(quantity) * Number(rate)),
})
let savedLines = {
  services: [serviceLine()],
  consumables: [chemicalLine('c1', 'chem1', 'BARITE', 'Barite', '60', '10'), chemicalLine('c2', 'chem2', 'BENT', 'Bentonite', '4', '20')],
}
function makeDay(status = 'draft') {
  return {
    entry: {
      id: 'd1', daily_cost_code: 'DC-W-1-20261010-AFE-1', rig_id: 'rig1', rig_code: 'RIG-1', rig_name: 'Rig one',
      well_id: 'well1', well_code: 'W-1', well_name: 'Well one', afe_id: 'afe1', afe_code: 'AFE-1', afe_name: 'Drilling',
      afe_status: 'approved', cost_date: '2026-10-10', standard_currency: 'USD', remarks: '', status,
      lead_lag_kind: '', lead_lag_days: null, submitted_at: status === 'submitted' ? '2026-10-11T00:00:00Z' : null,
      submitted_by: status === 'submitted' ? 'Owner' : '', status_remarks: '',
      services_count: 1, consumables_count: 2, tangibles_count: 0, other_expenses_count: 0,
      services_total: '2400', consumables_total: '680', tangibles_total: '0', other_expenses_total: '0', total_cost: '3080',
      upa_total: '0', npt_total: '0', usd_exchange_rate: '1',
      services_total_usd: '2400', consumables_total_usd: '680', tangibles_total_usd: '0', other_expenses_total_usd: '0',
      total_cost_usd: '3080', upa_total_usd: '0', npt_total_usd: '0',
      actual_depth: null, depth_unit: 'm', section_depths: [],
      rate_baseline_locked_at: '2026-10-01T00:00:00Z', budget_baseline_locked_at: '2026-10-01T00:00:00Z',
      warning_count: 0, is_deleted: false, deleted_at: null,
      created_by: 'Owner', updated_by: 'Owner', created_at: '2026-10-10T00:00:00Z', updated_at: '2026-10-10T00:00:00Z',
    },
    services: savedLines.services, consumables: savedLines.consumables, tangibles: [], other_expenses: [],
    comparison: {
      effective_on: '2026-10-10', currency: 'USD', planned_total: '100000', actual_to_date: '3080', tracked_actual_to_date: '3080',
      other_expenses_to_date: '0', lih_cost_to_date: '0', actual_including_lih: '3080', afe_available: '96920', balance: '96920',
      over_budget: false, includes_draft_entries: true, upa_to_date: '0', npt_to_date: '0', groups: [], budget_lines: [],
      adjusted_planned_total: null, adjusted_balance: null, has_adjustment: false,
    },
    warnings: [], progress: null,
  }
}

const unreviewed = { reviewed: false, reviewed_by: '', reviewed_at: null, review_note: '' }
const quantityCheck = {
  key: 'unusual-quantity|consumable:chem1:mud_chemical:MT', code: 'unusual-quantity', severity: 'warning',
  title: 'BARITE · Barite: quantity looks too high',
  message: '60 MT is recorded for today, 10 times the usual 6 MT. This matches one zero too many, or the decimal point one place too far right: 6 MT would be usual.',
  basis: 'The 8 nearest sheets of this AFE usually carry 6 MT each (most between 5 MT and 8 MT).',
  scope: 'afe', subject_label: 'BARITE · Barite', lines: [{ group: 'consumables', index: 0 }], field: 'quantity',
  current_value: '60', current_display: '60 MT', suggested_value: '6', suggested_display: '6 MT',
  apply_to: [{ group: 'consumables', index: 0 }], usual_display: '6 MT', history_count: 8, fingerprint: 'q|60', ...unreviewed,
}
const dayRateCheck = {
  key: 'unusual-quantity|service:svc1:Day Rate:Operation:days', code: 'more-than-a-day', severity: 'warning',
  title: 'MUD-LOG · Mud logging: more than one day on a daily sheet',
  message: '24 days is recorded on a sheet that covers one day. If 24 hours was meant, change the unit to hours.',
  basis: 'A Day Rate line normally carries at most one day (24 hours) on a daily sheet.',
  scope: 'sheet', subject_label: 'MUD-LOG · Mud logging', lines: [{ group: 'services', index: 0 }], field: 'quantity_unit',
  current_value: 'days', current_display: '24 days', suggested_value: 'hours', suggested_display: '24 hours',
  apply_to: [{ group: 'services', index: 0 }], usual_display: '1 day', history_count: 0, fingerprint: 'q|24', ...unreviewed,
}
const totalNote = {
  key: 'unusual-day-total|sheet', code: 'unusual-day-total', severity: 'info',
  title: 'Day total several times the usual',
  message: 'This sheet totals USD 3,080, 5.1 times the usual USD 600 a day on this AFE.',
  basis: 'The 8 nearest sheets of this AFE total about USD 600 a day (most between USD 540 and USD 660).',
  scope: 'afe', subject_label: '', lines: [], field: '', current_value: null, current_display: '',
  suggested_value: null, suggested_display: '', apply_to: [], usual_display: 'USD 600', history_count: 8,
  fingerprint: 'total|3080', ...unreviewed,
}
const result = (checks, extra = {}) => ({
  entry_id: 'd1', enabled: true, checks,
  open_warnings: checks.filter(item => !item.reviewed && item.severity === 'warning').length,
  open_notices: checks.filter(item => !item.reviewed && item.severity !== 'warning').length,
  reviewed: checks.filter(item => item.reviewed).length, history_sheets: 8, ...extra,
})

let currentUser = { id: 'u1', email: 'owner@example.com', name: 'Owner', is_active: true, is_owner: true, permission_keys: [], organization_slug: 'acme', organization_name: 'Acme' }
let sheetStatus = 'draft'
let savedChecks = result([quantityCheck, dayRateCheck, totalNote])
let previewChecks = []
let checksFailure = null
let reviewFailure = null
let wellFailure = null
const sheetChecks = (entryId, code, date, status, checks) => ({
  entry_id: entryId, daily_cost_code: code, cost_date: date, status, afe_code: 'AFE-1', checks,
  open_warnings: checks.filter(item => !item.reviewed && item.severity === 'warning').length,
  open_notices: checks.filter(item => !item.reviewed && item.severity !== 'warning').length,
  reviewed: checks.filter(item => item.reviewed).length,
})
const wellResult = (sheets, extra = {}) => ({
  well_id: 'well1', enabled: true, sheets_checked: 31, sheets_with_findings: sheets.length,
  open_warnings: sheets.reduce((sum, item) => sum + item.open_warnings, 0),
  open_notices: sheets.reduce((sum, item) => sum + item.open_notices, 0),
  reviewed: sheets.reduce((sum, item) => sum + item.reviewed, 0), truncated: false, sheets, ...extra,
})
let wellChecks = wellResult([])
const requests = []
const popups = []
w.addEventListener('api-error', event => popups.push(event.detail))

globalThis.fetch = async (url, init = {}) => {
  const path = String(url)
  const method = init.method ?? 'GET'
  const payload = init.body ? JSON.parse(init.body) : null
  requests.push({ method, path: path.replace('/api/v1', ''), payload })
  const json = body => ({ ok: true, status: 200, json: async () => body })
  const fail = (status, detail) => ({ ok: false, status, json: async () => ({ detail }) })
  if (path.endsWith('/auth/refresh')) return json({ access_token: 'token' })
  if (path.endsWith('/auth/me')) return json(currentUser)
  if (path === '/api/health') return json({ api_version: '0.12.0' })
  if (path.endsWith('/daily-cost/entries/d1/baseline')) return json(baseline)
  if (path.endsWith('/daily-cost/entries/d1/refresh-service-rates')) return json(baseline)
  if (path.endsWith('/daily-cost/entries/d1/amendments')) return json([])
  if (path.endsWith('/daily-cost/wells/well1/checks')) {
    if (wellFailure) return fail(500, wellFailure)
    return json(wellChecks)
  }
  if (path.endsWith('/daily-cost/entries/d1/checks/review')) {
    if (reviewFailure) return fail(409, reviewFailure)
    const kept = new Set(payload.items.map(item => item.key))
    savedChecks = result(savedChecks.checks.map(item => kept.has(item.key)
      ? { ...item, reviewed: true, reviewed_by: 'Owner', reviewed_at: '2026-10-10T09:30:00Z', review_note: payload.note }
      : item))
    return json(savedChecks)
  }
  if (path.endsWith('/daily-cost/entries/d1/checks/reopen')) {
    const reopened = new Set(payload.keys)
    savedChecks = result(savedChecks.checks.map(item => reopened.has(item.key) ? { ...item, ...unreviewed } : item))
    return json(savedChecks)
  }
  if (path.endsWith('/daily-cost/entries/d1/checks')) {
    if (checksFailure) return fail(500, checksFailure)
    return json(savedChecks)
  }
  if (path.endsWith('/daily-cost/entries/d1/preview')) {
    return json({
      services: [], consumables: [], tangibles: [], other_expenses: [],
      services_total: '0', consumables_total: '0', tangibles_total: '0', other_expenses_total: '0', total_cost: '0',
      upa_total: '0', npt_total: '0', total_cost_usd: '0', actual_depth: null, depth_unit: 'm', section_depths: [],
      warnings: [], entry_checks: previewChecks,
    })
  }
  if (path.endsWith('/daily-cost/entries/d1') && method === 'PUT') {
    savedLines = {
      services: payload.services.map((line, index) => ({ ...savedLines.services[index], quantity: line.quantity, quantity_unit: line.quantity_unit })),
      consumables: payload.consumables.map((line, index) => ({ ...savedLines.consumables[index], quantity: line.quantity })),
    }
    savedChecks = result(previewChecks)
    return json(makeDay(sheetStatus))
  }
  if (path.endsWith('/daily-cost/entries/d1')) return json(makeDay(sheetStatus))
  if (path.includes('/daily-cost/entries')) return json([])
  if (path.endsWith('/daily-cost/reference')) return json(reference)
  if (path.includes('/costing-sets')) return json([])
  return json({})
}

for (const method of ['error', 'warn']) {
  const original = console[method]
  console[method] = (...args) => {
    const message = String(args[0] ?? '')
    if (message.startsWith('MUI:') || message.startsWith('An update to') || message.includes('AG Grid')) return
    original(...args)
  }
}

const { act, createElement } = await import('react')
const { createRoot } = await import('react-dom/client')
const { createMemoryRouter, RouterProvider } = await import('react-router-dom')
const { AuthProvider } = await import('../../frontend/src/context/AuthContext')
const DailyCostSheet = (await import('../../frontend/src/pages/DailyCostSheet')).default
const { WellEntryChecksCard } = await import('../../frontend/src/components/daily-cost/WellEntryChecksCard')
const {
  applyEntryCheck, entryCheckCounts, entryCheckSeverityLabel, entryCheckSummary, hasSuggestion,
} = await import('../../frontend/src/lib/entryChecks')

// ---------------------------------------------------------------------------
// 1. Applying a suggestion is a pure edit of the unsaved sheet.
// ---------------------------------------------------------------------------
const line = extra => ({
  id: null, activity_id: 'act1', hole_section_id: 'sec1', phase_id: 'ph1', sub_activity_id: 'sub1', vendor_id: null,
  party_name: '', quantity: '1', currency: 'USD', exchange_rate: null, actual_depth: null, actual_depth_unit: 'm',
  override_rate: null, override_reason: '', remarks: '', ...extra,
})
const sheet = {
  remarks: '', lead_lag_kind: '', lead_lag_days: null, usd_exchange_rate: null,
  services: [line({ service_id: 'svc1', baseline_service_rate_id: 'rate1', charging_basis: 'Day Rate', charge_category: 'Operation', quantity: '24', quantity_unit: 'days' })],
  consumables: [
    line({ category: 'Mud Chemicals', item_kind: 'mud_chemical', item_id: 'chem1', quantity: '60.0000000000' }),
    line({ category: 'Mud Chemicals', item_kind: 'mud_chemical', item_id: 'chem2', quantity: '4', currency: 'NGN', exchange_rate: '0.65', override_rate: '5000', override_reason: 'Spot purchase', actual_depth: '3000', actual_depth_unit: 'm' }),
  ],
  tangibles: [line({ tangible_id: 'tan1', quantity: '2', currency: 'NGN', exchange_rate: '0.00065' })],
  other_expenses: [line({ expense_type: 'other', expense_description: 'Boat hire', quantity_unit: 'unit', unit_rate: '900' })],
}
const frozen = JSON.stringify(sheet)
const finding = extra => ({ ...quantityCheck, ...extra })

const fixedQuantity = applyEntryCheck(sheet, quantityCheck)
assert.equal(fixedQuantity.consumables[0].quantity, '6', 'the suggested quantity is written to the named line')
assert.equal(fixedQuantity.consumables[1], sheet.consumables[1], 'other lines of the group are untouched')
assert.equal(fixedQuantity.services, sheet.services, 'other groups are untouched')
assert.equal(JSON.stringify(sheet), frozen, 'the original payload is never mutated')

const fixedUnit = applyEntryCheck(sheet, dayRateCheck)
assert.equal(fixedUnit.services[0].quantity_unit, 'hours', 'a unit suggestion changes the unit')
assert.equal(fixedUnit.services[0].quantity, '24', 'a unit suggestion keeps the figure')

const second = [{ group: 'consumables', index: 1 }]
const fixedRate = applyEntryCheck(sheet, finding({ field: 'override_rate', current_value: '5000', suggested_value: '500', apply_to: second }))
assert.equal(fixedRate.consumables[1].override_rate, '500', 'a rate suggestion changes the daily override')
assert.equal(fixedRate.consumables[1].override_reason, 'Spot purchase', 'the override reason stays with the line')

const fixedFx = applyEntryCheck(sheet, finding({
  field: 'exchange_rate', current_value: '0.65', suggested_value: '0.00065',
  apply_to: [{ group: 'consumables', index: 1 }, { group: 'tangibles', index: 0 }],
}))
assert.equal(fixedFx.consumables[1].exchange_rate, '0.00065', 'an exchange-rate suggestion reaches every listed line')
assert.equal(fixedFx.tangibles[0].exchange_rate, '0.00065', 'including lines of another group')

const fixedDepthUnit = applyEntryCheck(sheet, finding({ field: 'actual_depth_unit', current_value: 'm', suggested_value: 'ft', apply_to: second }))
assert.equal(fixedDepthUnit.consumables[1].actual_depth_unit, 'ft', 'a depth-unit suggestion changes the unit')
assert.equal(fixedDepthUnit.consumables[1].actual_depth, '3000', 'and keeps the entered depth')
const fixedDepth = applyEntryCheck(sheet, finding({ field: 'actual_depth', current_value: '3000', suggested_value: '300', apply_to: second }))
assert.equal(fixedDepth.consumables[1].actual_depth, '300', 'a depth suggestion changes the entered depth')

const fixedSheetFx = applyEntryCheck(sheet, finding({ field: 'usd_exchange_rate', suggested_value: '0.00065', apply_to: [], lines: [] }))
assert.equal(fixedSheetFx.usd_exchange_rate, '0.00065', 'the sheet conversion rate is a sheet field')
assert.equal(fixedSheetFx.consumables, sheet.consumables, 'and touches no line')

assert.equal(applyEntryCheck(sheet, totalNote), null, 'a finding without a suggestion applies nothing')
assert.equal(applyEntryCheck(sheet, finding({ current_value: '61' })), null, 'a line whose value changed since the finding is refused')
assert.equal(applyEntryCheck(sheet, finding({ apply_to: [{ group: 'consumables', index: 7 }] })), null, 'a line that no longer exists is refused')
assert.equal(applyEntryCheck(sheet, finding({ field: 'quantity_unit', suggested_value: 'hours', current_value: 'days' })), null, 'a unit suggestion is refused on a line without a unit')
assert.equal(applyEntryCheck(sheet, finding({ field: 'override_rate', suggested_value: '5', apply_to: [{ group: 'other_expenses', index: 0 }] })), null, 'other expenses have no override to correct')
assert.equal(applyEntryCheck(sheet, finding({ field: 'actual_depth_unit', suggested_value: 'yards', apply_to: second })), null, 'an unknown depth unit is refused')
assert.equal(applyEntryCheck(sheet, finding({ field: 'actual_depth', suggested_value: '300' })), null, 'a depth suggestion is refused on a line without a depth')
assert.equal(JSON.stringify(sheet), frozen, 'refusals leave the payload untouched')

assert.equal(hasSuggestion(quantityCheck), true)
assert.equal(hasSuggestion(totalNote), false)
assert.deepEqual(entryCheckCounts([quantityCheck, dayRateCheck, totalNote, { ...totalNote, key: 'x', reviewed: true }]), { warnings: 2, notices: 1, reviewed: 1, open: 3 })
assert.equal(entryCheckSummary({ warnings: 2, notices: 1, reviewed: 0, open: 3 }), '2 to check, 1 to note')
assert.equal(entryCheckSeverityLabel(quantityCheck), 'Check', 'severity is always worded, never colour alone')
assert.equal(entryCheckSeverityLabel(totalNote), 'Note')
assert.equal(entryCheckSeverityLabel({ ...totalNote, reviewed: true }), 'Kept as entered')

// ---------------------------------------------------------------------------
// The sheet itself.
// ---------------------------------------------------------------------------
let root = null
async function renderSheet() {
  if (root) { await act(async () => root.unmount()); root = null }
  document.body.innerHTML = '<div id="root"></div>'
  root = createRoot(document.getElementById('root'))
  const router = createMemoryRouter([{ path: '/daily-cost/sheet/:entryId', element: createElement(DailyCostSheet) }], { initialEntries: ['/daily-cost/sheet/d1'] })
  await act(async () => { root.render(createElement(AuthProvider, null, createElement(RouterProvider, { router }))) })
  await act(async () => { await new Promise(resolve => setTimeout(resolve, 400)) })
}
const wait = ms => act(async () => { await new Promise(resolve => setTimeout(resolve, ms)) })
const buttons = () => [...document.querySelectorAll('button')]
const buttonWith = text => buttons().find(button => button.textContent.trim() === text)
const buttonStarting = text => buttons().find(button => button.textContent.trim().startsWith(text))
const click = async element => { await act(async () => { element.click() }) }
const dialogs = () => [...document.querySelectorAll('[role="dialog"]')]
const panel = () => [...document.querySelectorAll('section')].find(section => section.querySelector('h2')?.textContent === 'Entry checks')
const panelText = () => panel()?.textContent ?? ''
const items = () => [...(panel()?.querySelectorAll('[role="listitem"]') ?? [])]
const itemWith = text => items().find(item => item.textContent.includes(text))
const within = (element, text) => [...element.querySelectorAll('button')].find(button => button.textContent.trim() === text)
function setNativeValue(element, value) {
  const prototype = element.tagName === 'TEXTAREA' ? w.HTMLTextAreaElement.prototype : w.HTMLInputElement.prototype
  Object.getOwnPropertyDescriptor(prototype, 'value').set.call(element, value)
  element.dispatchEvent(new w.Event('input', { bubbles: true }))
  element.dispatchEvent(new w.Event('change', { bubbles: true }))
}

// 2. A saved Draft shows its findings beside the sheet, with the evidence and the actions.
await renderSheet()
assert.ok(panel(), 'the sheet carries an Entry checks section')
assert.equal(panel().getAttribute('aria-labelledby'), panel().querySelector('h2').id, 'the section is named by its heading')
assert.ok(panelText().includes('2 to check'), 'open warnings are counted in words')
assert.ok(panelText().includes('1 to note'), 'open notices are counted in words')
assert.ok(panelText().includes('For the saved sheet.'), 'the panel says which state it describes')
assert.ok(panelText().includes('Advice only: nothing here stops you saving.'), 'the panel says it never blocks a save')
assert.equal(items().length, 3, 'every open finding is listed')
const barite = itemWith('BARITE · Barite: quantity looks too high')
assert.ok(barite, 'the finding is titled with the item it is about')
assert.ok(barite.textContent.includes('10 times the usual 6 MT'), 'the finding says how far off the value is')
assert.ok(barite.textContent.includes('The 8 nearest sheets of this AFE usually carry 6 MT each'), 'the finding states its evidence')
assert.ok(barite.textContent.includes('Check'), 'a warning is labelled Check')
assert.ok(itemWith('Day total several times the usual').textContent.includes('Note'), 'a notice is labelled Note')
const applyBarite = within(barite, 'Apply 6 MT')
assert.ok(applyBarite && !applyBarite.disabled, 'a finding explained by one slip offers the corrected value')
assert.equal(applyBarite.getAttribute('aria-label'), 'Apply 6 MT to BARITE · Barite', 'the apply action names its target')
assert.ok(within(barite, 'Keep as entered'), 'a saved Draft finding can be kept as entered')
assert.ok(!within(itemWith('Day total several times the usual'), 'Apply'), 'a finding without a suggestion offers none')
const lineButton = [...barite.querySelectorAll('button')].find(button => (button.getAttribute('aria-label') ?? '').startsWith('Open Consumables'))
assert.ok(lineButton, 'the finding names the line it is about')
assert.ok(lineButton.textContent.includes('17-1/2') && lineButton.textContent.includes('quantity 60'), 'the line is described as it reads on the sheet')
assert.equal(requests.filter(request => request.path === '/daily-cost/entries/d1/checks').length, 1, 'the saved findings are read once')

// 3. The line a finding is about opens in the normal line editor.
await click(lineButton)
await wait(100)
assert.equal(dialogs().length, 1, 'the line opens in its editor')
assert.ok(dialogs()[0].textContent.includes('BARITE'), 'the editor holds the line the finding is about')
await click(within(dialogs()[0], 'Cancel'))
await wait(100)
// The editor's own unsaved-input prompt may ask first; nothing was changed here.
if (dialogs().length > 1) { await click(within(dialogs()[dialogs().length - 1], 'Discard changes')); await wait(100) }
assert.equal(dialogs().length, 0, 'the editor closes via Cancel')
assert.equal(items().length, 3, 'opening a line changes no finding')

// 4. The whole section folds away, and says so to assistive technology.
const fold = buttonWith('Hide')
assert.equal(fold.getAttribute('aria-expanded'), 'true', 'the disclosure states that it is open')
const body = document.getElementById(fold.getAttribute('aria-controls'))
assert.ok(body && !body.hidden, 'the disclosure controls the findings')
await click(fold)
assert.equal(fold.getAttribute('aria-expanded'), 'false', 'the disclosure states that it is closed')
assert.ok(body.hidden, 'the findings are hidden')
assert.ok(fold.textContent.includes('2 to check, 1 to note'), 'the folded section still says what is open')
await click(fold)

// 5. Applying a suggestion edits the unsaved sheet only; the preview then judges the new value.
previewChecks = [dayRateCheck, totalNote]
requests.length = 0
await click(within(itemWith('BARITE · Barite'), 'Apply 6 MT'))
assert.ok(document.body.textContent.includes('Suggestion applied to BARITE · Barite: 6 MT'), 'the sheet confirms what was applied')
assert.ok(panelText().includes('Recalculating for your unsaved changes'), 'the findings are marked as being recalculated')
assert.ok(buttons().filter(button => button.textContent.trim().startsWith('Apply ')).every(button => button.disabled), 'no suggestion can be applied to a sheet that has moved on')
await wait(700)
const previewRequest = requests.find(request => request.method === 'PUT' && request.path === '/daily-cost/entries/d1/preview')
assert.ok(previewRequest, 'the corrected sheet is previewed')
assert.equal(previewRequest.payload.consumables[0].quantity, '6', 'the preview carries the applied value')
assert.equal(previewRequest.payload.consumables[1].quantity, '4', 'and leaves the other lines alone')
assert.ok(!requests.some(request => request.method === 'PUT' && request.path === '/daily-cost/entries/d1'), 'applying a suggestion saves nothing')
assert.ok(!itemWith('BARITE · Barite'), 'the corrected value is no longer a finding')
assert.equal(items().length, 2, 'the remaining findings stay')
assert.ok(panelText().includes('For your unsaved changes.'), 'the panel now describes the unsaved edits')
assert.ok(panelText().includes('To keep a value as it is, save the sheet first.'), 'reviews wait for the saved sheet')
assert.ok(!buttonWith('Keep as entered'), 'an unsaved finding cannot be kept as entered')
assert.ok(!within(itemWith('MUD-LOG · Mud logging'), 'Apply 24 hours').disabled, 'suggestions are available again once the preview is current')

// 6. Saving keeps the findings on screen and reads them again from the saved sheet.
requests.length = 0
await click(buttonWith('Save sheet'))
await wait(300)
assert.ok(requests.some(request => request.method === 'PUT' && request.path === '/daily-cost/entries/d1'), 'the sheet is saved')
assert.ok(requests.some(request => request.method === 'GET' && request.path === '/daily-cost/entries/d1/checks'), 'the saved findings are read again')
assert.ok(panelText().includes('For the saved sheet.'), 'the panel describes the saved sheet again')
assert.equal(items().length, 2, 'the saved sheet still carries the two remaining findings')

// 7. Keeping a value as entered is a deliberate, audited action with an optional note.
requests.length = 0
await click(within(itemWith('MUD-LOG · Mud logging'), 'Keep as entered'))
await wait(100)
const keepDialog = dialogs()[0]
assert.ok(keepDialog, 'keeping a value opens a confirmation')
assert.ok(keepDialog.textContent.includes('Keep this value as entered?'), 'the confirmation is titled')
assert.ok(keepDialog.textContent.includes('written to the audit trail'), 'the confirmation says the decision is audited')
assert.ok(keepDialog.textContent.includes('24 days is recorded on a sheet that covers one day'), 'the confirmation repeats the finding')
setNativeValue(keepDialog.querySelector('textarea'), '  Standby crew billed for the whole hitch  ')
await wait(50)
await click(within(keepDialog, 'Keep as entered'))
await wait(200)
const review = requests.find(request => request.method === 'POST' && request.path === '/daily-cost/entries/d1/checks/review')
assert.ok(review, 'the review is sent to the API')
assert.deepEqual(review.payload, {
  items: [{ key: dayRateCheck.key, fingerprint: dayRateCheck.fingerprint }], note: 'Standby crew billed for the whole hitch',
}, 'the review names the finding and the exact value it accepts')
assert.equal(dialogs().length, 0, 'a recorded review closes the confirmation')
assert.ok(panelText().includes('1 kept as entered'), 'the kept value is counted')
assert.ok(!panelText().includes('to check'), 'and no longer counts as open')
assert.ok(document.body.textContent.includes('Kept as entered: MUD-LOG · Mud logging'), 'the sheet confirms the review')

// 8. Kept values stay inspectable and can be reopened while the sheet is a Draft.
const keptToggle = buttonWith('Show 1 kept as entered')
assert.equal(keptToggle.getAttribute('aria-expanded'), 'false', 'kept values start folded away')
await click(keptToggle)
const kept = itemWith('MUD-LOG · Mud logging')
assert.ok(kept.textContent.includes('Kept as entered by Owner'), 'the reviewer is named')
assert.ok(kept.textContent.includes('Note: Standby crew billed for the whole hitch'), 'the note is shown')
assert.ok(!within(kept, 'Apply 24 hours'), 'a kept value offers no correction')
requests.length = 0
await click(within(kept, 'Reopen'))
await wait(200)
const reopen = requests.find(request => request.method === 'POST' && request.path === '/daily-cost/entries/d1/checks/reopen')
assert.deepEqual(reopen?.payload, { keys: [dayRateCheck.key] }, 'reopening names the finding')
assert.ok(panelText().includes('1 to check'), 'the reopened finding is open again')

// 9. A review the server refuses stays in the confirmation, with the reason beside the action.
reviewFailure = '1 of these entry checks changed after they were shown. Save the sheet, refresh the checks and review them again.'
await click(within(itemWith('MUD-LOG · Mud logging'), 'Keep as entered'))
await wait(100)
await click(within(dialogs()[0], 'Keep as entered'))
await wait(200)
assert.equal(dialogs().length, 1, 'a refused review keeps the confirmation open')
assert.ok(dialogs()[0].querySelector('[role="alert"]').textContent.includes('changed after they were shown'), 'the reason is shown as an alert in the confirmation')
await click(within(dialogs()[0], 'Cancel'))
await wait(350)
assert.equal(dialogs().length, 0, 'Cancel closes the confirmation')
reviewFailure = null

// 10. Submitting names what is still open, without blocking.
await click(buttonStarting('Submit'))
await wait(100)
assert.ok(dialogs()[0].textContent.includes('Entry checks still open on this sheet: 1 to check, 1 to note'), 'the submission confirmation names the open checks')
assert.ok(!within(dialogs()[0], 'Submit daily sheet').disabled, 'open checks never block the submission')
await click(within(dialogs()[0], 'Cancel'))
await wait(350)

// 11. A submitted sheet shows its findings read-only.
sheetStatus = 'submitted'
savedChecks = result([dayRateCheck, { ...totalNote, reviewed: true, reviewed_by: 'Owner', reviewed_at: '2026-10-10T09:30:00Z', review_note: 'Rig move day' }])
await renderSheet()
assert.ok(panelText().includes('1 to check') && panelText().includes('1 kept as entered'), 'a submitted sheet still shows its findings')
assert.ok(!buttonStarting('Apply '), 'a submitted sheet offers no correction')
assert.ok(!buttonWith('Keep as entered'), 'a submitted sheet takes no review')
assert.ok(!panel().querySelector('button[aria-label^="Open "]'), 'its lines are named but not editable')
assert.ok(itemWith('MUD-LOG · Mud logging').textContent.includes('Services · MUD-LOG · Mud logging'), 'the line is still described')
await click(buttonWith('Show 1 kept as entered'))
assert.ok(itemWith('Day total several times the usual').textContent.includes('Kept as entered by Owner'), 'a kept value stays inspectable')
assert.ok(!within(panel(), 'Reopen'), 'a submitted sheet cannot reopen a review')

// 12. So does a Draft for a user who may only read.
sheetStatus = 'draft'
currentUser = { ...currentUser, is_owner: false, permission_keys: ['daily-cost:read'] }
await renderSheet()
assert.equal(items().length, 1, 'a reader sees the open finding')
assert.ok(!buttonStarting('Apply ') && !buttonWith('Keep as entered'), 'a reader gets no actions')
currentUser = { ...currentUser, is_owner: true, permission_keys: [] }

// 13. Nothing found is said in one line, with what the sheet was compared with.
savedChecks = result([], { history_sheets: 3 })
await renderSheet()
assert.ok(panelText().includes('Nothing unusual'), 'a clean sheet says so')
assert.ok(panelText().includes('Compared with 3 other sheets of this AFE.'), 'and says what it was compared with')
assert.ok(panelText().includes('Quantities are compared once an item appears on 5 other sheets'), 'a short history is explained')
assert.ok(!buttonWith('Hide'), 'there is nothing to fold away')
savedChecks = result([], { history_sheets: 0 })
await renderSheet()
assert.ok(panelText().includes('This is the only sheet of its AFE so far'), 'a first sheet is explained')

// 14. A failed read is shown in the section with a retry, not as a detached pop-up.
checksFailure = 'The database is busy.'
savedChecks = result([quantityCheck])
popups.length = 0
await renderSheet()
assert.ok(panel().querySelector('[role="alert"]').textContent.includes('Entry checks could not be loaded. The database is busy.'), 'the failure is an alert inside the section')
assert.equal(popups.length, 0, 'background advice does not raise the global error pop-up')
assert.ok(buttonWith('Save sheet'), 'the sheet itself is unaffected')
checksFailure = null
await click(buttonWith('Retry'))
await wait(200)
assert.ok(!panel().querySelector('[role="alert"]'), 'a successful retry clears the failure')
assert.equal(items().length, 1, 'and shows the findings')

// 15. A deployment that turned entry checks off shows no section at all.
savedChecks = result([], { enabled: false, history_sheets: 0 })
await renderSheet()
assert.ok(!panel(), 'the section is absent when entry checks are turned off')

// 16. The well cost analysis points at the sheets that still carry an open check.
async function renderWellCard() {
  if (root) { await act(async () => root.unmount()); root = null }
  document.body.innerHTML = '<div id="root"></div>'
  root = createRoot(document.getElementById('root'))
  const router = createMemoryRouter([{ path: '/analysis', element: createElement(WellEntryChecksCard, { wellId: 'well1' }) }], { initialEntries: ['/analysis'] })
  await act(async () => { root.render(createElement(RouterProvider, { router })) })
  await wait(150)
}
const keptReview = { reviewed: true, reviewed_by: 'Owner', reviewed_at: '2026-10-10T09:30:00Z', review_note: '' }
wellChecks = wellResult([
  sheetChecks('d3', 'DC-W-1-20261012-AFE-1', '2026-10-12', 'draft', [quantityCheck, dayRateCheck, totalNote]),
  sheetChecks('d2', 'DC-W-1-20261011-AFE-1', '2026-10-11', 'submitted', [{ ...totalNote, ...keptReview }]),
  sheetChecks('d1', 'DC-W-1-20261010-AFE-1', '2026-10-10', 'submitted', [dayRateCheck]),
])
requests.length = 0
await renderWellCard()
assert.ok(requests.some(request => request.method === 'GET' && request.path === '/daily-cost/wells/well1/checks'), 'the card reads the well-level checks')
const card = () => [...document.querySelectorAll('section')].find(section => section.querySelector('h2')?.textContent === 'Entry checks')
assert.ok(card(), 'the well shows an Entry checks card')
assert.ok(card().textContent.includes('3 to check') && card().textContent.includes('1 to note') && card().textContent.includes('1 kept as entered'), 'the card counts the open and kept checks in words')
assert.ok(card().textContent.includes('2 of the 31 sheets of this well carry a value that looks mistyped'), 'the card says how many sheets are affected')
const sheetsToggle = buttonWith('Show sheets')
assert.equal(sheetsToggle.getAttribute('aria-expanded'), 'false', 'the sheet list starts folded away')
assert.equal(card().querySelectorAll('[role="listitem"]').length, 0, 'no sheet is listed while folded')
await click(sheetsToggle)
assert.equal(sheetsToggle.getAttribute('aria-expanded'), 'true', 'the disclosure states that it is open')
const sheetRows = [...card().querySelectorAll('[role="listitem"]')]
assert.equal(sheetRows.length, 2, 'only sheets with an open check are listed')
assert.equal(sheetRows[0].querySelector('a').getAttribute('href'), '/daily-cost/entries/d3', 'each sheet links to its daily sheet')
assert.ok(sheetRows[0].textContent.includes('Draft') && sheetRows[1].textContent.includes('Submitted'), 'each sheet shows its status in words')
assert.ok(sheetRows[0].textContent.includes('BARITE · Barite: quantity looks too high'), 'the open checks of a sheet are named')
assert.ok(card().textContent.includes('1 other sheet carries only values kept as entered.'), 'sheets with nothing open are summarised')
assert.ok(card().textContent.includes('Covers every sheet of the well'), 'the card says it ignores the period filter')
assert.equal(card().querySelectorAll('button').length, 1, 'the card corrects nothing itself: its only control is the disclosure')

wellChecks = wellResult([sheetChecks('d2', 'DC-W-1-20261011-AFE-1', '2026-10-11', 'submitted', [{ ...totalNote, ...keptReview }])])
await renderWellCard()
assert.ok(card().textContent.includes('Nothing open'), 'a well without open checks says so')
assert.ok(card().textContent.includes('No open check on the 31 sheets of this well.'), 'and says how many sheets were covered')
assert.ok(!buttonWith('Show sheets'), 'there is nothing to list')

wellChecks = wellResult([], { enabled: false, sheets_checked: 0 })
await renderWellCard()
assert.ok(!card(), 'the card is absent when entry checks are turned off')
wellChecks = wellResult([], { sheets_checked: 0 })
await renderWellCard()
assert.ok(!card(), 'the card is absent on a well without daily sheets')

wellFailure = 'The database is busy.'
popups.length = 0
await renderWellCard()
assert.ok(card().querySelector('[role="alert"]').textContent.includes('Entry checks could not be loaded. The database is busy.'), 'a failed read is an alert inside the card')
assert.equal(popups.length, 0, 'and raises no global error pop-up')
wellFailure = null
wellChecks = wellResult([sheetChecks('d1', 'DC-W-1-20261010-AFE-1', '2026-10-10', 'draft', [dayRateCheck])])
await click(buttonWith('Retry'))
await wait(150)
assert.ok(card().textContent.includes('1 of the 31 sheets of this well carries a value that looks mistyped'), 'a retry shows the checks')

// 17. Light and dark: the same words and the same actions under both themes.
const createCache = (await import('@emotion/cache')).default
const { CacheProvider } = await import('@emotion/react')
const { ThemeProvider } = await import('@mui/material')
const { buildTheme } = await import('../../frontend/src/theme')
const { EntryChecksPanel } = await import('../../frontend/src/components/daily-cost/EntryChecksPanel')
wellChecks = wellResult([sheetChecks('d3', 'DC-W-1-20261012-AFE-1', '2026-10-12', 'draft', [quantityCheck, totalNote])])
const themed = {}
for (const mode of ['light', 'dark']) {
  if (root) { await act(async () => root.unmount()); root = null }
  document.body.innerHTML = '<div id="root"></div>'
  root = createRoot(document.getElementById('root'))
  const theme = buildTheme(mode)
  assert.equal(theme.palette.mode, mode)
  // Plain text style nodes, so the generated CSS of this theme can be read back.
  const cache = createCache({ key: `entry-checks-${mode}`, speedy: false })
  const both = createElement('div', null,
    createElement(EntryChecksPanel, {
      checks: [quantityCheck, totalNote, { ...dayRateCheck, ...keptReview }], source: 'saved', loading: false, stale: false,
      error: '', onRetry: () => {}, editable: true, historySheets: 12,
      describeLine: line => `${line.group} line ${line.index + 1}`,
      onApply: () => true, onOpenLine: () => {}, onKeep: async () => {}, onReopen: async () => {},
    }),
    createElement(WellEntryChecksCard, { wellId: 'well1' }),
  )
  const router = createMemoryRouter([{ path: '/themes', element: both }], { initialEntries: ['/themes'] })
  await act(async () => {
    root.render(createElement(CacheProvider, { value: cache }, createElement(ThemeProvider, { theme }, createElement(RouterProvider, { router }))))
  })
  await wait(150)
  const sections = [...document.querySelectorAll('section')].filter(section => section.querySelector('h2')?.textContent === 'Entry checks')
  assert.equal(sections.length, 2, `${mode}: the sheet section and the well card both render`)
  const [sheetSection, wellCard] = sections
  for (const words of ['1 to check', '1 to note', '1 kept as entered']) {
    assert.ok(sheetSection.textContent.includes(words), `${mode}: the sheet section counts "${words}" in words`)
  }
  assert.ok(sheetSection.textContent.includes('Check') && sheetSection.textContent.includes('Note'), `${mode}: each check is labelled in words, not by colour alone`)
  assert.ok(within(sheetSection, `Apply ${quantityCheck.suggested_display}`), `${mode}: the suggestion can be applied`)
  assert.equal([...sheetSection.querySelectorAll('button')].filter(button => button.textContent.trim() === 'Keep as entered').length, 2, `${mode}: each open check can be kept as entered`)
  assert.ok(wellCard.textContent.includes('1 of the 31 sheets of this well carries a value that looks mistyped'), `${mode}: the well card names the affected sheets`)
  const css = [...document.querySelectorAll(`style[data-emotion^="entry-checks-${mode}"]`)].map(style => style.textContent).join('\n')
  assert.ok(css.length > 500, `${mode}: the theme's CSS was generated`)
  for (const tone of ['warning', 'info', 'neutral']) {
    assert.ok(css.includes(`var(--wcp-tone-${tone}-bg)`) && css.includes(`var(--wcp-tone-${tone}-fg)`), `${mode}: the ${tone} tag takes its colours from the design tokens`)
  }
  assert.ok(css.toLowerCase().includes(theme.palette.background.paper.toLowerCase()), `${mode}: the sections sit on the theme's paper surface`)
  assert.ok(css.toLowerCase().includes(theme.palette.text.secondary.toLowerCase()), `${mode}: secondary text uses the theme's muted colour`)
  themed[mode] = {
    text: sections.map(section => section.textContent).join('\n'),
    controls: sections.flatMap(section => [...section.querySelectorAll('button, a')].map(control => control.textContent.trim())),
    paper: theme.palette.background.paper, css,
  }
}
assert.equal(themed.dark.text, themed.light.text, 'both themes show exactly the same words')
assert.deepEqual(themed.dark.controls, themed.light.controls, 'both themes offer exactly the same actions')
assert.notEqual(themed.dark.paper, themed.light.paper, 'the two themes really differ')
assert.ok(!themed.dark.css.toLowerCase().includes(`background-color:${themed.light.paper.toLowerCase()}`), 'no light surface leaks into the dark theme')

// 18. While the findings describe an earlier state of the sheet, nothing can be acted on.
let applied = 0
let opened = 0
async function renderPanelAlone(stale) {
  if (root) { await act(async () => root.unmount()); root = null }
  document.body.innerHTML = '<div id="root"></div>'
  root = createRoot(document.getElementById('root'))
  await act(async () => {
    root.render(createElement(EntryChecksPanel, {
      checks: [quantityCheck, { ...dayRateCheck, ...keptReview }], source: 'saved', loading: false, stale,
      staleText: 'Recalculating for your unsaved changes…', error: '', onRetry: () => {}, editable: true, historySheets: 12,
      describeLine: line => `${line.group} line ${line.index + 1}`,
      onApply: () => { applied += 1; return true }, onOpenLine: () => { opened += 1 },
      onKeep: async () => {}, onReopen: async () => {},
    }))
  })
}
await renderPanelAlone(true)
assert.ok(panelText().includes('Recalculating for your unsaved changes…'), 'the section says why its findings are out of date')
await click(buttonStarting('Show 1 kept as entered'))
const waiting = ['Apply 6 MT', 'Keep as entered', 'consumables line 1', 'Reopen'].map(label => within(panel(), label))
assert.ok(waiting.every(Boolean), 'the actions stay visible while the findings are out of date')
assert.ok(waiting.every(button => button.disabled), 'and every one of them waits for the new result')
for (const button of waiting) await click(button)
assert.equal(applied + opened, 0, 'a waiting action does nothing')
assert.equal(within(panel(), 'Hide').disabled, false, 'the section can still be folded away')
await renderPanelAlone(false)
await click(buttonStarting('Show 1 kept as entered'))
assert.ok(['Apply 6 MT', 'Keep as entered', 'consumables line 1', 'Reopen'].every(label => within(panel(), label)?.disabled === false), 'the actions return with the new result')
await click(within(panel(), 'Apply 6 MT'))
await click(within(panel(), 'consumables line 1'))
assert.deepEqual([applied, opened], [1, 1], 'and act once each')

// 19. Neither component hardcodes a colour or adds motion: tokens only.
for (const file of ['src/components/daily-cost/EntryChecksPanel.tsx', 'src/components/daily-cost/WellEntryChecksCard.tsx', 'src/lib/entryChecks.ts']) {
  const source = readFileSync(file, 'utf8')
  assert.ok(!/#[0-9a-fA-F]{3,8}\b/.test(source), `${file} hardcodes no colour`)
  assert.ok(!/rgba?\(/.test(source), `${file} hardcodes no rgb colour`)
  assert.ok(!/animation|keyframes|transition:/.test(source), `${file} adds no motion`)
}

await act(async () => root.unmount())
root = null
w.close()
console.log('Entry checks check: all assertions passed')
process.exit(0)
