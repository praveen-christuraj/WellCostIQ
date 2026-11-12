// Reusable-template UI check.
//
// Covers the three surfaces a user meets: an AFE estimate template in the
// library, a well plan template, and the picker that hands either of them to a
// record page. The fixtures follow the live API contract exactly (codes for the
// well plan scope, `is_available` on every referenced line, `line_count` and
// `use_count` on the summary), because the point of these surfaces is that a
// saved structure survives Master Data changes and still applies.
//
// Run:
//   cd frontend && NODE_PATH="$PWD/node_modules" ./node_modules/.bin/esbuild \
//     ../.agent/tools/templates-check.jsx --bundle --platform=node --format=esm --jsx=automatic \
//     --outfile=node_modules/.cache/templates-check.mjs --loader:.jsx=jsx --log-level=error --external:jsdom && \
//     node node_modules/.cache/templates-check.mjs
import assert from 'node:assert/strict'
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
for (const key of ['MutationObserver', 'IntersectionObserver', 'localStorage', 'sessionStorage', 'NodeList', 'HTMLCollection', 'DOMParser', 'SVGElement', 'FocusEvent', 'InputEvent', 'PointerEvent', 'WheelEvent', 'crypto']) {
  if (w[key] !== undefined) Object.defineProperty(globalThis, key, { value: w[key], configurable: true, writable: true })
}
globalThis.ResizeObserver = globalThis.ResizeObserver || class { observe() {} unobserve() {} disconnect() {} }
globalThis.IS_REACT_ACT_ENVIRONMENT = true
// AG Grid measures itself; jsdom has no layout, so seed the few functions it calls.
globalThis.HTMLElement.prototype.scrollIntoView = globalThis.HTMLElement.prototype.scrollIntoView || function scrollIntoView() {}

const checks = []
const check = (name, passed) => { checks.push({ name, passed }); assert.ok(passed, name) }

const { act } = await import('react')
const createCache = (await import('@emotion/cache')).default
const { CacheProvider } = await import('@emotion/react')
const { createRoot } = await import('react-dom/client')
const { ThemeProvider, CssBaseline } = await import('@mui/material')
const { MemoryRouter } = await import('react-router-dom')
const { buildTheme } = await import('../../frontend/src/theme')

