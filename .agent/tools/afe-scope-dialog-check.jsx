// One-dialog scope configuration check (AFE → Add/Edit service, Day Rate).
//
// A Day Rate service used to need one line per section when sections cost
// different rates. The dialog now configures every section (and phase) of the
// well in one box, and the service total is the sum of those section amounts.
// These checks drive the real dialog: they add two section rates, then read the
// line the dialog saves back to the estimate editor.
//
// Run:
//   cd frontend && NODE_PATH="$PWD/node_modules" ./node_modules/.bin/esbuild \
//     ../.agent/tools/afe-scope-dialog-check.jsx --bundle --platform=node --format=esm --jsx=automatic \
//     --outfile=node_modules/.cache/afe-scope-dialog-check.mjs --loader:.jsx=jsx --log-level=error --external:jsdom && \
//     node node_modules/.cache/afe-scope-dialog-check.mjs
import assert from 'node:assert/strict'
import { JSDOM } from 'jsdom'

const dom = new JSDOM('<html><body><div id="root"></div></body></html>', { pretendToBeVisual: true, url: 'http://localhost/' })
const w = dom.window
w.matchMedia = query => ({ matches: false, media: query, addListener() {}, removeListener() {}, addEventListener() {}, removeEventListener() {} })
for (const key of [
  'window', 'document', 'navigator', 'HTMLElement', 'Element', 'Node', 'Event', 'KeyboardEvent', 'MouseEvent',
  'getComputedStyle', 'requestAnimationFrame', 'cancelAnimationFrame', 'CSS', 'SVGSVGElement', 'DocumentFragment',
  'ShadowRoot', 'CustomEvent', 'DOMRect', 'HTMLInputElement', 'HTMLSelectElement', 'FocusEvent', 'InputEvent',
]) {
  Object.defineProperty(globalThis, key, { value: w[key], configurable: true, writable: true })
}
for (const key of ['MutationObserver', 'localStorage', 'sessionStorage', 'NodeList', 'HTMLCollection', 'crypto']) {
  if (w[key] !== undefined) Object.defineProperty(globalThis, key, { value: w[key], configurable: true, writable: true })
}
globalThis.ResizeObserver = globalThis.ResizeObserver || class { observe() {} unobserve() {} disconnect() {} }
globalThis.IS_REACT_ACT_ENVIRONMENT = true

const checks = []
const check = (name, passed) => { checks.push({ name, passed }); assert.ok(passed, name) }

const { act } = await import('react')
const createCache = (await import('@emotion/cache')).default
const { CacheProvider } = await import('@emotion/react')
const { ThemeProvider } = await import('@mui/material')
const { createRoot } = await import('react-dom/client')
const { buildTheme } = await import('../../frontend/src/theme')
const { ServiceLineDialog } = await import('../../frontend/src/components/afe/ServiceLineDialog')
const { serviceProblems } = await import('../../frontend/src/lib/afe')

const scope = {
  scope: 'drilling', well_id: 'well-1', well_code: 'WELL-1', well_name: 'Well one', well_location: '', block: '',
  objective: '', rig_code: 'RIG-1', rig_name: 'Rig one', depth_unit: 'm', status: 'active', config_status: 'configured',
  total_depth: '2000', total_days: '60',
  sections: [
    {
      hole_section_id: 'section-surface', section_code: '17-1/2', section_name: 'Surface hole',
      from_depth: '0', to_depth: '1000', total_days: '10',
      phases: [{ phase_id: 'phase-drill', phase_code: 'DRL', phase_name: 'Drilling', days: '10' }],
    },
    {
      hole_section_id: 'section-intermediate', section_code: '12-1/4', section_name: 'Intermediate hole',
      from_depth: '1000', to_depth: '2000', total_days: '50',
      phases: [{ phase_id: 'phase-drill', phase_code: 'DRL', phase_name: 'Drilling', days: '50' }],
    },
  ],
}

