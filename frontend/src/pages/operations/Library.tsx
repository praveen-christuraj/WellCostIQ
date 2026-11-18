import { useEffect, useState } from 'react'
import { Alert, Box, Button, MenuItem, Tab, Tabs, TextField, Typography } from '@mui/material'
import { AddRounded, DeleteOutlineRounded, RestoreRounded } from '@mui/icons-material'
import { FormDialog, PageHeading } from '../../components/Common'
import { DataTable } from '../../components/DataTable'
import { ImportDialog } from '../../components/ImportDialog'
import { useAuth } from '../../context/AuthContext'
import { api, body } from '../../lib/api'
import { auditExport } from '../../lib/operations'

const kinds = {
  'operation-codes': {
    label: 'Operation codes',
    code: 'operation_code',
    name: 'operation_name',
    defaults: { default_classification: 'Planned', category: 'other' },
  },
  'activity-codes': {
    label: 'Activity codes',
    code: 'activity_code',
    name: 'activity_name',
    defaults: { default_allocation: 'PT' },
  },
  'npt-codes': { label: 'NPT codes', code: 'npt_code', name: 'npt_name', defaults: { family: 'other', category: 'other' } },
  causes: { label: 'Cause codes', code: 'cause_code', name: 'cause_name', defaults: {} },
  'phase-codes': { label: 'Phase codes', code: 'phase_code', name: 'phase_name', defaults: {} },
  'source-marks': {
    label: 'Source mark rules',
    code: 'mark_code',
    name: 'mark_name',
    defaults: { default_classification: 'Planned', default_allocation: 'PT' },
  },
} as const
type Kind = keyof typeof kinds
type Row = { id: string; is_deleted: boolean } & Record<string, unknown>

