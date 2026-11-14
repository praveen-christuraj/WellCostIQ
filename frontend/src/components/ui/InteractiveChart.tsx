import { useEffect, useLayoutEffect, useMemo, useRef, useState } from 'react'
import type { EChartsReactProps } from 'echarts-for-react'
import ReactEChartsCore from 'echarts-for-react/esm/core'
import * as echarts from 'echarts/core'
import { BarChart, LineChart, PieChart, ScatterChart } from 'echarts/charts'
import { AxisPointerComponent, GraphicComponent, GridComponent, LegendComponent, TooltipComponent } from 'echarts/components'
import { SVGRenderer } from 'echarts/renderers'

echarts.use([
  BarChart, LineChart, PieChart, ScatterChart,
  AxisPointerComponent, GraphicComponent, GridComponent, LegendComponent, TooltipComponent,
  SVGRenderer,
])

/**
 * The application shell renders `#root` at 87.5% CSS zoom for its desktop
 * density. CSS zoom scales rendering *and* the pointer coordinates the browser
 * reports (offsetX/offsetY, and therefore zrender's hit test) towards the
 * origin, so a pointer over a pie slice resolves to a point a few pixels
 * up-and-left of the cursor: the value appears only once the cursor drifts far
 * enough outside the slice to land back on it. The bigger the distance from the
 * chart origin, the larger the error.
 *
 * The fix is to give the chart its own 1:1 coordinate space. The host measures
 * the space it really occupies on screen (viewport pixels, which the zoom has
 * already shrunk) and renders the chart at exactly that layout size inside an
 * inversely zoomed wrapper. Layout pixels then equal viewport pixels inside the
 * chart, so hover, click, the axis pointer, brush and the tooltip all agree with
 * the cursor at any application zoom, font size or window size.
 *
 * Tooltip movement is deliberately immediate: a moving tooltip must never lag
 * one category behind the pointer and imply that adjacent data is selected.
 */
const PROBE_ID = 'wcp-chart-zoom-probe'

/** Effective CSS zoom applied by the application shell (1 when unzoomed). */
export function measureAppZoom(): number {
  if (typeof document === 'undefined') return 1
  const host = document.getElementById('root') ?? document.body
  if (!host) return 1
  let probe = document.getElementById(PROBE_ID) as HTMLDivElement | null
  if (!probe) {
    probe = document.createElement('div')
    probe.id = PROBE_ID
    probe.setAttribute('aria-hidden', 'true')
    probe.style.cssText = [
      'position:absolute', 'left:0', 'top:0', 'width:100px', 'height:100px',
      'visibility:hidden', 'pointer-events:none', 'z-index:-1',
    ].join(';')
    host.appendChild(probe)
  }
  const width = probe.getBoundingClientRect().width
  return width > 0 ? width / 100 : 1
}

/** Wrapper zoom that cancels the shell zoom, e.g. 0.875 → 1.142857… */
export function inverseZoom(scale: number): number {
  return scale > 0 && Number.isFinite(scale) ? 1 / scale : 1
}

/** Chart option defaults that keep the pointer and the tooltip in step. */
function preciseTooltip(option: EChartsReactProps['option']) {
  const tooltip = option?.tooltip
  if (!tooltip || Array.isArray(tooltip)) return option
  return {
    ...option,
    tooltip: {
      ...tooltip,
      confine: tooltip.confine ?? true,
      transitionDuration: 0,
      hideDelay: tooltip.hideDelay ?? 60,
      enterable: tooltip.enterable ?? false,
    },
    // No emphasis dimming: the hovered slice/bar must be obvious under the cursor.
    series: option.series,
  }
}

type Box = { width: number; height: number }

/**
 * ECharts reports a click on the *series item*, not the record the caller
 * plotted. This host normalises every click into the shape the application uses
 * to open a record: the identity carried by the clicked data item
 * (`chartRowId`, see `lib/chartInteraction.ts`), the category `name`, the
 * plotted `dataIndex` **within the series that was clicked**, and the series
 * index. The clicked data item itself travels along as `data`, so a resolver
 * written against the raw ECharts shape and one written against this shape read
 * the same identity — the mismatch between the two is what opened a
 * neighbouring well.
 */
export type ChartClickEvent = {
  dataIndex: number | null
  seriesIndex: number | null
  /** Category label (or the item's `name`) of the clicked point. */
  name: string
  /** Record identity carried by the plotted data item, when the caller set one. */
  chartRowId: string
  /** The clicked data item, as plotted. */
  data: unknown
  /**
   * `true` when the pointer was on the category's row or column (the label or
   * the empty band beside a short bar) rather than on a drawn bar.
   */
  band: boolean
  /** The raw ECharts payload, for chart kinds that need another field. */
  raw: unknown
}