const reference = {
  services: [{
    id: 'service-mud', service_code: 'MUD-LOG', service_name: 'Mud logging', service_category: 'Drilling Services',
    service_group: 'Formation Evaluation', provider_type: 'Third Party Services', vendor_name: 'Vendor one',
    description: '', display_name: 'MUD-LOG · Mud logging',
  }],
  currencies: [{ code: 'USD', name: 'US Dollar', symbol: '$', is_default: true }],
  vendors: [], rigs: [], wells: [], hole_sections: [], phases: [], drill_bits: [], tangibles: [],
  catalogue_options: [], activities: [], afe_types: ['Drilling'], charging_bases: [], charge_categories: [],
  one_time_categories: [], consumable_categories: [], statuses: [],
}

const doc = w.document
const cache = createCache({ key: 'afe-scope-dialog-check', container: doc.head })
const root = createRoot(doc.getElementById('root'))
let saved = null

const render = async node => {
  await act(async () => {
    root.render(<CacheProvider value={cache}><ThemeProvider theme={buildTheme('light')}>{node}</ThemeProvider></CacheProvider>)
  })
  await act(async () => { await new Promise(resolve => setTimeout(resolve, 0)) })
}
const bodyText = () => doc.body.textContent || ''
const buttons = () => Array.from(doc.querySelectorAll('button'))
const click = async button => {
  await act(async () => { button.dispatchEvent(new w.MouseEvent('click', { bubbles: true })) })
  await act(async () => { await new Promise(resolve => setTimeout(resolve, 0)) })
}
// MUI text fields expose an empty input whose visible label lives in the FormControl.
const fieldFor = (label, index = 0) => {
  const controls = Array.from(doc.querySelectorAll('.MuiFormControl-root')).filter(node => {
    const labelNode = node.querySelector('label, .MuiInputLabel-root')
    return (labelNode?.textContent || '').replace(/\s*\*\s*$/, '').trim() === label
  })
  const control = controls[index]
  return control ? control.querySelector('input') : undefined
}
const type = async (input, value) => {
  assert.ok(input, 'the dialog renders the field being typed into')
  await act(async () => {
    const setter = Object.getOwnPropertyDescriptor(w.HTMLInputElement.prototype, 'value').set
    setter.call(input, value)
    input.dispatchEvent(new w.Event('input', { bubbles: true }))
  })
  await act(async () => { await new Promise(resolve => setTimeout(resolve, 0)) })
}

// MUI Select renders a role="combobox" div; open it, then click the option.
// `index` picks the Nth field with that label: the dialog's own Section select
// comes before the repeated Section selects inside the section rows.
const selectOption = async (label, optionText, index = 0) => {
  const matches = Array.from(doc.querySelectorAll('.MuiFormControl-root')).filter(node => {
    const labelNode = node.querySelector('label, .MuiInputLabel-root')
    return (labelNode?.textContent || '').replace(/\s*\*\s*$/, '').trim() === label
  })
  const control = matches[index]
  assert.ok(control, `the dialog renders the ${label} field`)
  const combo = control.querySelector('[role="combobox"]')
  assert.ok(combo, `the ${label} field is a select`)
  await act(async () => { combo.dispatchEvent(new w.MouseEvent('mousedown', { bubbles: true })) })
  await act(async () => { await new Promise(resolve => setTimeout(resolve, 0)) })
  const option = Array.from(doc.querySelectorAll('[role="option"]'))
    .find(node => (node.textContent || '').includes(optionText))
  assert.ok(option, `the ${label} list offers ${optionText}`)
  await act(async () => { option.dispatchEvent(new w.MouseEvent('click', { bubbles: true })) })
  await act(async () => { await new Promise(resolve => setTimeout(resolve, 0)) })
}

await render(<ServiceLineDialog open initial={null} scope={scope} reference={reference} onClose={() => {}} onSave={line => { saved = line }} />)

