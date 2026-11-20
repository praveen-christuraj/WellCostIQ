import { useMemo, useState } from 'react'
import { Alert, Box, FormControlLabel, Checkbox, Stack, Typography } from '@mui/material'
import { InteractiveChart, type ChartClickEvent } from '../ui/InteractiveChart'
import { useColorMode } from '../../context/ThemeContext'
import { chartPalette, surface } from '../../designSystem'
import type { OpsWellPath } from '../../lib/operations'
import {
  azimuthSeries,
  effectiveWindow,
  equalPlanBounds,
  fmtAngle,
  fmtDepth,
  fmtDls,
  interpolateAt,
  isSurveyed,
  mdTicks,
  sliceCurve,
  stationAt,
  type DepthWindow,
} from '../../lib/wellPath'

/**
 * Two linked 2D projections of exactly the same stations.
 *
 * **Plan view** is looking down — not "planned well". North is up and both axes
 * carry the same range, so the drawing is read for direction. **Vertical
 * section** is the shadow of the path on a vertical plane facing the stated
 * bearing: sideways motion out of that plane disappears, and rotating the plane
 * changes the shadow, not the well.
 *
 * A station selected in either view is emphasised in both; the caller also uses
 * that depth to highlight the row in the table and the mark in the schematic.
 * Nothing here invents a segment: below the last station the line stops, and the
 * gap to the hole bottom is named in words.
 */
