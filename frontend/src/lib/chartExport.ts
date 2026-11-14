/**
 * Chart capture for PDF export.
 *
 * The dashboards and the well cost analysis render every visual through the
 * shared `InteractiveChart` host, which forces the SVG renderer. Exporting "as
 * shown" therefore means capturing the *same* rendered scene, not re-drawing it:
 *
 *  1. `snapshotChart` reads the live chart's own SVG, re-renders it with the
 *     exported document's fonts and colours, and rasterises it through an
 *     `<img>` of an SVG data URL chosen to keep the browser's canvas untainted
 *     and therefore readable by `toDataURL`.
 *  2. Every SVG is self-contained: the host inlines the resolved font stack and
 *     the colours are literal paint values (ECharts writes them into the scene),
 *     so the snapshot matches the screen even though the PDF has no stylesheet.
 *
 * Failure is never fatal. If rasterisation is unavailable (an old browser, a
 * locked-down canvas) the export falls back to the chart's *data* as a table, so
 * a PDF never silently omits a visual.
 */

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

/** Resolution multiplier: a printed A4 page at 96 dpi reads 2× crisply. */
const SCALE = 2

function resolveFontStack(element: Element): string {
  const host = element.ownerDocument?.defaultView
  if (!host) return 'sans-serif'
  const root = element.ownerDocument.getElementById('root') ?? element.ownerDocument.body
  const style = host.getComputedStyle(root)
  return style.fontFamily || 'sans-serif'
}

/**
 * Serialise a chart's `<svg>` with the fonts and a white plate so a dark-theme
 * export stays legible on paper: the *series* colours are kept exactly as
 * shown, the page behind them becomes paper white.
 */
export function chartSvgMarkup(svg: SVGSVGElement, options: { background?: string; fontFamily?: string } = {}): string {
  const clone = svg.cloneNode(true) as SVGSVGElement
  const rect = svg.getBoundingClientRect()
  const width = Math.max(1, Math.round(rect.width || Number(svg.getAttribute('width')) || 640))
  const height = Math.max(1, Math.round(rect.height || Number(svg.getAttribute('height')) || 320))
  clone.setAttribute('xmlns', 'http://www.w3.org/2000/svg')
  clone.setAttribute('width', String(width))
  clone.setAttribute('height', String(height))
  clone.setAttribute('viewBox', clone.getAttribute('viewBox') ?? `0 0 ${width} ${height}`)
  // Never inherit the app's text colours: the plate is white.
  clone.style.fontFamily = options.fontFamily ?? resolveFontStack(svg)
  clone.style.background = options.background ?? '#FFFFFF'
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
  // encodeURIComponent keeps non-ASCII labels (well names, currency symbols)
  // intact; btoa would throw on them.
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
 * Capture one chart. Returns `null` when the element holds no rendered scene
 * (nothing plotted, or a chart still initialising) — the caller then exports the
 * figure's data instead of an empty box.
 */
export async function snapshotChart(element: Element | null, caption?: string): Promise<ChartSnapshot | null> {
  if (!element) return null
  const svg = element.querySelector('svg')
  if (!svg) return null
  const rect = svg.getBoundingClientRect()
  const width = Math.max(1, Math.round(rect.width || 640))
  const height = Math.max(1, Math.round(rect.height || 320))
  const markup = chartSvgMarkup(svg as SVGSVGElement)
  const dataUrlValue = await rasterise(markup, width, height)
  return { dataUrl: dataUrlValue, width, height, caption }
}

/**
 * Capture the chart hosted by one exportable figure panel.
 *
 * The panel is identified by `[data-chart-figure]` and the page passes the
 * figure's key, so a capture can never be attached to the panel above it.
 * Returns `null` when the panel is absent or holds no rendered scene.
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
