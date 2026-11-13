// Well status and plan status ladder regression check.
//
//   Well status  Upcoming -> Active -> Final review -> Completed
//   Plan status  Draft -> Configured -> Completed
//
// The server owns the rules (backend/app/services/well_lifecycle.py, covered by
// backend/tests/test_well_lifecycle.py). This check covers what the UI does with
// them: one wording and tone everywhere, a Wells register with one tab per well
// status, a status menu that offers exactly the moves the server lists (forward
// and one-step rollback, blocked moves explained, moves that are not the user's
// hidden), the confirmation dialog, and the stylesheet rule that keeps the hidden
// print sheet out of the on-screen View.
//
// Run:
//   cd frontend && NODE_PATH="$PWD/node_modules" ./node_modules/.bin/esbuild \
//     ../.agent/tools/well-lifecycle-check.jsx --bundle --platform=node --format=esm --jsx=automatic \
//     --outfile=node_modules/.cache/well-lifecycle-check.mjs --loader:.jsx=jsx --log-level=error \
//     --external:jsdom && node node_modules/.cache/well-lifecycle-check.mjs
import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import { JSDOM } from 'jsdom'

const dom = new JSDOM('<html><body><div id="root"></div></body></html>', { pretendToBeVisual: true, url: 'http://localhost/' })
const w = dom.window
w.matchMedia = query => ({ matches: false, media: query, addListener() {}, removeListener() {}, addEventListener() {}, removeEventListener() {} })
for (const key of [
  'window', 'document', 'navigator', 'HTMLElement', 'Element', 'Node', 'Event', 'KeyboardEvent', 'MouseEvent',
  'getComputedStyle', 'requestAnimationFrame', 'cancelAnimationFrame', 'CSS', 'SVGSVGElement', 'DocumentFragment',
  'ShadowRoot', 'CustomEvent', 'DOMRect', 'HTMLIFrameElement', 'HTMLInputElement', 'HTMLSelectElement',
]) {
  Object.defineProperty(globalThis, key, { value: w[key], configurable: true, writable: true })
}
for (const key of ['MutationObserver', 'IntersectionObserver', 'localStorage', 'sessionStorage', 'NodeList', 'HTMLCollection', 'DOMParser', 'SVGElement', 'FocusEvent', 'InputEvent', 'PointerEvent', 'WheelEvent', 'crypto', 'HTMLTextAreaElement']) {
  if (w[key] !== undefined) Object.defineProperty(globalThis, key, { value: w[key], configurable: true, writable: true })
}
globalThis.ResizeObserver = globalThis.ResizeObserver || class { observe() {} unobserve() {} disconnect() {} }
globalThis.IS_REACT_ACT_ENVIRONMENT = true

let passed = 0
const check = (condition, message) => { assert.ok(condition, message); passed += 1 }
const same = (actual, expected, message) => { assert.deepEqual(actual, expected, message); passed += 1 }

// ---------------------------------------------------------------------------
// 1. One vocabulary: labels, tones and the "takes new work" rule.
// ---------------------------------------------------------------------------
const rigWell = await import('../../frontend/src/lib/rigWell')
same(rigWell.WELL_STATUSES, ['upcoming', 'active', 'final_review', 'completed'], 'the well ladder has four steps, in order')
same(rigWell.PLAN_STATUSES, ['draft', 'configured', 'completed'], 'the plan ladder has three steps, in order')
same(rigWell.WELL_STATUSES.map(rigWell.trackingLabel), ['Upcoming', 'Active', 'Final review', 'Completed'], 'well status wording')
same(rigWell.PLAN_STATUSES.map(rigWell.planLabel), ['Draft', 'Configured', 'Completed'], 'plan status wording')
same(rigWell.WELL_STATUSES.map(rigWell.isOpenWellStatus), [true, true, false, false],
  'only an Upcoming or Active scope takes new work; Final review and Completed are closed')
check(rigWell.wellStatusTone('final_review') === 'warning' && rigWell.wellStatusTone('completed') === 'neutral',
  'Final review asks for attention, Completed is neutral')
check(rigWell.planStatusTone('configured') === 'success' && rigWell.planStatusTone('draft') === 'warning',
  'a Configured plan is the good state, a Draft plan still needs work')