check('the Day Rate dialog configures sections in the same dialog', bodyText().includes('Rate for each section and phase'))
check('the dialog explains the section amounts add up to one service total', bodyText().includes('Amounts add up to the service total'))
check('every well section is offered for a rate', bodyText().includes('17-1/2 · Surface hole') && bodyText().includes('12-1/4 · Intermediate hole'))
check('each section row shows its planned days', bodyText().includes('10 d planned') && bodyText().includes('50 d planned'))

// Pick the service and its currency, the two fields the estimate needs before saving.
await selectOption('Service', 'MUD-LOG · Mud logging', 0)
await selectOption('Currency', 'USD', 0)

// Add a surface rate of 1000/day and an intermediate rate of 1100/day.
const addRate = async (sectionLabel, rate) => {
  // The dialog's header has its own Section select; the scope editor's is the
  // second one, because it is the editor that carries a rate per section.
  await selectOption('Section', sectionLabel, 1)
  await type(fieldFor('Rate per day', 0), rate)
  // Re-read the button: React replaced it after the state updates above.
  await act(async () => { await new Promise(resolve => setTimeout(resolve, 0)) })
  const enabled = buttons().find(button => (button.textContent || '').includes('Add section rate'))
  assert.ok(enabled, 'the dialog offers to add the section rate')
  assert.equal(enabled.disabled, false, `the add button enables once ${sectionLabel} and its rate are entered`)
  await click(enabled)
  assert.equal(fieldFor('Rate per day', 0).value, '', 'adding a section rate clears the entry fields')
}
await addRate('17-1/2', '1000')
await addRate('12-1/4', '1100')

check('the surface section keeps its own rate in the section list', bodyText().includes('17-1/2 · Surface hole'))
check('the intermediate section keeps its own rate in the section list', bodyText().includes('12-1/4 · Intermediate hole'))

const save = buttons().find(button => (button.textContent || '').trim() === 'Add service')
assert.ok(save, 'the dialog offers its save action')
await click(save)

assert.ok(saved, 'the dialog hands the completed line back for saving')
check('one service line carries both section rates', saved.scope_rates.length === 2)
check('the first section rate is kept exactly as typed',
  saved.scope_rates.some(rate => rate.hole_section_id === 'section-surface' && rate.unit_rate === '1000'))
check('the second section rate is kept exactly as typed',
  saved.scope_rates.some(rate => rate.hole_section_id === 'section-intermediate' && rate.unit_rate === '1100'))
check('the well-wide rate card stays empty when every section has its own rate', saved.rates.length === 0)
check('the saved line has no problems, so the editor can price it', serviceProblems(saved).length === 0)
check('the section rate without entered days leaves the well plan to supply them', saved.scope_days.length === 0)

// A line configured per section is valid; a Day Rate line with no rate at all is not.
const missingRate = { ...saved, scope_rates: [] }
check('a Day Rate service still requires a rate', serviceProblems(missingRate).some(problem => problem.includes('Enter a unit rate')))
const duplicate = { ...saved, scope_rates: [...saved.scope_rates, saved.scope_rates[0]] }
check('the dialog rejects two rates for the same section and category',
  serviceProblems(duplicate).some(problem => problem.includes('more than one rate')))

// Entered days win over the well plan for that section only.
await render(<ServiceLineDialog open initial={saved} scope={scope} reference={reference} onClose={() => {}} onSave={line => { saved = line }} />)
check('reopening the saved line restores its section rates', bodyText().includes('17-1/2 · Surface hole') && bodyText().includes('12-1/4 · Intermediate hole'))
await type(fieldFor('Days', 0), '48')
const secondSave = buttons().find(button => (button.textContent || '').trim() === 'Save line')
assert.ok(secondSave, 'an edited line saves through the same dialog')
await click(secondSave)
check('entered section days are kept with the line',
  saved.scope_days.some(row => row.hole_section_id === 'section-surface' && row.quantity === '48'))

await act(async () => root.unmount())
dom.window.close()
console.log(`AFE one-dialog scope checks passed (${checks.length}): ${checks.map(item => item.name).join('; ')}.`)
process.exit(0)
