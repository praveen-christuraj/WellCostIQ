import { useEffect, useMemo, useState } from 'react'
import { AddOutlined, DeleteOutlineRounded, RestoreOutlined } from '@mui/icons-material'
import { Alert, Box, Button, Chip, Dialog, DialogActions, DialogContent, DialogTitle, FormControl, InputLabel, MenuItem, Select, TextField, Typography } from '@mui/material'
import { DataTable } from '../../components/DataTable'
import { ErrorMessage, PageHeading } from '../../components/Common'
import { SectionCard } from '../../components/ui/SectionCard'
import { listReports, opsReference, createReport, bulkDeleteReports, bulkRestoreReports, type OpsReport, type OpsReference } from '../../lib/operations'

function statusColor(v: string) {
  if (v === 'approved') return 'positive' as const
  if (v === 'submitted') return 'info' as const
  if (v === 'rejected') return 'error' as const
  if (v === 'draft' || v === 'in_review') return 'warning' as const
  return 'default' as const
}

export default function OperationsReports() {
  const [reports, setReports] = useState<OpsReport[]>([])
  const [ref, setRef] = useState<OpsReference | null>(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState('')
  const [filterWell, setFilterWell] = useState('')
  const [filterScope, setFilterScope] = useState('')
  const [filterStatus, setFilterStatus] = useState('')
  const [filterType, setFilterType] = useState('')
  const [dateFrom, setDateFrom] = useState('')
  const [dateTo, setDateTo] = useState('')
  const [selected, setSelected] = useState<string[]>([])
  const [createOpen, setCreateOpen] = useState(false)
  const [createWell, setCreateWell] = useState('')
  const [createRig, setCreateRig] = useState('')
  const [createScope, setCreateScope] = useState('drilling')
  const [createDate, setCreateDate] = useState(new Date().toISOString().slice(0, 10))
  const [createNo, setCreateNo] = useState('')
  const [saving, setSaving] = useState(false)
  const [_showDeleted, _setShowDeleted] = useState(false)

  const load = async () => {
    setLoading(true); setError('')
    try {
      const params: Record<string, string | undefined> = {}
      if (filterWell) params.well_id = filterWell
      if (filterScope) params.scope = filterScope
      if (filterStatus) params.status = filterStatus
      if (filterType) params.report_type = filterType
      if (dateFrom) params.from = dateFrom
      if (dateTo) params.to = dateTo
      const [rows, r] = await Promise.all([
        listReports(params),
        ref ? Promise.resolve(ref) : opsReference(),
      ])
      setReports(rows)
      setRef(r)
      if (!createWell && r.wells[0]) setCreateWell(r.wells[0].id)
      if (!createRig && r.rigs[0]) setCreateRig(r.rigs[0].id)
    } catch (e) { setError((e as Error).message) } finally { setLoading(false) }
  }

  useEffect(() => { load() }, [])
  useEffect(() => { load() }, [filterWell, filterScope, filterStatus, filterType])

  const doCreate = async () => {
    if (!createWell || !createDate) return
    setSaving(true); setError('')
    try {
      await createReport({ well_id: createWell, rig_id: createRig || undefined, scope: createScope, report_date: createDate, report_no_text: createNo })
      setCreateOpen(false); setCreateNo(''); await load()
    } catch (e) { setError((e as Error).message) } finally { setSaving(false) }
  }

  const doDelete = async () => {
    if (!selected.length) return
    setError('')
    try { await bulkDeleteReports(selected); setSelected([]); await load() } catch (e) { setError((e as Error).message) }
  }
  const doRestore = async () => {
    if (!selected.length) return
    try { await bulkRestoreReports(selected); setSelected([]); await load() } catch (e) { setError((e as Error).message) }
  }

  return (
    <Box>
      <PageHeading
        eyebrow="Well Operations" title="Daily reports"
        subtitle="DDR/DCR/D​MR/RMR — each well × scope × date is one period. The 24h log reconciles to planned/UPA/NPT hours; brief and depth-vs-time are computed, not typed."
        action={
          <Box display="flex" gap={1}>
            <Button variant="contained" startIcon={<AddOutlined />} onClick={() => setCreateOpen(true)}>New report</Button>
            <Button variant="outlined" color="error" startIcon={<DeleteOutlineRounded />} disabled={!selected.length} onClick={doDelete}>Delete</Button>
            <Button variant="outlined" startIcon={<RestoreOutlined />} disabled={!selected.length} onClick={doRestore}>Restore</Button>
          </Box>
        }
      />
      {error && <Box mb={2}><ErrorMessage message={error} /></Box>}

      <SectionCard title="Filters">
        <Box display="grid" gap={2} gridTemplateColumns={{ xs: '1fr', md: '1fr 1fr 1fr 1fr 1fr 1fr auto' }}>
          <FormControl size="small" fullWidth><InputLabel>Well</InputLabel><Select value={filterWell} label="Well" onChange={e => setFilterWell(e.target.value)}><MenuItem value="">All wells</MenuItem>{ref?.wells.map(w => <MenuItem key={w.id} value={w.id}>{w.display_name}</MenuItem>)}</Select></FormControl>
          <FormControl size="small" fullWidth><InputLabel>Scope</InputLabel><Select value={filterScope} label="Scope" onChange={e => setFilterScope(e.target.value)}><MenuItem value="">All</MenuItem><MenuItem value="drilling">Drilling</MenuItem><MenuItem value="completion">Completion</MenuItem></Select></FormControl>
          <FormControl size="small" fullWidth><InputLabel>Status</InputLabel><Select value={filterStatus} label="Status" onChange={e => setFilterStatus(e.target.value)}><MenuItem value="">All</MenuItem><MenuItem value="draft">Draft</MenuItem><MenuItem value="submitted">Submitted</MenuItem><MenuItem value="approved">Approved</MenuItem><MenuItem value="rejected">Rejected</MenuItem></Select></FormControl>
          <FormControl size="small" fullWidth><InputLabel>Type</InputLabel><Select value={filterType} label="Type" onChange={e => setFilterType(e.target.value)}><MenuItem value="">All</MenuItem><MenuItem value="DDR">DDR</MenuItem><MenuItem value="DCR">DCR</MenuItem><MenuItem value="DMR">DMR</MenuItem><MenuItem value="RMR">RMR</MenuItem></Select></FormControl>
          <TextField size="small" type="date" label="From" value={dateFrom} onChange={e => setDateFrom(e.target.value)} InputLabelProps={{ shrink: true }} />
          <TextField size="small" type="date" label="To" value={dateTo} onChange={e => setDateTo(e.target.value)} InputLabelProps={{ shrink: true }} />
          <Button variant="outlined" onClick={load}>Apply</Button>
        </Box>
      </SectionCard>

      <SectionCard title={`${reports.length} report(s)`}>
        <DataTable
          rows={reports}
          
          rowKey='id'
          onSelectionChange={rows => setSelected(rows.map((r: { id: string }) => r.id))}
          columns={[
            { field: 'report_date', headerName: 'Date', width: 120 },
            { field: 'well_code_snapshot', headerName: 'Well', width: 150 },
            { field: 'rig_code_snapshot', headerName: 'Rig', width: 120, valueFormatter: p => p.value || '—' },
            { field: 'scope', headerName: 'Scope', width: 110 },
            { field: 'report_type', headerName: 'Type', width: 80 },
            { field: 'report_no_text', headerName: 'No.', width: 90, valueFormatter: p => p.value || '—' },
            { field: 'day_number', headerName: 'Day', width: 70, valueFormatter: p => p.value ?? '—' },
            { field: 'depth_end_m', headerName: 'Depth (m)', width: 110, valueFormatter: p => p.value ? Number(p.value).toFixed(1) : '—' },
            {
              field: 'status', headerName: 'Status', width: 120,
              cellRenderer: (p: { value: string }) => <Chip size="small" label={p.value} color={statusColor(p.value)} />,
            },
            {
              field: 'extraction_status', headerName: 'Extraction', width: 130,
              cellRenderer: (p: { value: string }) => <Chip size="small" label={p.value || 'none'} color={p.value === 'needs_review' ? 'warning' : p.value === 'reviewed' ? 'positive' : 'default'} />,
            },
            { field: 'blocks', headerName: 'Blocks', width: 80, valueGetter: p => p.data?.blocks?.length ?? 0 },
            {
              field: 'id', headerName: '', width: 100, sortable: false,
              cellRenderer: (p: { data: OpsReport }) => <Button size="small" href={`/operations/reports/${p.data.id}`} variant="outlined">Open</Button>,
            },
          ]}
        />
        {!reports.length && !loading && <Alert severity="info" sx={{ mt: 2 }}>No reports match these filters. Create one manually or upload a PDF/Excel in Documents — extraction will draft it for review.</Alert>}
      </SectionCard>

      <Dialog open={createOpen} onClose={() => setCreateOpen(false)} maxWidth="sm" fullWidth>
        <DialogTitle>New daily report</DialogTitle>
        <DialogContent>
          <Box display="grid" gap={2} mt={1}>
            <FormControl size="small" fullWidth><InputLabel>Well *</InputLabel><Select value={createWell} label="Well *" onChange={e => setCreateWell(e.target.value)}>{ref?.wells.map(w => <MenuItem key={w.id} value={w.id}>{w.display_name}</MenuItem>)}</Select></FormControl>
            <FormControl size="small" fullWidth><InputLabel>Rig</InputLabel><Select value={createRig} label="Rig" onChange={e => setCreateRig(e.target.value)}><MenuItem value="">None</MenuItem>{ref?.rigs.map(r => <MenuItem key={r.id} value={r.id}>{r.display_name}</MenuItem>)}</Select></FormControl>
            <FormControl size="small" fullWidth><InputLabel>Scope</InputLabel><Select value={createScope} label="Scope" onChange={e => setCreateScope(e.target.value)}><MenuItem value="drilling">Drilling</MenuItem><MenuItem value="completion">Completion</MenuItem></Select></FormControl>
            <TextField size="small" type="date" label="Report date *" value={createDate} onChange={e => setCreateDate(e.target.value)} InputLabelProps={{ shrink: true }} />
            <TextField size="small" label="Report no." value={createNo} onChange={e => setCreateNo(e.target.value)} placeholder="e.g. 28" />
            <Alert severity="info">Period is 00:00–24:00 local (configurable in Settings). Day number is derived from spud; edit it if the well has no spud yet. Blocks must sum to ~1440 min (2-min tolerance); one spill block past midnight is allowed.</Alert>
          </Box>
        </DialogContent>
        <DialogActions>
          <Button onClick={() => setCreateOpen(false)}>Cancel</Button>
          <Button variant="contained" disabled={!createWell || !createDate || saving} onClick={doCreate}>{saving ? 'Creating…' : 'Create'}</Button>
        </DialogActions>
      </Dialog>
    </Box>
  )
}
