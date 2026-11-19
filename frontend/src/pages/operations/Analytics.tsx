import { useEffect, useMemo, useState } from 'react'
import { Link as RouterLink, useNavigate } from 'react-router-dom'
import { Box, Button, Chip, MenuItem, Stack, TextField, Typography } from '@mui/material'
import { RestartAlt, Tune } from '@mui/icons-material'
import { ErrorMessage, PageHeading } from '../../components/Common'
import { OpsAiReviewPanel } from '../../components/operations/OpsAiReviewPanel'
import { ChartPanel } from '../../components/ui/ChartPanel'
import { InteractiveChart, type ChartClickEvent } from '../../components/ui/InteractiveChart'
import { DataTable } from '../../components/DataTable'
import { useAuth } from '../../context/AuthContext'
import { useColorMode } from '../../context/ThemeContext'
import { chartPalette } from '../../designSystem'
import {
  auditExport,
  computeTimeDepthAxes,
  formatOpsRop,
  opsScopeReference,
  opsTimeDepth,
  type OpsScopeReference,
  type OpsTimeDepth,
  type TimeDepthAxisOverrides,
} from '../../lib/operations'

const EMPTY_AXES: TimeDepthAxisOverrides = {
  xMin: '',
  xMax: '',
  xStep: '',
  yMin: '',
  yMax: '',
  yStep: '',
}

const DAY_PRESETS = ['1', '2', '5', '10', '15', '30']
const DEPTH_PRESETS = ['100', '200', '300', '500', '1000']
const ACTIVITY_PRESETS = ['1', '2', '5', '10', '20']

