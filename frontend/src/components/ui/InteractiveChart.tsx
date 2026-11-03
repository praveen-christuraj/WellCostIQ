import { useMemo } from 'react'
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
 * Shared ECharts host for every interactive application visual.
 *
 * The application shell uses CSS zoom for its desktop density. ZRender's canvas
 * event normalisation reads pointer distances in rendered pixels while the
 * canvas scene remains in unzoomed layout pixels, which offsets hit-testing as
 * the pointer moves away from the chart origin. The SVG renderer maps viewport
 * coordinates back through the element transform, so the hovered item and the
 * tooltip data stay under the cursor at every supported app zoom.
 *
 * Tooltip movement is deliberately immediate. A moving tooltip must never lag
 * one category behind the pointer and imply that adjacent data is selected.
 */
export function InteractiveChart({ option, opts, ...props }: EChartsReactProps) {
  const preciseOption = useMemo(() => {
    const tooltip = option?.tooltip
    if (!tooltip || Array.isArray(tooltip)) return option
    return {
      ...option,
      tooltip: {
        ...tooltip,
        confine: tooltip.confine ?? true,
        transitionDuration: 0,
      },
    }
  }, [option])

  return <ReactEChartsCore
    {...props}
    echarts={echarts}
    option={preciseOption}
    opts={{ ...opts, renderer: 'svg' }}
    data-chart-renderer="svg"
  />
}