const live = { drilling_is_deleted: false, completion_is_deleted: false }
const rollUp = (status, completion_status, extra = {}) => rigWell.wellTrackingStatus({ ...live, status, completion_status, ...extra })
same([
  rollUp('upcoming', 'upcoming'), rollUp('active', 'upcoming'), rollUp('completed', 'upcoming'),
  rollUp('final_review', 'completed'), rollUp('final_review', 'final_review'), rollUp('completed', 'completed'),
  rollUp('completed', 'active', { completion_is_deleted: true }),
], ['upcoming', 'active', 'active', 'final_review', 'final_review', 'completed', 'completed'],
'the well-level status rolls the live scopes up exactly like the server does')

// ---------------------------------------------------------------------------
// 2. Fixtures: what the API returns for wells on every step of the ladder.
// ---------------------------------------------------------------------------
const move = (action, label, ladder, direction, to_status, to_plan, extra = {}) => ({
  action, label, description: `${label} — description`, ladder, direction, to_status, to_plan,
  permission: direction === 'rollback' ? 'rig-well:rollback' : 'rig-well:update', permitted: true, allowed: true, reason: '', ...extra,
})
const OFFERED = {
  'upcoming/draft': [
    move('configure', 'Mark Drilling plan as Configured', 'plan', 'forward', 'upcoming', 'configured'),
    move('start', 'Start Drilling (Active)', 'well', 'forward', 'active', 'draft',
      { allowed: false, reason: 'Mark the drilling plan as Configured first.' }),
  ],
  'active/configured': [
    move('draft', 'Reopen Drilling plan as Draft', 'plan', 'rollback', 'active', 'draft'),
    move('defer', 'Return Drilling to Upcoming', 'well', 'rollback', 'upcoming', 'configured'),
    move('final_review', 'Move Drilling to Final review', 'well', 'forward', 'final_review', 'completed'),
  ],
  'final_review/completed': [
    move('reactivate', 'Return Drilling to Active', 'well', 'rollback', 'active', 'configured'),
    move('complete', 'Mark Drilling as Completed', 'well', 'forward', 'completed', 'completed'),
  ],
  'completed/completed': [
    move('reopen', 'Return Drilling to Final review', 'well', 'rollback', 'final_review', 'completed'),
  ],
}
const makeWell = (code, status, plan, extra = {}) => ({
  id: `well-${code}`, rig_id: 'rig-1', rig_code: 'RIG-1', rig_name: 'Rig one', block_id: 'block-1', block_code: 'B-1', block_name: 'Block one',
  well_code: code, well_name: `Well ${code}`, well_location: 'Onshore', objective: 'Appraisal', remarks: '',
  status, config_status: plan, tracking_status: status, final_review_scope_count: status === 'final_review' ? 1 : 0,
  completion_status: 'upcoming', completion_config_status: 'draft',
  drilling_transitions: OFFERED[`${status}/${plan}`] ?? [], completion_transitions: [],
  depth_unit: 'm', completion_depth_unit: 'm', total_depth: '1000', total_depth_m: '1000', total_days: '10',
  completion_total_depth: null, completion_total_depth_m: null, completion_total_days: '0',
  section_count: 1, completion_section_count: 0, sub_activity_count: 0, drilling_sub_activity_count: 0, completion_sub_activity_count: 0,
  drilling_is_deleted: false, drilling_deleted_at: null, drilling_purged: false,
  completion_is_deleted: true, completion_deleted_at: null, completion_purged: true,
  is_deleted: false, deleted_at: null, created_at: '2026-11-01T00:00:00Z', updated_at: '2026-11-01T00:00:00Z',
  adjusted_total_days: null, has_plan_adjustment: false, plan_revision: null, ...extra,
})
const wells = [
  makeWell('W-UP', 'upcoming', 'draft'), makeWell('W-UP2', 'upcoming', 'draft'),
  makeWell('W-ACT', 'active', 'configured'),
  makeWell('W-FR', 'final_review', 'completed'),
  makeWell('W-DONE', 'completed', 'completed'),
]

