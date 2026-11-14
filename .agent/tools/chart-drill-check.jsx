// Chart drill-through identity check.
//
// Renders the real shared chart host in jsdom with the *same option shapes the
// Operations dashboard builds* (a reversed "AFE against actual cost" bar chart and
// a sorted "Planned days against actual time" stacked chart) and simulates the
// click ECharts reports for a given plotted row. The check asserts that the click
// opens the well that was plotted at that position:
//
//   * identity, when the point carries it (the normal path);
//   * the *plotted* array position, when a series type reports only a row number;
//   * never the neighbouring well — the reported "clicked A, opened C" bug;
//   * and, the part that matters, the *real Operations dashboard page* mounted
//     against an API-shaped payload (wells A, B, C), with real pointer events
//     pressed on every drawn bar and on each well's row. The check reads which
//     well the drill-through panel then asks the API for. Earlier versions of
//     this check called the resolver directly with a hand-built payload and so
//     passed while the page opened the wrong well.
//
// Contributor tool only — nothing here is imported by the app, and jsdom is
// installed with --no-save so application dependencies stay unchanged.
//
// Run from frontend/:
//   npm install --no-save jsdom && NODE_PATH="$PWD/node_modules" ./node_modules/.bin/esbuild \
//     ../.agent/tools/chart-drill-check.jsx --bundle --platform=node --format=esm \
//     --jsx=automatic --outfile=node_modules/.cache/chart-drill-check.mjs \
//     --loader:.jsx=jsx --log-level=error --external:jsdom && \
//     node node_modules/.cache/chart-drill-check.mjs
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
const { InteractiveChart } = await import('../../frontend/src/components/ui/InteractiveChart')
const { chartData, chartDrillHandler, chartRowId, resolveChartClick } = await import('../../frontend/src/lib/chartInteraction')

const results = []
const check = (label, pass, detail = '') => results.push({ label, pass: !!pass, detail })

// ---- the three wells from the report ---------------------------------------
// Deliberately spaced so "largest first" and "smallest first" disagree with the
// source order: A is the biggest plan, C the smallest.
const rows = [
  { well_id: 'w-a', well_code: 'WELL-A', afe_amount: '900', actual_amount: '400', actual_days: '30', npt_days: '2', upa_days: '1', planned_days: '40' },
  { well_id: 'w-b', well_code: 'WELL-B', afe_amount: '600', actual_amount: '900', actual_days: '20', npt_days: '0', upa_days: '4', planned_days: '18' },
  { well_id: 'w-c', well_code: 'WELL-C', afe_amount: '300', actual_amount: '100', actual_days: '40', npt_days: '8', upa_days: '0', planned_days: '35' },
]
const idOf = row => chartRowId('well', row.well_id)

// ---- 1. identity resolution (the normal path) -------------------------------
const plotted = [...rows].reverse()   // the chart draws smallest plan at the bottom
const data = chartData(plotted, idOf, row => Number(row.afe_amount), row => row.well_code)
check('plotted data carries each well identity', data.length === 3 && data.every((item, index) => item.chartRowId === idOf(plotted[index])))
check('plotted data keeps the well code as its label', data.map(item => item.name).join(',') === 'WELL-C,WELL-B,WELL-A')

const opened = []
const handler = chartDrillHandler(plotted, idOf, row => opened.push(row.well_id))
handler({ dataIndex: 0, data: data[0], name: data[0].name })
check('clicking the first plotted bar opens the first plotted well', opened[0] === 'w-c', String(opened[0]))
handler({ dataIndex: 1, data: data[1] })
check('clicking the middle bar opens the middle well', opened[1] === 'w-b', String(opened[1]))
handler({ dataIndex: 2, data: data[2] })
check('clicking the last bar opens the last well', opened[2] === 'w-a', String(opened[2]))

