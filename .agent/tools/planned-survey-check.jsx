// Non-pytest UI smoke: the reviewed file stages first, then the version-specific
// save refreshes the overlay. The expanded charts work on local display state.
import assert from 'node:assert/strict'
import { JSDOM } from 'jsdom'

const { window } = new JSDOM('<div id="root"></div>', { url: 'http://localhost/operations/plans', pretendToBeVisual: true })
for (const key of Object.getOwnPropertyNames(window)) {
  if (key in globalThis && !['Event', 'FormData', 'File', 'Blob'].includes(key)) continue
  try { Object.defineProperty(globalThis, key, { value: window[key], configurable: true, writable: true }) } catch { /* platform global */ }
}
globalThis.IS_REACT_ACT_ENVIRONMENT = true
window.matchMedia = () => ({ matches: false, addEventListener() {}, removeEventListener() {} })
window.HTMLCanvasElement.prototype.getContext = () => ({ measureText: text => ({ width: String(text).length * 7 }) })
Object.defineProperties(window.HTMLElement.prototype, {
  clientWidth: { configurable: true, get: () => 620 }, clientHeight: { configurable: true, get: () => 400 },
})
window.HTMLElement.prototype.getBoundingClientRect = () => new window.DOMRect(0, 0, 620, 400)

const { createElement, act } = await import('react')
const { createRoot } = await import('react-dom/client')
const { RouterProvider, createMemoryRouter } = await import('react-router-dom')
const { AuthProvider } = await import('../../frontend/src/context/AuthContext')
const { PlannedSurveyPanel } = await import('../../frontend/src/components/operations/PlannedSurveyPanel')
const { InteractiveChart } = await import('../../frontend/src/components/ui/InteractiveChart')
const { ChartPanel } = await import('../../frontend/src/components/ui/ChartPanel')
const { getRegisteredChartOption } = await import('../../frontend/src/lib/chartExport')
const { getInstanceByDom } = await import('echarts/core')

const plan = { id: 'v2', label: 'Design B', well_code: 'WELL-1', scope: 'drilling', version_no: 2, status: 'draft', is_deleted: false }
const path = '/api/v1/operations/plans/v2'
const station = (md, e, tvd) => ({ md_m: md, inc_deg: md ? 15 : 0, azi_deg: 90, vsec_m: e, ns_m: 0, ew_m: e,
  tvd_m: tvd, is_anchor: md === 0, interval_valid: md > 0 })
let saved = { stations: [], shared_reference: false, updated_at: '2026-11-20T12:00:00Z' }
let writeCount = 0
let previewCount = 0
const row = md => ({ md_m: md, inc_deg: md === '0' ? '0' : '20', azi_deg: '90', tvd_m: null, ns_m: null, ew_m: null,
  vsec_m: null, dls_deg_per_30m: null, source: 'CSV', tool: '', survey_at: null })
globalThis.fetch = async (url, request) => {
  if (url === '/api/v1/auth/refresh') return Response.json({ access_token: 'test' })
  if (url === '/api/v1/auth/me') return Response.json({ is_owner: false, permission_keys: ['ops-plan:read', 'ops-plan:update', 'ops-plan:import', 'ops-report:read'] })
  if (url.startsWith(`${path}/trajectory`)) return Response.json({
    vertical_section_azimuth_deg: 90, actual_visible: true, comparable: saved.shared_reference,
    comparison_basis: 'Reference confirmed', curve: [station(0, 0, 0), station(100, 12, 99)], survey_stations: [],
    planned_trajectory: { plan_version_id: 'v2', version_no: 2, status: 'draft', label: 'Design B', shared_reference: saved.shared_reference,
      anchor_basis: 'MD zero at surface', sources: saved.stations.length ? ['design.csv'] : [],
      curve: saved.stations.length ? [station(0, 0, 0), station(150, 30, 144)] : [] },
  })
  if (url === `${path}/surveys/preview`) {
    previewCount += 1
    return Response.json({ format: 'csv', file_name: 'design.csv', unit: 'm', detected_sheet: 'CSV', station_count: 2, sheets: ['CSV'], warnings: [],
      stations: [{ ...row('0'), station_no: 0 }, { ...row('150'), station_no: 0 }] })
  }
  if (url === `${path}/surveys`) {
    if (request.method === 'PUT') {
      writeCount += 1
      const input = JSON.parse(request.body)
      assert.equal(input.expected_updated_at, saved.updated_at)
      assert.equal(input.stations.length, 2)
      assert.ok(input.stations.every(station => station.source_file === 'design.csv' && !('station_no' in station)))
      saved = { stations: input.stations, shared_reference: input.shared_reference, updated_at: '2026-11-20T12:05:00Z' }
    }
    return Response.json(saved)
  }
  throw new Error(`Unexpected request: ${url}`)
}