export default function OperationsAnalytics() {
  const { can } = useAuth()
  const go = useNavigate()
  const { mode } = useColorMode()
  const colors = chartPalette(mode)

  const [ref, setRef] = useState<OpsScopeReference | null>(null)
  const [well, setWell] = useState('')
  const [scope, setScope] = useState('drilling')
  const [data, setData] = useState<OpsTimeDepth | null>(null)
  const [error, setError] = useState('')
  const [axisOpen, setAxisOpen] = useState(false)
  const [axisOverrides, setAxisOverrides] = useState<TimeDepthAxisOverrides>(EMPTY_AXES)

  useEffect(() => {
    opsScopeReference()
      .then((r) => {
        setRef(r)
        if (r.wells[0]) {
          setWell(r.wells[0].id)
          setScope(r.wells[0].drilling_available ? 'drilling' : 'completion')
        }
      })
      .catch((e) => setError(e.message))
  }, [])

  useEffect(() => {
    let current = true
    setData(null)
    setAxisOverrides(EMPTY_AXES)
    if (well) {
      setError('')
      opsTimeDepth(well, scope)
        .then((d) => {
          if (current) setData(d)
        })
        .catch((e) => {
          if (current) setError(e.message)
        })
    }
    return () => {
      current = false
    }
  }, [well, scope])

  const events = can('ops-report:read')
    ? {
        click: (event: ChartClickEvent) => {
          if (event.chartRowId) go(`/operations/reports/${event.chartRowId}`)
        },
      }
    : undefined

  const isCompletion = scope === 'completion'
  const actual = data?.actual ?? []
  const plan = data?.plan ?? []
  const projection = isCompletion ? [] : (data?.projection ?? [])
  const lag = data?.lag_series ?? []
  const rop = isCompletion ? [] : actual.filter((a) => a.rop !== null)

  // A completion has no depth axis; programme activities are plotted by ordinal number (1..n).
  const ordinal = isCompletion || data?.mode === 'activity'
  const plannedY = (p: { depth_m: number | null; activity_no?: number | null; cum_days: number }) =>
    ordinal ? (p.activity_no ?? null) : p.depth_m

  const axes = useMemo(() => {
    const xValues = [
      ...plan.map((p) => Number(p.cum_days)),
      ...actual.map((p) => Number(p.cum_days)),
      ...projection.map((p) => Number(p.cum_days)),
    ]
    const yValues = ordinal
      ? [
          ...plan.map((p) => Number(p.activity_no ?? NaN)),
          ...actual.map((p) => Number(p.activity_no ?? NaN)),
        ]
      : [
          ...plan.map((p) => Number(p.depth_m ?? NaN)),
          ...actual.map((p) => Number(p.depth_m ?? NaN)),
          ...projection.map((p) => Number(p.depth_m ?? NaN)),
        ]
    return computeTimeDepthAxes({
      mode: ordinal ? 'activity' : 'depth',
      xValues,
      yValues,
      overrides: axisOverrides,
    })
  }, [plan, actual, projection, ordinal, axisOverrides])

  const base = {
    animation: false,
    tooltip: { trigger: 'axis', confine: true },
    textStyle: { color: colors.axis },
    grid: { left: 24, right: 28, top: 48, bottom: 54, containLabel: true },
    legend: { top: 2, type: 'scroll', textStyle: { color: colors.axis } },
  }

  const timeAxis = {
    type: 'value',
    name: 'Elapsed days',
    nameLocation: 'middle',
    nameGap: 32,
    min: axes.xMin,
    max: axes.xMax,
    interval: axes.xStep,
    axisLabel: {
      hideOverlap: true,
      margin: 10,
      formatter: (v: number) => (Number.isInteger(v) ? String(v) : Number(v.toFixed(2)).toString()),
    },
  }

  const ropTimeAxis = {
    type: 'value',
    name: 'Elapsed days',
    nameLocation: 'middle',
    nameGap: 30,
    axisLabel: { hideOverlap: true },
  }

  const progressYAxis = ordinal
    ? {
        type: 'value',
        name: 'Activity no.',
        inverse: true,
        min: axes.yMin,
        max: axes.yMax,
        interval: axes.yStep,
        minInterval: 1,
        axisLabel: {
          hideOverlap: true,
          margin: 12,
          formatter: (v: number) => (Number.isInteger(v) ? String(v) : ''),
        },
      }
    : {
        type: 'value',
        name: 'MD (m)',
        inverse: true,
        min: axes.yMin,
        max: axes.yMax,
        interval: axes.yStep,
        axisLabel: {
          hideOverlap: true,
          margin: 12,
          formatter: (v: number) => v.toLocaleString('en-US', { maximumFractionDigits: 1 }),
        },
      }

  const depthOption = {
    ...base,
    xAxis: timeAxis,
    yAxis: progressYAxis,
    series: [
      {
        name: 'Active plan',
        type: 'line',
        connectNulls: false,
        color: colors.planned,
        data: plan.map((p) => [p.cum_days, plannedY(p)]),
      },
      {
        name: 'Actual',
        type: 'line',
        color: colors.actual,
        data: actual.map((p) => ({ value: [p.cum_days, plannedY(p)], chartRowId: p.report_id })),
      },
      ...(!ordinal
        ? [
            {
              name: 'ROP projection',
              type: 'line',
              color: colors.adjusted,
              lineStyle: { type: 'dashed' },
              data: projection.map((p) => [p.cum_days, p.depth_m]),
            },
          ]
        : []),
    ],
  }

  const updateAxis = (field: keyof TimeDepthAxisOverrides, value: string) =>
    setAxisOverrides((prev) => ({ ...prev, [field]: value }))
  const resetAxes = () => setAxisOverrides(EMPTY_AXES)
  const yPresets = ordinal ? ACTIVITY_PRESETS : DEPTH_PRESETS
  const yUnit = ordinal ? 'act.' : 'm'

  const progressEmpty = ordinal
    ? !actual.length && !plan.length
    : !actual.some((p) => p.depth_m !== null) && !plan.some((p) => p.depth_m !== null)

  return (
    <Box>
      <PageHeading
        eyebrow="Well Operations"
        title="Operations analytics"
        subtitle="Compare submitted or approved measurements with the active programme (WAT UTC+1:00). Select an actual point to inspect its report, or open Operation Summary for the full multi-day export."
        action={
          can('ops-report:read') && well ? (
            <Button
              component={RouterLink}
              to={`/operations/summary?well=${encodeURIComponent(well)}&scope=${encodeURIComponent(scope)}`}
              variant="outlined"
            >
              Operation summary
            </Button>
          ) : undefined
        }
      />
      {error && <ErrorMessage message={error} />}
      <Box display="flex" gap={2} flexWrap="wrap" mb={2}>
        <TextField
          sx={{ minWidth: 220 }}
          select
          label="Well"
          value={well}
          onChange={(e) => {
            setWell(e.target.value)
            setScope(ref?.wells.find((w) => w.id === e.target.value)?.drilling_available ? 'drilling' : 'completion')
          }}
        >
          {/* Always one option: the menu is empty before the reference loads and in
              a workspace with no configured well, and an empty select cannot show
              what it is waiting for. */}
          {(ref?.wells ?? []).map((w) => (
            <MenuItem key={w.id} value={w.id}>
              {w.display_name}
            </MenuItem>
          ))}
          {(ref?.wells ?? []).length === 0 && (
            <MenuItem value="" disabled>
              {ref ? 'No well is configured yet' : 'Loading wells…'}
            </MenuItem>
          )}
        </TextField>
        <TextField
          select
          label="Scope"
          value={scope}
          onChange={(e) => setScope(e.target.value)}
          sx={{ minWidth: 160 }}
        >
          <MenuItem value="drilling" disabled={!ref?.wells.find((w) => w.id === well)?.drilling_available}>
            Drilling
          </MenuItem>
          <MenuItem value="completion" disabled={!ref?.wells.find((w) => w.id === well)?.completion_available}>
            Completion
          </MenuItem>
        </TextField>
      </Box>
      <Box display="grid" gap={2} gridTemplateColumns="minmax(0,1fr)">
        <ChartPanel
          title={ordinal ? 'Time vs completion progress' : 'Time vs measured depth'}
          figureKey="time-depth"
          meta={
            !progressEmpty ? (
              <Stack direction="row" spacing={1} alignItems="center" flexWrap="wrap">
                <Typography variant="caption" sx={{ color: 'text.secondary', fontVariantNumeric: 'tabular-nums' }}>
                  X step {axes.xStep} d · Y step {axes.yStep} {yUnit}
                </Typography>
                {axes.isCustom && (
                  <Button
                    size="small"
                    variant="text"
                    startIcon={<RestartAlt fontSize="small" />}
                    onClick={resetAxes}
                    aria-label="Reset axes"
                  >
                    Reset axes
                  </Button>
                )}
                <Button
                  size="small"
                  variant={axisOpen || axes.isCustom ? 'outlined' : 'text'}
                  startIcon={<Tune fontSize="small" />}
                  onClick={() => setAxisOpen((open) => !open)}
                  aria-expanded={axisOpen}
                >
                  Axis scale
                </Button>
              </Stack>
            ) : undefined
          }
          toolbar={
            axisOpen && !progressEmpty ? (
              <Stack spacing={1.25} data-testid="time-depth-axis-controls">
                <Box
                  display="grid"
                  gap={1.25}
                  gridTemplateColumns={{ xs: '1fr', md: 'repeat(6, minmax(96px, 1fr)) auto' }}
                  alignItems="center"
                >
                  <TextField
                    size="small"
                    type="number"
                    label="X min (days)"
                    placeholder="0"
                    value={axisOverrides.xMin}
                    onChange={(e) => updateAxis('xMin', e.target.value)}
                    slotProps={{ inputLabel: { shrink: true }, htmlInput: { min: 0, step: 'any' } }}
                  />
                  <TextField
                    size="small"
                    type="number"
                    label="X max (days)"
                    placeholder={String(axes.defaultXMax)}
                    value={axisOverrides.xMax}
                    onChange={(e) => updateAxis('xMax', e.target.value)}
                    slotProps={{ inputLabel: { shrink: true }, htmlInput: { min: 0, step: 'any' } }}
                  />
                  <TextField
                    size="small"
                    type="number"
                    label="X step (days)"
                    placeholder={String(axes.defaultXStep)}
                    value={axisOverrides.xStep}
                    onChange={(e) => updateAxis('xStep', e.target.value)}
                    slotProps={{ inputLabel: { shrink: true }, htmlInput: { min: 0.1, step: 'any' } }}
                  />
                  <TextField
                    size="small"
                    type="number"
                    label={ordinal ? 'Y min (activity)' : 'Y min (MD m)'}
                    placeholder="0"
                    value={axisOverrides.yMin}
                    onChange={(e) => updateAxis('yMin', e.target.value)}
                    slotProps={{ inputLabel: { shrink: true }, htmlInput: { min: 0, step: ordinal ? 1 : 'any' } }}
                  />
                  <TextField
                    size="small"
                    type="number"
                    label={ordinal ? 'Y max (activity)' : 'Y max (MD m)'}
                    placeholder={String(axes.defaultYMax)}
                    value={axisOverrides.yMax}
                    onChange={(e) => updateAxis('yMax', e.target.value)}
                    slotProps={{ inputLabel: { shrink: true }, htmlInput: { min: 1, step: ordinal ? 1 : 'any' } }}
                  />
                  <TextField
                    size="small"
                    type="number"
                    label={ordinal ? 'Y step (activity)' : 'Y step (MD m)'}
                    placeholder={String(axes.defaultYStep)}
                    value={axisOverrides.yStep}
                    onChange={(e) => updateAxis('yStep', e.target.value)}
                    slotProps={{ inputLabel: { shrink: true }, htmlInput: { min: 1, step: ordinal ? 1 : 'any' } }}
                  />
                  <Button
                    size="small"
                    variant="outlined"
                    startIcon={<RestartAlt fontSize="small" />}
                    onClick={resetAxes}
                    disabled={!axes.isCustom}
                  >
                    Reset
                  </Button>
                </Box>
                <Stack direction="row" spacing={0.75} flexWrap="wrap" useFlexGap alignItems="center">
                  <Typography variant="caption" sx={{ color: 'text.secondary', mr: 0.5 }}>
                    {ordinal ? 'Activity interval:' : 'Depth interval:'}
                  </Typography>
                  <Chip
                    size="small"
                    label={`Auto (${axes.defaultYStep} ${yUnit})`}
                    variant={!axisOverrides.yStep ? 'filled' : 'outlined'}
                    color={!axisOverrides.yStep ? 'primary' : 'default'}
                    onClick={() => updateAxis('yStep', '')}
                  />
                  {yPresets.map((preset) => (
                    <Chip
                      key={`y-${preset}`}
                      size="small"
                      label={ordinal ? `${preset}` : `${preset} m`}
                      variant={axisOverrides.yStep === preset ? 'filled' : 'outlined'}
                      color={axisOverrides.yStep === preset ? 'primary' : 'default'}
                      onClick={() => updateAxis('yStep', preset)}
                    />
                  ))}
                  <Typography variant="caption" sx={{ color: 'text.secondary', ml: 1.5, mr: 0.5 }}>
                    Day interval:
                  </Typography>
                  <Chip
                    size="small"
                    label={`Auto (${axes.defaultXStep} d)`}
                    variant={!axisOverrides.xStep ? 'filled' : 'outlined'}
                    color={!axisOverrides.xStep ? 'primary' : 'default'}
                    onClick={() => updateAxis('xStep', '')}
                  />
                  {DAY_PRESETS.map((preset) => (
                    <Chip
                      key={`x-${preset}`}
                      size="small"
                      label={`${preset} d`}
                      variant={axisOverrides.xStep === preset ? 'filled' : 'outlined'}
                      color={axisOverrides.xStep === preset ? 'primary' : 'default'}
                      onClick={() => updateAxis('xStep', preset)}
                    />
                  ))}
                </Stack>
                {axes.warning && (
                  <Typography variant="caption" sx={{ color: 'warning.main' }}>
                    {axes.warning}
                  </Typography>
                )}
              </Stack>
            ) : undefined
          }
          caption={
            ordinal
              ? `Completion operations plot elapsed days against whole-number programme activities (currently ${axes.yMin}–${axes.yMax} in steps of ${axes.yStep}; use Axis scale to customise X and Y bounds or intervals). Rate of penetration (ROP) is N/A for completion operations.`
              : `Elapsed days from programme start, or reported drilling DFS for an undated drilling plan. Depth runs in ${axes.yStep} m steps (${axes.yMin.toLocaleString('en-US')}–${axes.yMax.toLocaleString('en-US')} m; default 300 m, adjustable via Axis scale); the dashed projection assumes continuous rotation at the latest measured ROP.`
          }
          height={560}
          empty={progressEmpty}
          emptyMessage={
            ordinal
              ? 'Activate a completion timeline or submit a report.'
              : 'Activate a timeline or submit a report with measured depth.'
          }
        >
          <InteractiveChart option={depthOption} onEvents={events} style={{ height: '100%' }} />
        </ChartPanel>
        <Box display="grid" gap={2} gridTemplateColumns={{ xs: 'minmax(0,1fr)', lg: 'repeat(2,minmax(0,1fr))' }}>
          <ChartPanel
            title="Lead (+) / lag (−) in days"
            figureKey="lead-lag"
            caption="Saved baseline days at the confirmed activity, or interpolated at the same measured depth, minus actual elapsed days. A positive bar is a lead ahead of plan; a negative bar is a lag behind it. Ambiguous depths have no depth-based comparison."
            empty={!lag.length}
            emptyMessage="No uniquely comparable depth and elapsed-day pair."
          >
            <InteractiveChart
              onEvents={events}
              style={{ height: '100%' }}
              option={{
                ...base,
                xAxis: { type: 'category', data: lag.map((a) => a.report_date), axisLabel: { hideOverlap: true } },
                yAxis: { type: 'value', name: 'Days' },
                series: [
                  {
                    type: 'bar',
                    color: colors.actual,
                    data: lag.map((a) => ({ value: a.lag_days, chartRowId: a.report_id })),
                  },
                ],
              }}
            />
          </ChartPanel>
          <ChartPanel
            title="Rate of penetration"
            meta={isCompletion ? 'N/A' : 'm/h'}
            caption={
              isCompletion
                ? 'Rate of penetration (ROP) applies to drilling operations only and is always reported as N/A for completion scopes.'
                : 'Metres gained ÷ measured rotating hours. Missing denominators are not estimated from shift length.'
            }
            empty={isCompletion || !rop.length}
            emptyMessage={
              isCompletion
                ? 'N/A — Rate of penetration is not applicable to completion operations.'
                : 'No report has both footage and rotating hours.'
            }
          >
            <InteractiveChart
              onEvents={events}
              style={{ height: '100%' }}
              option={{
                ...base,
                xAxis: ropTimeAxis,
                yAxis: { type: 'value', name: 'm/h' },
                series: [
                  {
                    type: 'line',
                    color: colors.actual,
                    data: rop.map((a) => ({ value: [a.cum_days, a.rop], chartRowId: a.report_id })),
                  },
                ],
              }}
            />
          </ChartPanel>
        </Box>
        <DataTable
          rows={actual.map((a) => ({
            ...a,
            rop_display: formatOpsRop(a.rop, isCompletion, '', '—'),
            lag_days: lag.find((l) => l.report_id === a.report_id)?.lag_days ?? null,
            comparison: lag.find((l) => l.report_id === a.report_id)?.basis,
            baseline: lag.find((l) => l.report_id === a.report_id)?.baseline,
          }))}
          rowKey="report_id"
          exportName="operations-performance"
          canExport={can('ops-analytics:export')}
          onExport={auditExport('analytics')}
          columns={[
            { field: 'report_date', headerName: 'Report date' },
            { field: 'cum_days', headerName: 'Elapsed days' },
            { field: 'basis', headerName: 'Time basis' },
            ...(ordinal
              ? [{ field: 'activity_no' as const, headerName: 'Activity no.' }]
              : [{ field: 'depth_m' as const, headerName: 'MD (m)' }]),
            { field: 'rop_display', headerName: 'ROP (m/h)' },
            { field: 'lag_days', headerName: 'Lag (days)' },
            { field: 'baseline', headerName: 'Baseline version' },
            { field: 'comparison', headerName: 'Comparison basis' },
          ]}
        />
        <OpsAiReviewPanel wellId={well || undefined} scope={scope || undefined} />
      </Box>
    </Box>
  )
}
