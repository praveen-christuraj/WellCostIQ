import { useCallback, useEffect, useMemo, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import type { EChartsOption } from 'echarts'
import {
  Alert, Box, Button, Checkbox, Collapse, FormControlLabel, IconButton, Menu, MenuItem, Table, TableBody,
  TableCell, TableContainer, TableHead, TablePagination, TableRow, TextField, Tooltip, Typography, useTheme,
} from '@mui/material'
import {
  DownloadRounded, ExpandLessRounded, ExpandMoreRounded, FilterListRounded, OpenInNewRounded,
  PictureAsPdfOutlined, RefreshRounded,
} from '@mui/icons-material'
import { ErrorMessage, PageHeading, Tag } from '../components/Common'
import { AiCostReviewPanel } from '../components/costIntelligence/AiCostReviewPanel'
import { ChartPanel } from '../components/ui/ChartPanel'
import { DatasetState } from '../components/ui/DatasetState'
import { ExportReportDialog } from '../components/ui/ExportReportDialog'
import { InteractiveChart } from '../components/ui/InteractiveChart'
import { SectionCard } from '../components/ui/SectionCard'
import { StatCard } from '../components/ui/StatCard'
import { useAuth } from '../context/AuthContext'
import { useColorMode } from '../context/ThemeContext'
import { chartPalette } from '../designSystem'
import { api, body } from '../lib/api'
import { chartData, chartDrillHandler, chartRowId } from '../lib/chartInteraction'
import {
  AI_CATEGORY_LABEL, amount, BAND_LABEL, BAND_TONE, CATEGORY_LABEL, filterFindings,
  REPORT_PRESETS, REPORT_SECTIONS, SEVERITY_LABEL, SEVERITY_TONE, signedPercent,
  type IntelligenceAiReview, type IntelligenceFinding, type IntelligenceOverview,
  type IntelligenceWell, type IntelligenceWellDetail, type ReportSectionKey,
} from '../lib/costIntelligence'
import { detailSheet, writeWorkbook } from '../lib/matrixWorkbook'
import type { ReportDocument, ReportFigure, ReportSection } from '../lib/reportPdf'
import { trackingLabel, WELL_STATUSES } from '../lib/rigWell'

const PAGE_SIZES = [20, 50, 100]
const FIGURES = [
  { key: 'ci-forecast', label: 'Forecast against AFE' },
  { key: 'ci-findings', label: 'Findings by subject' },
  { key: 'ci-well-daily', label: 'Selected well: daily cost' },
  { key: 'ci-well-cumulative', label: 'Selected well: cumulative cost and forecast' },
  { key: 'ci-well-trend', label: 'Selected well: trend statistic' },
]
const plottedWell = (row: IntelligenceWell) => chartRowId('ci-well', row.well_id)

/**
 * Cost Intelligence: the server analyses the cost record and this page shows
 * what it found, why, and what to do next. Personal read states never change
 * or block a source record. Charts go through the shared chart host, and every chart
 * point that selects a well carries that well's identity (never its position).
 */
export default function CostIntelligence() {
  const { can } = useAuth()
  const navigate = useNavigate()
  const theme = useTheme()
  const { mode } = useColorMode()
  const palette = useMemo(() => chartPalette(mode), [mode])
  const [aiReview, setAiReview] = useState<IntelligenceAiReview | null>(null)
  const axis = useMemo(() => ({ text: theme.palette.text.secondary, line: theme.palette.divider }), [theme])
  const tone = theme.palette

  const [data, setData] = useState<IntelligenceOverview | null>(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState('')
  const [from, setFrom] = useState('')
  const [to, setTo] = useState('')
  const [status, setStatus] = useState('')
  const [advanced, setAdvanced] = useState(false)
  const [severity, setSeverity] = useState('')
  const [category, setCategory] = useState('')
  const [findingWell, setFindingWell] = useState('')
  const [search, setSearch] = useState('')
  const [page, setPage] = useState(0)
  const [pageSize, setPageSize] = useState(20)
  const [expanded, setExpanded] = useState('')
  const [readStates, setReadStates] = useState<Record<string, string>>({})
  const [showRead, setShowRead] = useState(false)
  const [stateBusy, setStateBusy] = useState('')
  const [stateError, setStateError] = useState('')

  useEffect(() => {
    api<Record<string, string>>('/cost-intelligence/finding-states', { action: 'Load finding read states' })
      .then(setReadStates).catch(caught => setStateError((caught as Error).message))
  }, [])

  const markFinding = async (id: string, state: 'acknowledged' | 'dismissed' | 'unread') => {
    setStateBusy(id); setStateError('')
    try {
      await api(`/cost-intelligence/finding-states/${id}`, { method: 'PUT', body: body({ state }), action: 'Update finding read state' })
      setReadStates(current => {
        const next = { ...current }
        if (state === 'unread') delete next[id]
        else next[id] = state
        return next
      })
    } catch (caught) { setStateError((caught as Error).message) } finally { setStateBusy('') }
  }

  const [wellId, setWellId] = useState('')
  const [detail, setDetail] = useState<IntelligenceWellDetail | null>(null)
  const [detailError, setDetailError] = useState('')
  const [detailLoading, setDetailLoading] = useState(false)

  const [exportOpen, setExportOpen] = useState(false)
  const [exportAnchor, setExportAnchor] = useState<HTMLElement | null>(null)
  const [sections, setSections] = useState<ReportSectionKey[]>(REPORT_PRESETS.full.sections)
  const [notice, setNotice] = useState('')

  const query = useMemo(() => {
    const params = new URLSearchParams()
    if (from) params.set('from', from)
    if (to) params.set('to', to)
    return params
  }, [from, to])
  const rangeInvalid = Boolean(from && to && from > to)

  const load = useCallback(async () => {
    if (rangeInvalid) return
    setLoading(true); setError('')
    const params = new URLSearchParams(query)
    if (status) params.set('well_status', status)
    try {
      const result = await api<IntelligenceOverview>(`/cost-intelligence/overview?${params.toString()}`, { action: 'Analyse the cost record' })
      setData(result)
      // Keep the chosen well when it is still in scope; otherwise open the one
      // that most needs attention (the list arrives lowest score first).
      setWellId(current => (result.wells.some(row => row.well_id === current)
        ? current
        : result.wells.find(row => row.recorded_days > 0)?.well_id ?? ''))
    } catch (caught) { setError((caught as Error).message) } finally { setLoading(false) }
  }, [query, status, rangeInvalid])
  useEffect(() => { void load() }, [load])

  useEffect(() => {
    if (!wellId) { setDetail(null); return }
    let live = true
    setDetailLoading(true); setDetailError('')
    api<IntelligenceWellDetail>(`/cost-intelligence/wells/${wellId}?${query.toString()}`, { action: 'Analyse the well' })
      .then(result => { if (live) setDetail(result) })
      .catch(caught => { if (live) { setDetail(null); setDetailError((caught as Error).message) } })
      .finally(() => { if (live) setDetailLoading(false) })
    return () => { live = false }
  }, [wellId, query, data?.generated_at])

  const currency = data?.currency ?? ''
  const kpis = data?.kpis
  const wells = useMemo(() => data?.wells ?? [], [data])
  const findings = useMemo(
    () => filterFindings((data?.findings ?? []).filter(row => showRead || !readStates[row.id]), { severity, category, wellId: findingWell, search }),
    [data, severity, category, findingWell, search, readStates, showRead],
  )
  const suggestions = useMemo(() => (data?.suggestions ?? []).filter(row => !readStates[row.finding_id]), [data, readStates])
  const pageFindings = findings.slice(page * pageSize, page * pageSize + pageSize)
  useEffect(() => { setPage(0) }, [severity, category, findingWell, search, data, readStates, showRead])
  const filtersActive = Boolean(severity || category || findingWell || search || status || from || to)

  // ---- charts ----------------------------------------------------------------
  // The rows a chart draws and the rows its click handler resolves against are
  // the same array, and each point names its well.
  const forecastRows = useMemo(
    () => wells.filter(row => row.afe_amount || row.actual_amount).slice(0, 12).slice().reverse(),
    [wells],
  )
  const forecastOption: EChartsOption = useMemo(() => ({
    animation: false,
    grid: { left: 8, right: 26, top: 30, bottom: 8, containLabel: true },
    legend: { top: 0, textStyle: { color: axis.text }, itemWidth: 12, itemHeight: 8 },
    tooltip: { trigger: 'axis', axisPointer: { type: 'shadow' }, valueFormatter: value => amount(Number(value ?? 0), currency) },
    xAxis: { type: 'value', axisLabel: { color: axis.text, formatter: (value: number) => amount(value) }, splitLine: { lineStyle: { color: axis.line } } },
    yAxis: { type: 'category', data: forecastRows.map(row => row.well_code), axisLabel: { color: axis.text }, axisLine: { lineStyle: { color: axis.line } } },
    series: [
      { name: 'AFE', type: 'bar', barMaxWidth: 10, itemStyle: { color: palette.planned, opacity: .45 }, data: chartData(forecastRows, plottedWell, row => row.afe_amount ?? 0, row => row.well_code) },
      { name: 'Recorded', type: 'bar', barMaxWidth: 10, itemStyle: { color: palette.actual }, data: chartData(forecastRows, plottedWell, row => row.actual_amount ?? 0, row => row.well_code) },
      { name: 'Forecast at completion', type: 'bar', barMaxWidth: 10, itemStyle: { color: palette.adjusted }, data: chartData(forecastRows, plottedWell, row => (row.forecast.available ? row.forecast.estimate ?? 0 : '-'), row => row.well_code) },
    ],
  }), [forecastRows, palette, axis, currency])
  const selectForecastWell = chartDrillHandler<IntelligenceWell>(forecastRows, plottedWell, row => setWellId(row.well_id))

  const categoryRows = useMemo(() => (data?.by_category ?? []).slice().reverse(), [data])
  const categoryOption: EChartsOption = useMemo(() => ({
    animation: false,
    grid: { left: 8, right: 20, top: 30, bottom: 8, containLabel: true },
    legend: { top: 0, textStyle: { color: axis.text }, itemWidth: 12, itemHeight: 8 },
    tooltip: { trigger: 'axis', axisPointer: { type: 'shadow' } },
    xAxis: { type: 'value', minInterval: 1, axisLabel: { color: axis.text }, splitLine: { lineStyle: { color: axis.line } } },
    yAxis: { type: 'category', data: categoryRows.map(row => row.label), axisLabel: { color: axis.text }, axisLine: { lineStyle: { color: axis.line } } },
    series: [
      { name: 'Critical', type: 'bar', stack: 'n', barMaxWidth: 14, itemStyle: { color: tone.error.main }, data: categoryRows.map(row => row.critical) },
      { name: 'Warning', type: 'bar', stack: 'n', barMaxWidth: 14, itemStyle: { color: tone.warning.main }, data: categoryRows.map(row => row.warning) },
      { name: 'Note', type: 'bar', stack: 'n', barMaxWidth: 14, itemStyle: { color: palette.adjusted }, data: categoryRows.map(row => row.info) },
    ],
  }), [categoryRows, palette, axis, tone])
  const selectCategory = (params: { dataIndex?: number }) => {
    const row = typeof params.dataIndex === 'number' ? categoryRows[params.dataIndex] : undefined
    if (row) { setCategory(row.key); setAdvanced(true) }
  }

  const days = useMemo(() => detail?.days ?? [], [detail])
  const dailyOption: EChartsOption = useMemo(() => {
    const hasTangibles = days.some(row => Number(row.tangibles ?? 0) > 0)
    return {
      animation: false,
      grid: { left: 8, right: 20, top: 30, bottom: 8, containLabel: true },
      legend: { top: 0, textStyle: { color: axis.text }, itemWidth: 12, itemHeight: 8 },
      tooltip: { trigger: 'axis', valueFormatter: value => amount(Number(value ?? 0), currency) },
      xAxis: { type: 'category', data: days.map(row => row.cost_date), axisLabel: { color: axis.text }, axisLine: { lineStyle: { color: axis.line } } },
      yAxis: { type: 'value', axisLabel: { color: axis.text, formatter: (value: number) => amount(value) }, splitLine: { lineStyle: { color: axis.line } } },
      series: [
        ...(hasTangibles ? [
          {
            name: 'Daily operational', type: 'bar' as const, stack: 'daily', barMaxWidth: 14,
            data: days.map(row => ({
              value: row.operational ?? Math.max(0, row.actual - (row.tangibles ?? 0)),
              itemStyle: { color: row.spike ? tone.error.main : palette.actual },
            })),
          },
          {
            name: 'Tangibles (lump-sum)', type: 'bar' as const, stack: 'daily', barMaxWidth: 14,
            itemStyle: { color: palette.series[4] },
            data: days.map(row => row.tangibles ?? 0),
          },
        ] : [
          {
            name: 'Daily cost', type: 'bar' as const, barMaxWidth: 14,
            data: days.map(row => ({ value: row.actual, itemStyle: { color: row.spike ? tone.error.main : palette.actual } })),
          },
        ]),
        { name: 'Non-productive time', type: 'bar', barMaxWidth: 14, barGap: '-100%', itemStyle: { color: tone.warning.main }, data: days.map(row => row.npt) },
        ...(detail?.drift_baseline ? [{
          name: 'Opening baseline', type: 'line' as const, symbol: 'none', lineStyle: { color: palette.planned, type: 'dashed' as const, width: 1.5 },
          itemStyle: { color: palette.planned }, data: days.map(row => row.baseline),
        }] : []),
      ],
    }
  }, [days, detail, palette, axis, tone, currency])

  const cumulativeOption: EChartsOption = useMemo(() => {
    const projection = detail?.projection ?? []
    const dates = [...days.map(row => row.cost_date), ...projection.slice(1).map(row => row.cost_date)]
    const pad = (count: number) => Array.from({ length: Math.max(count, 0) }, () => null)
    const afe = detail?.well.afe_amount
    return {
      animation: false,
      grid: { left: 8, right: 20, top: 30, bottom: 8, containLabel: true },
      legend: { top: 0, textStyle: { color: axis.text }, itemWidth: 12, itemHeight: 8 },
      tooltip: { trigger: 'axis', valueFormatter: value => (value === null || value === undefined ? '—' : amount(Number(value), currency)) },
      xAxis: { type: 'category', data: dates, axisLabel: { color: axis.text }, axisLine: { lineStyle: { color: axis.line } } },
      yAxis: { type: 'value', axisLabel: { color: axis.text, formatter: (value: number) => amount(value) }, splitLine: { lineStyle: { color: axis.line } } },
      series: [
        { name: 'Recorded (cumulative)', type: 'line', symbol: 'none', lineStyle: { color: palette.actual, width: 2 }, itemStyle: { color: palette.actual }, data: [...days.map(row => row.cumulative), ...pad(projection.length - 1)] },
        ...(projection.length ? [
          { name: 'Forecast', type: 'line' as const, symbol: 'none', lineStyle: { color: palette.adjusted, width: 2, type: 'dashed' as const }, itemStyle: { color: palette.adjusted }, data: [...pad(days.length - 1), ...projection.map(row => row.estimate)] },
          { name: 'Forecast high', type: 'line' as const, symbol: 'none', lineStyle: { color: palette.adjusted, width: 1, type: 'dotted' as const }, itemStyle: { color: palette.adjusted }, data: [...pad(days.length - 1), ...projection.map(row => row.high)] },
          { name: 'Forecast low', type: 'line' as const, symbol: 'none', lineStyle: { color: palette.adjusted, width: 1, type: 'dotted' as const }, itemStyle: { color: palette.adjusted }, data: [...pad(days.length - 1), ...projection.map(row => row.low)] },
        ] : []),
        ...(afe ? [{ name: 'AFE', type: 'line' as const, symbol: 'none', lineStyle: { color: tone.error.main, width: 1.5 }, itemStyle: { color: tone.error.main }, data: dates.map(() => afe) }] : []),
      ],
    }
  }, [days, detail, palette, axis, tone, currency])

  const trendOption: EChartsOption = useMemo(() => ({
    animation: false,
    grid: { left: 8, right: 20, top: 30, bottom: 8, containLabel: true },
    legend: { top: 0, textStyle: { color: axis.text }, itemWidth: 12, itemHeight: 8 },
    tooltip: { trigger: 'axis' },
    xAxis: { type: 'category', data: days.map(row => row.cost_date), axisLabel: { color: axis.text }, axisLine: { lineStyle: { color: axis.line } } },
    yAxis: { type: 'value', axisLabel: { color: axis.text }, splitLine: { lineStyle: { color: axis.line } } },
    series: [
      { name: 'Running above baseline', type: 'line', symbol: 'none', lineStyle: { color: tone.error.main, width: 2 }, itemStyle: { color: tone.error.main }, data: days.map(row => row.cusum_up) },
      { name: 'Running below baseline', type: 'line', symbol: 'none', lineStyle: { color: palette.planned, width: 2 }, itemStyle: { color: palette.planned }, data: days.map(row => row.cusum_down) },
      { name: 'Alarm limit', type: 'line', symbol: 'none', lineStyle: { color: axis.text, width: 1, type: 'dashed' }, itemStyle: { color: axis.text }, data: days.map(() => detail?.cusum_limit ?? 0) },
    ],
  }), [days, detail, palette, axis, tone])
  const trendAvailable = days.some(row => row.cusum_up !== null)

  // ---- export ----------------------------------------------------------------
  const recordExport = async (format: 'csv' | 'xlsx' | 'pdf', recordCount: number) => {
    await api('/cost-intelligence/exports', {
      method: 'POST', body: body({ format, record_count: recordCount, sections: sections.join(',') }),
      action: 'Record the export',
    })
  }
  const findingRecord = (row: IntelligenceFinding) => ({
    severity: SEVERITY_LABEL[row.severity], subject: CATEGORY_LABEL[row.category], well: row.well_code,
    cost_date: row.cost_date ?? '', finding: row.title, detail: row.detail, amount: row.amount ?? '',
    suggestion: row.suggestion, basis: row.basis,
  })
  const findingColumns = [
    { key: 'severity', label: 'Severity' }, { key: 'subject', label: 'Subject' }, { key: 'well', label: 'Well' },
    { key: 'cost_date', label: 'Cost date' }, { key: 'finding', label: 'Finding' }, { key: 'detail', label: 'Detail' },
    { key: 'amount', label: `Amount (${currency})`, numeric: true }, { key: 'suggestion', label: 'Suggested action' },
    { key: 'basis', label: 'How it was derived' },
  ]
  const wellRecord = (row: IntelligenceWell) => ({
    well: row.well_code, name: row.well_name, rig: row.rig_code, status: trackingLabel(row.status), health: row.score,
    band: BAND_LABEL[row.band], afe: row.afe_amount ?? '', actual: row.actual_amount ?? '',
    actual_vs_afe_percent: row.utilisation_percent ?? '',
    forecast: row.forecast.available ? row.forecast.estimate ?? '' : '', variance_percent: row.forecast.variance_percent ?? '',
    critical: row.critical, warning: row.warning, notes: row.info, summary: row.summary,
  })
  const wellColumns = [
    { key: 'well', label: 'Well' }, { key: 'name', label: 'Name' }, { key: 'rig', label: 'Rig' }, { key: 'status', label: 'Status' },
    { key: 'health', label: 'Health score', numeric: true }, { key: 'band', label: 'Band' },
    { key: 'afe', label: `AFE (${currency})`, numeric: true }, { key: 'actual', label: `Recorded (${currency})`, numeric: true },
    { key: 'actual_vs_afe_percent', label: 'Actual / AFE %', numeric: true },
    { key: 'forecast', label: `Forecast (${currency})`, numeric: true }, { key: 'variance_percent', label: 'Forecast vs AFE %', numeric: true },
    { key: 'critical', label: 'Critical', numeric: true }, { key: 'warning', label: 'Warnings', numeric: true },
    { key: 'notes', label: 'Notes', numeric: true }, { key: 'summary', label: 'Summary' },
  ]
  const exportFile = async (format: 'xlsx' | 'csv') => {
    setExportAnchor(null); setError('')
    try {
      const rows = findings.map(findingRecord)
      if (format === 'xlsx') {
        const sheets = [
          detailSheet('Findings', findingColumns, rows),
          detailSheet('Well health', wellColumns, wells.map(wellRecord)),
        ]
        if (aiReview) {
          sheets.push(
            detailSheet(
              'AI review',
              [
                { key: 'severity', label: 'Severity' },
                { key: 'category', label: 'Category' },
                { key: 'well', label: 'Well' },
                { key: 'reference', label: 'Date / Ref' },
                { key: 'title', label: 'Finding' },
                { key: 'detail', label: 'Evidence' },
                { key: 'recommendation', label: 'Recommendation' },
              ],
              aiReview.findings.map(item => ({
                severity: SEVERITY_LABEL[item.severity],
                category: AI_CATEGORY_LABEL[item.category] ?? item.category,
                well: item.well_code || 'Portfolio',
                reference: item.reference,
                title: item.title,
                detail: item.detail,
                recommendation: item.recommendation,
              })),
            ),
          )
        }
        await writeWorkbook('cost-intelligence.xlsx', sheets)
      } else {
        const cell = (value: unknown) => {
          const text = String(value ?? '')
          // A leading =, +, - or @ would be run as a formula by a spreadsheet.
          const safe = /^[=+\-@]/.test(text) && Number.isNaN(Number(text)) ? `'${text}` : text
          return `"${safe.replace(/"/g, '""')}"`
        }
        const lines = [findingColumns.map(column => cell(column.label)).join(','),
          ...rows.map(row => findingColumns.map(column => cell((row as Record<string, unknown>)[column.key])).join(','))]
        const link = document.createElement('a')
        link.href = URL.createObjectURL(new Blob([`\ufeff${lines.join('\r\n')}`], { type: 'text/csv;charset=utf-8' }))
        link.download = 'cost-intelligence-findings.csv'
        link.click()
        URL.revokeObjectURL(link.href)
      }
      await recordExport(format, rows.length)
      setNotice(`Exported ${rows.length} finding(s) as ${format.toUpperCase()}.`)
    } catch (caught) { setError((caught as Error).message) }
  }

  const buildDocument = useCallback((options: {
    figures: Map<string, { dataUrl: string; width: number; height: number; title?: string; caption?: string }>
    includeFigures: boolean; includeTables: boolean; orientation: 'landscape' | 'portrait'
  }): ReportDocument => {
    const has = (key: ReportSectionKey) => sections.includes(key)
    const figure = (key: string, title: string, caption: string): ReportFigure => {
      const capture = options.figures.get(key)
      return { title, caption, dataUrl: capture?.dataUrl ?? '', width: capture?.width ?? 0, height: capture?.height ?? 0 }
    }
    const captured = (key: string) => options.includeFigures && options.figures.has(key)
    const out: ReportSection[] = []
    if (data && kpis && has('summary')) {
      const utilPct = kpis.utilisation_percent ?? (kpis.afe_amount && kpis.actual_amount != null ? (kpis.actual_amount / kpis.afe_amount) * 100 : null)
      out.push({
        title: 'Summary',
        notes: data.headline,
        kpis: [
          { label: 'Health score', value: `${kpis.score} / 100`, hint: BAND_LABEL[kpis.band] },
          { label: 'Combined AFE', value: amount(kpis.afe_amount, currency) },
          { label: 'Recorded cost', value: amount(kpis.actual_amount, currency) },
          { label: 'Actual / AFE %', value: utilPct != null ? `${utilPct.toFixed(1)}%` : '—', hint: '(Actual ÷ AFE) × 100' },
          { label: 'Forecast at completion', value: amount(kpis.forecast_amount, currency), hint: signedPercent(kpis.forecast_variance_percent) },
          { label: 'Cost above AFE', value: amount(kpis.amount_at_risk, currency), hint: 'Recorded or forecast' },
          { label: 'Findings', value: `${kpis.critical} critical, ${kpis.warning} warning`, hint: `${kpis.info} note(s)` },
        ],
        figures: [
          ...(captured('ci-forecast') ? [figure('ci-forecast', 'Forecast against AFE', `AFE, recorded cost and forecast at completion per well, in ${currency || 'the reporting currency'}.`)] : []),
          ...(captured('ci-findings') ? [figure('ci-findings', 'Findings by subject', 'Count of findings by subject and severity.')] : []),
        ],
      })
    }
    if (data && has('actions') && options.includeTables) {
      out.push({
        title: 'Suggested actions',
        subtitle: 'Ranked by severity, then by the amount involved.',
        tables: [{
          head: ['#', 'Severity', 'Well', 'Finding', 'Suggested action', `Amount (${currency})`], numeric: [0, 5], wide: [4],
          body: suggestions.map(row => [row.rank, SEVERITY_LABEL[row.severity], row.well_code, row.title, row.suggestion, amount(row.amount)]),
        }],
      })
    }
    if (has('wells') && options.includeTables) {
      out.push({
        title: 'Well health and forecast',
        tables: [{
          head: ['Well', 'Status', 'Health', `AFE (${currency})`, 'Recorded', 'Actual / AFE %', 'Forecast', 'vs AFE', 'Critical', 'Warnings'],
          numeric: [2, 3, 4, 5, 6, 7, 8, 9],
          body: wells.map(row => [row.well_code, trackingLabel(row.status), `${row.score} (${BAND_LABEL[row.band]})`, amount(row.afe_amount),
            amount(row.actual_amount), row.utilisation_percent != null ? `${row.utilisation_percent.toFixed(1)}%` : '—',
            row.forecast.available ? amount(row.forecast.estimate) : '—', signedPercent(row.forecast.variance_percent), row.critical, row.warning]),
        }],
        notes: wells.filter(row => row.critical || row.warning).map(row => row.summary),
      })
    }
    if (has('findings') && options.includeTables) {
      out.push({
        title: 'Findings',
        subtitle: showRead ? 'As filtered on the page, including read findings.' : 'As filtered on the page; acknowledged and dismissed findings are excluded.',
        tables: [{
          head: ['Severity', 'Well', 'Date', 'Finding', 'Detail', 'How it was derived'], wide: [4, 5],
          body: findings.map(row => [SEVERITY_LABEL[row.severity], row.well_code, row.cost_date ?? '', row.title, row.detail, row.basis]),
        }],
      })
    }
    if (detail && has('well')) {
      const wellTables: ReportSection['tables'] = []
      if (options.includeTables && detail.breakdown?.cost_groups.length) {
        wellTables.push({
          title: 'Cost group variance',
          head: ['Cost group', `AFE (${currency})`, 'Actual', 'Actual / AFE %', 'Share'],
          numeric: [1, 2, 3, 4],
          body: detail.breakdown.cost_groups.map(grp => [
            grp.label, amount(grp.planned), amount(grp.actual),
            grp.utilisation_percent != null ? `${grp.utilisation_percent.toFixed(1)}%` : '—',
            grp.share_percent != null ? `${grp.share_percent.toFixed(1)}%` : '—',
          ]),
        })
      }
      if (options.includeTables) {
        wellTables.push({
          title: 'Findings & suggested actions',
          head: ['Severity', 'Finding', 'Suggested action'], wide: [2],
          body: detail.findings.filter(row => showRead || !readStates[row.id]).map(row => [SEVERITY_LABEL[row.severity], row.title, row.suggestion]),
        })
      }
      out.push({
        title: `Well analysis: ${detail.well.well_code}`,
        subtitle: detail.well.summary,
        kpis: detail.breakdown ? [
          { label: 'Actual / AFE %', value: detail.well.utilisation_percent != null ? `${detail.well.utilisation_percent.toFixed(1)}%` : '—' },
          { label: 'Operational spend', value: amount(detail.breakdown.unit_economics.operational_actual, currency) },
          { label: 'Tangibles spend', value: amount(detail.breakdown.unit_economics.tangible_actual, currency) },
          { label: 'Operational daily avg', value: amount(detail.breakdown.unit_economics.operational_daily_avg, currency) },
          { label: 'CPI', value: detail.breakdown.unit_economics.burn_efficiency_index != null ? detail.breakdown.unit_economics.burn_efficiency_index.toFixed(2) : '—' },
        ] : undefined,
        figures: [
          ...(captured('ci-well-daily') ? [figure('ci-well-daily', 'Daily operational cost & tangibles', 'Daily operational spend separated from lump-sum tangibles, with flagged days and the opening baseline.')] : []),
          ...(captured('ci-well-cumulative') ? [figure('ci-well-cumulative', 'Cumulative cost and forecast', 'Recorded cumulative cost, the forecast path with its range, and the AFE.')] : []),
          ...(captured('ci-well-trend') ? [figure('ci-well-trend', 'Trend statistic', 'CUSUM of operational daily cost against the opening baseline; lump-sum tangibles are excluded.')] : []),
        ],
        tables: wellTables,
        notes: detail.notes,
      })
    }
    if (aiReview) {
      out.push({
        title: `AI Cost Analytic Review (${aiReview.model})`,
        subtitle: `${aiReview.scope === 'well' && aiReview.well_code ? `Well ${aiReview.well_code}` : `Portfolio (${aiReview.inspected_wells} wells)`} · Posture: ${BAND_LABEL[aiReview.risk_posture]}`,
        notes: [
          aiReview.executive_summary,
          ...aiReview.recommendations.map((rec, idx) => `Action ${idx + 1}: ${rec}`),
          ...aiReview.data_quality_notes.map(note => `Data note: ${note}`),
        ],
        tables: options.includeTables && aiReview.findings.length ? [{
          title: 'AI-identified anomalies, mistakes & risks',
          head: ['Severity', 'Category', 'Well / Ref', 'Finding', 'Recommended action'],
          wide: [3, 4],
          body: aiReview.findings.map(item => [
            SEVERITY_LABEL[item.severity],
            AI_CATEGORY_LABEL[item.category] ?? item.category,
            [item.well_code || 'Portfolio', item.reference].filter(Boolean).join(' · '),
            `${item.title}: ${item.detail}`,
            item.recommendation || '—',
          ]),
        }] : undefined,
      })
    }
    if (data && has('methods')) out.push({ title: 'How the analysis works', notes: data.methods })
    return {
      title: 'Cost Intelligence report',
      subtitle: 'Automated analysis of the cost record: findings are advice and state how they were derived.',
      scope: [from || to ? `Cost dates ${from || 'start'} to ${to || 'latest'}` : 'All cost dates', status ? `Status: ${trackingLabel(status)}` : 'All well statuses'].join(' · '),
      readAt: data ? new Date(data.generated_at).toLocaleString() : undefined,
      notices: data?.notes,
      sections: out,
      fileName: 'cost-intelligence-report',
      orientation: options.orientation,
    }
  }, [data, kpis, sections, wells, findings, detail, currency, from, to, status, filtersActive, aiReview, suggestions, readStates, showRead])

  const toggleSection = (key: ReportSectionKey) => setSections(current => (current.includes(key) ? current.filter(item => item !== key) : [...current, key]))
  const selectedWell = wells.find(row => row.well_id === wellId)
  const canExport = Boolean(data?.capabilities.export ?? can('cost-intelligence:export'))

  return <>
    <PageHeading
      eyebrow="REPORTS / COST INTELLIGENCE"
      title="Cost Intelligence"
      subtitle="Automated analysis of the daily cost record against each AFE: forecasts, creeping cost, unusual days, schedule and record gaps, each with the figures behind it and a suggested next step. Advice only; nothing is changed."
      action={<Box display="flex" gap={1} flexWrap="wrap">
        <Button startIcon={<RefreshRounded/>} onClick={() => void load()} disabled={loading}>{loading ? 'Analysing…' : 'Refresh'}</Button>
        {canExport && <Button startIcon={<DownloadRounded/>} variant="contained" disabled={!data} onClick={event => setExportAnchor(event.currentTarget)}>Export report</Button>}
      </Box>}
    />
    <Menu anchorEl={exportAnchor} open={!!exportAnchor} onClose={() => setExportAnchor(null)}>
      <Box sx={{ px: 2, pt: 1, pb: .5, maxWidth: 320 }}>
        <Typography fontSize={11} fontWeight={800} textTransform="uppercase" letterSpacing=".08em" color="text.secondary">Report contents</Typography>
        <Box display="flex" gap={.5} flexWrap="wrap" my={.75}>
          {Object.entries(REPORT_PRESETS).map(([key, preset]) => <Button key={key} size="small" variant="outlined" onClick={() => setSections(preset.sections)}>{preset.label}</Button>)}
        </Box>
        {REPORT_SECTIONS.map(item => <FormControlLabel key={item.key} sx={{ display: 'flex', m: 0 }}
          control={<Checkbox size="small" checked={sections.includes(item.key)} onChange={() => toggleSection(item.key)}/>}
          label={<Typography fontSize={12.5}>{item.label}</Typography>}/>)}
      </Box>
      <MenuItem disabled={!sections.length} onClick={() => { setExportAnchor(null); setExportOpen(true) }}><PictureAsPdfOutlined fontSize="small" sx={{ mr: 1 }}/>PDF report with charts</MenuItem>
      <MenuItem onClick={() => void exportFile('xlsx')}><DownloadRounded fontSize="small" sx={{ mr: 1 }}/>Excel workbook (findings and wells)</MenuItem>
      <MenuItem onClick={() => void exportFile('csv')}><DownloadRounded fontSize="small" sx={{ mr: 1 }}/>CSV (findings as filtered)</MenuItem>
    </Menu>

    <ErrorMessage message={error}/>
    {notice && <Alert severity="success" onClose={() => setNotice('')} sx={{ mb: 2 }}>{notice}</Alert>}

    <SectionCard bodyPadding={2} sx={{ mb: 2 }}>
      <Box display="flex" gap={1.5} flexWrap="wrap" alignItems="center">
        <FilterListRounded sx={{ fontSize: 17, color: 'text.secondary' }}/>
        <TextField size="small" type="date" label="Cost date from" value={from} onChange={event => setFrom(event.target.value)} InputLabelProps={{ shrink: true }} error={rangeInvalid}/>
        <TextField size="small" type="date" label="Cost date to" value={to} onChange={event => setTo(event.target.value)} InputLabelProps={{ shrink: true }} error={rangeInvalid}
          helperText={rangeInvalid ? 'The end date is before the start date.' : undefined}/>
        <TextField select size="small" label="Well status" value={status} onChange={event => setStatus(event.target.value)} sx={{ minWidth: 160 }}>
          <MenuItem value="">All statuses</MenuItem>
          {WELL_STATUSES.map(item => <MenuItem key={item} value={item}>{trackingLabel(item)}</MenuItem>)}
        </TextField>
        <Button size="small" color="inherit" onClick={() => setAdvanced(value => !value)} endIcon={advanced ? <ExpandLessRounded/> : <ExpandMoreRounded/>}>Finding filters</Button>
        {filtersActive && <Button size="small" color="inherit" onClick={() => { setFrom(''); setTo(''); setStatus(''); setSeverity(''); setCategory(''); setFindingWell(''); setSearch('') }}>Clear all</Button>}
      </Box>
      <Collapse in={advanced} timeout={0}>
        <Box display="flex" gap={1.5} flexWrap="wrap" alignItems="center" mt={1.5}>
          <TextField size="small" label="Search findings" value={search} onChange={event => setSearch(event.target.value)} sx={{ minWidth: 230 }}/>
          <TextField select size="small" label="Severity" value={severity} onChange={event => setSeverity(event.target.value)} sx={{ minWidth: 140 }}>
            <MenuItem value="">All severities</MenuItem>
            {(['critical', 'warning', 'info'] as const).map(item => <MenuItem key={item} value={item}>{SEVERITY_LABEL[item]}</MenuItem>)}
          </TextField>
          <TextField select size="small" label="Subject" value={category} onChange={event => setCategory(event.target.value)} sx={{ minWidth: 190 }}>
            <MenuItem value="">All subjects</MenuItem>
            {Object.entries(CATEGORY_LABEL).map(([key, label]) => <MenuItem key={key} value={key}>{label}</MenuItem>)}
          </TextField>
          <TextField select size="small" label="Well" value={findingWell} onChange={event => setFindingWell(event.target.value)} sx={{ minWidth: 170 }}>
            <MenuItem value="">All wells</MenuItem>
            {wells.slice().sort((a, b) => a.well_code.localeCompare(b.well_code)).map(row => <MenuItem key={row.well_id} value={row.well_id}>{row.well_code}</MenuItem>)}
          </TextField>
        </Box>
      </Collapse>
    </SectionCard>

    {loading && !data && <DatasetState kind="loading" title="Analysing the cost record…"/>}
    {!loading && data && !wells.length && <DatasetState title="No well matches these filters" message="Widen the date range or clear the status filter."/>}

    {data && kpis && wells.length > 0 && <>
      {data.notes.map(note => <Alert key={note} severity="info" sx={{ mb: 1.5 }}>{note}</Alert>)}

      <SectionCard title="Summary" subtitle={`Written from the figures below, as at ${data.as_of}.`} sx={{ mb: 2 }}
        meta={<Tag tone={BAND_TONE[kpis.band]}>{BAND_LABEL[kpis.band]}</Tag>}>
        <Box component="ul" sx={{ m: 0, pl: 2.25, display: 'grid', gap: .5 }}>
          {data.headline.map(line => <Typography key={line} component="li" fontSize={13}>{line}</Typography>)}
        </Box>
      </SectionCard>

      <AiCostReviewPanel
        wells={wells}
        selectedWell={selectedWell}
        dateFrom={from}
        dateTo={to}
        wellStatus={status}
        currency={currency}
        onNavigate={navigate}
        onReviewChange={setAiReview}
      />

      <Box display="grid" gap={1.5} sx={{ gridTemplateColumns: { xs: 'repeat(2, minmax(0, 1fr))', md: 'repeat(3, minmax(0, 1fr))', lg: 'repeat(6, minmax(0, 1fr))' }, mb: 2 }}>
        <StatCard label="Health score" value={`${kpis.score} / 100`} tone={kpis.band === 'good' ? 'positive' : kpis.band === 'watch' ? 'warning' : 'error'}
          hint="AFE-weighted average of the wells; 100 less 25 per critical, 10 per warning, 3 per note"/>
        <StatCard
          label="Actual / AFE %"
          value={(() => {
            const pct = kpis.utilisation_percent ?? (kpis.afe_amount && kpis.actual_amount != null ? (kpis.actual_amount / kpis.afe_amount) * 100 : null)
            return pct != null ? `${pct.toFixed(1)}%` : '—'
          })()}
          tone={((kpis.utilisation_percent ?? 0) > 100) ? 'error' : 'positive'}
          hint={`${amount(kpis.actual_amount, currency)} of ${amount(kpis.afe_amount, currency)}`}/>
        <StatCard label="Forecast at completion" value={amount(kpis.forecast_amount, currency)}
          tone={(kpis.forecast_variance ?? 0) > 0 ? 'error' : 'default'}
          hint={kpis.forecast_variance === null ? 'Needs AFE and daily cost access' : `${signedPercent(kpis.forecast_variance_percent)} against a combined AFE of ${amount(kpis.afe_amount, currency)}`}/>
        <StatCard label="Cost above AFE" value={amount(kpis.amount_at_risk, currency)} tone={kpis.amount_at_risk ? 'error' : 'default'}
          hint="Recorded or forecast overrun, summed over the wells"/>
        <StatCard label="Analysis findings" value={`${kpis.critical + kpis.warning}`} tone={kpis.critical ? 'error' : kpis.warning ? 'warning' : 'positive'}
          hint={`${kpis.critical} critical, ${kpis.warning} warning, ${kpis.info} note(s) · includes read`}/>
        <StatCard label="Wells at risk" value={`${kpis.wells_at_risk} of ${kpis.wells}`} tone={kpis.wells_at_risk ? 'error' : 'positive'}
          hint={`${kpis.analysed_wells} analysed day by day`}/>
      </Box>

      <Box display="grid" gap={2} sx={{ gridTemplateColumns: { xs: '1fr', lg: 'minmax(0, 3fr) minmax(0, 2fr)' }, mb: 2 }}>
        <ChartPanel figureKey="ci-forecast" title="Forecast against AFE" height={300}
          subtitle="Select a well's bars or its row to analyse that well below."
          empty={!forecastRows.length} emptyMessage="No AFE or recorded cost in scope."
          caption={`AFE, recorded cost and forecast at completion in ${currency || 'the reporting currency'}. Forecast = recorded cost plus the recent daily rate for the remaining planned days.`}>
          <InteractiveChart option={forecastOption} notMerge lazyUpdate style={{ height: '100%', width: '100%' }} onEvents={{ click: selectForecastWell }}/>
        </ChartPanel>
        <ChartPanel figureKey="ci-findings" title="Findings by subject" height={300}
          subtitle="Select a subject to filter the findings list."
          empty={!data.findings.length} emptyMessage="No finding in the analysed record."
          caption="Count of findings by subject and severity.">
          <InteractiveChart option={categoryOption} notMerge lazyUpdate style={{ height: '100%', width: '100%' }} onEvents={{ click: selectCategory }}/>
        </ChartPanel>
      </Box>

      <SectionCard title="Suggested actions" subtitle="The findings that need a decision, ranked by severity and then by the amount involved." bodyPadding={0} sx={{ mb: 2 }}>
        {suggestions.length === 0
          ? <Box p={3}><Typography color="text.secondary" fontSize={13}>Nothing needs action in the analysed record.</Typography></Box>
          : <TableContainer><Table size="small">
            <TableHead><TableRow>
              <TableCell width={36}>#</TableCell><TableCell>Well</TableCell><TableCell>Finding</TableCell><TableCell>Suggested action</TableCell>
              <TableCell align="right">Amount ({currency})</TableCell><TableCell align="right">Go to</TableCell>
            </TableRow></TableHead>
            <TableBody>{suggestions.map(row => <TableRow key={row.finding_id} hover>
              <TableCell>{row.rank}</TableCell>
              <TableCell><Button size="small" onClick={() => setWellId(row.well_id)} sx={{ minWidth: 0, px: .5 }}>{row.well_code}</Button></TableCell>
              <TableCell sx={{ maxWidth: 300 }}><Box display="flex" gap={1} alignItems="center"><Tag tone={SEVERITY_TONE[row.severity]}>{SEVERITY_LABEL[row.severity]}</Tag><Typography fontSize={12.5} fontWeight={700}>{row.title}</Typography></Box></TableCell>
              <TableCell sx={{ maxWidth: 460 }}><Typography fontSize={12.5}>{row.suggestion}</Typography></TableCell>
              <TableCell align="right">{amount(row.amount)}</TableCell>
              <TableCell align="right">{row.action_path && <Tooltip title={row.action_label}><IconButton size="small" aria-label={row.action_label} onClick={() => navigate(row.action_path)}><OpenInNewRounded sx={{ fontSize: 16 }}/></IconButton></Tooltip>}</TableCell>
            </TableRow>)}</TableBody>
          </Table></TableContainer>}
      </SectionCard>

      <SectionCard title="Well health" subtitle="Lowest score first. Select a well to analyse it." bodyPadding={0} sx={{ mb: 2 }}>
        <TableContainer><Table size="small">
          <TableHead><TableRow>
            <TableCell>Well</TableCell><TableCell>Status</TableCell><TableCell>Health</TableCell>
            <TableCell align="right">AFE ({currency})</TableCell><TableCell align="right">Recorded</TableCell>
            <TableCell align="right">Actual / AFE %</TableCell>
            <TableCell align="right">Forecast</TableCell><TableCell align="right">vs AFE</TableCell>
            <TableCell align="right">Findings</TableCell><TableCell>Reading</TableCell>
          </TableRow></TableHead>
          <TableBody>{wells.map(row => <TableRow key={row.well_id} hover selected={row.well_id === wellId} onClick={() => setWellId(row.well_id)} sx={{ cursor: 'pointer' }}>
            <TableCell><Typography fontSize={12.5} fontWeight={700}>{row.well_code}</Typography><Typography fontSize={10.5} color="text.secondary">{row.well_name}</Typography></TableCell>
            <TableCell>{trackingLabel(row.status)}</TableCell>
            <TableCell><Tag tone={BAND_TONE[row.band]}>{row.score} · {BAND_LABEL[row.band]}</Tag></TableCell>
            <TableCell align="right">{amount(row.afe_amount)}</TableCell>
            <TableCell align="right">{amount(row.actual_amount)}</TableCell>
            <TableCell align="right" sx={{ fontWeight: 700, color: (row.utilisation_percent ?? 0) > 100 ? 'error.main' : 'text.primary' }}>
              {row.utilisation_percent != null ? `${row.utilisation_percent.toFixed(1)}%` : '—'}
            </TableCell>
            <TableCell align="right">{row.forecast.available ? amount(row.forecast.estimate) : '—'}</TableCell>
            <TableCell align="right" sx={{ color: (row.forecast.variance_percent ?? 0) > 0 ? 'error.main' : 'text.primary' }}>{signedPercent(row.forecast.variance_percent)}</TableCell>
            <TableCell align="right">{row.critical + row.warning}{row.info ? ` + ${row.info}` : ''}</TableCell>
            <TableCell sx={{ maxWidth: 420 }}><Typography fontSize={12} color="text.secondary">{row.analysed ? row.summary : 'Budget position only; filter to this well for the day-by-day analysis.'}</Typography></TableCell>
          </TableRow>)}</TableBody>
        </Table></TableContainer>
      </SectionCard>

      <SectionCard sx={{ mb: 2 }}
        title={selectedWell ? `Well analysis: ${selectedWell.well_code}` : 'Well analysis'}
        subtitle={detail?.well.summary ?? 'Select a well above to see its daily cost, forecast and trend.'}
        meta={selectedWell && <Tag tone={BAND_TONE[selectedWell.band]}>{selectedWell.score} · {BAND_LABEL[selectedWell.band]}</Tag>}
        action={<TextField select size="small" label="Well" value={wellId} onChange={event => setWellId(event.target.value)} sx={{ minWidth: 190 }}>
          {wells.map(row => <MenuItem key={row.well_id} value={row.well_id}>{row.well_code}</MenuItem>)}
        </TextField>}>
        <ErrorMessage message={detailError}/>
        {detailLoading && !detail && <DatasetState kind="loading" compact title="Analysing the well…"/>}
        {detail && <>
          {detail.notes.map(note => <Alert key={note} severity="info" sx={{ mb: 1.5 }}>{note}</Alert>)}
          {detail.missing_dates.length > 0 && <Alert severity="warning" sx={{ mb: 1.5 }}>
            No sheet for {detail.missing_dates.slice(0, 8).join(', ')}{detail.missing_dates.length > 8 ? ` and ${detail.missing_dates.length - 8} more` : ''}.
          </Alert>}
          <Box display="grid" gap={2} sx={{ gridTemplateColumns: { xs: '1fr', lg: 'repeat(2, minmax(0, 1fr))' } }}>
            <ChartPanel figureKey="ci-well-daily" title="Daily cost" height={260} empty={!days.length}
              emptyMessage="No daily cost recorded for this well in the selected dates."
              caption="Flagged days are drawn in the alert colour. The dashed line is the opening baseline the trend is measured against.">
              <InteractiveChart option={dailyOption} notMerge lazyUpdate style={{ height: '100%', width: '100%' }}/>
            </ChartPanel>
            <ChartPanel figureKey="ci-well-cumulative" title="Cumulative cost and forecast" height={260} empty={!days.length}
              emptyMessage="No daily cost recorded for this well in the selected dates."
              caption={detail.well.forecast.available
                ? `Forecast ${amount(detail.well.forecast.estimate, currency)} (range ${amount(detail.well.forecast.low)} to ${amount(detail.well.forecast.high)}) at ${amount(detail.well.forecast.recent_daily, currency)} a day for ${detail.well.forecast.remaining_days ?? 0} remaining planned day(s).`
                : detail.well.forecast.reason || 'No forecast is available for this well.'}>
              <InteractiveChart option={cumulativeOption} notMerge lazyUpdate style={{ height: '100%', width: '100%' }}/>
            </ChartPanel>
            <Box sx={{ gridColumn: { lg: '1 / -1' } }}>
              <ChartPanel figureKey="ci-well-trend" title="Trend statistic" height={220} empty={!trendAvailable}
                emptyMessage="The trend check needs at least 12 recorded days."
                caption={detail.drift_start
                  ? `Sustained change of operational daily level estimated from ${detail.drift_start}. Lump-sum tangibles are excluded so end-of-scope bookings do not distort trend monitoring.`
                  : 'Both lines stay under the dashed limit: the daily operational cost has held its opening level.'}>
                <InteractiveChart option={trendOption} notMerge lazyUpdate style={{ height: '100%', width: '100%' }}/>
              </ChartPanel>
            </Box>
          </Box>
          {detail.breakdown && <Box mt={2.5} display="grid" gap={2}>
            <Box display="grid" gap={1.3} sx={{ gridTemplateColumns: { xs: 'repeat(2, minmax(0, 1fr))', md: 'repeat(5, minmax(0, 1fr))' } }}>
              <StatCard
                label="Operational vs Tangibles"
                value={amount(detail.breakdown.unit_economics.operational_actual, currency)}
                hint={`Tangibles: ${amount(detail.breakdown.unit_economics.tangible_actual, currency)}${detail.breakdown.unit_economics.tangible_utilisation_percent != null ? ` (${detail.breakdown.unit_economics.tangible_utilisation_percent.toFixed(1)}% of tangible AFE)` : ''}`}
              />
              <StatCard
                label="Operational daily avg"
                value={amount(detail.breakdown.unit_economics.operational_daily_avg, currency)}
                hint={detail.breakdown.unit_economics.planned_operational_daily != null
                  ? `Planned daily: ${amount(detail.breakdown.unit_economics.planned_operational_daily, currency)}`
                  : 'Recurring operational burn / day'}
              />
              <StatCard
                label="Cost Performance (CPI)"
                value={detail.breakdown.unit_economics.burn_efficiency_index != null
                  ? detail.breakdown.unit_economics.burn_efficiency_index.toFixed(2)
                  : '—'}
                tone={detail.breakdown.unit_economics.burn_efficiency_index == null ? 'default'
                  : detail.breakdown.unit_economics.burn_efficiency_index >= 1 ? 'positive' : 'warning'}
                hint=">1.00 under operational plan · <1.00 over-burning"
              />
              <StatCard
                label="Cost per metre"
                value={detail.breakdown.unit_economics.cost_per_meter != null
                  ? amount(detail.breakdown.unit_economics.cost_per_meter, currency)
                  : '—'}
                hint={detail.breakdown.unit_economics.depth_progress_percent != null
                  ? `${detail.breakdown.unit_economics.actual_depth ?? 0} m (${detail.breakdown.unit_economics.depth_progress_percent.toFixed(1)}% of target)`
                  : 'Requires recorded hole depth'}
              />
              <StatCard
                label="NPT / UPA share"
                value={`${detail.well.npt_share_percent != null ? `${detail.well.npt_share_percent.toFixed(1)}%` : '0.0%'} / ${detail.breakdown.unit_economics.upa_share_percent != null ? `${detail.breakdown.unit_economics.upa_share_percent.toFixed(1)}%` : '0.0%'}`}
                tone={((detail.well.npt_share_percent ?? 0) >= 10 || (detail.breakdown.unit_economics.upa_share_percent ?? 0) >= 10) ? 'warning' : 'default'}
                hint={detail.breakdown.unit_economics.top_cost_driver || 'Non-productive & unplanned cost shares'}
              />
            </Box>
            {detail.breakdown.cost_groups.length > 0 && <Box display="grid" gap={2} sx={{ gridTemplateColumns: { xs: '1fr', lg: 'repeat(2, minmax(0, 1fr))' } }}>
              <TableContainer sx={{ border: '1px solid', borderColor: 'divider', borderRadius: 2 }}>
                <Table size="small">
                  <TableHead><TableRow>
                    <TableCell>Cost group</TableCell>
                    <TableCell align="right">AFE ({currency})</TableCell>
                    <TableCell align="right">Actual</TableCell>
                    <TableCell align="right">Actual / AFE %</TableCell>
                    <TableCell align="right">Share</TableCell>
                  </TableRow></TableHead>
                  <TableBody>{detail.breakdown.cost_groups.map(grp => <TableRow key={grp.label} hover>
                    <TableCell sx={{ fontWeight: 700 }}>{grp.label}</TableCell>
                    <TableCell align="right">{amount(grp.planned)}</TableCell>
                    <TableCell align="right">{amount(grp.actual)}</TableCell>
                    <TableCell align="right" sx={{ fontWeight: 700, color: (grp.utilisation_percent ?? 0) > 105 ? 'error.main' : 'text.primary' }}>
                      {grp.utilisation_percent != null ? `${grp.utilisation_percent.toFixed(1)}%` : '—'}
                    </TableCell>
                    <TableCell align="right">{grp.share_percent != null ? `${grp.share_percent.toFixed(1)}%` : '—'}</TableCell>
                  </TableRow>)}</TableBody>
                </Table>
              </TableContainer>
              {detail.breakdown.activities.length > 0 && <TableContainer sx={{ border: '1px solid', borderColor: 'divider', borderRadius: 2 }}>
                <Table size="small">
                  <TableHead><TableRow>
                    <TableCell>Top cost-driving activities</TableCell>
                    <TableCell>Class</TableCell>
                    <TableCell align="right">Days</TableCell>
                    <TableCell align="right">Actual ({currency})</TableCell>
                    <TableCell align="right">Share</TableCell>
                  </TableRow></TableHead>
                  <TableBody>{detail.breakdown.activities.slice(0, 6).map((act, idx) => <TableRow key={`${act.activity_code}-${idx}`} hover>
                    <TableCell>{act.activity_name || act.activity_code}</TableCell>
                    <TableCell><Tag tone={act.classification === 'NPT' ? 'error' : act.classification === 'UPA' ? 'warning' : 'neutral'}>{act.classification}</Tag></TableCell>
                    <TableCell align="right">{act.active_days}</TableCell>
                    <TableCell align="right">{amount(act.amount)}</TableCell>
                    <TableCell align="right">{act.share_percent != null ? `${act.share_percent.toFixed(1)}%` : '—'}</TableCell>
                  </TableRow>)}</TableBody>
                </Table>
              </TableContainer>}
            </Box>}
          </Box>}
        </>}
      </SectionCard>

      <SectionCard title="Findings" bodyPadding={0}
        subtitle="Open a row for its basis and read actions. Scores and charts include all findings, including those marked read."
        meta={<Typography fontSize={12} color="text.secondary">{findings.length} of {data.findings.length}</Typography>}>
        <Box px={2} py={1}>
          {stateError && <Alert severity="error" role="alert">{stateError}</Alert>}
          <FormControlLabel control={<Checkbox checked={showRead} onChange={event => setShowRead(event.target.checked)}/>} label="Show acknowledged and dismissed findings"/>
          <Typography fontSize={12} color="text.secondary">Read state is personal to you and specific to the finding and well. Restore a finding to return it to the action queue.</Typography>
        </Box>
        <TableContainer><Table size="small">
          <TableHead><TableRow>
            <TableCell width={40}/><TableCell>Severity</TableCell><TableCell>Well</TableCell><TableCell>Subject</TableCell>
            <TableCell>Finding</TableCell><TableCell>Cost date</TableCell><TableCell align="right">Amount ({currency})</TableCell>
          </TableRow></TableHead>
          <TableBody>
            {pageFindings.length === 0 && <TableRow><TableCell colSpan={7} align="center" sx={{ py: 5, color: 'text.secondary' }}>
              {data.findings.length ? 'No finding matches these filters.' : 'No finding in the analysed record.'}
            </TableCell></TableRow>}
            {pageFindings.map(row => {
              const open = expanded === row.id
              return [
                <TableRow key={row.id} hover onClick={() => setExpanded(open ? '' : row.id)} sx={{ cursor: 'pointer' }}>
                  <TableCell><IconButton size="small" aria-label={open ? 'Hide the basis' : 'Show the basis'} aria-expanded={open}>{open ? <ExpandLessRounded fontSize="small"/> : <ExpandMoreRounded fontSize="small"/>}</IconButton></TableCell>
                  <TableCell><Tag tone={SEVERITY_TONE[row.severity]}>{SEVERITY_LABEL[row.severity]}</Tag></TableCell>
                  <TableCell>{row.well_code}</TableCell>
                  <TableCell>{CATEGORY_LABEL[row.category]}</TableCell>
                  <TableCell sx={{ maxWidth: 520 }}><Typography fontSize={12.5} fontWeight={700}>{row.title}</Typography>{readStates[row.id] && <Tag>{readStates[row.id]}</Tag>}<Typography fontSize={12} color="text.secondary">{row.detail}</Typography></TableCell>
                  <TableCell>{row.cost_date ?? '—'}</TableCell>
                  <TableCell align="right">{amount(row.amount)}</TableCell>
                </TableRow>,
                open && <TableRow key={`${row.id}-basis`}>
                  <TableCell/>
                  <TableCell colSpan={6} sx={{ bgcolor: 'background.default' }}>
                    <Box display="grid" gap={1} py={1}>
                      <Typography fontSize={12.5}><strong>Suggested action.</strong> {row.suggestion}</Typography>
                      <Typography fontSize={12.5}><strong>How it was derived.</strong> {row.basis}</Typography>
                      {row.evidence.length > 0 && <Box display="flex" gap={3} flexWrap="wrap">
                        {row.evidence.map(item => <Box key={item.label}><Typography fontSize={10.5} color="text.secondary" textTransform="uppercase" letterSpacing=".06em">{item.label}</Typography><Typography fontSize={13} fontWeight={700}>{item.value}</Typography></Box>)}
                      </Box>}
                      <Box display="flex" gap={1}>
                        {readStates[row.id]
                          ? <Button size="small" disabled={Boolean(stateBusy)} onClick={() => void markFinding(row.id, 'unread')}>Mark unread</Button>
                          : <><Button size="small" disabled={Boolean(stateBusy)} onClick={() => void markFinding(row.id, 'acknowledged')}>Acknowledge</Button><Button size="small" disabled={Boolean(stateBusy)} onClick={() => void markFinding(row.id, 'dismissed')}>Dismiss</Button></>}
                        <Button size="small" onClick={() => setWellId(row.well_id)}>Analyse {row.well_code}</Button>
                        {row.action_path && <Button size="small" startIcon={<OpenInNewRounded sx={{ fontSize: 15 }}/>} onClick={() => navigate(row.action_path)}>{row.action_label}</Button>}
                      </Box>
                    </Box>
                  </TableCell>
                </TableRow>,
              ]
            })}
          </TableBody>
        </Table></TableContainer>
        <TablePagination component="div" count={findings.length} page={page} rowsPerPage={pageSize} rowsPerPageOptions={PAGE_SIZES}
          onPageChange={(_, value) => setPage(value)} onRowsPerPageChange={event => { setPageSize(Number(event.target.value)); setPage(0) }}/>
      </SectionCard>

      <SectionCard title="How the analysis works" sx={{ mt: 2 }}>
        <Box component="ul" sx={{ m: 0, pl: 2.25, display: 'grid', gap: .5 }}>
          {data.methods.map(line => <Typography key={line} component="li" fontSize={12.5} color="text.secondary">{line}</Typography>)}
        </Box>
      </SectionCard>
    </>}

    <ExportReportDialog
      open={exportOpen}
      onClose={() => setExportOpen(false)}
      figures={FIGURES}
      buildDocument={buildDocument}
      onExport={(format, recordCount) => recordExport(format, recordCount)}
      fileName="cost-intelligence-report"
      title="Export the Cost Intelligence report"
    />
  </>
}
