import { useEffect, useMemo, useState } from 'react'
import { useSearchParams } from 'react-router-dom'
import { Alert, Box, Button, Chip, MenuItem, Tab, Tabs, TextField, Typography } from '@mui/material'
import { AddRounded, DeleteForeverOutlined, DeleteOutlineRounded, RestoreRounded } from '@mui/icons-material'
import { FormDialog, PageHeading } from '../../components/Common'
import { CorrelationsPanel } from '../../components/operations/CorrelationsPanel'
import { DataTable } from '../../components/DataTable'
import { ImportDialog } from '../../components/ImportDialog'
import { useAuth } from '../../context/AuthContext'
import { api, body } from '../../lib/api'
import {
  auditExport,
  defaultOpsCodes,
  type OpsDefaultCode,
} from '../../lib/operations'
import { CORRELATION_KIND_FOR_MASTER } from '../../components/operations/codeCriteria'

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
  agencies: { label: 'Agency codes', code: 'agency_code', name: 'agency_name', defaults: { category: 'other' } },
  'source-marks': {
    label: 'Source mark rules',
    code: 'mark_code',
    name: 'mark_name',
    defaults: { default_classification: 'Planned', default_allocation: 'PT' },
  },
} as const
type Kind = keyof typeof kinds
type Row = { id: string; is_deleted: boolean; correlation_count?: number } & Record<string, unknown>

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

const TAB_VALUES = ['default-codes', 'correlations', ...Object.keys(kinds)] as const
type TabValue = (typeof TAB_VALUES)[number]

