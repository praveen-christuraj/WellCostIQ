// Cost Intelligence check.
//
// Three things are verified, on the real page and the real analysis output:
//   * the analysis of the five shaped demo wells (steady, creeping, one day
//     keyed too high with missing sheets, overrun with NPT, not started) finds
//     what was put there and nothing else. The fixture is the API's own answer
//     for those wells (`.agent/tools/demo-data.py` seeds them);
//   * the page mounted in jsdom renders the summary and all five figures, and a
//     real pointer press on a well's bar analyses that well and no other;
//   * the source contract: shared chart host, identity-based selection, design
//     tokens only, audited export, 20/50/100 paging.
//
// Run with `make cost-intelligence-check`.
import { JSDOM } from 'jsdom'

const dom = new JSDOM('<!doctype html><html><head></head><body><div id="root"></div></body></html>', { pretendToBeVisual: true, url: 'http://localhost/' })
const w = dom.window
w.matchMedia = w.matchMedia || (q => ({ matches: false, media: q, onchange: null, addListener() {}, removeListener() {}, addEventListener() {}, removeEventListener() {}, dispatchEvent: () => false }))
for (const key of ['localStorage', 'sessionStorage', 'window', 'document', 'navigator', 'HTMLElement', 'Element', 'Node', 'Event', 'getComputedStyle', 'requestAnimationFrame', 'cancelAnimationFrame', 'CSS', 'SVGSVGElement', 'DocumentFragment', 'ShadowRoot', 'MouseEvent', 'KeyboardEvent', 'CustomEvent', 'DOMRect', 'HTMLInputElement']) {
  Object.defineProperty(globalThis, key, { value: w[key], configurable: true, writable: true })
}
// The full page (grids, dialogs, routing) reads many more browser globals than
// a single chart does; expose whatever the window has and Node lacks.
for (const key of Object.getOwnPropertyNames(w)) {
  if (key in globalThis) continue
  try { Object.defineProperty(globalThis, key, { value: w[key], configurable: true, writable: true }) } catch { /* not exposable */ }
}
globalThis.IS_REACT_ACT_ENVIRONMENT = true

const { act } = await import('react')
const createCache = (await import('@emotion/cache')).default
const { CacheProvider } = await import('@emotion/react')
const { createRoot } = await import('react-dom/client')
const { ThemeProvider } = await import('@mui/material')
const { buildTheme } = await import('../../frontend/src/theme')
const { filterFindings, amount, signedPercent, REPORT_PRESETS, REPORT_SECTIONS } = await import('../../frontend/src/lib/costIntelligence')

const results = []
const check = (label, pass, detail = '') => results.push({ label, pass: !!pass, detail })

const { readFileSync } = await import('node:fs')
const locate = name => [`../${name}`, name].find(candidate => { try { readFileSync(candidate); return true } catch { return false } })
const fixture = JSON.parse(readFileSync(locate('.agent/tools/fixtures/cost-intelligence.json'), 'utf8'))
const me = JSON.parse(readFileSync(locate('.agent/tools/fixtures/dashboard-three-wells.json'), 'utf8')).me
const requested = []
const overviewCalls = []
const posts = []
const json = (payload, status = 200) => ({ ok: status < 400, status, json: async () => payload, text: async () => JSON.stringify(payload), headers: new Map() })
globalThis.fetch = async (url, init = {}) => {
  const path = String(url)
  if (path.includes('/auth/refresh')) return json({ access_token: 'check' })
  if (path.includes('/auth/me')) return json(me)
  const well = path.match(/\/cost-intelligence\/wells\/([^?]+)/)
  if (well) {
    requested.push(well[1])
    return fixture.details[well[1]] ? json(fixture.details[well[1]]) : json({ detail: 'Unknown well' }, 404)
  }
  if (path.includes('/cost-intelligence/overview')) { overviewCalls.push(path); return json(fixture.overview) }
  if (path.includes('/cost-intelligence/exports')) { posts.push(JSON.parse(init.body)); return json({}, 204) }
  if (path.includes('/health')) return json({ status: 'ok', api_version: '99.0.0' })
  return json({}, 404)
}
w.fetch = globalThis.fetch
const boxOf = element => (element.id === 'wcp-chart-zoom-probe' ? { width: 100, height: 100 } : { width: 640, height: 300 })
w.HTMLElement.prototype.getBoundingClientRect = function () {
  const box = boxOf(this)
  return { x: 0, y: 0, left: 0, top: 0, right: box.width, bottom: box.height, width: box.width, height: box.height, toJSON() {} }
}
Object.defineProperty(w.HTMLElement.prototype, 'clientWidth', { configurable: true, get() { return boxOf(this).width } })
Object.defineProperty(w.HTMLElement.prototype, 'clientHeight', { configurable: true, get() { return boxOf(this).height } })
globalThis.ResizeObserver = w.ResizeObserver = class { observe() {} unobserve() {} disconnect() {} }

