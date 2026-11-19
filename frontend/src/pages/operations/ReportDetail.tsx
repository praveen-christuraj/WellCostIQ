import { useEffect, useState } from 'react'
import { Link as RouterLink } from 'react-router-dom'
import { AutoAwesomeOutlined, LockOpenOutlined } from '@mui/icons-material'
import {
  Alert,
  Autocomplete,
  Box,
  Button,
  Checkbox,
  Chip,
  CircularProgress,
  Divider,
  FormControlLabel,
  MenuItem,
  Stack,
  Switch,
  Tab,
  Tabs,
  TextField,
  Typography,
} from '@mui/material'
import { AiStatusAlert } from '../../components/assistant/AiStatusAlert'
import { ErrorMessage, FormDialog, PanelDialog, useFormDirty, useUnsavedChangesGuard } from '../../components/Common'
import { DataTable } from '../../components/DataTable'
import { BulkAssignDialog } from '../../components/operations/BulkAssignDialog'
import { SourceDialog } from '../../components/operations/SourceDialog'
import { StudyPanel } from '../../components/operations/StudyPanel'
import { SectionCard } from '../../components/ui/SectionCard'
import { useAuth } from '../../context/AuthContext'
import { downloadFile } from '../../lib/api'
import {
  aiPrefillReport,
  approveReport,
  auditExport,
  generateReportNarratives,
  getBrief,
  getReport,
  opsReference,
  opsReviewTimeline,
  rejectReport,
  reopenReport,
  reviewBrief,
  saveReport,
  submitReport,
  type OpsAiPrefill,
  type OpsBlock,
  type OpsNarratives,
  type OpsReference,
  type OpsReport,
  type OpsSurvey,
} from '../../lib/operations'
import { printDailyReport } from '../../lib/operationsPdf'
import {
  formatWatDateTime,
  formatWatShort,
  fromWatDateTimeInput,
  parseInstant,
  toWatDateTimeInput,
  WAT_LABEL,
} from '../../lib/time'

const editFields = [
  'sequence_no',
  'started_at',
  'ended_at',
  'duration_minutes',
  'phase_raw',
  'operation_code_id',
  'activity_code_id',
  'activity_id',
  'classification',
  'allocation',
  'is_productive',
  'classification_source',
  'classification_evidence',
  'source_page',
  'source_bbox',
  'npt_code_id',
  'agency_id',
  'cause_code',
  'hole_section_id',
  'phase_id',
  'depth_from_m',
  'depth_to_m',
  'tvd_from_m',
  'tvd_to_m',
  'bit_depth_m',
  'mud_weight_ppg',
  'footage_m',
  'rotating_hours',
  'rop_m_per_hr',
  'rop_basis',
  'vendor_id',
  'responsible_party',
  'reason',
  'narrative',
  'confidence',
  'review_state',
  // The visible comparison travels with the block so a save does not silently
  // reset an engineer's accept/edit decision back to "suggested".
  'timeline_comparison',
  'timeline_review_state',
  'timeline_note',
] as const

type Block = Pick<
  OpsBlock,
  | (typeof editFields)[number]
  | 'source_activity_code'
  | 'source_activity_label'
  | 'source_operation_label'
  | 'source_phase_label'
  | 'source_mark_label'
  | 'source_cause_label'
  | 'timeline_variance_days'
  | 'timeline_planned_days'
  | 'timeline_actual_days'
  | 'timeline_basis'
  | 'timeline_reviewed_by'
  | 'timeline_reviewed_at'
> & { id: string }

const surveyFields = {
  md_m: 'MD (m)',
  tvd_m: 'TVD (m)',
  inc_deg: 'Inclination (°)',
  azi_deg: 'Azimuth (°)',
  ns_m: 'N/S (m)',
  ew_m: 'E/W (m)',
  vsec_m: 'Vertical section (m)',
  dls_deg_per_30m: 'Dogleg (°/30 m)',
}

const newSurvey = (): OpsSurvey => ({
  md_m: null,
  tvd_m: null,
  vsec_m: null,
  dls_deg_per_30m: null,
  inc_deg: null,
  azi_deg: null,
  ns_m: null,
  ew_m: null,
  source: 'manual',
  tool: '',
})

const depthRange = (from: string | null | undefined, to: string | null | undefined) => {
  if (!from && !to) return '—'
  if (from && to && from !== to) return `${from}–${to}`
  return to || from || '—'
}