const requests = []
let transitionFailure = ''
globalThis.fetch = async (url, init = {}) => {
  const path = String(url).replace(/^.*\/api\/v1/, '')
  const method = init.method ?? 'GET'
  requests.push({ method, path, body: init.body ? JSON.parse(init.body) : null })
  const json = (payload, status = 200) => ({ ok: status < 400, status, json: async () => payload, text: async () => JSON.stringify(payload), headers: new w.Headers({ 'content-type': 'application/json' }) })
  if (path.endsWith('/auth/refresh')) return json({ access_token: 'token' })
  if (path.endsWith('/auth/me')) {
    return json({ id: 'u1', email: 'owner@example.com', name: 'Owner', is_active: true, is_owner: true, permission_keys: [], organization_slug: 'acme', organization_name: 'Acme' })
  }
  if (path.endsWith('/rig-well/rigs/dropdown')) return json([{ id: 'rig-1', rig_code: 'RIG-1', rig_name: 'Rig one', display_name: 'RIG-1 · Rig one', well_count: 5 }])
  if (path.endsWith('/rig-well/blocks/dropdown')) return json([{ id: 'block-1', block_code: 'B-1', block_name: 'Block one', description: '', display_name: 'B-1 · Block one', well_count: 5 }])
  if (method === 'POST' && path.endsWith('/transition')) {
    return transitionFailure ? json({ detail: transitionFailure }, 409) : json(wells[0])
  }
  if (path.startsWith('/rig-well/wells')) return json(wells)
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
const pause = ms => act(async () => { await new Promise(resolve => setTimeout(resolve, ms)) })
const click = element => act(async () => { element.dispatchEvent(new w.MouseEvent('click', { bubbles: true, cancelable: true })) })
const buttonWith = (text, scope = document) => [...scope.querySelectorAll('button')].find(button => button.textContent.trim() === text)

let root = null
async function mount(element, path = '/') {
  if (root) { await act(async () => root.unmount()); root = null }
  document.body.innerHTML = '<div id="root"></div>'
  root = createRoot(document.getElementById('root'))
  const router = createMemoryRouter([{ path: path.split('?')[0], element }], { initialEntries: [path] })
  await act(async () => { root.render(createElement(AuthProvider, null, createElement(RouterProvider, { router }))) })
  await pause(300)
}

// ---------------------------------------------------------------------------
// 3. The Wells register: one tab per well status, counted per scope row.
// ---------------------------------------------------------------------------
const WellsModule = await import('../../frontend/src/pages/Wells')
await mount(createElement(WellsModule.default), '/rig-well/wells')
const tabLabels = () => [...document.querySelectorAll('[role="tab"]')].map(tab => tab.textContent)
same(tabLabels(), ['Upcoming (2)', 'Active (1)', 'Final review (1)', 'Completed (1)'],
  'the register has one tab per well status, each counting its scope rows')
check(document.querySelector('[role="tab"][aria-selected="true"]').textContent.startsWith('Upcoming'), 'the register opens on Upcoming')
check(requests.some(request => request.method === 'GET' && request.path === '/rig-well/wells'), 'the register loads every well once and splits it by status')
await mount(createElement(WellsModule.default), '/rig-well/wells?tab=final_review')
check(document.querySelector('[role="tab"][aria-selected="true"]').textContent.startsWith('Final review'), 'a link can open the Final review tab directly')
await mount(createElement(WellsModule.default), '/rig-well/wells?tab=nonsense')
check(document.querySelector('[role="tab"][aria-selected="true"]').textContent.startsWith('Upcoming'), 'an unknown tab falls back to Upcoming')

// ---------------------------------------------------------------------------
// 4. The status menu offers exactly what the server lists.
// ---------------------------------------------------------------------------
const chosen = []
async function openMenu(well, props = {}) {
  await mount(createElement(WellsModule.WellActions, {
    well, scope: 'drilling', canEdit: true, canDelete: false, canAdjustPlan: false,
    onEdit() {}, onConfigure() {}, onDelete() {}, onAdjustPlan() {}, onActivateOtherScope() {},
    onTransition: option => chosen.push(option.action), ...props,
  }))
  const trigger = document.querySelector(`[aria-label="Change Drilling status of ${well.well_code}"]`)
  if (!trigger) return null
  await click(trigger)
  await pause(80)
  const menu = document.querySelector('[role="menu"]')
  return {
    headings: [...menu.querySelectorAll('.MuiListSubheader-root')].map(node => node.textContent),
    items: [...menu.querySelectorAll('[role="menuitem"]')].map(node => ({
      text: node.textContent, disabled: node.getAttribute('aria-disabled') === 'true', node,
    })),
  }
}
const moveTexts = menu => menu.items.map(item => item.text).filter(text => !text.startsWith('Add ') && !text.startsWith('Move Drilling scope'))

let menu = await openMenu(wells[0])
same(menu.headings, ['MOVE FORWARD'], 'an Upcoming scope with a Draft plan has nothing to roll back')
check(menu.items[0].text === 'Mark Drilling plan as Configured' && !menu.items[0].disabled, 'the plan can be marked Configured')
check(menu.items[1].disabled && menu.items[1].text.includes('Mark the drilling plan as Configured first.'),
  'Start is shown but disabled, with the reason the server gave')
await click(menu.items[1].node)
same(chosen, [], 'a blocked move cannot be chosen')
await click(menu.items[0].node)
same(chosen, ['configure'], 'choosing a move hands that server option to the confirmation dialog')

menu = await openMenu(wells[2])
same(menu.headings, ['MOVE FORWARD', 'ROLL BACK ONE STEP'], 'an Active scope moves forward or back one step')
same(moveTexts(menu), ['Move Drilling to Final review', 'Reopen Drilling plan as Draft', 'Return Drilling to Upcoming'],
  'Active/Configured: on to Final review, or back to Draft plan / Upcoming')
menu = await openMenu(wells[3])
same(moveTexts(menu), ['Mark Drilling as Completed', 'Return Drilling to Active'], 'Final review: on to Completed or back to Active')
menu = await openMenu(wells[4])
same(menu.headings, ['ROLL BACK ONE STEP'], 'a Completed scope can only be rolled back')
same(moveTexts(menu), ['Return Drilling to Final review'], 'Completed rolls back to Final review, never straight to Active')

// A planner without rig-well:rollback is not shown the rollbacks; an approver without
// rig-well:update is not shown forward moves, even one that is also blocked by state.
const notMine = option => ({ ...option, permitted: false, allowed: false, reason: option.reason || `This move needs the ${option.permission} permission.` })
const plannerWell = { ...wells[2], drilling_transitions: wells[2].drilling_transitions.map(option => option.direction === 'rollback' ? notMine(option) : option) }
menu = await openMenu(plannerWell)
same([menu.headings, moveTexts(menu)], [['MOVE FORWARD'], ['Move Drilling to Final review']], 'rollbacks are hidden from a role without rig-well:rollback')
const approverWell = { ...wells[0], drilling_transitions: wells[0].drilling_transitions.map(notMine) }
check(await openMenu(approverWell, { canEdit: false }) === null, 'a role with no move, edit or delete right gets no status menu at all')

// ---------------------------------------------------------------------------
// 5. The confirmation dialog: before -> after on both ladders, an audit note.
// ---------------------------------------------------------------------------
const { WellTransitionDialog, WellStatusTag, PlanStatusTag } = await import('../../frontend/src/components/WellLifecycle')
const done = []
let closed = 0
async function openDialog(well, option) {
  await mount(createElement(WellTransitionDialog, {
    well, scope: 'drilling', option, status: well.status, plan: well.config_status,
    onClose: () => { closed += 1 }, onDone: finished => done.push(finished.action),
  }))
  return document.querySelector('[role="dialog"]')
}
async function type(dialog, text) {
  const field = dialog.querySelector('textarea:not([aria-hidden="true"])')
  const setter = Object.getOwnPropertyDescriptor(w.HTMLTextAreaElement.prototype, 'value').set
  await act(async () => { setter.call(field, text); field.dispatchEvent(new w.Event('input', { bubbles: true })) })
}
const tags = dialog => [...dialog.querySelectorAll('[aria-label="changes to"]')].map(arrow => {
  const row = arrow.parentElement
  return [row.firstElementChild.textContent, row.lastElementChild.textContent]
})

let dialog = await openDialog(wells[2], OFFERED['active/configured'][2])
check(dialog.textContent.includes('Move Drilling to Final review?'), 'the dialog is titled with the move')
check(dialog.textContent.includes('W-ACT — Well W-ACT (RIG-1) · Drilling scope'), 'the dialog names the well, rig and scope')
same(tags(dialog), [['Active', 'Final review'], ['Configured', 'Completed']],
  'moving to Final review shows both ladders changing: the plan closes as Completed')
check(buttonWith('Confirm', dialog).disabled, 'a move cannot be confirmed without a reason')
await type(dialog, 'ok')
check(buttonWith('Confirm', dialog).disabled, 'two characters are not a reason')
await type(dialog, '  Rig released, costs under review  ')
check(!buttonWith('Confirm', dialog).disabled, 'a real reason enables the move')
requests.length = 0
await click(buttonWith('Confirm', dialog))
await pause(60)
same(requests.filter(request => request.method === 'POST'), [{
  method: 'POST', path: '/rig-well/wells/well-W-ACT/transition',
  body: { action: 'final_review', scope: 'drilling', remarks: 'Rig released, costs under review' },
}], 'the move is posted once with its action, scope and trimmed audit note')
same(done, ['final_review'], 'the register is told the move finished so it can reload')

dialog = await openDialog(wells[4], OFFERED['completed/completed'][0])
same(tags(dialog), [['Completed', 'Final review'], ['Completed', 'Completed']], 'reopening a Completed scope goes back one step only')
check(Boolean(buttonWith('Roll back', dialog)) && dialog.textContent.includes('Reason for the rollback'),
  'a rollback is labelled as one and asks for its reason')
transitionFailure = 'The drilling scope of W-DONE cannot move: 2 daily cost sheets are still in Draft.'
await type(dialog, 'Late invoice found')
await click(buttonWith('Roll back', dialog))
await pause(60)
check(document.querySelector('[role="dialog"]').textContent.includes('2 daily cost sheets are still in Draft'),
  'a refusal from the server is shown in the dialog, in the server\'s words')
same(done, ['final_review'], 'a refused move is not reported as done')
transitionFailure = ''
check(closed === 0, 'the dialog stays open after a refusal so the note is not lost')

await mount(createElement('div', null,
  ...['upcoming', 'active', 'final_review', 'completed'].map(status => createElement(WellStatusTag, { key: status, status })),
  ...['draft', 'configured', 'completed'].map(status => createElement(PlanStatusTag, { key: `p-${status}`, status })),
))
same([...document.querySelectorAll('#root > div > *')].map(node => node.textContent),
  ['Upcoming', 'Active', 'Final review', 'Completed', 'Draft', 'Configured', 'Completed'], 'the shared chips print the shared wording')

// ---------------------------------------------------------------------------
// 6. View vs print: the print sheet is hidden on screen by a real CSS rule.
//    A stray comment fragment once swallowed this selector, so the hidden print
//    copy rendered unstyled underneath the on-screen report preview.
// ---------------------------------------------------------------------------
const styles = readFileSync('../frontend/src/styles.css', 'utf8')
const withoutComments = styles.replace(/\/\*[\s\S]*?\*\//g, '')
const printStart = withoutComments.indexOf('@media print')
check(printStart > 0, 'the stylesheet has a print block')
const screenRules = withoutComments.slice(0, printStart)
const hideRule = /(^|\})\s*\.afe-print-sheet\s*\{\s*display:\s*none;?\s*\}/.exec(screenRules)
check(Boolean(hideRule), '.afe-print-sheet { display: none; } exists outside @media print, with exactly that selector')
const opens = (withoutComments.match(/\{/g) ?? []).length
const closes = (withoutComments.match(/\}/g) ?? []).length
check(opens === closes, 'the stylesheet braces balance, so no rule is swallowed by a broken neighbour')
check(!withoutComments.includes('*/') && !withoutComments.includes('/*'),
  'no orphaned comment opener or terminator is left to swallow the rule that follows it')
// jsdom applies the cascade for top-level rules, so the on-screen result is checked too.
const style = document.createElement('style')
style.textContent = screenRules
document.head.appendChild(style)
const sheet = document.createElement('div')
sheet.className = 'afe-print-sheet'
sheet.textContent = 'print copy'
document.body.appendChild(sheet)
check(w.getComputedStyle(sheet).display === 'none', 'on screen the print copy is not displayed; only the report preview is visible')
const printBlock = withoutComments.slice(printStart)
check(/\.afe-print-sheet\s*\{[^}]*display:\s*block/.test(printBlock), 'the print block is what reveals the sheet for the printer')

await act(async () => root.unmount())
dom.window.close()
console.log(`Well lifecycle checks passed (${passed}): status wording and roll-up, register tabs, status menu per ladder step, permission-hidden moves, transition dialog, and the on-screen print-sheet rule.`)
process.exit(0)
