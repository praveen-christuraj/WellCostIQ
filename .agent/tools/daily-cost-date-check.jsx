// Draft daily-sheet date correction check. Run after make ui-check (which installs jsdom):
// cd frontend && NODE_PATH="$PWD/node_modules" ./node_modules/.bin/esbuild \
// ../.agent/tools/daily-cost-date-check.jsx --bundle --platform=node --format=esm --jsx=automatic \
// --outfile=node_modules/.cache/daily-cost-date-check.mjs --external:jsdom && node node_modules/.cache/daily-cost-date-check.mjs
import assert from 'node:assert/strict'
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

const baseline = {
  id: 'baseline-1', rate_baseline_id: 'rate-baseline-1', afe_id: 'afe1', afe_code: 'AFE-1', afe_name: 'Drilling',
  standard_currency: 'USD', total_amount: '1000', locked_at: '2026-10-01T00:00:00Z', locked_by: 'Owner',
  afe_estimate_saved_at: '2026-10-01T00:00:00Z', catalogue_rates: [], service_rates: [], budget_lines: [],
  sections: [], exchange_rates: {},
}
const reference = {
  rigs: [{ id: 'rig1', rig_code: 'RIG-1', rig_name: 'Rig one', display_name: 'RIG-1 · Rig one' }],
  wells: [{ id: 'well1', rig_id: 'rig1', well_code: 'W-1', well_name: 'Well one', display_name: 'W-1 · Well one', status: 'active', config_status: 'configured', completion_status: 'active', completion_config_status: 'configured', sections: [] }],
  afes: [{ id: 'afe1', well_id: 'well1', afe_code: 'AFE-1', afe_name: 'Drilling', afe_type: 'Drilling', status: 'approved', configuration_scope: 'drilling', standard_currency: 'USD', total_cost: '1000', estimate_saved_at: '2026-10-01', display_name: 'AFE-1 — Drilling' }],
  activities: [], sub_activities: [], services: [], catalogue_items: [], vendors: [], currencies: ['USD'],
  charge_categories: [], charge_bases: [], quantity_units: [], classifications: [], consumable_categories: [], other_expense_types: [],
}
function makeDay(status = 'draft', costDate = '2026-10-10') {
  return {
    entry: {
      id: 'd1', daily_cost_code: 'DC-W-1-20261010-AFE-1', rig_id: 'rig1', rig_code: 'RIG-1', rig_name: 'Rig one',
      well_id: 'well1', well_code: 'W-1', well_name: 'Well one', afe_id: 'afe1', afe_code: 'AFE-1', afe_name: 'Drilling',
      afe_status: 'approved', cost_date: costDate, standard_currency: 'USD', remarks: '', status,
      lead_lag_kind: '', lead_lag_days: null, submitted_at: status === 'submitted' ? '2026-10-11T00:00:00Z' : null,
      submitted_by: status === 'submitted' ? 'Owner' : '', status_remarks: '',
      services_count: 0, consumables_count: 0, tangibles_count: 0, other_expenses_count: 0,
      services_total: '0', consumables_total: '0', tangibles_total: '0', other_expenses_total: '0', total_cost: '0',
      upa_total: '0', npt_total: '0', usd_exchange_rate: '1',
      services_total_usd: '0', consumables_total_usd: '0', tangibles_total_usd: '0', other_expenses_total_usd: '0',
      total_cost_usd: '0', upa_total_usd: '0', npt_total_usd: '0',
      actual_depth: null, depth_unit: 'm', section_depths: [],
      rate_baseline_locked_at: '2026-10-01T00:00:00Z', budget_baseline_locked_at: '2026-10-01T00:00:00Z',
      warning_count: 0, is_deleted: false, deleted_at: null,
      created_by: 'Owner', updated_by: 'Owner', created_at: '2026-10-10T00:00:00Z', updated_at: '2026-10-10T00:00:00Z',
    },
    services: [], consumables: [], tangibles: [], other_expenses: [],
    comparison: {
      effective_on: costDate, currency: 'USD', planned_total: '1000', actual_to_date: '0', tracked_actual_to_date: '0',
      other_expenses_to_date: '0', lih_cost_to_date: '0', actual_including_lih: '0', afe_available: '1000', balance: '1000',
      over_budget: false, includes_draft_entries: true, upa_to_date: '0', npt_to_date: '0', groups: [], budget_lines: [],
      adjusted_planned_total: null, adjusted_balance: null, has_adjustment: false,
    },
    warnings: [], progress: null,
  }
}
const preview = {
  services: [], consumables: [], tangibles: [], other_expenses: [],
  services_total: '0', consumables_total: '0', tangibles_total: '0', other_expenses_total: '0', total_cost: '0',
  upa_total: '0', npt_total: '0', total_cost_usd: '0', actual_depth: null, depth_unit: 'm', section_depths: [], warnings: [],
}

let currentUser = { id: 'u1', email: 'owner@example.com', name: 'Owner', is_active: true, is_owner: true, permission_keys: [], organization_slug: 'acme', organization_name: 'Acme' }
let sheetStatus = 'draft'
let patchError = null
const requests = []
globalThis.fetch = async (url, init = {}) => {
  const path = String(url)
  const method = init.method ?? 'GET'
  const payload = init.body ? JSON.parse(init.body) : null
  requests.push({ method, path: path.replace('/api/v1', ''), payload })
  const json = body => ({ ok: true, status: 200, json: async () => body })
  if (path.endsWith('/auth/refresh')) return json({ access_token: 'token' })
  if (path.endsWith('/auth/me')) return json(currentUser)
  if (path === '/api/health') return json({ api_version: '0.3.0' })
  if (path.endsWith('/daily-cost/entries/d1/baseline')) return json(baseline)
  if (path.endsWith('/daily-cost/entries/d1/refresh-service-rates')) return json(baseline)
  if (path.endsWith('/daily-cost/entries/d1/amendments')) return json([])
  if (path.endsWith('/daily-cost/entries/d1/preview')) return json(preview)
  if (path.endsWith('/daily-cost/entries/d1/date') && method === 'PATCH') {
    if (patchError) return { ok: false, status: 409, json: async () => ({ detail: patchError }) }
    return json(makeDay('draft', payload.cost_date))
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
    if (message.startsWith('MUI:') || message.startsWith('An update to')) return
    original(...args)
  }
}

