import { useEffect, useState } from 'react'
import {
  AssessmentOutlined, ArrowForwardRounded, BuildOutlined, HistoryOutlined, Inventory2Outlined, InsightsOutlined,
  PrecisionManufacturingOutlined, QueryStatsOutlined, ScheduleRounded, ScienceOutlined,
  StorefrontOutlined, TuneRounded, WaterDropOutlined,
} from '@mui/icons-material'
import { Box, Button, Typography } from '@mui/material'
import type { SvgIconComponent } from '@mui/icons-material'
import { Link as RouterLink } from 'react-router-dom'
import { ErrorMessage, PageHeading, Tag } from '../components/Common'
import { DatasetState } from '../components/ui/DatasetState'
import { SectionCard } from '../components/ui/SectionCard'
import { StatCard } from '../components/ui/StatCard'
import { useAuth } from '../context/AuthContext'
import { api } from '../lib/api'
import type { AfeOverview } from '../lib/afe'
import type { DailyCostOverview } from '../lib/dailyCost'
import type { RigWellOverview } from '../lib/rigWell'

const USAGE_REPORT_CARDS = [
  {
    path: '/reports/mud-chemicals-usage', title: 'Mud chemicals usage', icon: ScienceOutlined,
    description: 'Matrix of chemicals by well and hole section, with usage quantities, costs and section sub headers.',
  },
  {
    path: '/reports/drill-bits-usage', title: 'Drill bits usage', icon: PrecisionManufacturingOutlined,
    description: 'Drill bit matrix with make, model, size and IADC details, section usage and costs per well.',
  },
  {
    path: '/reports/tangibles-usage', title: 'Tangibles usage', icon: Inventory2Outlined,
    description: 'Categorized tangible matrix with category and subcategory grouping, section usage and costs per well.',
  },
  {
    path: '/reports/service-wise-cost', title: 'Service-wise cost', icon: BuildOutlined,
    description: 'Total service costs per well and hole section across every daily cost sheet in the selected range.',
  },
  {
    path: '/reports/vendor-wise-cost', title: 'Vendor/company-wise cost', icon: StorefrontOutlined,
    description: 'Total costs booked per vendor or recorded company, with cost-group and section breakdowns per well.',
  },
  {
    path: '/reports/npt-upa', title: 'NPT/UPA report', icon: ScheduleRounded,
    description: 'NPT and UPA allocated duration, affected cost dates and costs per well, alongside planned activity.',
  },
]

function ReportCard({ path, title, description, icon: Icon }: {
  path: string; title: string; description: string; icon: SvgIconComponent
}) {
  return <Box sx={{
    p: 2, borderRadius: 2, border: '1px solid', borderColor: 'divider', bgcolor: 'background.paper', height: '100%',
    display: 'flex', flexDirection: 'column', transition: 'border-color 120ms, box-shadow 120ms',
    '&:hover': { borderColor: 'text.disabled', boxShadow: 1 },
  }}>
    <Box display="flex" alignItems="center" gap={1.2} mb={.9}>
      <Box className="table-icon"><Icon sx={{ fontSize: 17 }}/></Box>
      <Typography fontWeight={700} fontSize={13.5}>{title}</Typography>
    </Box>
    <Typography color="text.secondary" fontSize={11.8} sx={{ flex: 1, lineHeight: 1.5 }}>{description}</Typography>
    <Button component={RouterLink} to={path} size="small" endIcon={<ArrowForwardRounded sx={{ fontSize: 15 }}/>} sx={{ mt: 1.5, alignSelf: 'flex-start', minWidth: 0 }}>Open report</Button>
  </Box>
}

type Activity = { id: string; action: string; entity_type: string; entity_label: string; summary: string; created_at: string }
type Dashboard = { wells: RigWellOverview | null; afes: AfeOverview | null; daily: DailyCostOverview | null; activity: Activity[] }