export function WellPlanSectionViews({
  path,
  selectedMd,
  onSelectMd,
  window,
  height = 330,
}: {
  path: OpsWellPath
  selectedMd: number | null
  onSelectMd: (md: number | null) => void
  window: DepthWindow
  height?: number
}) {
  const { mode } = useColorMode()
  const colors = chartPalette(mode)
  const s = surface(mode)
  const [showMdLabels, setShowMdLabels] = useState(true)
  const curve = path.curve
  const windowRange = effectiveWindow(curve, window)
  const points = useMemo(() => sliceCurve(curve, { from: windowRange.from, to: windowRange.to }), [curve, windowRange.from, windowRange.to])
  const selectedPoint = interpolateAt(curve, selectedMd)
  const marker = path.position
  // Measured depth can only be read off a depth-vs-depth drawing if it is
  // annotated: MD is not an axis of either projection, so the same nice MD
  // positions are interpolated onto both views.
  const mdGuides = useMemo(
    () => mdTicks(windowRange.from, windowRange.to).map((md) => ({ md, point: interpolateAt(curve, md) })).filter((row): row is { md: number; point: NonNullable<ReturnType<typeof interpolateAt>> } => row.point !== null),
    [curve, windowRange.from, windowRange.to],
  )
  const brass = mode === 'dark' ? '#F2C14E' : '#B87503'

  const axisText = colors.axis
  const base = {
    animation: false,
    textStyle: { color: axisText },
    tooltip: { trigger: 'item' as const, confine: true },
    grid: { left: 52, right: 52, top: 30, bottom: 46 },
  }

  const planBounds = useMemo(() => equalPlanBounds(points), [points])

  /** Plan: the stations as they sit on the ground, north up, equal scale. */
  const planOption = useMemo(() => ({
    ...base,
    // Equal insets on both axes so the square container yields a square plot:
    // only then does an equal north/east range read as a true 1:1 plan.
    grid: { left: 48, right: 48, top: 26, bottom: 70 },
    tooltip: {
      trigger: 'item' as const,
      confine: true,
      formatter: (p: { data?: { chartRowId?: string; value?: number[] } }) => {
        const value = p.data?.value ?? [0, 0]
        const md = Number(p.data?.chartRowId ?? NaN)
        const here = interpolateAt(curve, Number.isFinite(md) ? md : null)
        return [
          `<b>${fmtDepth(md, 1)} m MD</b>`,
          `N ${fmtDepth(value[1])} m · E ${fmtDepth(value[0])} m`,
          here ? `TVD ${fmtDepth(here.tvd_m)} m` : '',
        ].filter(Boolean).join('<br/>')
      },
    },
    xAxis: {
      type: 'value' as const,
      name: 'East (m)',
      nameLocation: 'middle' as const,
      nameGap: 28,
      min: planBounds[0],
      max: planBounds[1],
      splitLine: { lineStyle: { color: colors.grid, type: 'dashed' as const } },
      axisLine: { lineStyle: { color: colors.grid } },
      axisTick: { show: false },
    },
    yAxis: {
      type: 'value' as const,
      name: 'North (m)',
      nameGap: 16,
      min: planBounds[0],
      max: planBounds[1],
      splitLine: { lineStyle: { color: colors.grid, type: 'dashed' as const } },
      axisLine: { lineStyle: { color: colors.grid } },
      axisTick: { show: false },
    },
    series: [
      {
        name: 'Surveyed path',
        type: 'line' as const,
        color: colors.actual,
        showSymbol: false,
        lineStyle: { width: 2.2 },
        data: points.map((point) => ({
          value: [point.ew_m, point.ns_m],
          chartRowId: String(point.md_m),
        })),
      },
      {
        name: 'Stations',
        type: 'scatter' as const,
        color: colors.actual,
        symbolSize: 5,
        data: curve.map((station) => ({
          value: [station.ew_m, station.ns_m],
          chartRowId: String(station.md_m),
        })),
      },
      {
        name: 'Surface location',
        type: 'scatter' as const,
        color: colors.planned,
        symbol: 'rect',
        symbolSize: 8,
        data: [{ value: [0, 0], chartRowId: '' }],
        tooltip: { show: false },
      },
      ...(showMdLabels ? [{
        name: 'Depth labels',
        type: 'scatter' as const,
        silent: true,
        symbolSize: 1,
        data: mdGuides.map(({ md, point }) => ({
          value: [point.ew_m, point.ns_m],
          chartRowId: String(md),
        })),
        label: {
          show: true,
          position: 'top' as const,
          distance: 4,
          fontSize: 7.5,
          color: brass,
          formatter: (p: { dataIndex: number }) => `MD ${Math.round(mdGuides[p.dataIndex].md).toLocaleString()}`,
        },
        tooltip: { show: false },
        z: 4,
      }] : []),
      ...(selectedPoint ? [{
        name: 'Selected station',
        type: 'scatter' as const,
        color: colors.planned,
        symbol: 'circle',
        symbolSize: 14,
        itemStyle: { borderColor: s.paper, borderWidth: 2 },
        data: [{ value: [selectedPoint.ew_m, selectedPoint.ns_m], chartRowId: String(selectedPoint.md_m) }],
        z: 5,
      }] : []),
    ],
  }), [base, brass, colors.actual, colors.grid, colors.planned, curve, mdGuides, planBounds, points, s.paper, selectedPoint, showMdLabels])

  /** Section: the same stations projected on the plane facing the VS bearing. */
  const sectionOption = useMemo(() => {
    const vsecs = points.map((point) => point.vsec_m)
    const tvds = points.map((point) => point.tvd_m)
    const vsecLow = Math.min(0, ...vsecs)
    const vsecHigh = Math.max(0, ...vsecs)
    const tvdLow = Math.min(0, ...tvds)
    const tvdHigh = Math.max(...tvds, 1)
    const pad = Math.max((vsecHigh - vsecLow) * 0.1, 25)
    return {
      ...base,
      tooltip: {
        trigger: 'item' as const,
        confine: true,
        formatter: (p: { data?: { chartRowId?: string; value?: number[] } }) => {
          const value = p.data?.value ?? [0, 0]
          const md = Number(p.data?.chartRowId ?? NaN)
          return [
            `<b>${fmtDepth(md, 1)} m MD</b>`,
            `TVD ${fmtDepth(value[1])} m`,
            `Vertical section ${fmtDepth(value[0])} m`,
          ].join('<br/>')
        },
      },
      xAxis: {
        type: 'value' as const,
        name: 'Vertical section (m)',
        nameLocation: 'middle' as const,
        nameGap: 28,
        min: vsecLow - pad,
        max: vsecHigh + pad,
        splitLine: { lineStyle: { color: colors.grid, type: 'dashed' as const } },
        axisLine: { lineStyle: { color: colors.grid } },
        axisTick: { show: false },
      },
      yAxis: {
        type: 'value' as const,
        name: 'TVD (m)',
        nameGap: 16,
        inverse: true,
        min: tvdLow,
        max: tvdHigh * 1.02,
        splitLine: { lineStyle: { color: colors.grid, type: 'dashed' as const } },
        axisLine: { lineStyle: { color: colors.grid } },
        axisTick: { show: false },
      },
      series: [
        {
          name: 'Surveyed path',
          type: 'line' as const,
          color: colors.actual,
          showSymbol: false,
          lineStyle: { width: 2.2 },
          data: points.map((point) => ({
            value: [point.vsec_m, point.tvd_m],
            chartRowId: String(point.md_m),
          })),
          // Measured-depth guides: MD is not an axis of this projection, so
          // each tick is drawn as a horizontal rule at the interpolated TVD
          // and tagged on the right edge. A rule is an annotation, never a
          // station: it is interpolated between recorded points only.
          markLine: {
            silent: true,
            symbol: 'none',
            animation: false,
            data: mdGuides.map(({ md, point }) => ({
              yAxis: point.tvd_m,
              name: `MD ${Math.round(md).toLocaleString()} m`,
            })),
            lineStyle: { type: 'dashed' as const, width: 0.8, color: brass, opacity: 0.75 },
            label: {
              position: 'insideEndTop' as const,
              fontSize: 8,
              fontWeight: 700,
              color: brass,
              formatter: (p: { name: string }) => p.name,
            },
          },
        },
        {
          name: 'Stations',
          type: 'scatter' as const,
          color: colors.actual,
          symbolSize: 5,
          data: curve.map((station) => ({
            value: [station.vsec_m, station.tvd_m],
            chartRowId: String(station.md_m),
          })),
        },
        ...(selectedPoint ? [{
          name: 'Selected station',
          type: 'scatter' as const,
          color: colors.planned,
          symbolSize: 14,
          itemStyle: { borderColor: s.paper, borderWidth: 2 },
          data: [{ value: [selectedPoint.vsec_m, selectedPoint.tvd_m], chartRowId: String(selectedPoint.md_m) }],
          z: 5,
        }] : []),
      ],
    }
  }, [base, brass, colors.actual, colors.grid, colors.planned, mdGuides, points, curve, s.paper, selectedPoint])

  const click = (event: ChartClickEvent) => {
    if (event.chartRowId) {
      const md = Number(event.chartRowId)
      if (Number.isFinite(md)) onSelectMd(md)
      return
    }
    onSelectMd(null)
  }

  if (!curve.length) {
    return (
      <Alert severity="info" sx={{ fontSize: 12.5 }}>
        No survey stations are recorded for {path.well_code} ({path.scope}), so there is no path to project.
        With no survey, no path is drawn.
      </Alert>
    )
  }

  return (
    <Stack spacing={1.5}>
      <Box display="flex" justifyContent="flex-end" alignItems="center" sx={{ mt: -0.5 }}>
        <FormControlLabel
          control={<Checkbox size="small" checked={showMdLabels} onChange={(event) => setShowMdLabels(event.target.checked)} inputProps={{ 'aria-label': 'Show measured-depth labels' }} />}
          label={<Typography sx={{ fontSize: 11.5 }}>MD labels</Typography>}
          sx={{ mr: 0 }}
        />
      </Box>
      <Box
        display="grid"
        gap={2}
        gridTemplateColumns={{ xs: 'minmax(0,1fr)', lg: 'repeat(2,minmax(0,1fr))' }}
      >
        <Box>
          <Typography sx={{ fontSize: 11.5, fontWeight: 700, color: 'text.secondary', mb: 0.5 }}>
            Plan view · looking down · north up · equal N/E scale
          </Typography>
          {/* A square box with equal grid insets is what makes the equal N/E
              range a true 1:1 plan rather than a stretched one. */}
          <Box sx={{ width: height, maxWidth: '100%', aspectRatio: '1 / 1', mx: 'auto' }}>
            <InteractiveChart option={planOption} style={{ height: '100%' }} onEvents={{ click }} />
          </Box>
        </Box>
        <Box>
          <Typography sx={{ fontSize: 11.5, fontWeight: 700, color: 'text.secondary', mb: 0.5 }}>
            Vertical section · facing {fmtAngle(path.vertical_section_azimuth_deg, 1)} · TVD increases downward · dashed brass rules give interpolated MD
          </Typography>
          <Box sx={{ height }}>
            <InteractiveChart option={sectionOption} style={{ height: '100%' }} onEvents={{ click }} />
          </Box>
        </Box>
      </Box>
      <Typography sx={{ fontSize: 10.5, color: 'text.secondary', lineHeight: 1.5 }}>
        The vertical section is a projection, not a second survey: horizontal motion out of the stated plane
        disappears from it. Dashed brass rules are interpolated measured depths (never stations), labelled at the
        right edge of the plot. Depth window {fmtDepth(windowRange.from, 1)} – {fmtDepth(windowRange.to, 1)} m MD,
        clamped to the surveyed range.
        {marker.gap_m !== null && marker.gap_m > 0
          ? ` The reported hole bottom is ${fmtDepth(marker.gap_m, 1)} m below the last station and is not drawn as part of the line.`
          : ''}
      </Typography>
    </Stack>
  )
}

