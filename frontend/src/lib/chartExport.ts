/**
 * Chart capture and high-DPI print rendering for PDF export.
 *
 * Two paths work together:
 *  1. **Option-based crisp print render** (preferred): `InteractiveChart`
 *     registers its live ECharts option against its host DOM element. At export
 *     time (or offscreen for bundled reports), `renderChartOptionSnapshot`
 *     clones the option, enforces paper-white print colours (so dark mode never
 *     produces pale text on white paper), adds readable non-overlapping data
 *     labels (since PDFs have no hover tooltips), renders cleanly offscreen at
 *     exact print dimensions (unaffected by `#root { zoom: 0.875 }`) using
 *     ECharts' SVG renderer, and rasterises to high-DPI PNG.
 *  2. **Live SVG fallback**: If a figure holds a custom SVG without a registered
 *     option, `snapshotChart` clones the SVG, normalises dark-mode light inks to
 *     high-contrast print ink on a white plate, and rasterises it.
 *
 * Failure is never fatal. If rasterisation is unavailable the caller receives
 * `null` and the PDF builder prints a named gap followed by the underlying data
 * table.
 */

import * as echarts from 'echarts/core'
import { BarChart, LineChart, PieChart, ScatterChart } from 'echarts/charts'
import { AxisPointerComponent, GraphicComponent, GridComponent, LegendComponent, TooltipComponent } from 'echarts/components'
import { SVGRenderer } from 'echarts/renderers'
import type { EChartsOption } from 'echarts'

echarts.use([
  BarChart, LineChart, PieChart, ScatterChart,
  AxisPointerComponent, GraphicComponent, GridComponent, LegendComponent, TooltipComponent,
  SVGRenderer,
])

export type ChartSnapshot = {
  /** PNG data URL usable by jsPDF `addImage`. */
  dataUrl: string
  /** Rendered size in CSS pixels, used to keep the aspect ratio right. */
  width: number
  height: number
  /** Chart title, used as the figure caption. */
  title?: string
  /** Shown beside the figure when the numbers behind it are exported too. */
  caption?: string
}

/** Resolution multiplier: 2.5× keeps axis text & data labels razor sharp on A4. */
const SCALE = 2.5

const PRINT_INK = '#16283F'
const PRINT_MUTED = '#4A5C6B'
const PRINT_LINE = '#8A9BA8'
const PRINT_SPLIT = '#DCE3E8'
const PRINT_FONT = 'Inter, "Segoe UI", Roboto, Helvetica, Arial, sans-serif'

/** Registry connecting each mounted `InteractiveChart` host to its live option. */
const optionRegistry = new WeakMap<Element, EChartsOption>()

export function registerChartOption(host: Element | null, option: EChartsOption | null | undefined): void {
  if (!host) return
  if (option) optionRegistry.set(host, option)
  else optionRegistry.delete(host)
}

export function getRegisteredChartOption(host: Element | null): EChartsOption | undefined {
  return host ? optionRegistry.get(host) : undefined
}

/** Compact, readable formatting for printed chart data labels. */
export function formatPrintMetric(raw: unknown): string {
  const num = typeof raw === 'number' ? raw : Number(raw)
  if (!Number.isFinite(num) || Math.abs(num) < 1e-9) return ''
  const abs = Math.abs(num)
  const sign = num < 0 ? '−' : ''
  if (abs >= 1_000_000_000) return `${sign}${(abs / 1_000_000_000).toFixed(2)}B`
  if (abs >= 1_000_000) return `${sign}${(abs / 1_000_000).toFixed(2)}M`
  if (abs >= 10_000) return `${sign}${(abs / 1_000).toFixed(1)}k`
  if (abs >= 1_000) return `${sign}${Math.round(abs).toLocaleString('en-US')}`
  if (Number.isInteger(abs)) return `${sign}${abs}`
  return `${sign}${abs.toFixed(1)}`
}

