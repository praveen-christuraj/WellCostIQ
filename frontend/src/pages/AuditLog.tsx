import { useCallback, useEffect, useMemo, useState } from 'react'
import { Box, Button, MenuItem, TextField, Typography } from '@mui/material'
import { FilterListRounded, RefreshRounded } from '@mui/icons-material'
import type { ColDef } from 'ag-grid-community'
import { api } from '../lib/api'
import type { AuditEntry, AuditPage } from '../lib/types'
import { ErrorMessage, PageHeading, Tag } from '../components/Common'
import { DataTable } from '../components/DataTable'

const ACTIONS = ['login', 'login_failed', 'logout', 'create', 'update', 'delete', 'soft_delete', 'restore', 'rollback', 'permanent_delete', 'import', 'export', 'assign']
const ENTITIES = ['auth', 'user', 'role', 'permission', 'master_data', 'rig', 'well', 'well_configuration', 'well_sub_activity', 'rig_well_export', 'rig_well_deleted', 'afe', 'afe_estimate', 'afe_export', 'database_browser']

// Other Managements → Audit Log: read-only action trail with server-side filters and export.
export default function AuditLog() {
  const [rows, setRows] = useState<AuditEntry[]>([])
  const [total, setTotal] = useState(0)
  const [error, setError] = useState('')
  const [busy, setBusy] = useState(false)
  const [action, setAction] = useState('')
  const [entityType, setEntityType] = useState('')
  const [actor, setActor] = useState('')
  const [dateFrom, setDateFrom] = useState('')
  const [dateTo, setDateTo] = useState('')

  const load = useCallback(async () => {
    setBusy(true); setError('')
    try {
      const params = new URLSearchParams({ page: '1', page_size: '100' })
      if (action) params.set('action', action)
      if (entityType) params.set('entity_type', entityType)
      if (actor.trim()) params.set('actor', actor.trim())
      if (dateFrom) params.set('date_from', dateFrom)
      if (dateTo) params.set('date_to', dateTo)
      const page = await api<AuditPage>(`/audit?${params.toString()}`)
      setRows(page.items)
      setTotal(page.total)
    } catch (e) { setError((e as Error).message) } finally { setBusy(false) }
  }, [action, entityType, actor, dateFrom, dateTo])
  useEffect(() => { load() }, [load])

  const columns = useMemo<ColDef<AuditEntry>[]>(() => [
    { headerName: 'TIME', field: 'created_at', minWidth: 155, valueFormatter: p => p.value ? new Date(p.value).toLocaleString() : '' },
    { headerName: 'ACTOR', field: 'actor_email', minWidth: 190, cellRenderer: ({ data }: { data: AuditEntry }) => data && <Box display="flex" alignItems="center" height="100%"><Box><Typography fontWeight={700} fontSize={12}>{data.actor_name || 'System'}</Typography><Typography color="text.secondary" fontSize={11}>{data.actor_email}</Typography></Box></Box> },
    { headerName: 'ACTION', field: 'action', width: 130, flex: 0, cellRenderer: ({ value }: { value: string }) => <Box display="flex" alignItems="center" height="100%\"><Tag tone={value.includes('failed') ? 'warning' : 'info'}>{String(value).replace('_', ' ')}</Tag></Box> },
    { headerName: 'ENTITY', field: 'entity_type', minWidth: 170, cellRenderer: ({ data }: { data: AuditEntry }) => data && <Box display="flex" alignItems="center" height="100%" gap={.8}><Tag>{data.entity_type}</Tag><Typography fontSize={11.5} color="text.secondary" noWrap>{data.entity_label}</Typography></Box> },
    { headerName: 'SUMMARY', field: 'summary', minWidth: 260 },
    { headerName: 'IP ADDRESS', field: 'ip_address', minWidth: 125, valueFormatter: p => p.value || '—' },
  ], [])

  return <><PageHeading
    eyebrow="OTHER MANAGEMENTS / AUDIT LOG"
    title="Audit log"
    subtitle="Every recorded action in this workspace with its actor, object, source address and time. Read-only: nothing on this page changes a record."
    action={<Button variant="outlined" startIcon={<RefreshRounded/>} onClick={load} disabled={busy}>{busy ? 'Refreshing…' : 'Refresh'}</Button>}
  />
    <Box sx={{ border: '1px solid', borderColor: 'divider', borderRadius: 2.5, mb: 2, overflow: 'hidden', bgcolor: 'background.paper' }}>
      <Box sx={{ display: 'flex', alignItems: 'center', gap: 1, flexWrap: 'wrap', px: 2, py: .95, borderBottom: '1px solid', borderColor: 'divider', bgcolor: 'background.default' }}>
        <FilterListRounded sx={{ fontSize: 16, color: 'text.secondary' }}/>
        <Typography sx={{ fontSize: 10, fontWeight: 750, letterSpacing: '.11em', textTransform: 'uppercase', color: 'text.secondary' }}>Audit filters</Typography>
        <Typography fontSize={11} color="text.secondary">Filters run on the server across the whole trail; the table search narrows the {rows.length} entries already loaded.</Typography>
        {(action || entityType || actor || dateFrom || dateTo) && <Button size="small" color="inherit" sx={{ ml: 'auto' }} onClick={() => { setAction(''); setEntityType(''); setActor(''); setDateFrom(''); setDateTo('') }}>Clear</Button>}
      </Box>
      <Box sx={{ p: 1.6, display: 'flex', gap: 1.4, flexWrap: 'wrap', alignItems: 'center' }}>
        <TextField select size="small" label="Action" value={action} onChange={e => setAction(e.target.value)} sx={{ minWidth: 150 }}>
          <MenuItem value="">All actions</MenuItem>
          {ACTIONS.map(a => <MenuItem key={a} value={a}>{a.replace('_', ' ')}</MenuItem>)}
        </TextField>
        <TextField select size="small" label="Entity" value={entityType} onChange={e => setEntityType(e.target.value)} sx={{ minWidth: 150 }}>
          <MenuItem value="">All entities</MenuItem>
          {ENTITIES.map(t => <MenuItem key={t} value={t}>{t}</MenuItem>)}
        </TextField>
        <TextField size="small" label="Actor (name or email)" value={actor} onChange={e => setActor(e.target.value)} sx={{ minWidth: 200 }}/>
        <Box sx={{ width: '1px', alignSelf: 'stretch', bgcolor: 'divider', mx: .5 }}/>
        <Typography color="text.secondary" fontSize={10} fontWeight={750} letterSpacing=".09em" textTransform="uppercase">Date range</Typography>
        <TextField size="small" type="date" label="From" value={dateFrom} onChange={e => setDateFrom(e.target.value)} InputLabelProps={{ shrink: true }}/>
        <Typography color="text.secondary" fontSize={12}>to</Typography>
        <TextField size="small" type="date" label="To" value={dateTo} onChange={e => setDateTo(e.target.value)} InputLabelProps={{ shrink: true }}/>
      </Box>
    </Box>
    <ErrorMessage message={error}/>
    <DataTable fillHeight fillReserve={total > rows.length ? 40 : 0} rows={rows} columns={columns} searchPlaceholder="Search loaded entries..." exportName="audit-log"/>
    {total > rows.length && <Typography fontSize={12} color="text.secondary" mt={1.5}>Showing the latest {rows.length} of {total} matching entries. Narrow the date range to see older records.</Typography>}
  </>
}
