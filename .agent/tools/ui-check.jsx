// Design-layer check: renders the real theme and shared dialog/chip components in a DOM and
// asserts the rules the design system promises (focus rings, dialog semantics and naming,
// destructive-action colour, CSS-variable status chips) in light and dark.
//
// It is a contributor tool, not part of the application build: nothing here is imported by the
// app, and jsdom is installed with --no-save, so the app's own dependencies stay unchanged.
//
// Run from frontend/ (writes its bundle inside node_modules, so Node resolves jsdom):
//   npm install --no-save jsdom && NODE_PATH="$PWD/node_modules" ./node_modules/.bin/esbuild \
//     ../.agent/tools/ui-check.jsx --bundle --platform=node --format=esm --jsx=automatic \
//     --outfile=node_modules/.cache/ui-check.mjs --loader:.jsx=jsx --log-level=error \
//     --external:jsdom && node node_modules/.cache/ui-check.mjs
//
// Exits non-zero when a rule fails, so it can gate a UI change.
import { JSDOM } from 'jsdom'
import { readFileSync, readdirSync } from 'node:fs'
import { join } from 'node:path'

const dom = new JSDOM('<!doctype html><html><head></head><body><div id="root"></div></body></html>', { pretendToBeVisual: true, url: 'http://localhost/' })
const w = dom.window
w.matchMedia = w.matchMedia || (q => ({ matches: false, media: q, onchange: null, addListener() {}, removeListener() {}, addEventListener() {}, removeEventListener() {}, dispatchEvent: () => false }))
for (const key of ['window', 'document', 'navigator', 'HTMLElement', 'Element', 'Node', 'Event', 'getComputedStyle', 'requestAnimationFrame', 'cancelAnimationFrame', 'CSS', 'SVGSVGElement', 'DocumentFragment', 'ShadowRoot', 'MouseEvent', 'KeyboardEvent', 'CustomEvent', 'DOMRect', 'HTMLIFrameElement', 'HTMLInputElement']) {
  Object.defineProperty(globalThis, key, { value: w[key], configurable: true, writable: true })
}
globalThis.IS_REACT_ACT_ENVIRONMENT = true

const { act } = await import('react')
const createCache = (await import('@emotion/cache')).default
const { CacheProvider } = await import('@emotion/react')
const { createRoot } = await import('react-dom/client')
const { ThemeProvider, CssBaseline } = await import('@mui/material')
const { buildTheme } = await import('../../frontend/src/theme')
const { chartPalette } = await import('../../frontend/src/designSystem')
const { FormDialog, PanelDialog, Tag, ErrorMessage } = await import('../../frontend/src/components/Common')
const { InteractiveChart } = await import('../../frontend/src/components/ui/InteractiveChart')

const results = []
const check = (label, pass, detail = '') => results.push({ label, pass, detail })

const container = w.document.getElementById('root')
const root = createRoot(container)

for (const mode of ['light', 'dark']) {
  const cache = createCache({ key: 'csscheck', speedy: false }) // text nodes, so the CSS is readable
  await act(async () => {
    root.render(
      <CacheProvider value={cache}>
        <ThemeProvider theme={buildTheme(mode)}>
          <CssBaseline/>
          <Tag tone="warning">Pending</Tag>
          <ErrorMessage message="Row 3 failed"/>
          <FormDialog open danger title="Permanently delete entries?" subtitle="This cannot be undone." onClose={() => {}} onSubmit={() => {}} submitLabel="Permanently delete">
            <p>body</p>
          </FormDialog>
        </ThemeProvider>
      </CacheProvider>
    )
  })
  const doc = w.document
  const dialog = doc.querySelector('[role="dialog"]')
  const labelledBy = dialog?.getAttribute('aria-labelledby')
  const describedBy = dialog?.getAttribute('aria-describedby')
  const titleEl = labelledBy ? doc.getElementById(labelledBy) : null
  const subEl = describedBy ? doc.getElementById(describedBy) : null
  check(`${mode}: dialog exposes aria-labelledby`, Boolean(labelledBy) && Boolean(titleEl), `${labelledBy}`)
  check(`${mode}: accessible name is the title only`, titleEl?.textContent === 'Permanently delete entries?', JSON.stringify(titleEl?.textContent))
  check(`${mode}: aria-describedby points at the subtitle`, subEl?.textContent === 'This cannot be undone.', JSON.stringify(subEl?.textContent))
  const ids = [...doc.querySelectorAll('[id]')].map(e => e.id)
  check(`${mode}: no duplicate ids`, new Set(ids).size === ids.length, ids.join(','))
  const buttons = [...doc.querySelectorAll('[role="dialog"] button')]
  check(`${mode}: Cancel button present`, buttons.some(b => b.textContent === 'Cancel'), buttons.map(b => b.textContent).join('|'))
  const submit = buttons.find(b => b.textContent === 'Permanently delete')
  check(`${mode}: destructive submit uses the error colour`, Boolean(submit?.className.includes('MuiButton-containedError')), submit?.className.split(' ').filter(c => c.startsWith('MuiButton-contained')).join(','))
  check(`${mode}: dialog has no close icon`, doc.querySelectorAll('[role="dialog"] svg[data-testid="CloseIcon"]').length === 0)
  check(`${mode}: no nested heading in the dialog title`, doc.querySelectorAll('[role="dialog"] h2 h1, [role="dialog"] h2 h2, [role="dialog"] h2 h3, [role="dialog"] h2 h4, [role="dialog"] h2 h5, [role="dialog"] h2 h6').length === 0)
  check(`${mode}: dialog title element exists`, doc.querySelectorAll('[role="dialog"] h2').length === 1)
  const css = [...doc.querySelectorAll('style')].map(s => s.textContent).join('\n')
  check(`${mode}: focus ring injected into the document`, css.includes(':focus-visible{outline:2px solid'))
  check(`${mode}: chip colours resolve from CSS variables`, css.includes('var(--wcp-tone-warning-bg)'))
  check(`${mode}: error message announced`, Boolean(doc.querySelector('[role="alert"]')))
  check(`${mode}: dialog footer separated`, Boolean(doc.querySelector('.MuiDialogActions-root')))
}

