// Invoice Configuration — Deleted entries routing check.
//
// The page keeps one tab per configuration list and offers Restore / Delete
// permanently only on the Deleted entries view. Those two buttons must act on the
// *current* tab's list: an action built with a hard-coded kind looks correct on
// screen (the row's label is right) but silently restores or purges a record in
// another list. Nothing in the type system catches it, so this check presses the
// real buttons on the Description categories tab with a deleted row and asserts
// the request that leaves the page.
//
// Run:
//   cd frontend && NODE_PATH="$PWD/node_modules" ./node_modules/.bin/esbuild \
//     ../.agent/tools/invoice-config-deleted-check.jsx --bundle --platform=node --format=esm --jsx=automatic \
//     --outfile=node_modules/.cache/invoice-config-deleted-check.mjs --loader:.jsx=jsx --log-level=error --external:jsdom && \
//     node node_modules/.cache/invoice-config-deleted-check.mjs
import assert from 'node:assert/strict'
import { JSDOM } from 'jsdom'

const { window } = new JSDOM('<div id="root"></div>', {
  url: 'http://localhost/invoice-processing/configuration',
  pretendToBeVisual: true,
})
for (const key of [
  'window', 'document', 'navigator', 'HTMLElement', 'Element', 'Node', 'Event', 'KeyboardEvent', 'MouseEvent',
  'getComputedStyle', 'requestAnimationFrame', 'cancelAnimationFrame', 'CSS', 'SVGSVGElement', 'DocumentFragment',
  'ShadowRoot', 'CustomEvent', 'DOMRect', 'HTMLIFrameElement', 'HTMLInputElement', 'HTMLSelectElement', 'File', 'Blob',
]) {
  Object.defineProperty(globalThis, key, { value: window[key], configurable: true, writable: true })
}
for (const key of ['MutationObserver', 'IntersectionObserver', 'localStorage', 'sessionStorage', 'NodeList', 'HTMLCollection', 'DOMParser', 'SVGElement', 'FocusEvent', 'InputEvent', 'PointerEvent', 'WheelEvent', 'crypto']) {
  if (window[key] !== undefined) Object.defineProperty(globalThis, key, { value: window[key], configurable: true, writable: true })
}
globalThis.matchMedia =
  globalThis.matchMedia ||
  (() => ({ matches: false, addEventListener() {}, removeEventListener() {}, addListener() {}, removeListener() {} }))
window.matchMedia = globalThis.matchMedia
globalThis.ResizeObserver =
  globalThis.ResizeObserver || class { observe() {} unobserve() {} disconnect() {} }
window.ResizeObserver = globalThis.ResizeObserver
globalThis.IS_REACT_ACT_ENVIRONMENT = true
globalThis.HTMLElement.prototype.scrollIntoView =
  globalThis.HTMLElement.prototype.scrollIntoView || function scrollIntoView() {}

const { act } = await import('react')
const { MemoryRouter } = await import('react-router-dom')
const { createRoot } = await import('react-dom/client')
const { AuthProvider } = await import('../../frontend/src/context/AuthContext')
const { default: InvoiceConfigurationPage } = await import('../../frontend/src/pages/InvoiceConfiguration')

const permissions = ['invoice-processing:configure', 'invoice-processing:export', 'invoice-processing:read']

// A deleted row in every list, each with a distinct id, so a request naming the
// wrong list is visible in the URL and not just in the record.
const configuration = {
  vendors: [],
  currencies: [{ currency_code: 'USD', currency_name: 'US Dollar', currency_symbol: '$', is_default: true }],
  descriptions: [{ id: 'desc-live', name: 'Live description', description: '', is_active: true, is_deleted: false }],
  locations: [{ id: 'loc-deleted', name: 'Deleted location', description: '', is_active: true, is_deleted: true }],
  categories: [{ id: 'cat-deleted', name: 'Deleted category', description: '', is_active: true, is_deleted: true }],
  payment_terms: [{
    id: 'term-deleted', term_code: 'NET30', term_name: 'Deleted term', payment_days: 30, description: '',
    is_active: true, is_deleted: true, splits: [{ currency_code: 'USD', percentage: '100' }], vendor_ids: [],
  }],
  taxes: [{
    id: 'tax-deleted', tax_code: 'VAT', tax_name: 'Deleted tax', rate_percent: '7.5', direction: 'addition',
    is_report_visible: true, is_net_payable: true, is_common: true, description: '', is_active: true,
    is_deleted: true, vendor_ids: [],
  }],
  exchange_rates: [{
    id: 'rate-deleted', base_currency: 'USD', quote_currency: 'NGN', rate: '1500', description: '',
    is_active: true, is_deleted: true,
  }],
  blocks: [],
  signatories: [{
    id: 'sig-deleted', signatory_role: 'prepared', full_name: 'Deleted signatory', designation: '',
    is_active: true, is_deleted: true,
  }],
}
const posted = []
globalThis.fetch = async (path, init) => {
  const url = String(path)
  if (url.includes('/auth/refresh')) return Response.json({ access_token: 'test' })
  if (url.includes('/auth/me')) {
    return Response.json({
      is_owner: false, permission_keys: permissions, organization_name: 'Demo', email: 'owner@demo.example.com',
    })
  }
  if (url.includes('/invoice-processing/configuration')) return Response.json(configuration)
  if (url.includes('/invoice-processing/config/')) {
    posted.push({ url, method: init?.method ?? 'GET', body: init?.body ? JSON.parse(String(init.body)) : null })
    return Response.json({ affected_count: 1 })
  }
  throw new Error(`Unexpected request: ${url}`)
}

