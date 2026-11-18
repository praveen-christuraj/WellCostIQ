import { useEffect, useMemo, useState } from 'react'
import { Link as RouterLink, useSearchParams } from 'react-router-dom'
import {
  Alert,
  Box,
  Button,
  CircularProgress,
  FormControlLabel,
  MenuItem,
  Stack,
  Switch,
  Tab,
  Tabs,
  TextField,
  Typography,
} from '@mui/material'
import {
  DescriptionOutlined,
  PictureAsPdfOutlined,
  TableChartOutlined,
  TableViewOutlined,
} from '@mui/icons-material'
import type { ColDef } from 'ag-grid-community'
import { ErrorMessage, PageHeading, Tag, type Tone } from '../../components/Common'
import { DataTable } from '../../components/DataTable'
import { OpsAiReviewPanel } from '../../components/operations/OpsAiReviewPanel'
import { SectionCard } from '../../components/ui/SectionCard'
import { StatCard } from '../../components/ui/StatCard'
import { useAuth } from '../../context/AuthContext'
import {
  auditSummaryExport,
  getWellOperationSummary,
  opsScopeReference,
  type OpsScopeReference,
  type OpsSummaryActivity,
  type OpsSummaryBreakdown,
  type OpsSummaryDay,
  type OpsSummaryPhase,
  type OpsSummarySurvey,
  type OpsWellSummary,
} from '../../lib/operations'
import {
  exportWellSummaryCsv,
  exportWellSummaryPdf,
  exportWellSummaryXlsx,
} from '../../lib/operationsPdf'
import { formatWatDateTime, WAT_LABEL } from '../../lib/time'

type SummaryTab = 'activities' | 'daily' | 'breakdown' | 'phases' | 'surveys'

const fmtNum = (v: number | string | null | undefined, suffix = ''): string => {
  if (v === null || v === undefined || v === '') return '—'
  const n = Number(v)
  if (!Number.isFinite(n)) return String(v)
  const text = Number.isInteger(n) ? n.toLocaleString() : n.toLocaleString(undefined, { maximumFractionDigits: 3 })
  return `${text}${suffix}`
}

const allocTone = (alloc: string): Tone => {
  if (alloc === 'PT') return 'success'
  if (alloc === 'NPT') return 'error'
  if (alloc === 'UPA') return 'warning'
  if (alloc === 'SP') return 'info'
  return 'neutral'
}

const statusTone = (status: string): Tone => {
  if (status === 'approved') return 'success'
  if (status === 'submitted') return 'info'
  if (status === 'rejected') return 'error'
  return 'warning'
}