export default function OperationsReportDetail({
  id,
  includeDeleted,
  onClose,
  onChanged,
}: {
  id: string
  includeDeleted: boolean
  onClose: (report: OpsReport | null) => void
  onChanged: () => Promise<void>
}) {
  const { can } = useAuth()
  const [tab, setTab] = useState<'log' | 'details' | 'sources'>('log')
  const [report, setReport] = useState<OpsReport | null>(null)
  const [ref, setRef] = useState<OpsReference | null>(null)
  const [brief, setBrief] = useState('')
  const [briefError, setBriefError] = useState('')
  const [header, setHeader] = useState<Partial<OpsReport>>({})
  const [blocks, setBlocks] = useState<Block[]>([])
  const [surveys, setSurveys] = useState<OpsSurvey[]>([])
  const [dirty, setDirty] = useState(false)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')
  const [notice, setNotice] = useState('')
  const [editor, setEditor] = useState<Block | null>(null)
  const [remove, setRemove] = useState<Block | null>(null)
  const [source, setSource] = useState(false)
  const [reject, setReject] = useState(false)
  const [reason, setReason] = useState('')
  const [reopenOpen, setReopenOpen] = useState(false)
  const [reopenRemarks, setReopenRemarks] = useState('')
  const [confirmed, setConfirmed] = useState(false)
  const [bulkOpen, setBulkOpen] = useState(false)
  const [selected, setSelected] = useState<Block[]>([])
  // Bumped on every load so a stale selection never carries onto a new report.
  const [selectionKey, setSelectionKey] = useState(0)
  const [timelineReview, setTimelineReview] = useState<{
    open: boolean
    state: 'accepted' | 'edited' | 'rejected'
  }>({ open: false, state: 'accepted' })
  const [timelineNote, setTimelineNote] = useState('')

  // Offline AI narrative generator & AI extraction prefill state
  const [narUseAi, setNarUseAi] = useState(true)
  const [narFocus, setNarFocus] = useState('')
  const [narBusy, setNarBusy] = useState(false)
  const [narratives, setNarratives] = useState<OpsNarratives | null>(null)
  const [prefillBusy, setPrefillBusy] = useState(false)
  const [prefillResult, setPrefillResult] = useState<OpsAiPrefill | null>(null)

  const editorDirty = useFormDirty(editor, Boolean(editor))

  const reset = (r: OpsReport) => {
    setConfirmed(false)
    setReport(r)
    setHeader({})
    setBlocks(r.blocks)
    setSurveys(r.surveys)
    setSelected([])
    setSelectionKey((n) => n + 1)
    setDirty(false)
  }

  useEffect(() => {
    let current = true
    setError('')
    setBrief('')
    setBriefError('')
    setNarratives(null)
    setPrefillResult(null)
    setReport(null)
    if (id)
      Promise.all([getReport(id, includeDeleted), opsReference()])
        .then(([r, refs]) => {
          if (current) {
            reset(r)
            setRef(refs)
          }
        })
        .catch((e) => {
          if (current) setError((e as Error).message)
        })
    void getBrief(id, includeDeleted)
      .then((b) => {
        if (current) setBrief(b.summary)
      })
      .catch((e) => {
        if (current) setBriefError((e as Error).message)
      })
    return () => {
      current = false
    }
  }, [id, includeDeleted])

  /** Re-read the report after a bulk or review action, keeping the current tab. */
  const load = () =>
    getReport(id, includeDeleted)
      .then((r) => reset(r))
      .catch((e) => setError((e as Error).message))

  const refreshBrief = () => {
    setBriefError('')
    return getBrief(id, includeDeleted)
      .then((b) => setBrief(b.summary))
      .catch((e) => setBriefError((e as Error).message))
  }

  const editable =
    !!report &&
    !report.is_deleted &&
    ['draft', 'in_review', 'rejected'].includes(report.status) &&
    can('ops-report:update')

  const mayReopen =
    !!report &&
    !report.is_deleted &&
    ['submitted', 'approved'].includes(report.status) &&
    can('ops-report:reopen')

  const updateHeader = (patch: Partial<OpsReport>) => {
    setDirty(true)
    setHeader((prev) => ({ ...prev, ...patch }))
  }

  const persist = async (updatedBlocks = blocks) => {
    if (!report || !editable || busy) return false
    setBusy(true)
    setError('')
    setNotice('')
    try {
      const payload = updatedBlocks.map((b, i) => ({
        ...Object.fromEntries(editFields.map((k) => [k, b[k]])),
        block_id: b.id.startsWith('new-') ? null : b.id,
        sequence_no: i + 1,
        review_state: b.review_state === 'suggested' && confirmed ? 'accepted' : b.review_state,
      }))
      const r = await saveReport(report.id, {
        expected_updated_at: report.updated_at,
        confirm_review: confirmed,
        report: header,
        blocks: payload,
        surveys,
      })
      reset(r)
      void refreshBrief()
      void onChanged()
      setNotice(
        r.extraction_status === 'needs_review'
          ? 'Draft saved. Confirm remaining extracted suggestions before submitting.'
          : 'Draft saved. Submit when ready.',
      )
      return true
    } catch (e) {
      setError((e as Error).message)
      return false
    } finally {
      setBusy(false)
    }
  }

  const transition = async (action: 'submit' | 'approve' | 'reject' | 'reopen') => {
    if (!report || dirty) return
    setBusy(true)
    setError('')
    setNotice('')
    try {
      const r =
        action === 'submit'
          ? await submitReport(report.id)
          : action === 'approve'
            ? await approveReport(report.id)
            : action === 'reject'
              ? await rejectReport(report.id, reason)
              : await reopenReport(report.id, reopenRemarks.trim())
      reset(r)
      void onChanged()
      void refreshBrief()
      setReject(false)
      setReopenOpen(false)
      setNotice(
        action === 'reopen'
          ? 'Report reopened to editable draft. Update any fields or activity blocks, save, and submit when ready.'
          : `Report ${r.status}.`,
      )
    } catch (e) {
      setError((e as Error).message)
    } finally {
      setBusy(false)
    }
  }

  const runAiPrefill = async () => {
    if (!report || !editable || dirty || prefillBusy) return
    setPrefillBusy(true)
    setError('')
    setNotice('')
    try {
      const res = await aiPrefillReport(report.id)
      setPrefillResult(res)
      reset(res.report)
      void refreshBrief()
      void onChanged()
      if (res.ai_used) {
        const parts = []
        if (res.updated_header_fields.length) parts.push(`${res.updated_header_fields.length} header field(s)`)
        if (res.updated_block_count) parts.push(`${res.updated_block_count} activity block(s)`)
        setNotice(
          parts.length
            ? `Offline AI refined ${parts.join(' and ')}. Review all suggestions and save when satisfied.`
            : 'Offline AI checked the extracted draft — all available fields are already populated.',
        )
      }
    } catch (e) {
      setError((e as Error).message)
    } finally {
      setPrefillBusy(false)
    }
  }

  const runNarratives = async (withAi = narUseAi) => {
    if (!report || narBusy) return
    setNarBusy(true)
    setError('')
    try {
      setNarratives(await generateReportNarratives(report.id, withAi, narFocus.trim()))
    } catch (e) {
      setError((e as Error).message)
    } finally {
      setNarBusy(false)
    }
  }

  const applyNarratives = () => {
    if (!narratives || !editable) return
    const patch: Partial<OpsReport> = {}
    if (narratives.operation_summary) patch.operation_summary = narratives.operation_summary
    if (narratives.forward_plan) patch.forward_plan = narratives.forward_plan
    if (narratives.hse_summary) patch.hse_summary = narratives.hse_summary
    updateHeader(patch)
    setNotice('Generated D&C narratives applied to the draft fields — review, edit as needed, and click Save draft.')
  }

  const h = (field: keyof OpsReport) => (field in header ? header[field] : report?.[field])

  const addBlock = () => {
    const startRaw = blocks.at(-1)?.ended_at ?? report?.period_start_at
    const startDate = parseInstant(startRaw)
    if (!startDate) return
    const endDate = new Date(startDate.getTime() + 3600000)
    const startLocal = toWatDateTimeInput(startDate.toISOString())
    const endLocal = toWatDateTimeInput(endDate.toISOString())
    setEditor({
      id: `new-${Date.now()}`,
      sequence_no: blocks.length + 1,
      started_at: fromWatDateTimeInput(startLocal) || startDate.toISOString(),
      ended_at: fromWatDateTimeInput(endLocal) || endDate.toISOString(),
      duration_minutes: 60,
      phase_raw: '',
      operation_code_id: null,
      activity_code_id: null,
      activity_id: null,
      classification: 'Planned',
      allocation: 'PT',
      is_productive: true,
      classification_source: 'reviewer',
      npt_code_id: null,
      agency_id: null,
      cause_code: '',
      hole_section_id: null,
      phase_id: null,
      depth_from_m: null,
      depth_to_m: null,
      tvd_from_m: null,
      tvd_to_m: null,
      bit_depth_m: null,
      mud_weight_ppg: null,
      footage_m: null,
      rotating_hours: null,
      rop_m_per_hr: null,
      rop_basis: 'rotating',
      vendor_id: null,
      responsible_party: '',
      reason: '',
      narrative: '',
      confidence: '1',
      review_state: 'edited',
    })
  }

  const duration = (() => {
    if (!editor) return 0
    const a = parseInstant(editor.started_at)
    const b = parseInstant(editor.ended_at)
    if (!a || !b) return 0
    return Math.round((b.getTime() - a.getTime()) / 60000)
  })()

  const withEditor = () => {
    if (!editor || !(duration > 0 && duration <= 1440)) return null
    const b: Block = { ...editor, review_state: 'edited', duration_minutes: duration }
    return blocks.some((x) => x.id === b.id) ? blocks.map((x) => (x.id === b.id ? b : x)) : [...blocks, b]
  }

  const apply = () => {
    const updated = withEditor()
    if (!updated) return
    setBlocks(updated)
    setEditor(null)
    setDirty(true)
  }

  const guard = useUnsavedChangesGuard({
    when: dirty || editorDirty,
    onSave: async () => {
      if (!editorDirty) return persist()
      const updated = withEditor()
      return updated ? persist(updated) : false
    },
    title: 'Close with unsaved report changes?',
  })

  if (!report)
    return (
      <PanelDialog open title="Daily report" maxWidth={false} onClose={() => onClose(null)}>
        {error ? <ErrorMessage message={error} /> : <Typography role="status">Loading daily report…</Typography>}
      </PanelDialog>
    )

  const print = async () => {
    setBusy(true)
    try {
      await printDailyReport(report, brief)
    } catch (e) {
      setError((e as Error).message)
    } finally {
      setBusy(false)
    }
  }

  const totals = { Planned: 0, UPA: 0, NPT: 0 }
  for (const b of blocks) totals[b.classification] += b.duration_minutes
  const gap = report.period_minutes - totals.Planned - totals.UPA - totals.NPT

  const numField = (k: keyof OpsReport, label: string, helper?: string) => (
    <TextField
      key={k}
      size="small"
      label={label}
      helperText={helper}
      disabled={!editable}
      value={h(k) ?? ''}
      onChange={(e) => {
        const raw = e.target.value
        if (k === 'day_number' || k === 'pob_count') {
          updateHeader({ [k]: raw ? Number(raw) : null })
        } else {
          updateHeader({ [k]: raw || null })
        }
      }}
    />
  )

  const textField = (k: keyof OpsReport, label: string, full = false) => (
    <TextField
      key={k}
      size="small"
      sx={full ? { gridColumn: '1 / -1' } : undefined}
      label={label}
      disabled={!editable}
      value={h(k) ?? ''}
      onChange={(e) => updateHeader({ [k]: e.target.value })}
    />
  )

  return (
    <>
      <PanelDialog
        open
        maxWidth={false}
        onClose={() => onClose(report)}
        title={`${report.is_deleted ? 'Deleted daily report' : report.extraction_status === 'needs_review' ? 'Review extracted report' : 'Daily report'} · ${report.well_code_snapshot} · ${report.report_date}`}
        subtitle={`${report.rig_code_snapshot || 'Rig —'} / ${report.scope} · ${report.report_type} ${report.report_no_text} · ${report.status} · ${WAT_LABEL}`}
        footer={
          <Box display="flex" gap={1} alignItems="center" flexWrap="wrap" width="100%" justifyContent="flex-end">
            <Button onClick={() => onClose(report)} disabled={busy} color="inherit">
              {editable ? 'Cancel' : 'Close'}
            </Button>
            {!dirty && (
              <Button
                component={RouterLink}
                to={`/operations/summary?well=${encodeURIComponent(report.well_id)}&scope=${encodeURIComponent(report.scope)}`}
              >
                Well summary
              </Button>
            )}
            {can('ops-report:print') && (
              <Button onClick={print} disabled={busy || dirty}>
                Report PDF
              </Button>
            )}
            {mayReopen && (
              <Button
                variant="outlined"
                color="warning"
                startIcon={<LockOpenOutlined />}
                disabled={busy}
                onClick={() => {
                  setReopenRemarks('')
                  setError('')
                  setReopenOpen(true)
                }}
              >
                Reopen as draft
              </Button>
            )}
            {editable && (
              <Button variant="contained" disabled={busy} onClick={() => void persist()}>
                {confirmed ? 'Save reviewed draft' : 'Save draft'}
              </Button>
            )}
            {!report.is_deleted &&
              can('ops-report:submit') &&
              ['draft', 'in_review', 'rejected'].includes(report.status) && (
                <Button
                  variant="outlined"
                  disabled={busy || dirty || report.extraction_status === 'needs_review'}
                  onClick={() => void transition('submit')}
                >
                  Submit
                </Button>
              )}
            {!report.is_deleted && report.status === 'submitted' && can('ops-report:approve') && (
              <>
                <Button variant="contained" disabled={busy} onClick={() => void transition('approve')}>
                  Approve
                </Button>
                <Button
                  variant="outlined"
                  disabled={busy}
                  onClick={() => {
                    setReason('')
                    setReject(true)
                  }}
                >
                  Reject
                </Button>
              </>
            )}
          </Box>
        }
      >
        <Stack spacing={1.25} mb={1}>
          {error && <ErrorMessage message={error} />}
          {notice && (
            <Alert severity="success" onClose={() => setNotice('')}>
              {notice}
            </Alert>
          )}
          {prefillResult?.ai_error && (
            <AiStatusAlert
              message={prefillResult.ai_error}
              errorCode={prefillResult.ai_error_code}
              model={prefillResult.ai_model}
              busy={prefillBusy}
              fallbackNote="All deterministically extracted MDs, TVDs, wellbore parameters, surveys and time blocks remain intact below."
              onRetry={() => void runAiPrefill()}
              onDismiss={() => setPrefillResult(null)}
            />
          )}
          {report.status === 'rejected' && (
            <Alert severity="warning">Returned for correction: {report.rejection_reason}</Alert>
          )}
          {report.reopened_at && (
            <Alert severity="info">
              Last reopened by <strong>{report.reopened_by || 'workspace user'}</strong> on{' '}
              <strong>{formatWatDateTime(report.reopened_at)}</strong>
              {report.reopen_reason ? ` — Reason: ${report.reopen_reason}` : ''}.
            </Alert>
          )}
          {['submitted', 'approved'].includes(report.status) && !report.is_deleted && (
            <Alert severity="success">
              This report is <strong>{report.status}</strong>
              {report.approved_at
                ? ` (approved by ${report.approved_by || 'approver'} on ${formatWatDateTime(report.approved_at)})`
                : report.submitted_at
                  ? ` (submitted by ${report.submitted_by || 'engineer'} on ${formatWatDateTime(report.submitted_at)})`
                  : ''}
              . {mayReopen ? 'Click “Reopen as draft” with remarks if you need to revise any entry.' : 'Read-only.'}
            </Alert>
          )}
          {report.is_deleted && (
            <Alert severity="info">This report is read-only. Restore it from the register before making changes.</Alert>
          )}
          {!report.is_deleted && report.extraction_status === 'needs_review' && (
            <Alert severity="info">
              Extracted fields and blocks are prefilled as suggestions — including Measured Depths (MD), True Vertical
              Depths (TVD), bit depth, casing, mud, BHA, surveys, narratives and WAT activity blocks. Verify, adjust any
              value, and save the reviewed draft.
            </Alert>
          )}
          {editable &&
            (report.current_extraction_id || blocks.some((b) => b.review_state === 'suggested')) &&
            can('ops-report:review') && (
            <FormControlLabel
              control={
                <Checkbox
                  checked={confirmed}
                  onChange={(e) => {
                    setConfirmed(e.target.checked)
                    setDirty(true)
                  }}
                />
              }
              label="I checked the source, scope, MD/TVD depths, wellbore parameters and WAT time allocations. Accept the remaining suggestions when I save."
            />
          )}
        </Stack>

        <Tabs value={tab} onChange={(_, v) => setTab(v)} aria-label="Report editor sections" sx={{ mb: 1.5 }}>
          <Tab value="log" label={`Activity log (${blocks.length})`} />
          <Tab value="details" label="Measurements, wellbore & narratives" />
          <Tab value="sources" label={`Sources & surveys (${surveys.length})`} />
        </Tabs>

        {tab === 'log' && (
          <SectionCard
            title="Activity log"
            subtitle={`Times are entered and displayed in ${WAT_LABEL}. Durations are calculated directly from the start and end clocks.`}
            action={
              editable && (
                <Stack direction="row" gap={1} flexWrap="wrap">
                  {(report.source_document_id || blocks.length > 0) && (
                    <Button
                      variant="outlined"
                      size="small"
                      startIcon={prefillBusy ? <CircularProgress size={13} /> : <AutoAwesomeOutlined fontSize="small" />}
                      disabled={dirty || busy || prefillBusy}
                      onClick={() => void runAiPrefill()}
                    >
                      {prefillBusy ? 'Refining…' : 'AI Prefill Gaps'}
                    </Button>
                  )}
                  {can('ops-master:read') && (
                    <Button
                      component={RouterLink}
                      to="/operations/library?tab=correlations"
                      variant="outlined"
                      size="small"
                    >
                      Code correlations
                    </Button>
                  )}
                  <Button
                    variant="outlined"
                    size="small"
                    disabled={!blocks.length}
                    onClick={() => setBulkOpen(true)}
                  >
                    Assign codes in bulk{selected.length ? ` (${selected.length})` : ''}
                  </Button>
                  <Button
                    variant="outlined"
                    size="small"
                    disabled={!blocks.length}
                    onClick={() => {
                      setTimelineNote('')
                      setTimelineReview({ open: true, state: 'accepted' })
                    }}
                  >
                    Review lead / lag
                  </Button>
                  <Button variant="contained" size="small" onClick={addBlock}>
                    Add block
                  </Button>
                </Stack>
              )
            }
          >
            <Box display="flex" alignItems="center" gap={1} flexWrap="wrap" mb={1.5}>
              {Object.entries(totals).map(([k, v]) => (
                <Chip key={k} size="small" label={`${k}: ${(v / 60).toFixed(3)} h · ${(v / 1440).toFixed(3)} d`} />
              ))}
              <Chip
                size="small"
                label={`Productive ${(blocks.reduce((n, b) => n + (b.is_productive ? b.duration_minutes : 0), 0) / 60).toFixed(3)} h · Nonproductive ${(blocks.reduce((n, b) => n + (b.is_productive ? 0 : b.duration_minutes), 0) / 60).toFixed(3)} h`}
              />
              <Chip size="small" label={`Period balance: ${gap} min`} />
              {report.scope === 'completion' && <Chip size="small" variant="outlined" label="ROP: N/A" />}
              {(report.depth_end_m || report.tvd_m) && (
                <Chip
                  size="small"
                  color="primary"
                  variant="outlined"
                  label={`MD: ${report.depth_start_m ?? '—'}→${report.depth_end_m ?? '—'} m · TVD: ${report.tvd_m ?? '—'} m${report.bit_depth_m ? ` · Bit: ${report.bit_depth_m} m` : ''}`}
                />
              )}
            </Box>
            <DataTable
              rows={blocks}
              selectable={editable}
              selectionResetKey={selectionKey}
              onSelectionChange={setSelected}
              canExport={can('ops-report:export')}
              exportName={`${report.well_code_snapshot}-${report.report_date}-activities`}
              onExport={auditExport('reports')}
              columns={[
                {
                  field: 'started_at',
                  headerName: 'From (WAT)',
                  minWidth: 145,
                  valueFormatter: (p) => formatWatShort(p.value),
                },
                {
                  field: 'ended_at',
                  headerName: 'To (WAT)',
                  minWidth: 145,
                  valueFormatter: (p) => formatWatShort(p.value),
                },
                { field: 'duration_minutes', headerName: 'Min', minWidth: 80 },
                {
                  field: 'depth_to_m',
                  headerName: 'MD (m)',
                  minWidth: 120,
                  valueGetter: ({ data }) => (data ? depthRange(data.depth_from_m, data.depth_to_m) : '—'),
                },
                {
                  field: 'tvd_to_m',
                  headerName: 'TVD (m)',
                  minWidth: 120,
                  valueGetter: ({ data }) => (data ? depthRange(data.tvd_from_m, data.tvd_to_m) : '—'),
                },
                { field: 'bit_depth_m', headerName: 'Bit (m)', minWidth: 95 },
                { field: 'narrative', headerName: 'Operation', minWidth: 260, tooltipField: 'narrative' },
                { field: 'source_phase_label', headerName: 'Phase', minWidth: 155, tooltipField: 'source_phase_label' },
                {
                  field: 'source_activity_label',
                  headerName: 'Activity code',
                  minWidth: 205,
                  tooltipField: 'source_activity_label',
                  valueGetter: ({ data }) => {
                    const workspace = ref?.activity_codes.find((c) => c.id === data?.activity_code_id)
                    return workspace
                      ? `${workspace.activity_code} — ${workspace.activity_name}`
                      : data?.source_activity_label || ''
                  },
                },
                { field: 'classification', headerName: 'Class', minWidth: 98 },
                { field: 'allocation', headerName: 'Alloc', minWidth: 90 },
                { field: 'responsible_party', headerName: 'Agency', minWidth: 135 },
                {
                  field: 'timeline_comparison',
                  headerName: 'Lead (+/−)',
                  minWidth: 150,
                  valueGetter: ({ data }) => {
                    const variance = data?.timeline_variance_days
                    const mark = data?.timeline_comparison
                    if (!mark) return ''
                    const label = mark === 'ahead' ? 'Lead' : mark === 'behind' ? 'Lag' : 'On plan'
                    const days = variance === null || variance === undefined ? '' : ` ${Math.abs(Number(variance)).toFixed(3)} d`
                    return `${label}${days} · ${data?.timeline_review_state ?? 'suggested'}`
                  },
                },
                {
                  field: 'classification_evidence',
                  headerName: 'Evidence',
                  minWidth: 220,
                  tooltipField: 'classification_evidence',
                },
                { field: 'review_state', headerName: 'Review', minWidth: 105 },
                {
                  headerName: 'Actions',
                  minWidth: 150,
                  width: 160,
                  sortable: false,
                  cellRenderer: ({ data: b }: { data: Block }) => (
                    <>
                      <Button size="small" onClick={() => setEditor({ ...b })}>
                        {editable ? 'Edit' : 'Inspect'}
                      </Button>
                      {editable && (
                        <Button size="small" color="error" onClick={() => setRemove(b)}>
                          Remove
                        </Button>
                      )}
                    </>
                  ),
                },
              ]}
            />
          </SectionCard>
        )}

        {tab === 'details' && (
          <Box display="grid" gap={2} gridTemplateColumns={{ xs: 'minmax(0,1fr)', lg: 'minmax(0,3fr) minmax(0,2fr)' }}>
            <Stack spacing={2}>
              <SectionCard
                title="Depths (MD & TVD) & Drilling Performance"
                subtitle="All depths stored in metres (source ft automatically converted on extraction). Edit any prefilled value before saving."
              >
                <Box display="grid" gridTemplateColumns={{ xs: '1fr', sm: 'repeat(3,minmax(0,1fr))' }} gap={1.5}>
                  {numField('depth_start_m', 'Starting MD (m)')}
                  {numField('depth_end_m', 'Closing MD (m)')}
                  {numField('progress_m', 'Daily progress (m)')}
                  {numField('tvd_start_m', 'Starting TVD (m)')}
                  {numField(
                    'tvd_m',
                    'Closing TVD (m)',
                    report.tvd_source ? `Basis: ${report.tvd_source}` : undefined,
                  )}
                  {numField('bit_depth_m', 'Bit depth (m)')}
                  {numField('md_auth_m', 'Authorized TD MD (m)')}
                  {numField('rotating_hours', 'Rotating hours (h)')}
                  {numField('cum_rotating_hours', 'Cum. rotating hours (h)')}
                  <TextField
                    size="small"
                    type="date"
                    label="Spud date"
                    slotProps={{ inputLabel: { shrink: true } }}
                    disabled={!editable}
                    value={h('spud_date') ?? ''}
                    onChange={(e) => updateHeader({ spud_date: e.target.value || null })}
                  />
                  {numField('dfs_days', 'Days from spud (DFS)')}
                  {numField('est_days', 'Authorized / est. days')}
                  {numField('day_number', 'Day number')}
                  {textField('datum', 'Depth datum (e.g. RKB/RT)')}
                  {numField('pob_count', 'Personnel on board (POB)')}
                </Box>
              </SectionCard>

              <SectionCard
                title="Wellbore, Casing, Drilling Fluid & BHA"
                subtitle="Prefilled from OpenWells casing/section/fluid/BHA blocks and DMR/Summary sheets."
              >
                <Box display="grid" gridTemplateColumns={{ xs: '1fr', sm: 'repeat(3,minmax(0,1fr))' }} gap={1.5}>
                  {textField('hole_section_text', 'Hole section')}
                  {numField('hole_size_in', 'Hole size (in)')}
                  {numField('last_casing_size_in', 'Last casing OD (in)')}
                  {numField('last_casing_depth_m', 'Last casing shoe MD (m)')}
                  {textField('mud_type', 'Mud / fluid type')}
                  {numField('mud_weight_ppg', 'Mud weight (ppg)')}
                  {numField('mud_viscosity_sec', 'Funnel viscosity (s/qt)')}
                  {numField('mud_pv_cp', 'Plastic viscosity PV (cP)')}
                  {numField('mud_yp_lbf', 'Yield point YP (lbf/100ft²)')}
                  {textField('bha_summary', 'BHA / completion string summary', true)}
                  {textField('current_status', 'Current status at report cut-off', true)}
                </Box>
              </SectionCard>

              <SectionCard
                title={`Report Metadata, Period (${WAT_LABEL}) & Engineer Narratives`}
                subtitle="Verify header identifiers, WAT period boundaries, 24-hr operation summary, forecast and HSE notes."
              >
                <Box display="grid" gridTemplateColumns={{ xs: '1fr', sm: '1fr 1fr' }} gap={1.5}>
                  {textField('report_no_text', 'Report no.')}
                  {textField('event_code', 'Event code')}
                  {textField('customer', 'Operator / customer')}
                  {textField('project', 'Project')}
                  {textField('block_text', 'Block / concession')}
                  {textField('site', 'Site / field / well position')}
                  {textField('uwi', 'UWI')}
                  {textField('supervisor', 'Rig supervisor')}
                  {textField('engineer', 'Well engineer')}
                  <Box />
                  {(['period_start_at', 'period_end_at'] as const).map((k) => (
                    <TextField
                      key={k}
                      label={k === 'period_start_at' ? `Period start (${WAT_LABEL})` : `Period end (${WAT_LABEL})`}
                      type="datetime-local"
                      size="small"
                      slotProps={{ inputLabel: { shrink: true } }}
                      disabled={!editable}
                      value={toWatDateTimeInput(h(k) as string)}
                      onChange={(e) => {
                        const iso = fromWatDateTimeInput(e.target.value)
                        if (iso) updateHeader({ [k]: iso })
                      }}
                    />
                  ))}
                  {report.plan_checkpoints.length > 0 && (
                    <TextField
                      sx={{ gridColumn: '1 / -1' }}
                      select
                      size="small"
                      label="Last completed programme activity"
                      value={h('completed_plan_item_id') ?? ''}
                      disabled={!editable}
                      onChange={(e) => updateHeader({ completed_plan_item_id: e.target.value || null })}
                      helperText="Confirm a checkpoint for lead/lag when depth stays constant (e.g. casing, testing or completion work)."
                    >
                      <MenuItem value="">Compare at measured depth</MenuItem>
                      {report.plan_checkpoints.map((c) => (
                        <MenuItem key={c.id} value={c.id}>
                          {c.description}
                        </MenuItem>
                      ))}
                    </TextField>
                  )}
                  {(
                    [
                      ['operation_summary', '24-hour operation summary'],
                      ['forward_plan', '24-hour forecast / planned operations'],
                      ['hse_summary', 'HSE & safety summary'],
                      ['remarks', 'Engineer remarks'],
                    ] as const
                  ).map(([k, l]) => (
                    <TextField
                      key={k}
                      sx={{ gridColumn: '1 / -1' }}
                      label={l}
                      multiline
                      minRows={2}
                      disabled={!editable}
                      value={h(k) ?? ''}
                      onChange={(e) => updateHeader({ [k]: e.target.value })}
                    />
                  ))}
                </Box>
              </SectionCard>
            </Stack>

            <Stack spacing={2}>
              <SectionCard
                title="AI D&C Narrative Generator"
                subtitle="Generate concise, engineering-grade 24-hr operation summary, forecast and HSE text strictly from this report’s saved data using your offline LAN Ollama model (with instant rule-based fallback)."
              >
                <Stack spacing={1.25}>
                  <TextField
                    size="small"
                    label="Optional focus (e.g. highlight casing run, mud conditioning, NPT recovery)"
                    value={narFocus}
                    onChange={(e) => setNarFocus(e.target.value)}
                    disabled={narBusy || dirty}
                  />
                  <Stack direction="row" gap={1} alignItems="center" flexWrap="wrap">
                    <FormControlLabel
                      control={
                        <Switch
                          size="small"
                          checked={narUseAi}
                          onChange={(_, v) => setNarUseAi(v)}
                          disabled={narBusy}
                        />
                      }
                      label={<Typography fontSize={12.5}>Offline AI (Ollama)</Typography>}
                    />
                    <Button
                      variant="contained"
                      size="small"
                      startIcon={
                        narBusy ? <CircularProgress size={13} color="inherit" /> : <AutoAwesomeOutlined fontSize="small" />
                      }
                      disabled={narBusy || dirty || busy}
                      onClick={() => void runNarratives(narUseAi)}
                    >
                      {narBusy ? 'Drafting…' : 'Generate narratives'}
                    </Button>
                  </Stack>
                  {dirty && (
                    <Typography variant="caption" color="text.secondary">
                      Save current edits first so the generator reads your latest measurements and blocks.
                    </Typography>
                  )}
                  {narratives?.ai_error && (
                    <AiStatusAlert
                      message={narratives.ai_error}
                      errorCode={narratives.ai_error_code}
                      model={narratives.ai_model}
                      busy={narBusy}
                      fallbackNote="Rule-based engineer narratives drafted from saved figures are shown below."
                      onRetry={() => void runNarratives(true)}
                    />
                  )}
                  {narratives && (
                    <Box
                      sx={{
                        p: 1.5,
                        borderRadius: 1.5,
                        border: '1px solid',
                        borderColor: 'divider',
                        bgcolor: 'background.default',
                        display: 'grid',
                        gap: 1,
                      }}
                    >
                      <Stack direction="row" gap={1} alignItems="center" flexWrap="wrap">
                        <Chip
                          size="small"
                          color={narratives.ai_used ? 'primary' : 'default'}
                          label={narratives.ai_used ? `Offline AI · ${narratives.ai_model}` : 'Rule-based D&C draft'}
                        />
                        {editable && (
                          <Button size="small" variant="outlined" sx={{ ml: 'auto' }} onClick={applyNarratives}>
                            Apply to draft fields
                          </Button>
                        )}
                      </Stack>
                      {narratives.operation_summary && (
                        <Box>
                          <Typography variant="caption" fontWeight={700} color="text.secondary">
                            24-HR SUMMARY
                          </Typography>
                          <Typography fontSize={12.5}>{narratives.operation_summary}</Typography>
                        </Box>
                      )}
                      {narratives.forward_plan && (
                        <Box>
                          <Typography variant="caption" fontWeight={700} color="text.secondary">
                            24-HR FORECAST
                          </Typography>
                          <Typography fontSize={12.5}>{narratives.forward_plan}</Typography>
                        </Box>
                      )}
                      {narratives.hse_summary && (
                        <Box>
                          <Typography variant="caption" fontWeight={700} color="text.secondary">
                            HSE SUMMARY
                          </Typography>
                          <Typography fontSize={12.5}>{narratives.hse_summary}</Typography>
                        </Box>
                      )}
                      {narratives.engineering_brief && (
                        <>
                          <Divider />
                          <Box>
                            <Typography variant="caption" fontWeight={700} color="text.secondary">
                              ENGINEERING BRIEF
                            </Typography>
                            <Typography fontSize={12.5}>{narratives.engineering_brief}</Typography>
                          </Box>
                        </>
                      )}
                    </Box>
                  )}
                </Stack>
              </SectionCard>

              <SectionCard
                title="Daily brief"
                subtitle={dirty ? 'Based on the last saved draft.' : 'Based on the saved report.'}
              >
                {briefError && <ErrorMessage message={briefError} />}
                <StudyPanel
                  key={report.updated_at}
                  summary={brief}
                  disabled={dirty || busy}
                  runLabel="Generate brief"
                  run={(useAi) => reviewBrief(report.id, useAi, includeDeleted)}
                />
              </SectionCard>
            </Stack>
          </Box>
        )}

        {tab === 'sources' && (
          <Stack spacing={2}>
            <SectionCard
              title="Source documents & extraction notes"
              action={
                <Stack direction="row" gap={1} flexWrap="wrap">
                  {editable && (report.source_document_id || report.sources.length > 0) && (
                    <Button
                      variant="outlined"
                      size="small"
                      startIcon={prefillBusy ? <CircularProgress size={13} /> : <AutoAwesomeOutlined fontSize="small" />}
                      disabled={dirty || busy || prefillBusy}
                      onClick={() => void runAiPrefill()}
                    >
                      {prefillBusy ? 'Refining…' : 'AI Prefill from Source'}
                    </Button>
                  )}
                  {editable && report.status === 'draft' && can('ops-doc:read') && can('ops-doc:extract') && (
                    <Button variant="contained" size="small" disabled={dirty || busy} onClick={() => setSource(true)}>
                      Extract PDF / Excel
                    </Button>
                  )}
                </Stack>
              }
            >
              {report.sources.length ? (
                <Stack direction="row" gap={1} flexWrap="wrap" mb={report.extraction_notes ? 1 : 0}>
                  {report.sources.map((s) =>
                    can('ops-doc:download') ? (
                      <Button
                        key={s.id}
                        variant="outlined"
                        size="small"
                        onClick={() =>
                          downloadFile(`/operations/documents/${s.id}/download`, s.file_name).catch((e) =>
                            setError((e as Error).message),
                          )
                        }
                      >
                        {s.file_name}
                      </Button>
                    ) : (
                      <Typography key={s.id}>{s.file_name}</Typography>
                    ),
                  )}
                </Stack>
              ) : (
                <Typography variant="body2">
                  {report.source_document_id ? 'Previously filed source' : 'Manual entry · no source attached'}
                </Typography>
              )}
              {report.extraction_notes && (
                <Typography whiteSpace="pre-line" variant="body2" color="text.secondary" sx={{ mt: 1 }}>
                  {report.extraction_notes}
                </Typography>
              )}
            </SectionCard>

            <SectionCard
              title="Directional survey stations"
              subtitle="Reported MD, TVD, inclination, azimuth, offsets and dogleg severity relative to the survey datum. Blank means unrecorded, never zero."
              action={
                editable && (
                  <Button
                    size="small"
                    variant="outlined"
                    onClick={() => {
                      setSurveys([...surveys, newSurvey()])
                      setDirty(true)
                    }}
                  >
                    Add station
                  </Button>
                )
              }
            >
              {!surveys.length && <Typography variant="body2">No survey measurements reported.</Typography>}
              {surveys.map((s, i) => (
                <Box key={i} display="flex" gap={1} alignItems="center" flexWrap="wrap" mb={1.25}>
                  <Typography variant="body2" sx={{ minWidth: 110, fontWeight: 600 }}>
                    Station {i + 1} · {s.tool || s.source}
                  </Typography>
                  {(Object.keys(surveyFields) as (keyof typeof surveyFields)[]).map((k) => (
                    <TextField
                      size="small"
                      key={k}
                      sx={{ width: 132 }}
                      label={surveyFields[k]}
                      value={s[k] ?? ''}
                      disabled={!editable}
                      onChange={(e) => {
                        setDirty(true)
                        setSurveys(surveys.map((x, j) => (j === i ? { ...x, [k]: e.target.value || null } : x)))
                      }}
                    />
                  ))}
                  {editable && (
                    <Button
                      size="small"
                      color="error"
                      onClick={() => {
                        setSurveys(surveys.filter((_, j) => i !== j))
                        setDirty(true)
                      }}
                    >
                      Remove
                    </Button>
                  )}
                </Box>
              ))}
            </SectionCard>
          </Stack>
        )}

        {source && ref && (
          <SourceDialog
            extract
            reference={ref}
            report={report}
            initial={{ well_id: report.well_id, scope: report.scope }}
            onClose={() => setSource(false)}
            onSaved={(r) => {
              if (r) {
                reset(r)
                void refreshBrief()
                void onChanged()
                setTab('log')
              }
              setSource(false)
            }}
          />
        )}

        <BulkAssignDialog
          open={bulkOpen}
          reference={ref}
          reportIds={report ? [report.id] : []}
          blocks={(selected.length ? selected : blocks) as unknown as OpsBlock[]}
          onClose={() => setBulkOpen(false)}
          onApplied={() => {
            void load()
            void onChanged()
          }}
        />

        <FormDialog
          open={timelineReview.open}
          title="Review the timeline comparison"
          subtitle="The system compares this day with the active programme. Accept it, or mark your own lead or lag with a note. A reviewed comparison is kept through later recalculations."
          onClose={() => setTimelineReview({ ...timelineReview, open: false })}
          onSubmit={async () => {
            if (!report) return
            setBusy(true)
            setError('')
            try {
              await opsReviewTimeline(report.id, {
                review_state: timelineReview.state,
                note: timelineNote.trim(),
                block_ids: (selected.length ? selected : blocks).map((b) => b.id),
              })
              setTimelineReview({ ...timelineReview, open: false })
              await load()
              setNotice('Timeline comparison reviewed.')
            } catch (e) {
              setError((e as Error).message)
            } finally {
              setBusy(false)
            }
          }}
          submitLabel="Save review"
          busy={busy}
          submitDisabled={timelineReview.state === 'edited' && !timelineNote.trim()}
          maxWidth="sm"
        >
          <Stack spacing={2} pt={0.5}>
            {error && <Alert severity="error">{error}</Alert>}
            <TextField
              select
              label="Decision"
              value={timelineReview.state}
              onChange={(e) =>
                setTimelineReview({ ...timelineReview, state: e.target.value as typeof timelineReview.state })
              }
            >
              <MenuItem value="accepted">Accept the system comparison</MenuItem>
              <MenuItem value="edited">Edit the comparison myself</MenuItem>
              <MenuItem value="rejected">Reject the comparison</MenuItem>
            </TextField>
            <TextField
              label="Note"
              value={timelineNote}
              onChange={(e) => setTimelineNote(e.target.value)}
              multiline
              minRows={2}
              required={timelineReview.state === 'edited'}
              helperText="Required when you edit the comparison; recorded in the Audit Log."
            />
            <Typography variant="caption" color="text.secondary">
              {(selected.length ? selected : blocks).length} block(s) will be marked{' '}
              {timelineReview.state}. A positive number is a lead ahead of plan; a negative number is a lag
              behind it.
            </Typography>
          </Stack>
        </FormDialog>

        {editor && (
          <FormDialog
            open
            title={`Activity block ${editor.sequence_no}`}
            subtitle={`Duration: ${duration > 0 ? `${duration} min (${(duration / 60).toFixed(2)} h)` : 'Invalid range'} · Timestamps in ${WAT_LABEL}`}
            maxWidth={false}
            dirty={editorDirty}
            onClose={() => setEditor(null)}
            onSubmit={editable ? apply : () => setEditor(null)}
            submitLabel={editable ? 'Apply to draft' : 'Done'}
            submitDisabled={editable && !(duration > 0 && duration <= 1440)}
          >
            <Box display="grid" gridTemplateColumns={{ xs: '1fr', sm: '1fr 1fr', md: 'repeat(3,minmax(0,1fr))' }} gap={2} pt={1}>
              {(['started_at', 'ended_at'] as const).map((k) => (
                <TextField
                  key={k}
                  type="datetime-local"
                  slotProps={{ inputLabel: { shrink: true } }}
                  label={k === 'started_at' ? `From (${WAT_LABEL})` : `To (${WAT_LABEL})`}
                  disabled={!editable}
                  value={toWatDateTimeInput(editor[k])}
                  onChange={(e) =>
                    setEditor({
                      ...editor,
                      [k]: fromWatDateTimeInput(e.target.value) ?? '',
                    })
                  }
                />
              ))}
              <TextField
                select
                label="Classification"
                disabled={!editable}
                value={editor.classification}
                onChange={(e) => {
                  const c = e.target.value as Block['classification']
                  setEditor({
                    ...editor,
                    classification: c,
                    classification_source: 'reviewer',
                    allocation: c === 'Planned' ? 'PT' : c,
                    is_productive: c !== 'NPT',
                  })
                }}
              >
                {['Planned', 'UPA', 'NPT'].map((c) => (
                  <MenuItem key={c} value={c}>
                    {c}
                  </MenuItem>
                ))}
              </TextField>
              <TextField
                select
                label="Allocation"
                disabled={!editable}
                value={editor.allocation}
                onChange={(e) =>
                  setEditor({
                    ...editor,
                    allocation: e.target.value as Block['allocation'],
                    is_productive: e.target.value === 'NPT' ? false : editor.is_productive,
                  })
                }
              >
                {['PT', 'NPT', 'UPA', 'SP'].map((c) => (
                  <MenuItem key={c} value={c}>
                    {c}
                  </MenuItem>
                ))}
              </TextField>
              <TextField
                select
                label="Operation code"
                value={editor.operation_code_id ?? ''}
                disabled={!editable}
                onChange={(e) => {
                  const nextOp = e.target.value || null
                  let next = { ...editor, operation_code_id: nextOp }
                  if (nextOp && ref?.code_links?.length) {
                    const hits = ref.code_links.filter(
                      (l) => l.is_active && (!l.scope || l.scope === report.scope) && l.operation_code_id === nextOp,
                    )
                    const unique = <K extends keyof (typeof hits)[number]>(k: K) => {
                      const vals = Array.from(new Set(hits.map((h) => h[k]).filter(Boolean)))
                      return vals.length === 1 ? (vals[0] as string) : null
                    }
                    if (!next.activity_code_id) next = { ...next, activity_code_id: unique('activity_code_id') }
                    if (!next.phase_raw) {
                      const pl = unique('phase_label')
                      if (pl) next = { ...next, phase_raw: pl.split(' — ')[0].trim() }
                    }
                    if (next.classification === 'NPT' && !next.npt_code_id) {
                      next = { ...next, npt_code_id: unique('npt_code_id') }
                    }
                    if ((next.classification === 'NPT' || next.classification === 'UPA') && !next.cause_code) {
                      const cc = unique('cause_code')
                      if (cc) next = { ...next, cause_code: cc }
                    }
                  }
                  setEditor(next)
                }}
              >
                <MenuItem value="">Not assigned</MenuItem>
                {ref?.operation_codes.map((c) => (
                  <MenuItem key={c.id} value={c.id}>
                    {c.operation_name} ({c.operation_code})
                  </MenuItem>
                ))}
              </TextField>
              <TextField
                select
                label="Activity code"
                value={editor.activity_code_id ?? ''}
                disabled={!editable}
                onChange={(e) => {
                  const nextAct = e.target.value || null
                  let next = { ...editor, activity_code_id: nextAct }
                  if (nextAct && ref?.code_links?.length) {
                    const hits = ref.code_links.filter(
                      (l) =>
                        l.is_active &&
                        (!l.scope || l.scope === report.scope) &&
                        l.activity_code_id === nextAct &&
                        (!next.operation_code_id || !l.operation_code_id || l.operation_code_id === next.operation_code_id),
                    )
                    const ops = Array.from(new Set(hits.map((h) => h.operation_code_id).filter(Boolean)))
                    if (!next.operation_code_id && ops.length === 1) next = { ...next, operation_code_id: ops[0] as string }
                  }
                  setEditor(next)
                }}
              >
                <MenuItem value="">Not assigned</MenuItem>
                {ref?.activity_codes.map((c) => (
                  <MenuItem key={c.id} value={c.id}>
                    {c.activity_name} ({c.activity_code})
                  </MenuItem>
                ))}
              </TextField>
              <TextField
                select
                label="NPT code"
                disabled={!editable}
                value={editor.npt_code_id ?? ''}
                onChange={(e) => {
                  const nextNpt = e.target.value || null
                  let next = { ...editor, npt_code_id: nextNpt }
                  if (nextNpt && ref?.code_links?.length) {
                    const hits = ref.code_links.filter(
                      (l) => l.is_active && (!l.scope || l.scope === report.scope) && l.npt_code_id === nextNpt,
                    )
                    const causes = Array.from(new Set(hits.map((h) => h.cause_code).filter(Boolean)))
                    if (!next.cause_code && causes.length === 1) next = { ...next, cause_code: causes[0] }
                    const agencies = Array.from(new Set(hits.map((h) => h.agency_id).filter(Boolean)))
                    if (!next.vendor_id && !next.agency_id && agencies.length === 1) {
                      const ag = hits.find((h) => h.agency_id === agencies[0])
                      next = {
                        ...next,
                        agency_id: agencies[0] as string,
                        responsible_party: next.responsible_party || ag?.agency_name || '',
                      }
                    }
                  }
                  setEditor(next)
                }}
              >
                <MenuItem value="">Not assigned</MenuItem>
                {ref?.npt_codes.map((n) => (
                  <MenuItem key={n.id} value={n.id}>
                    {n.npt_name} ({n.npt_code})
                  </MenuItem>
                ))}
              </TextField>
              <TextField
                select
                label="Cause"
                value={editor.cause_code}
                disabled={!editable}
                onChange={(e) => setEditor({ ...editor, cause_code: e.target.value })}
              >
                <MenuItem value="">Not assigned</MenuItem>
                {editor.cause_code && !ref?.causes.some((c) => c.cause_code === editor.cause_code) && (
                  <MenuItem value={editor.cause_code}>{editor.cause_code} (source)</MenuItem>
                )}
                {ref?.causes.map((c) => (
                  <MenuItem key={c.id} value={c.cause_code}>
                    {c.cause_name} ({c.cause_code})
                  </MenuItem>
                ))}
              </TextField>
              <TextField
                select
                label="Agency / service vendor"
                disabled={!editable}
                value={editor.vendor_id ?? ''}
                onChange={(e) => {
                  const v = ref?.vendors.find((item) => item.id === e.target.value)
                  setEditor({
                    ...editor,
                    vendor_id: v?.id ?? null,
                    responsible_party: v?.vendor_name ?? editor.responsible_party,
                    agency_id: null,
                  })
                }}
              >
                <MenuItem value="">Custom / not linked</MenuItem>
                {ref?.vendors.map((v) => (
                  <MenuItem key={v.id} value={v.id}>
                    {v.vendor_name} ({v.vendor_code})
                  </MenuItem>
                ))}
              </TextField>
              <TextField
                label="Responsible agency label"
                disabled={!editable}
                value={editor.responsible_party}
                onChange={(e) => setEditor({ ...editor, responsible_party: e.target.value })}
              />
              <Autocomplete
                freeSolo
                disabled={!editable}
                options={(ref?.phase_codes ?? []).map((c) => c.phase_code)}
                value={editor.phase_raw}
                onInputChange={(_, val) => setEditor((b) => (b ? { ...b, phase_raw: val } : b))}
                renderOption={(props, val) => (
                  <li {...props} key={val}>
                    {ref?.phase_codes.find((c) => c.phase_code === val)?.phase_name} ({val})
                  </li>
                )}
                renderInput={(params) => <TextField {...params} label="Source phase" />}
              />
              <FormControlLabel
                label="Productive time"
                control={
                  <Checkbox
                    disabled={!editable || editor.classification === 'NPT' || editor.allocation === 'NPT'}
                    checked={editor.is_productive}
                    onChange={(e) => setEditor({ ...editor, is_productive: e.target.checked })}
                  />
                }
              />
              {(
                [
                  ['depth_from_m', 'From MD (m)'],
                  ['depth_to_m', 'To MD (m)'],
                  ['tvd_from_m', 'From TVD (m)'],
                  ['tvd_to_m', 'To TVD (m)'],
                  ['bit_depth_m', 'Bit depth (m)'],
                  ['mud_weight_ppg', 'Mud weight (ppg)'],
                  ['footage_m', 'Footage (m)'],
                  ['rotating_hours', 'Rotating hours (h)'],
                  ['rop_m_per_hr', 'ROP (m/hr)'],
                ] as const
              ).map(([k, l]) => {
                const ropNa = k === 'rop_m_per_hr' && report.scope === 'completion'
                return (
                  <TextField
                    key={k}
                    label={l}
                    disabled={!editable || ropNa}
                    value={ropNa ? 'N/A' : (editor[k] ?? '')}
                    onChange={(e) => {
                      if (!ropNa) setEditor({ ...editor, [k]: e.target.value || null })
                    }}
                  />
                )
              })}
              <TextField
                sx={{ gridColumn: '1 / -1' }}
                label="NPT / delay reason"
                disabled={!editable}
                value={editor.reason}
                onChange={(e) => setEditor({ ...editor, reason: e.target.value })}
              />
              <TextField
                label="Activity narrative"
                multiline
                minRows={3}
                sx={{ gridColumn: '1 / -1' }}
                disabled={!editable}
                value={editor.narrative}
                onChange={(e) => setEditor({ ...editor, narrative: e.target.value })}
              />
              {[
                ['Activity', editor.source_activity_label],
                ['Phase', editor.source_phase_label],
                ['Operation', editor.source_operation_label],
                ['Mark', editor.source_mark_label],
                ['Cause', editor.source_cause_label],
              ].some(([, value]) => value) && (
                <Typography variant="body2" sx={{ gridColumn: '1 / -1' }}>
                  Printed codes:{' '}
                  {[
                    editor.source_activity_label,
                    editor.source_phase_label,
                    editor.source_operation_label,
                    editor.source_mark_label,
                    editor.source_cause_label,
                  ]
                    .filter(Boolean)
                    .join(' · ')}
                </Typography>
              )}
              <Typography variant="body2" color="text.secondary" sx={{ gridColumn: '1 / -1' }}>
                Source: {editor.source_bbox || 'Manual entry'} ·{' '}
                {editor.classification_evidence || editor.classification_source} · Confidence{' '}
                {Number(editor.confidence).toFixed(3)}
              </Typography>
            </Box>
          </FormDialog>
        )}

        {remove && (
          <FormDialog
            open
            danger
            title={`Remove block ${remove.sequence_no} from this draft?`}
            onClose={() => setRemove(null)}
            submitLabel="Remove"
            onSubmit={() => {
              setBlocks(blocks.filter((b) => b.id !== remove.id).map((b, i) => ({ ...b, sequence_no: i + 1 })))
              setRemove(null)
              setDirty(true)
            }}
          >
            The stored log will change only when you save.
          </FormDialog>
        )}

        {reject && (
          <FormDialog
            open
            title="Return report for correction"
            onClose={() => setReject(false)}
            submitLabel="Reject"
            busy={busy}
            submitDisabled={!reason.trim()}
            onSubmit={() => void transition('reject')}
          >
            <TextField fullWidth label="Reason" value={reason} onChange={(e) => setReason(e.target.value)} />
            {error && <ErrorMessage message={error} />}
          </FormDialog>
        )}

        {reopenOpen && (
          <FormDialog
            open
            title={`Reopen ${report.report_type} ${report.report_no_text} (${report.report_date})?`}
            subtitle="Moves this submitted or approved daily report back to editable draft so you can revise measurements, MD/TVD depths, time blocks, surveys or narratives, then save and re-submit. Reports older than 30 days require ops-report:amend. Logged permanently in the Audit Log."
            onClose={() => setReopenOpen(false)}
            submitLabel="Reopen as draft"
            busyLabel="Reopening…"
            busy={busy}
            submitDisabled={reopenRemarks.trim().length < 3}
            onSubmit={() => void transition('reopen')}
            maxWidth="sm"
          >
            <Box display="grid" gap={2} pt={1}>
              <TextField
                required
                fullWidth
                multiline
                minRows={3}
                label="Reason for reopening (audit log)"
                value={reopenRemarks}
                onChange={(e) => setReopenRemarks(e.target.value)}
                slotProps={{ htmlInput: { maxLength: 500 } }}
                helperText="Minimum 3 characters. Describe the correction or update required."
              />
              {error && <ErrorMessage message={error} />}
            </Box>
          </FormDialog>
        )}
      </PanelDialog>
      {guard}
    </>
  )
}
