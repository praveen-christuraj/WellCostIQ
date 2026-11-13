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

export function InteractiveChart({ option, opts, style, ...props }: EChartsReactProps) {
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
        style={{ width: '100%', height: '100%', ...style }}
        data-chart-renderer="svg"
      />
    </div>
  </div>
}
