// Catalogue UI check: bulk price revision and the description column.
//
// The bulk-revision dialog is the only way a price moves in bulk, so it has to
// be honest before the upload: it must show exactly which rows change, refuse to
// run without a reason, and keep the server's all-or-nothing refusal on screen.
// The description column is the other half — Master Data pages show what an item
// is, not just its code and price.
//
// Run:
//   cd frontend && NODE_PATH="$PWD/node_modules" ./node_modules/.bin/esbuild \
//     ../.agent/tools/catalogue-check.jsx --bundle --platform=node --format=esm --jsx=automatic \
//     --outfile=node_modules/.cache/catalogue-check.mjs --loader:.jsx=jsx --log-level=error --external:jsdom && \
//     node node_modules/.cache/catalogue-check.mjs
import assert from 'node:assert/strict'
import { JSDOM } from 'jsdom'

const dom = new JSDOM('<html><body><div id="root"></div></body></html>', { pretendToBeVisual: true, url: 'http://localhost/' })
const w = dom.window
w.matchMedia = query => ({ matches: false, media: query, addListener() {}, removeListener() {}, addEventListener() {}, removeEventListener() {} })
for (const key of [
  'window', 'document', 'navigator', 'HTMLElement', 'Element', 'Node', 'Event', 'KeyboardEvent', 'MouseEvent',
  'getComputedStyle', 'requestAnimationFrame', 'cancelAnimationFrame', 'CSS', 'SVGSVGElement', 'DocumentFragment',
  'ShadowRoot', 'CustomEvent', 'DOMRect', 'HTMLIFrameElement', 'HTMLInputElement', 'HTMLSelectElement', 'File', 'Blob',
]) {
  Object.defineProperty(globalThis, key, { value: w[key], configurable: true, writable: true })
}
for (const key of ['MutationObserver', 'IntersectionObserver', 'localStorage', 'sessionStorage', 'NodeList', 'HTMLCollection', 'DOMParser', 'SVGElement', 'FocusEvent', 'InputEvent', 'PointerEvent', 'WheelEvent', 'crypto']) {
  if (w[key] !== undefined) Object.defineProperty(globalThis, key, { value: w[key], configurable: true, writable: true })
}
globalThis.ResizeObserver = globalThis.ResizeObserver || class { observe() {} unobserve() {} disconnect() {} }
globalThis.IS_REACT_ACT_ENVIRONMENT = true

const checks = []
const check = (name, passed) => { checks.push({ name, passed }); assert.ok(passed, name) }

const { act } = await import('react')
const createCache = (await import('@emotion/cache')).default
const { CacheProvider } = await import('@emotion/react')
const { createRoot } = await import('react-dom/client')
const { ThemeProvider, CssBaseline } = await import('@mui/material')
const { buildTheme } = await import('../../frontend/src/theme')
const { TANGIBLE_CONFIG, CONSUMABLE_TYPES } = await import('../../frontend/src/lib/catalogue')

// ---------------------------------------------------------------------------
// 1. Every catalogue type exposes a description column, and the table shows it.
// ---------------------------------------------------------------------------
const ALL_CONFIGS = [TANGIBLE_CONFIG, ...CONSUMABLE_TYPES]
check('every catalogue type declares a description field',
  ALL_CONFIGS.every(config => config.fields.some(field => field.key === 'description')))
check('every catalogue type lists a description column in its table',
  ALL_CONFIGS.every(config => config.columns.some(column => column.key === 'description')),
  ALL_CONFIGS.filter(config => !config.columns.some(column => column.key === 'description')).map(config => config.key).join(', '))
// Grid headings are upper-case throughout the catalogue tables; the label must
// read Description in that style, not an abbreviation like DESC.
check('the description column heading reads Description',
  ALL_CONFIGS.every(config => (config.columns.find(column => column.key === 'description')?.label ?? '').toUpperCase() === 'DESCRIPTION'))
check('the description column is given real width instead of being squeezed out',
  ALL_CONFIGS.every(config => {
    const column = config.columns.find(item => item.key === 'description')
    return Boolean(column && (column.flex || (column.width ?? 0) >= 160))
  }))
check('description is optional on import so a price-only file still loads',
  ALL_CONFIGS.every(config => (config.importOptional ?? []).includes('description')))