function numericValue(datum: unknown): number | null {
  if (typeof datum === 'number') return Number.isFinite(datum) ? datum : null
  if (Array.isArray(datum)) {
    const candidate = datum.length >= 2 ? datum[1] : datum[0]
    const n = Number(candidate)
    return Number.isFinite(n) ? n : null
  }
  if (datum && typeof datum === 'object' && 'value' in datum) {
    const val = (datum as { value?: unknown }).value
    if (Array.isArray(val)) return numericValue(val)
    const n = Number(val)
    return Number.isFinite(n) ? n : null
  }
  return null
}

function cloneOptionForPrint(option: EChartsOption): Record<string, unknown> {
  // Strip functions carefully while preserving data/styling structures, then
  // re-attach clean print formatters where needed.
  const copyValue = (val: unknown, depth = 0): unknown => {
    if (depth > 10 || val === null || val === undefined) return val
    if (typeof val === 'function') return val
    if (Array.isArray(val)) return val.map(item => copyValue(item, depth + 1))
    if (typeof val === 'object') {
      const out: Record<string, unknown> = {}
      for (const [k, v] of Object.entries(val as Record<string, unknown>)) {
        out[k] = copyValue(v, depth + 1)
      }
      return out
    }
    return val
  }
  return copyValue(option) as Record<string, unknown>
}

function normaliseAxisForPrint(axis: unknown, isValueAxis: boolean): unknown {
  if (Array.isArray(axis)) return axis.map(item => normaliseAxisForPrint(item, isValueAxis))
  if (!axis || typeof axis !== 'object') return axis
  const ax = { ...(axis as Record<string, unknown>) }
  const existingLabel = (ax.axisLabel && typeof ax.axisLabel === 'object') ? ax.axisLabel as Record<string, unknown> : {}
  const existingLine = (ax.axisLine && typeof ax.axisLine === 'object') ? ax.axisLine as Record<string, unknown> : {}
  const existingSplit = (ax.splitLine && typeof ax.splitLine === 'object') ? ax.splitLine as Record<string, unknown> : {}
  ax.axisLabel = {
    ...existingLabel,
    color: PRINT_INK,
    fontSize: Math.max(10, Number(existingLabel.fontSize ?? 10)),
    fontFamily: PRINT_FONT,
  }
  ax.axisLine = {
    ...existingLine,
    lineStyle: {
      ...((existingLine.lineStyle as Record<string, unknown> | undefined) ?? {}),
      color: PRINT_LINE,
    },
  }
  if (ax.nameTextStyle && typeof ax.nameTextStyle === 'object') {
    ax.nameTextStyle = { ...(ax.nameTextStyle as Record<string, unknown>), color: PRINT_MUTED, fontSize: 10 }
  } else if (ax.name) {
    ax.nameTextStyle = { color: PRINT_MUTED, fontSize: 10 }
  }
  if (isValueAxis || ax.type === 'value') {
    ax.splitLine = {
      ...existingSplit,
      lineStyle: {
        ...((existingSplit.lineStyle as Record<string, unknown> | undefined) ?? {}),
        color: PRINT_SPLIT,
      },
    }
  }
  return ax
}

/**
 * Transform any interactive ECharts option into a clean, paper-white print
 * option with formatted, non-overlapping data labels.
 */
