import { useCallback, useEffect, useMemo, useState } from 'react'
import { Link as RouterLink } from 'react-router-dom'
import type { EChartsOption } from 'echarts'
import {
  ArrowForwardRounded, DescriptionOutlined, FactCheckOutlined, LayersOutlined, RefreshRounded, TaskAltOutlined,
} from '@mui/icons-material'
import { Alert, Box, Button, List, ListItem, ListItemText, Typography, useTheme } from '@mui/material'
import { ErrorMessage, PageHeading, Tag } from '../components/Common'
import { ChartPanel } from '../components/ui/ChartPanel'
import { InteractiveChart } from '../components/ui/InteractiveChart'
import { DatasetState } from '../components/ui/DatasetState'
import { SectionCard } from '../components/ui/SectionCard'
import { StatCard } from '../components/ui/StatCard'
import { useAuth } from '../context/AuthContext'
import { useColorMode } from '../context/ThemeContext'
import { api } from '../lib/api'
import { chartPalette } from '../designSystem'
import { totalsText, type AfeOverview as AfeOverviewData } from '../lib/afe'
import { compactMoney } from '../lib/businessDashboard'

const STATUS_TONE: Record<string, 'success' | 'warning' | 'info' | 'neutral'> = {
  approval: 'success', review: 'warning', submitted: 'info', draft: 'neutral',
}

function timeLabel(value: string) {
  const date = new Date(value)
  return Number.isNaN(date.getTime()) ? value : date.toLocaleString(undefined, { dateStyle: 'medium', timeStyle: 'short' })
}