export default function Reports() {
  const { can } = useAuth()
  const canReadRig = can('rig-well:read')
  const canReadAfe = can('afe:read')
  const canReadDaily = can('daily-cost:read')
  const [dashboard, setDashboard] = useState<Dashboard>({ wells: null, afes: null, daily: null, activity: [] })
  const [busy, setBusy] = useState(true)
  const [error, setError] = useState('')

  useEffect(() => {
    let active = true
    const requests = Promise.allSettled([
      canReadRig ? api<RigWellOverview>('/rig-well/overview') : Promise.resolve(null),
      canReadAfe ? api<AfeOverview>('/afe/overview') : Promise.resolve(null),
      canReadDaily ? api<DailyCostOverview>('/daily-cost/overview') : Promise.resolve(null),
    ])
    requests.then(results => {
      if (!active) return
      const errors: string[] = []
      const wells = results[0].status === 'fulfilled' ? results[0].value : null
      const afes = results[1].status === 'fulfilled' ? results[1].value : null
      const daily = results[2].status === 'fulfilled' ? results[2].value : null
      results.forEach((result, index) => {
        if (result.status === 'rejected') errors.push(`${['Rig & Well', 'AFE', 'Daily Cost'][index]} summary: ${result.reason instanceof Error ? result.reason.message : 'could not be loaded'}`)
      })
      const activity = [
        ...(wells?.recent_activity ?? []),
        ...(afes?.recent_activity ?? []),
        ...(daily?.recent_activity ?? []),
      ].sort((a, b) => b.created_at.localeCompare(a.created_at)).slice(0, 8)
      setDashboard({ wells, afes, daily, activity })
      setError(errors.join(' · '))
    }).finally(() => { if (active) setBusy(false) })
    return () => { active = false }
  }, [canReadRig, canReadAfe, canReadDaily])

  const reportCount = Number(canReadRig && (canReadAfe || canReadDaily)) + Number(canReadDaily) * 7

  return <>
    <PageHeading
      eyebrow="REPORTS / ANALYTICS"
      title="Reports"
      subtitle="Consolidated views of well plans, AFE budgets and recorded actual cost. Every report states its population, currency basis and date bounds, and exports the same rows it shows."
      action={<>
        {can('report-builder:read') || can('report-builder:create') ? <Button component={RouterLink} to="/reports/builder" variant="outlined" startIcon={<TuneRounded/>}>Report Builder</Button> : null}
        {can('custom-reports:read') ? <Button component={RouterLink} to="/reports/custom" variant="contained" endIcon={<ArrowForwardRounded/>}>Custom Reports</Button> : null}
      </>}
    />
    <ErrorMessage message={error}/>
    {busy ? <DatasetState kind="loading" title="Loading the report catalogue…"/> : <>
      <Box display="grid" gap={1.5} sx={{ gridTemplateColumns: { xs: 'repeat(2, minmax(0,1fr))', lg: 'repeat(4, minmax(0,1fr))' } }}>
        <StatCard label="Available reports" value={reportCount} hint="Consolidated workspace reports" icon={<AssessmentOutlined fontSize="small"/>}/>
        {canReadRig && <StatCard label="Active wells" value={dashboard.wells?.active_wells ?? '—'} hint="Wells in the workspace register" icon={<QueryStatsOutlined fontSize="small"/>}/>}
        {canReadAfe && <StatCard label="Active AFEs" value={dashboard.afes?.active_afes ?? '—'} hint="Current AFE records" icon={<AssessmentOutlined fontSize="small"/>}/>}
        {canReadDaily && <StatCard label="Wells with actuals" value={dashboard.daily?.wells_tracked ?? '—'} hint="Wells with daily cost entries" icon={<HistoryOutlined fontSize="small"/>}/>}
      </Box>
      {(!canReadAfe || !canReadDaily) && <Box display="flex" gap={2} flexWrap="wrap" sx={{ mt: 1.25 }}>
        {!canReadAfe && <Typography color="text.secondary" fontSize={11.5}>AFE figures are shown only to users with AFE read access.</Typography>}
        {!canReadDaily && <Typography color="text.secondary" fontSize={11.5}>Actual cost figures are shown only to users with daily cost read access.</Typography>}
      </Box>}

      {(canReadRig && (canReadAfe || canReadDaily)) || canReadDaily ? <Box display="flex" alignItems="center" gap={1} sx={{ mt: 2.75, mb: 1.2 }}>
        <Typography sx={{ fontSize: 10, fontWeight: 750, letterSpacing: '.12em', textTransform: 'uppercase', color: 'text.secondary' }}>Featured reports</Typography>
        <Box sx={{ flex: 1, height: '1px', bgcolor: 'divider' }}/>
      </Box> : null}

      <Box display="grid" gap={1.5} sx={{ gridTemplateColumns: { xs: '1fr', lg: 'repeat(2, minmax(0, 1fr))' } }}>
        {canReadRig && (canReadAfe || canReadDaily) && <SectionCard
          title="Well-wise cost comparisons"
          subtitle="Configured wells, AFE totals and daily actuals side by side, with planned versus actual days, remaining budget and cost utilisation."
          meta={<Tag tone="info">AFE ↔ actual</Tag>}
        >
          <Box display="flex" alignItems="flex-start" gap={2}>
            <Box className="table-icon" sx={{ width: 38, height: 38 }}><InsightsOutlined sx={{ fontSize: 19 }}/></Box>
            <Typography fontSize={12} color="text.secondary" sx={{ lineHeight: 1.55, flex: 1, minWidth: 0 }}>
              Choose the wells and period, then read budget against actual in a single currency. Every row opens that well&apos;s cost analysis.
            </Typography>
          </Box>
          <Box display="flex" alignItems="center" gap={1} flexWrap="wrap" sx={{ mt: 1.75, pt: 1.5, borderTop: '1px solid', borderColor: 'divider' }}>
            <Typography fontSize={10.5} color="text.secondary" sx={{ flex: 1, minWidth: 0 }}>Requires well, AFE and daily cost read access.</Typography>
            <Button component={RouterLink} to="/reports/well-cost-comparison" size="small" variant="contained" endIcon={<ArrowForwardRounded sx={{ fontSize: 15 }}/>}>Open report</Button>
          </Box>
        </SectionCard>}
        {canReadDaily && <SectionCard
          title="Consumption and losses"
          subtitle="Cumulative surface and other mud losses as a section-by-mud-type matrix, with date or month drill-through and a filtered export."
          meta={<Tag tone="info">Mud · losses</Tag>}
        >
          <Box display="flex" alignItems="flex-start" gap={2}>
            <Box className="table-icon" sx={{ width: 38, height: 38 }}><WaterDropOutlined sx={{ fontSize: 19 }}/></Box>
            <Typography fontSize={12} color="text.secondary" sx={{ lineHeight: 1.55, flex: 1, minWidth: 0 }}>
              Losses are read from daily sheets and grouped by section and mud type; the export contains exactly the rows on screen.
            </Typography>
          </Box>
          <Box display="flex" alignItems="center" gap={1} flexWrap="wrap" sx={{ mt: 1.75, pt: 1.5, borderTop: '1px solid', borderColor: 'divider' }}>
            <Typography fontSize={10.5} color="text.secondary" sx={{ flex: 1, minWidth: 0 }}>Reads daily cost sheets for the selected date range.</Typography>
            <Button component={RouterLink} to="/reports/consumption-losses" size="small" variant="contained" endIcon={<ArrowForwardRounded sx={{ fontSize: 15 }}/>}>Open report</Button>
          </Box>
        </SectionCard>}
      </Box>

      {canReadDaily && <>
        <Box display="flex" alignItems="center" gap={1} sx={{ mt: 2.75, mb: 1.2 }}>
          <Typography sx={{ fontSize: 10, fontWeight: 750, letterSpacing: '.12em', textTransform: 'uppercase', color: 'text.secondary' }}>Usage, cost and NPT/UPA</Typography>
          <Box sx={{ flex: 1, height: '1px', bgcolor: 'divider' }}/>
          <Typography sx={{ fontSize: 10.5, color: 'text.secondary' }}>Daily cost sources</Typography>
        </Box>
        <Box display="grid" gap={1.5} sx={{ gridTemplateColumns: { xs: '1fr', sm: 'repeat(2, minmax(0, 1fr))', lg: 'repeat(3, minmax(0, 1fr))' } }}>
          {USAGE_REPORT_CARDS.map(card => <ReportCard key={card.path} path={card.path} title={card.title} description={card.description} icon={card.icon}/>)}
        </Box>
      </>}

      <Box sx={{ mt: 2 }}>
        <SectionCard
          title="Recent source activity"
          subtitle="Latest updates from the modules whose records these reports read."
          meta={<Tag tone="success">Audit enabled</Tag>}
          bodyPadding={0}
        >
          {dashboard.activity.length === 0
            ? <Box sx={{ px: 2.25, py: 2.5 }}><Typography color="text.secondary" fontSize={12.5}>No recent source activity is available.</Typography></Box>
            : dashboard.activity.map(item => <Box key={`${item.entity_type}-${item.id}`} display="grid" gridTemplateColumns={{ xs: '1fr', md: '180px 1fr 200px' }} gap={1} alignItems="center" sx={{ px: 2.25, py: 1, borderBottom: '1px solid', borderColor: 'divider', '&:last-of-type': { borderBottom: 0 } }}>
              <Typography fontSize={11.5} color="text.secondary" className="tnum">{new Date(item.created_at).toLocaleString()}</Typography>
              <Typography fontSize={12.5}>{item.summary || `${item.action} ${item.entity_type}`}</Typography>
              <Typography fontSize={11.5} color="text.secondary" noWrap>{item.entity_label || item.entity_type.replace(/_/g, ' ')}</Typography>
            </Box>)}
        </SectionCard>
      </Box>
    </>}
  </>
}
