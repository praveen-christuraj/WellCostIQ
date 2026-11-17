import { useEffect, useMemo, useState } from 'react'
import {
   CloudUploadOutlined, DescriptionOutlined,
  ScheduleOutlined, SpeedOutlined,  WarningAmberRounded,
   InsightsOutlined,
} from '@mui/icons-material'
import {
  Alert, Box, Button, Chip, FormControl, InputLabel, MenuItem, Select,
  TextField, Typography, useTheme,
} from '@mui/material'
import { ChartPanel } from '../../components/ui/ChartPanel'
import { InteractiveChart } from '../../components/ui/InteractiveChart'
import { SectionCard } from '../../components/ui/SectionCard'
import { StatCard } from '../../components/ui/StatCard'
import { ErrorMessage, PageHeading } from '../../components/Common'
// DataTable reserved for upcoming table
import { useAuth } from '../../context/AuthContext'
import { useColorMode } from '../../context/ThemeContext'
import { chartPalette } from '../../designSystem'
import { opsDashboard, opsReference, type OpsDashboard, type OpsReference } from '../../lib/operations'

export default function OperationsOverview() {
  const {} = useAuth() // can reserved for future guards
  const { mode } = useColorMode()
  const theme = useTheme()
  const palette = useMemo(() => chartPalette(mode), [mode])
  const [dashboard, setDashboard] = useState<OpsDashboard | null>(null)
  const [reference, setReference] = useState<OpsReference | null>(null)
  const [_loading, setLoading] = useState(true)
  const [error, setError] = useState('')
  const [wellId, setWellId] = useState('')
  const [rigId, setRigId] = useState('')
  const [dateFrom, setDateFrom] = useState('')
  const [dateTo, setDateTo] = useState('')

  const load = async () => {
    setLoading(true); setError('')
    try {
      const [dash, ref] = await Promise.all([
        opsDashboard({ well_id: wellId || undefined, rig_id: rigId || undefined, from: dateFrom || undefined, to: dateTo || undefined }),
        reference ? Promise.resolve(reference) : opsReference(),
      ])
      setDashboard(dash)
      setReference(ref)
    } catch (e) { setError((e as Error).message) } finally { setLoading(false) }
  }

  useEffect(() => { load() }, [])
  useEffect(() => { load() }, [wellId, rigId])

  const kpis = dashboard?.kpis

  const trendOption = useMemo(() => {
    if (!dashboard?.daily_trend?.length) return null
    const dates = dashboard.daily_trend.map(d => d.date)
    return {
      tooltip: { trigger: 'axis' },
      legend: { data: ['Logged hrs', 'NPT hrs', 'Planned hrs'], bottom: 0 },
      grid: { left: 40, right: 20, top: 20, bottom: 40 },
      xAxis: { type: 'category', data: dates, axisLabel: { rotate: 0, fontSize: 10 } },
      yAxis: { type: 'value', name: 'Hours' },
      series: [
        { name: 'Logged hrs', type: 'bar', stack: 'total', data: dashboard.daily_trend.map(d => d.logged_hours), itemStyle: { color: "#15515B" } },
        { name: 'NPT hrs', type: 'bar', stack: 'total', data: dashboard.daily_trend.map(d => d.npt_hours), itemStyle: { color: "#C62828" } },
        { name: 'Planned hrs', type: 'line', data: dashboard.daily_trend.map(d => d.planned_hours), smooth: true, lineStyle: { color: "#2E7D32", width: 2 } },
      ],
    }
  }, [dashboard, palette])

  const nptCodeOption = useMemo(() => {
    if (!dashboard?.npt_by_code?.length) return null
    return {
      tooltip: { trigger: 'item', formatter: '{b}: {c} hrs ({d}%)' },
      legend: { bottom: 0, type: 'scroll' as const },
      series: [{ type: 'pie', radius: ['35%', '70%'], data: dashboard.npt_by_code.map(n => ({ name: n.code, value: n.hours })), itemStyle: { borderRadius: 6 } }],
    }
  }, [dashboard])

  const nptAgencyOption = useMemo(() => {
    if (!dashboard?.npt_by_agency?.length) return null
    return {
      tooltip: { trigger: 'axis' },
      grid: { left: 120, right: 20, top: 10, bottom: 20 },
      xAxis: { type: 'value' },
      yAxis: { type: 'category', data: dashboard.npt_by_agency.map(a => a.agency), axisLabel: { fontSize: 11 } },
      series: [{ type: 'bar', data: dashboard.npt_by_agency.map(a => a.hours), itemStyle: { color: "#ED6C02" } }],
    }
  }, [dashboard, palette])

  return (
    <Box>
      <PageHeading
        eyebrow="Well Operations" title="Well Operations"
        subtitle="Daily drilling & completion operations — reports, NPT and time-vs-depth (hours only, no cost)."
        action={
          <Box display="flex" gap={1} flexWrap="wrap">
            <Button variant="outlined" href="/operations/documents" startIcon={<CloudUploadOutlined />}>Documents</Button>
            <Button variant="outlined" href="/operations/reports" startIcon={<DescriptionOutlined />}>Reports</Button>
            <Button variant="contained" href="/operations/analytics" startIcon={<InsightsOutlined />}>Analytics</Button>
          </Box>
        }
      />

      {error && <Box mb={2}><ErrorMessage message={error}  /></Box>}

      <SectionCard title="Filters">
        <Box display="grid" gap={2} gridTemplateColumns={{ xs: '1fr', md: '1fr 1fr 1fr 1fr auto' }}>
          <FormControl size="small" fullWidth>
            <InputLabel>Well</InputLabel>
            <Select value={wellId} label="Well" onChange={e => setWellId(e.target.value)}>
              <MenuItem value="">All wells</MenuItem>
              {reference?.wells.map(w => <MenuItem key={w.id} value={w.id}>{w.display_name}</MenuItem>)}
            </Select>
          </FormControl>
          <FormControl size="small" fullWidth>
            <InputLabel>Rig</InputLabel>
            <Select value={rigId} label="Rig" onChange={e => setRigId(e.target.value)}>
              <MenuItem value="">All rigs</MenuItem>
              {reference?.rigs.map(r => <MenuItem key={r.id} value={r.id}>{r.display_name}</MenuItem>)}
            </Select>
          </FormControl>
          <TextField size="small" type="date" label="From" value={dateFrom} onChange={e => setDateFrom(e.target.value)} InputLabelProps={{ shrink: true }} />
          <TextField size="small" type="date" label="To" value={dateTo} onChange={e => setDateTo(e.target.value)} InputLabelProps={{ shrink: true }} />
          <Button variant="outlined" onClick={load}>Apply</Button>
        </Box>
      </SectionCard>

      {kpis && (
        <Box display="grid" gap={2} gridTemplateColumns={{ xs: '1fr', sm: '1fr 1fr', lg: 'repeat(4, 1fr)' }} mt={2}>
          <StatCard label="Reports" value={kpis.total_reports} hint={`${kpis.draft_reports} draft · ${kpis.approved_reports} approved · ${kpis.submitted_reports} submitted`} icon={<DescriptionOutlined />} />
          <StatCard label="Awaiting review" value={kpis.reports_awaiting_review} hint="Extracted → needs review" tone={kpis.reports_awaiting_review ? 'warning' : 'default'} icon={<WarningAmberRounded />} />
          <StatCard label="Logged hours" value={kpis.total_logged_hours.toFixed(1)} hint={`${kpis.planned_hours.toFixed(1)} planned · ${kpis.npt_hours.toFixed(1)} NPT · ${kpis.upa_hours.toFixed(1)} UPA`} icon={<ScheduleOutlined />} />
          <StatCard label="Wells coverage" value={`${kpis.wells_covered}/${kpis.wells_total}`} hint={`Avg ROP ${kpis.avg_rop ?? '—'} m/hr · NPT ${kpis.npt_pct}% · Productive ${kpis.productive_pct}%`} icon={<SpeedOutlined />} tone={kpis.data_quality_score < 70 ? 'error' : kpis.data_quality_score < 90 ? 'warning' : 'positive'} />
        </Box>
      )}

      <Box display="grid" gap={2} gridTemplateColumns={{ xs: '1fr', lg: '2fr 1fr' }} mt={2}>
        <ChartPanel title="Daily trend — logged, NPT and planned hours" height={320} empty={!trendOption} emptyMessage="No daily data yet — upload a DDR/DCR to see the trend.">
          {trendOption && <InteractiveChart option={trendOption as never} style={{ height: 300 }} />}
        </ChartPanel>
        <ChartPanel title="NPT by code (hours)" height={320} empty={!nptCodeOption} emptyMessage="No NPT yet — all planned time shows here when present.">
          {nptCodeOption && <InteractiveChart option={nptCodeOption as never} style={{ height: 300 }} />}
        </ChartPanel>
      </Box>

      <Box mt={2}>
        <ChartPanel title="NPT by responsible party (hours)" height={300} empty={!nptAgencyOption} emptyMessage="No agency split — tag NPT blocks with responsible party.">
          {nptAgencyOption && <InteractiveChart option={nptAgencyOption as never} style={{ height: 260 }} />}
        </ChartPanel>
      </Box>

      <Box mt={2} display="grid" gap={2} gridTemplateColumns={{ xs: '1fr', lg: '1fr 1fr' }}>
        <SectionCard title="Recent reports">
          {!dashboard?.recent_reports?.length ? (
            <Alert severity="info">No reports yet. Upload a DDR/DCR/D​MR PDF or Excel in Documents — the engine extracts the 24h time log, classifies Planned/UPA/NPT and computes ROP; you review before it becomes the record.</Alert>
          ) : (
            <Box>
              {dashboard.recent_reports.slice(0, 8).map(r => (
                <Box key={r.id} display="flex" alignItems="center" justifyContent="space-between" py={1} borderBottom={`1px solid ${theme.palette.divider}`}>
                  <Box>
                    <Typography fontSize={13} fontWeight={700}>{r.well_code_snapshot} — {r.report_date} <Chip size="small" label={r.scope} sx={{ ml: 1 }} /> <Chip size="small" label={r.status} color={r.status === 'approved' ? 'success' : r.status === 'submitted' ? 'info' : 'default'} sx={{ ml: 0.5 }} /></Typography>
                    <Typography fontSize={12} color="text.secondary">{r.rig_name_snapshot} · {r.report_type} {r.report_no_text} · {r.depth_end_m ? `${Number(r.depth_end_m).toFixed(0)} m` : '—'} · {r.blocks.length} blocks</Typography>
                  </Box>
                  <Button size="small" href={`/operations/reports/${r.id}`}>Open</Button>
                </Box>
              ))}
            </Box>
          )}
        </SectionCard>
        <SectionCard title="Data quality">
          <Box display="grid" gap={1.5}>
            <Box display="flex" justifyContent="space-between"><Typography fontSize={13}>Awaiting review</Typography><Typography fontSize={13} fontWeight={700}>{kpis?.reports_awaiting_review ?? 0}</Typography></Box>
            <Box display="flex" justifyContent="space-between"><Typography fontSize={13}>Unaccounted hours</Typography><Typography fontSize={13} fontWeight={700}>{kpis?.unaccounted_hours ?? 0}</Typography></Box>
            <Box display="flex" justifyContent="space-between"><Typography fontSize={13}>NPT % of logged</Typography><Typography fontSize={13} fontWeight={700}>{kpis?.npt_pct ?? 0}%</Typography></Box>
            <Box display="flex" justifyContent="space-between"><Typography fontSize={13}>Productive %</Typography><Typography fontSize={13} fontWeight={700}>{kpis?.productive_pct ?? 0}%</Typography></Box>
            <Box display="flex" justifyContent="space-between"><Typography fontSize={13}>Score</Typography><Chip label={kpis?.data_quality_score ?? 0} color={(kpis?.data_quality_score ?? 0) >= 85 ? 'success' : (kpis?.data_quality_score ?? 0) >= 60 ? 'warning' : 'error'} size="small" /></Box>
            <Alert severity="info" sx={{ mt: 1 }}>Every figure is traced to a reviewed block. A report cannot be submitted while NPT blocks miss a code or a block overlaps another — fix is shown inline.</Alert>
          </Box>
        </SectionCard>
      </Box>

      <Box mt={2}>
        <SectionCard title="How it works — the operations spine">
          <Typography fontSize={13} color="text.secondary" paragraph>
            Upload a DDR/DCR/DMR/RMR (PDF or Excel) into the well/scope directory → extraction drafts the 24h time log with classification (Planned/UPA/NPT), allocation (PT/NPT/UPA/SP), productivity, depth/ROP and confidence → you verify in the review workspace (PDF on left, parsed fields on right, provenance chips and findings) → submit → approve. The dashboard, time-vs-depth chart, lead/lag and ROP are all computed from approved blocks — no re-typing.
          </Typography>
          <Box display="flex" gap={1} flexWrap="wrap">
            <Chip label="Rig-scoped" size="small" />
            <Chip label="Well-scoped" size="small" />
            <Chip label="Drilling / Completion scoped" size="small" />
            <Chip label="Draft until verified" size="small" color="warning" />
            <Chip label="RBAC-separated from costing" size="small" color="info" />
          </Box>
        </SectionCard>
      </Box>
    </Box>
  )
}