const echarts = await import('echarts/core')
const { getECData } = await import('echarts/lib/util/innerStore.js')
const { MemoryRouter } = await import('react-router-dom')
const { AuthProvider } = await import('../../frontend/src/context/AuthContext')
const { ThemeModeProvider } = await import('../../frontend/src/context/ThemeContext')
const CostIntelligence = (await import('../../frontend/src/pages/CostIntelligence')).default

// ---- 1. the fixture is the analysis of the five shaped demo wells -------------
const overview = fixture.overview
const byCode = Object.fromEntries(overview.wells.map(row => [row.well_code, row]))
const codesOf = code => overview.findings.filter(row => row.well_code === code).map(row => row.code)
check('the steady well raises no cost or schedule finding', byCode['WELL-A'].critical + byCode['WELL-A'].warning === 0, codesOf('WELL-A').join(','))
check('the creeping well is caught by the trend check', codesOf('WELL-B').includes('drift-up'))
check('the creeping well is forecast over its AFE', codesOf('WELL-B').includes('forecast-overrun'))
check('the keyed-too-high day is the only unusual day reported', overview.findings.filter(row => row.code === 'cost-spike').length === 1 && codesOf('WELL-C').includes('cost-spike'))
check('the missing sheets are reported', codesOf('WELL-C').includes('missing-sheets'))
check('the overrun well reports AFE, schedule and NPT', ['afe-exceeded', 'schedule-overrun', 'npt-share'].every(code => codesOf('WELL-D').includes(code)), codesOf('WELL-D').join(','))
check('a well with no cost yet is not penalised', byCode['WELL-E'].score === 100)
check('every finding states its basis and a suggestion', overview.findings.every(row => row.basis.length > 20 && row.suggestion.length > 20))
check('suggestions are ranked and never list notes', overview.suggestions.every((row, index) => row.rank === index + 1 && row.severity !== 'info'))

// ---- 2. shared rules ---------------------------------------------------------
const all = overview.findings
check('the findings filter narrows by severity', filterFindings(all, { severity: 'critical', category: '', wellId: '', search: '' }).length === overview.kpis.critical)
check('the findings filter narrows by well', filterFindings(all, { severity: '', category: '', wellId: 'w-c', search: '' }).every(row => row.well_code === 'WELL-C'))
check('the findings filter searches text', filterFindings(all, { severity: '', category: '', wellId: '', search: 'creeping' }).length === 1)
check('amounts print whole units with a minus sign', amount(-1234.56, 'USD') === '−USD 1,235', amount(-1234.56, 'USD'))
check('a missing figure prints a dash', amount(null) === '—' && signedPercent(null) === '—')
check('every report preset only names real sections', Object.values(REPORT_PRESETS).every(preset => preset.sections.every(key => REPORT_SECTIONS.some(item => item.key === key))))

// ---- 3. the real page --------------------------------------------------------
const pageHost = w.document.createElement('div')
w.document.body.appendChild(pageHost)
const pageRoot = createRoot(pageHost)
const settle = async (ms = 30) => { await act(async () => { await new Promise(resolve => setTimeout(resolve, ms)) }) }
await act(async () => {
  pageRoot.render(
    <MemoryRouter>
      <ThemeModeProvider>
        <AuthProvider>
          <CostIntelligence/>
        </AuthProvider>
      </ThemeModeProvider>
    </MemoryRouter>,
  )
})
for (let i = 0; i < 30 && !pageHost.querySelector('[data-chart-key="ci-well-daily"] svg'); i++) await settle(50)
const text = () => pageHost.textContent
check('the page renders the forecast chart', Boolean(pageHost.querySelector('[data-chart-key="ci-forecast"] svg')))
check('the page renders the selected well charts', ['ci-well-daily', 'ci-well-cumulative', 'ci-well-trend'].every(key => pageHost.querySelector(`[data-chart-key="${key}"] svg`)))
check('the written summary is shown', overview.headline.every(line => text().includes(line)))
check('the page opens on the well that most needs attention', requested[0] === overview.wells.find(row => row.recorded_days > 0).well_id, requested.join(','))
check('one analysis request is made on load', overviewCalls.length === 1, String(overviewCalls.length))
check('five figures are marked for export with unique keys', new Set([...pageHost.querySelectorAll('[data-chart-figure]')].map(node => node.getAttribute('data-chart-key'))).size === 5)

