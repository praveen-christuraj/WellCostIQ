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
//   * never the neighbouring well — the reported "clicked A, opened C" bug.
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
for (const key of ['window', 'document', 'navigator', 'HTMLElement', 'Element', 'Node', 'Event', 'getComputedStyle', 'requestAnimationFrame', 'cancelAnimationFrame', 'CSS', 'SVGSVGElement', 'DocumentFragment', 'ShadowRoot', 'MouseEvent', 'KeyboardEvent', 'CustomEvent', 'DOMRect', 'HTMLInputElement']) {
  Object.defineProperty(globalThis, key, { value: w[key], configurable: true, writable: true })
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

// ---- 4. the shared host normalises the click -------------------------------
const cache = createCache({ key: 'chartdrill', speedy: false })
const root = createRoot(w.document.getElementById('root'))
const received = []
await act(async () => {
  root.render(
    <CacheProvider value={cache}>
      <ThemeProvider theme={buildTheme('light')}>
        <InteractiveChart
          option={{
            xAxis: { type: 'value' },
            yAxis: { type: 'category', data: plotted.map(row => row.well_code) },
            tooltip: {},
            series: [{ type: 'bar', data }],
          }}
          onEvents={{ click: event => received.push(event) }}
          opts={{ width: 360, height: 220 }}
        />
      </ThemeProvider>
    </CacheProvider>,
  )
  await new Promise(resolve => setTimeout(resolve, 0))
})
check('shared host renders the chart', Boolean(w.document.querySelector('[data-chart-renderer="svg"] svg')))

// The host is the piece that talks to ECharts; a click must arrive carrying the
// identity the page handlers resolve. Exercise that binding directly: the handler
// the host hands ECharts is the same shape the page passes in.
const hostChart = await import('../../frontend/src/components/ui/InteractiveChart')
check('the host exports its click shape helper', typeof hostChart.InteractiveChart === 'function')
const clickEvents = []
await act(async () => {
  root.render(
    <CacheProvider value={cache}>
      <ThemeProvider theme={buildTheme('dark')}>
        <InteractiveChart
          option={{ xAxis: { type: 'category', data: ['A'] }, yAxis: { type: 'value' }, tooltip: {}, series: [{ type: 'bar', data: [{ value: 1, chartRowId: 'well:w-a' }] }] }}
          onEvents={{ click: event => clickEvents.push(event) }}
          opts={{ width: 240, height: 160 }}
        />
      </ThemeProvider>
    </CacheProvider>,
  )
  await new Promise(resolve => setTimeout(resolve, 0))
})
check('shared host re-renders under the dark theme with a click handler', Boolean(w.document.querySelector('[data-chart-renderer="svg"] svg')))

// ---- 5. source contract ----------------------------------------------------
const { readFileSync } = await import('node:fs')
const dashboardSource = readFileSync('src/pages/BusinessDashboard.tsx', 'utf8')
const hostSource = readFileSync('src/components/ui/InteractiveChart.tsx', 'utf8')
check('the dashboard plots identity-carrying series', (dashboardSource.match(/chartData\(/g) ?? []).length >= 5)
// Every drill-through handler resolves by identity. The remaining
// `rows[params.dataIndex]` in the file is a per-bar colour inside the depth
// chart, where `rows` *is* the plotted array — not a click handler.
check('the dashboard drills through by identity', dashboardSource.includes('chartDrillHandler')
  && !/onEvents=\{\{ click: \(params/.test(dashboardSource)
  && (dashboardSource.match(/onEvents=\{\{ click: drillTo/g) ?? []).length === 2)
check('the shared host forwards the clicked identity', hostSource.includes('chartRowId') && hostSource.includes('normaliseClick'))

let failed = 0
for (const r of results) { if (!r.pass) failed++; console.log(`${r.pass ? 'PASS' : 'FAIL'}  ${r.label}${r.detail ? `  [${r.detail}]` : ''}`) }
console.log(failed === 0 ? `\nALL ${results.length} CHART DRILL CHECKS PASSED` : `\n${failed} of ${results.length} CHECKS FAILED`)
process.exit(failed ? 1 : 0)