export default function AfeOverview() {
  const { can } = useAuth()
  const theme = useTheme()
  const { mode } = useColorMode()
  const [overview, setOverview] = useState<AfeOverviewData | null>(null)
  const [busy, setBusy] = useState(true)
  const [error, setError] = useState('')

  const load = useCallback(async () => {
    setBusy(true)
    setError('')
    try {
      setOverview(await api<AfeOverviewData>('/afe/overview'))
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : 'AFE overview could not be loaded')
    } finally {
      setBusy(false)
    }
  }, [])

  useEffect(() => { void load() }, [load])

  const palette = useMemo(() => chartPalette(mode), [mode])
  const axisText = theme.palette.text.secondary
  const statusColours: Record<string, string> = {
    draft: palette.series[10],
    submitted: palette.series[0],
    review: palette.series[1],
    approval: palette.series[2],
  }
  const statusOption: EChartsOption = useMemo(() => ({
    animation: false,
    tooltip: {
      trigger: 'item', confine: true,
      backgroundColor: theme.palette.background.paper, borderColor: theme.palette.divider,
      textStyle: { color: theme.palette.text.primary, fontSize: 11.5 },
    },
    legend: { bottom: 0, textStyle: { color: axisText, fontSize: 11 }, itemWidth: 10, itemHeight: 10, icon: 'roundRect' },
    series: [{
      type: 'pie',
      radius: ['54%', '78%'],
      center: ['50%', '44%'],
      avoidLabelOverlap: true,
      label: { show: false },
      emphasis: { label: { show: true, fontSize: 14, fontWeight: 700, color: theme.palette.text.primary, formatter: '{b}\n{c}' } },
      itemStyle: { borderColor: theme.palette.background.paper, borderWidth: 3 },
      data: (overview?.statuses ?? []).map(item => ({ name: item.label, value: item.count, itemStyle: { color: statusColours[item.status] } })),
    }],
    // The centre of the ring carries the population, so the ring never reads as
    // "one whole draft" when it is simply every AFE in the workspace.
    graphic: overview && overview.active_afes > 0 ? [
      {
        type: 'text', left: 'center', top: '33%', silent: true,
        style: { text: `${overview.active_afes}`, textAlign: 'center', fill: theme.palette.text.primary, font: `700 24px ${theme.typography.fontFamily}` },
      },
      {
        type: 'text', left: 'center', top: '43%', silent: true,
        style: { text: 'active AFEs', textAlign: 'center', fill: theme.palette.text.secondary, font: `600 10px ${theme.typography.fontFamily}` },
      },
    ] : [],
  }), [overview, theme, axisText])

  // A bar chart puts every well on one numeric axis, so wells are only charted
  // together when they share a currency. Wells costing in another currency stay
  // in the AFE register: comparing them here would silently mix money.
  const wellGroups = useMemo(() => {
    const groups = new Map<string, { label: string; total: string }[]>()
    for (const well of overview?.top_wells ?? []) {
      const key = well.currency || ''
      groups.set(key, [...(groups.get(key) ?? []), { label: well.label, total: well.total }])
    }
    const sorted = [...groups.entries()].sort((a, b) => b[1].length - a[1].length)
    const [currency = '', wells = []] = sorted[0] ?? []
    const otherWells = sorted.slice(1).reduce((sum, [, rows]) => sum + rows.length, 0)
    return { currency, wells, otherWells }
  }, [overview])
  const topWells = [...wellGroups.wells].reverse()
  const wellOption: EChartsOption = useMemo(() => ({
    animation: false,
    grid: { left: 4, right: 78, top: 8, bottom: 6, containLabel: true },
    tooltip: {
      trigger: 'axis', axisPointer: { type: 'shadow' }, confine: true,
      backgroundColor: theme.palette.background.paper, borderColor: theme.palette.divider,
      textStyle: { color: theme.palette.text.primary, fontSize: 11.5 },
    },
    xAxis: {
      type: 'value',
      axisLabel: { color: axisText, fontSize: 10.5, formatter: (value: number) => compactMoney(value, '') },
      splitLine: { lineStyle: { color: theme.palette.divider } },
      axisLine: { show: false },
    },
    yAxis: { type: 'category', data: topWells.map(item => item.label), axisLabel: { color: axisText, fontSize: 10.5, width: 160, overflow: 'truncate' }, axisLine: { lineStyle: { color: theme.palette.divider } }, axisTick: { show: false } },
    series: [{
      type: 'bar',
      data: topWells.map(item => Number(item.total)),
      barMaxWidth: 16,
      itemStyle: { color: palette.planned, borderRadius: [0, 3, 3, 0] },
      label: { show: true, position: 'right', color: axisText, fontSize: 10, formatter: (params: { value?: unknown }) => compactMoney(Number(params.value ?? 0), '') },
    }],
  }), [topWells, theme, axisText, palette])

  return <>
    <PageHeading
      eyebrow="AFE MANAGEMENT / PORTFOLIO"
      title="AFE portfolio"
      subtitle="Well-scoped authorisation-for-expenditure records for drilling and completion, their cost estimates, and how far each has moved through review and approval."
      action={<Box display="flex" gap={1} flexWrap="wrap">
        <Button variant="outlined" startIcon={<RefreshRounded/>} onClick={load} disabled={busy}>{busy ? 'Refreshing…' : 'Refresh'}</Button>
        <Button component={RouterLink} to="/afe/register" variant="contained" endIcon={<ArrowForwardRounded/>}>Open AFE register</Button>
      </Box>}
    />
    <ErrorMessage message={error}/>

    {overview && overview.warning_afes > 0 && <Alert severity="warning" sx={{ mb: 2 }} action={<Button component={RouterLink} to="/afe/register?tab=estimation" size="small">Review</Button>}>
      {overview.warning_afes} AFE{overview.warning_afes === 1 ? '' : 's'} carry estimate warnings. Review them in AFE cost estimation before submitting.
    </Alert>}

    {busy && !overview ? <DatasetState kind="loading" title="Loading the AFE portfolio…"/> : overview && <>
      <Box display="grid" gap={1.5} sx={{ gridTemplateColumns: { xs: 'repeat(2, minmax(0,1fr))', lg: 'repeat(4, minmax(0,1fr))' } }}>
        <StatCard label="Active AFEs" value={overview.active_afes.toLocaleString()} hint={`${overview.drilling_afes} drilling · ${overview.completion_afes} completion`} icon={<DescriptionOutlined fontSize="small"/>}/>
        <StatCard
          label="Approved"
          value={overview.approved_afes.toLocaleString()}
          hint={overview.approved_by_currency.length ? `${totalsText(overview.approved_by_currency)} approved` : 'No approved AFE yet'}
          icon={<TaskAltOutlined fontSize="small"/>}
          tone={overview.approved_afes ? 'positive' : 'default'}
        />
        <StatCard label="Wells with AFEs" value={overview.wells_with_afes.toLocaleString()} hint="Wells carrying at least one active AFE" icon={<LayersOutlined fontSize="small"/>}/>
        <StatCard label="Deleted AFEs" value={overview.deleted_afes.toLocaleString()} hint="Recoverable from Deleted entries" icon={<FactCheckOutlined fontSize="small"/>}/>
      </Box>

      {overview.conversion_pending_afes > 0 && <Alert severity="info" sx={{ mt: 1.5 }}>
        {overview.conversion_pending_afes} AFE{overview.conversion_pending_afes === 1 ? ' is' : 's are'} left out of converted totals until its currency conversion rates are entered. Totals below remain grouped by their own currency.
      </Alert>}

      <Box display="grid" gap={2} sx={{ mt: 2, gridTemplateColumns: { xs: '1fr', lg: 'minmax(0, 1.15fr) minmax(0, 1fr)' } }}>
        <SectionCard
          title="Approval pipeline"
          subtitle={`Estimated value across active AFEs, each in its own standard currency: ${totalsText(overview.totals_by_currency)}`}
          meta={<Tag tone="info">{overview.active_afes} active</Tag>}
          bodyPadding={0}
        >
          <Box sx={{ display: 'grid', gridTemplateColumns: { xs: '1fr', sm: 'minmax(0, 1.15fr) minmax(0, .85fr)' }, alignItems: 'center' }}>
            <Box sx={{ height: 292, px: 1 }}>
              {overview.statuses.some(row => row.count > 0)
                ? <InteractiveChart option={statusOption} notMerge lazyUpdate style={{ height: '100%', width: '100%' }}/>
                : <Box sx={{ height: '100%', display: 'grid', placeItems: 'center' }}><Typography fontSize={12.5} color="text.secondary">No AFEs to show yet.</Typography></Box>}
            </Box>
            <Box sx={{ px: 2, py: 1.5, borderLeft: { sm: '1px solid' }, borderTop: { xs: '1px solid', sm: 0 }, borderColor: 'divider', height: '100%' }}>
              {overview.statuses.map(item => <Box key={item.status} sx={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', gap: 1, py: 1.1, borderBottom: '1px solid', borderColor: 'divider', '&:last-of-type': { borderBottom: 0 } }}>
                <Box display="flex" alignItems="center" gap={1}><Tag tone={STATUS_TONE[item.status] ?? 'neutral'}>{item.label}</Tag></Box>
                <Typography fontSize={15} fontWeight={700} className="tnum">{item.count.toLocaleString()}</Typography>
              </Box>)}
              <Box display="flex" gap={1} flexWrap="wrap" sx={{ mt: 2 }}>
                {can('afe:estimate') && <Button component={RouterLink} to="/afe/register?tab=estimation" size="small" variant="outlined">Cost estimation</Button>}
                {can('afe:create') && <Button component={RouterLink} to="/afe/register" size="small" variant="outlined">Create AFE</Button>}
              </Box>
            </Box>
          </Box>
        </SectionCard>

        <ChartPanel
          title="Highest-cost wells"
          subtitle={`Total estimate of active AFEs per well, in ${wellGroups.currency || 'the wells\' own currency'}.`}
          meta={wellGroups.currency ? <Tag tone="neutral">{wellGroups.currency}</Tag> : undefined}
          height={292}
          empty={!overview.top_wells.length}
          emptyMessage="No AFEs with estimates yet."
          caption={wellGroups.otherWells
            ? `${wellGroups.otherWells} further well${wellGroups.otherWells === 1 ? '' : 's'} cost in another currency and cannot share this axis; open the AFE register to compare them.`
            : 'Bar length is the estimated value in each AFE\'s own standard currency; convert in the AFE estimate, never on this chart.'}
        >
          <InteractiveChart option={wellOption} notMerge lazyUpdate style={{ height: '100%', width: '100%' }}/>
        </ChartPanel>
      </Box>

      <Box display="grid" gap={2} sx={{ mt: 2, gridTemplateColumns: { xs: '1fr', lg: 'minmax(0, 1fr) minmax(0, 1fr)' } }}>
        <SectionCard title="Register shortcuts" subtitle="Jump straight to the queue you need. Each tab keeps its own filters and export.">
          <Box sx={{ display: 'grid', gap: 1 }}>
            {[
              { label: 'AFE register', detail: 'Create, edit and open every AFE in this workspace.', to: '/afe/register', icon: DescriptionOutlined },
              { label: 'AFE cost estimation', detail: 'Price services, consumables and tangibles against the well plan.', to: '/afe/register?tab=estimation', icon: TaskAltOutlined },
              { label: 'Wells in final review', detail: 'AFEs whose well scope is in Final review.', to: '/afe/register?tab=final_review', icon: FactCheckOutlined },
              { label: 'Completed wells', detail: 'AFEs attached to completed well scopes.', to: '/afe/register?tab=completed', icon: LayersOutlined },
              { label: 'Deleted entries', detail: 'Recover or permanently remove a deleted AFE.', to: '/afe/register?tab=deleted', icon: FactCheckOutlined },
            ].map(item => <Box key={item.label} sx={{ display: 'flex', alignItems: 'center', gap: 1.2, border: '1px solid', borderColor: 'divider', borderRadius: 1.5, px: 1.5, py: 1.1, '&:hover': { borderColor: 'text.disabled' } }}>
              <Box className="table-icon"><item.icon sx={{ fontSize: 17 }}/></Box>
              <Box flex={1} minWidth={0}>
                <Typography fontSize={12.5} fontWeight={650}>{item.label}</Typography>
                <Typography fontSize={11} color="text.secondary">{item.detail}</Typography>
              </Box>
              <Button component={RouterLink} to={item.to} size="small" endIcon={<ArrowForwardRounded sx={{ fontSize: 15 }}/>}>Open</Button>
            </Box>)}
          </Box>
        </SectionCard>
        <SectionCard title="Recent activity" subtitle="Latest AFE, estimate and export events from the audit trail." bodyPadding={0}>
          {overview.recent_activity.length
            ? <List dense disablePadding>
              {overview.recent_activity.map(item => <ListItem key={item.id} divider disableGutters sx={{ px: 2.25, py: 1.05 }}>
                <ListItemText
                  primary={item.summary || `${item.action} ${item.entity_label}`}
                  secondary={`${timeLabel(item.created_at)} · ${item.entity_label}`}
                  primaryTypographyProps={{ fontSize: 12.5, fontWeight: 600, noWrap: true }}
                  secondaryTypographyProps={{ fontSize: 10.8 }}
                />
              </ListItem>)}
            </List>
            : <Box sx={{ px: 2.25, py: 3 }}><Typography color="text.secondary" fontSize={12.5}>No AFE activity recorded yet.</Typography></Box>}
        </SectionCard>
      </Box>
    </>}
  </>
}