const chartOf = key => {
  const element = pageHost.querySelector(`[data-chart-key="${key}"] .echarts-for-react`)
  return element ? echarts.getInstanceByDom(element) : null
}
const barsOf = chart => {
  const bars = []
  for (const element of chart.getZr().storage.getDisplayList()) {
    const info = getECData(element)
    if (info?.dataIndex == null || info.seriesIndex == null) continue
    const rect = element.getBoundingRect().clone()
    if (element.transform) rect.applyTransform(element.transform)
    if (rect.width < 1 || rect.height < 1) continue
    const item = chart.getOption().series[info.seriesIndex]?.data?.[info.dataIndex]
    bars.push({ seriesIndex: info.seriesIndex, x: rect.x + rect.width / 2, y: rect.y + rect.height / 2, label: item?.name })
  }
  return bars
}
const press = async (chart, x, y) => {
  const layer = chart.getZr().painter.getViewportRoot()
  for (const type of ['mousemove', 'mousedown', 'mouseup', 'click']) {
    const event = new w.MouseEvent(type, { bubbles: true, cancelable: true, clientX: x, clientY: y, button: 0 })
    for (const key of ['offsetX', 'offsetY', 'zrX', 'zrY']) Object.defineProperty(event, key, { value: key.endsWith('X') ? x : y, configurable: true })
    await act(async () => { layer.dispatchEvent(event) })
  }
  await settle(40)
}
// Pressing a well's bar analyses that well: the page asks for it and no other.
const forecast = chartOf('ci-forecast')
check('the forecast chart instance is live', Boolean(forecast))
if (forecast) {
  const bars = barsOf(forecast)
  const drawn = [...new Set(bars.map(bar => bar.label))].sort().join(',')
  check('bars are drawn for every well with an AFE', drawn === 'WELL-A,WELL-B,WELL-C,WELL-D,WELL-E', drawn)
  let current = requested[requested.length - 1]
  for (const code of ['WELL-A', 'WELL-C', 'WELL-D', 'WELL-B', 'WELL-E']) {
    const expected = byCode[code].well_id
    for (const bar of bars.filter(item => item.label === code)) {
      requested.length = 0
      await press(forecast, bar.x, bar.y)
      // Selecting the well already selected asks for nothing new; anything
      // else must be exactly the pressed well.
      const ok = expected === current ? requested.length === 0 : requested.length === 1 && requested[0] === expected
      check(`pressing ${code} (series ${bar.seriesIndex}) analyses ${code}`, ok, `asked for ${requested.join(',') || 'nothing'}`)
      current = expected
    }
  }
}
check('the selected well heading follows the press', text().includes('Well analysis: WELL-E'))

// A row in the health table selects its own well.
const row = [...pageHost.querySelectorAll('tbody tr')].find(node => node.textContent.startsWith('WELL-D'))
requested.length = 0
await act(async () => { row.click() })
await settle(40)
check('a well health row analyses its own well', requested.length === 1 && requested[0] === byCode['WELL-D'].well_id, requested.join(','))

// ---- 4. source contract ------------------------------------------------------
const pageSource = readFileSync(locate('frontend/src/pages/CostIntelligence.tsx'), 'utf8')
check('charts go through the shared host', !/echarts-for-react/.test(pageSource) && (pageSource.match(/<InteractiveChart/g) ?? []).length === 5)
check('no colour is hardcoded on the page', !/#[0-9a-fA-F]{3,8}\b/.test(pageSource))
check('the well selection resolves by identity against the plotted rows', /chartDrillHandler<IntelligenceWell>\(forecastRows, plottedWell/.test(pageSource))
check('exports are audited', /\/cost-intelligence\/exports/.test(pageSource))
check('the findings list pages at 20, 50 and 100', /PAGE_SIZES = \[20, 50, 100\]/.test(pageSource))

let failed = 0
for (const r of results) { if (!r.pass) failed++; console.log(`${r.pass ? 'PASS' : 'FAIL'}  ${r.label}${r.detail ? `  [${r.detail}]` : ''}`) }
console.log(failed === 0 ? `\nALL ${results.length} COST INTELLIGENCE CHECKS PASSED` : `\n${failed} of ${results.length} CHECKS FAILED`)
process.exit(failed ? 1 : 0)
