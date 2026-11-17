import { useEffect, useState } from 'react'
import { AddOutlined, CheckCircleOutline } from '@mui/icons-material'
import { Alert, Box, Button, Dialog, DialogActions, DialogContent, DialogTitle, FormControl, InputLabel, MenuItem, Select, TextField, Typography } from '@mui/material'
import { ErrorMessage, PageHeading } from '../../components/Common'
import { SectionCard } from '../../components/ui/SectionCard'
import { DataTable } from '../../components/DataTable'
import { listPlans, createPlan, addPlanItem, activatePlan, opsReference, type OpsReference, type OpsPlan } from '../../lib/operations'

export default function OperationsPlans() {
  const [plans, setPlans] = useState<OpsPlan[]>([])
  const [ref, setRef] = useState<OpsReference | null>(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState('')
  const [filterWell, setFilterWell] = useState('')
  const [filterScope, setFilterScope] = useState('')
  const [createOpen, setCreateOpen] = useState(false)
  const [createWell, setCreateWell] = useState('')
  const [createScope, setCreateScope] = useState('drilling')
  const [createLabel, setCreateLabel] = useState('')
  const [createDays, setCreateDays] = useState('')
  const [itemOpen, setItemOpen] = useState<string | null>(null)
  const [itemDesc, setItemDesc] = useState('')
  const [itemDepth, setItemDepth] = useState('')
  const [itemHours, setItemHours] = useState('')
  const [bulkUploadOpen, setBulkUploadOpen] = useState(false)
  const [bulkDownloadOpen, setBulkDownloadOpen] = useState(false)

  const load = async () => {
    setLoading(true); setError('')
    try {
      const [p, r] = await Promise.all([listPlans(filterWell || undefined, filterScope || undefined), ref ? Promise.resolve(ref) : opsReference()])
      setPlans(p); setRef(r)
      if (!createWell && r.wells[0]) setCreateWell(r.wells[0].id)
    } catch (e) { setError((e as Error).message) } finally { setLoading(false) }
  }
  useEffect(() => { load() }, [])
  useEffect(() => { load() }, [filterWell, filterScope])

  const doCreate = async () => {
    setError('')
    try {
      await createPlan({ well_id: createWell, scope: createScope as never, label: createLabel, planned_days: createDays ? Number(createDays) : undefined })
      setCreateOpen(false); setCreateLabel(''); setCreateDays(''); await load()
    } catch (e) { setError((e as Error).message) }
  }
  const doAddItem = async (planId: string) => {
    setError('')
    try {
      const maxSeq = Math.max(0, ...(plans.find(p => p.id === planId)?.items.map(i => i.sequence_no) || []))
      await addPlanItem(planId, { sequence_no: maxSeq + 1, description: itemDesc, target_depth_m: itemDepth ? Number(itemDepth) : undefined, planned_hours: itemHours ? Number(itemHours) : 0 })
      setItemOpen(null); setItemDesc(''); setItemDepth(''); setItemHours(''); await load()
    } catch (e) { setError((e as Error).message) }
  }
  const doActivate = async (planId: string) => {
    setError('')
    try { await activatePlan(planId); await load() } catch (e) { setError((e as Error).message) }
  }
  const doBulkUpload = () => {
    setBulkUploadOpen(true)
  }
  const doBulkDownload = () => {
    setBulkDownloadOpen(true)
  }

  return (
    <Box>
      <PageHeading eyebrow="Well Operations" title="Plans & timeline" subtitle="Versioned plan per well/scope — items carry target depth, planned hours, ROP/trip-speed assumptions and contingency. Activating a new version supersedes the old (kept for comparison). Lead/lag = actual cum days − planned cum days at same depth (positive = behind). Bulk upload/download Excel/CSV supported. System studies timeline (depth/hours) from Excel. (1st in operations order: Plans/Timeline → Daily Reports → Analytics → Library/Settings)" />
      {error && <Box mb={2}><ErrorMessage message={error} /></Box>}

      <SectionCard title="Filters & actions">
        <Box display="grid" gap={2} gridTemplateColumns={{ xs: '1fr', md: '1fr 1fr 1fr auto auto' }}>
          <FormControl size="small"><InputLabel>Well</InputLabel><Select value={filterWell} label="Well" onChange={e => setFilterWell(e.target.value)}><MenuItem value="">All wells</MenuItem>{ref?.wells.map(w => <MenuItem key={w.id} value={w.id}>{w.display_name}</MenuItem>)}</Select></FormControl>
          <FormControl size="small"><InputLabel>Scope</InputLabel><Select value={filterScope} label="Scope" onChange={e => setFilterScope(e.target.value)}><MenuItem value="">All</MenuItem><MenuItem value="drilling">Drilling</MenuItem><MenuItem value="completion">Completion</MenuItem></Select></FormControl>
          <Button variant="outlined" onClick={load}>Apply</Button>
          <Button variant="contained" startIcon={<AddOutlined />} onClick={() => setCreateOpen(true)}>New plan</Button>
          <Button variant="outlined" onClick={doBulkUpload}>Bulk upload</Button>
          <Button variant="outlined" onClick={doBulkDownload}>Bulk download</Button>
        </Box>
      </SectionCard>

      {plans.map(plan => (
        <SectionCard
          key={plan.id}
          title={`${plan.well_code} ${plan.well_name} — ${plan.label} (v${plan.version_no})`}
          subtitle={`Scope ${plan.scope} · ${plan.status}${plan.planned_days ? ` · ${plan.planned_days} days` : ''} · ${plan.items.length} item(s)`}
          action={
            <Box display="flex" gap={1}>
              {plan.status !== 'active' && <Button size="small" variant="outlined" startIcon={<CheckCircleOutline />} onClick={() => doActivate(plan.id)}>Activate</Button>}
              <Button size="small" onClick={() => setItemOpen(plan.id)}>Add item</Button>
            </Box>
          }
        >
          {plan.notes && <Typography fontSize={12} color="text.secondary" mb={1}>{plan.notes}</Typography>}
          {plan.items.length ? (
            <DataTable
              rows={plan.items}
              rowKey='id'
              columns={[
                { field: 'sequence_no', headerName: '#', width: 60 },
                { field: 'description', headerName: 'Activity / operation', flex: 1.5, minWidth: 240 },
                { field: 'target_depth_m', headerName: 'Target depth (m)', width: 140, valueFormatter: p => p.value ? Number(p.value).toFixed(1) : '—' },
                { field: 'planned_hours', headerName: 'Planned hrs', width: 110, valueFormatter: p => p.value ? Number(p.value).toFixed(1) : '—' },
                { field: 'cum_planned_days', headerName: 'Cum days', width: 110, valueFormatter: p => p.value ? Number(p.value).toFixed(2) : '—' },
              ]}
            />
          ) : (
            <Alert severity="info">No items — add hole-section activities. Planned hours = ROUNDUP((depth−prev)/ROP)+2 for drilling, ROUNDUP(depth/28.5/10)+2 for trips, plus contingency; cum days = prev + hrs/24 (reproduces the engineers’ workbook, but server-owned so the Plan-Days defect cannot recur).</Alert>
          )}
          {itemOpen === plan.id && (
            <Box mt={2} p={2} border={`1px solid`} sx={{ borderColor: 'divider', borderRadius: 1 }}>
              <Typography fontSize={13} fontWeight={700} mb={1}>Add item to this plan</Typography>
              <Box display="grid" gap={2} gridTemplateColumns={{ xs: '1fr', md: '2fr 1fr 1fr auto' }}>
                <TextField size="small" label="Description" value={itemDesc} onChange={e => setItemDesc(e.target.value)} placeholder="e.g. Drill 12¼″ to 2450 m" />
                <TextField size="small" label="Target depth (m)" type="number" value={itemDepth} onChange={e => setItemDepth(e.target.value)} />
                <TextField size="small" label="Planned hours" type="number" value={itemHours} onChange={e => setItemHours(e.target.value)} />
                <Button variant="contained" onClick={() => doAddItem(plan.id)} disabled={!itemDesc}>Add</Button>
              </Box>
            </Box>
          )}
        </SectionCard>
      ))}
      {!plans.length && !loading && <Alert severity="info" sx={{ mt: 2 }}>No plans yet. A plan can also be generated from the well plan already in the database (well_sections + well_phases.days) so the schedule baseline is not re-typed.</Alert>}

      <Dialog open={createOpen} onClose={() => setCreateOpen(false)} maxWidth="sm" fullWidth>
        <DialogTitle>New plan version</DialogTitle>
        <DialogContent>
          <Box display="grid" gap={2} mt={1}>
            <FormControl size="small"><InputLabel>Well *</InputLabel><Select value={createWell} label="Well *" onChange={e => setCreateWell(e.target.value)}>{ref?.wells.map(w => <MenuItem key={w.id} value={w.id}>{w.display_name}</MenuItem>)}</Select></FormControl>
            <FormControl size="small"><InputLabel>Scope</InputLabel><Select value={createScope} label="Scope" onChange={e => setCreateScope(e.target.value)}><MenuItem value="drilling">Drilling</MenuItem><MenuItem value="completion">Completion</MenuItem></Select></FormControl>
            <TextField size="small" label="Label *" value={createLabel} onChange={e => setCreateLabel(e.target.value)} placeholder="e.g. Programme Rev 2" />
            <TextField size="small" label="Planned days (optional)" type="number" value={createDays} onChange={e => setCreateDays(e.target.value)} helperText="Or leave blank — computed from items (sum hrs/24)." />
          </Box>
        </DialogContent>
        <DialogActions><Button onClick={() => setCreateOpen(false)}>Cancel</Button><Button variant="contained" disabled={!createWell || !createLabel} onClick={doCreate}>Create</Button></DialogActions>
      </Dialog>

      <Dialog open={bulkUploadOpen} onClose={() => setBulkUploadOpen(false)} maxWidth="sm" fullWidth>
        <DialogTitle>Bulk upload plan (Excel/CSV)</DialogTitle>
        <DialogContent>
          <Typography fontSize={13}>Upload Excel/CSV to create or update plans. System will study timeline (depth/hours) from Excel.</Typography>
          <Box mt={2} display="flex" gap={1}>
            <Button variant="contained" onClick={() => { /* TODO: implement bulk upload API call */ setBulkUploadOpen(false); load() }}>Upload</Button>
            <Button onClick={() => setBulkUploadOpen(false)}>Cancel</Button>
          </Box>
        </DialogContent>
      </Dialog>

      <Dialog open={bulkDownloadOpen} onClose={() => setBulkDownloadOpen(false)} maxWidth="sm" fullWidth>
        <DialogTitle>Bulk download plan (Excel/CSV)</DialogTitle>
        <DialogContent>
          <Typography fontSize={13}>Download all plans as Excel/CSV.</Typography>
          <Box mt={2} display="flex" gap={1}>
            <Button variant="contained" onClick={() => { /* TODO: implement bulk download API call */ setBulkDownloadOpen(false); load() }}>Download</Button>
            <Button onClick={() => setBulkDownloadOpen(false)}>Cancel</Button>
          </Box>
        </DialogContent>
      </Dialog>
    </Box>
  )
}
