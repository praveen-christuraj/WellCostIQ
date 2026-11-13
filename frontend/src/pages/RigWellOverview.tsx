import { useCallback, useEffect, useMemo, useState } from 'react'
import { Link as RouterLink } from 'react-router-dom'
import type { EChartsOption } from 'echarts'
import {
  AddRounded, ArrowForwardRounded, BusinessOutlined, FactCheckOutlined, GridViewOutlined,
  LanguageOutlined, RefreshRounded, ScheduleOutlined, TaskAltOutlined,
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
import { chartPalette } from '../designSystem'
import { api } from '../lib/api'
import type { RigWellOverview as RigWellOverviewData } from '../lib/rigWell'

function timeLabel(value: string) {
  const date = new Date(value)
  return Number.isNaN(date.getTime()) ? value : date.toLocaleString(undefined, { dateStyle: 'medium', timeStyle: 'short' })
}

export default function RigWellOverview() {
  const { can } = useAuth()
  const theme = useTheme()
  const { mode } = useColorMode()
  const [overview, setOverview] = useState<RigWellOverviewData | null>(null)
  const [busy, setBusy] = useState(true)
  const [error, setError] = useState('')

  const load = useCallback(async () => {
    setBusy(true)
    setError('')
    try {
      setOverview(await api<RigWellOverviewData>('/rig-well/overview'))
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : 'Rig & Well Management overview could not be loaded')
    } finally {
      setBusy(false)
    }
  }, [])

  useEffect(() => { void load() }, [load])

  const palette = useMemo(() => chartPalette(mode), [mode])
  const axisText = theme.palette.text.secondary
  // Lifecycle order reads as progress: planned → configured → review → complete.
  // Each state keeps a distinct visualization colour in both themes.
  const lifecycleColours = useMemo(() => {
    return [palette.series[10], palette.series[0], palette.series[1], palette.series[2]]
  }, [palette])

  const activities = [...(overview?.activity_counts ?? [])].reverse()
  const barOption: EChartsOption = useMemo(() => ({
    animation: false,
    grid: { left: 2, right: 30, top: 8, bottom: 6, containLabel: true },
    tooltip: {
      trigger: 'axis', axisPointer: { type: 'shadow' }, confine: true,
      backgroundColor: theme.palette.background.paper, borderColor: theme.palette.divider,
      textStyle: { color: theme.palette.text.primary, fontSize: 11.5 },
      valueFormatter: value => `${Number(value ?? 0).toLocaleString()} sub activit${Number(value) === 1 ? 'y' : 'ies'}`,
    },
    xAxis: {
      type: 'value', minInterval: 1,
      axisLabel: { color: axisText, fontSize: 10.5 }, axisLine: { show: false }, axisTick: { show: false },
      splitLine: { lineStyle: { color: theme.palette.divider } },
    },
    yAxis: {
      type: 'category',
      data: activities.map(item => item.label),
      axisLabel: { color: axisText, fontSize: 10.5, width: 190, overflow: 'truncate' },
      axisLine: { lineStyle: { color: theme.palette.divider } }, axisTick: { show: false },
    },
    series: [{
      type: 'bar', barMaxWidth: 18,
      data: activities.map(item => item.count),
      itemStyle: { color: palette.series[0], borderRadius: [0, 3, 3, 0] },
      label: { show: true, position: 'right', color: axisText, fontSize: 10 },
    }],
  }), [activities, theme, axisText, palette])

  const lifecycleOption: EChartsOption = useMemo(() => ({
    animation: false,
    tooltip: {
      trigger: 'item', confine: true,
      backgroundColor: theme.palette.background.paper, borderColor: theme.palette.divider,
      textStyle: { color: theme.palette.text.primary, fontSize: 11.5 },
    },
    legend: { bottom: 0, textStyle: { color: axisText, fontSize: 10.5 }, itemWidth: 10, itemHeight: 10, icon: 'roundRect' },
    series: [{
      type: 'pie', radius: ['54%', '78%'], center: ['50%', '44%'],
      avoidLabelOverlap: true,
      label: { show: false },
      emphasis: { label: { show: true, fontSize: 13, fontWeight: 700, color: theme.palette.text.primary, formatter: '{b}\n{c}' } },
      itemStyle: { borderColor: theme.palette.background.paper, borderWidth: 3 },
      data: [
        { name: 'Upcoming', value: overview?.upcoming_wells ?? 0, itemStyle: { color: lifecycleColours[0] } },
        { name: 'Active', value: overview?.active_wells ?? 0, itemStyle: { color: lifecycleColours[1] } },
        { name: 'Final review', value: overview?.final_review_wells ?? 0, itemStyle: { color: lifecycleColours[2] } },
        { name: 'Completed', value: overview?.completed_wells ?? 0, itemStyle: { color: lifecycleColours[3] } },
      ],
    }],
  }), [overview, theme, axisText, lifecycleColours])

  // Block counts cover every well whose scope is still live (upcoming included),
  // so each block's share is taken over that same population.
  const openWells = (overview?.block_counts ?? []).reduce((total, block) => total + block.well_count, 0)
  // The four well statuses partition the live wells, so they always add up.
  const lifecycleTotal = (overview?.upcoming_wells ?? 0) + (overview?.active_wells ?? 0)
    + (overview?.final_review_wells ?? 0) + (overview?.completed_wells ?? 0)

  return <>
    <PageHeading
      eyebrow="RIG & WELL MANAGEMENT / DIRECTORY"
      title="Rig & well"
      subtitle="The operational directory every cost record hangs from: blocks, rigs, rig-scoped wells, well plans, and the sub activities that classify each day's work."
      action={<Box display="flex" gap={1} flexWrap="wrap">
        <Button variant="outlined" startIcon={<RefreshRounded/>} onClick={() => void load()} disabled={busy}>{busy ? 'Refreshing…' : 'Refresh'}</Button>
        {can('rig-well:create') && <Button component={RouterLink} to="/rig-well/blocks" variant="outlined" startIcon={<AddRounded/>}>Add block</Button>}
        {can('rig-well:create') && <Button component={RouterLink} to="/rig-well/rigs" variant="outlined" startIcon={<AddRounded/>}>Add rig</Button>}
        {can('rig-well:create') && <Button component={RouterLink} to="/rig-well/wells" variant="contained" startIcon={<AddRounded/>}>Add well</Button>}
      </Box>}
    />
    <ErrorMessage message={error}/>

    {busy && !overview ? <DatasetState kind="loading" title="Loading the rig and well directory…"/> : overview && <>
      <Box display="grid" gap={1.5} sx={{ gridTemplateColumns: { xs: 'repeat(2, minmax(0,1fr))', lg: 'repeat(4, minmax(0,1fr))' } }}>
        <StatCard label="Active blocks" value={overview.active_blocks.toLocaleString()} hint={`${overview.deleted_blocks} retained in Deleted entries`} icon={<GridViewOutlined fontSize="small"/>}/>
        <StatCard label="Active rigs" value={overview.active_rigs.toLocaleString()} hint={`${overview.deleted_rigs} retained in Deleted entries`} icon={<BusinessOutlined fontSize="small"/>}/>
        <StatCard label="Sub activities" value={overview.active_sub_activities.toLocaleString()} hint={`${overview.deleted_sub_activities} retained in Deleted entries`} icon={<TaskAltOutlined fontSize="small"/>}/>
        <StatCard label="Wells" value={lifecycleTotal.toLocaleString()} hint={`${overview.deleted_wells} in Deleted entries`} icon={<LanguageOutlined fontSize="small"/>}/>
        {/* Well status: the four values partition the wells above. */}
        <StatCard label="Upcoming wells" value={overview.upcoming_wells.toLocaleString()} hint="Well status · under planning, not yet started" icon={<ScheduleOutlined fontSize="small"/>}/>
        <StatCard label="Active wells" value={overview.active_wells.toLocaleString()} hint="Well status · operations running" icon={<LanguageOutlined fontSize="small"/>} tone="positive"/>
        <StatCard label="Wells in final review" value={overview.final_review_wells.toLocaleString()} hint="Well status · operations ended, costs under review" icon={<FactCheckOutlined fontSize="small"/>} tone={overview.final_review_wells ? 'warning' : 'default'}/>
        <StatCard label="Completed wells" value={overview.completed_wells.toLocaleString()} hint="Well status · signed off" icon={<TaskAltOutlined fontSize="small"/>}/>
        {/* Plan status of the wells that are still upcoming or active. */}
        <StatCard label="Plan configured" value={overview.configured_wells.toLocaleString()} hint="Plan status · open wells with a signed-off plan" icon={<TaskAltOutlined fontSize="small"/>} tone="positive"/>
        <StatCard label="Plan in draft" value={overview.draft_wells.toLocaleString()} hint="Plan status · open wells whose plan is still a draft" icon={<FactCheckOutlined fontSize="small"/>} tone={overview.draft_wells ? 'warning' : 'default'}/>
        <SectionCard bodyPadding={1.75} sx={{ display: 'flex', flexDirection: 'column', justifyContent: 'center', gridColumn: { xs: 'span 2', lg: 'span 2' } }}>
          <Typography sx={{ fontSize: 9.5, fontWeight: 750, letterSpacing: '.11em', textTransform: 'uppercase', color: 'text.secondary' }}>Directory structure</Typography>
          <Typography fontWeight={700} fontSize={13} sx={{ mt: .6 }}>Block → Rig → Well → Sub activity</Typography>
          <Typography color="text.secondary" fontSize={11} sx={{ mt: .5, lineHeight: 1.45 }}>
            Block codes segregate wells; activities, phases and hole sections live in Master data.
          </Typography>
        </SectionCard>
      </Box>

      {overview.active_blocks === 0 && <Alert severity="info" sx={{ mt: 1.5 }} action={can('rig-well:create') ? <Button component={RouterLink} to="/rig-well/blocks" size="small">Create a block</Button> : undefined}>
        Start with a block and a rig. Every well belongs to one block and one rig, and well sub activities are classified by an Activity in Master Data.
      </Alert>}

      <Box display="grid" gap={2} sx={{ mt: 2, gridTemplateColumns: { xs: '1fr', lg: 'minmax(0, 1.15fr) minmax(0, 1fr)' } }}>
        <SectionCard
          title="Wells by block"
          subtitle="Wells segregated by the block they belong to, counted while any scope is still live."
          action={<Button component={RouterLink} to="/rig-well/wells" size="small" endIcon={<ArrowForwardRounded sx={{ fontSize: 15 }}/>}>Well register</Button>}
        >
          {overview.block_counts.length
            ? <Box display="grid" gap={1}>
              {overview.block_counts.map(block => <Box key={block.block_id} sx={{ display: 'flex', alignItems: 'center', gap: 1.4, border: '1px solid', borderColor: 'divider', borderRadius: 1.5, px: 1.4, py: 1.15, minWidth: 0 }}>
                <Box className="table-icon"><GridViewOutlined sx={{ fontSize: 16 }}/></Box>
                <Box flex={1} minWidth={0}>
                  <Typography fontWeight={650} fontSize={12.5} noWrap title={block.block_name}>{block.block_name}</Typography>
                  <Typography color="text.secondary" fontSize={10.8} className="tnum">{block.block_code} · {block.well_count} well{block.well_count === 1 ? '' : 's'}</Typography>
                </Box>
                <Box sx={{ width: 84, flex: '0 0 auto' }}>
                  <Box sx={{ height: 3, borderRadius: 2, bgcolor: 'divider', overflow: 'hidden' }}>
                    <Box sx={{ height: '100%', width: `${openWells ? Math.min(100, (block.well_count / openWells) * 100) : 0}%`, bgcolor: 'primary.main' }}/>
                  </Box>
                  <Typography color="text.secondary" fontSize={10} textAlign="right" sx={{ mt: .35 }}>
                    {openWells ? Math.round((block.well_count / openWells) * 100) : 0}% of wells
                  </Typography>
                </Box>
              </Box>)}
            </Box>
            : <DatasetState compact kind="empty" title="No blocks yet" message="Create a block to segregate wells in this workspace." action={can('rig-well:create') ? <Button component={RouterLink} to="/rig-well/blocks" size="small" variant="outlined">Create a block</Button> : undefined}/>}
        </SectionCard>

        <ChartPanel
          title="Wells by well status"
          subtitle="Where every well sits on the Upcoming → Active → Final review → Completed ladder."
          meta={lifecycleTotal ? <Tag tone="neutral">{lifecycleTotal} wells</Tag> : undefined}
          height={286}
          empty={!lifecycleTotal}
          emptyMessage="No wells to classify yet."
          caption="A well appears once, under the roll-up of its live scopes: Completed when every scope is, Upcoming while none has started, Final review once none is operating, otherwise Active."
        >
          <InteractiveChart option={lifecycleOption} notMerge lazyUpdate style={{ height: '100%', width: '100%' }}/>
        </ChartPanel>
      </Box>

      <Box sx={{ mt: 2 }}>
        <ChartPanel
          title="Sub activities by Master Data activity"
          subtitle="Active well sub activities grouped by the Activity they are classified under."
          height={Math.max(220, activities.length * 42 + 40)}
          empty={!activities.length}
          emptyMessage="Activity distribution appears once sub activities are entered under a well."
          caption="Sub activities are the classification every daily cost line is recorded under, so this is the shape of cost capture for the workspace."
        >
          <InteractiveChart option={barOption} notMerge lazyUpdate style={{ height: '100%', width: '100%' }}/>
        </ChartPanel>
      </Box>

      {can('audit:read') && <Box sx={{ mt: 2 }}>
        <SectionCard
          title="Recent module activity"
          subtitle="The latest audited rig, well, configuration and sub activity changes."
          meta={<Tag tone="success">Audit enabled</Tag>}
          action={<Button component={RouterLink} to="/other-management/audit" size="small" endIcon={<ArrowForwardRounded sx={{ fontSize: 15 }}/>}>Open audit log</Button>}
          bodyPadding={0}
        >
          {overview.recent_activity.length ? <List disablePadding>
            {overview.recent_activity.map(item => <ListItem key={item.id} divider sx={{ px: 2.25, py: 1.1, gap: 1.4, alignItems: 'flex-start', '&:last-of-type': { borderBottom: 0 } }}>
              <Box sx={{ pt: .2 }}><Tag tone="info">{item.action.replaceAll('_', ' ')}</Tag></Box>
              <ListItemText
                primary={<Typography fontSize={12.5} fontWeight={650}>{item.summary}</Typography>}
                secondary={`${item.entity_label} · ${timeLabel(item.created_at)}`}
                primaryTypographyProps={{ component: 'div' }}
                secondaryTypographyProps={{ component: 'div', fontSize: 11 }}
                sx={{ my: 0 }}
              />
            </ListItem>)}
          </List> : <Box sx={{ px: 2.25, py: 2.5 }}><Typography color="text.secondary" fontSize={12.5}>No audited rig or well activity yet.</Typography></Box>}
        </SectionCard>
      </Box>}
    </>}
  </>
}