// The reported bug, stated exactly: the plot is reversed, so a handler that
// indexed the *source* array by the plotted row number opened A's row for the
// bottom bar and C's row for the top bar. Resolve the top bar (WELL-A, plotted
// last) and prove it opens WELL-A, not the source array's last row (WELL-C).
opened.length = 0
handler({ dataIndex: 2, data: data[2] })
const sourceOrderIndexed = rows[2].well_id          // what the old handler opened
check(
  'the reported bug is not reintroduced: the top bar opens WELL-A, not the source order',
  opened[0] === 'w-a' && opened[0] !== sourceOrderIndexed,
  `${opened[0]} vs source-order ${sourceOrderIndexed}`,
)

// ---- 2. positional fallback stays inside the plotted array -----------------
// A scatter series can report the row number without the item identity. The
// fallback must still read the plotted array, not the source order.
const withoutIdentity = [{ value: 1 }, { value: 2 }, { value: 3 }]
const fallback = chartDrillHandler(plotted, idOf, row => opened.push(row.well_id))
opened.length = 0
fallback({ dataIndex: 1, data: withoutIdentity[1] })
check('a click without identity falls back to the plotted position', opened[0] === 'w-b', String(opened[0]))

// A row number outside the plotted array opens nothing instead of the wrong well.
opened.length = 0
fallback({ dataIndex: 9, data: {} })
check('an out-of-range click opens nothing', opened.length === 0)

// ---- 3. day chart: stacked series share the category ------------------------
const daysPlotted = [...rows].sort((left, right) => Number(right.actual_days) - Number(left.actual_days))
const productive = chartData(daysPlotted, idOf, row => Number(row.actual_days) - Number(row.npt_days) - Number(row.upa_days), row => row.well_code)
const npt = chartData(daysPlotted, idOf, row => Number(row.npt_days), row => row.well_code)
const dayHandler = chartDrillHandler(daysPlotted, idOf, row => opened.push(row.well_id))
opened.length = 0
dayHandler({ dataIndex: 2, seriesIndex: 0, data: productive[2] })
check('productive-days click opens its own well', opened[0] === daysPlotted[2].well_id, String(opened[0]))
dayHandler({ dataIndex: 0, seriesIndex: 2, data: npt[0] })
check('NPT-days click in another stack opens the same category well', opened[1] === daysPlotted[0].well_id, String(opened[1]))

// ---- 4. the shape the shared host really delivers ---------------------------
// The host does not pass the raw ECharts payload on: it emits a normalised event
// with the identity at the top level. The resolver must read that shape too —
// when it did not, the identity was lost and the click fell back to a position.
const hostModule = await import('../../frontend/src/components/ui/InteractiveChart')
const { normaliseClick, categoryBandClick } = hostModule
const normalised = normaliseClick({ dataIndex: 2, seriesIndex: 0, name: 'WELL-A', data: data[2] })
check('the host event carries the identity at the top level', normalised.chartRowId === 'well:w-a', normalised.chartRowId)
check('the host event keeps the plotted data item', normalised.data === data[2])
const sourceOrderHandler = chartDrillHandler(plotted, idOf, row => opened.push(row.well_id))
opened.length = 0
sourceOrderHandler(normalised)
check('a normalised host click opens the well it names', opened[0] === 'w-a', String(opened[0]))
// Even a caller that hands the resolver the WRONG array (the source order, as
// the dashboard once did) must not open a neighbouring well.
opened.length = 0
chartDrillHandler(rows, idOf, row => opened.push(row.well_id))(normalised)
check('identity wins even against an array in another order', opened[0] === 'w-a', String(opened[0]))
// A click naming a record that is not plotted opens nothing — never a guess.
opened.length = 0
chartDrillHandler(plotted, idOf, row => opened.push(row.well_id))(normaliseClick({ dataIndex: 0, data: { value: 1, chartRowId: 'well:gone' } }))
check('an identity that is not plotted opens nothing', opened.length === 0, String(opened[0]))

