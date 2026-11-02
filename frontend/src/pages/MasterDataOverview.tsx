import { useEffect, useState } from 'react'
import { Link as RouterLink } from 'react-router-dom'
import { ArrowForwardRounded, DeleteOutlineRounded, Inventory2Outlined, LibraryBooksOutlined, StorageOutlined } from '@mui/icons-material'
import { Box, Button, Typography } from '@mui/material'
import { api } from '../lib/api'
import type { MasterDataActivity, MasterDataOverview as OverviewData } from '../lib/masterData'
import { ErrorMessage, PageHeading, Tag } from '../components/Common'
import { DatasetState } from '../components/ui/DatasetState'
import { SectionCard } from '../components/ui/SectionCard'
import { StatCard } from '../components/ui/StatCard'

// Vendors and PO/SO Orders have their own pages; the reference lists share one.
const CONSUMABLE_KEYS = ['mud-chemicals', 'cement-additives', 'fuel-types', 'drill-bits']

const modulePath = (key: string) => {
  if (key === 'vendors' || key === 'po-so-orders' || key === 'services') return `/master-data/${key}`
  if (key === 'tangibles') return '/master-data/tangibles'
  if (CONSUMABLE_KEYS.includes(key)) return `/master-data/consumables?type=${key}`
  return `/master-data/records?module=${key}`
}

function activityTone(action: string): 'neutral' | 'success' | 'info' | 'warning' {
  if (action === 'create' || action === 'restore' || action === 'import') return 'success'
  if (action === 'soft_delete' || action === 'permanent_delete') return 'warning'
  return 'info'
}

function RecentActivity({ entries }: { entries: MasterDataActivity[] }) {
  if (!entries.length) {
    return <DatasetState kind="empty" compact title="No master data activity yet" message="Creates, edits, imports and deletions will appear here as they are audited."/>
  }
  return <Box>
    {entries.map(entry => <Box key={entry.id} display="flex" alignItems="flex-start" gap={1.2} sx={{ borderTop: '1px solid', borderColor: 'divider', py: 1.35, '&:first-of-type': { borderTop: 0 } }}>
      <Box sx={{ pt: .2 }}><Tag tone={activityTone(entry.action)}>{entry.action.replaceAll('_', ' ')}</Tag></Box>
      <Box flex={1} minWidth={0}>
        <Typography fontSize={12.5} fontWeight={650} noWrap>{entry.entity_label}</Typography>
        <Typography color="text.secondary" fontSize={11.5}>{entry.summary}</Typography>
        <Typography color="text.disabled" fontSize={10.5} mt={.35}>{new Date(entry.created_at).toLocaleString()}</Typography>
      </Box>
    </Box>)}
  </Box>
}

export default function MasterDataOverview() {
  const [data, setData] = useState<OverviewData | null>(null)
  const [error, setError] = useState('')

  useEffect(() => {
    api<OverviewData>('/master-data/overview')
      .then(setData)
      .catch((caught: unknown) => setError(caught instanceof Error ? caught.message : 'Could not load the module summary'))
  }, [])

  return <>
    <PageHeading
      eyebrow="MASTER DATA MANAGEMENT / OVERVIEW"
      title="Master data"
      subtitle="The workspace reference data every costing workflow reads from: units, currencies, phases, hole sections, activities, services, vendors and their PO/SO orders."
      action={<Box display="flex" gap={1} flexWrap="wrap">
        <Button component={RouterLink} to="/master-data/deleted" variant="outlined" startIcon={<DeleteOutlineRounded/>}>Deleted entries</Button>
        <Button component={RouterLink} to="/master-data/records" variant="contained" endIcon={<ArrowForwardRounded/>}>Manage master data</Button>
      </Box>}
    />
    <ErrorMessage message={error}/>

    {!data ? <DatasetState kind="loading" title="Loading master data…"/> : <>
      <Box display="grid" gap={1.5} sx={{ gridTemplateColumns: { xs: 'repeat(2, minmax(0,1fr))', md: 'repeat(3, minmax(0,1fr))' } }}>
        <StatCard label="Active records" value={data.active_records.toLocaleString()} hint="Available to well-costing workflows" icon={<StorageOutlined fontSize="small"/>}/>
        <StatCard label="Deleted entries" value={data.deleted_records.toLocaleString()} hint="Recoverable until permanently removed" icon={<DeleteOutlineRounded fontSize="small"/>} tone={data.deleted_records ? 'warning' : 'default'}/>
        <StatCard label="Reference types" value={data.module_count.toLocaleString()} hint="Reference lists, vendors and PO/SO orders" icon={<LibraryBooksOutlined fontSize="small"/>}/>
      </Box>

      <Box display="grid" gap={2} sx={{ mt: 2, gridTemplateColumns: { xs: '1fr', lg: 'minmax(0, 1.2fr) minmax(0, 1fr)' } }}>
        <SectionCard title="Data by type" subtitle="Active and deleted records in each reference catalogue." meta={<Tag tone="info">{data.active_records + data.deleted_records} total</Tag>} bodyPadding={0}>
          {data.modules.map(module => <Box key={module.key} display="flex" alignItems="center" gap={1.4} sx={{ px: 2.25, py: 1.35, borderBottom: '1px solid', borderColor: 'divider', '&:last-of-type': { borderBottom: 0 }, '&:hover': { bgcolor: 'action.hover' } }}>
            <Box className="table-icon"><Inventory2Outlined sx={{ fontSize: 17 }}/></Box>
            <Box flex={1} minWidth={0}>
              <Typography fontSize={12.5} fontWeight={650}>{module.label}</Typography>
              <Typography color="text.secondary" fontSize={11}>{module.active_count} active · {module.deleted_count} deleted</Typography>
            </Box>
            <Button component={RouterLink} to={modulePath(module.key)} size="small" endIcon={<ArrowForwardRounded sx={{ fontSize: 16 }}/>}>Open</Button>
          </Box>)}
        </SectionCard>

        <SectionCard title="Recent activity" subtitle="Changes and lifecycle events, recorded in the audit trail." meta={<Tag tone="success">Audit enabled</Tag>} bodyPadding={0}>
          <Box sx={{ px: 2.25, py: 1 }}>
            <RecentActivity entries={data.recent_activity}/>
          </Box>
        </SectionCard>
      </Box>
    </>}
  </>
}
