import { useCallback, useEffect, useMemo, useRef, useState, type ReactNode } from 'react'
import { Link as RouterLink } from 'react-router-dom'
import type { EChartsOption } from 'echarts'
import {
  AccountBalanceWalletOutlined, AlignVerticalBottomRounded, ArrowForwardRounded, CalendarMonthOutlined,
  DescriptionOutlined, DownloadDoneRounded, EventBusyOutlined, LayersOutlined,
  RefreshRounded, ReportProblemOutlined, ScheduleOutlined, SpeedOutlined,
  TerrainOutlined, TrendingUpRounded, WarningAmberRounded,
} from '@mui/icons-material'
import {
  Alert, Box, Button, FormControlLabel, LinearProgress, MenuItem, Paper,
  Switch, Tab, Tabs, TextField, Tooltip, Typography, useTheme,
} from '@mui/material'
import type { ColDef, ICellRendererParams } from 'ag-grid-community'
import { DataTable } from '../components/DataTable'
import { ErrorMessage, PageHeading, Tag } from '../components/Common'
import { ChartPanel } from '../components/ui/ChartPanel'
import { InteractiveChart } from '../components/ui/InteractiveChart'
import { DatasetState } from '../components/ui/DatasetState'
import { SectionCard } from '../components/ui/SectionCard'
import { StatCard } from '../components/ui/StatCard'
import { DrillThroughPanel } from '../components/business-dashboard/DrillThroughPanel'
import { useAuth } from '../context/AuthContext'
import { useColorMode } from '../context/ThemeContext'
import { api, body } from '../lib/api'
import { chartPalette } from '../designSystem'
import {
  AFE_STATUS_LABELS, currentYearFilters, EMPTY_FILTERS, compactMoney, count, dashboardQuery, decimal, displayDate,
  displayDateTime, money, percent, presetRange,
  type BusinessDashboard as BusinessDashboardData, type DashboardAfeRow, type DashboardFilters,
  type DashboardRigRow, type DashboardWellRow, type Money,
} from '../lib/businessDashboard'

function BalanceCell({ value, currency }: { value: Money; currency: string }) {
  const negative = value !== null && Number(value) < 0
  return <Typography component="span" fontSize={12} fontWeight={700} color={negative ? 'error.main' : 'text.primary'}>{money(value, currency)}</Typography>
}

function DepthCell({ row }: { row: DashboardWellRow }) {
  const value = row.depth_progress_percent === null ? null : Math.min(100, Math.max(0, Number(row.depth_progress_percent)))
  return <Box minWidth={130} py={.6}>
    <Box display="flex" justifyContent="space-between" gap={1}>
      <Typography fontSize={11.5} fontWeight={700}>{percent(row.depth_progress_percent)}</Typography>
      <Typography fontSize={10.5} color="text.secondary">
        {decimal(row.actual_depth, 0)} / {decimal(row.planned_depth, 0)} m
      </Typography>
    </Box>
    <LinearProgress
      variant="determinate"
      value={value ?? 0}
      aria-label={`Depth progress ${percent(row.depth_progress_percent)}`}
      sx={{
        mt: .5, height: 5, borderRadius: 3, bgcolor: 'divider',
        '& .MuiLinearProgress-bar': { transition: 'none', bgcolor: value !== null && value >= 100 ? 'success.main' : 'primary.main' },
      }}
    />
  </Box>
}

