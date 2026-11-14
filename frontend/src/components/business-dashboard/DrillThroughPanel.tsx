import { useEffect, useMemo, useState } from 'react'
import { Link as RouterLink } from 'react-router-dom'
import type { EChartsOption } from 'echarts'
import {
  Box, Button, CircularProgress, Divider, Paper, Table, TableBody, TableCell, TableHead, TableRow,
  Typography, useTheme,
} from '@mui/material'
import { InsightsOutlined, OpenInNewRounded, PictureAsPdfOutlined } from '@mui/icons-material'
import { ErrorMessage, PanelDialog, Tag } from '../Common'
import { planLabel, planStatusTone, trackingLabel, wellStatusTone } from '../../lib/rigWell'
import { InteractiveChart } from '../ui/InteractiveChart'
import { ExportReportDialog } from '../ui/ExportReportDialog'
import type { ReportFigure, ReportDocument, ReportSection } from '../../lib/reportPdf'
import { useAuth } from '../../context/AuthContext'
import { useColorMode } from '../../context/ThemeContext'
import { api, body } from '../../lib/api'
import { chartPalette } from '../../designSystem'
import {
  AFE_STATUS_LABELS, CLASSIFICATION_TONES, dashboardQuery, decimal, displayDate, money, percent,
  type DashboardFilters, type DashboardDaySheet, type DashboardWellDetail, type Money,
} from '../../lib/businessDashboard'
import { formatDepthMeters } from '../../lib/units'

const SHEET_STATUS_LABELS: Record<string, string> = { draft: 'Draft', submitted: 'Submitted' }

function SheetStatus({ status }: { status: string }) {
  return <Tag tone={status === 'submitted' ? 'success' : 'info'}>
    {SHEET_STATUS_LABELS[status] ?? status}
  </Tag>
}

function Stat({ label, value, hint }: { label: string; value: string; hint?: string }) {
  return <Box sx={{ minWidth: 0 }}>
    <Typography color="text.secondary" fontSize={10} fontWeight={800} letterSpacing={.6} textTransform="uppercase" noWrap>{label}</Typography>
    <Typography fontSize={16} fontWeight={800} sx={{ mt: .35, overflowWrap: 'anywhere' }} noWrap title={value}>{value}</Typography>
    {hint && <Typography color="text.secondary" fontSize={10.5} noWrap title={hint}>{hint}</Typography>}
  </Box>
}

function BalanceValue({ value, currency }: { value: Money; currency: string }) {
  const negative = value !== null && Number(value) < 0
  return <Typography component="span" fontSize={12.5} fontWeight={700} color={negative ? 'error.main' : 'text.primary'}>
    {money(value, currency)}
  </Typography>
}