// ---- 5. the real Operations dashboard, real pointer events -------------------
// Mount the page itself against an API-shaped payload with wells A, B and C,
// press the pointer on each drawn bar, and read which well the drill-through
// panel asks the API for. This is the defect as the user met it.
const { readFileSync } = await import('node:fs')
const fixturePath = ['../.agent/tools/fixtures/dashboard-three-wells.json', '.agent/tools/fixtures/dashboard-three-wells.json']
  .find(candidate => { try { readFileSync(candidate); return true } catch { return false } })
const fixture = JSON.parse(readFileSync(fixturePath, 'utf8'))
const requested = []
const json = (payload, status = 200) => ({ ok: status < 400, status, json: async () => payload, text: async () => JSON.stringify(payload), headers: new Map() })
globalThis.fetch = async (url) => {
  const path = String(url)
  if (path.includes('/auth/refresh')) return json({ access_token: 'check' })
  if (path.includes('/auth/me')) return json(fixture.me)
  const well = path.match(/\/dashboard\/business\/wells\/([^?]+)/)
  if (well) {
    requested.push(well[1])
    const row = fixture.dashboard.wells.find(item => item.well_id === well[1])
    return json({ ...fixture.detail, well: row ?? fixture.detail.well })
  }
  if (path.includes('/dashboard/business')) return json(fixture.dashboard)
  if (path.includes('/health')) return json({ status: 'ok', api_version: '99.0.0' })
  return json({}, 404)
}
w.fetch = globalThis.fetch
// jsdom has no layout: give every element a real box so ECharts draws to scale,
// and keep the application-zoom probe at exactly 100px (zoom 1).
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
const BusinessDashboard = (await import('../../frontend/src/pages/BusinessDashboard')).default

const pageHost = w.document.createElement('div')
w.document.body.appendChild(pageHost)
const pageRoot = createRoot(pageHost)
const settle = async (ms = 30) => { await act(async () => { await new Promise(resolve => setTimeout(resolve, ms)) }) }
await act(async () => {
  pageRoot.render(
    <MemoryRouter>
      <ThemeModeProvider>
        <AuthProvider>
          <BusinessDashboard/>
        </AuthProvider>
      </ThemeModeProvider>
    </MemoryRouter>,
  )
})
for (let i = 0; i < 20 && !pageHost.querySelector('[data-chart-key="afe-actual"] svg'); i++) await settle(50)
check('the Operations dashboard renders its charts', Boolean(pageHost.querySelector('[data-chart-key="afe-actual"] svg')))

const chartOf = key => {
  const element = pageHost.querySelector(`[data-chart-key="${key}"] .echarts-for-react`)
  return element ? echarts.getInstanceByDom(element) : null
}
// Every drawn bar of a chart with the well it was drawn for and its centre.
const barsOf = chart => {
  const bars = []
  for (const element of chart.getZr().storage.getDisplayList()) {
    const info = getECData(element)
    if (info?.dataIndex == null || info.seriesIndex == null || info.dataType === 'node') continue
    const rect = element.getBoundingRect().clone()
    if (element.transform) rect.applyTransform(element.transform)
    if (rect.width < 1 || rect.height < 1) continue
    const item = chart.getOption().series[info.seriesIndex]?.data?.[info.dataIndex]
    bars.push({ seriesIndex: info.seriesIndex, dataIndex: info.dataIndex, x: rect.x + rect.width / 2, y: rect.y + rect.height / 2, wellRow: item?.chartRowId, label: item?.name })
  }
  return bars
}
// A real press: the pointer events the browser sends, on the chart's own layer.
const press = async (chart, x, y) => {
  const layer = chart.getZr().painter.getViewportRoot()
  for (const type of ['mousemove', 'mousedown', 'mouseup', 'click']) {
    const event = new w.MouseEvent(type, { bubbles: true, cancelable: true, clientX: x, clientY: y, button: 0 })
    for (const key of ['offsetX', 'offsetY', 'zrX', 'zrY']) {
      Object.defineProperty(event, key, { value: key.endsWith('X') ? x : y, configurable: true })
    }
    await act(async () => { layer.dispatchEvent(event) })
  }
  await settle(20)
}
const closePanel = async () => {
  const close = [...w.document.querySelectorAll('button')].find(button => /^close$/i.test(button.textContent.trim()) || button.getAttribute('aria-label') === 'Close')
  if (close) await act(async () => { close.click() })
  await settle(20)
}