let drill = ''
const chartOption = { animation: false, xAxis: { type: 'value', name: 'Time (days)', min: 0, max: 4 },
  yAxis: { type: 'value', name: 'MD (m)', inverse: true },
  series: [{ type: 'scatter', name: 'Reports', data: [{ value: [2, 100], chartRowId: 'report-1' }] }] }
const router = createMemoryRouter([{ path: '/', element: <AuthProvider>
  <ChartPanel title="Time versus depth" figureKey="test-time-depth">
    <InteractiveChart option={chartOption} onEvents={{ click: event => { drill = event.chartRowId } }} />
  </ChartPanel>
  <PlannedSurveyPanel plan={plan} />
</AuthProvider> }])
const root = createRoot(window.document.getElementById('root'))
const top = () => [...document.querySelectorAll('[role=dialog]')].at(-1)
const click = async (label, within = document) => {
  const button = [...within.querySelectorAll('button')].find(node => !node.disabled && (node.getAttribute('aria-label') ?? node.textContent.trim()) === label)
  assert.ok(button, `Enabled button: ${label}`)
  await act(async () => button.click())
}
const type = async (label, value) => {
  const input = [...top().querySelectorAll('input')].find(node => node.labels?.[0]?.textContent?.includes(label))
  assert.ok(input, `Input: ${label}`)
  await act(async () => {
    Object.getOwnPropertyDescriptor(window.HTMLInputElement.prototype, 'value').set.call(input, value)
    input.dispatchEvent(new window.Event('input', { bubbles: true }))
  })
}
await act(async () => root.render(createElement(RouterProvider, { router })))
await click('Edit / import survey')
await click('Import / extract survey', top())
const file = top().querySelector('input[type=file]')
Object.defineProperty(file, 'files', { value: [new File(['md_m,inc_deg,azi_deg\n0,0,90'], 'design.csv', { type: 'text/csv' })] })
await act(async () => file.dispatchEvent(new window.Event('change', { bubbles: true })))
assert.equal(previewCount, 1)
assert.equal(writeCount, 0)
await click('Apply to draft', top())
assert.equal(writeCount, 0)
const sharedRef = [...top().querySelectorAll('input[type=checkbox]')].find(node => node.labels?.[0].textContent.includes('I confirm'))
assert.ok(sharedRef)
await act(async () => sharedRef.click())
await click('Save planned survey', top())
assert.equal(writeCount, 1)
assert.ok(document.body.textContent.includes('Planned: Design B · v2 (draft)'))
await click('Expand Trajectory — plan view and vertical section')
await type('Inspect exact MD', '75')
assert.ok(top().textContent.includes('Actual − Planned: TVD'))
assert.ok(top().textContent.includes('(interpolated)'))
await type('Inspect exact MD', '125')
assert.ok(!top().textContent.includes('Actual − Planned:'))
await click('Close', top())

await click('Expand Time versus depth')
await type('X · Time (days) from', '1')
await type('Y · MD (m) to', '150')
const inspect = top()
const plot = getInstanceByDom(inspect.querySelector('[data-chart-renderer]'))
assert.ok(plot, 'The expanded ECharts plot is mounted')
assert.equal(plot.getOption().xAxis[0].min, 1)
assert.equal(plot.getOption().yAxis[0].max, 150)
assert.equal(plot.getOption().yAxis[0].inverse, true)
assert.equal(getRegisteredChartOption(inspect.querySelector('[data-chart-precision]')), undefined)
assert.equal(getRegisteredChartOption(document.querySelector('[data-chart-key=test-time-depth] [data-chart-precision]')).xAxis.min, 0)
await act(async () => inspect.querySelector('input[type=checkbox]').click())
assert.equal(plot.getOption().series[0].label.show, true)
const [x, y] = plot.convertToPixel({ xAxisIndex: 0, yAxisIndex: 0 }, [2, 100])
await act(async () => {
  for (const kind of ['mousedown', 'mouseup', 'click']) {
    plot.getZr().handler.dispatch(kind, { zrX: x, zrY: y, which: 1 })
  }
})
assert.equal(drill, 'report-1')

await act(async () => root.unmount())
window.close()
console.log('Planned survey: preview vs save, provenance, same-MD interpolation, no extrapolation, expanded axes/labels and record drill-through passed.')
process.exit(0)