type ChartClickHandler = (event: ChartClickEvent) => void

export function normaliseClick(raw: unknown, band = false): ChartClickEvent {
  const payload = (raw ?? {}) as {
    dataIndex?: number
    seriesIndex?: number
    name?: string
    data?: { name?: string; chartRowId?: string } | null
  }
  const data = payload.data && typeof payload.data === 'object' ? payload.data : null
  return {
    dataIndex: typeof payload.dataIndex === 'number' ? payload.dataIndex : null,
    seriesIndex: typeof payload.seriesIndex === 'number' ? payload.seriesIndex : null,
    name: data?.name ?? payload.name ?? '',
    chartRowId: typeof data?.chartRowId === 'string' ? data.chartRowId : '',
    data: payload.data ?? null,
    band,
    raw,
  }
}

type AxisOption = { type?: string; data?: unknown[] }
type SeriesOption = { data?: unknown[] }
type ChartInstance = {
  getOption: () => { xAxis?: AxisOption[]; yAxis?: AxisOption[]; series?: SeriesOption[] }
  convertFromPixel: (finder: Record<string, number>, value: number[]) => number[] | number
  containPixel: (finder: Record<string, number>, value: number[]) => boolean
  getWidth: () => number
  getHeight: () => number
  getZr: () => { on: (name: string, handler: (event: BandPointer) => void) => void }
}
type BandPointer = { offsetX: number; offsetY: number; target?: unknown }

/**
 * A bar chart is read by its row: the well's label, its bars and the empty
 * track beside a short bar all mean "this well". ECharts only reports a click
 * that lands on a drawn bar, so a thin bar (or a zero) left the row dead and a
 * near miss on a 12px bar landed on the neighbouring well's bar instead.
 *
 * This resolves a pointer position to the category whose band it lies in, and
 * returns the same payload a click on that category's own bar would produce —
 * including the identity the bar carries. Nothing is inferred from an unrelated
 * array: the data item is read from the chart's own current option.
 */
export function categoryBandClick(chart: ChartInstance, pointer: BandPointer): unknown | null {
  let option: ReturnType<ChartInstance['getOption']>
  try { option = chart.getOption() } catch { return null }
  const xAxis = option.xAxis?.[0]
  const yAxis = option.yAxis?.[0]
  const horizontal = yAxis?.type === 'category' && xAxis?.type !== 'category'
  const vertical = xAxis?.type === 'category' && yAxis?.type !== 'category'
  if (!horizontal && !vertical) return null
  const point = [pointer.offsetX, pointer.offsetY]
  let located: number[] | number
  try { located = chart.convertFromPixel({ xAxisIndex: 0, yAxisIndex: 0 }, point) } catch { return null }
  if (!Array.isArray(located)) return null
  const index = Math.round(Number(horizontal ? located[1] : located[0]))
  const categories = (horizontal ? yAxis?.data : xAxis?.data) ?? []
  if (!Number.isInteger(index) || index < 0 || index >= categories.length) return null
  // The pointer must be within the chart along the value axis too; a click in
  // the legend or the caption margin is not a click on a well.
  let inside = false
  try { inside = chart.containPixel({ gridIndex: 0 }, point) } catch { inside = false }
  if (!inside) {
    // Left of a horizontal chart (or below a vertical one) is the label gutter.
    const cross = horizontal ? pointer.offsetX : pointer.offsetY
    const limit = horizontal ? chart.getWidth() : chart.getHeight()
    const probe = horizontal ? [limit / 2, pointer.offsetY] : [pointer.offsetX, limit / 2]
    let alongBand = false
    try { alongBand = chart.containPixel({ gridIndex: 0 }, probe) } catch { alongBand = false }
    if (!alongBand || cross < 0 || cross > limit) return null
    // Only the label side counts: for a horizontal chart that is the left gutter,
    // for a vertical chart the bottom gutter.
    const gutter = horizontal ? pointer.offsetX < limit / 2 : pointer.offsetY > limit / 2
    if (!gutter) return null
  }
  const series = option.series ?? []
  for (let seriesIndex = 0; seriesIndex < series.length; seriesIndex++) {
    const item = series[seriesIndex]?.data?.[index]
    if (item && typeof item === 'object' && typeof (item as { chartRowId?: unknown }).chartRowId === 'string') {
      const category = categories[index]
      const label = typeof category === 'object' && category !== null
        ? String((category as { value?: unknown }).value ?? '')
        : String(category ?? '')
      return { dataIndex: index, seriesIndex, name: label, data: item }
    }
  }
  return null
}