export function DrillThroughPanel({ wellId, filters, onClose }: {
  wellId: string
  filters: DashboardFilters
  onClose: () => void
}) {
  const { can } = useAuth()
  const { mode } = useColorMode()
  const theme = useTheme()
  const palette = useMemo(() => chartPalette(mode), [mode])
  const [detail, setDetail] = useState<DashboardWellDetail | null>(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState('')
  const [exportOpen, setExportOpen] = useState(false)

  // The panel is keyed to the well that was clicked. A late response for the
  // previously opened well is dropped, and the detail is cleared the moment the
  // selection changes, so the header, the KPI strip and the charts can never
  // show one well's figures under another well's name.
  useEffect(() => {
    if (!wellId) return
    let active = true
    setLoading(true)
    setError('')
    setDetail(null)
    const query = dashboardQuery(filters)
    api<DashboardWellDetail>(`/dashboard/business/wells/${wellId}${query ? `?${query}` : ''}`)
      .then(result => {
        if (!active) return
        if (result.well.well_id !== wellId) {
          setError('The drill-through returned a different well. Close the panel and select the well again.')
          return
        }
        setDetail(result)
      })
      .catch(caught => { if (active) setError(caught instanceof Error ? caught.message : 'The well detail could not be loaded') })
      .finally(() => { if (active) setLoading(false) })
    return () => { active = false }
    // The panel reloads when the well, dashboard filters or currency change.
  }, [wellId, filters.from, filters.to, filters.currency, filters.includeDraft]) // eslint-disable-line react-hooks/exhaustive-deps

  const currency = detail?.well.currency || filters.currency
  const classification = useMemo(() => (detail?.classification ?? []).filter(row => Number(row.days ?? 0) > 0 || Number(row.actual ?? 0) > 0), [detail])
  const sectionRows = detail?.sections ?? []
  const activityRows = detail?.activities ?? []

  const dailyOption: EChartsOption = useMemo(() => {
    const rows = detail?.daily ?? []
    return {
      animation: false,
      grid: { left: 12, right: 16, top: 30, bottom: 26, containLabel: true },
      legend: { top: 0, textStyle: { color: theme.palette.text.secondary }, itemWidth: 12, itemHeight: 8 },
      tooltip: {
        trigger: 'axis',
        valueFormatter: value => money(String(value ?? 0), currency),
      },
      xAxis: {
        type: 'category',
        data: rows.map(row => row.cost_date.slice(5)),
        axisLabel: { color: theme.palette.text.secondary, fontSize: 10.5 },
        axisLine: { lineStyle: { color: theme.palette.divider } },
      },
      yAxis: {
        type: 'value',
        axisLabel: { color: theme.palette.text.secondary, fontSize: 10.5 },
        splitLine: { lineStyle: { color: theme.palette.divider } },
      },
      series: [
        {
          name: 'Daily actual', type: 'bar', barMaxWidth: 14,
          itemStyle: { color: palette.series[0], opacity: .65 }, data: rows.map(row => Number(row.actual)),
        },
        {
          name: 'Cumulative actual', type: 'line', smooth: true, symbol: 'none',
          itemStyle: { color: palette.actual }, lineStyle: { width: 2.2, color: palette.actual },
          areaStyle: { color: `${palette.actual}20` }, data: rows.map(row => Number(row.cumulative)),
        },
      ],
    }
  }, [detail, currency, theme, palette])

  const timeOption: EChartsOption = useMemo(() => {
    const colors: Record<string, string> = {
      Planned: palette.series[2],
      UPA: palette.series[1],
      NPT: palette.series[3],
    }
    return {
      animation: false,
      tooltip: { trigger: 'item', valueFormatter: value => `${Number(value ?? 0).toLocaleString()} days` },
      legend: { bottom: 0, textStyle: { color: theme.palette.text.secondary }, itemWidth: 12, itemHeight: 8 },
      series: [{
        type: 'pie',
        radius: ['48%', '72%'],
        center: ['50%', '42%'],
        label: { color: theme.palette.text.primary, fontSize: 10.5, formatter: '{b}\n{c} d' },
        itemStyle: { borderColor: theme.palette.background.paper, borderWidth: 2 },
        data: classification.map(row => ({
          name: row.key, value: Number(row.days ?? 0), itemStyle: { color: colors[row.key] ?? palette.series[0] },
        })),
      }],
    }
  }, [classification, theme, palette])

  /**
   * The drill-through document: the well's own figures. Everything here is drawn
   * from `detail`, the payload this panel already shows, so the exported page and
   * the panel cannot disagree. The two charts are captured from their live scene.
   */
  const buildDocument = (options: {
    figures: Map<string, { dataUrl: string; width: number; height: number; title?: string; caption?: string }>
    includeFigures: boolean
    includeTables: boolean
    orientation: 'landscape' | 'portrait'
  }): ReportDocument => {
    const figure = (key: string, title: string, caption: string): ReportFigure => {
      const capture = options.figures.get(key)
      return {
        title,
        caption,
        dataUrl: capture?.dataUrl ?? '',
        width: capture?.width ?? 0,
        height: capture?.height ?? 0,
      }
    }
    const well = detail?.well
    const sections: ReportSection[] = [{
      title: 'Well position',
      subtitle: well ? `${well.rig_code} ${well.rig_name} · ${well.well_location || 'Location not recorded'} · block ${well.block || '—'}` : undefined,
      kpis: well ? [
        { label: 'Planned days', value: decimal(well.planned_days, 2), hint: `Drilling ${decimal(well.drilling_planned_days, 2)}${well.completion_planned_days ? ` · Completion ${decimal(well.completion_planned_days, 2)}` : ''}` },
        { label: 'Actual days', value: decimal(well.actual_days, 3), hint: `${displayDate(well.first_cost_date)} → ${displayDate(well.last_cost_date)}` },
        { label: 'Cost sheets', value: decimal(well.sheets), hint: `${decimal(well.recorded_days)} recording days · ${decimal(well.draft_sheets)} draft` },
        { label: 'NPT / UPA days', value: `${decimal(well.npt_days, 3)} / ${decimal(well.upa_days, 3)}` },
        { label: 'AFE amount', value: money(well.afe_amount, currency), hint: well.afe_count ? `${well.afe_count} AFE` : 'No active AFE' },
        { label: 'Actual cost', value: money(well.actual_amount, currency), hint: `${percent(well.utilisation_percent)} of the effective AFE` },
        { label: 'AFE balance', value: money(well.afe_balance, currency), hint: well.over_budget ? 'Over the effective AFE' : 'Remaining against the effective AFE' },
        { label: 'Depth progress', value: percent(well.depth_progress_percent), hint: `${decimal(well.actual_depth, 0)} of ${decimal(well.planned_depth, 0)} m` },
      ] : [],
    }]
    if (options.includeFigures) {
      sections.push({
        title: 'Visuals as shown',
        figures: [
          figure('drill-daily', 'Daily actual and cumulative cost', `Every saved sheet in the current range, in ${currency}.`),
          figure('drill-time', 'Recorded time split', 'Classified operational hours ÷ 24 by classification.'),
        ],
      })
    }
    if (options.includeTables && detail) {
      sections.push({
        title: 'Cost group reconciliation',
        tables: [{
          head: ['Cost group', 'AFE planned', `Actual (${currency})`, 'Balance'],
          numeric: [1, 2, 3],
          body: detail.cost_groups.map(row => [row.label, money(row.planned, currency), money(row.actual, currency), money(row.balance, currency)]),
        }],
      })
      if (detail.sections.length) {
        sections.push({
          title: 'Hole sections and depth',
          tables: [{
            head: ['Section', 'Planned depth (m)', 'Actual depth (m)', 'Planned days', 'Cost days', `Actual (${currency})`, 'Reached'],
            numeric: [1, 2, 3, 4, 5],
            body: detail.sections.map(row => [
              `${row.section_code} — ${row.section_name}${row.scope === 'completion' ? ' (completion)' : ''}`,
              row.from_depth != null ? `${decimal(row.from_depth, 2)} – ${decimal(row.to_depth, 2)}` : '—',
              row.actual_depth != null ? decimal(row.actual_depth, 2) : '—',
              decimal(row.planned_days, 2), decimal(row.active_days), money(row.amount, currency), row.reached ? 'Reached' : 'Not reached',
            ]),
          }],
        })
      }
      if (detail.activities.length) {
        sections.push({
          title: 'Activities recorded',
          tables: [{
            head: ['Activity', 'Class', 'Days', `Actual (${currency})`, 'Share'],
            numeric: [2, 3, 4],
            body: detail.activities.map(row => [
              `${row.activity_code || '—'} ${row.activity_name}`.trim(), row.classification,
              decimal(row.active_days), money(row.amount, currency), percent(row.share),
            ]),
          }],
        })
      }
      sections.push({
        title: 'AFE positions',
        tables: [{
          head: ['AFE', 'Type', 'Status', `AFE amount (${currency})`, 'SOW adjusted', `Actual (${currency})`, 'Balance', 'Actual days'],
          numeric: [3, 4, 5, 6, 7],
          body: detail.afes.map(row => [
            `${row.afe_code} — ${row.afe_name}`, row.afe_type, AFE_STATUS_LABELS[row.status] ?? row.status,
            money(row.afe_amount, currency), money(row.sow_adjusted_amount, currency), money(row.actual_amount, currency),
            money(row.afe_balance, currency), decimal(row.actual_days, 3),
          ]),
        }],
      })
      if (detail.sheets.length) {
        sections.push({
          title: 'Daily cost sheets',
          tables: [{
            head: ['Cost date', 'AFE', 'Status', 'Actual depth (m)', `Total (${currency})`, 'NPT', 'UPA'],
            numeric: [3, 4, 5, 6],
            body: detail.sheets.map(row => [
              displayDate(row.cost_date), row.afe_code || '—', SHEET_STATUS_LABELS[row.status] ?? row.status,
              row.actual_depth != null ? formatDepthMeters(row.actual_depth, 'm') : '—',
              money(row.total, currency), money(row.npt, currency), money(row.upa, currency),
            ]),
          }],
        })
      }
      if (detail.notes.length) sections.push({ title: 'How this drill-through is calculated', notes: detail.notes })
    }
    return {
      title: well ? `${well.well_code} — ${well.well_name}` : 'Well drill-through',
      subtitle: 'Plan, AFE budget and recorded actuals for one well, cut by activity, section and day.',
      scope: [well?.rig_code, well?.well_code, filters.currency || currency, filters.from || filters.to
        ? `${filters.from ? displayDate(filters.from) : 'start'} to ${filters.to ? displayDate(filters.to) : 'today'}` : 'All cost dates'].filter(Boolean).join(' · '),
      readAt: new Date().toLocaleString(),
      notices: [
        filters.includeDraft ? 'Draft and submitted daily sheets are included.' : 'Submitted daily sheets only.',
        'Actual days are elapsed time, not a count of sheets; sections and activities report active days.',
      ],
      sections,
      fileName: `well-drill-through-${well?.well_code ?? 'well'}`,
      orientation: options.orientation,
    }
  }

  return <PanelDialog
    open={!!wellId}
    title={detail ? `${detail.well.well_code} — ${detail.well.well_name}` : 'Well drill-through'}
    subtitle={detail
      ? `${detail.well.rig_code} ${detail.well.rig_name} · ${detail.well.well_location || 'Location not recorded'} · block ${detail.well.block || '—'}`
      : 'Plan, AFE budget and recorded actuals for the selected well.'}
    onClose={onClose}
    maxWidth="lg"
    footer={<Box display="flex" gap={1} flexWrap="wrap" justifyContent="flex-end" width="100%">
      {can('daily-cost:read') && detail && <Button component={RouterLink} to={`/daily-cost/analysis/${detail.well.well_id}`} variant="contained" startIcon={<InsightsOutlined/>}>Open well cost analysis</Button>}
      <Button variant="outlined" startIcon={<PictureAsPdfOutlined/>} disabled={!detail} onClick={() => setExportOpen(true)}>Export PDF</Button>
      <Button onClick={onClose} color="inherit">Close</Button>
    </Box>}
  >
    {error && <ErrorMessage message={error}/>}
    {loading && !detail && <Box py={6} display="grid" sx={{ placeItems: 'center' }}><CircularProgress size={26}/></Box>}
    {detail && <>
      <Box display="flex" gap={.75} flexWrap="wrap" mb={2}>
        <Tag tone={wellStatusTone(detail.well.status)}>Well status: {trackingLabel(detail.well.status)}</Tag>
        <Tag tone={planStatusTone(detail.well.config_status)}>Plan status: {planLabel(detail.well.config_status)}</Tag>
        {detail.well.has_sow_adjustment && <Tag tone="info">SOW adjusted</Tag>}
        {detail.well.over_budget && <Tag tone="error">Over AFE</Tag>}
      </Box>

      <Paper variant="outlined" sx={{ p: 2, borderRadius: 2 }}>
        <Box display="grid" gap={1.6} sx={{ gridTemplateColumns: { xs: 'repeat(2, minmax(0,1fr))', sm: 'repeat(4, minmax(0,1fr))', lg: 'repeat(6, minmax(0,1fr))' } }}>
          <Stat label="Planned days" value={decimal(detail.well.planned_days, 2)} hint={`Drilling ${decimal(detail.well.drilling_planned_days, 2)}${detail.well.completion_planned_days ? ` · Completion ${decimal(detail.well.completion_planned_days, 2)}` : ''}`}/>
          <Stat label="Actual days" value={decimal(detail.well.actual_days, 3)} hint={`${displayDate(detail.well.first_cost_date)} → ${displayDate(detail.well.last_cost_date)} · ${detail.well.actual_days_basis === 'spud' ? 'from spud' : 'cost dates only'}`}/>
          <Stat label="Cost sheets" value={decimal(detail.well.sheets)} hint={`${decimal(detail.well.recorded_days)} recording days · ${decimal(detail.well.draft_sheets)} draft`}/>
          <Stat label="NPT / UPA days" value={`${decimal(detail.well.npt_days, 3)} / ${decimal(detail.well.upa_days, 3)}`} hint={`${money(detail.well.npt_amount, currency)} · ${money(detail.well.upa_amount, currency)}`}/>
          <Stat label="AFE amount" value={money(detail.well.afe_amount, currency)} hint={detail.well.afe_count ? `${detail.well.afe_count} AFE${detail.well.afe_count === 1 ? '' : 's'}` : 'No active AFE'}/>
          <Stat label="SOW adjusted" value={money(detail.well.sow_adjusted_amount, currency)} hint={`Effective ${money(detail.well.effective_afe_amount, currency)}`}/>
          <Stat label="Actual cost" value={money(detail.well.actual_amount, currency)} hint={`${percent(detail.well.utilisation_percent)} of the effective AFE`}/>
          <Stat label="AFE balance" value={money(detail.well.afe_balance, currency)} hint={detail.well.over_budget ? 'Over the effective AFE' : 'Remaining against the effective AFE'}/>
          <Stat label="Services" value={money(detail.well.services_amount, currency)} hint="Recorded actual"/>
          <Stat label="Consumables" value={money(detail.well.consumables_amount, currency)} hint="Recorded actual"/>
          <Stat label="Tangibles" value={money(detail.well.tangibles_amount, currency)} hint="Recorded actual"/>
          <Stat label="Other expenses" value={money(detail.well.other_expenses_amount, currency)} hint="Unbudgeted, deducted from the AFE"/>
          <Stat label="Depth progress" value={percent(detail.well.depth_progress_percent)} hint={`${decimal(detail.well.actual_depth, 0)} of ${decimal(detail.well.planned_depth, 0)} m`}/>
          <Stat label="Planned sections" value={decimal(detail.well.section_count)} hint="Drilling configuration"/>
        </Box>
      </Paper>

      <Box display="grid" gap={2} mt={2} sx={{ gridTemplateColumns: { xs: '1fr', md: 'minmax(0, 1.6fr) minmax(0, 1fr)' } }}>
        <Paper
          variant="outlined" sx={{ p: 2, borderRadius: 2 }}
          data-chart-figure="1" data-chart-key="drill-daily"
          data-chart-title="Daily actual and cumulative cost"
          data-chart-caption={`Every saved sheet in the current date range, in ${currency || 'the selected currency'}.`}
        >
          <Typography fontWeight={800} fontSize={13.5}>Daily actual and cumulative cost</Typography>
          <Typography color="text.secondary" fontSize={11.5} mb={1}>Every saved sheet in the current date range, in {currency || 'the selected currency'}.</Typography>
          {detail.daily.length
            ? <Box height={230}><InteractiveChart option={dailyOption} notMerge lazyUpdate style={{ height: '100%', width: '100%' }}/></Box>
            : <Typography color="text.secondary" fontSize={12.5} py={6} textAlign="center">No cost sheets in this range.</Typography>}
        </Paper>
        <Paper
          variant="outlined" sx={{ p: 2, borderRadius: 2 }}
          data-chart-figure="1" data-chart-key="drill-time"
          data-chart-title="Recorded time split"
          data-chart-caption="Classified operational hours ÷ 24 by classification."
        >
          <Typography fontWeight={800} fontSize={13.5}>Recorded time split</Typography>
          <Typography color="text.secondary" fontSize={11.5} mb={1}>Distinct cost dates per classification.</Typography>
          {classification.length
            ? <Box height={230}><InteractiveChart option={timeOption} notMerge lazyUpdate style={{ height: '100%', width: '100%' }}/></Box>
            : <Typography color="text.secondary" fontSize={12.5} py={6} textAlign="center">No classified activity recorded.</Typography>}
        </Paper>
      </Box>

      {detail.afes.length > 0 && <>
        <Typography fontWeight={800} fontSize={13.5} mt={2.5} mb={1}>AFE positions</Typography>
        <Box sx={{ border: '1px solid', borderColor: 'divider', borderRadius: 2, overflowX: 'auto' }}>
          <Table size="small">
            <TableHead>
              <TableRow>
                <TableCell>AFE</TableCell>
                <TableCell>Type</TableCell>
                <TableCell>Status</TableCell>
                <TableCell align="right">AFE amount</TableCell>
                <TableCell align="right">SOW adjusted</TableCell>
                <TableCell align="right">Actual</TableCell>
                <TableCell align="right">Balance</TableCell>
                <TableCell align="right">Days</TableCell>
              </TableRow>
            </TableHead>
            <TableBody>
              {detail.afes.map(row => <TableRow key={row.afe_id} hover>
                <TableCell>
                  {can('afe:read')
                    ? <Typography
                      component={RouterLink}
                      to={`/afe/estimate/${row.afe_id}`}
                      fontSize={12.5}
                      fontWeight={700}
                      color="primary.main"
                      sx={{ textDecoration: 'none', '&:hover': { textDecoration: 'underline' } }}
                    >{row.afe_code}</Typography>
                    : <Typography fontSize={12.5} fontWeight={700}>{row.afe_code}</Typography>}
                  <Typography fontSize={11} color="text.secondary">{row.afe_name}</Typography>
                </TableCell>
                <TableCell>{row.afe_type}</TableCell>
                <TableCell><Tag tone={row.status === 'approval' ? 'success' : row.status === 'review' ? 'warning' : 'neutral'}>{AFE_STATUS_LABELS[row.status] ?? row.status}</Tag></TableCell>
                <TableCell align="right">{money(row.afe_amount, row.currency)}</TableCell>
                <TableCell align="right">{money(row.sow_adjusted_amount, row.currency)}</TableCell>
                <TableCell align="right">{money(row.actual_amount, row.currency)}</TableCell>
                <TableCell align="right"><BalanceValue value={row.afe_balance} currency={row.currency}/></TableCell>
                <TableCell align="right">{decimal(row.actual_days, 3)} <Typography component="span" fontSize={10.5} color="text.secondary">({decimal(row.npt_days, 3)} NPT · {decimal(row.upa_days, 3)} UPA)</Typography></TableCell>
              </TableRow>)}
            </TableBody>
          </Table>
        </Box>
      </>}

      {detail.sheets.length > 0 && <Box mt={2.5}>
        <Box display="flex" alignItems="baseline" justifyContent="space-between" gap={1} mb={1}>
          <Typography fontWeight={800} fontSize={13.5}>Daily cost sheets</Typography>
          <Typography color="text.secondary" fontSize={11}>
            {detail.sheets.length} sheet{detail.sheets.length === 1 ? '' : 's'} in this range
            {can('daily-cost:read') ? ' · open a sheet to see its lines' : ''}
          </Typography>
        </Box>
        <Box sx={{ border: '1px solid', borderColor: 'divider', borderRadius: 2, overflow: 'auto', maxHeight: 300 }}>
          <Table size="small" stickyHeader>
            <TableHead>
              <TableRow>
                <TableCell>Cost date</TableCell>
                <TableCell>AFE</TableCell>
                <TableCell>Status</TableCell>
                <TableCell align="right">Actual depth (m)</TableCell>
                <TableCell align="right">Total</TableCell>
                <TableCell align="right">NPT / UPA</TableCell>
                <TableCell align="right">Action</TableCell>
              </TableRow>
            </TableHead>
            <TableBody>
              {detail.sheets.map((row: DashboardDaySheet) => <TableRow key={row.entry_id} hover>
                <TableCell>{displayDate(row.cost_date)}</TableCell>
                <TableCell>{row.afe_code || '—'}</TableCell>
                <TableCell><SheetStatus status={row.status}/></TableCell>
                <TableCell align="right">{formatDepthMeters(row.actual_depth, 'm')}</TableCell>
                <TableCell align="right">{money(row.total, currency)}</TableCell>
                <TableCell align="right">{money(row.npt, currency)} / {money(row.upa, currency)}</TableCell>
                <TableCell align="right">
                  {can('daily-cost:read')
                    ? <Button
                      size="small"
                      component={RouterLink}
                      to={`/daily-cost/entries/${row.entry_id}`}
                      endIcon={<OpenInNewRounded sx={{ fontSize: 15 }}/>}
                    >Open sheet</Button>
                    : <Typography color="text.secondary" fontSize={11}>—</Typography>}
                </TableCell>
              </TableRow>)}
            </TableBody>
          </Table>
        </Box>
      </Box>}

      <Box display="grid" gap={2} mt={2} sx={{ gridTemplateColumns: { xs: '1fr', md: 'minmax(0, 1.15fr) minmax(0, 1fr)' } }}>
        <Box>
          <Typography fontWeight={800} fontSize={13.5} mb={1}>Hole sections and depth</Typography>
          <Box sx={{ border: '1px solid', borderColor: 'divider', borderRadius: 2, overflowX: 'auto' }}>
            <Table size="small">
              <TableHead>
                <TableRow>
                  <TableCell>Section</TableCell>
                  <TableCell align="right">Planned depth (m)</TableCell>
                  <TableCell align="right">Actual depth (m)</TableCell>
                  <TableCell align="right">Planned days</TableCell>
                  <TableCell align="right">Cost days</TableCell>
                  <TableCell align="right">Actual</TableCell>
                  <TableCell>Status</TableCell>
                </TableRow>
              </TableHead>
              <TableBody>
                {sectionRows.map((row, index) => <TableRow key={`${row.hole_section_id}-${row.scope}-${index}`} hover>
                  <TableCell>
                    <Typography fontSize={12.5} fontWeight={700}>{row.section_code}</Typography>
                    <Typography fontSize={10.5} color="text.secondary">{row.section_name}{row.scope === 'completion' ? ' · completion' : ''}</Typography>
                  </TableCell>
                  <TableCell align="right">{row.from_depth != null ? `${decimal(row.from_depth, 2)} – ${decimal(row.to_depth, 2)} m` : '—'}</TableCell>
                  <TableCell align="right">{row.actual_depth != null ? formatDepthMeters(row.actual_depth, 'm') : '—'}</TableCell>
                  <TableCell align="right">{decimal(row.planned_days, 2)}</TableCell>
                  <TableCell align="right">{decimal(row.active_days)}</TableCell>
                  <TableCell align="right">{money(row.amount, currency)}</TableCell>
                  <TableCell><Tag tone={row.reached ? 'success' : 'neutral'}>{row.reached ? 'Reached' : 'Not reached'}</Tag></TableCell>
                </TableRow>)}
                {!sectionRows.length && <TableRow><TableCell colSpan={6}><Typography color="text.secondary" fontSize={12.5}>No configured sections.</Typography></TableCell></TableRow>}
              </TableBody>
            </Table>
          </Box>
        </Box>
        <Box>
          <Typography fontWeight={800} fontSize={13.5} mb={1}>Activities recorded</Typography>
          <Box sx={{ border: '1px solid', borderColor: 'divider', borderRadius: 2, overflowX: 'auto', maxHeight: 320 }}>
            <Table size="small" stickyHeader>
              <TableHead>
                <TableRow>
                  <TableCell>Activity</TableCell>
                  <TableCell>Class</TableCell>
                  <TableCell align="right">Days</TableCell>
                  <TableCell align="right">Actual</TableCell>
                  <TableCell align="right">Share</TableCell>
                </TableRow>
              </TableHead>
              <TableBody>
                {activityRows.map((row, index) => <TableRow key={`${row.activity_id}-${index}`} hover>
                  <TableCell>
                    <Typography fontSize={12.5} fontWeight={700}>{row.activity_code || '—'}</Typography>
                    <Typography fontSize={10.5} color="text.secondary">{row.activity_name}</Typography>
                  </TableCell>
                  <TableCell><Tag tone={CLASSIFICATION_TONES[row.classification] ?? 'neutral'}>{row.classification}</Tag></TableCell>
                  <TableCell align="right">{decimal(row.active_days)}</TableCell>
                  <TableCell align="right">{money(row.amount, currency)}</TableCell>
                  <TableCell align="right">{percent(row.share)}</TableCell>
                </TableRow>)}
                {!activityRows.length && <TableRow><TableCell colSpan={5}><Typography color="text.secondary" fontSize={12.5}>No classified activity recorded in this range.</Typography></TableCell></TableRow>}
              </TableBody>
            </Table>
          </Box>
        </Box>
      </Box>

      <Box display="grid" gap={2} mt={2} sx={{ gridTemplateColumns: { xs: '1fr', md: 'minmax(0, 1fr) minmax(0, 1fr)' } }}>
        <Box>
          <Typography fontWeight={800} fontSize={13.5} mb={1}>Cost group reconciliation</Typography>
          <Box sx={{ border: '1px solid', borderColor: 'divider', borderRadius: 2 }}>
            <Table size="small">
              <TableHead>
                <TableRow>
                  <TableCell>Group</TableCell>
                  <TableCell align="right">AFE planned</TableCell>
                  <TableCell align="right">Actual</TableCell>
                  <TableCell align="right">Balance</TableCell>
                </TableRow>
              </TableHead>
              <TableBody>
                {detail.cost_groups.map(row => <TableRow key={row.key} hover>
                  <TableCell>{row.label}</TableCell>
                  <TableCell align="right">{money(row.planned, currency)}</TableCell>
                  <TableCell align="right">{money(row.actual, currency)}</TableCell>
                  <TableCell align="right"><BalanceValue value={row.balance} currency={currency}/></TableCell>
                </TableRow>)}
              </TableBody>
            </Table>
          </Box>
        </Box>
        <Box>
          <Typography fontWeight={800} fontSize={13.5} mb={1}>How this drill-through is calculated</Typography>
          <Paper variant="outlined" sx={{ p: 1.8, borderRadius: 2 }}>
            {detail.notes.map(note => <Box key={note} display="flex" gap={1} mb={1}>
              <Divider orientation="vertical" flexItem sx={{ borderColor: 'primary.main', borderWidth: 1 }}/>
              <Typography color="text.secondary" fontSize={11.5} lineHeight={1.5}>{note}</Typography>
            </Box>)}
          </Paper>
        </Box>
      </Box>
    </>}

    <ExportReportDialog
      open={exportOpen}
      onClose={() => setExportOpen(false)}
      figures={[
        { key: 'drill-daily', label: 'Daily actual and cumulative cost' },
        { key: 'drill-time', label: 'Recorded time split' },
      ]}
      buildDocument={buildDocument}
      onExport={async (format, recordCount) => {
        await api('/dashboard/business/export-audit', {
          method: 'POST',
          body: body({ format, record_count: recordCount }),
        })
      }}
      fileName={`well-drill-through-${detail?.well.well_code ?? 'well'}`}
      title="Export this drill-through"
    />
  </PanelDialog>
}
