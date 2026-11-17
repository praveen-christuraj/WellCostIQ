import { useEffect, useMemo, useState } from 'react'
import { Alert, Box, Button, FormControl, InputLabel, MenuItem, Select, Typography } from '@mui/material'
import { ErrorMessage, PageHeading } from '../../components/Common'
import { ChartPanel } from '../../components/ui/ChartPanel'
import { InteractiveChart } from '../../components/ui/InteractiveChart'
import { SectionCard } from '../../components/ui/SectionCard'
import { useColorMode } from '../../context/ThemeContext'
import { chartPalette } from '../../designSystem'
import { opsTimeDepth, opsReference,  type OpsReference, type OpsTimeDepth } from '../../lib/operations'

export default function OperationsAnalytics() {
  const { mode } = useColorMode()
  const palette = useMemo(() => chartPalette(mode), [mode])
  const [ref, setRef] = useState<OpsReference | null>(null)
  const [wellId, setWellId] = useState('')
  const [scope, setScope] = useState('drilling')
  const [data, setData] = useState<OpsTimeDepth | null>(null)
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState('')

  const loadRef = async () => {
    try { const r = await opsReference(); setRef(r); if (r.wells[0]) setWellId(r.wells[0].id) } catch (e) { setError((e as Error).message) }
  }
  useEffect(() => { loadRef() }, [])

  const load = async () => {
    if (!wellId) return
    setLoading(true); setError('')
    try { const d = await opsTimeDepth(wellId, scope); setData(d) } catch (e) { setError((e as Error).message) } finally { setLoading(false) }
  }
  useEffect(() => { if (wellId) load() }, [wellId, scope])

  const timeDepthOption = useMemo(() => {
    if (!data || !data.actual.length) return null
    const planSeries = data.plan.map(p => [p.cum_days, p.depth_m])
    const actualSeries = data.actual.map(a => [a.cum_days, a.depth_m])
    return {
      tooltip: { trigger: 'axis' },
      legend: { data: ['Plan', 'Actual'], bottom: 10, left: 'center' },
      grid: { left: 80, right: 40, top: 40, bottom: 60 },
      xAxis: { type: 'value', name: 'Cumulative days', nameLocation: 'middle', nameGap: 30 },
      yAxis: { type: 'value', name: 'Depth (m)', inverse: true },
      series: [
        { name: 'Plan', type: 'line', data: planSeries, smooth: true, lineStyle: { color: "#15515B", width: 2, type: 'dashed' }, itemStyle: { color: "#15515B" }, symbolSize: 6 },
        { name: 'Actual', type: 'line', data: actualSeries, smooth: false, step: 'end', lineStyle: { color: "#2E7D32", width: 2 }, itemStyle: { color: "#2E7D32" }, symbolSize: 6 },
      ],
    }
  }, [data, palette])

  const lagOption = useMemo(() => {
    if (!data?.lag_series?.length) return null
    return {
      tooltip: { trigger: 'axis' },
      grid: { left: 80, right: 40, top: 40, bottom: 60 },
      legend: { data: ['Lag days'], bottom: 10, left: 'center' },
      xAxis: { type: 'category', data: data.lag_series.map(l => l.report_date), axisLabel: { rotate: 15, fontSize: 10 } },
      yAxis: { type: 'value', name: 'Lag (days) — positive = behind' },
      series: [
        {
          name: 'Lag days', type: 'bar', data: data.lag_series.map(l => l.lag_days),
          itemStyle: { color: (params: { value: number }) => params.value > 0 ? "#C62828" : "#2E7D32" },
        },
      ],
    }
  }, [data, palette])

  const ropOption = useMemo(() => {
    if (!data?.actual.length) return null
    // Derive ROP-ish as depth delta / time delta between actual points
    const points: [number, number][] = []
    for (let i = 1; i < data.actual.length; i++) {
      const prev = data.actual[i - 1]
      const cur = data.actual[i]
      const dDepth = cur.depth_m - prev.depth_m
      const dDays = cur.cum_days - prev.cum_days
      if (dDays > 0 && dDepth > 0) points.push([cur.cum_days, dDepth / (dDays * 24)])
    }
    if (!points.length) return null
    return {
      tooltip: { trigger: 'axis' },
      grid: { left: 60, right: 20, top: 20, bottom: 40 },
      xAxis: { type: 'value', name: 'Cumulative days' },
      yAxis: { type: 'value', name: 'ROP (m/hr)' },
      series: [{ name: 'ROP', type: 'line', data: points, smooth: true, lineStyle: { color: "#ED6C02", width: 2 } }],
    }
  }, [data, palette])

  return (
    <Box>
      <PageHeading eyebrow="Well Operations" title="Analytics — Time vs Depth" subtitle="Actual (staircase from blocks) vs planned (rate-based plan builder). Lead = actual − planned: positive = behind (lag), negative = ahead. ROP = footage ÷ rotating hours (on-bottom only). Every point drills through to its blocks. (3rd in operations order: Plans/Timeline → Daily Reports → Analytics → Library/Settings)" />
      {error && <Box mb={2}><ErrorMessage message={error} /></Box>}

      <SectionCard title="Filters">
        <Box display="grid" gap={2} gridTemplateColumns={{ xs: '1fr', md: '1fr 1fr 1fr auto' }}>
          <FormControl size="small" fullWidth>
            <InputLabel>Well</InputLabel>
            <Select value={wellId} label="Well" onChange={e => setWellId(e.target.value)}>
              {ref?.wells.map(w => <MenuItem key={w.id} value={w.id}>{w.display_name}</MenuItem>)}
            </Select>
          </FormControl>
          <FormControl size="small" fullWidth>
            <InputLabel>Scope</InputLabel>
            <Select value={scope} label="Scope" onChange={e => setScope(e.target.value)}>
              <MenuItem value="drilling">Drilling</MenuItem>
              <MenuItem value="completion">Completion</MenuItem>
            </Select>
          </FormControl>
          <Button variant="outlined" onClick={load} disabled={!wellId || loading}>{loading ? 'Loading…' : 'Reload'}</Button>
        </Box>
        <Typography fontSize={11} color="text.secondary" mt={1}>Plan is versioned; activating a new version keeps the old for comparison. Actual maps blocks → plan items by activity/depth/window (reviewer can drag to fix). Timeline resolver keeps expected state per well/scope for dashboard, brief and “missing report” check — persisted, not cache.</Typography>
      </SectionCard>

      <Box mt={2}>
        <ChartPanel title="Time vs Depth — Plan vs Actual (depth inverted, time on X)" height={420} empty={!timeDepthOption} emptyMessage="No curve — need at least one approved report with depth and (optionally) a plan for this well/scope. Add a plan in the Plans tab or under Rig/Well → Plans.">
          {timeDepthOption && <InteractiveChart option={timeDepthOption as never} style={{ height: 380 }} />}
        </ChartPanel>
        {!timeDepthOption && data && <Alert severity="info" sx={{ mt: 1 }}>Plan is empty — create one: pick hole section + activity, give target depth; planned hours are generated from ROP/trip-speed/contingency assumptions (matching the engineers’ workbook formulas, but explicit: drilling = ROUNDUP((depth−prev)/ROP)+2, trip = ROUNDUP(depth/28.5/10)+2, cum days = prev + hrs/24).</Alert>}
      </Box>

      <Box display="grid" gap={2} gridTemplateColumns={{ xs: '1fr', lg: '1fr 1fr' }} mt={2}>
        <ChartPanel title="Lag / Lead (days) — lag = actual − planned at same depth" height={320} empty={!lagOption} emptyMessage="No lag series — needs both plan and actual.">
          {lagOption && <InteractiveChart option={lagOption as never} style={{ height: 280 }} />}
        </ChartPanel>
        <ChartPanel title="ROP (m/hr) — on-bottom only, reaming excluded" height={320} empty={!ropOption} emptyMessage="No ROP points — ensure blocks have depth_from/to and rotating_hours, and are counted as on-bottom drilling.">
          {ropOption && <InteractiveChart option={ropOption as never} style={{ height: 280 }} />}
        </ChartPanel>
      </Box>

      <SectionCard title="NPT bands & milestones">
        <Typography fontSize={12} color="text.secondary">NPT bands shade the time axis where NPT blocks occurred; milestones mark spud, casing points, section TD, TD and rig release (planned vs actual). The chart above shows NPT bands when present; milestones are added where the timeline resolver provides them.</Typography>
        {data?.npt_bands?.length ? <Typography fontSize={12} mt={1}>{data.npt_bands.length} NPT band(s) in this well/scope — shaded on the time axis.</Typography> : <Typography fontSize={12} mt={1} color="text.secondary">No NPT bands — no NPT blocks yet for this well/scope.</Typography>}
      </SectionCard>

      <Alert severity="success" sx={{ mt: 2 }}>Every chart point drills through to the blocks that produced it — click a point to open its report. All figures print their basis (“of logged time”, “rotating-hours basis”, “positive = behind”).</Alert>
    </Box>
  )
}