export function preparePrintChartOption(
  option: EChartsOption,
  opts: { includeDataLabels?: boolean } = {},
): EChartsOption {
  const includeLabels = opts.includeDataLabels !== false
  const cloned = cloneOptionForPrint(option)

  cloned.animation = false
  cloned.backgroundColor = '#FFFFFF'
  cloned.tooltip = { show: false }
  cloned.textStyle = { fontFamily: PRINT_FONT, color: PRINT_INK }

  // Legend: force high-contrast ink and keep it clear of the plot area.
  if (cloned.legend) {
    const fixLegend = (leg: Record<string, unknown>) => ({
      ...leg,
      textStyle: {
        ...((leg.textStyle as Record<string, unknown> | undefined) ?? {}),
        color: PRINT_INK,
        fontSize: 10.5,
        fontFamily: PRINT_FONT,
      },
    })
    cloned.legend = Array.isArray(cloned.legend)
      ? (cloned.legend as Record<string, unknown>[]).map(fixLegend)
      : fixLegend(cloned.legend as Record<string, unknown>)
  }

  // Detect horizontal bar orientation (category yAxis, value xAxis).
  const firstX = Array.isArray(cloned.xAxis) ? cloned.xAxis[0] : cloned.xAxis
  const firstY = Array.isArray(cloned.yAxis) ? cloned.yAxis[0] : cloned.yAxis
  const isHorizontal = (firstY as Record<string, unknown> | undefined)?.type === 'category'
    && (firstX as Record<string, unknown> | undefined)?.type !== 'category'

  if (cloned.xAxis) cloned.xAxis = normaliseAxisForPrint(cloned.xAxis, !isHorizontal)
  if (cloned.yAxis) cloned.yAxis = normaliseAxisForPrint(cloned.yAxis, isHorizontal)

  // Add breathing room in the grid so right/top data labels are never clipped.
  if (cloned.grid && !Array.isArray(cloned.grid) && typeof cloned.grid === 'object') {
    const grid = { ...(cloned.grid as Record<string, unknown>) }
    grid.containLabel = true
    grid.top = typeof grid.top === 'number' ? Math.max(grid.top, 38) : (grid.top ?? 38)
    grid.right = typeof grid.right === 'number' ? Math.max(grid.right, isHorizontal ? 54 : 28) : (grid.right ?? 28)
    grid.bottom = typeof grid.bottom === 'number' ? Math.max(grid.bottom, 14) : (grid.bottom ?? 14)
    grid.left = typeof grid.left === 'number' ? Math.max(grid.left, 12) : (grid.left ?? 12)
    cloned.grid = grid
  }

  // Enrich series with legible, overlap-safe print data labels.
  if (includeLabels && Array.isArray(cloned.series)) {
    const seriesList = cloned.series as Record<string, unknown>[]
    // Track top series per stack so stacked bar charts display totals cleanly.
    const stackLastIndex = new Map<string, number>()
    const stackTotals = new Map<string, number[]>()
    seriesList.forEach((s, idx) => {
      if (s.type === 'bar' && typeof s.stack === 'string' && s.stack) {
        stackLastIndex.set(s.stack, idx)
        const arr = stackTotals.get(s.stack) ?? []
        const data = Array.isArray(s.data) ? s.data : []
        data.forEach((d, i) => {
          const val = numericValue(d) ?? 0
          arr[i] = (arr[i] ?? 0) + val
        })
        stackTotals.set(s.stack, arr)
      }
    })

    cloned.series = seriesList.map((rawSeries, seriesIdx) => {
      const s = { ...rawSeries }
      const type = String(s.type ?? '')
      const data = Array.isArray(s.data) ? s.data : []
      const count = data.length
      const existingLabel = (s.label && typeof s.label === 'object') ? s.label as Record<string, unknown> : {}
      const labelExplicitlyOff = existingLabel.show === false && String(s.name ?? '').toLowerCase().includes('band')
      if (labelExplicitlyOff) return s

      if (type === 'pie') {
        s.label = {
          ...existingLabel,
          show: true,
          color: PRINT_INK,
          fontSize: 10,
          fontWeight: 600,
          fontFamily: PRINT_FONT,
          formatter: (params: { name?: string; value?: unknown; percent?: number }) => {
            const pct = typeof params.percent === 'number' ? `${params.percent.toFixed(1)}%` : ''
            const val = formatPrintMetric(params.value)
            const shortName = String(params.name ?? '').slice(0, 22)
            return pct ? `${shortName}\n${val} (${pct})` : `${shortName}: ${val}`
          },
        }
        s.labelLine = { show: true, length: 10, length2: 8, lineStyle: { color: PRINT_LINE } }
        s.labelLayout = { hideOverlap: true }
        return s
      }

      if (type === 'bar') {
        const stackKey = typeof s.stack === 'string' ? s.stack : ''
        // Skip negative/overlay barGap='-100%' secondary overlays (like NPT overlay) from double-labelling.
        if (s.barGap === '-100%') {
          s.label = { ...existingLabel, show: false }
          return s
        }
        if (stackKey) {
          const isTopOfStack = stackLastIndex.get(stackKey) === seriesIdx
          if (isTopOfStack && count <= 28) {
            const totals = stackTotals.get(stackKey) ?? []
            const stride = count > 16 ? 2 : 1
            s.label = {
              ...existingLabel,
              show: true,
              position: isHorizontal ? 'right' : 'top',
              distance: 4,
              color: PRINT_INK,
              fontSize: count > 14 ? 8.5 : 9.5,
              fontWeight: 600,
              fontFamily: PRINT_FONT,
              formatter: (params: { dataIndex?: number }) => {
                const idx = params.dataIndex ?? 0
                if (idx % stride !== 0 && idx !== count - 1) return ''
                return formatPrintMetric(totals[idx] ?? 0)
              },
            }
            s.labelLayout = { hideOverlap: true }
          } else {
            s.label = { ...existingLabel, show: false }
          }
          return s
        }
        if (count <= 26) {
          const stride = count > 16 ? 2 : 1
          s.label = {
            ...existingLabel,
            show: true,
            position: isHorizontal ? 'right' : 'top',
            distance: 4,
            color: PRINT_INK,
            fontSize: count > 12 ? 8.5 : 9.5,
            fontWeight: 600,
            fontFamily: PRINT_FONT,
            formatter: (params: { dataIndex?: number; value?: unknown; data?: unknown }) => {
              const idx = params.dataIndex ?? 0
              if (idx % stride !== 0 && idx !== count - 1) return ''
              const val = numericValue(params.value ?? params.data)
              return val !== null && val !== 0 ? formatPrintMetric(val) : ''
            },
          }
          s.labelLayout = { hideOverlap: true }
        }
        return s
      }

      if (type === 'line') {
        // Don't clutter translucent range bands (forecast low/high area fills).
        const nameLower = String(s.name ?? '').toLowerCase()
        if (nameLower.includes('range') || nameLower.includes('base') || s.silent === true) {
          return s
        }
        // Identify key indices: first non-null, last non-null, and peak.
        let firstIdx = -1
        let lastIdx = -1
        let peakIdx = -1
        let peakVal = -Infinity
        data.forEach((d, idx) => {
          const v = numericValue(d)
          if (v === null) return
          if (firstIdx < 0) firstIdx = idx
          lastIdx = idx
          if (v > peakVal) { peakVal = v; peakIdx = idx }
        })
        const stride = count > 12 ? Math.max(2, Math.ceil(count / 5)) : Math.max(1, Math.ceil(count / 6))
        s.showSymbol = true
        s.symbolSize = Math.max(Number(s.symbolSize ?? 0), 4)
        s.label = {
          ...existingLabel,
          show: true,
          position: 'top',
          distance: 4,
          color: PRINT_INK,
          fontSize: 9,
          fontWeight: 600,
          fontFamily: PRINT_FONT,
          formatter: (params: { dataIndex?: number; value?: unknown; data?: unknown }) => {
            const idx = params.dataIndex ?? 0
            const showThis = idx === lastIdx || idx === peakIdx || (count <= 8 && idx === firstIdx) || (idx % stride === 0)
            if (!showThis) return ''
            const v = numericValue(params.value ?? params.data)
            return v !== null ? formatPrintMetric(v) : ''
          },
        }
        s.labelLayout = { hideOverlap: true }
        return s
      }

      if (type === 'scatter') {
        if (count <= 20) {
          s.label = {
            ...existingLabel,
            show: true,
            position: isHorizontal ? 'right' : 'top',
            distance: 5,
            color: PRINT_MUTED,
            fontSize: 8.5,
            fontWeight: 600,
            fontFamily: PRINT_FONT,
            formatter: (params: { value?: unknown; data?: unknown }) => {
              const v = numericValue(params.value ?? params.data)
              return v !== null && v !== 0 ? formatPrintMetric(v) : ''
            },
          }
          s.labelLayout = { hideOverlap: true }
        }
        return s
      }

      return s
    })
  }

  return cloned as EChartsOption
}

