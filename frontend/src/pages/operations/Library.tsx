import { useEffect, useState } from 'react'
import { useSearchParams } from 'react-router-dom'
import { Alert, Box, Button, MenuItem, Tab, Tabs, TextField, Typography } from '@mui/material'
import { AddRounded, DeleteOutlineRounded, RestoreRounded } from '@mui/icons-material'
import { FormDialog, PageHeading } from '../../components/Common'
import { DataTable } from '../../components/DataTable'
import { ImportDialog } from '../../components/ImportDialog'
import { useAuth } from '../../context/AuthContext'
import { api, body } from '../../lib/api'
import {
  auditExport,
  defaultOpsCodes,
  opsCorrelationReference,
  opsCorrelations,
  opsCreateCorrelation,
  opsDeleteCorrelations,
  opsRestoreCorrelations,
  opsUpdateCorrelation,
  type OpsCorrelation,
  type OpsCorrelationReference,
  type OpsDefaultCode,
} from '../../lib/operations'

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
  'npt-codes': {
    label: 'NPT codes',
    code: 'npt_code',
    name: 'npt_name',
    defaults: { family: 'other', category: 'other' },
  },
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

function DefaultCodes() {
  const [codes, setCodes] = useState<OpsDefaultCode[]>([])
  const [family, setFamily] = useState('')
  const [error, setError] = useState('')
  const [loading, setLoading] = useState(true)
  const { can } = useAuth()
  useEffect(() => {
    let current = true
    defaultOpsCodes()
      .then((rows) => {
        if (current) setCodes(rows)
      })
      .catch((e) => {
        if (current) setError(e.message)
      })
      .finally(() => {
        if (current) setLoading(false)
      })
    return () => {
      current = false
    }
  }, [])
  return (
    <Box mt={1.5}>
      <Alert severity="info" sx={{ mb: 1.5 }}>
        These are the built-in definitions for the supported OpenWells reports and engineering workbooks, not a
        universal OpenWells catalogue. Add workspace-specific codes on the other tabs.
      </Alert>
      {error && <Alert severity="error">{error}</Alert>}
      {loading ? (
        <Typography role="status">Loading default codes…</Typography>
      ) : (
        <>
          <TextField
            select
            label="Code family"
            value={family}
            onChange={(e) => setFamily(e.target.value)}
            sx={{ minWidth: 215, mb: 1.5 }}
          >
            <MenuItem value="">All code families</MenuItem>
            {[...new Set(codes.map((c) => c.family))].map((f) => (
              <MenuItem key={f} value={f}>
                {f}
              </MenuItem>
            ))}
          </TextField>
          <DataTable
            rows={codes.filter((c) => !family || c.family === family)}
            fillHeight
            searchPlaceholder="Search code or meaning…"
            canExport={can('ops-master:export')}
            onExport={auditExport('library')}
            exportName="operations-default-codes"
            columns={[
              { field: 'family', headerName: 'Code family', minWidth: 145 },
              { field: 'code', headerName: 'Code', minWidth: 105 },
              { field: 'name', headerName: 'Meaning', minWidth: 250, flex: 2, tooltipField: 'name' },
              {
                field: 'description',
                headerName: 'How to interpret',
                minWidth: 230,
                flex: 2,
                tooltipField: 'description',
              },
              { field: 'classification', headerName: 'Suggested class' },
              { field: 'allocation', headerName: 'Suggested allocation' },
              { field: 'source', headerName: 'Reference', minWidth: 195 },
            ]}
          />
        </>
      )}
    </Box>
  )
}

const CORRELATION_KINDS = [
  { key: 'operation', label: 'Operation code' },
  { key: 'activity', label: 'Activity code' },
  { key: 'npt', label: 'NPT code' },
  { key: 'cause', label: 'Cause code' },
  { key: 'phase', label: 'Phase (and programme phase)' },
  { key: 'agency', label: 'Agency' },
] as const

/**
 * Correlate the printed default codes with this workspace's own library.
 *
 * Extraction reads a printed token such as 19-D from the source. Without a
 * correlation it leaves the dropdown empty — it never guesses which workspace
 * code the token "probably" means. This tab is where that mapping is decided.
 */
