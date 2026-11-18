import { useState } from 'react'
import { AddOutlined } from '@mui/icons-material'
import { Alert, Box, Button, TextField, Typography } from '@mui/material'
import { Link as RouterLink } from 'react-router-dom'
import { ErrorMessage, FormDialog, PageHeading, PanelDialog, Tag } from '../../components/Common'
import { DataTable } from '../../components/DataTable'
import {
  FolderFields,
  ScopeDirectory,
  useOperationsRegister,
  type Folder,
} from '../../components/operations/ScopeDirectory'
import { StudyPanel } from '../../components/operations/StudyPanel'
import { TimelineEditor } from '../../components/operations/TimelineEditor'
import { api } from '../../lib/api'
import { useAuth } from '../../context/AuthContext'
import { createPlan, activatePlan, auditExport, getOpsPlan, studyTimeline, type OpsPlan } from '../../lib/operations'

export default function OperationsPlans() {
  const { can } = useAuth()
  const register = useOperationsRegister('plans')
  const { reference, deleted, rows, refresh, location } = register
  const [create, setCreate] = useState(false)
  const [folder, setFolder] = useState<Folder>({ well_id: '', scope: 'drilling' })
  const [label, setLabel] = useState(''),
    [start, setStart] = useState('')
  const [busy, setBusy] = useState(false),
    [error, setError] = useState('')
  const [formError, setFormError] = useState('')
  const [editor, setEditor] = useState<{ plan: OpsPlan; edit: boolean } | null>(null)
  const [action, setAction] = useState<{ plan: OpsPlan; kind: 'activate' | 'delete' | 'restore' } | null>(null)
  const save = async () => {
    setBusy(true)
    setFormError('')
    try {
      const plan = await createPlan({
        ...folder,
        label: label.trim(),
        planned_start_at: start ? new Date(`${start}Z`).toISOString() : null,
      })
      setCreate(false)
      register.change(register.formLocation(folder))
      await refresh()
      if (can('ops-plan:update')) setEditor({ plan, edit: true })
    } catch (e) {
      setFormError((e as Error).message)
    } finally {
      setBusy(false)
    }
  }
  const open = async (id: string, edit: boolean) => {
    setBusy(true)
    setError('')
    try {
      setEditor({ plan: await getOpsPlan(id), edit })
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
        title={deleted ? 'Deleted plan versions' : 'Plans & timeline'}
        subtitle="Browse by rig and well, then open a version to view its programme. Operations planned days are independent of costing."
        action={
          <>
            <Button component={RouterLink} to="/operations/guide">
              Ask &amp; guide
            </Button>
            <Button variant="outlined" disabled={busy} onClick={() => register.change({ rig: '' }, !deleted)}>
              {deleted ? 'Active versions' : 'Deleted versions'}
            </Button>
            {!deleted && can('ops-plan:create') && (
              <Button
                variant="contained"
                startIcon={<AddOutlined />}
                disabled={!reference || busy || register.loading}
                onClick={() => {
                  setFolder(register.destination() ?? { well_id: '', scope: 'drilling' })
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
      {(register.error || error) && <ErrorMessage message={register.error || error} />}
      <ScopeDirectory {...register} resource="plans" />
      {location.well &&
        (register.loading ? (
          <Typography role="status">Loading plan versions…</Typography>
        ) : (
          <DataTable
            key={JSON.stringify(location)}
            rows={rows}
            fillHeight
            exportName="operations-plan-versions"
            canExport={can('ops-plan:export')}
            onExport={auditExport('plans')}
            searchPlaceholder="Search plan versions…"
            columns={[
              { field: 'label', headerName: 'Programme', minWidth: 225, flex: 2 },
              { field: 'scope', headerName: 'Scope' },
              { field: 'version_no', headerName: 'Version' },
              {
                field: 'status',
                headerName: 'Status',
                cellRenderer: ({ value }: { value: string }) => <Tag>{value}</Tag>,
              },
              { field: 'planned_days', headerName: 'Planned days' },
              { field: 'planned_start_at', headerName: 'Start (UTC)' },
              {
                headerName: 'Actions',
                width: 315,
                sortable: false,
                cellRenderer: ({ data: p }: { data: OpsPlan }) => (
                  <>
                    <Button size="small" disabled={busy} onClick={() => void open(p.id, false)}>
                      View timeline
                    </Button>
                    {!deleted && p.status === 'draft' && can('ops-plan:update') && (
                      <Button size="small" disabled={busy} onClick={() => void open(p.id, true)}>
                        Edit
                      </Button>
                    )}
                    {((deleted && can('ops-plan:restore')) ||
                      (!deleted && p.status === 'draft' && can('ops-plan:delete'))) && (
                      <Button
                        size="small"
                        color={deleted ? 'inherit' : 'error'}
                        disabled={busy}
                        onClick={() => {
                          setFormError('')
                          setAction({ plan: p, kind: deleted ? 'restore' : 'delete' })
                        }}
                      >
                        {deleted ? 'Restore' : 'Delete'}
                      </Button>
                    )}
                    {!deleted && p.status === 'draft' && can('ops-plan:activate') && (
                      <Button
                        size="small"
                        disabled={busy || !Number(p.planned_days)}
                        onClick={() => {
                          setFormError('')
                          setAction({ plan: p, kind: 'activate' })
                        }}
                      >
                        Activate
                      </Button>
                    )}
                  </>
                ),
              },
            ]}
          />
        ))}
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
          <FolderFields folder={folder} change={setFolder} reference={reference} />
          <TextField required label="Programme label" value={label} onChange={(e) => setLabel(e.target.value)} />
          <TextField
            type="datetime-local"
            label="Programme start (UTC)"
            slotProps={{ inputLabel: { shrink: true } }}
            value={start}
            onChange={(e) => setStart(e.target.value)}
            helperText="Without a start, drilling needs reported days from spud. Completion needs a start for lead/lag."
          />
          {formError && <Alert severity="error">{formError}</Alert>}
        </Box>
      </FormDialog>
      {editor &&
        (editor.edit && !editor.plan.is_deleted && editor.plan.status === 'draft' ? (
          <TimelineEditor plan={editor.plan} onClose={() => setEditor(null)} onSaved={refresh} />
        ) : (
          <PlanView plan={editor.plan} onClose={() => setEditor(null)} />
        ))}
      {action && (
        <FormDialog
          open
          title={`${action.kind[0].toUpperCase()}${action.kind.slice(1)} ${action.plan.label}?`}
          danger={action.kind === 'delete'}
          busy={busy}
          onClose={() => setAction(null)}
          submitLabel={action.kind[0].toUpperCase() + action.kind.slice(1)}
          onSubmit={async () => {
            setBusy(true)
            setFormError('')
            try {
              if (action.kind === 'activate') await activatePlan(action.plan.id)
              else
                await api(`/operations/plans/${action.plan.id}${action.kind === 'restore' ? '/restore' : ''}`, {
                  method: action.kind === 'restore' ? 'POST' : 'DELETE',
                })
              setAction(null)
              await refresh()
            } catch (e) {
              setFormError((e as Error).message)
            } finally {
              setBusy(false)
            }
          }}
        >
          {action.kind === 'activate'
            ? 'This becomes the baseline for this well and scope. The previous version is retained as superseded.'
            : action.kind === 'restore'
              ? 'Restore this version as a draft.'
              : 'This draft and its items can be restored from Deleted versions.'}
          {formError && <Alert severity="error">{formError}</Alert>}
        </FormDialog>
      )}
    </Box>
  )
}

function PlanView({ plan, onClose }: { plan: OpsPlan; onClose: () => void }) {
  const { can } = useAuth()
  return (
    <PanelDialog
      open
      title={`Timeline · ${plan.label}`}
      maxWidth={false}
      onClose={onClose}
      subtitle={`${plan.well_code} · ${plan.scope} · Version ${plan.version_no} · ${plan.status}`}
    >
      <DataTable
        rows={plan.items}
        exportName={`${plan.well_code}-${plan.scope}-timeline-v${plan.version_no}`}
        canExport={can('ops-plan:export')}
        onExport={auditExport('plans')}
        columns={[
          { field: 'sequence_no', headerName: 'Sequence' },
          { field: 'description', headerName: 'Activity', minWidth: 250, flex: 3, tooltipField: 'description' },
          { field: 'target_depth_m', headerName: 'Target MD (m)' },
          { field: 'planned_hours', headerName: 'Planned hours' },
          { field: 'cum_planned_days', headerName: 'Cumulative days' },
        ]}
      />
      <Box mt={2}>
        <Typography variant="h6">Timeline study</Typography>
        <StudyPanel runLabel="Study saved timeline" run={(useAi) => studyTimeline(plan.id, useAi)} />
      </Box>
    </PanelDialog>
  )
}
