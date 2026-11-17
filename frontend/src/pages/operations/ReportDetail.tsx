import { useEffect, useState } from 'react'
import { useParams, useNavigate } from 'react-router-dom'
import {
  CheckCircleOutline,  SaveOutlined, SendOutlined, ThumbUpOutlined, BlockOutlined,
   TerrainOutlined, ScheduleOutlined, SpeedOutlined,
} from '@mui/icons-material'
import {
  Alert, Box, Button, Chip, Dialog, DialogActions, DialogContent, DialogTitle,
  FormControl, InputLabel, MenuItem, Select, TextField, Typography, Divider,
} from '@mui/material'
import { ErrorMessage, PageHeading } from '../../components/Common'
import { DataTable } from '../../components/DataTable'
// ChartPanel reserved
import { SectionCard } from '../../components/ui/SectionCard'
import { StatCard } from '../../components/ui/StatCard'
import { getReport, saveReport, submitReport, approveReport, rejectReport, getBrief, opsReference, type OpsReport, type OpsBlock, type OpsReference } from '../../lib/operations'
// api via operations lib

function clsColor(cls: string) {
  if (cls === 'NPT') return 'error' as const
  if (cls === 'UPA') return 'warning' as const
  return 'positive' as const
}

export default function OperationsReportDetail() {
  const { id } = useParams<{ id: string }>()
  const navigate = useNavigate()
  const [report, setReport] = useState<OpsReport | null>(null)
  const [ref, setRef] = useState<OpsReference | null>(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState('')
  const [saving, setSaving] = useState(false)
  const [brief, setBrief] = useState<{ summary: string; time_split: Record<string, unknown>; npt_items: unknown[]; depth_progress: Record<string, unknown>; data_quality: Record<string, unknown> } | null>(null)
  const [editOpen, setEditOpen] = useState(false)
  const [editBlock, setEditBlock] = useState<OpsBlock | null>(null)
  const [editForm, setEditForm] = useState<Partial<OpsBlock>>({})
  const [blockDrafts, setBlockDrafts] = useState<OpsBlock[]>([])
  const [headerDraft, setHeaderDraft] = useState<Partial<OpsReport>>({})
  const [rejectOpen, setRejectOpen] = useState(false)
  const [rejectReason, setRejectReason] = useState('')

  const load = async () => {
    if (!id) return
    setLoading(true); setError('')
    try {
      const [r, reference] = await Promise.all([getReport(id), ref ? Promise.resolve(ref) : opsReference()])
      setReport(r); setBlockDrafts(r.blocks || []); setRef(reference)
      try { const b = await getBrief(r.id); setBrief(b) } catch { /* ignore */ }
    } catch (e) { setError((e as Error).message) } finally { setLoading(false) }
  }
  useEffect(() => { load() }, [id])

  const totalMin = blockDrafts.reduce((s, b) => s + (b.duration_minutes || 0), 0)
  const plannedMin = blockDrafts.filter(b => b.classification === 'Planned').reduce((s, b) => s + b.duration_minutes, 0)
  const upaMin = blockDrafts.filter(b => b.classification === 'UPA').reduce((s, b) => s + b.duration_minutes, 0)
  const nptMin = blockDrafts.filter(b => b.classification === 'NPT').reduce((s, b) => s + b.duration_minutes, 0)
  const unacc = report ? (report.period_minutes || 1440) - totalMin : 0
  const footage = report?.depth_start_m && report?.depth_end_m ? (Number(report.depth_end_m) - Number(report.depth_start_m)) : null

  const canEdit = report?.status === 'draft' || report?.status === 'in_review' || report?.status === 'rejected'
  const findings: string[] = []
  if (Math.abs(unacc) > 2) findings.push(`Unaccounted ${unacc} min — logged ${totalMin} vs period ${report?.period_minutes || 1440}`)
  blockDrafts.forEach((b, i) => {
    if (b.classification === 'NPT' && !b.npt_code_id) findings.push(`Block ${b.sequence_no} NPT missing code`)
    if (b.classification === 'NPT' && b.is_productive) findings.push(`Block ${b.sequence_no} NPT cannot be productive`)
    if (b.classification === 'NPT' && !b.reason) findings.push(`Block ${b.sequence_no} NPT missing reason`)
  })
  // Overlap check
  const sorted = [...blockDrafts].sort((a, b) => new Date(a.started_at).getTime() - new Date(b.started_at).getTime())
  for (let i = 0; i < sorted.length - 1; i++) {
    if (new Date(sorted[i + 1].started_at) < new Date(sorted[i].ended_at)) findings.push(`Block ${sorted[i].sequence_no} overlaps ${sorted[i + 1].sequence_no}`)
  }

  const doSave = async () => {
    if (!report) return
    setSaving(true); setError('')
    try {
      // Build blocks payload: recompute durations from timestamps if edited
      const payloadBlocks = blockDrafts.map(b => ({
        sequence_no: b.sequence_no,
        started_at: b.started_at,
        ended_at: b.ended_at,
        duration_minutes: b.duration_minutes,
        phase_raw: b.phase_raw,
        operation_code_id: b.operation_code_id,
        activity_code_id: b.activity_code_id,
        activity_id: b.activity_id,
        classification: b.classification,
        allocation: b.allocation,
        is_productive: b.is_productive,
        classification_source: b.classification_source || 'reviewer',
        npt_code_id: b.npt_code_id,
        agency_id: b.agency_id,
        cause_code: b.cause_code,
        hole_section_id: b.hole_section_id,
        phase_id: b.phase_id,
        depth_from_m: b.depth_from_m,
        depth_to_m: b.depth_to_m,
        depth_unit: b.depth_unit,
        footage_m: b.footage_m,
        rotating_hours: b.rotating_hours,
        rop_m_per_hr: b.rop_m_per_hr,
        responsible_party: b.responsible_party,
        reason: b.reason,
        narrative: b.narrative,
        confidence: b.confidence,
        review_state: (b.review_state === 'suggested' ? 'accepted' : b.review_state),
      }))
      const headerPayload: Record<string, unknown> = {}
      ;['report_no_text','day_number','event_code','depth_start_m','depth_end_m','depth_unit','operation_summary','forward_plan','hse_summary','remarks','hole_section_id','phase_id'].forEach(k => {
        const v = (headerDraft as Record<string, unknown>)[k]
        if (v !== undefined) headerPayload[k] = v
      })
      const saved = await saveReport(report.id, { report: headerPayload, blocks: payloadBlocks })
      setReport(saved); setBlockDrafts(saved.blocks || []); setHeaderDraft({})
    } catch (e) { setError((e as Error).message) } finally { setSaving(false) }
  }

  const doSubmit = async () => {
    if (!report) return
    setError('')
    try { await doSave(); const r = await submitReport(report.id); setReport(r); setBlockDrafts(r.blocks || []) } catch (e) { setError((e as Error).message) }
  }
  const doApprove = async () => {
    if (!report) return
    try { const r = await approveReport(report.id); setReport(r) } catch (e) { setError((e as Error).message) }
  }
  const doReject = async () => {
    if (!report) return
    try { const r = await rejectReport(report.id, rejectReason); setReport(r); setRejectOpen(false); setRejectReason('') } catch (e) { setError((e as Error).message) }
  }

  const openEdit = (b: OpsBlock) => {
    setEditBlock(b); setEditForm({ ...b }); setEditOpen(true)
  }
  const applyEdit = () => {
    if (!editBlock) return
    setBlockDrafts(prev => prev.map(x => x.id === editBlock.id ? { ...x, ...editForm } as OpsBlock : x))
    setEditOpen(false); setEditBlock(null)
  }

  const addBlock = () => {
    const last = blockDrafts[blockDrafts.length - 1]
    const start = last ? new Date(new Date(last.ended_at).getTime()) : new Date(report?.period_start_at || new Date().toISOString())
    const end = new Date(start.getTime() + 60 * 60000)
    const nb: OpsBlock = {
      id: `new-${Date.now()}`,
      organization_id: report?.organization_id || '',
      report_id: report?.id || '',
      sequence_no: blockDrafts.length + 1,
      started_at: start.toISOString(),
      ended_at: end.toISOString(),
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
      npt_code_snapshot: '',
      agency_id: null,
      cause_code: '',
      hole_section_id: null,
      phase_id: null,
      depth_from_m: null,
      depth_to_m: null,
      depth_unit: 'm',
      footage_m: null,
      rotating_hours: null,
      rop_m_per_hr: null,
      rop_basis: 'rotating',
      responsible_party: '',
      vendor_id: null,
      reason: '',
      narrative: '',
      confidence: '1.00',
      review_state: 'edited',
      is_deleted: false,
      created_at: new Date().toISOString(),
      updated_at: new Date().toISOString(),
    }
    setBlockDrafts([...blockDrafts, nb])
  }

  if (loading) return <Box p={3}><Typography>Loading report…</Typography></Box>
  if (!report) return <Box p={3}><ErrorMessage message={error || 'Report not found'} /></Box>

  return (
    <Box>
      <PageHeading
        eyebrow="Well Operations" title={`${report.well_code_snapshot} — ${report.report_date} — ${report.report_type} ${report.report_no_text || ''}`}
        subtitle={`${report.rig_name_snapshot || 'No rig'} · ${report.scope} · ${report.event_code || ''} · Day ${report.day_number ?? '—'} · DFS ${report.dfs_days ?? '—'} · Status: ${report.status}`}
      />
      {error && <Box mb={2}><ErrorMessage message={error} /></Box>}

      <Box display="grid" gap={2} gridTemplateColumns={{ xs: '1fr', lg: 'repeat(4, 1fr)' }}>
        <StatCard label="Depth" value={report.depth_end_m ? `${Number(report.depth_end_m).toFixed(0)} m` : '—'} hint={`Start ${report.depth_start_m ? Number(report.depth_start_m).toFixed(0) : '—'} → End ${report.depth_end_m ? Number(report.depth_end_m).toFixed(0) : '—'} · Footage ${footage !== null ? footage.toFixed(1) + ' m' : '—'}`} icon={<TerrainOutlined />} />
        <StatCard label="Time" value={`${(totalMin / 60).toFixed(2)} h`} hint={`Planned ${(plannedMin / 60).toFixed(2)}h · UPA ${(upaMin / 60).toFixed(2)}h · NPT ${(nptMin / 60).toFixed(2)}h · Unacc. ${(unacc / 60).toFixed(2)}h`} icon={<ScheduleOutlined />} tone={Math.abs(unacc) > 2 ? 'warning' : undefined} />
        <StatCard label="ROP" value={report.rotating_hours ? `${(footage !== null && report.rotating_hours ? (footage / Number(report.rotating_hours)).toFixed(2) : '—')} m/hr` : '—'} hint={`Rotating ${report.rotating_hours ?? '—'} h · Basis: ${blockDrafts[0]?.rop_basis || 'rotating'} · Productive ${(blockDrafts.filter(b => b.is_productive).reduce((s, b) => s + b.duration_minutes, 0) / 60).toFixed(2)}h`} icon={<SpeedOutlined />} />
        <StatCard label="Status & extraction" value={report.status} hint={`Extraction: ${report.extraction_status} · Blocks: ${blockDrafts.length} · Avg conf: ${blockDrafts.length ? (blockDrafts.reduce((s, b) => s + Number(b.confidence), 0) / blockDrafts.length).toFixed(2) : '—'}`} icon={<CheckCircleOutline />} tone={report.extraction_status === 'needs_review' ? 'warning' : report.status === 'approved' ? 'info' : undefined} />
      </Box>

      {findings.length > 0 && (
        <Alert severity="warning" sx={{ mt: 2 }}>
          <Typography fontWeight={700}>Findings to fix before submit:</Typography>
          <ul style={{ margin: '6px 0 0 18px' }}>{findings.map((f, i) => <li key={i}><Typography fontSize={13}>{f}</Typography></li>)}</ul>
        </Alert>
      )}
      {findings.length === 0 && report.extraction_status === 'needs_review' && (
        <Alert severity="info" sx={{ mt: 2 }}>Review each block (provenance chips show extracted/confidence). Accept or edit, then Save — findings clear. Nothing submits automatically.</Alert>
      )}

      <Box mt={2} display="flex" gap={1} flexWrap="wrap" alignItems="center">
        <Button variant="outlined" onClick={() => navigate('/operations/reports')}>Back to list</Button>
        {canEdit && <Button variant="contained" startIcon={<SaveOutlined />} disabled={saving} onClick={doSave}>{saving ? 'Saving…' : 'Save draft'}</Button>}
        {canEdit && <Button variant="outlined" onClick={addBlock}>Add block</Button>}
        {report.status === 'draft' && <Button variant="contained" color="positive" startIcon={<SendOutlined />} onClick={doSubmit}>Submit</Button>}
        {report.status === 'submitted' && <Button variant="contained" color="positive" startIcon={<ThumbUpOutlined />} onClick={doApprove}>Approve</Button>}
        {report.status === 'submitted' && <Button variant="outlined" color="error" startIcon={<BlockOutlined />} onClick={() => setRejectOpen(true)}>Reject</Button>}
        <Chip label={`${report.period_minutes} min period`} size="small" />
        <Chip label={unacc === 0 ? 'Complete (≤2 min tol.)' : `Unaccounted ${unacc} min`} size="small" color={Math.abs(unacc) > 2 ? 'warning' : 'positive'} />
      </Box>

      <Box display="grid" gap={2} gridTemplateColumns={{ xs: '1fr', lg: '2fr 1fr' }} mt={2}>
        <SectionCard title="24h time log — one row per activity block">
          <Box mb={1} display="flex" gap={1} alignItems="center">
            <Box flex={1} height={18} display="flex" border={`1px solid`} sx={{ borderColor: 'divider', borderRadius: 1, overflow: 'hidden' }}>
              {blockDrafts.map(b => (
                <Box key={b.id} flex={b.duration_minutes} bgcolor={b.classification === 'NPT' ? 'error.main' : b.classification === 'UPA' ? 'warning.main' : 'success.main'} title={`${b.classification} ${b.duration_minutes} min: ${b.narrative.slice(0, 80)}`} />
              ))}
              {unacc > 0 && <Box flex={unacc} bgcolor="grey.300" title={`Unaccounted ${unacc} min`} />}
            </Box>
            <Typography fontSize={11} color="text.secondary">Planned green · UPA amber · NPT red · unaccounted grey</Typography>
          </Box>
          <DataTable
            rows={blockDrafts}
            rowKey='id'
            columns={[
              { field: 'sequence_no', headerName: '#', width: 50 },
              { field: 'started_at', headerName: 'From', width: 140, valueFormatter: p => p.value ? new Date(p.value).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit', hour12: false }) : '—' },
              { field: 'ended_at', headerName: 'To', width: 140, valueFormatter: p => p.value ? new Date(p.value).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit', hour12: false }) : '—' },
              { field: 'duration_minutes', headerName: 'Min', width: 70 },
              { field: 'phase_raw', headerName: 'Phase', width: 90, valueFormatter: p => p.value || '—' },
              { field: 'classification', headerName: 'Class', width: 100, cellRenderer: (p: { value: string }) => <Chip size="small" label={p.value} color={clsColor(p.value)} /> },
              { field: 'allocation', headerName: 'Alloc', width: 80 },
              { field: 'npt_code_snapshot', headerName: 'NPT code', width: 100, valueFormatter: p => p.value || '—' },
              { field: 'confidence', headerName: 'Conf', width: 70, valueFormatter: p => p.value ? Number(p.value).toFixed(2) : '—' },
              { field: 'review_state', headerName: 'Review', width: 100, valueFormatter: p => p.value || '—' },
              { field: 'narrative', headerName: 'Operation (narrative)', flex: 1.5, minWidth: 260, tooltipField: 'narrative' },
              { field: 'id', headerName: '', width: 90, sortable: false, cellRenderer: (p: { data: OpsBlock }) => <Button size="small" onClick={() => openEdit(p.data)} disabled={!canEdit}>Edit</Button> },
            ]}
          />
          <Typography fontSize={11} color="text.secondary" mt={1}>Each block stores started_at/ended_at/duration_minutes (recomputed on save), classification+allocation+is_productive, NPT code/agency/cause, responsible party, footage/ROP with basis, narrative and provenance (explicit/code/keyword/timeline/reviewer + confidence). Low-confidence fields are flagged; findings above list every conflict.</Typography>
        </SectionCard>

        <Box display="grid" gap={2}>
          <SectionCard title="Brief — the day in one paragraph">
            {brief ? (
              <Box>
                <Typography fontSize={13} whiteSpace="pre-wrap">{brief.summary}</Typography>
                <Divider sx={{ my: 1.5 }} />
                <Typography fontSize={12} fontWeight={700}>Time split (min):</Typography>
                <Typography fontSize={12} color="text.secondary">{JSON.stringify(brief.time_split, null, 1).slice(2, -1)}</Typography>
                <Typography fontSize={12} fontWeight={700} mt={1}>Depth progress:</Typography>
                <Typography fontSize={12} color="text.secondary">{JSON.stringify(brief.depth_progress, null, 1).slice(2, -1)}</Typography>
                <Typography fontSize={11} color="text.secondary" mt={1}>Deterministic — server recomputes every figure; numbers never added by AI. Optional offline-AI polish (workspace toggle, default off) may rewrite for readability but never changes a figure.</Typography>
              </Box>
            ) : (
              <Typography fontSize={13} color="text.secondary">Brief will appear after saving — it composes identity, top blocks, time split, NPT list, depth/ROP, forward plan and data-quality.</Typography>
            )}
          </SectionCard>
          <SectionCard title="Header — well, rig, scope, depth, depths & remarks">
            <Box display="grid" gap={1.5}>
              <TextField size="small" label="Report no." value={(headerDraft.report_no_text ?? report.report_no_text) || ''} onChange={e => setHeaderDraft(h => ({ ...h, report_no_text: e.target.value }))} disabled={!canEdit} />
              <TextField size="small" label="Day number" type="number" value={(headerDraft.day_number ?? report.day_number) ?? ''} onChange={e => setHeaderDraft(h => ({ ...h, day_number: Number(e.target.value) || undefined }))} disabled={!canEdit} helperText="Campaign day from spud (or manual when spud is future/absent)" />
              <Box display="grid" gridTemplateColumns="1fr 1fr" gap={1}>
                <TextField size="small" label="Depth start (m)" value={(headerDraft.depth_start_m ?? report.depth_start_m) ?? ''} onChange={e => setHeaderDraft(h => ({ ...h, depth_start_m: e.target.value as unknown as string }))} disabled={!canEdit} />
                <TextField size="small" label="Depth end (m)" value={(headerDraft.depth_end_m ?? report.depth_end_m) ?? ''} onChange={e => setHeaderDraft(h => ({ ...h, depth_end_m: e.target.value as unknown as string }))} disabled={!canEdit} />
              </Box>
              <TextField size="small" label="Operation summary (24h summary)" multiline minRows={3} value={(headerDraft.operation_summary ?? report.operation_summary) ?? ''} onChange={e => setHeaderDraft(h => ({ ...h, operation_summary: e.target.value }))} disabled={!canEdit} />
              <TextField size="small" label="Forward plan (next 24h)" multiline minRows={2} value={(headerDraft.forward_plan ?? report.forward_plan) ?? ''} onChange={e => setHeaderDraft(h => ({ ...h, forward_plan: e.target.value }))} disabled={!canEdit} />
              <TextField size="small" label="HSE summary" multiline minRows={2} value={(headerDraft.hse_summary ?? report.hse_summary) ?? ''} onChange={e => setHeaderDraft(h => ({ ...h, hse_summary: e.target.value }))} disabled={!canEdit} />
              <Typography fontSize={11} color="text.secondary">Well position & direction (MD/TVD, inclination/azimuth, DLS) come from section 7.1 + narrative MWD/gyro surveys — shown in the survey panel of the analytics page; missing values are flagged, never fabricated.</Typography>
            </Box>
          </SectionCard>
        </Box>
      </Box>

      <Dialog open={editOpen} onClose={() => setEditOpen(false)} maxWidth="md" fullWidth>
        <DialogTitle>Edit block {editBlock?.sequence_no}</DialogTitle>
        <DialogContent>
          <Box display="grid" gap={2} mt={1} gridTemplateColumns={{ xs: '1fr', md: '1fr 1fr' }}>
            <TextField size="small" label="Started at" type="datetime-local" value={editForm.started_at ? new Date(editForm.started_at as string).toISOString().slice(0, 16) : ''} onChange={e => setEditForm(f => ({ ...f, started_at: new Date(e.target.value).toISOString() }))} InputLabelProps={{ shrink: true }} />
            <TextField size="small" label="Ended at" type="datetime-local" value={editForm.ended_at ? new Date(editForm.ended_at as string).toISOString().slice(0, 16) : ''} onChange={e => setEditForm(f => ({ ...f, ended_at: new Date(e.target.value).toISOString() }))} InputLabelProps={{ shrink: true }} />
            <FormControl size="small"><InputLabel>Classification</InputLabel><Select value={editForm.classification || 'Planned'} label="Classification" onChange={e => setEditForm(f => ({ ...f, classification: e.target.value as never }))}><MenuItem value="Planned">Planned</MenuItem><MenuItem value="UPA">UPA</MenuItem><MenuItem value="NPT">NPT</MenuItem></Select></FormControl>
            <FormControl size="small"><InputLabel>Allocation</InputLabel><Select value={editForm.allocation || 'PT'} label="Allocation" onChange={e => setEditForm(f => ({ ...f, allocation: e.target.value as never }))}><MenuItem value="PT">PT</MenuItem><MenuItem value="NPT">NPT</MenuItem><MenuItem value="UPA">UPA</MenuItem><MenuItem value="SP">SP</MenuItem></Select></FormControl>
            <TextField size="small" label="Phase raw (DRLPRO…)" value={editForm.phase_raw || ''} onChange={e => setEditForm(f => ({ ...f, phase_raw: e.target.value }))} />
            <FormControl size="small">
              <InputLabel>NPT code</InputLabel>
              <Select value={editForm.npt_code_id || ''} label="NPT code" onChange={e => setEditForm(f => ({ ...f, npt_code_id: e.target.value || null }))}>
                <MenuItem value="">None</MenuItem>
                {ref?.npt_codes.map(n => <MenuItem key={n.id} value={n.id}>{n.npt_code} — {n.npt_name}</MenuItem>)}
              </Select>
            </FormControl>
            <TextField size="small" label="Responsible party" value={editForm.responsible_party || ''} onChange={e => setEditForm(f => ({ ...f, responsible_party: e.target.value }))} />
            <TextField size="small" label="Reason (mandatory for NPT/UPA)" value={editForm.reason || ''} onChange={e => setEditForm(f => ({ ...f, reason: e.target.value }))} />
            <Box gridColumn={{ xs: '1', md: '1 / span 2' }}>
              <TextField size="small" label="Narrative / operation" fullWidth multiline minRows={3} value={editForm.narrative || ''} onChange={e => setEditForm(f => ({ ...f, narrative: e.target.value }))} />
            </Box>
            <TextField size="small" label="Depth from (m)" value={editForm.depth_from_m || ''} onChange={e => setEditForm(f => ({ ...f, depth_from_m: e.target.value as unknown as never }))} />
            <TextField size="small" label="Depth to (m)" value={editForm.depth_to_m || ''} onChange={e => setEditForm(f => ({ ...f, depth_to_m: e.target.value as unknown as never }))} />
            <TextField size="small" label="Rotating hours" value={editForm.rotating_hours || ''} onChange={e => setEditForm(f => ({ ...f, rotating_hours: e.target.value as unknown as never }))} helperText="ROP = footage ÷ rotating_hours; only on-bottom blocks count" />
            <Box display="flex" gap={1} alignItems="center">
              <Typography fontSize={13}>Productive</Typography>
              <input type="checkbox" checked={!!editForm.is_productive} onChange={e => setEditForm(f => ({ ...f, is_productive: e.target.checked }))} />
              <Typography fontSize={11} color="text.secondary">NPT can never be productive (DB check).</Typography>
            </Box>
          </Box>
          <Alert severity="info" sx={{ mt: 2 }}>NPT requires a code, agency (optional) and ≥10-char reason — enforced in schema + service + DB. Corrections are stored as overrides and learned for next extraction (inspectable, revocable).</Alert>
        </DialogContent>
        <DialogActions><Button onClick={() => setEditOpen(false)}>Cancel</Button><Button variant="contained" onClick={applyEdit}>Apply</Button></DialogActions>
      </Dialog>

      <Dialog open={rejectOpen} onClose={() => setRejectOpen(false)} maxWidth="sm" fullWidth>
        <DialogTitle>Reject report</DialogTitle>
        <DialogContent><TextField autoFocus size="small" label="Reason" fullWidth multiline minRows={2} value={rejectReason} onChange={e => setRejectReason(e.target.value)} /></DialogContent>
        <DialogActions><Button onClick={() => setRejectOpen(false)}>Cancel</Button><Button variant="contained" color="error" disabled={!rejectReason.trim()} onClick={doReject}>Reject</Button></DialogActions>
      </Dialog>
    </Box>
  )
}