export default function OperationsLibrary() {
  const [params, setParams] = useSearchParams()
  const requested = params.get('tab') ?? ''
  const tab: TabValue = (TAB_VALUES as readonly string[]).includes(requested) ? (requested as TabValue) : 'default-codes'
  const isCorrelations = tab === 'correlations'
  const isDefault = tab === 'default-codes'
  const kind = tab as Kind
  const focusKind = params.get('kind') ?? ''
  const focusCode = params.get('code') ?? ''
  const { can } = useAuth(),
    [deleted, setDeleted] = useState(false),
    [rows, setRows] = useState<Row[]>([]),
    [selected, setSelected] = useState<Row[]>([]),
    [rules, setRules] = useState<Row[]>([])
  const [form, setForm] = useState<Record<string, string> | null>(null),
    [id, setId] = useState(''),
    [pending, setPending] = useState<{ rows: Row[]; action: 'delete' | 'restore' | 'permanent-delete' } | null>(null),
    [importing, setImporting] = useState(false),
    [error, setError] = useState(''),
    [notice, setNotice] = useState(''),
    [busy, setBusy] = useState(false)
  const spec = kinds[kind],
    path = `/operations/masters/${kind}`

  const getRows = () =>
    api<Row[]>(path + (deleted ? '?include_deleted=true' : '')).then((rs) => rs.filter((r) => r.is_deleted === deleted))

  useEffect(() => {
    let current = true
    setRows([])
    setSelected([])
    setRules([])
    setError('')
    setNotice('')
    setPending(null)
    if (isDefault || isCorrelations) return
    getRows()
      .then((rs) => {
        if (!current) return
        setRows(rs)
        const withRules = rs.filter((r) => (r.correlation_count ?? 0) > 0)
        if (withRules.length) {
          setRules(withRules)
        }
      })
      .catch((e) => {
        if (current) setError((e as Error).message)
      })
    return () => {
      current = false
    }
  }, [kind, deleted, isDefault, isCorrelations])

  const load = async () => {
    setRows(await getRows())
    setSelected([])
  }

  const edit = (row?: Row) => {
    const defaults = { [spec.code]: '', [spec.name]: '', ...spec.defaults, description: '' }
    setId(row?.id ?? '')
    setForm(Object.fromEntries(Object.entries(defaults).map(([k, v]) => [k, String(row?.[k] ?? v)])))
    setError('')
  }

  const run = async (fn: () => Promise<void>, message = '') => {
    setBusy(true)
    setError('')
    try {
      await fn()
      await load()
      if (message) setNotice(message)
    } catch (e) {
      setError((e as Error).message)
    } finally {
      setBusy(false)
    }
  }

  const runPending = async () => {
    if (!pending) return
    const suffix = pending.action === 'permanent-delete' ? 'permanent-delete' : pending.action
    await run(async () => {
      await api(`${path}/bulk-${suffix}`, {
        method: 'POST',
        body: body({ ids: pending.rows.map((r) => r.id) }),
      })
      setPending(null)
    })
  }

  /** Deep link a code into the Correlations tab, filtered to the rules that reference it. */
  const openRules = (row: Row) =>
    setParams({ tab: 'correlations', kind: CORRELATION_KIND_FOR_MASTER[kind] ?? '', code: row.id })

  const linkedCount = (row: Row) => Number(row.correlation_count ?? 0)
  const activeSelection = useMemo(() => selected.filter((r) => linkedCount(r) === 0), [selected])

  return (
    <Box>
      <PageHeading
        eyebrow="Well Operations"
        title="Code library"
        subtitle="Define this workspace’s phase, operation, activity, NPT, cause, agency and source-mark codes. Codes are displayed alongside their names. Responsible parties for new NPT / UPA entries come from active Master Data vendors."
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
        value={tab}
        onChange={(_, v: TabValue) => setParams(v === 'default-codes' ? {} : { tab: v })}
        aria-label="Code library tabs"
      >
        <Tab value="default-codes" label="Default Codes" />
        <Tab value="correlations" label="Correlations" />
        {(Object.keys(kinds) as Kind[]).map((k) => (
          <Tab key={k} value={k} label={kinds[k].label} />
        ))}
      </Tabs>
      {isCorrelations ? (
        <CorrelationsPanel
          focusKind={focusKind}
          focusCode={focusCode}
          onClearFocus={() => setParams({ tab: 'correlations' })}
        />
      ) : isDefault ? (
        <DefaultCodes />
      ) : (
        <Box mt={1.5}>
          {error && <Alert severity="error" sx={{ mb: 1.5 }}>{error}</Alert>}
          {notice && <Alert severity="success" sx={{ mb: 1.5 }} onClose={() => setNotice('')}>{notice}</Alert>}
          {deleted && (
            <Alert severity="info" sx={{ mb: 1.5 }}>
              Restore brings a code back into the active library. Delete permanently is offered only here and only for a
              code no rule, report block or programme item still references.
            </Alert>
          )}
          {kind === 'source-marks' && (
            <Alert severity="info" sx={{ mb: 1.5 }}>
              Add a printed source mark to override its suggested classification and allocation. These rules affect
              future drafts, never saved logs.
            </Alert>
          )}
          {selected.length > 0 && (
            <Box display="flex" gap={1.5} alignItems="center" py={1} flexWrap="wrap">
              <Typography fontWeight={700}>{selected.length} selected</Typography>
              {!deleted && can('ops-master:delete') && (
                <Button
                  color="error"
                  disabled={activeSelection.length === 0}
                  onClick={() => setPending({ rows: selected, action: 'delete' })}
                >
                  Move to Deleted entries
                </Button>
              )}
              {deleted && can('ops-master:restore') && (
                <Button onClick={() => setPending({ rows: selected, action: 'restore' })}>Restore selected</Button>
              )}
              {deleted && can('ops-master:permanent-delete') && (
                <Button color="error" startIcon={<DeleteForeverOutlined />} onClick={() => setPending({ rows: selected, action: 'permanent-delete' })}>
                  Delete selected permanently
                </Button>
              )}
              {!deleted && activeSelection.length < selected.length && (
                <Typography fontSize={12} color="text.secondary">
                  {selected.length - activeSelection.length} selected code
                  {selected.length - activeSelection.length === 1 ? ' is' : 's are'} referenced by a rule and
                  cannot be deleted until it is unlinked.
                </Typography>
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
                field: 'correlation_count',
                headerName: 'Rules',
                width: 140,
                minWidth: 130,
                cellRenderer: ({ data: r }: { data: Row }) => {
                  const count = linkedCount(r)
                  if (!count) return <Chip size="small" variant="outlined" label="Unlinked" sx={{ height: 20, fontSize: 10.5 }} />
                  return (
                    <Button
                      size="small"
                      aria-label={`Show the ${count} rule${count === 1 ? '' : 's'} linked to ${String(r[spec.code])}`}
                      onClick={() => openRules(r)}
                      sx={{ minWidth: 0, fontSize: 11.5, px: 1 }}
                    >
                      <Chip size="small" color="primary" variant="outlined" label={`${count} rule${count === 1 ? '' : 's'}`} sx={{ height: 20, fontSize: 10.5, cursor: 'pointer' }} />
                    </Button>
                  )
                },
              },
              {
                headerName: 'Actions',
                width: 210,
                minWidth: 200,
                sortable: false,
                cellRenderer: ({ data: r }: { data: Row }) => (
                  <>
                    {!deleted && can('ops-master:update') && (
                      <Button size="small" onClick={() => edit(r)}>
                        Edit
                      </Button>
                    )}
                    {!deleted && linkedCount(r) > 0 && (
                      <Button size="small" onClick={() => openRules(r)}>
                        View rules
                      </Button>
                    )}
                    {can(deleted ? 'ops-master:restore' : 'ops-master:delete') && (
                      <Button
                        size="small"
                        aria-label={deleted ? 'Restore' : `Delete ${String(r[spec.code])}`}
                        color={deleted ? 'inherit' : 'error'}
                        onClick={() => setPending({ rows: [r], action: deleted ? 'restore' : 'delete' })}
                      >
                        {deleted ? <RestoreRounded /> : <DeleteOutlineRounded />}
                      </Button>
                    )}
                    {deleted && can('ops-master:permanent-delete') && (
                      <Button
                        size="small"
                        color="error"
                        aria-label={`Delete ${String(r[spec.code])} permanently`}
                        onClick={() => setPending({ rows: [r], action: 'permanent-delete' })}
                      >
                        Delete permanently
                      </Button>
                    )}
                  </>
                ),
              },
            ]}
          />
          {rows.length === 0 && (
            <Typography fontSize={12.5} color="text.secondary" mt={1}>
              {deleted
                ? 'No codes are in Deleted entries. A code moved here can be restored or deleted permanently.'
                : `No ${spec.label.toLowerCase()} yet. Add one, or import a list.`}
            </Typography>
          )}
          {rules.length > 0 && !deleted && (
            <Typography fontSize={12} color="text.secondary" mt={1}>
              {rules.length} code{rules.length === 1 ? ' is' : 's are'} referenced by a correlation or code link.
              Managing those rules happens in <strong>Correlations</strong>.
            </Typography>
          )}
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
          {pending && (
            <FormDialog
              open
              danger={pending.action !== 'restore'}
              title={
                pending.action === 'delete'
                  ? `Move ${pending.rows.length} code${pending.rows.length === 1 ? '' : 's'} to Deleted entries?`
                  : pending.action === 'restore'
                    ? `Restore ${pending.rows.length} code${pending.rows.length === 1 ? '' : 's'}?`
                    : `Delete ${pending.rows.length} code${pending.rows.length === 1 ? '' : 's'} permanently?`
              }
              onClose={() => setPending(null)}
              submitLabel={
                pending.action === 'delete'
                  ? 'Move to Deleted entries'
                  : pending.action === 'restore'
                    ? 'Restore'
                    : 'Delete permanently'
              }
              busy={busy}
              onSubmit={() => void runPending()}
            >
              <Box display="grid" gap={2} pt={0.5}>
                {error && <Alert severity="error">{error}</Alert>}
                <Typography fontSize={13} color="text.secondary">
                  {pending.action === 'delete' &&
                    'Historical reports retain their recorded values. A code referenced by an active correlation or code link is refused until that rule is removed.'}
                  {pending.action === 'restore' && 'The code becomes available again in every dropdown that uses it.'}
                  {pending.action === 'permanent-delete' &&
                    'A permanent delete cannot be undone and is refused while any report block, programme item or rule still references the code.'}
                </Typography>
                {pending.action === 'permanent-delete' && (
                  <Alert severity="warning" icon={false}>
                    This removes the code from the library for good. Restore it instead if any historical record may need
                    to name it.
                  </Alert>
                )}
              </Box>
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
      )}
    </Box>
  )
}