export default function BusinessDashboard() {
  const { can } = useAuth()
  const { mode } = useColorMode()
  const theme = useTheme()
  const palette = useMemo(() => chartPalette(mode), [mode])
  const [filters, setFilters] = useState<DashboardFilters>(currentYearFilters())
  const [data, setData] = useState<BusinessDashboardData | null>(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState('')
  const [tab, setTab] = useState(0)
  const [drillWell, setDrillWell] = useState('')
  const [autoRefresh, setAutoRefresh] = useState(false)
  const [refreshedAt, setRefreshedAt] = useState<Date | null>(null)
  const requestVersion = useRef(0)
  const [filtersOpen, setFiltersOpen] = useState(false)

  const load = useCallback(async (silent = false) => {
    const version = ++requestVersion.current
    if (!silent) setLoading(true)
    setError('')
    try {
      const query = dashboardQuery(filters)
      const result = await api<BusinessDashboardData>(`/dashboard/business${query ? `?${query}` : ''}`)
      if (version !== requestVersion.current) return
      setData(result)
      setRefreshedAt(new Date())
    } catch (caught) {
      if (version !== requestVersion.current) return
      setError(caught instanceof Error ? caught.message : 'The business dashboard could not be loaded')
    } finally {
      if (version === requestVersion.current) setLoading(false)
    }
  }, [filters])

  useEffect(() => { void load() }, [load])

  // "Real time" here means the page re-reads the ledger on a fixed interval;
  // the switch is off by default so a shared screen is not hammering the API.
  useEffect(() => {
    if (!autoRefresh) return
    const timer = window.setInterval(() => { void load(true) }, 60_000)
    return () => window.clearInterval(timer)
  }, [autoRefresh, load])

  const setFilter = <K extends keyof DashboardFilters>(key: K, value: DashboardFilters[K]) => {
    setFilters(previous => {
      const next = { ...previous, [key]: value }
      // Keep dependent pickers honest: a new rig clears a well from another rig.
      if (key === 'rig' && previous.well) {
        const well = data?.filters.wells.find(item => item.id === previous.well)
        if (well && well.rig_id !== value) next.well = ''
      }
      if (key === 'well' && value) {
        const well = data?.filters.wells.find(item => item.id === value)
        if (well) next.rig = well.rig_id
      }
      return next
    })
  }

  const currency = data?.currency || filters.currency
  const caps = data?.capabilities ?? { plan: false, budget: false, actuals: false }
  const canExport = can('rig-well:export') || can('afe:export') || can('daily-cost:export')

  const wellOptions = useMemo(() => (data?.filters.wells ?? []).filter(well => !filters.rig || well.rig_id === filters.rig), [data, filters.rig])
  const afeOptions = useMemo(() => (data?.filters.afes ?? []).filter(afe =>
    (!filters.rig || afe.rig_id === filters.rig) && (!filters.well || afe.well_id === filters.well)
  ), [data, filters.rig, filters.well])

  // ---- chart data ------------------------------------------------------------
  const chartWells = useMemo(() => [...(data?.wells ?? [])]
    .filter(row => Number(row.effective_afe_amount ?? row.actual_amount ?? 0) > 0)
    .sort((a, b) => Number(b.effective_afe_amount ?? b.actual_amount ?? 0) - Number(a.effective_afe_amount ?? a.actual_amount ?? 0))
    .slice(0, 10), [data])

  const daysWells = useMemo(() => [...(data?.wells ?? [])]
    .sort((a, b) => Number(b.actual_days ?? 0) - Number(a.actual_days ?? 0))
    .slice(0, 10), [data])

  const axis = useMemo(() => ({
    text: theme.palette.text.secondary,
    line: theme.palette.divider,
  }), [theme])

  const costOption: EChartsOption = useMemo(() => {
    const rows = [...chartWells].reverse()
    const series: EChartsOption['series'] = []
    if (caps.budget) {
      series.push({
        name: 'AFE amount', type: 'bar', barMaxWidth: 12,
        itemStyle: { color: palette.planned, opacity: .45 },
        data: rows.map(row => Number(row.afe_amount ?? 0)),
      })
      if (rows.some(row => row.has_sow_adjustment)) {
        series.push({
          name: 'SOW adjusted', type: 'bar', barMaxWidth: 12,
          itemStyle: { color: palette.adjusted },
          data: rows.map(row => row.sow_adjusted_amount === null ? '-' : Number(row.sow_adjusted_amount)),
        })
      }
    }
    if (caps.actuals) {
      series.push({
        name: 'Actual cost', type: 'bar', barMaxWidth: 12,
        itemStyle: { color: palette.actual },
        data: rows.map(row => Number(row.actual_amount ?? 0)),
      })
    }
    return {
      animation: false,
      grid: { left: 8, right: 26, top: 30, bottom: 8, containLabel: true },
      legend: { top: 0, textStyle: { color: axis.text }, itemWidth: 12, itemHeight: 8 },
      tooltip: {
        trigger: 'axis', axisPointer: { type: 'shadow' },
        valueFormatter: value => (value === '-' ? '—' : money(String(value ?? 0), currency)),
      },
      xAxis: { type: 'value', axisLabel: { color: axis.text, fontSize: 10.5 }, splitLine: { lineStyle: { color: axis.line } } },
      yAxis: {
        type: 'category',
        data: rows.map(row => row.well_code),
        axisLabel: { color: axis.text, fontSize: 10.5, width: 110, overflow: 'truncate' },
        axisLine: { lineStyle: { color: axis.line } },
      },
      series,
    }
  }, [chartWells, caps, currency, palette, axis])

  const daysOption: EChartsOption = useMemo(() => {
    const rows = [...daysWells].reverse()
    return {
      animation: false,
      grid: { left: 8, right: 30, top: 30, bottom: 8, containLabel: true },
      legend: { top: 0, textStyle: { color: axis.text }, itemWidth: 12, itemHeight: 8 },
      tooltip: {
        trigger: 'axis', axisPointer: { type: 'shadow' },
        valueFormatter: value => `${Number(value ?? 0).toLocaleString()} d`,
      },
      xAxis: { type: 'value', axisLabel: { color: axis.text, fontSize: 10.5 }, splitLine: { lineStyle: { color: axis.line } } },
      yAxis: {
        type: 'category',
        data: rows.map(row => row.well_code),
        axisLabel: { color: axis.text, fontSize: 10.5, width: 110, overflow: 'truncate' },
        axisLine: { lineStyle: { color: axis.line } },
      },
      series: caps.actuals ? [
        {
          name: 'Productive days', type: 'bar', stack: 'days', barMaxWidth: 16,
          itemStyle: { color: palette.series[2] },
          data: rows.map(row => Math.max((row.actual_days ?? 0) - Number(row.npt_days ?? 0) - Number(row.upa_days ?? 0), 0)),
        },
        {
          name: 'UPA days', type: 'bar', stack: 'days', barMaxWidth: 16,
          itemStyle: { color: palette.series[1] },
          data: rows.map(row => Number(row.upa_days ?? 0)),
        },
        {
          name: 'NPT days', type: 'bar', stack: 'days', barMaxWidth: 16,
          itemStyle: { color: palette.series[3] },
          data: rows.map(row => Number(row.npt_days ?? 0)),
        },
        ...(caps.plan ? [{
          name: 'Planned days', type: 'scatter' as const, symbol: 'diamond', symbolSize: 11,
          itemStyle: { color: palette.planned },
          data: rows.map(row => Number(row.planned_days ?? 0)),
        }] : []),
      ] : [],
    }
  }, [daysWells, caps, palette, axis])

  const trendOption: EChartsOption = useMemo(() => {
    const rows = data?.daily ?? []
    return {
      animation: false,
      grid: { left: 12, right: 16, top: 30, bottom: 26, containLabel: true },
      legend: { top: 0, textStyle: { color: axis.text }, itemWidth: 12, itemHeight: 8 },
      tooltip: { trigger: 'axis', valueFormatter: value => money(String(value ?? 0), currency) },
      xAxis: {
        type: 'category',
        data: rows.map(row => row.cost_date.slice(5)),
        axisLabel: { color: axis.text, fontSize: 10.5 },
        axisLine: { lineStyle: { color: axis.line } },
      },
      yAxis: { type: 'value', axisLabel: { color: axis.text, fontSize: 10.5 }, splitLine: { lineStyle: { color: axis.line } } },
      series: [
        {
          name: 'Daily actual', type: 'bar', barMaxWidth: 14,
          itemStyle: { color: palette.series[0], opacity: .65 },
          data: rows.map(row => Number(row.actual)),
        },
        {
          name: 'Cumulative actual', type: 'line', smooth: true, symbol: 'none',
          itemStyle: { color: palette.actual }, lineStyle: { width: 2.2, color: palette.actual },
          areaStyle: { color: `${palette.actual}20` },
          data: rows.map(row => Number(row.cumulative)),
        },
      ],
    }
  }, [data, currency, palette, axis])

  const mixOption: EChartsOption = useMemo(() => {
    const rows = (data?.cost_groups ?? []).filter(row => Number(row.actual ?? 0) > 0)
    return {
      animation: false,
      tooltip: { trigger: 'item', valueFormatter: value => money(String(value ?? 0), currency) },
      legend: { bottom: 0, textStyle: { color: axis.text }, itemWidth: 12, itemHeight: 8 },
      series: [{
        type: 'pie',
        radius: ['50%', '74%'],
        center: ['50%', '43%'],
        label: { show: false },
        itemStyle: { borderColor: theme.palette.background.paper, borderWidth: 2 },
        data: rows.map((row, index) => ({
          name: row.label, value: Number(row.actual ?? 0), itemStyle: { color: palette.series[index % palette.series.length] },
        })),
      }],
    }
  }, [data, currency, theme.palette.background.paper, palette, axis])

  const depthOption: EChartsOption = useMemo(() => {
    const rows = [...(data?.wells ?? [])]
      .filter(row => row.depth_progress_percent !== null)
      .sort((a, b) => Number(a.depth_progress_percent ?? 0) - Number(b.depth_progress_percent ?? 0))
      .slice(-10)
    return {
      animation: false,
      grid: { left: 8, right: 48, top: 8, bottom: 8, containLabel: true },
      tooltip: {
        trigger: 'axis', axisPointer: { type: 'shadow' },
        formatter: (params: unknown) => {
          const items = params as { dataIndex: number }[]
          const row = rows[items[0]?.dataIndex ?? 0]
          if (!row) return ''
          return `${row.well_code}<br/>${percent(row.depth_progress_percent)} · ${decimal(row.actual_depth, 0)} of ${decimal(row.planned_depth, 0)} m`
        },
      },
      xAxis: { type: 'value', max: 100, axisLabel: { color: axis.text, fontSize: 10.5, formatter: '{value}%' }, splitLine: { lineStyle: { color: axis.line } } },
      yAxis: {
        type: 'category',
        data: rows.map(row => row.well_code),
        axisLabel: { color: axis.text, fontSize: 10.5, width: 110, overflow: 'truncate' },
        axisLine: { lineStyle: { color: axis.line } },
      },
      series: [{
        type: 'bar', barMaxWidth: 14,
        itemStyle: {
          color: (params: { dataIndex: number }) => Number(rows[params.dataIndex]?.depth_progress_percent ?? 0) >= 100
            ? palette.series[2] : palette.series[0],
          borderRadius: [0, 3, 3, 0],
        },
        label: { show: true, position: 'right', color: axis.text, fontSize: 10.5, formatter: '{c}%' },
        data: rows.map(row => Number(row.depth_progress_percent ?? 0)),
      }],
    }
  }, [data, palette, axis])

  const drillFromChart = (params: { dataIndex?: number }, rows: { well_id: string }[]) => {
    const row = rows[params.dataIndex ?? -1]
    if (row) setDrillWell(row.well_id)
  }

  // ---- table columns ---------------------------------------------------------
  const wellColumns: ColDef<DashboardWellRow>[] = useMemo(() => {
    const columns: ColDef<DashboardWellRow>[] = [
      { headerName: 'RIG', field: 'rig_code', minWidth: 110, flex: 0.6 },
      {
        headerName: 'WELL', field: 'well_code', minWidth: 190, flex: 1.2,
        cellRenderer: (params: ICellRendererParams<DashboardWellRow>) => params.data && <Box minWidth={0}>
          <Typography fontSize={12.5} fontWeight={700} noWrap>{params.data.well_code}</Typography>
          <Typography fontSize={10.5} color="text.secondary" noWrap>{params.data.well_name}</Typography>
        </Box>,
      },
      {
        headerName: 'STATUS', field: 'status', minWidth: 130, flex: 0.7,
        cellRenderer: (params: ICellRendererParams<DashboardWellRow>) => params.data && <Tag tone={params.data.status === 'completed' ? 'info' : 'success'}>
          {params.data.status === 'completed' ? 'Completed' : 'Active'}
        </Tag>,
      },
    ]
    if (caps.plan) {
      columns.push({
        headerName: 'PLANNED DAYS', field: 'planned_days', minWidth: 140, flex: 0.7,
        headerTooltip: 'Planned days from the well configuration (drilling + configured completion). An approved plan adjustment replaces the configured count.',
        valueFormatter: params => decimal(String(params.value ?? ''), 2),
        cellRenderer: (params: ICellRendererParams<DashboardWellRow>) => params.data && <Box>
          <Typography fontSize={12.5} fontWeight={700}>{decimal(params.data.planned_days, 2)}</Typography>
          <Typography fontSize={10} color="text.secondary">{decimal(params.data.drilling_planned_days, 2)} drilling{params.data.completion_planned_days ? ` · ${decimal(params.data.completion_planned_days, 2)} completion` : ''}</Typography>
        </Box>,
      })
    }
    if (caps.actuals) {
      columns.push({
        headerName: 'ACTUAL DAYS', field: 'actual_days', minWidth: 140, flex: 0.8,
        headerTooltip: 'Calendar days from the first to the last day of the cost register, including any missing sheet inside that span.',
        cellRenderer: (params: ICellRendererParams<DashboardWellRow>) => params.data && <Box>
          <Typography fontSize={12.5} fontWeight={700}>{count(params.data.actual_days)} <Typography component="span" fontSize={10} color="text.secondary">days</Typography></Typography>
          <Typography fontSize={10} color="text.secondary">{count(params.data.recorded_days)} recorded · {count(params.data.sheets)} sheets</Typography>
        </Box>,
      })
      columns.push({
        headerName: 'NPT / UPA', field: 'npt_days', minWidth: 120, flex: 0.65,
        cellRenderer: (params: ICellRendererParams<DashboardWellRow>) => params.data && <Box display="flex" gap={.5} alignItems="center">
          <Tag tone="error">{decimal(params.data.npt_days, 2)} NPT</Tag>
          <Tag tone="warning">{decimal(params.data.upa_days, 2)} UPA</Tag>
        </Box>,
      })
    }
    if (caps.plan && caps.actuals) {
      columns.push({
        headerName: 'DEPTH PROGRESS', field: 'depth_progress_percent', minWidth: 190, flex: 1,
        headerTooltip: 'Deepest configured hole section carrying recorded daily cost, against the deepest planned section.',
        cellRenderer: (params: ICellRendererParams<DashboardWellRow>) => params.data ? <DepthCell row={params.data}/> : null,
      })
    }
    if (caps.budget) {
      columns.push({
        headerName: 'AFE AMOUNT', field: 'afe_amount', minWidth: 145, flex: 0.8,
        headerTooltip: 'Saved AFE estimate total in the selected currency.',
        valueFormatter: params => money(String(params.value ?? ''), currency),
      })
      columns.push({
        headerName: 'SOW ADJUSTED', field: 'sow_adjusted_amount', minWidth: 145, flex: 0.8,
        headerTooltip: 'Latest approved SOW adjustment. Blank means no approved adjustment exists.',
        cellRenderer: (params: ICellRendererParams<DashboardWellRow>) => params.data && (params.data.sow_adjusted_amount === null
          ? <Typography fontSize={12} color="text.secondary">—</Typography>
          : <Box>
            <Typography fontSize={12} fontWeight={700}>{money(params.data.sow_adjusted_amount, currency)}</Typography>
            <Typography fontSize={10} color="text.secondary">Effective {money(params.data.effective_afe_amount, currency)}</Typography>
          </Box>),
      })
    }
    if (caps.actuals) {
      columns.push({
        headerName: 'ACTUAL AMOUNT', field: 'actual_amount', minWidth: 145, flex: 0.8,
        valueFormatter: params => money(String(params.value ?? ''), currency),
      })
    }
    if (caps.budget && caps.actuals) {
      columns.push({
        headerName: 'AFE BALANCE', field: 'afe_balance', minWidth: 145, flex: 0.8,
        cellRenderer: (params: ICellRendererParams<DashboardWellRow>) => params.data && <Box>
          <BalanceCell value={params.data.afe_balance} currency={currency}/>
          <Typography fontSize={10} color="text.secondary">{percent(params.data.utilisation_percent)} used</Typography>
        </Box>,
      })
    }
    columns.push({
      headerName: 'ACTIONS', field: 'well_id', minWidth: 130, flex: 0.6, sortable: false,
      cellRenderer: (params: ICellRendererParams<DashboardWellRow>) => params.data && <Box display="flex" gap={.5}>
        <Button size="small" onClick={() => setDrillWell(params.data!.well_id)}>Drill in</Button>
      </Box>,
    })
    return columns
  }, [caps, currency])

  const afeColumns: ColDef<DashboardAfeRow>[] = useMemo(() => {
    const columns: ColDef<DashboardAfeRow>[] = [
      {
        headerName: 'AFE', field: 'afe_code', minWidth: 190, flex: 1.2,
        cellRenderer: (params: ICellRendererParams<DashboardAfeRow>) => params.data && <Box minWidth={0}>
          <Typography fontSize={12.5} fontWeight={700} noWrap>{params.data.afe_code}</Typography>
          <Typography fontSize={10.5} color="text.secondary" noWrap>{params.data.afe_name}</Typography>
        </Box>,
      },
      { headerName: 'WELL', field: 'well_code', minWidth: 120, flex: 0.7 },
      { headerName: 'RIG', field: 'rig_code', minWidth: 100, flex: 0.55 },
      { headerName: 'TYPE', field: 'afe_type', minWidth: 110, flex: 0.6 },
      {
        headerName: 'STATUS', field: 'status', minWidth: 115, flex: 0.6,
        cellRenderer: (params: ICellRendererParams<DashboardAfeRow>) => params.data && <Tag tone={params.data.status === 'approval' ? 'success' : params.data.status === 'review' ? 'warning' : params.data.status === 'submitted' ? 'info' : 'neutral'}>
          {AFE_STATUS_LABELS[params.data.status] ?? params.data.status}
        </Tag>,
      },
      { headerName: 'CUR', field: 'currency', minWidth: 80, flex: 0.4 },
      {
        headerName: 'AFE AMOUNT', field: 'afe_amount', minWidth: 140, flex: 0.8,
        cellRenderer: (params: ICellRendererParams<DashboardAfeRow>) => params.data && (params.data.conversion_pending
          ? <Tag tone="warning">Conversion pending</Tag>
          : <Typography fontSize={12}>{money(params.data.afe_amount, params.data.currency)}</Typography>),
      },
      {
        headerName: 'SOW ADJUSTED', field: 'sow_adjusted_amount', minWidth: 135, flex: 0.8,
        valueFormatter: params => money(String(params.value ?? ''), currency),
      },
      {
        headerName: 'ACTUAL', field: 'actual_amount', minWidth: 135, flex: 0.8,
        cellRenderer: (params: ICellRendererParams<DashboardAfeRow>) => params.data && <Typography fontSize={12}>{money(params.data.actual_amount, params.data.currency)}</Typography>,
      },
      {
        headerName: 'BALANCE', field: 'afe_balance', minWidth: 135, flex: 0.8,
        cellRenderer: (params: ICellRendererParams<DashboardAfeRow>) => params.data && <BalanceCell value={params.data.afe_balance} currency={params.data.currency}/>,
      },
      {
        headerName: 'DAYS', field: 'actual_days', minWidth: 130, flex: 0.65,
        cellRenderer: (params: ICellRendererParams<DashboardAfeRow>) => params.data && <Box>
          <Typography fontSize={12}>{count(params.data.actual_days)} <Typography component="span" fontSize={10} color="text.secondary">days</Typography></Typography>
          <Typography fontSize={10} color="text.secondary">{decimal(params.data.npt_days, 2)} NPT · {decimal(params.data.upa_days, 2)} UPA</Typography>
        </Box>,
      },
      {
        headerName: 'ACTIONS', field: 'afe_id', minWidth: 165, flex: 0.75, sortable: false,
        cellRenderer: (params: ICellRendererParams<DashboardAfeRow>) => params.data && <Box display="flex" gap={.5}>
          <Button size="small" onClick={() => setDrillWell(params.data!.well_id)}>Drill in</Button>
          {can('afe:read') && <Button size="small" component={RouterLink} to={`/afe/estimate/${params.data.afe_id}`}>AFE</Button>}
        </Box>,
      },
    ]
    return columns
  }, [can, currency])

  const rigColumns: ColDef<DashboardRigRow>[] = useMemo(() => {
    const columns: ColDef<DashboardRigRow>[] = [
      {
        headerName: 'RIG', field: 'rig_code', minWidth: 190, flex: 1.1,
        cellRenderer: (params: ICellRendererParams<DashboardRigRow>) => params.data && <Box>
          <Typography fontSize={12.5} fontWeight={700}>{params.data.rig_code}</Typography>
          <Typography fontSize={10.5} color="text.secondary">{params.data.rig_name}</Typography>
        </Box>,
      },
      {
        headerName: 'WELLS', field: 'wells', minWidth: 140, flex: 0.7,
        cellRenderer: (params: ICellRendererParams<DashboardRigRow>) => params.data && <Box>
          <Typography fontSize={12.5} fontWeight={700}>{count(params.data.wells)}</Typography>
          <Typography fontSize={10} color="text.secondary">{count(params.data.active_wells)} active · {count(params.data.completed_wells)} completed</Typography>
        </Box>,
      },
    ]
    if (caps.plan) columns.push({ headerName: 'PLANNED DAYS', field: 'planned_days', minWidth: 130, flex: 0.7, valueFormatter: params => decimal(String(params.value ?? ''), 2) })
    if (caps.actuals) columns.push({
      headerName: 'ACTUAL DAYS', field: 'actual_days', minWidth: 135, flex: 0.7,
      cellRenderer: (params: ICellRendererParams<DashboardRigRow>) => params.data && <Box>
        <Typography fontSize={12.5} fontWeight={700}>{count(params.data.actual_days)}</Typography>
        <Typography fontSize={10} color="text.secondary">{count(params.data.recorded_days)} recorded · {count(params.data.draft_sheets)} draft sheets</Typography>
      </Box>,
    })
    if (caps.actuals) columns.push({
      headerName: 'NPT / UPA', field: 'npt_days', minWidth: 120, flex: 0.6,
      cellRenderer: (params: ICellRendererParams<DashboardRigRow>) => params.data && <Typography fontSize={12}>{decimal(params.data.npt_days, 2)} / {decimal(params.data.upa_days, 2)}</Typography>,
    })
    if (caps.budget) columns.push({ headerName: 'AFE AMOUNT', field: 'afe_amount', minWidth: 145, flex: 0.8, valueFormatter: params => money(String(params.value ?? ''), currency) })
    if (caps.actuals) columns.push({ headerName: 'ACTUAL AMOUNT', field: 'actual_amount', minWidth: 145, flex: 0.8, valueFormatter: params => money(String(params.value ?? ''), currency) })
    if (caps.budget && caps.actuals) columns.push({
      headerName: 'AFE BALANCE', field: 'afe_balance', minWidth: 145, flex: 0.8,
      cellRenderer: (params: ICellRendererParams<DashboardRigRow>) => params.data && <BalanceCell value={params.data.afe_balance} currency={currency}/>,
    })
    if (caps.plan && caps.actuals) columns.push({
      headerName: 'DEPTH (m)', field: 'planned_depth', minWidth: 160, flex: 0.85,
      cellRenderer: (params: ICellRendererParams<DashboardRigRow>) => params.data && <Typography fontSize={11.5}>
        {decimal(params.data.actual_depth, 0)} / {decimal(params.data.planned_depth, 0)} m
      </Typography>,
    })
    return columns
  }, [caps, currency])

  const recordExport = async (kind: 'csv' | 'xlsx' | 'pdf', recordCount: number) => {
    await api('/dashboard/business/export-audit', {
      method: 'POST',
      body: body({ format: kind, record_count: recordCount }),
    })
  }

  const alerts = data?.alerts ?? []
  const presetActive = (preset: 'all' | '7d' | '30d' | 'month' | 'quarter') => {
    const range = presetRange(preset)
    return (filters.from ?? '') === (range.from ?? '') && (filters.to ?? '') === (range.to ?? '')
  }
  const PRESETS: { key: 'all' | '7d' | '30d' | 'month' | 'quarter'; label: string }[] = [
    { key: '7d', label: '7 days' },
    { key: '30d', label: '30 days' },
    { key: 'month', label: 'This month' },
    { key: 'quarter', label: 'Quarter' },
    { key: 'all', label: 'All time' },
  ]
  const financialCards = !data ? [] : [
    caps.budget && {
      key: 'afe',
      label: 'AFE amount',
      value: money(data!.kpis.afe_amount, currency),
      hint: `${count(data!.kpis.afes)} AFE${data!.kpis.afes === 1 ? '' : 's'}${data!.kpis.conversion_pending_afes ? ` · ${data!.kpis.conversion_pending_afes} pending conversion` : ''}`,
      icon: <DescriptionOutlined fontSize="small"/>,
      title: 'Saved AFE estimate totals in the selected currency. Estimates with an incomplete conversion are excluded from this figure.',
    },
    caps.budget && {
      key: 'sow',
      label: 'SOW adjusted',
      value: money(data!.kpis.sow_adjusted_amount, currency),
      hint: `Effective plan ${compactMoney(data!.kpis.effective_afe_amount, currency)}`,
      icon: <DownloadDoneRounded fontSize="small"/>,
      title: 'Latest approved SOW adjustment. Where none exists, the saved AFE amount is the effective plan.',
    },
    caps.actuals && {
      key: 'actual',
      label: 'Actual cost',
      value: money(data!.kpis.actual_amount, currency),
      hint: `${count(data!.kpis.wells_with_actuals)} wells tracked · ${compactMoney(data!.kpis.other_expenses_amount, currency)} other`,
      icon: <AccountBalanceWalletOutlined fontSize="small"/>,
      title: 'Recorded daily cost in the selected currency, including other expenses.',
    },
    caps.budget && caps.actuals && {
      key: 'balance',
      label: 'AFE balance',
      value: money(data!.kpis.afe_balance, currency),
      hint: `${percent(data!.kpis.utilisation_percent)} of the effective plan used`,
      icon: <TrendingUpRounded fontSize="small"/>,
      tone: (data!.kpis.afe_balance !== null && Number(data!.kpis.afe_balance) < 0 ? 'error' : 'positive') as 'error' | 'positive',
      title: 'Effective AFE amount (SOW adjusted, otherwise the saved estimate) less recorded actual cost.',
      badge: <Box sx={{ mt: .25 }}>
        <LinearProgress variant="determinate" value={Math.min(100, Math.max(0, Number(data!.kpis.utilisation_percent ?? 0)))} aria-label={`${percent(data!.kpis.utilisation_percent)} of the effective plan used`}
          sx={{ height: 4, borderRadius: 2, bgcolor: 'divider', '& .MuiLinearProgress-bar': { transition: 'none', bgcolor: Number(data!.kpis.afe_balance ?? 0) < 0 ? 'error.main' : 'primary.main' } }}/>
      </Box>,
    },
  ].filter(Boolean) as { key: string; label: string; value: string; hint: string; icon: ReactNode; tone?: 'error' | 'positive'; title?: string; badge?: ReactNode }[]

  const operationCards = !data ? [] : [
    {
      key: 'wells',
      label: 'Wells in scope',
      value: count(data!.kpis.wells),
      hint: `${count(data!.kpis.active_wells)} active · ${count(data!.kpis.completed_wells)} completed${caps.plan ? ` · ${count(data!.kpis.configured_wells)} configured` : ''}`,
      icon: <LayersOutlined fontSize="small"/>,
    },
    caps.plan && {
      key: 'planned',
      label: 'Planned days',
      value: decimal(data!.kpis.planned_days, 2),
      hint: 'From the well configuration; an approved plan adjustment replaces it.',
      icon: <ScheduleOutlined fontSize="small"/>,
      title: 'Planned days from Well Configuration (drilling + configured completion), with any approved plan adjustment applied.',
    },
    caps.actuals && {
      key: 'actual-days',
      label: 'Actual days',
      value: decimal(data!.kpis.actual_days),
      hint: `${count(data!.kpis.recorded_days)} recorded · ${data!.kpis.day_variance === null ? '—' : `${Number(data!.kpis.day_variance) >= 0 ? '+' : ''}${decimal(data!.kpis.day_variance, 1)} vs plan`}`,
      icon: <AlignVerticalBottomRounded fontSize="small"/>,
      tone: (data!.kpis.day_variance !== null && Number(data!.kpis.day_variance) > 0 ? 'warning' : 'default') as 'warning' | 'default',
      title: 'Calendar days from the first to the last day of each well\'s cost register, summed across wells.',
    },
    caps.actuals && {
      key: 'npt',
      label: 'NPT / UPA days',
      value: `${decimal(data!.kpis.npt_days, 2)} / ${decimal(data!.kpis.upa_days, 2)}`,
      hint: `${compactMoney(data!.kpis.npt_amount, currency)} NPT · ${compactMoney(data!.kpis.upa_amount, currency)} UPA`,
      icon: <EventBusyOutlined fontSize="small"/>,
      tone: (Number(data!.kpis.npt_days ?? 0) > 0 ? 'error' : 'default') as 'error' | 'default',
      title: 'Deduplicated operational service hours classified as NPT or UPA, divided by 24. Affected cost dates are not treated as duration.',
    },
    {
      key: 'depth',
      label: 'Depth progress',
      value: percent(data!.kpis.depth_progress_percent),
      hint: `${decimal(data!.kpis.actual_depth, 0)} of ${decimal(data!.kpis.planned_depth, 0)} m`,
      icon: <TerrainOutlined fontSize="small"/>,
      title: 'Actual depth from the daily cost register (standardized in meters, ft ÷ 3.281) against planned well depth in meters across all wells.',
      badge: <Box sx={{ mt: .25 }}>
        <LinearProgress variant="determinate" value={Math.min(100, Math.max(0, Number(data!.kpis.depth_progress_percent ?? 0)))} aria-label={`Depth progress ${percent(data!.kpis.depth_progress_percent)}`}
          sx={{ height: 4, borderRadius: 2, bgcolor: 'divider', '& .MuiLinearProgress-bar': { transition: 'none', bgcolor: 'primary.main' } }}/>
      </Box>,
    },
  ].filter(Boolean) as { key: string; label: string; value: string; hint: string; icon: ReactNode; tone?: 'default' | 'warning' | 'error'; title?: string; badge?: ReactNode }[]

  return <>
    <PageHeading
      eyebrow="HOME / OPERATIONS DASHBOARD"
      title="Operations dashboard"
      subtitle="Rig and well plans, AFE budgets, SOW adjustments, actual cost, NPT/UPA time and depth progress in one view. Every figure keeps the currency it was reported in; open a well to follow it back to the records."
      action={<Box display="flex" alignItems="center" gap={1} flexWrap="wrap">
        <FormControlLabel
          control={<Switch size="small" checked={autoRefresh} onChange={event => setAutoRefresh(event.target.checked)}/>}
          label={<Typography fontSize={11.5}>Auto refresh</Typography>}
          sx={{ mr: .25 }}
        />
        <Button size="small" variant="outlined" startIcon={<RefreshRounded sx={{ fontSize: 17 }}/>} onClick={() => void load()} disabled={loading}>
          {loading ? 'Refreshing…' : 'Refresh'}
        </Button>
        {caps.actuals && can('daily-cost:read') && <Button size="small" component={RouterLink} to="/daily-cost/analysis" endIcon={<ArrowForwardRounded sx={{ fontSize: 16 }}/>}>Well cost analysis</Button>}
      </Box>}
    />

    {/* Scope bar: the date range, currency and inclusion basis the whole page reads through. */}
    <Paper variant="outlined" sx={{ borderColor: 'divider', borderRadius: 2.5, mb: 2, overflow: 'hidden' }}>
      <Box sx={{ px: 1.75, py: 1.25, borderBottom: '1px solid', borderColor: 'divider', bgcolor: 'background.default', display: 'flex', alignItems: 'center', gap: 1.5, flexWrap: 'wrap' }}>
        <Box display="flex" alignItems="center" gap={.9} sx={{ minWidth: 0 }}>
          <CalendarMonthOutlined sx={{ fontSize: 17, color: 'text.secondary' }}/>
          <Typography sx={{ fontSize: 11.5, fontWeight: 700, color: 'text.primary' }}>Scope &amp; period</Typography>
          <Typography sx={{ fontSize: 11.5, color: 'text.secondary' }} className="tnum">
            {filters.from || filters.to
              ? `${filters.from ? displayDate(filters.from) : 'start'} → ${filters.to ? displayDate(filters.to) : 'today'}`
              : 'All cost dates'}
            {` · ${currency || 'no currency'} · ${filters.includeDraft ? 'draft and submitted sheets' : 'submitted sheets only'}`}
          </Typography>
        </Box>
        <Box display="flex" gap={.5} flexWrap="wrap" ml="auto" alignItems="center">
          {PRESETS.map(preset => <Button
            key={preset.key}
            size="small"
            variant={presetActive(preset.key) ? 'contained' : 'text'}
            color={presetActive(preset.key) ? 'primary' : 'inherit'}
            onClick={() => { const range = presetRange(preset.key); setFilters(previous => ({ ...previous, from: range.from, to: range.to })) }}
            sx={{ minWidth: 0, px: 1.1, py: .35, fontSize: 11.5, fontWeight: 650, borderRadius: 1.5 }}
          >{preset.label}</Button>)}
          <Box sx={{ width: '1px', height: 18, bgcolor: 'divider', mx: .5 }}/>
          <Button size="small" color="inherit" onClick={() => setFiltersOpen(open => !open)} aria-expanded={filtersOpen} sx={{ fontSize: 11.5 }}>{filtersOpen ? 'Hide scope' : 'More scope'}</Button>
          <Button size="small" color="inherit" onClick={() => setFilters(EMPTY_FILTERS)} sx={{ fontSize: 11.5 }}>Reset</Button>
        </Box>
      </Box>
      <Box sx={{ p: 1.75, display: 'grid', gap: 1.4, gridTemplateColumns: { xs: '1fr', sm: 'repeat(2, minmax(0,1fr))', md: 'repeat(4, minmax(0,1fr))' } }}>
        <TextField size="small" type="date" label="From" value={filters.from} onChange={event => setFilter('from', event.target.value)} InputLabelProps={{ shrink: true }}/>
        <TextField size="small" type="date" label="To" value={filters.to} onChange={event => setFilter('to', event.target.value)} InputLabelProps={{ shrink: true }}/>
        <TextField select size="small" label="Currency" value={filters.currency || currency} onChange={event => setFilter('currency', event.target.value)} helperText="Amounts are never mixed across currencies">
          {(data?.filters.currencies ?? (currency ? [currency] : [])).map(code => <MenuItem key={code} value={code}>{code}</MenuItem>)}
        </TextField>
        <FormControlLabel
          control={<Switch size="small" checked={filters.includeDraft} onChange={event => setFilter('includeDraft', event.target.checked)}/>}
          label={<Typography fontSize={11.5}>Include draft sheets</Typography>}
          sx={{ mt: .4 }}
        />
        {filtersOpen && <>
          <TextField select size="small" label="Rig" value={filters.rig} onChange={event => setFilter('rig', event.target.value)}>
            <MenuItem value="">All rigs</MenuItem>
            {(data?.filters.rigs ?? []).map(rig => <MenuItem key={rig.id} value={rig.id}>{rig.code} — {rig.name}</MenuItem>)}
          </TextField>
          <TextField select size="small" label="Well" value={filters.well} onChange={event => setFilter('well', event.target.value)}>
            <MenuItem value="">All wells</MenuItem>
            {wellOptions.map(well => <MenuItem key={well.id} value={well.id}>{well.code} — {well.name}</MenuItem>)}
          </TextField>
          <TextField select size="small" label="AFE" value={filters.afe} onChange={event => setFilter('afe', event.target.value)} disabled={!caps.budget}>
            <MenuItem value="">All AFEs</MenuItem>
            {afeOptions.map(afe => <MenuItem key={afe.id} value={afe.id}>{afe.code} — {afe.name}</MenuItem>)}
          </TextField>
          <TextField select size="small" label="AFE type" value={filters.afeType} onChange={event => setFilter('afeType', event.target.value)} disabled={!caps.budget}>
            <MenuItem value="">Both types</MenuItem>
            {(data?.filters.afe_types ?? []).map(type => <MenuItem key={type} value={type}>{type}</MenuItem>)}
          </TextField>
          <TextField select size="small" label="Well status" value={filters.status} onChange={event => setFilter('status', event.target.value)}>
            <MenuItem value="">Any status</MenuItem>
            <MenuItem value="active">Active</MenuItem>
            <MenuItem value="completed">Completed</MenuItem>
          </TextField>
        </>}
      </Box>
      <Box sx={{ px: 1.75, py: 1, display: 'flex', alignItems: 'center', gap: 1, flexWrap: 'wrap', borderTop: '1px solid', borderColor: 'divider' }}>
        <Tag tone="success">Live</Tag>
        <Typography color="text.secondary" fontSize={11.2} className="tnum" aria-live="polite">
          {refreshedAt ? `Updated ${displayDateTime(refreshedAt.toISOString())}` : 'Loading…'}
          {autoRefresh ? ' · refreshes every 60 seconds' : ''}
          {data ? ` · ${count(data.kpis.wells)} wells · ${count(data.kpis.afes)} AFEs · ${count(data.kpis.rigs)} rigs` : ''}
        </Typography>
        <Box flex={1}/>
        {data && !caps.budget && <Typography color="text.secondary" fontSize={10.8}>AFE figures need AFE read access.</Typography>}
        {data && !caps.actuals && <Typography color="text.secondary" fontSize={10.8}>Actual cost needs daily cost read access.</Typography>}
        {data && !caps.plan && <Typography color="text.secondary" fontSize={10.8}>Planned days and depth need rig and well read access.</Typography>}
      </Box>
    </Paper>

    <ErrorMessage message={error}/>

    {alerts.length > 0 && <Box sx={{ mb: 2.25 }}>
      <Box display="flex" alignItems="center" gap={1} sx={{ mb: 1 }}>
        <Typography sx={{ fontSize: 10, fontWeight: 750, letterSpacing: '.12em', textTransform: 'uppercase', color: 'text.secondary' }}>Needs attention</Typography>
        <Box sx={{ flex: 1, height: '1px', bgcolor: 'divider' }}/>
        <Typography sx={{ fontSize: 10.5, color: 'text.secondary' }}>{alerts.length} signal{alerts.length === 1 ? '' : 's'}</Typography>
      </Box>
      <Box display="grid" gap={1} sx={{ gridTemplateColumns: { xs: '1fr', lg: 'repeat(2, minmax(0,1fr))' } }}>
        {alerts.map(alert => <Alert
          key={`${alert.kind}-${alert.title}`}
          severity={alert.severity}
          icon={alert.severity === 'error' ? <ReportProblemOutlined/> : alert.severity === 'warning' ? <WarningAmberRounded/> : <SpeedOutlined/>}
          action={alert.well_id ? <Button size="small" onClick={() => setDrillWell(alert.well_id!)}>Open</Button> : undefined}
          sx={{ alignItems: 'flex-start', '& .MuiAlert-message': { minWidth: 0 }, border: '1px solid', borderColor: 'divider' }}
        >
          <Typography fontSize={12.5} fontWeight={700}>{alert.title}</Typography>
          <Typography fontSize={11.5} lineHeight={1.45}>{alert.detail}</Typography>
        </Alert>)}
      </Box>
    </Box>}

    {loading && !data && <DatasetState kind="loading" title="Reading the cost ledger for the selected scope…"/>}

    {data && (data.kpis.wells ?? 0) === 0 && <SectionCard bodyPadding={0}>
      <DatasetState
        kind="empty"
        title="No wells match the current scope"
        message="Clear the filters, or create the rig, well and well configuration the dashboard summarises. Access to a module also decides which figures this page can show."
        action={<>
          <Button variant="outlined" onClick={() => setFilters(EMPTY_FILTERS)}>Reset filters</Button>
          {can('rig-well:read') && <Button component={RouterLink} to="/rig-well/wells" variant="contained" endIcon={<ArrowForwardRounded/>}>Open well register</Button>}
        </>}
      />
    </SectionCard>}

    {data && (data.kpis.wells ?? 0) > 0 && <>
      <Box display="flex" alignItems="center" gap={1} sx={{ mb: 1.2 }}>
        <Typography sx={{ fontSize: 10, fontWeight: 750, letterSpacing: '.12em', textTransform: 'uppercase', color: 'text.secondary' }}>Financial exposure</Typography>
        <Box sx={{ flex: 1, height: '1px', bgcolor: 'divider' }}/>
        <Typography sx={{ fontSize: 10.5, color: 'text.secondary' }}>Effective plan against recorded actual · {currency || 'no currency'}</Typography>
      </Box>
      <Box display="grid" gap={1.5} sx={{ gridTemplateColumns: { xs: 'repeat(2, minmax(0,1fr))', lg: `repeat(${Math.max(financialCards.length, 1)}, minmax(0,1fr))` } }}>
        {financialCards.map(card => <StatCard key={card.key} label={card.label} value={card.value} hint={card.hint} icon={card.icon} tone={card.tone} title={card.title} badge={card.badge}/>)}
      </Box>

      <Box display="flex" alignItems="center" gap={1} sx={{ mt: 2.75, mb: 1.2 }}>
        <Typography sx={{ fontSize: 10, fontWeight: 750, letterSpacing: '.12em', textTransform: 'uppercase', color: 'text.secondary' }}>Operations performance</Typography>
        <Box sx={{ flex: 1, height: '1px', bgcolor: 'divider' }}/>
        <Typography sx={{ fontSize: 10.5, color: 'text.secondary' }}>Time, depth and delivery</Typography>
      </Box>
      <Box display="grid" gap={1.5} sx={{ gridTemplateColumns: { xs: 'repeat(2, minmax(0,1fr))', md: 'repeat(3, minmax(0,1fr))', xl: 'repeat(5, minmax(0,1fr))' } }}>
        {operationCards.map(card => <StatCard key={card.key} label={card.label} value={card.value} hint={card.hint} icon={card.icon} tone={card.tone} title={card.title} badge={card.badge}/>)}
      </Box>

      <Box sx={{ mt: 1.5 }}>
        <SectionCard bodyPadding={0}>
          <Box sx={{ display: 'grid', gridTemplateColumns: { xs: 'repeat(2, minmax(0,1fr))', md: 'repeat(4, minmax(0,1fr))' } }}>
            {[
              { label: 'Rigs in scope', value: count(data.kpis.rigs), hint: `${count(data.kpis.draft_wells)} wells still in configuration draft` },
              { label: 'Over budget', value: `${count(data.kpis.over_budget_wells)} / ${count(data.kpis.over_budget_afes)}`, hint: 'Wells / AFEs above their effective plan', alert: Boolean(data.kpis.over_budget_wells) },
              { label: 'Recording days', value: count(data.kpis.recorded_days), hint: `${count(data.kpis.actual_days)} calendar days in scope` },
              { label: 'Unplanned (UPA)', value: compactMoney(data.kpis.upa_amount, currency), hint: `${decimal(data.kpis.upa_days, 2)} UPA days in the cost register` },
            ].map((fact, index) => <Box key={fact.label} sx={{ px: 2.1, py: 1.5, borderLeft: index === 0 ? 0 : '1px solid', borderColor: 'divider', borderTop: { xs: index >= 2 ? '1px solid' : 0, md: 0 } }}>
              <Typography sx={{ fontSize: 9.5, fontWeight: 700, letterSpacing: '.09em', textTransform: 'uppercase', color: 'text.secondary' }}>{fact.label}</Typography>
              <Typography sx={{ fontSize: 17, fontWeight: 700, mt: .35, letterSpacing: '-.4px', color: fact.alert ? 'error.main' : 'text.primary' }} className="tnum">{fact.value}</Typography>
              <Typography sx={{ fontSize: 10.5, color: 'text.secondary', mt: .2 }}>{fact.hint}</Typography>
            </Box>)}
          </Box>
        </SectionCard>
      </Box>

      <Box display="grid" gap={2} sx={{ mt: 2.5, gridTemplateColumns: { xs: '1fr', lg: 'minmax(0, 1.55fr) minmax(0, 1fr)' } }}>
        <ChartPanel
          title="AFE against actual cost"
          subtitle="Top wells by effective plan. Select a bar to open that well's drill-through panel."
          meta={<Tag tone={data.kpis.over_budget_wells ? 'error' : 'success'}>{data.kpis.over_budget_wells ? `${data.kpis.over_budget_wells} over plan` : 'Within plan'}</Tag>}
          height={296}
          empty={!chartWells.length}
          emptyMessage="No AFE or actual cost to chart for this scope yet."
          caption={`AFE amount and actual cost in ${currency || 'the selected currency'}; SOW adjusted appears only where an approved adjustment exists.`}
        >
          <InteractiveChart
            option={costOption} notMerge lazyUpdate style={{ height: '100%', width: '100%' }}
            onEvents={{ click: (params: { dataIndex?: number }) => drillFromChart(params, chartWells) }}
          />
        </ChartPanel>
        <ChartPanel
          title="Actual cost mix"
          subtitle="Where the recorded money went, by cost group."
          meta={<Tag tone="info">Share</Tag>}
          height={296}
          empty={!data.cost_groups.some(row => Number(row.actual ?? 0) > 0)}
          emptyMessage="No recorded cost to break down yet."
          caption="Shares of recorded actual cost in the selected currency; hover a slice for its exact amount."
        >
          <InteractiveChart option={mixOption} notMerge lazyUpdate style={{ height: '100%', width: '100%' }}/>
        </ChartPanel>
      </Box>

      <Box display="grid" gap={2} sx={{ mt: 2, gridTemplateColumns: { xs: '1fr', lg: 'minmax(0, 1.55fr) minmax(0, 1fr)' } }}>
        <ChartPanel
          title="Cumulative actual cost"
          subtitle="Daily actual cost with the running cumulative line, by cost date."
          meta={<Tag tone="info">{currency || 'Currency'}</Tag>}
          height={268}
          empty={!data.daily.length}
          emptyMessage="No recorded cost in this range."
          caption={`Daily bars and the cumulative line are the same money counted differently — never add the two series. ${refreshedAt ? `Read at ${displayDateTime(refreshedAt.toISOString())}.` : ''}`}
        >
          <InteractiveChart option={trendOption} notMerge lazyUpdate style={{ height: '100%', width: '100%' }}/>
        </ChartPanel>
        <ChartPanel
          title="Depth progress"
          subtitle="Deepest section carrying cost against the planned depth, per well."
          height={268}
          empty={!data.wells.some(row => row.depth_progress_percent !== null)}
          emptyMessage="No depth progress available."
          caption="Progress uses the deepest configured hole section with recorded cost; depth is measured, never summed across sections."
        >
          <InteractiveChart option={depthOption} notMerge lazyUpdate style={{ height: '100%', width: '100%' }}/>
        </ChartPanel>
      </Box>

      <Box display="grid" gap={2} sx={{ mt: 2, gridTemplateColumns: { xs: '1fr', lg: 'minmax(0, 1.55fr) minmax(0, 1fr)' } }}>
        <ChartPanel
          title="Planned days against actual time"
          subtitle="Actual days split into productive, UPA and NPT by allocated service hours ÷ 24."
          meta={<Tag tone="info">Duration</Tag>}
          height={278}
          empty={!daysWells.length}
          emptyMessage="No plan or recorded days to chart yet."
          caption="The diamond marks the planned duration. NPT and UPA are operational durations, not affected-date counts."
        >
          <InteractiveChart
            option={daysOption} notMerge lazyUpdate style={{ height: '100%', width: '100%' }}
            onEvents={{ click: (params: { dataIndex?: number }) => drillFromChart(params, daysWells) }}
          />
        </ChartPanel>
        <SectionCard title="Time classification" subtitle="Days and recorded cost under each classification." sx={{ height: '100%' }}>
          <Box>
            {data.classification.map(row => <Box key={row.key} sx={{ py: 1.15, borderBottom: '1px solid', borderColor: 'divider', '&:last-of-type': { borderBottom: 0 } }}>
              <Box display="flex" justifyContent="space-between" alignItems="center" gap={1}>
                <Box display="flex" alignItems="center" gap={.8}>
                  <Tag tone={row.key === 'NPT' ? 'error' : row.key === 'UPA' ? 'warning' : 'success'}>{row.key}</Tag>
                  <Typography fontSize={11.5} color="text.secondary" className="tnum">{decimal(row.days, row.key === 'Planned' ? 0 : 2)} days</Typography>
                </Box>
                <Typography fontSize={12.5} fontWeight={700} className="tnum">{money(row.actual, currency)}</Typography>
              </Box>
              <Box display="flex" alignItems="center" gap={1} mt={.6}>
                <LinearProgress variant="determinate" value={Math.min(100, Math.max(0, Number(row.share ?? 0)))} aria-label={`${row.key} share ${percent(row.share)}`} sx={{ flex: 1, height: 4, borderRadius: 2, bgcolor: 'divider', '& .MuiLinearProgress-bar': { transition: 'none', bgcolor: row.key === 'NPT' ? 'error.main' : row.key === 'UPA' ? 'warning.main' : 'primary.main' } }}/>
                <Typography fontSize={10.5} color="text.secondary" className="tnum" sx={{ flex: '0 0 auto', whiteSpace: 'nowrap' }}>{percent(row.share)} of cost</Typography>
              </Box>
            </Box>)}
            {caps.actuals && data.kpis.other_expenses_amount !== null && Number(data.kpis.other_expenses_amount) > 0 && <Box sx={{ pt: 1.2, borderTop: '1px solid', borderColor: 'divider', display: 'flex', justifyContent: 'space-between' }}>
              <Typography fontSize={11.5} color="text.secondary">Other expenses (unbudgeted)</Typography>
              <Typography fontSize={12} fontWeight={700} color="warning.main" className="tnum">{money(data.kpis.other_expenses_amount, currency)}</Typography>
            </Box>}
          </Box>
        </SectionCard>
      </Box>

      <Box sx={{ mt: 2 }}>
        <SectionCard
          title="Cost group reconciliation"
          subtitle="AFE planned against recorded actual by cost group, in the selected currency."
          meta={<Tag tone="info">{data.cost_groups.length} groups</Tag>}
          bodyPadding={0}
        >
          <Box sx={{ overflowX: 'auto' }}>
            <Box component="table" sx={{ width: '100%', borderCollapse: 'collapse', fontSize: 12 }}>
              <Box component="thead">
                <Box component="tr">
                  {['Group', 'AFE planned', 'Actual', 'Balance', 'Share'].map(label => <Box component="th" key={label} sx={{
                    textAlign: label === 'Group' ? 'left' : 'right', py: 1, px: 2, bgcolor: 'background.default',
                    borderBottom: '1px solid', borderColor: 'divider',
                    fontSize: 9.5, fontWeight: 700, letterSpacing: '.07em', textTransform: 'uppercase', color: 'text.secondary',
                  }}>{label}</Box>)}
                </Box>
              </Box>
              <Box component="tbody">
                {data.cost_groups.map(row => <Box component="tr" key={row.key} sx={{ '&:hover td': { bgcolor: 'action.hover' } }}>
                  <Box component="td" sx={{ py: .95, px: 2, borderBottom: '1px solid', borderColor: 'divider', fontWeight: 600 }}>{row.label}</Box>
                  <Box component="td" sx={{ py: .95, px: 2, borderBottom: '1px solid', borderColor: 'divider', textAlign: 'right' }} className="tnum">{money(row.planned, currency)}</Box>
                  <Box component="td" sx={{ py: .95, px: 2, borderBottom: '1px solid', borderColor: 'divider', textAlign: 'right' }} className="tnum">{money(row.actual, currency)}</Box>
                  <Box component="td" sx={{ py: .95, px: 2, borderBottom: '1px solid', borderColor: 'divider', textAlign: 'right' }}>
                    <BalanceCell value={row.balance} currency={currency}/>
                  </Box>
                  <Box component="td" sx={{ py: .95, px: 2, borderBottom: '1px solid', borderColor: 'divider', textAlign: 'right' }} className="tnum">{percent(row.share)}</Box>
                </Box>)}
              </Box>
            </Box>
          </Box>
        </SectionCard>
      </Box>

      <Box sx={{ mt: 3 }}>
        <Box display="flex" alignItems="flex-end" justifyContent="space-between" gap={1.5} flexWrap="wrap" sx={{ mb: 1.25 }}>
          <Box>
            <Typography sx={{ fontSize: 14, fontWeight: 700 }}>Register drill-through</Typography>
            <Typography color="text.secondary" fontSize={11.5} sx={{ mt: .3 }}>
              Each register carries its own search, advanced filters, date range, 20/50/100 paging and CSV/XLSX/PDF export. Use Drill in for the record-level panel.
            </Typography>
          </Box>
        </Box>
        <Tabs value={tab} onChange={(_event, value: number) => setTab(value)} sx={{ mb: 1.5, minHeight: 42, '& .MuiTab-root': { minHeight: 42 } }}>
          <Tab label={`Wells (${data.wells.length})`}/>
          {caps.budget && <Tab label={`AFEs (${data.afes.length})`}/>}
          <Tab label={`Rigs (${data.rigs.length})`}/>
        </Tabs>
        {tab === 0 && <DataTable
          rows={data.wells}
          columns={wellColumns}
          rowKey="well_id"
          searchPlaceholder="Search wells, rigs, locations..."
          exportName="business-dashboard-wells"
          canExport={canExport}
          onExport={recordExport}
        />}
        {tab === 1 && caps.budget && <DataTable
          rows={data.afes}
          columns={afeColumns}
          rowKey="afe_id"
          searchPlaceholder="Search AFEs, wells, rigs, statuses..."
          exportName="business-dashboard-afes"
          canExport={canExport}
          onExport={recordExport}
        />}
        {tab === 2 && <DataTable
          rows={data.rigs}
          columns={rigColumns}
          rowKey="rig_id"
          searchPlaceholder="Search rigs..."
          exportName="business-dashboard-rigs"
          canExport={canExport}
          onExport={recordExport}
        />}
      </Box>

      <Box display="flex" gap={2} flexWrap="wrap" mt={1.75} alignItems="center">
        <Typography color="text.secondary" fontSize={10.8}>
          Planned days and AFE amounts are plan-level figures; the date range narrows the cost register only.
        </Typography>
        <Box flex={1}/>
        <Tooltip title="Amounts are grouped by the AFE standard currency, never converted silently.">
          <Typography color="text.secondary" fontSize={10.8} sx={{ textDecoration: 'underline dotted', cursor: 'help' }}>Currency: {currency || 'not set'}</Typography>
        </Tooltip>
      </Box>
    </>}

    <DrillThroughPanel wellId={drillWell} filters={filters} onClose={() => setDrillWell('')}/>
  </>
}