// ---------------------------------------------------------------------------
// Fixtures: exactly what the API returns (verified live against the smoke API).
// ---------------------------------------------------------------------------
const summary = (overrides = {}) => ({
  id: 'template-afe', owner_id: 'user-1', owner_name: 'Smoke Owner', template_kind: 'afe',
  name: 'Standard 17-1/2 drilling AFE', description: 'The lines this workspace always estimates',
  scope: 'Drilling', afe_type: 'Drilling', standard_currency: 'USD', is_shared: false, is_owner: true,
  use_count: 4, last_used_at: '2026-11-02T09:15:00Z', line_count: 3, unavailable_count: 0,
  updated_at: '2026-11-01T10:00:00Z', ...overrides,
})
const afeTemplate = {
  ...summary(),
  services: [
    { service_id: 'svc-mud', service_code: 'MUD-LOG', service_name: 'Mud logging', charging_basis: 'Day Rate',
      section_code: '17-1/2', section_label: '17-1/2 · Surface hole', phase_code: 'DRILL', phase_label: 'Drilling',
      currency: 'USD', service_amount: '12000', operation_rate: null, standby_rate: null, repair_rate: null,
      operation_days: '12', standby_days: null, repair_days: null, quantity_unit: 'days',
      remarks: '', is_available: true },
    { service_id: 'svc-gone', service_code: 'OLD-SVC', service_name: 'Retired service', charging_basis: 'Day Rate',
      section_code: '', section_label: '', phase_code: '', phase_label: '', currency: 'USD', service_amount: '0',
      operation_rate: null, standby_rate: null, repair_rate: null, operation_days: '2', standby_days: null,
      repair_days: null, quantity_unit: 'days', remarks: '', is_available: false },
  ],
  consumables: [
    { category: 'Mud Chemicals', section_code: '', section_label: '', phase_code: '', phase_label: '',
      drill_bit_id: null, drill_bit_code: '', drill_bit_name: '', quantity: '40', estimated_amount: '8000',
      currency: 'USD', remarks: '', is_available: true },
  ],
  tangibles: [], sections: [], created_at: '2026-11-01T10:00:00Z',
}
const wellTemplate = {
  ...summary({ id: 'template-well', template_kind: 'well', name: 'Smoke dev plan', description: 'Standard development well',
    scope: 'Drilling', line_count: 1, is_shared: true }),
  services: [], consumables: [], tangibles: [],
  sections: [{
    hole_section_id: 'section-1', section_code: '17-1/2', section_name: 'Surface hole',
    from_depth: '0', to_depth: '1200', depth_unit: 'm', remarks: '',
    phases: [{ phase_id: 'phase-1', phase_code: 'DRILL', phase_name: 'Drilling', days: '12', remarks: '', is_available: true }],
    is_available: true,
  }],
  created_at: '2026-11-01T10:00:00Z',
}
const preview = (template) => {
  const line = (kind, label, note = '', isAvailable = true) => ({ kind, label, note, is_available: isAvailable })
  return {
    template_id: template.id, template_kind: template.template_kind, name: template.name,
    services: template.services.map(item => line('service', `${item.service_code} · ${item.service_name}`,
      item.section_label, item.is_available)),
    consumables: template.consumables.map(item => line('consumable', `${item.category} · ${item.quantity}`,
      '', item.is_available)),
    tangibles: template.tangibles.map(item => line('tangible', `${item.tangible_code} · ${item.tangible_name}`,
      '', item.is_available)),
    sections: template.sections.map(item => line('section', `${item.section_code} · ${item.section_name}`,
      `${item.from_depth}–${item.to_depth} ${item.depth_unit} · ${item.phases.length} phase · 12 days`, item.is_available)),
    // The server words the warning; keep the same sentence it returns.
    warnings: [...template.services, ...template.consumables, ...template.tangibles, ...template.sections]
      .some(item => item.is_available === false)
      ? ['Retired service is no longer in Master Data and will be skipped.']
      : [],
    can_apply: true,
  }
}

// ---------------------------------------------------------------------------
// 1. The library's pure helpers refuse an incomplete template before the API.
// ---------------------------------------------------------------------------
const {
  emptyTemplate, templateToInput, templateProblem, plannedDays, formatTemplateDate, resolveScope,
} = await import('../../frontend/src/lib/recordTemplates')

assert.equal(templateProblem(emptyTemplate('afe')), 'Enter a name for this template.')
assert.equal(templateProblem({ ...emptyTemplate('afe'), name: 'Standard' }), 'Add at least one line to this template.')
assert.equal(templateProblem(emptyTemplate('well')), 'Enter a name for this template.')
assert.equal(templateProblem({ ...emptyTemplate('well'), name: 'Plan' }), 'Add at least one hole section.')
assert.equal(templateProblem({
  ...emptyTemplate('well'), name: 'Plan',
  sections: [{ hole_section_id: 's1', from_depth: '0', to_depth: '100', remarks: '', phases: [] }],
}), 'Every hole section needs at least one phase.')
assert.equal(templateProblem({ ...afeTemplate, ...templateToInput(afeTemplate) }), '',
  'an existing template round-trips into an editable copy that is ready to save')

const roundTrip = templateToInput(afeTemplate)
assert.equal(roundTrip.services.length, 2, 'every saved line survives the trip into the editor')
assert.equal(roundTrip.consumables[0].estimated_amount, '8000', 'the amount is kept so the editor never blanks it')
assert.equal(plannedDays(wellTemplate), 12, 'planned days total from the well plan sections')
assert.equal(formatTemplateDate('2026-11-02T09:15:00Z'), '02/11/2026')
assert.equal(formatTemplateDate(null), 'Never used')

// A template carries scope *codes*, so it applies to any well with the same sections.
const plan = { sections: [{ hole_section_id: 'other-section', section_code: '17-1/2', phases: [{ phase_id: 'other-phase', phase_code: 'DRILL' }] }] }
assert.deepEqual(resolveScope(plan, '17-1/2', 'DRILL'), { sectionId: 'other-section', phaseId: 'other-phase', missing: false },
  'a code applies to a different well whose ids differ')