for (const [key, title] of [['afe-actual', 'AFE against actual cost'], ['planned-days', 'Planned days against actual time'], ['depth', 'Depth progress']]) {
  const chart = chartOf(key)
  check(`${title}: the chart instance is live`, Boolean(chart))
  if (!chart) continue
  const bars = barsOf(chart)
  const wellsDrawn = [...new Set(bars.map(bar => bar.label))].sort().join(',')
  check(`${title}: bars are drawn for A, B and C`, wellsDrawn === 'A,B,C', wellsDrawn)
  for (const code of ['A', 'B', 'C']) {
    for (const bar of bars.filter(item => item.label === code)) {
      requested.length = 0
      await press(chart, bar.x, bar.y)
      const expected = `w-${code.toLowerCase()}`
      check(
        `${title}: pressing well ${code} (series ${bar.seriesIndex}) opens well ${code}`,
        requested.length === 1 && requested[0] === expected,
        `asked for ${requested.join(',') || 'nothing'}`,
      )
      await closePanel()
    }
    // The row beside the bars (the empty track) belongs to the same well.
    const band = bars.find(item => item.label === code)
    const option = chart.getOption()
    const position = option.yAxis[0].data.findIndex(entry => (typeof entry === 'object' ? entry.value : entry) === code)
    const rowY = chart.convertToPixel({ yAxisIndex: 0 }, position)
    requested.length = 0
    const gridRect = chart.getModel().getComponent('grid').coordinateSystem.getRect()
    await press(chart, gridRect.x + gridRect.width - 4, rowY)
    const expected = `w-${code.toLowerCase()}`
    check(`${title}: pressing the empty track of well ${code}'s row opens well ${code}`,
      band && requested.length === 1 && requested[0] === expected, `asked for ${requested.join(',') || 'nothing'}`)
    await closePanel()
  }
}
// A press outside every row (the legend margin) opens nothing.
const costChart = chartOf('afe-actual')
if (costChart) {
  requested.length = 0
  await press(costChart, costChart.getWidth() / 2, 3)
  check('pressing the legend margin opens no well', requested.length === 0, requested.join(','))
}
check('categoryBandClick is exported for the host', typeof categoryBandClick === 'function')

// ---- 6. source contract ----------------------------------------------------
const dashboardSource = readFileSync(['src/pages/BusinessDashboard.tsx', 'frontend/src/pages/BusinessDashboard.tsx'].find(candidate => { try { readFileSync(candidate); return true } catch { return false } }), 'utf8')
check('the dashboard plots identity-carrying series', (dashboardSource.match(/chartData\(/g) ?? []).length >= 5)
check('the dashboard drills through by identity on all three well charts', dashboardSource.includes('chartDrillHandler')
  && !/onEvents=\{\{ click: \(params/.test(dashboardSource)
  && (dashboardSource.match(/onEvents=\{\{ click: drillTo/g) ?? []).length === 3)
// The array given to the resolver is the array the chart was plotted from.
check('each resolver receives the plotted array, not the source order',
  /chartDrillHandler<DashboardWellRow>\(costRows,/.test(dashboardSource)
  && /chartDrillHandler<DashboardWellRow>\(daysRows,/.test(dashboardSource)
  && /chartDrillHandler<DashboardWellRow>\(depthRows,/.test(dashboardSource)
  && !/chartDrillHandler<DashboardWellRow>\((chartWells|daysWells),/.test(dashboardSource))

let failed = 0
for (const r of results) { if (!r.pass) failed++; console.log(`${r.pass ? 'PASS' : 'FAIL'}  ${r.label}${r.detail ? `  [${r.detail}]` : ''}`) }
console.log(failed === 0 ? `\nALL ${results.length} CHART DRILL CHECKS PASSED` : `\n${failed} of ${results.length} CHECKS FAILED`)
process.exit(failed ? 1 : 0)