const host = document.createElement('div')
document.body.appendChild(host)
const root = createRoot(host)
const settle = async () => {
  for (let i = 0; i < 14; i += 1) await act(async () => { await new Promise((r) => setTimeout(r, 30)) })
}
await act(async () =>
  root.render(
    <AuthProvider>
      <MemoryRouter initialEntries={['/invoice-processing/configuration']}>
        <InvoiceConfigurationPage />
      </MemoryRouter>
    </AuthProvider>,
  ),
)
await settle()

const text = () => document.body.textContent ?? ''
// Row actions and the confirmation dialog's submit share a label ("Restore"),
// so `last` picks the dialog's button, which is where the request is made.
const pressText = async (label, { last = false } = {}) => {
  const matches = [...document.querySelectorAll('button')].filter((el) => (el.textContent ?? '').trim() === label)
  const button = last ? matches.at(-1) : matches[0]
  assert.ok(button, `a "${label}" button should be on screen; saw: ${[...document.querySelectorAll('button')].map((el) => (el.textContent ?? '').trim()).filter(Boolean).slice(0, 24).join(' | ')}`)
  await act(async () => { button.dispatchEvent(new window.MouseEvent('click', { bubbles: true })) })
  await settle()
}
const pressTab = async (label) => {
  const tab = [...document.querySelectorAll('[role="tab"]')].find((el) => (el.textContent ?? '').includes(label))
  assert.ok(tab, `the ${label} tab should exist`)
  await act(async () => { tab.dispatchEvent(new window.MouseEvent('click', { bubbles: true })) })
  await settle()
}

// A live tab never offers the permanent actions, and it never lists a deleted row.
assert.ok(!text().includes('Delete permanently'), 'a live configuration row must not offer permanent delete')
assert.ok(!text().includes('Deleted location'), 'a deleted row must stay out of the live view')
// The toggle counts the current list only, so each tab states its own total.
assert.ok(text().includes('Deleted entries (1)'), `the toggle should count this list; DOM held: ${text().slice(0, 400)}`)
await pressText('Deleted entries (1)')
assert.ok(text().includes('Deleted location'), 'the Deleted entries view should list the deleted rows')
assert.ok(text().includes('Restore'), 'a deleted row should offer Restore')

// Each tab must act on its own list. Description categories is the deepest list
// and was the one that mis-routed to Locations.
await pressTab('Description categories')
assert.ok(text().includes('Deleted category'), 'the deleted category should be listed')
await pressText('Restore')
await pressText('Restore', { last: true })
const restored = posted.at(-1)
assert.equal(
  restored?.url,
  '/api/v1/invoice-processing/config/categories/bulk-restore',
  `Restore must act on the category list, not another tab; sent ${restored?.url}`,
)
assert.deepEqual(restored?.body, { ids: ['cat-deleted'] }, 'Restore must name the pressed row')

await pressText('Delete permanently')
await pressText('Delete permanently', { last: true })
const purged = posted.at(-1)
assert.equal(
  purged?.url,
  '/api/v1/invoice-processing/config/categories/bulk-permanent-delete',
  `Delete permanently must act on the category list; sent ${purged?.url}`,
)
assert.deepEqual(purged?.body, { ids: ['cat-deleted'] }, 'the purge must name the pressed row')

// The same buttons on the tax list, so the routing is read from the tab and not
// from a single lucky constant.
await pressTab('Taxes')
await pressText('Delete permanently')
await pressText('Delete permanently', { last: true })
assert.equal(
  posted.at(-1)?.url,
  '/api/v1/invoice-processing/config/taxes/bulk-permanent-delete',
  `Delete permanently must follow the tab; sent ${posted.at(-1)?.url}`,
)
assert.deepEqual(posted.at(-1)?.body, { ids: ['tax-deleted'] })

await act(async () => root.unmount())
console.log('Invoice configuration Deleted entries: each tab restores and purges its own list.')
process.exit(0)