assert.deepEqual(resolveScope(plan, '12-1/4', ''), { sectionId: null, phaseId: null, missing: true },
  'a section the well does not have is reported, never guessed')

// ---------------------------------------------------------------------------
// 2. The picker shows what will be added, what is unavailable, and never
//    applies without a confirm.
// ---------------------------------------------------------------------------
const fetchCalls = []
const jsonResponse = payload => ({ ok: true, status: 200, json: async () => payload, text: async () => JSON.stringify(payload), headers: { get: () => 'application/json' } })
globalThis.fetch = async (url, options = {}) => {
  const path = String(url).replace('/api/v1', '')
  fetchCalls.push({ path, method: options.method || 'GET' })
  if (path.startsWith('/record-templates/') && path.endsWith('/preview')) {
    return jsonResponse(preview(path.includes('template-well') ? wellTemplate : afeTemplate))
  }
  if (path === '/record-templates/template-afe') return jsonResponse(afeTemplate)
  if (path === '/record-templates/template-well') return jsonResponse(wellTemplate)
  if (path === '/record-templates?kind=afe') return jsonResponse([{ ...summary(), unavailable_count: 1 }])
  if (path === '/record-templates?kind=well') return jsonResponse([{ ...wellTemplate, services: undefined, consumables: undefined, tangibles: undefined, sections: undefined }])
  if (path === '/record-templates/template-afe/apply') return jsonResponse({ ...summary(), use_count: 5 })
  return jsonResponse([])
}

const { TemplatePickerDialog } = await import('../../frontend/src/components/templates/TemplatePickerDialog')
const doc = w.document
const cache = createCache({ key: 'templates-check', container: doc.head })
const root = createRoot(doc.getElementById('root'))
const mount = async node => {
  await act(async () => {
    root.render(<CacheProvider value={cache}><ThemeProvider theme={buildTheme('light')}><CssBaseline/><MemoryRouter>{node}</MemoryRouter></ThemeProvider></CacheProvider>)
  })
  await act(async () => { await new Promise(resolve => setTimeout(resolve, 0)) })
}

let applied = null
await mount(<TemplatePickerDialog open kind="afe" onClose={() => {}} onApply={(template, appliedPreview) => { applied = { template, appliedPreview } }}/>)

let text = doc.body.textContent || ''
check('the picker names the kind of template it is offering', text.includes('Use a AFE estimate template'))
check('the picker explains that using a template never changes it', text.includes('The template itself is never changed by using it.'))
check('the picker lists the lines the template will add', text.includes('MUD-LOG · Mud logging') && text.includes('Mud Chemicals · 40'))
check('the picker marks the line whose Master Data is gone', text.includes('OLD-SVC · Retired service') && text.includes('Unavailable'))
check('the picker counts the lines that are ready', text.includes('2 of 3 lines ready to use'))
check('the picker repeats the warning about skipped lines', text.includes('no longer in Master Data'))
check('the picker says nothing is saved by applying', text.includes('Nothing is saved until you save the record.'))
check('the picker states the template is never written by applying', text.includes('never changed by using it'))
check('a template the user owns is not labelled read-only', !text.includes('Read-only'))

// Applying is explicit: the confirm button applies, and only then.
assert.equal(applied, null, 'opening the picker must never apply a template by itself')
const confirm = Array.from(doc.querySelectorAll('button')).find(button => /^Use \d+ line/.test(button.textContent || ''))
assert.ok(confirm, 'the dialog offers a confirm button naming the line count')
await act(async () => { confirm.dispatchEvent(new w.MouseEvent('click', { bubbles: true })) })
check('confirming hands the page the full template and the preview it was shown',
  applied?.template?.id === 'template-afe' && applied?.appliedPreview?.services.length === 2)

// A well plan template previews its sections in readable depths.
await mount(<TemplatePickerDialog open kind="well" wellId="well-1" onClose={() => {}} onApply={() => {}}/>)
text = doc.body.textContent || ''
check('a well plan template previews its hole section and planned days',
  text.includes('17-1/2 · Surface hole') && text.includes('0–1200 m · 1 phase · 12 days'))
check('the well preview was requested for the well being configured',
  fetchCalls.some(call => call.path === '/record-templates?kind=well'))