function resolveFontStack(element: Element): string {
  const host = element.ownerDocument?.defaultView
  if (!host) return PRINT_FONT
  const root = element.ownerDocument.getElementById('root') ?? element.ownerDocument.body
  const style = host.getComputedStyle(root)
  return style.fontFamily || PRINT_FONT
}

/** Detect very light SVG text inks (from dark theme) so they become legible on paper white. */
function isPaleInk(color: string | null): boolean {
  if (!color) return false
  const c = color.trim().toLowerCase()
  const hexMatch = /^#([0-9a-f]{6})$/.exec(c)
  if (hexMatch) {
    const r = parseInt(hexMatch[1].slice(0, 2), 16)
    const g = parseInt(hexMatch[1].slice(2, 4), 16)
    const b = parseInt(hexMatch[1].slice(4, 6), 16)
    return (0.299 * r + 0.587 * g + 0.114 * b) > 175
  }
  const rgbMatch = /^rgba?\(\s*(\d+)\s*,\s*(\d+)\s*,\s*(\d+)/.exec(c)
  if (rgbMatch) {
    const r = Number(rgbMatch[1]), g = Number(rgbMatch[2]), b = Number(rgbMatch[3])
    return (0.299 * r + 0.587 * g + 0.114 * b) > 175
  }
  return c === 'white' || c === '#fff'
}

/**
 * Serialise a chart's `<svg>` with paper-white plate and high-contrast ink so
 * dark-theme exports remain crisp and legible on paper.
 */
export function chartSvgMarkup(svg: SVGSVGElement, options: { background?: string; fontFamily?: string } = {}): string {
  const clone = svg.cloneNode(true) as SVGSVGElement
  const attrW = Number(svg.getAttribute('width'))
  const attrH = Number(svg.getAttribute('height'))
  const rect = svg.getBoundingClientRect()
  const width = Math.max(1, Math.round(attrW || rect.width || 640))
  const height = Math.max(1, Math.round(attrH || rect.height || 320))
  clone.setAttribute('xmlns', 'http://www.w3.org/2000/svg')
  clone.setAttribute('width', String(width))
  clone.setAttribute('height', String(height))
  clone.setAttribute('viewBox', clone.getAttribute('viewBox') ?? `0 0 ${width} ${height}`)
  clone.style.fontFamily = options.fontFamily ?? resolveFontStack(svg)
  clone.style.background = options.background ?? '#FFFFFF'

  // Remap dark-mode pale text/tspan inks to dark print ink on paper white.
  clone.querySelectorAll('text, tspan').forEach(node => {
    const fill = node.getAttribute('fill')
    if (isPaleInk(fill)) node.setAttribute('fill', PRINT_INK)
  })

  const plate = svg.ownerDocument.createElementNS('http://www.w3.org/2000/svg', 'rect')
  plate.setAttribute('x', '0')
  plate.setAttribute('y', '0')
  plate.setAttribute('width', '100%')
  plate.setAttribute('height', '100%')
  plate.setAttribute('fill', options.background ?? '#FFFFFF')
  clone.insertBefore(plate, clone.firstChild)
  return new XMLSerializer().serializeToString(clone)
}

function dataUrl(markup: string): string {
  return `data:image/svg+xml;charset=utf-8,${encodeURIComponent(markup)}`
}

async function rasterise(svgMarkup: string, width: number, height: number): Promise<string> {
  const image = new Image()
  image.crossOrigin = 'anonymous'
  await new Promise<void>((resolve, reject) => {
    image.onload = () => resolve()
    image.onerror = () => reject(new Error('The chart image could not be rendered'))
    image.src = dataUrl(svgMarkup)
  })
  const canvas = document.createElement('canvas')
  canvas.width = Math.max(1, Math.round(width * SCALE))
  canvas.height = Math.max(1, Math.round(height * SCALE))
  const context = canvas.getContext('2d')
  if (!context) throw new Error('The chart canvas is not available')
  context.fillStyle = '#FFFFFF'
  context.fillRect(0, 0, canvas.width, canvas.height)
  context.drawImage(image, 0, 0, canvas.width, canvas.height)
  return canvas.toDataURL('image/png')
}

/**
 * Render any ECharts option purely offscreen to a crisp, paper-white PNG with
 * formatted data labels — usable for both live-page exports and offscreen
 * consolidated report bundles.
 */
export async function renderChartOptionSnapshot(
  option: EChartsOption,
  opts: {
    width?: number
    height?: number
    title?: string
    caption?: string
    includeDataLabels?: boolean
  } = {},
): Promise<ChartSnapshot | null> {
  const width = Math.max(320, Math.round(opts.width ?? 820))
  const height = Math.max(200, Math.round(opts.height ?? 360))
  const printOption = preparePrintChartOption(option, { includeDataLabels: opts.includeDataLabels })
  let svgMarkup = ''
  const chart = echarts.init(null as unknown as HTMLElement, null, {
    renderer: 'svg',
    ssr: true,
    width,
    height,
  })
  try {
    chart.setOption(printOption, true)
    svgMarkup = chart.renderToSVGString()
  } finally {
    chart.dispose()
  }
  if (!svgMarkup) return null
  if (!svgMarkup.includes('xmlns="http://www.w3.org/2000/svg"')) {
    svgMarkup = svgMarkup.replace('<svg', '<svg xmlns="http://www.w3.org/2000/svg"')
  }
  const pngUrl = await rasterise(svgMarkup, width, height)
  return {
    dataUrl: pngUrl,
    width,
    height,
    title: opts.title,
    caption: opts.caption,
  }
}

/**
 * Capture one chart. Uses the registered ECharts option when available (for
 * crisp paper-white rendering with data labels, immune to CSS zoom and dark
 * theme); falls back to rasterising the live SVG directly.
 */
export async function snapshotChart(element: Element | null, caption?: string): Promise<ChartSnapshot | null> {
  if (!element) return null
  const registered = getRegisteredChartOption(element)
  if (registered) {
    try {
      const svg = element.querySelector('svg')
      const attrW = Number(svg?.getAttribute('width') ?? 0)
      const attrH = Number(svg?.getAttribute('height') ?? 0)
      const rect = (svg ?? element).getBoundingClientRect()
      const rawW = attrW || rect.width || 720
      const rawH = attrH || rect.height || 340
      // Normalise print canvas width to ~820px preserving exact aspect ratio.
      const targetW = Math.max(640, Math.min(960, Math.round(rawW * 1.15)))
      const aspect = rawW > 0 ? rawH / rawW : 0.46
      const targetH = Math.max(260, Math.min(480, Math.round(targetW * aspect)))
      const rendered = await renderChartOptionSnapshot(registered, {
        width: targetW,
        height: targetH,
        caption,
        includeDataLabels: true,
      })
      if (rendered) return rendered
    } catch {
      // Fall back cleanly to live SVG capture below.
    }
  }
  const svg = element.querySelector('svg')
  if (!svg) return null
  const attrW = Number(svg.getAttribute('width'))
  const attrH = Number(svg.getAttribute('height'))
  const rect = svg.getBoundingClientRect()
  const width = Math.max(1, Math.round(attrW || rect.width || 640))
  const height = Math.max(1, Math.round(attrH || rect.height || 320))
  const markup = chartSvgMarkup(svg as SVGSVGElement)
  const dataUrlValue = await rasterise(markup, width, height)
  return { dataUrl: dataUrlValue, width, height, caption }
}

/**
 * Capture the chart hosted by one exportable figure panel.
 */
export async function captureFigureChart(figureKey: string): Promise<ChartSnapshot | null> {
  if (typeof document === 'undefined') return null
  const panel = Array.from(document.querySelectorAll<HTMLElement>('[data-chart-figure]'))
    .find(element => (element.dataset.chartKey ?? '') === figureKey)
  if (!panel) return null
  const host = panel.querySelector('[data-chart-precision]')
  if (!host || host.querySelector('svg') === null) return null
  const snapshot = await snapshotChart(host, panel.dataset.chartCaption ?? '')
  if (!snapshot) return null
  snapshot.title = panel.dataset.chartTitle ?? ''
  return snapshot
}

/** Capture several figures, keyed, skipping the ones that are not on screen. */
export async function captureFigures(keys: string[]): Promise<Map<string, ChartSnapshot>> {
  const captures = new Map<string, ChartSnapshot>()
  for (const key of keys) {
    try {
      const snapshot = await captureFigureChart(key)
      if (snapshot) captures.set(key, snapshot)
    } catch {
      // Leave the key out: the document then names the figure as a gap.
    }
  }
  return captures
}
