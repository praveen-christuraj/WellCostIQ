import { useEffect, useState } from 'react'
import { AddOutlined } from '@mui/icons-material'
import { Alert, Box, Button, MenuItem, TextField } from '@mui/material'
import { ErrorMessage, FormDialog, PageHeading } from '../../components/Common'
import { DataTable } from '../../components/DataTable'
import { SectionCard } from '../../components/ui/SectionCard'
import { FolderFields, type Folder } from '../../components/operations/ScopeDirectory'
import { TimelineEditor } from '../../components/operations/TimelineEditor'
import { api } from '../../lib/api'
import { useAuth } from '../../context/AuthContext'
import {
  listPlans,
  createPlan,
  activatePlan,
  opsScopeReference,
  auditExport,
  type OpsScopeReference,
  type OpsPlan,
} from '../../lib/operations'

export default function OperationsPlans() {
  const { can } = useAuth(),
    [plans, setPlans] = useState<OpsPlan[]>([]),
    [ref, setRef] = useState<OpsScopeReference | null>(null),
    [error, setError] = useState('')
  const [well, setWell] = useState(''),
    [scope, setScope] = useState(''),
    [create, setCreate] = useState(false),
    [folder, setFolder] = useState<Folder>({ well_id: '', scope: 'drilling' })
  const [label, setLabel] = useState(''),
    [start, setStart] = useState(''),
    [busy, setBusy] = useState(false),
    [formError, setFormError] = useState(''),
    [edit, setEdit] = useState<OpsPlan | null>(null),
    [activate, setActivate] = useState<OpsPlan | null>(null)
  const [deleted, setDeleted] = useState(false),
    [remove, setRemove] = useState<OpsPlan | null>(null),
    [rig, setRig] = useState('')
  const load = async () => {
    setPlans(await listPlans(undefined, undefined, deleted))
  }
  useEffect(() => {
    opsScopeReference()
      .then(setRef)
      .catch((e) => setError(e.message))
  }, [])
  useEffect(() => {
    let current = true
    setPlans([])
    listPlans(undefined, undefined, deleted)
      .then((ps) => {
        if (current) setPlans(ps)
      })
      .catch((e) => {
        if (current) setError(e.message)
      })
    return () => {
      current = false
    }
  }, [deleted])
  const save = async () => {
    setBusy(true)
    setFormError('')
    try {
      const plan = await createPlan({
        ...folder,
        label,
        planned_start_at: start ? new Date(`${start}Z`).toISOString() : null,
      })
      setWell(folder.well_id)
      setScope(folder.scope)
      await load()
      setCreate(false)
      if (can('ops-plan:update')) setEdit(plan)
    } catch (e) {
      setFormError((e as Error).message)
    } finally {
      setBusy(false)
    }
  }
  return (
    <Box>
      <PageHeading
        eyebrow="Well Operations"
        title="Plans & timeline"
        subtitle="Set a programme for each well and scope. Operations planned days are the sum of reviewed activity hours divided by 24, independent of Well Configuration and costing."
        action={
          <>
            <Button variant="outlined" onClick={() => setDeleted(!deleted)}>
              {deleted ? 'Active versions' : 'Deleted versions'}
            </Button>
            {!deleted && can('ops-plan:create') && (
              <Button
                variant="contained"
                startIcon={<AddOutlined />}
                onClick={() => {
                  const w = ref?.wells.find((w) => w.id === well)
                  setFolder({ well_id: well, scope: w && !w.drilling_available ? 'completion' : 'drilling' })
                  setLabel('')
                  setStart('')
                  setFormError('')
                  setCreate(true)
                }}
              >
                New plan version
              </Button>
            )}
          </>
        }
      />
      {error && <ErrorMessage message={error} />}
      <Box display="flex" gap={2} flexWrap="wrap" mb={2}>
        <TextField
          select
          label="Rig"
          sx={{ minWidth: 150 }}
          value={rig}
          onChange={(e) => {
            setRig(e.target.value)
            setWell('')
          }}
        >
          <MenuItem value="">All rigs</MenuItem>
          {ref?.rigs.map((r) => (
            <MenuItem key={r.id} value={r.id}>
              {r.rig_code}
            </MenuItem>
          ))}
        </TextField>
        <TextField select label="Well" value={well} onChange={(e) => setWell(e.target.value)} sx={{ minWidth: 200 }}>
          <MenuItem value="">All wells</MenuItem>
          {ref?.wells
            .filter((w) => !rig || w.rig_id === rig)
            .map((w) => (
              <MenuItem key={w.id} value={w.id}>
                {w.display_name}
              </MenuItem>
            ))}
        </TextField>
        <TextField select label="Scope" value={scope} onChange={(e) => setScope(e.target.value)} sx={{ minWidth: 150 }}>
          <MenuItem value="">All scopes</MenuItem>
          <MenuItem value="drilling">Drilling</MenuItem>
          <MenuItem value="completion">Completion</MenuItem>
        </TextField>
      </Box>
      {plans
        .filter(
          (p) =>
            (!rig || ref?.wells.some((w) => w.id === p.well_id && w.rig_id === rig)) &&
            (!well || p.well_id === well) &&
            (!scope || p.scope === scope),
        )
        .map((p) => (
          <SectionCard
            key={p.id}
            title={`${p.well_code} · ${p.scope} · ${p.label}`}
            subtitle={`Version ${p.version_no} · ${p.status} · ${Number(p.planned_days ?? 0).toFixed(3)} planned days`}
            action={
              <Box display="flex" gap={1} flexWrap="wrap">
                {!deleted && p.status === 'draft' && can('ops-plan:update') && (
                  <Button onClick={() => setEdit(p)}>Edit timeline</Button>
                )}
                {((!deleted && p.status === 'draft' && can('ops-plan:delete')) || (deleted && can('ops-plan:restore'))) && (
                  <Button
                    color={deleted ? 'inherit' : 'error'}
                    onClick={() => {
                      setFormError('')
                      setRemove(p)
                    }}
                  >
                    {deleted ? 'Restore' : 'Delete'}
                  </Button>
                )}
                {!deleted && p.status === 'draft' && can('ops-plan:activate') && (
                  <Button
                    variant="outlined"
                    disabled={!Number(p.planned_days)}
                    onClick={() => {
                      setFormError('')
                      setActivate(p)
                    }}
                  >
                    Activate
                  </Button>
                )}
              </Box>
            }
          >
            <DataTable
              rows={p.items}
              exportName={`${p.well_code}-${p.scope}-timeline-v${p.version_no}`}
              canExport={can('ops-plan:export')}
              onExport={auditExport('plans')}
              onImport={
                !deleted && p.status === 'draft' && can('ops-plan:update') && can('ops-plan:import')
                  ? () => setEdit(p)
                  : undefined
              }
              columns={[
                { field: 'sequence_no', headerName: 'Sequence' },
                { field: 'description', headerName: 'Activity', minWidth: 260, flex: 3 },
                { field: 'target_depth_m', headerName: 'Target depth (m)' },
                { field: 'planned_hours', headerName: 'Planned hours' },
                {
                  field: 'cum_planned_days',
                  headerName: 'Cumulative days',
                  valueFormatter: (p) => Number(p.value).toFixed(3),
                },
              ]}
            />
          </SectionCard>
        ))}
      {!plans.length && (
        <Alert severity="info">Create a draft version to import the programme workbook or enter activities manually.</Alert>
      )}
      <FormDialog
        open={create}
        title="New operations plan"
        submitLabel="Create draft"
        onClose={() => setCreate(false)}
        onSubmit={save}
        busy={busy}
        submitDisabled={!folder.well_id || !label.trim()}
        maxWidth="sm"
      >
        <Box display="grid" gap={2} pt={1}>
          <FolderFields folder={folder} change={setFolder} reference={ref} />
          <TextField required label="Programme label" value={label} onChange={(e) => setLabel(e.target.value)} />
          <TextField
            type="datetime-local"
            label="Programme start (UTC)"
            slotProps={{ inputLabel: { shrink: true } }}
            value={start}
            onChange={(e) => setStart(e.target.value)}
            helperText="Day zero for schedule variance. Without a start, drilling uses reported days from spud; completion cannot calculate lag."
          />
          {formError && <Alert severity="error">{formError}</Alert>}
        </Box>
      </FormDialog>
      {edit && <TimelineEditor plan={edit} onClose={() => setEdit(null)} onSaved={load} />}
      {remove && (
        <FormDialog
          open
          title={`${deleted ? 'Restore' : 'Delete'} ${remove.label}?`}
          danger={!deleted}
          onClose={() => setRemove(null)}
          submitLabel={deleted ? 'Restore' : 'Delete'}
          busy={busy}
          onSubmit={async () => {
            setBusy(true)
            try {
              await api(`/operations/plans/${remove.id}${deleted ? '/restore' : ''}`, { method: deleted ? 'POST' : 'DELETE' })
              await load()
              setRemove(null)
            } catch (e) {
              setFormError((e as Error).message)
            } finally {
              setBusy(false)
            }
          }}
        >
          {deleted ? 'Restore this version as a draft.' : 'This draft and its items can be restored from Deleted versions.'}
          {formError && <Alert severity="error">{formError}</Alert>}
        </FormDialog>
      )}
      {activate && (
        <FormDialog
          open
          title={`Activate ${activate.label}?`}
          subtitle="This makes the reviewed timeline the baseline for extraction and analytics. Any previously active version for this well scope is retained as superseded."
          onClose={() => setActivate(null)}
          onSubmit={async () => {
            setBusy(true)
            try {
              await activatePlan(activate.id)
              await load()
              setActivate(null)
            } catch (e) {
              setFormError((e as Error).message)
            } finally {
              setBusy(false)
            }
          }}
          busy={busy}
          submitLabel="Activate"
        >
          {formError && <Alert severity="error">{formError}</Alert>}
        </FormDialog>
      )}
    </Box>
  )
}