// ---------------------------------------------------------------------------
// 2. The bulk revision dialog previews against the register before uploading.
// ---------------------------------------------------------------------------
const records = [
  { id: 't1', tangible_code: 'CSG-01', tangible_name: 'Surface casing', description: '20 inch conductor', unit_rate: '1250', cost_uplift: '100', currency: 'USD', is_deleted: false },
  { id: 't2', tangible_code: 'CSG-02', tangible_name: 'Production casing', description: '', unit_rate: '980', cost_uplift: '100', currency: 'USD', is_deleted: false },
]
const uploadedRows = [
  // Edited: 1250 -> 1312.50, written the way a spreadsheet stores it.
  { tangible_code: 'CSG-01', tangible_name: 'Surface casing', description: '20 inch conductor', unit_rate: '1312.5000000000', cost_uplift: '100', currency: 'USD' },
  // Untouched: must be counted, never rewritten.
  { tangible_code: 'CSG-02', tangible_name: 'Production casing', description: '', unit_rate: '980.0000000000', cost_uplift: '100', currency: 'USD' },
]

const calls = []
const jsonResponse = payload => ({ ok: true, status: 200, json: async () => payload })
globalThis.fetch = async (url, options = {}) => {
  calls.push({ url: String(url), method: options.method || 'GET' })
  if (String(url).includes('bulk-revise')) {
    return jsonResponse({
      revised_count: 1, unchanged_count: 1, skipped_count: 0, error_count: 0,
      original_rate: null, new_rate: '1312.5', currency: 'USD', effective_date: '2026-11-12',
      errors: [], warnings: [],
    })
  }
  return jsonResponse({})
}

const { BulkPriceRevisionDialog } = await import('../../frontend/src/components/catalogue/BulkPriceRevisionDialog')
const doc = w.document
const cache = createCache({ key: 'catalogue-check', container: doc.head })
const root = createRoot(doc.getElementById('root'))
const mount = async node => {
  await act(async () => {
    root.render(<CacheProvider value={cache}><ThemeProvider theme={buildTheme('light')}><CssBaseline/>{node}</ThemeProvider></CacheProvider>)
  })
  await act(async () => { await new Promise(resolve => setTimeout(resolve, 0)) })
}

let revised = ''
const dialog = <BulkPriceRevisionDialog open config={TANGIBLE_CONFIG} current={records} onClose={() => {}} onRevised={summary => { revised = summary }}/>
await mount(dialog)

let text = doc.body.textContent || ''
check('the dialog names the catalogue it revises', text.includes('Bulk price revision · Tangibles'))
check('it explains the download-edit-upload order',
  text.includes('Download the current price list') && text.includes('Step 2 · Upload the edited file'))
check('it warns that nothing else on the record changes', text.includes('Nothing else on the record changes.'))
check('the reason is required before anything can be revised',
  text.includes('Reason for the price change') && text.includes('At least 3 characters.'))

check('the confirm button exists before a file is chosen',
  Array.from(doc.querySelectorAll('button')).some(button => /^Revise /.test(button.textContent || '')))
check('nothing can be revised until a file is uploaded and a reason given',
  Array.from(doc.querySelectorAll('button')).find(button => /^Revise /.test(button.textContent || ''))?.disabled === true)

// The operator edits one price and uploads the file.
const fileInput = doc.querySelector('input[type="file"]')
check('the dialog only accepts the spreadsheet formats it can read', fileInput.accept === '.xlsx,.csv')
const headerLine = 'tangible_code,tangible_name,description,unit_rate,cost_uplift,currency'
const csv = [headerLine, ...uploadedRows.map(row => [
  row.tangible_code, row.tangible_name, row.description, row.unit_rate, row.cost_uplift, row.currency,
].join(','))].join('\r\n')
const file = new w.File([csv], 'tangibles-price-revision.csv', { type: 'text/csv' })
await act(async () => {
  Object.defineProperty(fileInput, 'files', { value: [file], configurable: true })
  fileInput.dispatchEvent(new w.Event('change', { bubbles: true }))
  await new Promise(resolve => setTimeout(resolve, 60))
})
await act(async () => { await new Promise(resolve => setTimeout(resolve, 60)) })

