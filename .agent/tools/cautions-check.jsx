// Dismissible cautions: the store, the component, and the two rules that keep a
// dismissal honest — it is per workspace, and it expires when the facts change.
//
// Run with: make cautions-check
import assert from 'node:assert/strict'
import { JSDOM } from 'jsdom'

const dom = new JSDOM('<html><body><div id="root"></div></body></html>', { pretendToBeVisual: true, url: 'http://localhost/' })
const w = dom.window
w.matchMedia = query => ({ matches: false, media: query, addListener() {}, removeListener() {}, addEventListener() {}, removeEventListener() {} })
for (const key of ['window', 'document', 'navigator', 'HTMLElement', 'Element', 'Node', 'Event', 'CustomEvent', 'getComputedStyle', 'requestAnimationFrame', 'cancelAnimationFrame', 'CSS', 'DocumentFragment', 'MouseEvent', 'KeyboardEvent', 'DOMParser', 'localStorage']) {
  Object.defineProperty(globalThis, key, { value: w[key], configurable: true, writable: true })
}
globalThis.IS_REACT_ACT_ENVIRONMENT = true

const { act } = await import('react')
const { createRoot } = await import('react-dom/client')
const { MemoryRouter } = await import('react-router-dom')
const { ThemeProvider } = await import('@mui/material/styles')
const { buildTheme } = await import('../../frontend/src/theme')
const { AuthProvider } = await import('../../frontend/src/context/AuthContext')
const { Caution, RestoreCautions } = await import('../../frontend/src/components/ui/Caution')
const cautions = await import('../../frontend/src/lib/cautions')

const settle = async (ms = 0) => { await act(async () => { await new Promise(resolve => setTimeout(resolve, ms)) }) }
const page = 'cautions-check'
const scope = { organizationSlug: 'north-field', page }
const otherWorkspace = { organizationSlug: 'south-field', page }
// The mounted components read the signed-in user; this check has no session, so
// the workspace part of their scope is empty. Store calls made *on behalf of* the
// page must use the same scope the page will, or they would land in a different
// workspace bucket.
const mountedScope = { organizationSlug: undefined, page }

// 1. The store. A dismissal is remembered for one exact wording, in one workspace.
const signature = cautions.cautionSignature('no-plan', '1 well has no cost plan')
assert.equal(cautions.isCautionDismissed('no-plan', signature, scope), false, 'nothing is dismissed before the reader acts')
cautions.dismissCaution('no-plan', signature, scope)
assert.equal(cautions.isCautionDismissed('no-plan', signature, scope), true, 'the dismissal is remembered')
assert.equal(cautions.isCautionDismissed('no-plan', cautions.cautionSignature('no-plan', '4 wells have no cost plan'), scope), false, 'a caution that now says something else is a new fact and comes back')
assert.equal(cautions.dismissedCautionCount(scope), 1)
assert.equal(cautions.dismissedCautionCount(otherWorkspace), 0, 'two workspaces in one browser never share notes')
assert.equal(cautions.isCautionDismissed('no-plan', signature, otherWorkspace), false)
assert.equal(cautions.dismissedCautionCount({ page: 'another-page', organizationSlug: 'north-field' }), 0, 'a note on one page never hides a caution on another')
cautions.restorePageCautions(scope)
assert.equal(cautions.dismissedCautionCount(scope), 0, 'Show dismissed cautions clears the page')
assert.equal(cautions.isCautionDismissed('no-plan', signature, scope), false)

// 2. A stale note is forgotten, so the page count only describes what is hidden now.
cautions.dismissCaution('no-plan', signature, scope)
cautions.pruneCaution('no-plan', cautions.cautionSignature('no-plan', '4 wells have no cost plan'), scope)
assert.equal(cautions.dismissedCautionCount(scope), 0, 'a note the caution has outgrown is dropped')
assert.equal(cautions.isCautionDismissed('no-plan', signature, scope), false, 'and it no longer hides the current caution')

// 3. A broken or hostile store never breaks a page.
w.localStorage.setItem('wcp.dismissed-cautions:north-field', 'not json at all')
assert.equal(cautions.isCautionDismissed('no-plan', signature, scope), false, 'unreadable notes read as "nothing dismissed"')
assert.equal(cautions.dismissedCautionCount(scope), 0)
w.localStorage.setItem('wcp.dismissed-cautions:north-field', '["array"]')
assert.equal(cautions.dismissedCautionCount(scope), 0, 'a legacy array value is ignored')
w.localStorage.removeItem('wcp.dismissed-cautions:north-field')

