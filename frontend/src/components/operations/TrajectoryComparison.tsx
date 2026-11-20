import { useMemo, useState } from 'react'
import { Autocomplete, Box, Checkbox, createFilterOptions, FormControlLabel, Stack, TextField, Typography } from '@mui/material'
import type { EChartsOption } from 'echarts'
import { useColorMode } from '../../context/ThemeContext'
import { chartPalette, surface } from '../../designSystem'
import type { OpsTrajectoryComparison } from '../../lib/operations'
import { equalPlanBounds, fmtAngle, fmtDepth, interpolateAt, sliceCurve, usableTrajectory, type DepthWindow, type CurvePoint } from '../../lib/wellPath'
import { InteractiveChart, type ChartClickEvent } from '../ui/InteractiveChart'
import { VisualExpand } from '../ui/VisualExpand'
import { SectionCard } from '../ui/SectionCard'
import { formatRange, parseNumber, parseRange, validRange, VisualDepthControls } from './VisualDepthControls'

export type TrajectoryPart = 'geometry' | 'steering'
const FULL_RANGE = { from: null, to: null }
const GEOMETRY_TITLE = 'Trajectory — plan view and vertical section'
const filterStations = createFilterOptions<{ md: number; label: string }>({ limit: 100 })
const STEERING_TITLE = 'Inclination and azimuth along measured depth'

export function TrajectoryComparisonPanel({ path, part = 'geometry', window = FULL_RANGE, selectedMd, onSelectMd, action, figureKey }: {
  path: OpsTrajectoryComparison
  part?: TrajectoryPart
  window?: DepthWindow
  selectedMd: number | null
  onSelectMd: (md: number | null) => void
  action?: React.ReactNode
  figureKey?: string
}) {
  const title = part === 'geometry' ? GEOMETRY_TITLE : STEERING_TITLE
  const exists = Boolean(path.curve.length || path.planned_trajectory?.curve.length)
  const subtitle = part === 'geometry'
    ? `Plan view uses a 1:1 north/east scale. Vertical section faces ${fmtAngle(path.vertical_section_azimuth_deg, 1)}.`
    : 'Both tracks use measured depth. The azimuth line breaks at the 360° wrap.'
  return <SectionCard title={title} subtitle={subtitle}
    dataAttributes={figureKey ? { 'data-chart-figure': '1', 'data-chart-key': figureKey, 'data-chart-title': title,
      'data-chart-subtitle': subtitle, 'data-chart-caption': path.comparison_basis ?? '', 'data-chart-empty': exists ? '0' : '1' } : undefined}
    action={<Stack direction="row" gap={1} flexWrap="wrap" useFlexGap>{action}{exists &&
      <TrajectoryExpand path={path} part={part} title={title} subtitle={subtitle} window={window} selectedMd={selectedMd} />}
    </Stack>}>
    <TrajectoryComparison path={path} part={part} window={window} selectedMd={selectedMd} onSelectMd={onSelectMd} />
  </SectionCard>
}

export function TrajectoryExpand({ path, part = 'geometry', title, subtitle, window, selectedMd }: {
  path: OpsTrajectoryComparison; part?: TrajectoryPart; title: string; subtitle?: string; window: DepthWindow; selectedMd: number | null
}) {
  return <VisualExpand visual={{ title, subtitle }}>
    {() => <TrajectoryComparison path={path} part={part} window={window} selectedMd={selectedMd} expanded />}
  </VisualExpand>
}