// PanelDialog: same rules, footer button instead of a submit action.
const cache2 = createCache({ key: 'csscheck2', speedy: false })
await act(async () => {
  root.render(
    <CacheProvider value={cache2}>
      <ThemeProvider theme={buildTheme('light')}>
        <PanelDialog open title="Attachments" onClose={() => {}}>files</PanelDialog>
      </ThemeProvider>
    </CacheProvider>
  )
})
{
  const doc = w.document
  const dialog = doc.querySelector('[role="dialog"]')
  check('panel dialog labelled', Boolean(dialog?.getAttribute('aria-labelledby')))
  check('panel dialog has a close button', [...doc.querySelectorAll('[role="dialog"] button')].some(b => b.textContent === 'Close'))
}

// Render the real shared chart host, not only its source contract, so modular
// ECharts registrations and SVG output are exercised by the UI check.
await act(async () => {
  root.render(<InteractiveChart
    option={{ xAxis: { type: 'category', data: ['A'] }, yAxis: { type: 'value' }, tooltip: {}, series: [{ type: 'bar', data: [1] }] }}
    opts={{ width: 240, height: 160 }}
  />)
  await new Promise(resolve => setTimeout(resolve, 0))
})
check('shared chart host renders an SVG scene', Boolean(w.document.querySelector('[data-chart-renderer="svg"] svg')))

// Layout needs authenticated application context, so these source-level checks
// protect the shared shell without duplicating a mock permission model here.
const layoutSource = readFileSync('src/components/Layout.tsx', 'utf8')
const apiSource = readFileSync('src/lib/api.ts', 'utf8')
const dataTableSource = readFileSync('src/components/DataTable.tsx', 'utf8')
check('shell uses permission-aware side navigation', layoutSource.includes('aria-label="Primary navigation"') && layoutSource.includes('modulesForUser'))
check('desktop navigation can collapse and persists', layoutSource.includes('wcp-nav-expanded') && layoutSource.includes('Collapse navigation'))
check('mobile navigation uses a drawer', layoutSource.includes('<Drawer open={mobileOpen}'))
check('main work area has no fixed width cap', !layoutSource.includes('maxWidth: 1600'))
check('failed API actions emit visible feedback', apiSource.includes("CustomEvent('api-error'") && layoutSource.includes('<Snackbar open={!!apiNotice}'))
check('grid pagination menu escapes the zoomed coordinate space', dataTableSource.includes("popupParent={typeof document === 'undefined' ? null : document.body}"))

// Every ECharts surface shares one zoom-aware SVG host. Canvas pointer
// coordinates drift under the app shell's CSS zoom, so a direct renderer import
// is a regression even when the individual chart options look correct.
const sourceFiles = []
const collectSources = directory => {
  for (const entry of readdirSync(directory, { withFileTypes: true })) {
    const path = join(directory, entry.name)
    if (entry.isDirectory()) collectSources(path)
    else if (/\.tsx?$/.test(entry.name)) sourceFiles.push(path)
  }
}
collectSources('src')
const directEChartsUsers = sourceFiles.filter(path => path !== 'src/components/ui/InteractiveChart.tsx' && readFileSync(path, 'utf8').includes('echarts-for-react'))
const chartHostSource = readFileSync('src/components/ui/InteractiveChart.tsx', 'utf8')
const chartUsageCount = sourceFiles.reduce((count, path) => count + (readFileSync(path, 'utf8').match(/<InteractiveChart\b/g)?.length ?? 0), 0)
check('all interactive charts use the shared precision host', directEChartsUsers.length === 0 && chartUsageCount === 14, `${chartUsageCount} charts; direct renderers: ${directEChartsUsers.join(',') || 'none'}`)
check('chart host corrects zoomed pointer mapping with SVG', chartHostSource.includes("renderer: 'svg'") && chartHostSource.includes('transitionDuration: 0'))
for (const mode of ['light', 'dark']) {
  const colours = chartPalette(mode).series
  check(`${mode}: visualization palette has 12 distinct series colours`, colours.length === 12 && new Set(colours).size === colours.length)
}

let failed = 0
for (const r of results) { if (!r.pass) failed++; console.log(`${r.pass ? 'PASS' : 'FAIL'}  ${r.label}${r.detail ? `  [${r.detail}]` : ''}`) }
console.log(failed === 0 ? `\nALL ${results.length} UI CHECKS PASSED` : `\n${failed} of ${results.length} CHECKS FAILED`)
process.exit(failed ? 1 : 0)