function Correlations() {
  const { can } = useAuth()
  const [ref, setRef] = useState<OpsCorrelationReference | null>(null)
  const [rows, setRows] = useState<OpsCorrelation[]>([])
  const [deleted, setDeleted] = useState(false)
  const [kind, setKind] = useState('')
  const [error, setError] = useState('')
  const [busy, setBusy] = useState(false)
  const [form, setForm] = useState<{
    rowId: string
    kind: string
    source_code: string
    target_id: string
    note: string
  } | null>(null)

  const load = async (showDeleted = deleted) => {
    const [r, c] = await Promise.all([
      opsCorrelationReference(),
      opsCorrelations({ kind: kind || undefined, deleted: showDeleted }),
    ])
    setRef(r)
    setRows(c)
  }
  useEffect(() => {
    let current = true
    setError('')
    Promise.all([
      opsCorrelationReference(),
      opsCorrelations({ kind: kind || undefined, deleted }),
    ])
      .then(([r, c]) => {
        if (current) {
          setRef(r)
          setRows(c)
        }
      })
      .catch((e) => {
        if (current) setError((e as Error).message)
      })
    return () => {
      current = false
    }
  }, [kind, deleted])

  const run = async (fn: () => Promise<unknown>) => {
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

  const save = async () => {
    if (!form) return
    await run(async () => {
      if (form.rowId) {
        await opsUpdateCorrelation(form.rowId, {
          target_id: form.target_id,
          is_active: true,
          note: form.note,
        })
      } else {
        const printed = ref?.printed.find((p) => p.code === form.source_code)
        await opsCreateCorrelation({
          kind: form.kind,
          source_family: printed?.family ?? '',
          source_code: form.source_code,
          source_label: printed?.description ?? '',
          target_id: form.target_id,
          note: form.note,
        })
      }
      setForm(null)
    })
  }

  const libraryFor = (k: string) => ref?.library[k] ?? []

  return (
    <Box mt={1.5}>
      <Alert severity="info" sx={{ mb: 1.5 }}>
        Extraction pre-selects a dropdown only when a correlation exists. No correlation leaves the field empty
        so the engineer chooses from this workspace's own library. Correlating a code never approves a block and
        never changes an already saved report.
      </Alert>
      {error && <Alert severity="error">{error}</Alert>}
      <Box display="flex" gap={1.5} flexWrap="wrap" alignItems="center" mb={1.5}>
        <TextField
          select
          label="Code kind"
          value={kind}
          onChange={(e) => setKind(e.target.value)}
          sx={{ minWidth: 210 }}
        >
          <MenuItem value="">All kinds</MenuItem>
          {CORRELATION_KINDS.map((k) => (
            <MenuItem key={k.key} value={k.key}>
              {k.label}
            </MenuItem>
          ))}
        </TextField>
        <Button variant="outlined" onClick={() => setDeleted(!deleted)}>
          {deleted ? 'Active correlations' : 'Deleted correlations'}
        </Button>
        {!deleted && can('ops-master:correlate') && (
          <Button
            variant="contained"
            startIcon={<AddRounded />}
            onClick={() => {
              setError('')
              setForm({
                rowId: '',
                kind: kind || 'operation',
                source_code: '',
                target_id: '',
                note: '',
              })
            }}
          >
            New correlation
          </Button>
        )}
      </Box>
      <DataTable
        key={`${kind}/${deleted}`}
        rows={rows as unknown as Record<string, unknown>[]}
        fillHeight
        searchPlaceholder="Search printed code, meaning or library code…"
        canExport={can('ops-master:export')}
        onExport={auditExport('library')}
        exportName="operations-correlations"
        columns={[
          { field: 'kind', headerName: 'Kind', minWidth: 110 },
          { field: 'source_family', headerName: 'Printed family', minWidth: 190 },
          { field: 'source_code', headerName: 'Printed code', minWidth: 120 },
          { field: 'source_label', headerName: 'Printed meaning', minWidth: 240, tooltipField: 'source_label' },
          { field: 'target_label', headerName: 'Workspace code', minWidth: 240, tooltipField: 'target_label' },
          { field: 'note', headerName: 'Note', minWidth: 180, tooltipField: 'note' },
          {
            headerName: 'Actions',
            width: 210,
            minWidth: 190,
            sortable: false,
            cellRenderer: ({ data: row }: { data: OpsCorrelation }) => (
              <>
                {!deleted && can('ops-master:correlate') && (
                  <Button
                    size="small"
                    onClick={() =>
                      setForm({
                        rowId: row.id,
                        kind: row.kind,
                        source_code: row.source_code,
                        target_id: row.target_id ?? '',
                        note: row.note,
                      })
                    }
                  >
                    Edit
                  </Button>
                )}
                {can('ops-master:correlate') && (
                  <Button
                    size="small"
                    color={deleted ? 'inherit' : 'error'}
                    disabled={busy}
                    onClick={() =>
                      void run(() =>
                        deleted ? opsRestoreCorrelations([row.id]) : opsDeleteCorrelations([row.id]),
                      )
                    }
                  >
                    {deleted ? 'Restore' : 'Delete'}
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
          title={form.rowId ? 'Edit a correlation' : 'Correlate a printed code'}
          subtitle="The printed left-hand code is read from the source document. The right-hand value is what this workspace wants the dropdown to show."
          onClose={() => setForm(null)}
          onSubmit={() => void save()}
          busy={busy}
          submitDisabled={!form.kind || !form.source_code || !form.target_id}
        >
          <Box display="grid" gap={2} pt={0.5}>
            {error && <Alert severity="error">{error}</Alert>}
            <TextField
              select
              label="Code kind"
              value={form.kind}
              onChange={(e) => setForm({ ...form, kind: e.target.value, target_id: '' })}
              disabled={Boolean(form.rowId)}
            >
              {CORRELATION_KINDS.map((k) => (
                <MenuItem key={k.key} value={k.key}>
                  {k.label}
                </MenuItem>
              ))}
            </TextField>
            <TextField
              select
              label="Printed default code"
              value={form.source_code}
              onChange={(e) => setForm({ ...form, source_code: e.target.value })}
              disabled={Boolean(form.rowId)}
              helperText="Only codes in the built-in reference can be correlated."
            >
              {(ref?.printed ?? [])
                .filter((p) => (form.kind === 'operation' ? p.family === 'OpenWells operation code' || p.family === 'Operation' : true))
                .filter((p) => (form.kind === 'activity' ? p.family === 'Activity' || p.family === 'OpenWells code token' : true))
                .filter((p) => (form.kind === 'npt' ? p.family === 'Trouble / NPT' : true))
                .filter((p) => (form.kind === 'cause' ? ['Cause', 'Trouble / NPT'].includes(p.family) : true))
                .filter((p) => (form.kind === 'phase' ? ['OpenWells phase', 'Programme phase'].includes(p.family) : true))
                .map((p) => (
                  <MenuItem key={`${p.family}/${p.code}`} value={p.code}>
                    {p.code} — {p.description || p.family}
                  </MenuItem>
                ))}
            </TextField>
            <TextField
              select
              label="Workspace code"
              value={form.target_id}
              onChange={(e) => setForm({ ...form, target_id: e.target.value })}
            >
              {libraryFor(form.kind).map((c) => (
                <MenuItem key={c.id} value={c.id}>
                  {c.code} — {c.name}
                </MenuItem>
              ))}
            </TextField>
            <TextField
              label="Note"
              value={form.note}
              onChange={(e) => setForm({ ...form, note: e.target.value })}
              multiline
              minRows={2}
              helperText="Optional. Record why this printed code maps to that workspace code."
            />
          </Box>
        </FormDialog>
      )}
    </Box>
  )
}

export default function OperationsLibrary() {
  const [params, setParams] = useSearchParams()
  const tab = params.get('tab')
  const isCorrelations = tab === 'correlations'
  const isDefault = !isCorrelations && (!tab || !Object.hasOwn(kinds, tab) || tab === 'default-codes')
  const kind: Kind = isDefault ? 'operation-codes' : (tab as Kind)
  const { can } = useAuth(),
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
    if (isDefault || isCorrelations) return
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
  }, [kind, deleted, isDefault, isCorrelations])
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
            {!isDefault && !isCorrelations && !deleted && can('ops-master:create') && (
              <Button variant="contained" startIcon={<AddRounded />} onClick={() => edit()}>
                New code
              </Button>
            )}
            {!isDefault && !isCorrelations && (
              <Button variant="outlined" startIcon={<RestoreRounded />} onClick={() => setDeleted(!deleted)}>
                {deleted ? 'Active entries' : 'Deleted entries'}
              </Button>
            )}
          </>
        }
      />
      <Tabs
        variant="scrollable"
        value={isCorrelations ? 'correlations' : isDefault ? 'default-codes' : kind}
        onChange={(_, v) => setParams({ tab: v })}
      >
        <Tab value="default-codes" label="Default Codes" />
        <Tab value="correlations" label="Correlations" />
        {(Object.keys(kinds) as Kind[]).map((k) => (
          <Tab key={k} value={k} label={kinds[k].label} />
        ))}
      </Tabs>
      {isCorrelations ? (
        <Correlations />
      ) : isDefault ? (
        <DefaultCodes />
      ) : (
        <>
          {kind === 'source-marks' && (
            <Alert severity="info">
              Add a printed source mark to override its suggested classification and allocation. These rules affect
              future drafts, never saved logs.
            </Alert>
          )}
          {error && <Alert severity="error">{error}</Alert>}
          {selected.length > 0 && (
            <Box display="flex" gap={2} alignItems="center" py={1}>
              <Typography>{selected.length} selected</Typography>
              {can(deleted ? 'ops-master:restore' : 'ops-master:delete') && (
                <Button onClick={() => setPending(selected)}>
                  {deleted ? 'Restore selected' : 'Move to Deleted entries'}
                </Button>
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
        </>
      )}
    </Box>
  )
}
