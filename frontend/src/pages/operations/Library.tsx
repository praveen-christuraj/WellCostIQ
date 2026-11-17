import { useEffect, useState } from 'react'
import { Box, Button, Tab, Tabs, TextField, Alert, Typography } from '@mui/material'
import { DataTable } from '../../components/DataTable'
import { ErrorMessage, PageHeading } from '../../components/Common'
import { SectionCard } from '../../components/ui/SectionCard'
import { api } from '../../lib/api'

type Kind = 'operation-codes' | 'activity-codes' | 'npt-codes' | 'agencies' | 'causes'
const KINDS: { key: Kind; label: string }[] = [
  { key: 'operation-codes', label: 'Operation codes (A–T)' },
  { key: 'activity-codes', label: 'Activity codes (1–37)' },
  { key: 'npt-codes', label: 'NPT codes (75)' },
  { key: 'agencies', label: 'Agencies (30)' },
  { key: 'causes', label: 'Cause codes (17)' },
]

export default function OperationsLibrary() {
  const [kind, setKind] = useState<Kind>('operation-codes')
  const [rows, setRows] = useState<Record<string, unknown>[]>([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState('')
  const [formOpen, setFormOpen] = useState(false)
  const [editing, setEditing] = useState<Record<string, unknown> | null>(null)
  const [form, setForm] = useState<Record<string, string>>({})

  const load = async () => {
    setLoading(true); setError('')
    try { const data = await api<Record<string, unknown>[]>(`/operations/masters/${kind}`, { action: `Load ${kind}` }); setRows(data) } catch (e) { setError((e as Error).message) } finally { setLoading(false) }
  }
  useEffect(() => { load() }, [kind])

  const startCreate = () => {
    setEditing(null)
    if (kind === 'operation-codes') setForm({ operation_code: '', operation_name: '', category: 'other', default_classification: 'Planned', description: '' })
    else if (kind === 'activity-codes') setForm({ activity_code: '', activity_name: '', default_allocation: 'PT', description: '' })
    else if (kind === 'npt-codes') setForm({ npt_code: '', npt_name: '', family: 'other', category: 'other', description: '' })
    else if (kind === 'agencies') setForm({ agency_code: '', agency_name: '', category: 'operator', description: '' })
    else setForm({ cause_code: '', cause_name: '', description: '' })
    setFormOpen(true)
  }
  const startEdit = (row: Record<string, unknown>) => {
    setEditing(row)
    if (kind === 'operation-codes') setForm({ operation_code: String(row.operation_code || ''), operation_name: String(row.operation_name || ''), category: String(row.category || ''), default_classification: String(row.default_classification || 'Planned'), description: String(row.description || '') })
    else if (kind === 'activity-codes') setForm({ activity_code: String(row.activity_code || ''), activity_name: String(row.activity_name || ''), default_allocation: String(row.default_allocation || 'PT'), description: String(row.description || '') })
    else if (kind === 'npt-codes') setForm({ npt_code: String(row.npt_code || ''), npt_name: String(row.npt_name || ''), family: String(row.family || ''), category: String(row.category || ''), description: String(row.description || '') })
    else if (kind === 'agencies') setForm({ agency_code: String(row.agency_code || ''), agency_name: String(row.agency_name || ''), category: String(row.category || ''), description: String(row.description || '') })
    else setForm({ cause_code: String(row.cause_code || ''), cause_name: String(row.cause_name || ''), description: String(row.description || '') })
    setFormOpen(true)
  }
  const save = async () => {
    setError('')
    try {
      if (editing) await api(`/operations/masters/${kind}/${editing.id}`, { method: 'PUT', body: JSON.stringify(form), action: `Update ${kind}` })
      else await api(`/operations/masters/${kind}`, { method: 'POST', body: JSON.stringify(form), action: `Create ${kind}` })
      setFormOpen(false); await load()
    } catch (e) { setError((e as Error).message) }
  }

  const columns =
    kind === 'operation-codes'
      ? [{ field: 'operation_code', headerName: 'Code', width: 100 }, { field: 'operation_name', headerName: 'Name', flex: 1 }, { field: 'default_classification', headerName: 'Class', width: 100 }, { field: 'is_productive_default', headerName: 'Prod?', width: 80, valueFormatter: (p: { value: boolean }) => p.value ? 'Yes' : 'No' }, { field: 'description', headerName: 'Description', flex: 1 }]
      : kind === 'activity-codes'
        ? [{ field: 'activity_code', headerName: 'Code', width: 100 }, { field: 'activity_name', headerName: 'Name', flex: 1 }, { field: 'default_allocation', headerName: 'Alloc', width: 90 }, { field: 'description', headerName: 'Description', flex: 1 }]
        : kind === 'npt-codes'
          ? [{ field: 'npt_code', headerName: 'Code', width: 120 }, { field: 'npt_name', headerName: 'Name', flex: 1 }, { field: 'family', headerName: 'Family', width: 120 }, { field: 'category', headerName: 'Category', width: 120 }, { field: 'description', headerName: 'Description', flex: 1 }]
          : kind === 'agencies'
            ? [{ field: 'agency_code', headerName: 'Code', width: 140 }, { field: 'agency_name', headerName: 'Name', flex: 1 }, { field: 'category', headerName: 'Category', width: 130 }, { field: 'description', headerName: 'Description', flex: 1 }]
            : [{ field: 'cause_code', headerName: 'Code', width: 120 }, { field: 'cause_name', headerName: 'Name', flex: 1 }, { field: 'description', headerName: 'Description', flex: 1 }]

  return (
    <Box>
      <PageHeading eyebrow="Well Operations" title="Code library — operations" subtitle="All categorizations and codes are user-configurable: phase codes, operation codes A–T, activity codes, NPT family, agencies and causes. Starter list ships as import templates — load via import, not seeded by migration." />
      {error && <Box mb={2}><ErrorMessage message={error} /></Box>}

      <Tabs value={kind} onChange={(_, v) => setKind(v)} variant="scrollable" scrollButtons="auto">
        {KINDS.map(k => <Tab key={k.key} value={k.key} label={k.label} />)}
      </Tabs>

      <SectionCard title={`${KINDS.find(k => k.key === kind)?.label} — ${rows.length} record(s)`} action={<Button variant="contained" onClick={startCreate} disabled={loading}>New</Button>}>
        <DataTable
          rows={rows}
          
          rowKey='id'
          columns={[...(columns as never[]), { field: 'id', headerName: '', width: 90, sortable: false, cellRenderer: (p: { data: Record<string, unknown> }) => <Button size="small" onClick={() => startEdit(p.data)}>Edit</Button> }]}
        />
        <Alert severity="info" sx={{ mt: 2 }}>The `Codes` sheet from operations reports seeded 256 activities, 37 activity codes, 75 NPT codes, 30 agencies, 17 causes and 10 phase codes — captured in `docs/operations/activity-taxonomy-extracted.csv`. Import via Master Data import (xlsx/csv) or add here. Mapping from OpenWells phase abbreviations (DRLPRO, DRLSUR, CSGIN2, EVAL…) → hole section + operation code lives in `ops_phase_map` (editable).</Alert>
      </SectionCard>

      {formOpen && (
        <Box mt={2} p={2} border={`1px solid`} sx={{ borderColor: 'divider', borderRadius: 2 }} bgcolor="background.paper">
          <Typography fontWeight={700} mb={1}>{editing ? 'Edit' : 'New'} — {kind}</Typography>
          <Box display="grid" gap={2} gridTemplateColumns={{ xs: '1fr', md: '1fr 1fr' }}>
            {Object.keys(form).map(k => (
              <TextField key={k} size="small" label={k} value={form[k]} onChange={e => setForm(f => ({ ...f, [k]: e.target.value }))} />
            ))}
          </Box>
          <Box mt={2} display="flex" gap={1}><Button variant="contained" onClick={save}>Save</Button><Button onClick={() => setFormOpen(false)}>Cancel</Button></Box>
        </Box>
      )}
    </Box>
  )
}