export function InteractiveChart({ option, opts, style, onEvents, onChartReady, ...props }: EChartsReactProps) {
  // The handlers given to ECharts never change identity; they call whatever the
  // page passed on its *latest* render through a ref. `echarts-for-react`
  // unbinds and rebinds every listener whenever `onEvents` compares unequal,
  // and an inline `{ click: … }` literal compares unequal on every render, so
  // between the unbind and the rebind a click could be answered by nobody or
  // by the previous render's rows. A stable binding with a live ref is bound
  // once and always resolves against the rows on screen.
  const latest = useRef(onEvents)
  latest.current = onEvents
  const seriesClickSeen = useRef(false)
  const eventNames = Object.keys(onEvents ?? {}).filter(name => typeof onEvents?.[name] === 'function').sort().join('|')
  const bind = useMemo(() => {
    if (!eventNames) return undefined
    const bound: Record<string, (params: unknown) => void> = {}
    for (const name of eventNames.split('|')) {
      bound[name] = name === 'click'
        ? (params: unknown) => {
          seriesClickSeen.current = true
          ;(latest.current?.[name] as ChartClickHandler | undefined)?.(normaliseClick(params))
        }
        : (params: unknown) => (latest.current?.[name] as ((value: unknown) => void) | undefined)?.(params)
    }
    return bound
  }, [eventNames])

  // Whole-row selection for category charts that drill through (see
  // `categoryBandClick`). A press on a drawn bar is reported twice by the
  // pointer layer: once as ECharts' series click and once as this raw click, in
  // an order ECharts does not promise. The row is therefore resolved after both
  // have been delivered, and only when no series click claimed the press.
  const ready = useMemo(() => (instance: unknown) => {
    const chart = instance as ChartInstance
    try {
      chart.getZr().on('click', pointer => {
        const position = { offsetX: pointer.offsetX, offsetY: pointer.offsetY }
        queueMicrotask(() => {
          const claimed = seriesClickSeen.current
          seriesClickSeen.current = false
          const handler = latest.current?.click as ChartClickHandler | undefined
          if (claimed || typeof handler !== 'function') return
          const payload = categoryBandClick(chart, position)
          if (payload) handler(normaliseClick(payload, true))
        })
      })
    } catch { /* a chart without a pointer layer simply keeps bar-only clicks */ }
    onChartReadyRef.current?.(instance as never)
  }, [])
  const onChartReadyRef = useRef(onChartReady)
  onChartReadyRef.current = onChartReady

  const hostRef = useRef<HTMLDivElement | null>(null)
  const [box, setBox] = useState<Box | null>(null)
  const [zoom, setZoom] = useState(1)

  const preciseOption = useMemo(() => preciseTooltip(option), [option])

  // Measure the on-screen box before paint so the chart never initialises at
  // the zoomed size and then has to be corrected visibly.
  useLayoutEffect(() => {
    const host = hostRef.current
    if (!host) return
    const sync = () => {
      const rect = host.getBoundingClientRect()
      if (rect.width <= 0 || rect.height <= 0) return
      setBox(current => (
        current && Math.abs(current.width - rect.width) < 0.5 && Math.abs(current.height - rect.height) < 0.5
          ? current
          : { width: rect.width, height: rect.height }
      ))
      const scale = measureAppZoom()
      setZoom(current => (Math.abs(current - scale) < 0.001 ? current : scale))
    }
    sync()
    if (typeof ResizeObserver === 'undefined') {
      window.addEventListener('resize', sync)
      return () => window.removeEventListener('resize', sync)
    }
    const observer = new ResizeObserver(sync)
    observer.observe(host)
    return () => observer.disconnect()
  }, [])

  // Re-measure when the application zoom itself changes (density switch/fullscreen).
  useEffect(() => {
    const sync = () => setZoom(measureAppZoom())
    window.addEventListener('resize', sync)
    return () => window.removeEventListener('resize', sync)
  }, [])

  const wrapped = box !== null && Math.abs(zoom - 1) > 0.001
  return <div
    ref={hostRef}
    data-chart-precision="1:1"
    data-chart-app-zoom={zoom.toFixed(4)}
    style={{ position: 'relative', width: '100%', height: '100%', overflow: 'hidden' }}
  >
    <div
      data-chart-plot
      style={wrapped
        ? {
          width: box.width,
          height: box.height,
          zoom: inverseZoom(zoom),
          transformOrigin: '0 0',
        }
        : { width: '100%', height: '100%' }}
    >
      <ReactEChartsCore
        {...props}
        echarts={echarts}
        option={preciseOption}
        opts={{ ...opts, renderer: 'svg' }}
        onEvents={bind}
        onChartReady={ready}
        style={{ width: '100%', height: '100%', ...style }}
        data-chart-renderer="svg"
      />
    </div>
  </div>
}
