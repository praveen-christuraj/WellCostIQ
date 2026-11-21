import { useEffect, useMemo, useState } from 'react'
import { AddOutlined, LockOpenOutlined } from '@mui/icons-material'
import { Alert, Box, Button, Chip, Stack, Tab, Tabs, TextField, Typography } from '@mui/material'
import { Link as RouterLink } from 'react-router-dom'
import { ErrorMessage, FormDialog, PageHeading, PanelDialog, Tag, type Tone } from '../../components/Common'
import { Caution, RestoreCautions } from '../../components/ui/Caution'
import { DataTable } from '../../components/DataTable'
import {
  FolderFields,
  ScopeDirectory,
  useOperationsRegister,
  type Folder,
} from '../../components/operations/ScopeDirectory'
import { StudyPanel } from '../../components/operations/StudyPanel'
import { PlannedSurveyPanel } from '../../components/operations/PlannedSurveyPanel'
import { TimelineEditor } from '../../components/operations/TimelineEditor'
import { useAuth } from '../../context/AuthContext'
import { api } from '../../lib/api'
import {
  activatePlan,
  auditExport,
  closeSequence,
  createPlan,
  getOpsPlan,
  reopenPlan,
  reopenSequence,
  sequenceExport,
  setSequenceState,
  studyTimeline,
  timelineRollup,
  updatePlan,
  type OpsPlan,
  type OpsPlanItem,
  type OpsTimelineRollup,
  type OpsTimelineRollupCode,
} from '../../lib/operations'
import { exportCsv } from '../../lib/export'
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