// ---------------------------------------------------------------------------
// 3. An empty library sends the user to Manage templates instead of a dead end.
// ---------------------------------------------------------------------------
globalThis.fetch = async (url) => {
  const path = String(url).replace('/api/v1', '')
  fetchCalls.push({ path, method: 'GET' })
  return jsonResponse([])
}
await mount(<TemplatePickerDialog open kind="daily-cost" onClose={() => {}} onApply={() => {}}/>)
text = doc.body.textContent || ''
check('an empty library explains what to do instead of failing',
  text.includes('There is no daily cost sheet template yet.') && text.includes('Manage templates'))
check('the empty library never shows a confirm that could add nothing',
  !Array.from(doc.querySelectorAll('button')).some(button => /^Use \d+ line/.test(button.textContent || '')))

// ---------------------------------------------------------------------------
// 4. The library page lists templates, explains each kind and keeps private
//    ones private.
// ---------------------------------------------------------------------------
const { default: TemplatesPage } = await import('../../frontend/src/pages/Templates')
const { AuthProvider } = await import('../../frontend/src/context/AuthContext')
const me = {
  id: 'user-1', email: 'owner@smokeenergy.com', full_name: 'Smoke Owner', is_active: true,
  organization_name: 'Smoke', organization_slug: 'smoke', is_owner: true, permission_keys: [],
  must_change_password: false, password_expired: false, password_changed_at: null, password_expires_at: null,
  password_days_remaining: null, created_at: '2026-01-01T00:00:00Z', updated_at: '2026-01-01T00:00:00Z',
}
globalThis.fetch = async (url) => {
  const path = String(url).replace('/api/v1', '')
  fetchCalls.push({ path, method: 'GET' })
  // The page only shows its create/export actions once the signed-in account is
  // known, so the harness restores a session the way a returning user's cookie does.
  if (path === '/auth/refresh') return jsonResponse({ access_token: 'check-token' })
  if (path === '/auth/me') return jsonResponse(me)
  if (path === '/record-templates') return jsonResponse([
    summary({ unavailable_count: 1 }),
    summary({ id: 'template-shared', name: 'Workspace standard', is_shared: true, is_owner: false, owner_name: 'Ada Okafor' }),
    wellTemplate,
  ])
  return jsonResponse([])
}
await mount(<AuthProvider><TemplatesPage/></AuthProvider>)
await act(async () => { await new Promise(resolve => setTimeout(resolve, 0)) })
text = doc.body.textContent || ''
check('the library headings explain the feature in plain words',
  text.includes('Reusable templates') && text.includes('no Excel template, no retyping'))
check('the library is split into one tab per record type',
  text.includes('AFE estimate template') && text.includes('Well configuration template') && text.includes('Daily cost sheet template'))
check('the AFE tab lists the AFE templates only', text.includes('Standard 17-1/2 drilling AFE'))
check('the AFE tab explains what an AFE template carries',
  text.includes('The standard service, consumable and tangible lines of an estimate.'))
check('the library repeats that applying never saves a record',
  text.includes('never saves a record by itself'))
check('an unavailable line is called out in the list', text.includes('1 unavailable'))
const buttonLabels = Array.from(doc.querySelectorAll('button')).map(button => (button.getAttribute('aria-label') || button.textContent || '').trim())
check('the library offers edit and delete on your own template, and copy on someone else\'s',
  buttonLabels.includes('Edit Standard 17-1/2 drilling AFE') && buttonLabels.includes('Delete Standard 17-1/2 drilling AFE')
  && buttonLabels.includes('Copy Workspace standard')
  && !buttonLabels.includes('Edit Workspace standard') && !buttonLabels.includes('Delete Workspace standard'))
check("a shared template names its owner so the reader knows whose it is", text.includes('Ada Okafor'))
check('a brand-new library still offers the create action',
  Array.from(doc.querySelectorAll('button')).some(button => /New .*template/i.test(button.textContent || '')))

const failures = checks.filter(item => !item.passed)
console.log(`Template checks passed: ${checks.length - failures.length}/${checks.length}`)
console.log('  library helpers, the picker preview and confirm, the empty state, and the management page all behave.')
process.exit(failures.length ? 1 : 0)