const { act, createElement } = await import('react')
const { createRoot } = await import('react-dom/client')
const { createMemoryRouter, RouterProvider } = await import('react-router-dom')
const { AuthProvider } = await import('../../frontend/src/context/AuthContext')
const DailyCostSheet = (await import('../../frontend/src/pages/DailyCostSheet')).default

let root = null
async function renderSheet() {
  if (root) { await act(async () => root.unmount()); root = null }
  document.body.innerHTML = '<div id="root"></div>'
  root = createRoot(document.getElementById('root'))
  const router = createMemoryRouter([{ path: '/daily-cost/sheet/:entryId', element: createElement(DailyCostSheet) }], { initialEntries: ['/daily-cost/sheet/d1'] })
  await act(async () => { root.render(createElement(AuthProvider, null, createElement(RouterProvider, { router }))) })
  await act(async () => { await new Promise(resolve => setTimeout(resolve, 350)) })
}
const buttonWith = text => [...document.querySelectorAll('button')].find(button => button.textContent.includes(text))
const dialog = () => document.querySelector('[role="dialog"]')
function setNativeValue(element, value) {
  const prototype = element.tagName === 'TEXTAREA' ? w.HTMLTextAreaElement.prototype : w.HTMLInputElement.prototype
  Object.getOwnPropertyDescriptor(prototype, 'value').set.call(element, value)
  element.dispatchEvent(new w.Event('input', { bubbles: true }))
  element.dispatchEvent(new w.Event('change', { bubbles: true }))
}
const wait = ms => act(async () => { await new Promise(resolve => setTimeout(resolve, ms)) })

// 1. A draft sheet exposes the date correction action.
await renderSheet()
assert.ok(document.body.textContent.includes('Sheet date'), 'the sheet shows its operating date prominently')
assert.ok(buttonWith('Change date'), 'a draft sheet offers Change date')

// 2. Correcting the date keeps unsaved cost edits and sends only the new date.
const remarks = document.querySelector('textarea')
assert.ok(remarks, 'the daily remarks field is available')
setNativeValue(remarks, 'Unsaved shift note')
await wait(50)
requests.length = 0
await act(async () => { buttonWith('Change date').click() })
await wait(80)
assert.ok(dialog(), 'the change-date dialog opens')
const dateInput = dialog().querySelector('input[type="date"]')
assert.ok(dateInput, 'the dialog has a date picker')
assert.equal(dateInput.value, '2026-10-10', 'the picker starts on the saved sheet date')
setNativeValue(dateInput, '2026-10-12')
await wait(50)
await act(async () => { buttonWith('Save new date').click() })
await wait(150)
const patch = requests.find(request => request.method === 'PATCH' && request.path === '/daily-cost/entries/d1/date')
assert.ok(patch, 'the dialog PATCHes the dedicated date endpoint')
assert.deepEqual(patch.payload, { cost_date: '2026-10-12' }, 'only the corrected operating date is sent')
assert.ok(!dialog(), 'a successful date change closes the dialog')
assert.ok(document.body.textContent.includes('Sheet date changed from'), 'the sheet confirms the date correction')
assert.equal(document.querySelector('textarea').value, 'Unsaved shift note', 'unsaved cost edits survive the date correction')
await wait(600)
const previewRequest = requests.find(request => request.method === 'PUT' && request.path === '/daily-cost/entries/d1/preview')
assert.ok(previewRequest, 'the unsaved draft is previewed again after the date move')
assert.equal(previewRequest.payload.remarks, 'Unsaved shift note', 'the preview still carries the unsaved edits')

// 3. A duplicate date keeps the dialog open and shows the server conflict beside the field.
patchError = 'A daily cost sheet already exists for W-1, AFE-1 and 2026-10-11. Choose another date.'
await renderSheet()
await act(async () => { buttonWith('Change date').click() })
await wait(80)
setNativeValue(dialog().querySelector('input[type="date"]'), '2026-10-11')
await wait(50)
await act(async () => { buttonWith('Save new date').click() })
await wait(150)
assert.ok(dialog(), 'a rejected date change keeps the dialog open')
assert.ok(dialog().textContent.includes('already exists'), 'the duplicate-date conflict is shown in the dialog')
patchError = null

// 4. Submitted sheets stay read-only.
sheetStatus = 'submitted'
await renderSheet()
assert.ok(!buttonWith('Change date'), 'a submitted sheet does not offer Change date')
assert.ok(document.body.textContent.includes('Submitted — the operating date is locked.'), 'the submitted date is labelled locked')

// 5. A draft without update permission cannot change the date.
sheetStatus = 'draft'
currentUser = { ...currentUser, is_owner: false, permission_keys: ['daily-cost:read'] }
await renderSheet()
assert.ok(!buttonWith('Change date'), 'read-only drafts do not offer Change date')
assert.ok(document.body.textContent.includes('read-only without the Daily Cost update permission'), 'the permission boundary is explained')

await act(async () => root.unmount())
root = null
w.close()
console.log('Daily cost date correction check: all assertions passed')
process.exit(0)
