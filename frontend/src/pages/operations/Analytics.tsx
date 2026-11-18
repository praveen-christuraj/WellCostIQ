import { useEffect, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { Box, MenuItem, TextField } from '@mui/material'
import { ErrorMessage, PageHeading } from '../../components/Common'
import { ChartPanel } from '../../components/ui/ChartPanel'
import { InteractiveChart, type ChartClickEvent } from '../../components/ui/InteractiveChart'
import { DataTable } from '../../components/DataTable'
import { useAuth } from '../../context/AuthContext'
import { useColorMode } from '../../context/ThemeContext'
import { chartPalette } from '../../designSystem'
import { auditExport, opsTimeDepth, opsScopeReference, type OpsScopeReference, type OpsTimeDepth } from '../../lib/operations'

export default function OperationsAnalytics() {
  const { can } = useAuth(),
    go = useNavigate(),
    { mode } = useColorMode(),
    colors = chartPalette(mode)
  const [ref, setRef] = useState<OpsScopeReference | null>(null),
    [well, setWell] = useState(''),
    [scope, setScope] = useState('drilling'),
    [data, setData] = useState<OpsTimeDepth | null>(null),
    [error, setError] = useState('')
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
  const base = {
    animation: false,
    tooltip: { trigger: 'axis', confine: true },
    textStyle: { color: colors.axis },
    grid: { left: 20, right: 28, top: 48, bottom: 52, containLabel: true },
    legend: { top: 2, type: 'scroll', textStyle: { color: colors.axis } },
  }
  const days = { type: 'value', name: 'Elapsed days', nameLocation: 'middle', nameGap: 30, axisLabel: { hideOverlap: true } }
  const actual = data?.actual ?? [],
    lag = data?.lag_series ?? [],
    rop = actual.filter((a) => a.rop !== null)
  const depth = {
    ...base,
    xAxis: days,
    yAxis: { type: 'value', name: 'MD (m)', inverse: true },
    series: [
      {
        name: 'Active plan',
        type: 'line',
        connectNulls: false,
        color: colors.planned,
        data: data?.plan.map((p) => [p.cum_days, p.depth_m]) ?? [],
      },
      {
        name: 'Actual',
        type: 'line',
        color: colors.actual,
        data: actual.map((p) => ({ value: [p.cum_days, p.depth_m], chartRowId: p.report_id })),
      },
      {
        name: 'ROP projection',
        type: 'line',
        color: colors.adjusted,
        lineStyle: { type: 'dashed' },
        data: data?.projection.map((p) => [p.cum_days, p.depth_m]) ?? [],
      },
    ],
  }
  return (
    <Box>
      <PageHeading
        eyebrow="Well Operations"
        title="Operations analytics"
        subtitle="Compare submitted or approved measurements with the active programme. Select an actual point to inspect its report."
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
          {ref?.wells.map((w) => (
            <MenuItem key={w.id} value={w.id}>
              {w.display_name}
            </MenuItem>
          ))}
        </TextField>
        <TextField select label="Scope" value={scope} onChange={(e) => setScope(e.target.value)} sx={{ minWidth: 160 }}>
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
          title="Time vs measured depth"
          caption="Elapsed days from programme start, or reported drilling DFS for an undated drilling plan. Otherwise days are relative to the first submitted period, without a lag estimate. The dashed projection to the next deeper target assumes continuous rotation at the latest measured ROP, not a completion forecast."
          height={350}
          empty={!actual.some((p) => p.depth_m !== null) && !data?.plan.some((p) => p.depth_m !== null)}
          emptyMessage="Activate a timeline or submit a report with measured depth."
        >
          <InteractiveChart option={depth} onEvents={events} style={{ height: '100%' }} />
        </ChartPanel>
        <Box display="grid" gap={2} gridTemplateColumns={{ xs: 'minmax(0,1fr)', lg: 'repeat(2,minmax(0,1fr))' }}>
          <ChartPanel
            title="Lead / lag (days)"
            caption="Actual days minus the saved baseline days at the confirmed activity or, otherwise, interpolated at the same depth. Positive is behind. Ambiguous depths have no depth-based lag."
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
            caption="Metres gained ÷ measured rotating hours. Missing denominators are not estimated from shift length."
            empty={!rop.length}
            emptyMessage="No report has both footage and rotating hours."
          >
            <InteractiveChart
              onEvents={events}
              style={{ height: '100%' }}
              option={{
                ...base,
                xAxis: days,
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
            { field: 'depth_m', headerName: 'MD (m)' },
            { field: 'rop', headerName: 'ROP (m/h)' },
            { field: 'lag_days', headerName: 'Lag (days)' },
            { field: 'baseline', headerName: 'Baseline version' },
            { field: 'comparison', headerName: 'Comparison basis' },
          ]}
        />
      </Box>
    </Box>
  )
}