// 4. The component. It renders, dismisses on the button, folds away, and the page
//    offers the way back — without a reload.
const host = w.document.createElement('div')
w.document.body.appendChild(host)
const root = createRoot(host)
const text = () => host.textContent ?? ''
const click = async (element, message) => {
  assert.ok(element, message)
  await act(async () => element.dispatchEvent(new w.MouseEvent('click', { bubbles: true })))
  await settle()
}
const render = async (count, extra = null) => {
  await act(async () => root.render(<MemoryRouter><ThemeProvider theme={buildTheme('light')}><AuthProvider>
    <RestoreCautions page={page}/>
    <Caution cautionKey="no-plan" page={page} signature={[count, 'well-1']}>
      {`${count} well${count === 1 ? '' : 's'} ha${count === 1 ? 's' : 've'} no cost plan.`}
    </Caution>
    <Caution cautionKey="currency" page={page} severity="info" signature={['EUR']}>
      Figures in EUR are excluded from this total.
    </Caution>
    {extra}
  </AuthProvider></ThemeProvider></MemoryRouter>))
  await settle()
}

await render(1)
assert.ok(text().includes('1 well has no cost plan.'), 'the caution is shown until it is read')
assert.ok(text().includes('Figures in EUR are excluded'), 'every caution on the page is dismissible')
assert.ok(!text().includes('dismissed on this page'), 'a page with no dismissal shows no restore affordance')

await click(w.document.querySelector('button[aria-label="Dismiss this caution"]'), 'the caution has a dismiss button')
assert.ok(!text().includes('1 well has no cost plan.'), 'it folds away when dismissed')
assert.ok(text().includes('Figures in EUR are excluded'), 'dismissing one caution leaves the others alone')
assert.ok(text().includes('1 caution dismissed on this page.'), 'the page offers to bring it back')

// The count is live: dismissing a second caution updates the figure beside it.
const dismissButtons = () => [...w.document.querySelectorAll('button[aria-label="Dismiss this caution"]')]
await click(dismissButtons()[0], 'the second caution can be dismissed too')
assert.ok(text().includes('2 cautions dismissed on this page.'), 'the restore affordance follows every dismissal')

await click([...w.document.querySelectorAll('button')].find(button => button.textContent === 'Show dismissed cautions'), 'Show dismissed cautions exists')
assert.ok(text().includes('1 well has no cost plan.'), 'it comes back on request, without a reload')
assert.ok(text().includes('Figures in EUR are excluded'), 'and so does the other one')
assert.ok(!text().includes('dismissed on this page'), 'the restore affordance disappears once nothing is dismissed')

// 5. Changed facts override the dismissal: a dismissal is not a mute switch.
//    Dismiss the one-well wording through the real store, then mount the same
//    page with four wells.
cautions.dismissCaution('no-plan', cautions.cautionSignature('no-plan', '1 well has no cost plan.', cautions.cautionSignature(1, 'well-1')), mountedScope)
assert.equal(cautions.dismissedCautionCount(mountedScope), 1, 'the one-well note is stored')
await render(4)
assert.ok(text().includes('4 wells have no cost plan.'), 'a caution whose count changed is shown again')
assert.ok(!text().includes('dismissed on this page'), 'and the stale note does not linger as a dismissal')

// 6. Transient messages are not cautions: they keep their own control and are never
//    remembered, so a failed save cannot be silently hidden forever.
const transient = <Caution cautionKey="save-failed" page={page} severity="error" transient signature={['boom']}>The sheet was not saved.</Caution>
await act(async () => root.unmount())
assert.equal(cautions.dismissedCautionCount(mountedScope), 0, 'the stale note was forgotten when the facts changed')
const transientHost = w.document.createElement('div')
w.document.body.appendChild(transientHost)
const transientRoot = createRoot(transientHost)
await act(async () => transientRoot.render(<ThemeProvider theme={buildTheme('light')}><AuthProvider>{transient}</AuthProvider></ThemeProvider>))
await settle()
assert.ok(transientHost.textContent.includes('The sheet was not saved.'), 'a transient message is shown')
assert.equal(transientHost.querySelector('button[aria-label="Dismiss this caution"]'), null, 'it has no dismissal button')
assert.equal(cautions.dismissedCautionCount(mountedScope), 0, 'and nothing was remembered')
await act(async () => transientRoot.unmount())

// 7. Both themes render the same words and controls.
for (const mode of ['light', 'dark']) {
  const themed = w.document.createElement('div')
  w.document.body.appendChild(themed)
  const themedRoot = createRoot(themed)
  await act(async () => themedRoot.render(<MemoryRouter><ThemeProvider theme={buildTheme(mode)}><AuthProvider>
    <Caution cautionKey="theme" page={page} signature={[mode]}>Same caution in {mode}.</Caution>
  </AuthProvider></ThemeProvider></MemoryRouter>))
  await settle()
  assert.ok(themed.textContent.includes(`Same caution in ${mode}.`), `${mode}: the caution renders`)
  assert.ok(themed.querySelector('button[aria-label="Dismiss this caution"]'), `${mode}: the dismiss control is present`)
  await act(async () => themedRoot.unmount())
  themed.remove()
}

await act(async () => root.unmount())
w.localStorage.clear()
console.log('Cautions check: dismissals are per workspace, live, and expire when the facts change; transient messages stay transient; light and dark agree.')
// jsdom keeps timers and the React scheduler alive; the checks are done.
process.exit(0)