text = doc.body.textContent || ''
check('the chosen file is named back with its row count',
  text.includes('tangibles-price-revision.csv') && text.includes('2 rows'))
check('exactly one price is identified as changing', text.includes('1 price will change'))
check('the row left at its current price is counted, not hidden',
  text.includes('2 rows read · 1 left at the current price'))
check('the changed code is named so the operator can confirm it', text.includes('CSG-01'))
check('the preview shows the new price as typed, never the ten-decimal storage form',
  text.includes('1312.5') && !text.includes('1312.5000000000'))
check('the unchanged row is labelled unchanged and the changed one is called out',
  text.includes('Price changed') && text.includes('Unchanged'))

// A reason is required: a changed file alone cannot move a price.
const confirmLabel = () => (Array.from(doc.querySelectorAll('button'))
  .find(button => /^Revise /.test(button.textContent || '')) ?? null)
const reasonBox = () => Array.from(doc.querySelectorAll('textarea, input')).find(input =>
  (input.closest('.MuiFormControl-root')?.textContent || '').includes('Reason for the price change'))
const typeReason = async value => {
  const field = reasonBox()
  assert.ok(field, 'the reason field is reachable')
  await act(async () => {
    const prototype = field.tagName === 'TEXTAREA' ? w.HTMLTextAreaElement.prototype : w.HTMLInputElement.prototype
    Object.getOwnPropertyDescriptor(prototype, 'value').set.call(field, value)
    field.dispatchEvent(new w.Event('input', { bubbles: true }))
    await new Promise(resolve => setTimeout(resolve, 0))
  })
}
const upload = async (input, chosen) => {
  await act(async () => {
    Object.defineProperty(input, 'files', { value: [chosen], configurable: true })
    input.dispatchEvent(new w.Event('change', { bubbles: true }))
    await new Promise(resolve => setTimeout(resolve, 60))
  })
  await act(async () => { await new Promise(resolve => setTimeout(resolve, 40)) })
}

closed = false
await mount(<BulkPriceRevisionDialog open config={TANGIBLE_CONFIG} current={records} onClose={() => { closed = true }} onRevised={() => {}}/>)
await upload(doc.querySelector('input[type="file"]'), file)
check('an uploaded file with no reason cannot be run',
  confirmLabel()?.disabled === true && (doc.body.textContent || '').includes('1 price will change'))
await typeReason('ab')
check('a reason shorter than three characters still cannot be run', confirmLabel()?.disabled === true)
await typeReason('November supplier increase')
check('a changed file plus a real reason can be run', confirmLabel()?.disabled === false)

// ---------------------------------------------------------------------------
// 3. The server's all-or-nothing refusal stays on screen, verbatim.
// ---------------------------------------------------------------------------
const refusal = '1 row could not be revised. No price was changed. Row 2: NOPE is not in this workspace. Download a fresh template.'
globalThis.fetch = async (url, options = {}) => {
  calls.push({ url: String(url), method: options.method || 'GET' })
  if (String(url).includes('bulk-revise')) {
    return { ok: false, status: 422, json: async () => ({ detail: refusal }) }
  }
  return jsonResponse({})
}
let closed = false
await mount(<BulkPriceRevisionDialog open config={TANGIBLE_CONFIG} current={records} onClose={() => { closed = true }} onRevised={() => {}}/>)
await upload(doc.querySelector('input[type="file"]'), file)
await typeReason('November supplier increase')
await act(async () => {
  confirmLabel()?.dispatchEvent(new w.MouseEvent('click', { bubbles: true }))
  await new Promise(resolve => setTimeout(resolve, 60))
})
text = doc.body.textContent || ''
check('a rejected file keeps the dialog open', closed === false)
check('it says plainly that no price was changed', text.includes('No price was changed'))
check("the server's row-level reason is shown unchanged", text.includes('NOPE is not in this workspace'))
check('the dialog never claims the revision succeeded', !text.includes('revised effective'))

const failures = checks.filter(item => !item.passed)
console.log(`Catalogue checks passed: ${checks.length - failures.length}/${checks.length}`)
console.log('  description columns, the change preview, the reason gate and the all-or-nothing refusal all hold.')
process.exit(failures.length ? 1 : 0)
