import { useState } from 'react'
import { AddOutlined, LockOpenOutlined } from '@mui/icons-material'
import { Alert, Box, Button, Stack, TextField, Typography } from '@mui/material'
import { Link as RouterLink } from 'react-router-dom'
import { ErrorMessage, FormDialog, PageHeading, PanelDialog, Tag, type Tone } from '../../components/Common'
import { DataTable } from '../../components/DataTable'
import {
  FolderFields,
  ScopeDirectory,
  useOperationsRegister,
  type Folder,
} from '../../components/operations/ScopeDirectory'
import { StudyPanel } from '../../components/operations/StudyPanel'
import { TimelineEditor } from '../../components/operations/TimelineEditor'
import { useAuth } from '../../context/AuthContext'
import { api } from '../../lib/api'
import {
  activatePlan,
  auditExport,
  createPlan,
  getOpsPlan,
  reopenPlan,
  studyTimeline,
  updatePlan,
  type OpsPlan,
} from '../../lib/operations'
import {
  formatWatDateTime,
  formatWatShort,
  fromWatDateTimeInput,
  toWatDateTimeInput,
  WAT_LABEL,
} from '../../lib/time'

const planStatusTone = (status: string): Tone => {
  if (status === 'active') return 'success'
  if (status === 'draft') return 'warning'
  return 'neutral'
}

