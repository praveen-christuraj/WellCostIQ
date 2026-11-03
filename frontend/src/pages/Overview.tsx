import { useEffect, useMemo, useState } from 'react'
import { Link } from 'react-router-dom'
import { Avatar, Box, Button, Typography, useTheme } from '@mui/material'
import { ArrowForwardRounded, AdminPanelSettingsOutlined, PeopleOutline, ShieldOutlined, VpnKeyOutlined } from '@mui/icons-material'
import { api } from '../lib/api'
import type { Overview as OverviewType } from '../lib/types'
import { useAuth } from '../context/AuthContext'
import { useColorMode } from '../context/ThemeContext'
import { PageHeading, Tag } from '../components/Common'
import { ChartPanel } from '../components/ui/ChartPanel'
import { DatasetState } from '../components/ui/DatasetState'
import { SectionCard } from '../components/ui/SectionCard'
import { StatCard } from '../components/ui/StatCard'
import { InteractiveChart } from '../components/ui/InteractiveChart'
import { chartPalette, surface } from '../designSystem'

function initials(name: string) {
  return name.split(' ').filter(Boolean).map(part => part[0]).slice(0, 2).join('').toUpperCase()
}

// User Management dashboard. Reached from the User Management menu; the app
// landing page is the Users register, not this summary.
export default function Overview() {
  const { user, can } = useAuth()
  const { mode } = useColorMode()
  const theme = useTheme()
  const [data, setData] = useState<OverviewType | null>(null)
  const [error, setError] = useState('')
  useEffect(() => { api<OverviewType>('/overview').then(setData).catch((caught: unknown) => setError(caught instanceof Error ? caught.message : 'The workspace summary could not be loaded')) }, [])

  const palette = useMemo(() => chartPalette(mode), [mode])
  const s = surface(mode)
  const axisText = theme.palette.text.secondary
  const activeShare = data && data.users ? Math.round((data.active_users / data.users) * 100) : 0

  // Horizontal bars keep a single-role workspace readable: the category label
  // sits on the axis and the bar length carries the count.
  const roleRows = [...(data?.role_distribution ?? [])].sort((a, b) => a.count - b.count)
  const roleOption = useMemo(() => ({
    animation: false,
    grid: { left: 2, right: 30, top: 8, bottom: 6, containLabel: true },
    xAxis: {
      type: 'value' as const, minInterval: 1,
      splitLine: { lineStyle: { color: s.divider } },
      axisLabel: { color: axisText, fontSize: 10.5 }, axisLine: { show: false }, axisTick: { show: false },
    },
    yAxis: {
      type: 'category' as const,
      data: roleRows.map(row => row.name),
      axisLine: { lineStyle: { color: s.divider } }, axisTick: { show: false },
      axisLabel: { color: axisText, fontSize: 10.5, width: 150, overflow: 'truncate' },
    },
    tooltip: {
      trigger: 'axis' as const, axisPointer: { type: 'shadow' as const }, confine: true,
      backgroundColor: theme.palette.background.paper, borderColor: s.divider,
      textStyle: { color: theme.palette.text.primary, fontSize: 11.5 },
      valueFormatter: (value: unknown) => `${Number(value ?? 0).toLocaleString()} member${Number(value) === 1 ? '' : 's'}`,
    },
    series: [{
      type: 'bar' as const, barMaxWidth: 18,
      data: roleRows.map(row => row.count),
      itemStyle: { color: palette.series[0], borderRadius: [0, 3, 3, 0] },
      label: { show: true, position: 'right' as const, color: axisText, fontSize: 10.5 },
    }],
  }), [roleRows, axisText, s.divider, theme.palette.background.paper, theme.palette.text.primary, palette])

  return <>
    <PageHeading
      eyebrow="USER MANAGEMENT / DASHBOARD"
      title={`Welcome, ${user?.full_name.split(' ')[0] ?? 'there'}.`}
      subtitle={`People, roles and permissions in ${user?.organization_name ?? 'this workspace'}. Membership and access changes are audit logged.`}
      action={can('users:create') ? <Button component={Link} to="/users" variant="contained" endIcon={<ArrowForwardRounded/>}>Manage team</Button> : undefined}
    />
    {error && <Typography color="error.main" fontSize={12.5} sx={{ mb: 2 }}>{error}</Typography>}

    {!data ? <DatasetState kind="loading" title="Loading the workspace summary…"/> : <>
      <Box display="grid" gap={1.5} sx={{ gridTemplateColumns: { xs: 'repeat(2, minmax(0,1fr))', lg: 'repeat(4, minmax(0,1fr))' } }}>
        <StatCard label="Total users" value={data.users.toLocaleString()} hint={`${data.active_users.toLocaleString()} active members`} icon={<PeopleOutline fontSize="small"/>}/>
        <StatCard label="Active roles" value={data.roles.toLocaleString()} hint="Defined access groups" icon={<AdminPanelSettingsOutlined fontSize="small"/>}/>
        <StatCard label="Permissions" value={data.permissions.toLocaleString()} hint="Capabilities available to grant" icon={<VpnKeyOutlined fontSize="small"/>}/>
        <StatCard label="Access status" value={`${activeShare}%`} hint="Users currently active" icon={<ShieldOutlined fontSize="small"/>} tone={activeShare >= 80 ? 'positive' : 'default'}/>
      </Box>

      <Box display="grid" gap={2} sx={{ mt: 2, alignItems: 'start', gridTemplateColumns: { xs: '1fr', lg: 'minmax(0, 1.1fr) minmax(0, 1fr)' } }}>
        <ChartPanel
          title="Role distribution"
          subtitle="Members assigned to each role. A user can hold more than one role, so the bars can exceed the user count."
          meta={<Tag tone="success">Live data</Tag>}
          height={Math.max(220, roleRows.length * 34 + 64)}
          empty={!roleRows.length}
          emptyMessage="Create a role to see how members are distributed."
          caption="Counts come from the role assignments the API reports for this workspace."
        >
          <InteractiveChart notMerge lazyUpdate option={roleOption} style={{ height: '100%', width: '100%' }}/>
        </ChartPanel>

        <SectionCard
          title="Recently added"
          subtitle="The latest people in this workspace."
          action={can('users:read') ? <Button component={Link} to="/users" size="small" endIcon={<ArrowForwardRounded sx={{ fontSize: 15 }}/>}>View all</Button> : undefined}
          bodyPadding={0}
        >
          {data.recent_users.length ? data.recent_users.map(person => <Box key={person.id} display="flex" alignItems="center" gap={1.4} sx={{ px: 2.25, py: 1.25, borderBottom: '1px solid', borderColor: 'divider', '&:last-of-type': { borderBottom: 0 } }}>
            <Avatar sx={{ width: 32, height: 32, fontSize: 11.5, fontWeight: 750 }}>{initials(person.full_name)}</Avatar>
            <Box flex={1} minWidth={0}>
              <Typography fontSize={12.5} fontWeight={650} noWrap>{person.full_name}</Typography>
              <Typography fontSize={11} color="text.secondary" noWrap>{person.email}</Typography>
            </Box>
            <Tag tone={person.is_active ? 'success' : 'neutral'}>{person.is_active ? 'Active' : 'Inactive'}</Tag>
          </Box>)
            : <Box sx={{ px: 2.25, py: 2.5 }}><Typography color="text.secondary" fontSize={12.5}>No users in this workspace yet.</Typography></Box>}
        </SectionCard>
      </Box>

      <Box sx={{ mt: 2 }}>
        <SectionCard
          title="Your workspace, your rules"
          subtitle="Roles bundle the permissions a person needs. Grant only what the job requires; every change is recorded against the administrator who made it."
        >
          <Box display="flex" alignItems="center" gap={1.4} flexWrap="wrap">
            <Box className="table-icon" sx={{ width: 36, height: 36 }}><ShieldOutlined sx={{ fontSize: 18 }}/></Box>
            <Typography fontSize={12} color="text.secondary" sx={{ flex: 1, minWidth: 240, lineHeight: 1.55 }}>
              {data.permissions.toLocaleString()} capabilities are available across {data.roles.toLocaleString()} role{data.roles === 1 ? '' : 's'}.
              {can('roles:read') ? ' Open Roles to review what each one can reach.' : ' Ask a workspace owner for role access.'}
            </Typography>
            {can('roles:read') && <Button component={Link} to="/roles" variant="outlined" size="small" endIcon={<ArrowForwardRounded sx={{ fontSize: 15 }}/>}>Explore roles</Button>}
            {can('permissions:read') && <Button component={Link} to="/permissions" size="small">Permission catalogue</Button>}
          </Box>
        </SectionCard>
      </Box>
    </>}
  </>
}