export default function OperationsLibrary() {
  const { can } = useAuth(),
    [kind, setKind] = useState<Kind>('operation-codes'),
    [deleted, setDeleted] = useState(false),
    [rows, setRows] = useState<Row[]>([]),
    [selected, setSelected] = useState<Row[]>([])
  const [form, setForm] = useState<Record<string, string> | null>(null),
    [id, setId] = useState(''),
    [pending, setPending] = useState<Row[]>([]),
    [importing, setImporting] = useState(false),
    [error, setError] = useState(''),
    [busy, setBusy] = useState(false)
  const spec = kinds[kind],
    path = `/operations/masters/${kind}`
  const getRows = () =>
    api<Row[]>(path + (deleted ? '?include_deleted=true' : '')).then((rs) => rs.filter((r) => r.is_deleted === deleted))
  const load = async () => {
    setRows(await getRows())
    setSelected([])
  }
  useEffect(() => {
    let current = true
    setRows([])
    setSelected([])
    setError('')
    getRows()
      .then((rs) => {
        if (current) setRows(rs)
      })
      .catch((e) => {
        if (current) setError(e.message)
      })
    return () => {
      current = false
    }
  }, [kind, deleted])
  const edit = (row?: Row) => {
    const defaults = { [spec.code]: '', [spec.name]: '', ...spec.defaults, description: '' }
    setId(row?.id ?? '')
    setForm(Object.fromEntries(Object.entries(defaults).map(([k, v]) => [k, String(row?.[k] ?? v)])))
    setError('')
  }
  const run = async (fn: () => Promise<void>) => {
    setBusy(true)
    setError('')
    try {
      await fn()
      await load()
    } catch (e) {
      setError((e as Error).message)
    } finally {
      setBusy(false)
    }
  }
  return (
    <Box>
      <PageHeading
        eyebrow="Well Operations"
        title="Code library"
        subtitle="Define this workspace’s activity, operation and reason codes. Codes are displayed alongside their names. Responsible parties for new NPT / UPA entries come from active Master Data vendors."
        action={
          <>
            {!deleted && can('ops-master:create') && (
              <Button variant="contained" startIcon={<AddRounded />} onClick={() => edit()}>
                New code
              </Button>
            )}
            <Button variant="outlined" startIcon={<RestoreRounded />} onClick={() => setDeleted(!deleted)}>
              {deleted ? 'Active entries' : 'Deleted entries'}
            </Button>
          </>
        }
      />
      <Tabs variant="scrollable" value={kind} onChange={(_, v) => setKind(v)}>
        {(Object.keys(kinds) as Kind[]).map((k) => (
          <Tab key={k} value={k} label={kinds[k].label} />
        ))}
      </Tabs>
      {kind === 'source-marks' && (
        <Alert severity="info">
          Add a printed source mark to override its suggested classification and allocation. These rules affect future drafts,
          never saved logs.
        </Alert>
      )}
      {error && <Alert severity="error">{error}</Alert>}
      {selected.length > 0 && (
        <Box display="flex" gap={2} alignItems="center" py={1}>
          <Typography>{selected.length} selected</Typography>
          {can(deleted ? 'ops-master:restore' : 'ops-master:delete') && (
            <Button onClick={() => setPending(selected)}>{deleted ? 'Restore selected' : 'Move to Deleted entries'}</Button>
          )}
        </Box>
      )}
      <DataTable
        key={`${kind}/${deleted}`}
        rows={rows}
        fillHeight
        selectable
        exportSelected
        onSelectionChange={setSelected}
        canExport={can('ops-master:export')}
        onExport={auditExport('library')}
        exportName={`operations-${kind}`}
        onImport={!deleted && can('ops-master:import') ? () => setImporting(true) : undefined}
        columns={[
          { field: spec.code, headerName: 'Code' },
          {
            field: spec.name,
            headerName: 'Name',
            cellRenderer: ({ data: r }: { data: Row }) => `${r[spec.name]} (${r[spec.code]})`,
          },
          ...Object.keys(spec.defaults).map((k) => ({ field: k, headerName: k.replaceAll('_', ' ') })),
          { field: 'description', headerName: 'Description' },
          {
            headerName: 'Actions',
            width: 155,
            minWidth: 140,
            sortable: false,
            cellRenderer: ({ data: r }: { data: Row }) => (
              <>
                {!deleted && can('ops-master:update') && (
                  <Button size="small" onClick={() => edit(r)}>
                    Edit
                  </Button>
                )}
                {can(deleted ? 'ops-master:restore' : 'ops-master:delete') && (
                  <Button
                    size="small"
                    aria-label={deleted ? 'Restore' : 'Delete'}
                    color={deleted ? 'inherit' : 'error'}
                    onClick={() => setPending([r])}
                  >
                    {deleted ? <RestoreRounded /> : <DeleteOutlineRounded />}
                  </Button>
                )}
              </>
            ),
          },
        ]}
      />
      {form && (
        <FormDialog
          open
          title={`${id ? 'Edit' : 'New'} code`}
          onClose={() => setForm(null)}
          onSubmit={() =>
            run(async () => {
              await api(path + (id ? `/${id}` : ''), { method: id ? 'PUT' : 'POST', body: body(form) })
              setForm(null)
            })
          }
          busy={busy}
          submitDisabled={!form[spec.code]?.trim() || !form[spec.name]?.trim()}
        >
          <Box display="grid" gap={2} pt={1}>
            {Object.keys(form).map((k) => {
              const options =
                k === 'default_classification'
                  ? ['Planned', 'UPA', 'NPT']
                  : k === 'default_allocation'
                    ? ['PT', 'UPA', 'NPT', 'SP']
                    : null
              return (
                <TextField
                  key={k}
                  select={!!options}
                  label={k.replaceAll('_', ' ')}
                  value={form[k]}
                  onChange={(e) => setForm({ ...form, [k]: e.target.value })}
                >
                  {options?.map((o) => (
                    <MenuItem key={o} value={o}>
                      {o}
                    </MenuItem>
                  ))}
                </TextField>
              )
            })}
            {error && <Alert severity="error">{error}</Alert>}
          </Box>
        </FormDialog>
      )}
      {pending.length > 0 && (
        <FormDialog
          open
          title={`${deleted ? 'Restore' : 'Move to Deleted entries'} · ${pending.length} codes?`}
          danger={!deleted}
          onClose={() => setPending([])}
          submitLabel={deleted ? 'Restore' : 'Delete'}
          busy={busy}
          onSubmit={() =>
            run(async () => {
              await api(`${path}/bulk-${deleted ? 'restore' : 'delete'}`, {
                method: 'POST',
                body: body({ ids: pending.map((r) => r.id) }),
              })
              setPending([])
            })
          }
        >
          Historical reports retain their recorded values.{error && <Alert severity="error">{error}</Alert>}
        </FormDialog>
      )}
      {importing && (
        <ImportDialog
          open
          title={`Import ${spec.label.toLowerCase()}`}
          onClose={() => setImporting(false)}
          headers={[spec.code, spec.name]}
          optionalHeaders={[...Object.keys(spec.defaults), 'description']}
          templateName={`${kind}.csv`}
          headerAliases={{
            Code: spec.code,
            Name: spec.name,
            Description: 'description',
            ...Object.fromEntries(Object.keys(spec.defaults).map((k) => [k.replaceAll('_', ' '), k])),
          }}
          onRows={async (rows) => {
            const result = await api<{ errors: string[] }>(path + '/import', {
              method: 'POST',
              body: body(rows.map((r) => Object.fromEntries(Object.entries(r).filter(([, v]) => v !== '')))),
            })
            await load()
            return result.errors
          }}
        />
      )}
    </Box>
  )
}