export default function OperationsPlans() {
  const { can } = useAuth()
  const register = useOperationsRegister('plans')
  const { reference, deleted, rows, refresh, location } = register
  const [create, setCreate] = useState(false)
  const [folder, setFolder] = useState<Folder>({ well_id: '', scope: 'drilling' })
  const [label, setLabel] = useState('')
  const [start, setStart] = useState('')
  const [notes, setNotes] = useState('')
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')
  const [notice, setNotice] = useState('')
  const [formError, setFormError] = useState('')
  const [editor, setEditor] = useState<{ plan: OpsPlan; edit: boolean } | null>(null)
  const [metaEdit, setMetaEdit] = useState<OpsPlan | null>(null)
  const [reopenTarget, setReopenTarget] = useState<OpsPlan | null>(null)
  const [reopenRemarks, setReopenRemarks] = useState('')
  const [action, setAction] = useState<{
    plan: OpsPlan
    kind: 'activate' | 'delete' | 'restore' | 'permanent-delete'
  } | null>(null)

  const save = async () => {
    setBusy(true)
    setFormError('')
    setNotice('')
    try {
      const plan = await createPlan({
        ...folder,
        label: label.trim(),
        planned_start_at: fromWatDateTimeInput(start),
        notes: notes.trim(),
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

  const saveMetadata = async () => {
    if (!metaEdit) return
    setBusy(true)
    setFormError('')
    setNotice('')
    try {
      await updatePlan(metaEdit.id, {
        label: label.trim(),
        planned_start_at: fromWatDateTimeInput(start),
        notes: notes.trim(),
      })
      setMetaEdit(null)
      await refresh()
      setNotice('Draft plan details updated.')
    } catch (e) {
      setFormError((e as Error).message)
    } finally {
      setBusy(false)
    }
  }

  const confirmReopen = async () => {
    if (!reopenTarget) return
    setBusy(true)
    setFormError('')
    setNotice('')
    try {
      const updated = await reopenPlan(reopenTarget.id, reopenRemarks.trim())
      setReopenTarget(null)
      setReopenRemarks('')
      await refresh()
      setNotice(`Timeline "${updated.label}" (v${updated.version_no}) reopened to draft. Update items or details, then re-activate when ready.`)
      if (can('ops-plan:update')) setEditor({ plan: updated, edit: true })
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

  const openMetaDialog = (p: OpsPlan) => {
    setLabel(p.label)
    setStart(toWatDateTimeInput(p.planned_start_at))
    setNotes(p.notes || '')
    setFormError('')
    setMetaEdit(p)
  }

  const openReopenDialog = (p: OpsPlan) => {
    setEditor(null)
    setReopenRemarks('')
    setFormError('')
    setReopenTarget(p)
  }

  return (
    <Box>
      <PageHeading
        eyebrow="Well Operations"
        title={deleted ? 'Deleted plan versions' : 'Plans & timeline'}
        subtitle={`Browse by rig and well, then open a version to view, edit or reopen its programme. Start timestamps use ${WAT_LABEL}; operations planned days are independent of costing.`}
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
                  setNotes('')
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
      {notice && (
        <Alert severity="success" onClose={() => setNotice('')} sx={{ mb: 2 }}>
          {notice}
        </Alert>
      )}
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
              { field: 'label', headerName: 'Programme', minWidth: 220, flex: 2 },
              { field: 'scope', headerName: 'Scope', minWidth: 105 },
              { field: 'version_no', headerName: 'Version', minWidth: 92 },
              {
                field: 'status',
                headerName: 'Status',
                minWidth: 165,
                cellRenderer: ({ data: p }: { data: OpsPlan }) => (
                  <Stack direction="row" gap={0.5} alignItems="center">
                    <Tag tone={planStatusTone(p.status)}>{p.status}</Tag>
                    {p.status === 'draft' && p.reopened_at && <Tag tone="info">Reopened</Tag>}
                  </Stack>
                ),
              },
              { field: 'planned_days', headerName: 'Planned days', minWidth: 120 },
              {
                field: 'planned_start_at',
                headerName: 'Start (WAT)',
                minWidth: 155,
                valueFormatter: (p) => (p.value ? formatWatShort(String(p.value)) : '—'),
              },
              {
                headerName: 'Actions',
                width: 390,
                sortable: false,
                cellRenderer: ({ data: p }: { data: OpsPlan }) => (
                  <>
                    <Button size="small" disabled={busy} onClick={() => void open(p.id, false)}>
                      View timeline
                    </Button>
                    {!deleted && p.status === 'draft' && can('ops-plan:update') && (
                      <>
                        <Button size="small" disabled={busy} onClick={() => void open(p.id, true)}>
                          Edit
                        </Button>
                        <Button size="small" disabled={busy} onClick={() => openMetaDialog(p)}>
                          Details
                        </Button>
                      </>
                    )}
                    {!deleted && (p.status === 'active' || p.status === 'superseded') && can('ops-plan:reopen') && (
                      <Button
                        size="small"
                        color="warning"
                        disabled={busy}
                        onClick={() => openReopenDialog(p)}
                      >
                        Reopen
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
                    {deleted && can('ops-plan:permanent-delete') && (
                      <Button
                        size="small"
                        color="error"
                        disabled={busy}
                        onClick={() => {
                          setFormError('')
                          setAction({ plan: p, kind: 'permanent-delete' })
                        }}
                      >
                        Delete permanently
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
            label={`Programme start (${WAT_LABEL})`}
            slotProps={{ inputLabel: { shrink: true } }}
            value={start}
            onChange={(e) => setStart(e.target.value)}
            helperText="Entered in West Africa Time (UTC+1:00). Without a start, drilling uses reported DFS; completion requires a start for lead/lag."
          />
          <TextField
            label="Programme notes"
            multiline
            minRows={2}
            value={notes}
            onChange={(e) => setNotes(e.target.value)}
          />
          {formError && <Alert severity="error">{formError}</Alert>}
        </Box>
      </FormDialog>

      <FormDialog
        open={!!metaEdit}
        title={`Edit plan details · ${metaEdit?.label ?? ''}`}
        subtitle={`Update label, planned start (${WAT_LABEL}) or notes for this draft version.`}
        submitLabel="Save details"
        onClose={() => setMetaEdit(null)}
        onSubmit={saveMetadata}
        busy={busy}
        submitDisabled={!label.trim()}
        maxWidth="sm"
      >
        <Box display="grid" gap={2} pt={1}>
          <TextField required label="Programme label" value={label} onChange={(e) => setLabel(e.target.value)} />
          <TextField
            type="datetime-local"
            label={`Programme start (${WAT_LABEL})`}
            slotProps={{ inputLabel: { shrink: true } }}
            value={start}
            onChange={(e) => setStart(e.target.value)}
            helperText="West Africa Time (Africa/Lagos, UTC+1:00)."
          />
          <TextField
            label="Programme notes"
            multiline
            minRows={3}
            value={notes}
            onChange={(e) => setNotes(e.target.value)}
          />
          {formError && <Alert severity="error">{formError}</Alert>}
        </Box>
      </FormDialog>

      <FormDialog
        open={!!reopenTarget}
        title={`Reopen ${reopenTarget?.label ?? 'timeline'} (v${reopenTarget?.version_no ?? ''})?`}
        subtitle="Returns this timeline version to editable draft so you can revise activities, target depths, planned hours or start time, then re-activate it. Previously reviewed daily reports retain their historical baseline reference, and this reopen action is permanently recorded in the Audit Log."
        submitLabel="Reopen as draft"
        busyLabel="Reopening…"
        onClose={() => setReopenTarget(null)}
        onSubmit={confirmReopen}
        busy={busy}
        submitDisabled={reopenRemarks.trim().length < 3}
        maxWidth="sm"
      >
        <Box display="grid" gap={2} pt={1}>
          <TextField
            required
            label="Reason for reopening (audit log)"
            multiline
            minRows={3}
            value={reopenRemarks}
            onChange={(e) => setReopenRemarks(e.target.value)}
            slotProps={{ htmlInput: { maxLength: 500 } }}
            helperText="Minimum 3 characters. State what needs to be revised in the programme or timeline."
          />
          {formError && <Alert severity="error">{formError}</Alert>}
        </Box>
      </FormDialog>

      {editor &&
        (editor.edit && !editor.plan.is_deleted && editor.plan.status === 'draft' ? (
          <TimelineEditor plan={editor.plan} onClose={() => setEditor(null)} onSaved={refresh} />
        ) : (
          <PlanView
            plan={editor.plan}
            onClose={() => setEditor(null)}
            onReopen={
              !editor.plan.is_deleted &&
              (editor.plan.status === 'active' || editor.plan.status === 'superseded') &&
              can('ops-plan:reopen')
                ? () => openReopenDialog(editor.plan)
                : undefined
            }
          />
        ))}

      {action && (
        <FormDialog
          open
          title={`${
            action.kind === 'permanent-delete'
              ? 'Delete permanently'
              : action.kind[0].toUpperCase() + action.kind.slice(1)
          } ${action.plan.label}?`}
          danger={action.kind === 'delete' || action.kind === 'permanent-delete'}
          busy={busy}
          onClose={() => setAction(null)}
          submitLabel={
            action.kind === 'permanent-delete'
              ? 'Delete permanently'
              : action.kind[0].toUpperCase() + action.kind.slice(1)
          }
          onSubmit={async () => {
            setBusy(true)
            setFormError('')
            try {
              if (action.kind === 'activate') await activatePlan(action.plan.id)
              else if (action.kind === 'permanent-delete') {
                // Permanent is its own route so a mis-clicked Delete never destroys
                // programme rows: the version must already be in Deleted versions.
                await api('/operations/plans/bulk-permanent-delete', {
                  method: 'POST',
                  body: JSON.stringify({ ids: [action.plan.id] }),
                })
              } else
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
            ? 'This becomes the active baseline for this well and scope. Any prior active version is retained as superseded.'
            : action.kind === 'restore'
              ? 'Restore this version as an editable draft.'
              : action.kind === 'permanent-delete'
                ? 'This permanently removes the timeline and its programme rows. It cannot be undone, and it is refused while a daily report still uses this version as its baseline.'
                : 'This draft and its items can be restored from Deleted versions.'}
          {formError && <Alert severity="error">{formError}</Alert>}
        </FormDialog>
      )}
    </Box>
  )
}

function PlanView({
  plan,
  onClose,
  onReopen,
}: {
  plan: OpsPlan
  onClose: () => void
  onReopen?: () => void
}) {
  const { can } = useAuth()
  return (
    <PanelDialog
      open
      title={`Timeline · ${plan.label}`}
      maxWidth={false}
      onClose={onClose}
      subtitle={`${plan.well_code} · ${plan.scope} · Version ${plan.version_no} · ${plan.status}${plan.planned_start_at ? ` · Start: ${formatWatDateTime(plan.planned_start_at)}` : ''}`}
      footer={
        <>
          {onReopen && (
            <Button color="warning" variant="outlined" startIcon={<LockOpenOutlined />} onClick={onReopen}>
              Reopen as draft
            </Button>
          )}
          <Button onClick={onClose} color="inherit">
            Close
          </Button>
        </>
      }
    >
      {plan.reopened_at && (
        <Alert severity="info" sx={{ mb: 2 }}>
          Last reopened by <strong>{plan.reopened_by || 'workspace user'}</strong> on{' '}
          <strong>{formatWatDateTime(plan.reopened_at)}</strong>
          {plan.reopen_reason ? ` — Reason: ${plan.reopen_reason}` : ''}.
        </Alert>
      )}
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