/**
 * Inclination and azimuth along measured depth — the steering record.
 *
 * The two angles are plotted on separate scales because they are different
 * quantities. Azimuth breaks at the 0°/360° wrap instead of drawing a false full
 * turn across the chart.
 */
export function WellSteeringTracks({
  path,
  selectedMd,
  onSelectMd,
  window,
  height = 230,
}: {
  path: OpsWellPath
  selectedMd: number | null
  onSelectMd: (md: number | null) => void
  window: DepthWindow
  height?: number
}) {
  const { mode } = useColorMode()
  const colors = chartPalette(mode)
  const curve = path.curve
  const range = effectiveWindow(curve, window)
  const points = useMemo(() => sliceCurve(curve, { from: range.from, to: range.to }), [curve, range.from, range.to])
  const azimuth = useMemo(() => azimuthSeries(points), [points])
  const selected = stationAt(curve, selectedMd)

  const base = {
    animation: false,
    textStyle: { color: colors.axis },
    grid: { left: 58, right: 24, top: 34, bottom: 40 },
    tooltip: { trigger: 'axis' as const, confine: true, axisPointer: { type: 'line' as const } },
  }

  const click = (event: ChartClickEvent) => {
    const md = Number(event.chartRowId)
    onSelectMd(Number.isFinite(md) && event.chartRowId ? md : null)
  }

  const incOption = useMemo(() => ({
    ...base,
    xAxis: { type: 'value' as const, name: 'MD (m)', nameLocation: 'middle' as const, nameGap: 26, min: range.from, max: range.to },
    yAxis: { type: 'value' as const, name: 'Inc (°)', min: 0, max: Math.max(90, Math.ceil(Math.max(0, ...points.map((p) => p.inc_deg)) / 15) * 15 + 2) },
    series: [
      {
        name: 'Inclination',
        type: 'line' as const,
        color: colors.planned,
        showSymbol: false,
        lineStyle: { width: 2 },
        data: points.map((point) => ({ value: [point.md_m, point.inc_deg], chartRowId: String(point.md_m) })),
      },
      ...(selected ? [{
        name: 'Selected',
        type: 'scatter' as const,
        color: colors.actual,
        symbolSize: 10,
        data: [{ value: [selected.md_m, selected.inc_deg], chartRowId: String(selected.md_m) }],
      }] : []),
    ],
  }), [base, colors.actual, colors.planned, points, range.from, range.to, selected])

  const aziOption = useMemo(() => ({
    ...base,
    xAxis: { type: 'value' as const, name: 'MD (m)', nameLocation: 'middle' as const, nameGap: 26, min: range.from, max: range.to },
    yAxis: {
      type: 'value' as const,
      name: 'Azi (° from grid north)',
      min: 0,
      max: 360,
      interval: 90,
      axisLabel: { formatter: '{value}°' },
    },
    series: [
      {
        name: 'Azimuth',
        type: 'line' as const,
        color: colors.series[2] ?? colors.adjusted,
        showSymbol: false,
        connectNulls: false,
        lineStyle: { width: 2 },
        data: azimuth.data.map(([md, value]) => ({
          value: [md, value],
          chartRowId: value === null ? '' : String(md),
        })),
      },
      ...(selected ? [{
        name: 'Selected',
        type: 'scatter' as const,
        color: colors.actual,
        symbolSize: 10,
        data: [{ value: [selected.md_m, selected.azi_deg], chartRowId: String(selected.md_m) }],
      }] : []),
    ],
  }), [azimuth.data, base, colors.actual, colors.adjusted, colors.series, range.from, range.to, selected])

  if (curve.length < 2) {
    return (
      <Typography sx={{ fontSize: 12.5, color: 'text.secondary' }}>
        Two stations are needed to plot a trend. {curve.length === 1 ? 'One station is recorded.' : 'None are recorded.'}
      </Typography>
    )
  }

  return (
    <Stack spacing={1}>
      <Stack direction={{ xs: 'column', lg: 'row' }} spacing={2}>
        <Box flex={1} minWidth={0} sx={{ height }}>
          <InteractiveChart option={incOption} style={{ height: '100%' }} onEvents={{ click }} />
        </Box>
        <Box flex={1} minWidth={0} sx={{ height }}>
          <InteractiveChart option={aziOption} style={{ height: '100%' }} onEvents={{ click }} />
        </Box>
      </Stack>
      <Typography sx={{ fontSize: 10.5, color: 'text.secondary', lineHeight: 1.5 }}>
        Inclination is measured from vertical (0° vertical, 90° horizontal); azimuth is clockwise from grid north.
        A first inclination at or above 1° is a threshold crossing, not necessarily the planned kick-off.
        {azimuth.wraps.length
          ? ` The azimuth line breaks at ${azimuth.wraps.map((md) => `${fmtDepth(md, 1)} m`).join(', ')} where it crosses 360°, rather than drawing a full turn.`
          : ''}
      </Typography>
      {selected && (
        <Typography sx={{ fontSize: 10.5, color: 'text.secondary' }}>
          Selected station {fmtDepth(selected.md_m, 2)} m · {fmtAngle(selected.inc_deg)} / {fmtAngle(selected.azi_deg)} ·
          DLS {fmtDls(selected.dls_deg_per_30m)}
          {isSurveyed(curve, selectedMd) ? '' : ' · outside the surveyed range'}
        </Typography>
      )}
    </Stack>
  )
}

export default WellPlanSectionViews