export default function OperationsSummary() {
  const { can } = useAuth()
  const [params, setParams] = useSearchParams()
  const [ref, setRef] = useState<OpsScopeReference | null>(null)
  const [rig, setRig] = useState(params.get('rig') || '')
  const [well, setWell] = useState(params.get('well') || '')
  const [scope, setScope] = useState(params.get('scope') || '')
  const [from, setFrom] = useState(params.get('from') || '')
  const [to, setTo] = useState(params.get('to') || '')
  const [includeDrafts, setIncludeDrafts] = useState(params.get('drafts') !== 'false')
  const [tab, setTab] = useState<SummaryTab>('activities')
  const [summary, setSummary] = useState<OpsWellSummary | null>(null)
  const [loading, setLoading] = useState(false)
  const [exporting, setExporting] = useState<'' | 'pdf' | 'xlsx' | 'csv'>('')
  const [error, setError] = useState('')

  const mayExport = can('ops-report:export') || can('ops-analytics:export')

  useEffect(() => {
    opsScopeReference()
      .then((loaded) => {
        setRef(loaded)
        setWell((current) => {
          if (current && loaded.wells.some((w) => w.id === current)) return current
          const filtered = rig ? loaded.wells.filter((w) => w.rig_id === rig) : loaded.wells
          return filtered[0]?.id ?? ''
        })
      })
      .catch((e) => setError((e as Error).message))
  }, []) // eslint-disable-line react-hooks/exhaustive-deps

  const wells = useMemo(
    () => (ref?.wells ?? []).filter((w) => !rig || w.rig_id === rig),
    [ref, rig],
  )

  useEffect(() => {
    const next = new URLSearchParams()
    if (rig) next.set('rig', rig)
    if (well) next.set('well', well)
    if (scope) next.set('scope', scope)
    if (from) next.set('from', from)
    if (to) next.set('to', to)
    if (!includeDrafts) next.set('drafts', 'false')
    setParams(next, { replace: true })
  }, [rig, well, scope, from, to, includeDrafts, setParams])

  useEffect(() => {
    if (!well) {
      setSummary(null)
      return
    }
    let active = true
    setLoading(true)
    setError('')
    getWellOperationSummary({
      well_id: well,
      scope: scope || undefined,
      from: from || undefined,
      to: to || undefined,
      include_drafts: includeDrafts,
    })
      .then((res) => {
        if (active) setSummary(res)
      })
      .catch((e) => {
        if (active) setError((e as Error).message)
      })
      .finally(() => {
        if (active) setLoading(false)
      })
    return () => {
      active = false
    }
  }, [well, scope, from, to, includeDrafts])

  const handleExport = async (kind: 'pdf' | 'xlsx' | 'csv') => {
    if (!summary || exporting) return
    setExporting(kind)
    setError('')
    try {
      if (kind === 'pdf') await exportWellSummaryPdf(summary)
      else if (kind === 'xlsx') await exportWellSummaryXlsx(summary)
      else await exportWellSummaryCsv(summary, tab)
    } catch (e) {
      setError((e as Error).message)
    } finally {
      setExporting('')
    }
  }

  const activityCols = useMemo<ColDef<OpsSummaryActivity>[]>(
    () => [
      { field: 'line_no', headerName: '#', minWidth: 68, maxWidth: 82 },
      { field: 'report_date', headerName: 'DATE', minWidth: 112 },
      { field: 'scope', headerName: 'SCOPE', minWidth: 105 },
      {
        field: 'report_no',
        headerName: 'REPORT',
        minWidth: 115,
        valueGetter: (p) => (p.data ? `${p.data.report_type} ${p.data.report_no || '—'}` : ''),
      },
      {
        field: 'report_status',
        headerName: 'STATUS',
        minWidth: 110,
        cellRenderer: (p: { value: string }) => <Tag tone={statusTone(p.value)}>{p.value}</Tag>,
      },
      { field: 'start_wat', headerName: 'FROM (WAT)', minWidth: 145 },
      { field: 'end_wat', headerName: 'TO (WAT)', minWidth: 145 },
      { field: 'duration_hours', headerName: 'HRS', minWidth: 85, valueFormatter: (p) => fmtNum(p.value) },
      { field: 'cum_days', headerName: 'CUM DAYS', minWidth: 102, valueFormatter: (p) => fmtNum(p.value) },
      { field: 'hole_section', headerName: 'SECTION', minWidth: 115 },
      { field: 'phase_code', headerName: 'PHASE', minWidth: 95 },
      { field: 'activity_code', headerName: 'ACTIVITY', minWidth: 160 },
      { field: 'classification', headerName: 'CLASS', minWidth: 98 },
      {
        field: 'allocation',
        headerName: 'ALLOC',
        minWidth: 92,
        cellRenderer: (p: { value: string }) => <Tag tone={allocTone(p.value)}>{p.value}</Tag>,
      },
      { field: 'responsible_party', headerName: 'AGENCY / VENDOR', minWidth: 150 },
      { field: 'depth_from_m', headerName: 'MD FROM (M)', minWidth: 115, valueFormatter: (p) => fmtNum(p.value) },
      { field: 'depth_to_m', headerName: 'MD TO (M)', minWidth: 112, valueFormatter: (p) => fmtNum(p.value) },
      { field: 'tvd_from_m', headerName: 'TVD FROM (M)', minWidth: 118, valueFormatter: (p) => fmtNum(p.value) },
      { field: 'tvd_to_m', headerName: 'TVD TO (M)', minWidth: 115, valueFormatter: (p) => fmtNum(p.value) },
      { field: 'bit_depth_m', headerName: 'BIT (M)', minWidth: 100, valueFormatter: (p) => fmtNum(p.value) },
      { field: 'footage_m', headerName: 'FOOTAGE (M)', minWidth: 112, valueFormatter: (p) => fmtNum(p.value) },
      { field: 'rop_m_per_hr', headerName: 'ROP (M/H)', minWidth: 105, valueFormatter: (p) => fmtNum(p.value) },
      { field: 'mud_weight_ppg', headerName: 'MW (PPG)', minWidth: 100, valueFormatter: (p) => fmtNum(p.value) },
      { field: 'npt_code', headerName: 'NPT CODE', minWidth: 140 },
      { field: 'reason', headerName: 'REASON', minWidth: 180 },
      { field: 'narrative', headerName: 'OPERATION DESCRIPTION', minWidth: 320, flex: 2 },
      {
        headerName: 'ACTIONS',
        minWidth: 95,
        sortable: false,
        cellRenderer: (p: { data?: OpsSummaryActivity }) =>
          p.data ? (
            <Button component={RouterLink} to={`/operations/reports/${p.data.report_id}`} size="small">
              Report
            </Button>
          ) : null,
      },
    ],
    [],
  )

  const dailyCols = useMemo<ColDef<OpsSummaryDay>[]>(
    () => [
      { field: 'report_date', headerName: 'DATE', minWidth: 115 },
      { field: 'scope', headerName: 'SCOPE', minWidth: 105 },
      {
        field: 'report_no',
        headerName: 'REPORT',
        minWidth: 118,
        valueGetter: (p) => (p.data ? `${p.data.report_type} ${p.data.report_no || '—'}` : ''),
      },
      { field: 'day_number', headerName: 'DAY #', minWidth: 82, valueFormatter: (p) => fmtNum(p.value) },
      { field: 'dfs_days', headerName: 'DFS (D)', minWidth: 92, valueFormatter: (p) => fmtNum(p.value) },
      {
        field: 'status',
        headerName: 'STATUS',
        minWidth: 130,
        cellRenderer: (p: { data?: OpsSummaryDay }) =>
          p.data ? (
            <Stack direction="row" gap={0.5} alignItems="center">
              <Tag tone={statusTone(p.data.status)}>{p.data.status}</Tag>
              {p.data.reopened && <Tag tone="warning">Reopened</Tag>}
            </Stack>
          ) : null,
      },
      { field: 'hole_section', headerName: 'SECTION', minWidth: 115 },
      { field: 'depth_start_m', headerName: 'START MD (M)', minWidth: 120, valueFormatter: (p) => fmtNum(p.value) },
      { field: 'depth_end_m', headerName: 'END MD (M)', minWidth: 115, valueFormatter: (p) => fmtNum(p.value) },
      { field: 'tvd_start_m', headerName: 'START TVD (M)', minWidth: 122, valueFormatter: (p) => fmtNum(p.value) },
      { field: 'tvd_m', headerName: 'END TVD (M)', minWidth: 118, valueFormatter: (p) => fmtNum(p.value) },
      { field: 'bit_depth_m', headerName: 'BIT (M)', minWidth: 102, valueFormatter: (p) => fmtNum(p.value) },
      { field: 'progress_m', headerName: 'PROGRESS (M)', minWidth: 118, valueFormatter: (p) => fmtNum(p.value) },
      { field: 'rotating_hours', headerName: 'ROT HRS', minWidth: 98, valueFormatter: (p) => fmtNum(p.value) },
      { field: 'rop_m_per_hr', headerName: 'ROP (M/H)', minWidth: 105, valueFormatter: (p) => fmtNum(p.value) },
      { field: 'mud_type', headerName: 'MUD', minWidth: 105 },
      { field: 'mud_weight_ppg', headerName: 'MW (PPG)', minWidth: 100, valueFormatter: (p) => fmtNum(p.value) },
      { field: 'last_casing', headerName: 'LAST CASING', minWidth: 155 },
      { field: 'pob_count', headerName: 'POB', minWidth: 80, valueFormatter: (p) => fmtNum(p.value) },
      { field: 'logged_hours', headerName: 'LOGGED HRS', minWidth: 110, valueFormatter: (p) => fmtNum(p.value) },
      { field: 'pt_hours', headerName: 'PT HRS', minWidth: 92, valueFormatter: (p) => fmtNum(p.value) },
      { field: 'upa_hours', headerName: 'UPA HRS', minWidth: 95, valueFormatter: (p) => fmtNum(p.value) },
      { field: 'npt_hours', headerName: 'NPT HRS', minWidth: 95, valueFormatter: (p) => fmtNum(p.value) },
      { field: 'productive_pct', headerName: 'PROD %', minWidth: 95, valueFormatter: (p) => (p.value != null ? `${p.value}%` : '—') },
      { field: 'operation_summary', headerName: '24-HR OPERATION SUMMARY', minWidth: 280, flex: 2 },
      { field: 'forward_plan', headerName: '24-HR FORECAST', minWidth: 240 },
      {
        headerName: 'ACTIONS',
        minWidth: 92,
        sortable: false,
        cellRenderer: (p: { data?: OpsSummaryDay }) =>
          p.data ? (
            <Button component={RouterLink} to={`/operations/reports/${p.data.report_id}`} size="small">
              Open
            </Button>
          ) : null,
      },
    ],
    [],
  )

  const breakdownCols = useMemo<ColDef<OpsSummaryBreakdown>[]>(
    () => [
      { field: 'classification', headerName: 'CLASSIFICATION', minWidth: 130 },
      {
        field: 'allocation',
        headerName: 'ALLOCATION',
        minWidth: 115,
        cellRenderer: (p: { value: string }) => <Tag tone={allocTone(p.value)}>{p.value}</Tag>,
      },
      { field: 'responsible_party', headerName: 'AGENCY / VENDOR', minWidth: 185 },
      { field: 'code', headerName: 'CODE', minWidth: 185 },
      { field: 'cause_code', headerName: 'CAUSE', minWidth: 135 },
      { field: 'events', headerName: 'EVENTS', minWidth: 95 },
      { field: 'hours', headerName: 'HOURS', minWidth: 105, valueFormatter: (p) => fmtNum(p.value) },
      { field: 'days', headerName: 'DAYS', minWidth: 98, valueFormatter: (p) => fmtNum(p.value) },
      { field: 'pct_of_total', headerName: '% TOTAL', minWidth: 100, valueFormatter: (p) => `${p.value ?? 0}%` },
      {
        field: 'pct_of_npt',
        headerName: '% NPT',
        minWidth: 95,
        valueFormatter: (p) => (p.data?.allocation === 'NPT' ? `${p.value ?? 0}%` : '—'),
      },
      { field: 'sample_reason', headerName: 'SAMPLE REASON / OPERATION', minWidth: 280, flex: 2 },
    ],
    [],
  )

  const phaseCols = useMemo<ColDef<OpsSummaryPhase>[]>(
    () => [
      { field: 'phase', headerName: 'PHASE', minWidth: 185 },
      { field: 'hole_section', headerName: 'HOLE SECTION', minWidth: 150 },
      { field: 'events', headerName: 'BLOCKS', minWidth: 95 },
      { field: 'total_hours', headerName: 'TOTAL HRS', minWidth: 110, valueFormatter: (p) => fmtNum(p.value) },
      { field: 'total_days', headerName: 'DAYS', minWidth: 95, valueFormatter: (p) => fmtNum(p.value) },
      { field: 'pt_hours', headerName: 'PT HRS', minWidth: 95, valueFormatter: (p) => fmtNum(p.value) },
      { field: 'upa_hours', headerName: 'UPA HRS', minWidth: 98, valueFormatter: (p) => fmtNum(p.value) },
      { field: 'npt_hours', headerName: 'NPT HRS', minWidth: 98, valueFormatter: (p) => fmtNum(p.value) },
      { field: 'sp_hours', headerName: 'SP HRS', minWidth: 95, valueFormatter: (p) => fmtNum(p.value) },
      { field: 'productive_pct', headerName: 'PROD %', minWidth: 100, valueFormatter: (p) => `${p.value ?? 0}%` },
      { field: 'max_md_m', headerName: 'MAX MD (M)', minWidth: 118, valueFormatter: (p) => fmtNum(p.value) },
      { field: 'max_tvd_m', headerName: 'MAX TVD (M)', minWidth: 120, valueFormatter: (p) => fmtNum(p.value) },
      { field: 'footage_m', headerName: 'FOOTAGE (M)', minWidth: 118, valueFormatter: (p) => fmtNum(p.value) },
    ],
    [],
  )

  const surveyCols = useMemo<ColDef<OpsSummarySurvey>[]>(
    () => [
      { field: 'report_date', headerName: 'DATE', minWidth: 115 },
      { field: 'report_no', headerName: 'REPORT #', minWidth: 105 },
      { field: 'scope', headerName: 'SCOPE', minWidth: 105 },
      { field: 'md_m', headerName: 'MD (M)', minWidth: 115, valueFormatter: (p) => fmtNum(p.value) },
      { field: 'tvd_m', headerName: 'TVD (M)', minWidth: 115, valueFormatter: (p) => fmtNum(p.value) },
      { field: 'inc_deg', headerName: 'INC (°)', minWidth: 100, valueFormatter: (p) => fmtNum(p.value) },
      { field: 'azi_deg', headerName: 'AZIMUTH (°)', minWidth: 115, valueFormatter: (p) => fmtNum(p.value) },
      { field: 'ns_m', headerName: 'N/S (M)', minWidth: 105, valueFormatter: (p) => fmtNum(p.value) },
      { field: 'ew_m', headerName: 'E/W (M)', minWidth: 105, valueFormatter: (p) => fmtNum(p.value) },
      { field: 'vsec_m', headerName: 'V. SEC (M)', minWidth: 110, valueFormatter: (p) => fmtNum(p.value) },
      { field: 'dls_deg_per_30m', headerName: 'DLS (°/30M)', minWidth: 118, valueFormatter: (p) => fmtNum(p.value) },
      { field: 'tool', headerName: 'TOOL', minWidth: 120 },
      {
        headerName: 'ACTIONS',
        minWidth: 92,
        sortable: false,
        cellRenderer: (p: { data?: OpsSummarySurvey }) =>
          p.data ? (
            <Button component={RouterLink} to={`/operations/reports/${p.data.report_id}`} size="small">
              Report
            </Button>
          ) : null,
      },
    ],
    [],
  )

  const k = summary?.kpis

  return (
    <Box display="grid" gap={2.5}>
      <PageHeading
        eyebrow="Well Operations"
        title="Well Operation Summary"
        subtitle={`Complete multi-day cumulative drilling and completion summary for a well — depths (MD & TVD), bit progress, ROP, PT/UPA/NPT/SP breakdown, chronological operations log and directional surveys in ${WAT_LABEL}.`}
        meta={
          summary ? (
            <>
              <Tag tone="info">{summary.timezone_label}</Tag>
              <Tag tone="neutral">{summary.scope_label}</Tag>
              {summary.first_report_date && summary.last_report_date && (
                <Tag tone="neutral">
                  {summary.first_report_date} → {summary.last_report_date}
                </Tag>
              )}
              <Typography variant="caption" color="text.secondary">
                Compiled {formatWatDateTime(summary.generated_at)}
              </Typography>
            </>
          ) : undefined
        }
        action={
          <>
            <Button component={RouterLink} to="/operations/reports" variant="outlined" startIcon={<DescriptionOutlined />}>
              Daily reports
            </Button>
            {mayExport && (
              <>
                <Button
                  variant="outlined"
                  startIcon={exporting === 'csv' ? <CircularProgress size={14} /> : <TableChartOutlined />}
                  disabled={!summary || !!exporting || (!summary.activities.length && !summary.daily_rollup.length)}
                  onClick={() => void handleExport('csv')}
                >
                  Export CSV
                </Button>
                <Button
                  variant="outlined"
                  startIcon={exporting === 'xlsx' ? <CircularProgress size={14} /> : <TableViewOutlined />}
                  disabled={!summary || !!exporting || (!summary.activities.length && !summary.daily_rollup.length)}
                  onClick={() => void handleExport('xlsx')}
                >
                  Export Excel (.xlsx)
                </Button>
                <Button
                  variant="contained"
                  startIcon={exporting === 'pdf' ? <CircularProgress size={14} color="inherit" /> : <PictureAsPdfOutlined />}
                  disabled={!summary || !!exporting || (!summary.activities.length && !summary.daily_rollup.length)}
                  onClick={() => void handleExport('pdf')}
                >
                  Export PDF
                </Button>
              </>
            )}
          </>
        }
      />

      <SectionCard
        title="Well & Period Selection"
        subtitle="Select a well and optional scope or date window to compile its complete multi-day operational history."
      >
        <Box
          display="grid"
          gap={1.5}
          alignItems="center"
          gridTemplateColumns={{ xs: '1fr', sm: 'repeat(2,minmax(0,1fr))', lg: 'repeat(6,minmax(0,1fr))' }}
        >
          <TextField
            select
            size="small"
            label="Rig"
            value={rig}
            onChange={(e) => {
              const nextRig = e.target.value
              setRig(nextRig)
              const nextWells = (ref?.wells ?? []).filter((w) => !nextRig || w.rig_id === nextRig)
              if (!nextWells.some((w) => w.id === well)) setWell(nextWells[0]?.id ?? '')
            }}
          >
            <MenuItem value="">All rigs</MenuItem>
            {ref?.rigs.map((r) => (
              <MenuItem key={r.id} value={r.id}>
                {r.display_name}
              </MenuItem>
            ))}
          </TextField>

          <TextField
            select
            size="small"
            label="Well"
            value={well}
            disabled={!wells.length}
            onChange={(e) => setWell(e.target.value)}
          >
            {wells.map((w) => (
              <MenuItem key={w.id} value={w.id}>
                {w.display_name}
              </MenuItem>
            ))}
          </TextField>

          <TextField select size="small" label="Scope" value={scope} onChange={(e) => setScope(e.target.value)}>
            <MenuItem value="">Drilling & Completion</MenuItem>
            <MenuItem value="drilling">Drilling</MenuItem>
            <MenuItem value="completion">Completion</MenuItem>
          </TextField>

          <TextField
            size="small"
            type="date"
            label="From date"
            InputLabelProps={{ shrink: true }}
            value={from}
            onChange={(e) => setFrom(e.target.value)}
          />
          <TextField
            size="small"
            type="date"
            label="To date"
            InputLabelProps={{ shrink: true }}
            value={to}
            onChange={(e) => setTo(e.target.value)}
          />
          <FormControlLabel
            control={<Switch size="small" checked={includeDrafts} onChange={(_, v) => setIncludeDrafts(v)} />}
            label={<Typography fontSize={12.5}>Include draft reports</Typography>}
          />
        </Box>
      </SectionCard>

      <ErrorMessage message={error} />

      {!well && !loading && (
        <Alert severity="info">
          No wells are registered yet, or no well is selected. Choose a well above to compile its multi-day Well Operation Summary.
        </Alert>
      )}

      {loading && (
        <Box display="flex" alignItems="center" gap={1.5} py={4} justifyContent="center">
          <CircularProgress size={22} />
          <Typography color="text.secondary" fontSize={13}>
            Compiling multi-day well operation summary…
          </Typography>
        </Box>
      )}

      {summary && k && !loading && (
        <>
          <Box
            display="grid"
            gap={1.5}
            gridTemplateColumns={{ xs: '1fr', sm: 'repeat(2,minmax(0,1fr))', lg: 'repeat(6,minmax(0,1fr))' }}
          >
            <StatCard
              label="Reports & Logged Time"
              value={`${k.total_reports} d · ${fmtNum(k.total_logged_hours, ' h')}`}
              hint={`${k.approved_reports} appr · ${k.submitted_reports} sub · ${k.draft_reports} draft (${k.total_blocks} blocks)`}
            />
            <StatCard
              label="Current Measured Depth"
              value={k.current_md_m != null ? fmtNum(k.current_md_m, ' m MD') : '—'}
              hint={`Start ${fmtNum(k.start_md_m, ' m')} · Max ${fmtNum(k.max_md_m, ' m')} · Auth ${fmtNum(k.authorized_md_m, ' m')}`}
            />
            <StatCard
              label="True Vertical Depth"
              value={k.current_tvd_m != null ? fmtNum(k.current_tvd_m, ' m TVD') : '—'}
              hint={`Max TVD ${fmtNum(k.max_tvd_m, ' m')} · Bit ${fmtNum(k.latest_bit_depth_m, ' m')}`}
            />
            <StatCard
              label="Footage & Avg ROP"
              value={fmtNum(k.total_footage_m, ' m')}
              hint={`Avg ROP ${fmtNum(k.avg_rop_m_per_hr, ' m/h')} · Rot ${fmtNum(k.total_rotating_hours, ' h')}`}
            />
            <StatCard
              label="Productive Time (PT)"
              value={`${fmtNum(k.pt_hours, ' h')} (${k.productive_pct}%)`}
              tone="positive"
              hint={`UPA ${fmtNum(k.upa_hours, ' h')} (${k.upa_pct}%) · SP ${fmtNum(k.sp_hours, ' h')}`}
            />
            <StatCard
              label="Non-Productive (NPT)"
              value={`${fmtNum(k.npt_hours, ' h')} (${k.npt_pct}%)`}
              tone={k.npt_hours > 0 ? 'warning' : 'default'}
              hint={
                k.planned_days != null
                  ? `Logged ${fmtNum(k.total_logged_days, ' d')} vs plan ${fmtNum(k.planned_days, ' d')}`
                  : `${fmtNum(k.total_logged_days, ' d')} logged · Unacc ${fmtNum(k.unaccounted_hours, ' h')}`
              }
            />
          </Box>

          <SectionCard
            title={`${summary.well_code} — ${summary.well_name}`}
            subtitle={[
              summary.rig_code ? `Rig: ${summary.rig_code}` : '',
              summary.block_text ? `Block: ${summary.block_text}` : '',
              summary.field_site ? `Field/Site: ${summary.field_site}` : '',
              summary.customer ? `Operator: ${summary.customer}` : '',
              summary.uwi ? `UWI: ${summary.uwi}` : '',
              summary.datum ? `Datum: ${summary.datum}` : '',
              summary.spud_date ? `Spud: ${summary.spud_date}` : '',
            ]
              .filter(Boolean)
              .join(' · ') || 'Wellbore configuration & latest daily report state'}
          >
            <Box
              display="grid"
              gap={1.5}
              gridTemplateColumns={{ xs: '1fr', sm: 'repeat(2,minmax(0,1fr))', lg: 'repeat(4,minmax(0,1fr))' }}
            >
              <Box>
                <Typography variant="caption" color="text.secondary" fontWeight={700}>
                  HOLE SECTION & LAST CASING
                </Typography>
                <Typography fontSize={13} fontWeight={600}>
                  {summary.latest_hole_section || '—'} · {summary.last_casing || 'No casing shoe recorded'}
                </Typography>
              </Box>
              <Box>
                <Typography variant="caption" color="text.secondary" fontWeight={700}>
                  LATEST MUD SYSTEM & POB
                </Typography>
                <Typography fontSize={13} fontWeight={600}>
                  {summary.latest_mud || '—'}
                  {k.latest_pob != null ? ` · POB ${k.latest_pob}` : ''}
                </Typography>
              </Box>
              <Box>
                <Typography variant="caption" color="text.secondary" fontWeight={700}>
                  LATEST BHA & TRAJECTORY
                </Typography>
                <Typography fontSize={13} fontWeight={600}>
                  {summary.latest_bha || '—'}
                  {k.survey_count > 0
                    ? ` · ${k.survey_count} surveys (max inc ${fmtNum(k.max_inc_deg, '°')}, DLS ${fmtNum(k.max_dls_deg_per_30m, '°/30m')})`
                    : ''}
                </Typography>
              </Box>
              <Box>
                <Typography variant="caption" color="text.secondary" fontWeight={700}>
                  LATEST REPORTED STATUS
                </Typography>
                <Typography fontSize={13} fontWeight={600}>
                  {summary.latest_status || '—'}
                </Typography>
              </Box>
            </Box>
          </SectionCard>

          {k.total_reports === 0 ? (
            <Alert severity="info">
              No daily operation reports match the selected filter for <strong>{summary.well_code}</strong>.
              {!includeDrafts ? ' Enable “Include draft reports” or submit a report in Daily reports.' : ' Upload and extract a DDR/DCR or create a daily report first.'}
            </Alert>
          ) : (
            <SectionCard
              title="Cumulative Well Operations Ledger"
              subtitle={`All timestamps shown in ${summary.timezone_label}. Export PDF or Excel (.xlsx) above for the full multi-tab report package, or use any table’s export menu.`}
            >
              <Tabs
                value={tab}
                onChange={(_, v: SummaryTab) => setTab(v)}
                variant="scrollable"
                scrollButtons="auto"
                sx={{ mb: 2, borderBottom: 1, borderColor: 'divider' }}
              >
                <Tab value="activities" label={`Operations Log (${summary.activities.length})`} />
                <Tab value="daily" label={`Daily Rollup (${summary.daily_rollup.length})`} />
                <Tab value="breakdown" label={`PT / UPA / NPT Breakdown (${summary.pt_npt_breakdown.length})`} />
                <Tab value="phases" label={`Phase & Section Summary (${summary.phase_breakdown.length})`} />
                <Tab value="surveys" label={`Directional Surveys (${summary.surveys.length})`} />
              </Tabs>

              {tab === 'activities' && (
                <DataTable
                  rows={summary.activities}
                  columns={activityCols}
                  rowKey="id"
                  exportName={`${summary.well_code}-operations-log`}
                  searchPlaceholder="Search operation description, phase, vendor, code, reason…"
                  canExport={mayExport}
                  onExport={auditSummaryExport}
                />
              )}
              {tab === 'daily' && (
                <DataTable
                  rows={summary.daily_rollup}
                  columns={dailyCols}
                  rowKey="report_id"
                  exportName={`${summary.well_code}-daily-rollup`}
                  searchPlaceholder="Search date, report #, hole section, mud, 24-hr summary…"
                  canExport={mayExport}
                  onExport={auditSummaryExport}
                />
              )}
              {tab === 'breakdown' && (
                <DataTable
                  rows={summary.pt_npt_breakdown}
                  columns={breakdownCols}
                  rowKey={(r) => `${r.classification}-${r.allocation}-${r.responsible_party}-${r.code}-${r.cause_code}`}
                  exportName={`${summary.well_code}-pt-npt-breakdown`}
                  searchPlaceholder="Search agency, vendor, NPT code, cause, allocation…"
                  canExport={mayExport}
                  onExport={auditSummaryExport}
                />
              )}
              {tab === 'phases' && (
                <DataTable
                  rows={summary.phase_breakdown}
                  columns={phaseCols}
                  rowKey={(r) => `${r.phase}-${r.hole_section}`}
                  exportName={`${summary.well_code}-phase-summary`}
                  searchPlaceholder="Search phase or hole section…"
                  canExport={mayExport}
                  onExport={auditSummaryExport}
                />
              )}
              {tab === 'surveys' && (
                <DataTable
                  rows={summary.surveys}
                  columns={surveyCols}
                  rowKey={(r) => `${r.report_id}-${r.md_m}-${r.tvd_m}-${r.inc_deg}`}
                  exportName={`${summary.well_code}-directional-surveys`}
                  searchPlaceholder="Search survey depth, date, report # or tool…"
                  canExport={mayExport}
                  onExport={auditSummaryExport}
                />
              )}
            </SectionCard>
          )}

          <OpsAiReviewPanel
            wellId={well}
            rigId={rig || undefined}
            scope={scope || undefined}
            dateFrom={from || undefined}
            dateTo={to || undefined}
          />
        </>
      )}
    </Box>
  )
}