function TrajectoryComparison({ path, part, window, selectedMd, onSelectMd, expanded = false }: {
  path: OpsTrajectoryComparison; part: TrajectoryPart; window: DepthWindow;
  selectedMd: number | null; onSelectMd?: (md: number | null) => void; expanded?: boolean
}) {
  const [mdText, setMdText] = useState(() => formatRange(window))
  const [tvdText, setTvdText] = useState(() => formatRange(FULL_RANGE))
  const [extent, setExtent] = useState('')
  const [showPlan, setShowPlan] = useState(true)
  const [showActual, setShowActual] = useState(true)
  const [labels, setLabels] = useState(false)
  const [localSelection, setLocalSelection] = useState(selectedMd)
  const [inspectMd, setInspectMd] = useState(selectedMd?.toString() ?? '')
  const selection = expanded ? localSelection : selectedMd
  const setSelection = (md: number | null) => {
    if (expanded) { setLocalSelection(md); setInspectMd(String(md ?? '')) }
    else onSelectMd?.(md)
  }
  const { mode } = useColorMode()
  const colors = chartPalette(mode)
  const token = surface(mode)
  const plan = path.planned_trajectory
  const actual = useMemo(() => usableTrajectory(path.curve), [path.curve])
  const planned = plan?.curve ?? []
  const md = expanded ? parseRange(mdText) : window
  const tvd = parseRange(tvdText)
  const appliedRange = validRange(md) ? md : window
  const plansInView = showPlan ? sliceCurve(planned, appliedRange) : []
  const actualsInView = showActual ? sliceCurve(actual, appliedRange) : []
  const points = [...plansInView, ...actualsInView]
  const extentValue = parseNumber(extent)
  const extentError = extent !== '' && (extentValue === null || extentValue <= 0)
  const bounds = extentValue !== null && extentValue > 0 ? [-extentValue, extentValue] : equalPlanBounds(points)
  const insideRange = (value: number) => (appliedRange.from === null || value >= appliedRange.from) && (appliedRange.to === null || value <= appliedRange.to)
  const planAt = interpolateAt(planned, selection)
  const actualAt = interpolateAt(actual, selection)
  const reportDepthMd = path.position?.report_depth_md_m ?? null
  const reportPoint = showActual ? interpolateAt(actual, reportDepthMd) : null
  const evidence = selection === null ? null : path.survey_stations.find(row => Math.abs(row.md_m - selection) < 1e-6)

  const axis = (name: string, extra = {}) => ({
    type: 'value' as const, name, nameLocation: 'middle' as const, nameGap: 33,
    axisLine: { lineStyle: { color: colors.grid } }, axisLabel: { color: colors.axis, hideOverlap: true },
    splitLine: { lineStyle: { color: colors.grid, type: 'dashed' as const } }, ...extra,
  })
  const groups = [
    { name: 'Planned', points: plansInView, color: colors.planned, dashed: true, selected: showPlan ? planAt : null },
    { name: 'Actual', points: actualsInView, color: colors.actual, dashed: false, selected: showActual ? actualAt : null },
  ].filter(group => group.points.length)
  const option = (kind: 'map' | 'section' | 'inc' | 'azi'): EChartsOption => {
    const isMap = kind === 'map'
    const isSection = kind === 'section'
    const getXY = (pt: CurvePoint) => kind === 'map' ? [pt.ew_m, pt.ns_m] : kind === 'section' ? [pt.vsec_m, pt.tvd_m]
      : kind === 'inc' ? [pt.md_m, pt.inc_deg] : [pt.md_m, (pt.azi_deg + 360) % 360]
    const marker = isSection && reportPoint && insideRange(reportPoint.md_m) ? reportPoint : null
    const markerData = marker ? [{ value: getXY(marker), chartRowId: String(marker.md_m), point: marker, interpolated: marker.interpolated }] : []
    const yLimit = validRange(tvd, true) ? { min: tvd.from ?? undefined, max: tvd.to ?? undefined } : {}
    return {
      animation: false, textStyle: { color: colors.axis },
      grid: isMap ? { left: 52, right: 52, top: 52, bottom: 52 } : { left: 64, right: 26, top: 40, bottom: 52 },
      legend: { top: 0, selectedMode: false, textStyle: { color: colors.axis }, data: [...groups.map(group => group.name), ...(marker ? ['Report closing MD'] : [])] },
      tooltip: { trigger: 'item', renderMode: 'richText', formatter: raw => {
        const data = (Array.isArray(raw) ? raw[0] : raw) as { seriesName?: string; data?: { point?: CurvePoint; interpolated?: boolean } }
        const point = data.data?.point
        if (!point) return ''
        return `${data.seriesName} · ${fmtDepth(point.md_m, 3)} m MD${data.data?.interpolated ? ' (interpolated)' : ''}\n` +
          `TVD ${fmtDepth(point.tvd_m)} m · N ${fmtDepth(point.ns_m)} m · E ${fmtDepth(point.ew_m)} m\n` +
          `Inc ${fmtAngle(point.inc_deg)} · Azi ${fmtAngle((point.azi_deg + 360) % 360)}`
      } },
      xAxis: axis(isMap ? 'East (m)' : isSection ? 'Vertical section (m)' : 'Measured depth (m)',
        isMap ? { min: bounds[0], max: bounds[1] } : isSection ? { scale: true } : { min: appliedRange.from ?? 'dataMin', max: appliedRange.to ?? 'dataMax' }),
      yAxis: axis(isMap ? 'North (m)' : isSection ? 'TVD (m)' : kind === 'inc' ? 'Inclination (°)' : 'Azimuth (°)',
        isMap ? { min: bounds[0], max: bounds[1] } : isSection ? { scale: true, inverse: true, ...yLimit } : { min: 0, max: kind === 'azi' ? 360 : 180 }),
      series: [...groups.flatMap(group => {
        const data = group.points.flatMap((point, index) => {
          const [x, y] = getXY(point)
          const datum = { value: [x, y], chartRowId: String(point.md_m), point, interpolated: point.interpolated }
          return kind === 'azi' && index > 0 && Math.abs(y - getXY(group.points[index - 1])[1]) > 180 ? [[x, null], datum] : [datum]
        })
        const selected = group.selected && insideRange(group.selected.md_m) ? group.selected : null
        return [{
          name: group.name, type: 'line' as const, data, color: group.color, symbol: group.dashed ? 'emptyCircle' : 'circle',
          showSymbol: true, symbolSize: 5, connectNulls: false, clip: true,
          lineStyle: { width: 2.5, type: group.dashed ? 'dashed' as const : 'solid' as const },
          label: { show: labels, formatter: (row: { data: unknown }) => {
            const datum = row.data as { point?: CurvePoint } | null
            return datum?.point ? `${fmtDepth(datum.point.md_m, 1)} m` : ''
          } }, labelLayout: { hideOverlap: true },
        }, ...(selected ? [{
          name: group.name, type: 'scatter' as const, color: group.color, symbolSize: 12,
          itemStyle: { borderColor: token.paper, borderWidth: 2 }, z: 6,
          data: [{ value: getXY(selected), chartRowId: String(selected.md_m), point: selected, interpolated: selected.interpolated }],
        }] : [])]
      }), ...(marker ? [{
        name: 'Report closing MD', type: 'scatter' as const, symbol: 'diamond', symbolSize: 13, color: colors.adjusted, z: 5,
        data: markerData,
      }] : [])],
    }
  }
  const click = (event: ChartClickEvent) => { if (event.chartRowId) setSelection(Number(event.chartRowId)) }
  const plotSize = expanded ? 'min(62vh, 580px)' : 335
  const hasComparison = Boolean(plan?.curve.length && actual.length)
  const ranges = (curve: typeof actual) => curve.length ? `${fmtDepth(curve[0].md_m, 1)}–${fmtDepth(curve[curve.length - 1].md_m, 1)} m MD` : ''
  const overlap = hasComparison && Math.max(planned[0].md_m, actual[0].md_m) <= Math.min(planned.at(-1)!.md_m, actual.at(-1)!.md_m)
  const draftCount = path.survey_stations.filter(row => row.report_status && !['submitted', 'approved'].includes(row.report_status)).length
  const stationChoices = useMemo(() => [...new Set(points.filter(point => !point.interpolated).map(point => point.md_m))]
    .sort((a, b) => a - b).map(md => ({ md, label: `${fmtDepth(md, 3)} m MD` })), [points])
  return <Stack spacing={1.5}>
    <Typography color="text.secondary" variant="body2">
      {plan?.curve.length ? <>Planned: {plan.label} · v{plan.version_no} ({plan.status}) · {ranges(planned)} · {plan.anchor_basis}.</>
        : plan ? `No planned survey saved for ${plan.label} · v${plan.version_no} (${plan.status}).` : ''}
      {' '}{path.actual_visible === false ? 'Actual survey is not available with your report permissions.'
        : actual.length ? `Actual: ${ranges(actual)}.${draftCount ? ` Includes ${draftCount} station(s) from reports not yet submitted or approved.` : ''}` : 'No usable actual survey stations.'}
    </Typography>
    {plan?.sources.length && part === 'geometry' ? <Typography variant="caption" color="text.secondary">Planned sources: {plan.sources.slice(0, 3).join('; ')}{plan.sources.length > 3 && ` · ${plan.sources.length - 3} more in the station table`}</Typography> : null}
    {part === 'geometry' && hasComparison && <Typography color="text.secondary" variant="caption">
      {path.comparison_basis}{!overlap && ' The two surveys have no overlapping measured depths.'}
    </Typography>}
    {part === 'geometry' && reportDepthMd !== null && !interpolateAt(actual, reportDepthMd) && <Typography variant="caption" color="text.secondary">
      Report closing depth: {fmtDepth(reportDepthMd)} m MD, outside the usable actual survey coverage. The trajectory is not extrapolated to it.
    </Typography>}
    {actual.length < path.curve.length && <Typography variant="caption" color="text.secondary">Actual geometry stops before an unusable interval; positions below it are not compared.</Typography>}
    {expanded && <>
      <VisualDepthControls range={mdText} onChange={setMdText} reset={() => {
        setMdText(formatRange(window)); setTvdText(formatRange(FULL_RANGE)); setExtent(''); setLabels(false); setShowPlan(true); setShowActual(true)
      }} />
      {part === 'geometry' && <Stack direction="row" gap={1} flexWrap="wrap" useFlexGap>
        <TextField size="small" type="number" label="Equal N/E limit ±m" value={extent} error={extentError}
          helperText={extentError ? 'Enter a positive limit.' : 'Blank uses the data extent.'}
          onChange={event => setExtent(event.target.value)} />
        <VisualDepthControls axis="TVD" range={tvdText} onChange={setTvdText} />
      </Stack>}
      <Stack direction="row" gap={1} alignItems="center" flexWrap="wrap" useFlexGap>
        {planned.length > 0 && <FormControlLabel control={<Checkbox checked={showPlan} onChange={event => setShowPlan(event.target.checked)} />} label="Planned" />}
        {actual.length > 0 && <FormControlLabel control={<Checkbox checked={showActual} onChange={event => setShowActual(event.target.checked)} />} label="Actual" />}
        <FormControlLabel control={<Checkbox checked={labels} onChange={event => setLabels(event.target.checked)} />} label="MD data labels" />
        <TextField size="small" type="number" label="Inspect exact MD (m)" value={inspectMd} slotProps={{ htmlInput: { step: 'any', min: 0 } }}
          onChange={event => { setInspectMd(event.target.value); setLocalSelection(parseNumber(event.target.value)) }} />
        <Autocomplete size="small" sx={{ width: 240 }} options={stationChoices} value={null} filterOptions={filterStations}
          onChange={(_, option) => { if (option) setSelection(option.md) }}
          renderInput={params => <TextField {...params} label="Jump to a station" />} />
      </Stack>
    </>}
    {points.length > 0 ? <Box display="grid" gap={2} gridTemplateColumns={{ xs: 'minmax(0,1fr)', md: 'repeat(2,minmax(0,1fr))' }}>
      {part === 'geometry' ? <>
        <Box sx={{ width: plotSize, maxWidth: '100%', aspectRatio: '1 / 1', mx: 'auto' }}>
          <InteractiveChart option={option('map')} onEvents={{ click }} expandable={false} />
        </Box>
        <Box sx={{ height: plotSize }}><InteractiveChart option={option('section')} onEvents={{ click }} expandable={false} /></Box>
      </> : <>
        <Box sx={{ height: expanded ? plotSize : 245 }}><InteractiveChart option={option('inc')} onEvents={{ click }} expandable={false} /></Box>
        <Box sx={{ height: expanded ? plotSize : 245 }}><InteractiveChart option={option('azi')} onEvents={{ click }} expandable={false} /></Box>
      </>}
    </Box> : (planned.length > 0 || actual.length > 0) && <Typography color="text.secondary" variant="body2">No visible stations in this depth window.</Typography>}
    {selection !== null && <Stack spacing={0.5} aria-live="polite">
      <Typography variant="subtitle2">{fmtDepth(selection, 3)} m MD</Typography>
      {([{ name: 'Planned', value: planAt, visible: Boolean(plan) }, { name: 'Actual', value: actualAt, visible: path.actual_visible !== false }]).map(({ name, value, visible }) => visible && <Typography key={String(name)} variant="caption" color="text.secondary">
        {String(name)}: {value ? `TVD ${fmtDepth(value.tvd_m)} m · N ${fmtDepth(value.ns_m)} m · E ${fmtDepth(value.ew_m)} m · Inc ${fmtAngle(value.inc_deg)} · Azi ${fmtAngle((value.azi_deg + 360) % 360)}${value.interpolated ? ' (interpolated)' : ' (survey station)'}` : 'outside usable survey coverage'}
        {name === 'Actual' && evidence ? ` · ${[evidence.report_no, evidence.report_date, evidence.report_status, evidence.source].filter(Boolean).join(' · ')}` : ''}
      </Typography>)}
      {path.comparable && planAt && actualAt && <Typography variant="caption">
        Actual − Planned: TVD {fmtDepth(actualAt.tvd_m - planAt.tvd_m)} m · N {fmtDepth(actualAt.ns_m - planAt.ns_m)} m · E {fmtDepth(actualAt.ew_m - planAt.ew_m)} m
      </Typography>}
    </Stack>}
  </Stack>
}