const CAUTION_PAGE = 'operations-plans'

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
  const [editor, setEditor] = useState<{ plan: OpsPlan; edit: boolean; survey?: boolean } | null>(null)
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

  const open = async (id: string, edit: boolean, survey = false) => {
    setBusy(true)
    setError('')
    try {
      setEditor({ plan: await getOpsPlan(id), edit, survey })
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
      <RestoreCautions page={CAUTION_PAGE}/>

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
                width: 506,
                sortable: false,
                cellRenderer: ({ data: p }: { data: OpsPlan }) => (
                  <>
                    <Button size="small" disabled={busy} onClick={() => void open(p.id, false)}>
                      View timeline
                    </Button>
                    <Button size="small" disabled={busy} onClick={() => void open(p.id, false, true)}>Planned survey</Button>
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
            key={editor.plan.id}
            plan={editor.plan}
            initialSurvey={editor.survey}
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

/** What a programme row's own state is called on screen. */
function stateLabel(state: unknown): string {
  switch (state) {
    case 'skipped':
      return 'Skipped'
    case 'complete':
      return 'Finished'
    case 'not_started':
    case 'planned':
    case undefined:
      return 'Planned'
    default:
      return 'Planned'
  }
}

function PlanView({
  plan,
  onClose,
  onReopen,
  initialSurvey,
}: {
  plan: OpsPlan
  onClose: () => void
  onReopen?: () => void
  initialSurvey?: boolean
}) {
  const { can } = useAuth()
  const [tab, setTab] = useState(initialSurvey ? 'survey' : 'timeline')
  const [rollup, setRollup] = useState<OpsTimelineRollup | null>(null)
  const [rollupError, setRollupError] = useState('')
  const [notice, setNotice] = useState('')
  const [busy, setBusy] = useState(false)
  /** Skip / close is a decision with a reason, so it opens a form instead of firing. */
  const [action, setAction] = useState<{
    kind: 'skip' | 'unskip' | 'close' | 'reopen'
    code: OpsTimelineRollupCode
  } | null>(null)
  const [reason, setReason] = useState('')
  const [hours, setHours] = useState('')
  const [actionError, setActionError] = useState('')
  const [reload, setReload] = useState(0)

  useEffect(() => {
    let current = true
    setRollupError('')
    timelineRollup(plan.id)
      .then((r) => {
        if (current) setRollup(r)
      })
      .catch((e: unknown) => {
        if (current) setRollupError((e as Error).message)
      })
    return () => {
      current = false
    }
  }, [plan.id, reload])

  const openAction = (kind: 'skip' | 'unskip' | 'close' | 'reopen', code: OpsTimelineRollupCode) => {
    setAction({ kind, code })
    setReason('')
    // Pre-fill the hours a close will be judged on: the logged total, which is the
    // evidence the engineer is confirming.
    setHours(code.actual_hours ?? '')
    setActionError('')
  }

  const runAction = async () => {
    if (!action) return
    setBusy(true)
    setActionError('')
    try {
      const { kind, code } = action
      if (kind === 'skip' || kind === 'unskip') {
        const result = await setSequenceState(plan.id, code.item_id, {
          state: kind === 'skip' ? 'skipped' : 'planned',
          reason: kind === 'skip' ? reason : '',
        })
        setNotice(result.summary)
      } else if (kind === 'close') {
        const result = await closeSequence(plan.id, code.item_id, {
          actual_hours: hours.trim() || null,
          note: reason,
        })
        setNotice(result.summary)
      } else {
        const result = await reopenSequence(plan.id, code.item_id, reason)
        setNotice(result.summary)
      }
      setAction(null)
      setReason('')
      setHours('')
      setReload((n) => n + 1)
    } catch (e) {
      setActionError((e as Error).message)
    } finally {
      setBusy(false)
    }
  }

  const exportRegister = async () => {
    setBusy(true)
    setRollupError('')
    try {
      const data = await sequenceExport(plan.id)
      exportCsv(
        `${plan.well_code}-${plan.scope}-sequence-register-v${plan.version_no}.csv`,
        data.rows,
        data.columns.map((column) => ({
          header: column.replace(/_/g, ' '),
          value: (row: Record<string, unknown>) => {
            const value = row[column]
            return value === null || value === undefined ? '' : String(value)
          },
        })),
      )
      setNotice(`Sequence register exported · ${data.notes[0]}`)
    } catch (e) {
      setRollupError((e as Error).message)
    } finally {
      setBusy(false)
    }
  }
  /** The programme rows, enriched with what the logs actually recorded per code. */
  /** The programme rows, enriched with what the logs actually recorded per code. */
  const rows = useMemo<Array<OpsPlanItem & Partial<Omit<OpsTimelineRollupCode, 'state'>>>>(() => {
    if (!rollup) return plan.items.map((item) => ({ ...item }))
    // Joined on identity, never on the printed number: a saved order change must not
    // move one activity's actual hours onto its neighbour.
    const byItem = new Map(rollup.codes.map((c) => [c.item_id, c]))
    return plan.items.map((item) => {
      const code = byItem.get(item.id)
      return {
        ...item,
        actual_hours: code?.actual_hours ?? null,
        remaining_hours: code?.remaining_hours ?? null,
        progress_pct: code?.progress_pct ?? null,
        variance_hours: code?.variance_hours ?? null,
        variance_days: code?.variance_days ?? null,
        comparison: code?.comparison,
        line_count: code?.line_count,
        report_count: code?.report_count,
        effective_cum_days: code?.effective_cum_days ?? null,
        cum_shift_days: code?.cum_shift_days ?? null,
        close_suggested: code?.close_suggested ?? false,
        close_source: code?.close_source ?? '',
      }
    })
  }, [plan.items, rollup])
  const fmt = (value: string | number | null | undefined) => {
    if (value === null || value === undefined || value === '') return '—'
    const parsed = Number(value)
    return Number.isFinite(parsed) ? parsed.toFixed(2) : String(value)
  }
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
      <Tabs value={tab} onChange={(_, value: 'timeline' | 'survey') => setTab(value)} aria-label="Plan version sections" sx={{ mb: 2 }}>
        <Tab value="timeline" label="Timeline activities" id="plan-timeline-tab" aria-controls="plan-timeline-panel" />
        <Tab value="survey" label="Planned survey" id="plan-survey-tab" aria-controls="plan-survey-panel" />
      </Tabs>
      {tab === 'survey' ? <Box role="tabpanel" id="plan-survey-panel" aria-labelledby="plan-survey-tab"><PlannedSurveyPanel plan={plan} /></Box> :
        <Box role="tabpanel" id="plan-timeline-panel" aria-labelledby="plan-timeline-tab">
      {plan.reopened_at && (
        <Caution cautionKey="plan-reopened" page={CAUTION_PAGE} severity="info" signature={[plan.id, plan.reopened_at]} sx={{ mb: 2 }}>
          Last reopened by <strong>{plan.reopened_by || 'workspace user'}</strong> on{' '}
          <strong>{formatWatDateTime(plan.reopened_at)}</strong>
          {plan.reopen_reason ? ` — Reason: ${plan.reopen_reason}` : ''}.
        </Caution>
      )}
      {rollupError && (
        <Alert severity="warning" sx={{ mb: 2 }}>
          Planned-vs-actual per code could not be loaded: {rollupError}
        </Alert>
      )}
      {notice && (
        <Alert severity="success" sx={{ mb: 2 }} onClose={() => setNotice('')}>
          {notice}
        </Alert>
      )}
      {rollup && (
        <Stack spacing={1.5} mb={1.5}>
          <Box display="flex" gap={1} flexWrap="wrap" alignItems="center">
            <Chip size="small" variant="outlined" label={`Planned in scope ${fmt(rollup.totals.planned_in_scope)} h`} />
            <Chip size="small" variant="outlined" label={`Hours spent ${fmt(rollup.totals.actual_total)} h`} />
            <Chip
              size="small"
              color={
                rollup.totals.realised_variance === null
                  ? 'default'
                  : rollup.totals.comparison === 'ahead'
                    ? 'success'
                    : rollup.totals.comparison === 'behind'
                      ? 'warning'
                      : 'default'
              }
              label={
                // Only finished activities vote. An open plan has spent hours, not
                // a lead — the chip says so instead of printing the burn as one.
                rollup.totals.closed_code_count === 0
                  ? 'No activity finished yet — no lead or lag'
                  : `Lead / lag ${
                      Number(rollup.totals.realised_variance ?? 0) >= 0 ? '+' : ''
                    }${fmt(rollup.totals.realised_variance)} h · ${fmt(rollup.totals.realised_variance_days)} d`
              }
            />
            {Number(rollup.totals.planned_saved ?? 0) > 0 && (
              <Chip
                size="small"
                variant="outlined"
                label={`${fmt(rollup.totals.planned_saved)} h released by skipped activities`}
              />
            )}
            {Number(rollup.totals.actual_unplanned ?? 0) > 0 && (
              <Chip
                size="small"
                color="warning"
                variant="outlined"
                label={`${fmt(rollup.totals.actual_unplanned)} h unplanned (${rollup.unplanned.line_count} line(s)) — reads as lag`}
              />
            )}
            {Number(rollup.totals.actual_unplanned ?? 0) === 0 && rollup.uncoded_lines > 0 && (
              <Chip
                size="small"
                color="warning"
                variant="outlined"
                label={`${rollup.uncoded_lines} uncoded line(s) in drafts — not yet counted`}
              />
            )}
            {rollup.provisional_report_count > 0 && (
              <Chip
                size="small"
                variant="outlined"
                label={`${rollup.provisional_report_count} draft report(s) excluded from these figures`}
              />
            )}
            <Button size="small" onClick={() => void exportRegister()} disabled={busy}>
              Export the register
            </Button>
          </Box>
          <Typography variant="caption" color="text.secondary">
            Hours are summed per sequence code across every confirmed report logged against this baseline. Variance is
            planned − actual, ÷ 24 for days; positive is a lead, negative a lag. It is printed only once the activity is
            <strong> finished</strong> — until then the difference is work still owed, shown as remaining hours. Skipped
            activities release their hours instead of reading as a lag.
          </Typography>
          {rollup.findings.length > 0 && (
            <Alert severity={rollup.findings.some((f) => f.severity === 'warning') ? 'warning' : 'info'}>
              {rollup.findings.slice(0, 4).map((finding) => (
                <Typography key={`${finding.kind}-${finding.item_id ?? finding.block_id ?? ''}`} variant="caption" component="p">
                  {finding.message}
                </Typography>
              ))}
            </Alert>
          )}
        </Stack>
      )}
      <DataTable
        rows={rows}
        exportName={`${plan.well_code}-${plan.scope}-timeline-v${plan.version_no}`}
        canExport={can('ops-plan:export')}
        onExport={auditExport('plans')}
        columns={[
          { field: 'sequence_no', headerName: 'Sequence', width: 100 },
          { field: 'description', headerName: 'Activity', minWidth: 250, flex: 3, tooltipField: 'description' },
          { field: 'target_depth_m', headerName: 'Target MD (m)' },
          { field: 'planned_hours', headerName: 'Planned hours', valueFormatter: (p) => fmt(p.value) },
          {
            field: 'state',
            headerName: 'State',
            width: 130,
            valueGetter: ({ data }) => stateLabel(data?.state),
            // The state is the reason a row has no verdict, so it is the one cell
            // that must never be silent.
            cellStyle: ({ data }): Record<string, string> => {
              if (data?.state === 'skipped') return { color: 'var(--mui-palette-text-secondary)' }
              if (data?.state === 'complete') {
                return { color: 'var(--mui-palette-success-main)', fontWeight: '600' }
              }
              return {}
            },
          },
          {
            field: 'actual_hours',
            headerName: 'Logged (h)',
            valueGetter: ({ data }) =>
              data?.actual_hours === null || data?.actual_hours === undefined
                ? '—'
                : Number(data.actual_hours).toFixed(2),
          },
          {
            field: 'progress_pct',
            headerName: 'Progress',
            width: 105,
            valueGetter: ({ data }) =>
              data?.progress_pct === null || data?.progress_pct === undefined
                ? '—'
                : `${Number(data.progress_pct).toFixed(0)} %`,
          },
          {
            // Remaining work, printed where the old screen printed a lead. An open
            // activity owes hours; it is not early.
            field: 'remaining_hours',
            headerName: 'Remaining (h)',
            width: 120,
            valueGetter: ({ data }) =>
              data?.remaining_hours === null || data?.remaining_hours === undefined
                ? '—'
                : Number(data.remaining_hours).toFixed(2),
          },
          {
            field: 'variance_hours',
            headerName: 'Variance (h)',
            minWidth: 110,
            valueGetter: ({ data }) =>
              data?.variance_hours === null || data?.variance_hours === undefined
                ? '—'
                : `${Number(data.variance_hours) >= 0 ? '+' : ''}${Number(data.variance_hours).toFixed(2)}`,
          },
          {
            field: 'comparison',
            headerName: 'Lead / Lag',
            width: 130,
            valueGetter: ({ data }) => {
              if (!data || data.variance_hours === null || data.variance_hours === undefined) {
                // Say what the row is instead of "On plan", which would be a claim.
                return data?.state === 'skipped'
                  ? 'Released'
                  : data?.state === 'complete'
                    ? 'On plan'
                    : data?.state === undefined || data?.state === 'planned'
                      ? 'Not started'
                      : 'No verdict yet'
              }
              return data.comparison === 'ahead' ? 'Lead' : data.comparison === 'behind' ? 'Lag' : 'On plan'
            },
          },
          {
            field: 'line_count',
            headerName: 'Lines',
            width: 80,
            valueGetter: ({ data }) => (data?.line_count === undefined ? '—' : String(data.line_count)),
          },
          {
            field: 'report_count',
            headerName: 'Logs',
            width: 80,
            valueGetter: ({ data }) => (data?.report_count === undefined ? '—' : String(data.report_count)),
          },
          {
            field: 'cum_planned_days',
            headerName: 'Cumulative days',
            valueGetter: ({ data }) =>
              data?.cum_shift_days && Number(data.cum_shift_days) > 0
                ? `${fmt(data.cum_planned_days)} (${fmt(data.effective_cum_days)} effective)`
                : fmt(data?.cum_planned_days),
          },
          {
            headerName: 'ACTIONS',
            width: 190,
            sortable: false,
            filter: false,
            valueGetter: ({ data }) =>
              data?.state === 'skipped'
                ? 'Restore'
                : data?.state === 'complete'
                  ? 'Reopen'
                  : data?.state === undefined || data?.state === 'planned'
                    ? 'Skip · Close'
                    : 'Close',
            onCellClicked: ({ data }) => {
              if (!data || !rollup) return
              const code = rollup.codes.find((c) => c.item_id === data.id)
              if (!code) return
              // A skipped row is restored, a finished one reopened, an open one
              // either skipped or closed — each with its own form.
              if (code.state === 'skipped') openAction('unskip', code)
              else if (code.state === 'complete') openAction('reopen', code)
              else openAction('close', code)
            },
            cellStyle: { cursor: 'pointer', color: 'var(--mui-palette-primary-main)' } as Record<string, string>,
          },
        ]}
      />
      <Box mt={2}>
        <Typography variant="h6">Timeline study</Typography>
        <StudyPanel runLabel="Study saved timeline" run={(useAi) => studyTimeline(plan.id, useAi)} />
      </Box>
        </Box>}

      {action && (
        <FormDialog
          open
          title={
            action.kind === 'skip'
              ? `Skip sequence ${action.code.sequence_no}`
              : action.kind === 'unskip'
                ? `Restore sequence ${action.code.sequence_no}`
                : action.kind === 'close'
                  ? `Finish sequence ${action.code.sequence_no}`
                  : `Reopen sequence ${action.code.sequence_no}`
          }
          subtitle={action.code.description}
          onClose={() => setAction(null)}
          onSubmit={() => void runAction()}
          submitLabel={
            action.kind === 'skip'
              ? 'Skip the activity'
              : action.kind === 'unskip'
                ? 'Put it back in the plan'
                : action.kind === 'close'
                  ? 'Finish the activity'
                  : 'Reopen it'
          }
          busy={busy}
          submitDisabled={action.kind === 'skip' || action.kind === 'reopen' ? reason.trim().length < 3 : false}
        >
          <Stack spacing={2} pt={0.5}>
            {actionError && <Alert severity="error">{actionError}</Alert>}
            {action.kind === 'skip' && (
              <Alert severity="warning">
                A skipped activity will never be done. Its {fmt(action.code.planned_hours)} planned hours leave the
                plan&rsquo;s scope and are reported once as <strong>saved</strong>; every later activity&rsquo;s
                effective position moves earlier by that time. It is not counted as a lag. Hours already logged
                against it must be moved first.
              </Alert>
            )}
            {action.kind === 'unskip' && (
              <Alert severity="info">
                Restoring puts its {fmt(action.code.planned_hours)} planned hours back in scope and moves every later
                activity&rsquo;s effective position back out. The saved-hours line disappears.
              </Alert>
            )}
            {action.kind === 'close' && (
              <>
                <Alert severity="info">
                  Finishing is what turns hours into a lead or a lag: {fmt(action.code.planned_hours)} h planned −{' '}
                  {fmt(action.code.actual_hours)} h logged. It is never inferred from the hours alone, because a job
                  finished in 90 hours and a job abandoned at 100 are not the same event.
                </Alert>
                <TextField
                  label="Actual hours to close on"
                  value={hours}
                  onChange={(e) => {
                    const typed = e.target.value
                    if (!/^\d*\.?\d*$/.test(typed)) return
                    setHours(typed)
                  }}
                  helperText="Defaults to the hours logged against it. Change it only with a note saying where the real figure is."
                  fullWidth
                />
              </>
            )}
            {action.kind === 'reopen' && (
              <Alert severity="warning">
                Reopening withdraws the verdict. The hours stay on the record; the activity goes back to showing
                progress until it is finished again.
              </Alert>
            )}
            <TextField
              label={
                action.kind === 'skip'
                  ? 'Why is the activity skipped?'
                  : action.kind === 'close'
                    ? 'Note (required if the hours differ from the log)'
                    : action.kind === 'reopen'
                      ? 'Why is the close withdrawn?'
                      : 'Note'
              }
              value={reason}
              onChange={(e) => setReason(e.target.value)}
              multiline
              minRows={2}
              fullWidth
              required={action.kind === 'skip' || action.kind === 'reopen'}
              helperText={
                action.kind === 'skip' || action.kind === 'reopen'
                  ? 'At least a few words. It is kept with the activity and written to the Audit Log.'
                  : 'Kept with the close, so a reader sees on what evidence it was made.'
              }
            />
          </Stack>
        </FormDialog>
      )}
    </PanelDialog>
  )
}
