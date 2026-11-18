import { useEffect, useState } from 'react'
import {
  Alert,
  Autocomplete,
  Box,
  Button,
  Checkbox,
  Chip,
  FormControlLabel,
  MenuItem,
  Tab,
  Tabs,
  TextField,
  Typography,
} from '@mui/material'
import { ErrorMessage, FormDialog, PanelDialog, useFormDirty, useUnsavedChangesGuard } from '../../components/Common'
import { DataTable } from '../../components/DataTable'
import { SectionCard } from '../../components/ui/SectionCard'
import { printDailyReport } from '../../lib/operationsPdf'
import { StudyPanel } from '../../components/operations/StudyPanel'
import { SourceDialog } from '../../components/operations/SourceDialog'
import { useAuth } from '../../context/AuthContext'
import { downloadFile } from '../../lib/api'
import {
  approveReport,
  auditExport,
  getBrief,
  getReport,
  opsReference,
  rejectReport,
  reviewBrief,
  saveReport,
  submitReport,
  type OpsBlock,
  type OpsReference,
  type OpsReport,
  type OpsSurvey,
} from '../../lib/operations'

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
  'bit_depth_m',
  'rotating_hours',
  'rop_basis',
  'vendor_id',
  'responsible_party',
  'reason',
  'narrative',
  'confidence',
  'review_state',
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
> & { id: string }
const utc = (s: string) => (/[Zz]|[+-]\d\d:\d\d$/.test(s) ? s : `${s}Z`)
const dateInput = (s: string | null | undefined) => (s ? new Date(utc(s)).toISOString().slice(0, 16) : '')
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
  const [report, setReport] = useState<OpsReport | null>(null),
    [ref, setRef] = useState<OpsReference | null>(null),
    [brief, setBrief] = useState(''),
    [briefError, setBriefError] = useState('')
  const [header, setHeader] = useState<Partial<OpsReport>>({}),
    [blocks, setBlocks] = useState<Block[]>([]),
    [surveys, setSurveys] = useState<OpsSurvey[]>([])
  const [dirty, setDirty] = useState(false),
    [busy, setBusy] = useState(false),
    [error, setError] = useState(''),
    [notice, setNotice] = useState('')
  const [editor, setEditor] = useState<Block | null>(null),
    [remove, setRemove] = useState<Block | null>(null),
    [source, setSource] = useState(false),
    [reject, setReject] = useState(false),
    [reason, setReason] = useState('')
  const [confirmed, setConfirmed] = useState(false)
  const editorDirty = useFormDirty(editor, Boolean(editor))
  const reset = (r: OpsReport) => {
    setConfirmed(false)
    setReport(r)
    setHeader({})
    setBlocks(r.blocks)
    setSurveys(r.surveys)
    setDirty(false)
  }
  useEffect(() => {
    let current = true
    setError('')
    setBrief('')
    setBriefError('')
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
          if (current) setError(e.message)
        })
    void getBrief(id, includeDeleted)
      .then((b) => {
        if (current) setBrief(b.summary)
      })
      .catch((e) => {
        if (current) setBriefError(e.message)
      })
    return () => {
      current = false
    }
  }, [id, includeDeleted])
  const refreshBrief = () => {
    setBriefError('')
    return getBrief(id, includeDeleted)
      .then((b) => setBrief(b.summary))
      .catch((e) => setBriefError(e.message))
  }
  const editable =
    !!report &&
    !report.is_deleted &&
    ['draft', 'in_review', 'rejected'].includes(report.status) &&
    can('ops-report:update')
  const updateHeader = (patch: Partial<OpsReport>) => {
    setDirty(true)
    setHeader({ ...header, ...patch })
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
          ? 'Draft saved. Source review is still required.'
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
  const transition = async (action: 'submit' | 'approve' | 'reject') => {
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
            : await rejectReport(report.id, reason)
      reset(r)
      void onChanged()
      void refreshBrief()
      setReject(false)
      setNotice(`Report ${r.status}.`)
    } catch (e) {
      setError((e as Error).message)
    } finally {
      setBusy(false)
    }
  }
  const h = (field: keyof OpsReport) => (field in header ? header[field] : report?.[field])
  const addBlock = () => {
    const start = blocks.at(-1)?.ended_at ?? report?.period_start_at
    if (!start) return
    setEditor({
      id: `new-${Date.now()}`,
      sequence_no: blocks.length + 1,
      started_at: utc(start),
      ended_at: new Date(Date.parse(utc(start)) + 3600000).toISOString(),
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
      bit_depth_m: null,
      rotating_hours: null,
      rop_basis: 'rotating',
      vendor_id: null,
      responsible_party: '',
      reason: '',
      narrative: '',
      confidence: '1',
      review_state: 'edited',
    })
  }
  const duration = editor
    ? Math.round((Date.parse(utc(editor.ended_at)) - Date.parse(utc(editor.started_at))) / 60000)
    : 0
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
  return (
    <>
      <PanelDialog
        open
        maxWidth={false}
        onClose={() => onClose(report)}
        title={`${report.is_deleted ? 'Deleted daily report' : report.extraction_status === 'needs_review' ? 'Review extracted report' : 'Daily report'} · ${report.well_code_snapshot} · ${report.report_date}`}
        subtitle={`${report.rig_code_snapshot} / ${report.scope} · ${report.report_type} ${report.report_no_text} · ${report.status}`}
        footer={
          <Box display="flex" gap={1} alignItems="center" flexWrap="wrap" width="100%" justifyContent="flex-end">
            <Button onClick={() => onClose(report)} disabled={busy} color="inherit">
              {editable ? 'Cancel' : 'Close'}
            </Button>
            {can('ops-report:print') && (
              <Button onClick={print} disabled={busy || dirty}>
                Report PDF
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
        {error && <ErrorMessage message={error} />}
        {notice && <Alert severity="success">{notice}</Alert>}
        {report.status === 'rejected' && (
          <Alert severity="warning">Returned for correction: {report.rejection_reason}</Alert>
        )}
        {report.is_deleted && (
          <Alert severity="info">This report is read-only. Restore it from the register before making changes.</Alert>
        )}
        {!report.is_deleted && report.extraction_status === 'needs_review' && (
          <Alert severity="info">
            These are suggestions. Check the dates, measurements and time classifications, then save the reviewed draft.
          </Alert>
        )}
        {editable && report.current_extraction_id && can('ops-report:review') && (
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
            label="I checked the source, scope, measurements and time allocations. Accept the remaining suggestions when I save."
          />
        )}
        <Tabs value={tab} onChange={(_, v) => setTab(v)} aria-label="Report editor sections" sx={{ mb: 1.5 }}>
          <Tab value="log" label="Activity log" />
          <Tab value="details" label="Brief & report details" />
          <Tab value="sources" label="Sources & surveys" />
        </Tabs>
        {tab === 'log' && (
          <SectionCard
            title="Activity log"
            subtitle="Times are UTC. Durations are calculated from the entered times."
            action={editable && <Button onClick={addBlock}>Add block</Button>}
          >
            <Box display="flex" alignItems="center" gap={1} flexWrap="wrap" mb={1.5}>
              {Object.entries(totals).map(([k, v]) => (
                <Chip key={k} label={`${k}: ${(v / 60).toFixed(3)} h · ${(v / 1440).toFixed(3)} d`} />
              ))}
              <Chip
                label={`Productive ${(blocks.reduce((n, b) => n + (b.is_productive ? b.duration_minutes : 0), 0) / 60).toFixed(3)} h · Nonproductive ${(blocks.reduce((n, b) => n + (b.is_productive ? 0 : b.duration_minutes), 0) / 60).toFixed(3)} h`}
              />
              <Chip label={`Period balance: ${gap} min`} />
            </Box>
            <DataTable
              rows={blocks}
              canExport={can('ops-report:export')}
              exportName={`${report.well_code_snapshot}-${report.report_date}-activities`}
              onExport={auditExport('reports')}
              columns={[
                {
                  field: 'started_at',
                  headerName: 'From (UTC)',
                  valueFormatter: (p) => dateInput(p.value).replace('T', ' '),
                },
                {
                  field: 'ended_at',
                  headerName: 'To (UTC)',
                  valueFormatter: (p) => dateInput(p.value).replace('T', ' '),
                },
                { field: 'duration_minutes', headerName: 'Minutes' },
                { field: 'narrative', headerName: 'Operation', minWidth: 260, tooltipField: 'narrative' },
                { field: 'source_phase_label', headerName: 'Phase', minWidth: 165, tooltipField: 'source_phase_label' },
                {
                  field: 'source_activity_label',
                  headerName: 'Activity code',
                  minWidth: 220,
                  tooltipField: 'source_activity_label',
                  valueGetter: ({ data }) => {
                    const workspace = ref?.activity_codes.find((c) => c.id === data?.activity_code_id)
                    return workspace
                      ? `${workspace.activity_code} — ${workspace.activity_name}`
                      : data?.source_activity_label || ''
                  },
                },
                { field: 'classification', headerName: 'Class' },
                { field: 'allocation', headerName: 'Allocation' },
                { field: 'responsible_party', headerName: 'Agency' },
                {
                  field: 'classification_evidence',
                  headerName: 'Evidence',
                  minWidth: 240,
                  tooltipField: 'classification_evidence',
                },
                { field: 'review_state', headerName: 'Review' },
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
            <SectionCard title="Daily measurements & narrative">
              <Box display="grid" gridTemplateColumns={{ xs: '1fr', sm: '1fr 1fr' }} gap={2}>
                {(
                  [
                    ['report_no_text', 'Report no.'],
                    ['site', 'Site / well position'],
                    ['depth_start_m', 'Starting MD (m)'],
                    ['depth_end_m', 'Closing MD (m)'],
                    ['tvd_m', 'TVD (m)'],
                    ['rotating_hours', 'Rotating hours'],
                    ['dfs_days', 'Days from spud'],
                    ['day_number', 'Day number'],
                  ] as const
                ).map(([k, label]) => (
                  <TextField
                    key={k}
                    size="small"
                    label={label}
                    disabled={!editable}
                    value={h(k) ?? ''}
                    onChange={(e) =>
                      updateHeader({
                        [k]:
                          k === 'day_number'
                            ? e.target.value
                              ? Number(e.target.value)
                              : null
                            : e.target.value || (k === 'site' || k === 'report_no_text' ? '' : null),
                      })
                    }
                  />
                ))}
                {report.plan_checkpoints.length > 0 && (
                  <TextField
                    sx={{ gridColumn: '1 / -1' }}
                    select
                    label="Last completed programme activity"
                    value={h('completed_plan_item_id') ?? ''}
                    disabled={!editable}
                    onChange={(e) => updateHeader({ completed_plan_item_id: e.target.value || null })}
                    helperText="Confirm a checkpoint for lead/lag when depth stays constant (e.g. completion work)."
                  >
                    <MenuItem value="">Compare at measured depth</MenuItem>
                    {report.plan_checkpoints.map((c) => (
                      <MenuItem key={c.id} value={c.id}>
                        {c.description}
                      </MenuItem>
                    ))}
                  </TextField>
                )}
                {(['period_start_at', 'period_end_at'] as const).map((k) => (
                  <TextField
                    key={k}
                    label={k === 'period_start_at' ? 'Period start (UTC)' : 'Period end (UTC)'}
                    type="datetime-local"
                    size="small"
                    disabled={!editable}
                    value={dateInput(h(k) as string)}
                    onChange={(e) => {
                      if (e.target.value) updateHeader({ [k]: `${e.target.value}:00Z` })
                    }}
                  />
                ))}
                {(
                  [
                    ['operation_summary', '24-hour summary'],
                    ['forward_plan', 'Forward plan'],
                    ['hse_summary', 'HSE summary'],
                    ['remarks', 'Remarks'],
                  ] as const
                ).map(([k, l]) => (
                  <TextField
                    key={k}
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
          </Box>
        )}
        {tab === 'sources' && (
          <>
            <SectionCard
              title="Source documents"
              action={
                editable &&
                report.status === 'draft' &&
                can('ops-doc:read') &&
                can('ops-doc:extract') && (
                  <Button disabled={dirty || busy} onClick={() => setSource(true)}>
                    Extract PDF / Excel
                  </Button>
                )
              }
            >
              {report.sources.length ? (
                report.sources.map((s) =>
                  can('ops-doc:download') ? (
                    <Button
                      key={s.id}
                      onClick={() =>
                        downloadFile(`/operations/documents/${s.id}/download`, s.file_name).catch((e) =>
                          setError(e.message),
                        )
                      }
                    >
                      {s.file_name}
                    </Button>
                  ) : (
                    <Typography key={s.id}>{s.file_name}</Typography>
                  ),
                )
              ) : (
                <Typography variant="body2">
                  {report.source_document_id ? 'Previously filed source' : 'Manual entry · no source attached'}
                </Typography>
              )}
              {report.extraction_notes && (
                <Typography whiteSpace="pre-line" variant="body2" color="text.secondary">
                  {report.extraction_notes}
                </Typography>
              )}
            </SectionCard>
            <SectionCard
              title="Survey stations"
              subtitle="Reported offsets are relative to the survey datum. A blank value is unknown, not zero."
              action={
                editable && (
                  <Button
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
                <Box key={i} display="flex" gap={1} flexWrap="wrap" mb={1}>
                  <Typography variant="body2">
                    Station {i + 1} · {s.tool || s.source}
                  </Typography>
                  {(Object.keys(surveyFields) as (keyof typeof surveyFields)[]).map((k) => (
                    <TextField
                      size="small"
                      key={k}
                      sx={{ width: 130 }}
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
          </>
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
        {editor && (
          <FormDialog
            open
            title={`Activity block ${editor.sequence_no}`}
            maxWidth={false}
            dirty={editorDirty}
            onClose={() => setEditor(null)}
            onSubmit={editable ? apply : () => setEditor(null)}
            submitLabel={editable ? 'Apply to draft' : 'Done'}
            submitDisabled={editable && !(duration > 0 && duration <= 1440)}
          >
            <Box display="grid" gridTemplateColumns={{ xs: '1fr', sm: '1fr 1fr' }} gap={2} pt={1}>
              {(['started_at', 'ended_at'] as const).map((k) => (
                <TextField
                  key={k}
                  type="datetime-local"
                  label={k === 'started_at' ? 'From (UTC)' : 'To (UTC)'}
                  disabled={!editable}
                  value={dateInput(editor[k])}
                  onChange={(e) => setEditor({ ...editor, [k]: e.target.value ? `${e.target.value}:00Z` : '' })}
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
                label="NPT code"
                disabled={!editable}
                value={editor.npt_code_id ?? ''}
                onChange={(e) => setEditor({ ...editor, npt_code_id: e.target.value || null })}
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
                label="NPT / UPA agency (vendor)"
                disabled={
                  !editable || (editor.classification === 'Planned' && !['UPA', 'NPT'].includes(editor.allocation))
                }
                value={editor.vendor_id ?? ''}
                onChange={(e) => {
                  const v = ref?.vendors.find((v) => v.id === e.target.value)
                  setEditor({
                    ...editor,
                    vendor_id: v?.id ?? null,
                    responsible_party: v?.vendor_name ?? '',
                    agency_id: null,
                  })
                }}
              >
                <MenuItem value="">Not assigned</MenuItem>
                {ref?.vendors.map((v) => (
                  <MenuItem key={v.id} value={v.id}>
                    {v.vendor_name} ({v.vendor_code})
                  </MenuItem>
                ))}
              </TextField>
              <TextField
                select
                label="Operation code"
                value={editor.operation_code_id ?? ''}
                disabled={!editable}
                onChange={(e) => setEditor({ ...editor, operation_code_id: e.target.value || null })}
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
                onChange={(e) => setEditor({ ...editor, activity_code_id: e.target.value || null })}
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
                  ['bit_depth_m', 'Bit depth (m)'],
                  ['rotating_hours', 'Rotating hours'],
                ] as const
              ).map(([k, l]) => (
                <TextField
                  key={k}
                  label={l}
                  disabled={!editable}
                  value={editor[k] ?? ''}
                  onChange={(e) => setEditor({ ...editor, [k]: e.target.value || null })}
                />
              ))}
              <TextField
                label="Reason"
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
              <Typography variant="body2" sx={{ gridColumn: '1 / -1' }}>
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
            onSubmit={() => transition('reject')}
          >
            <TextField fullWidth label="Reason" value={reason} onChange={(e) => setReason(e.target.value)} />
            {error && <ErrorMessage message={error} />}
          </FormDialog>
        )}
      </PanelDialog>
      {guard}
    </>
  )
}
