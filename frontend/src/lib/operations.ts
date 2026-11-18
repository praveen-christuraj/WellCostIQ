import { api, body, uploadFiles } from './api'

export type Scope = 'drilling' | 'completion'

export type OpsDocument = {
  id: string
  organization_id: string
  well_id: string | null
  rig_id: string | null
  scope: string
  document_type: string
  file_name: string
  content_type: string
  size_bytes: number
  checksum_sha256: string
  document_date: string | null
  report_no_text: string
  status: string
  version_no: number
  well_code_snapshot: string
  well_name_snapshot: string
  rig_code_snapshot: string
  rig_name_snapshot: string
  uploaded_by: string
  uploaded_by_name: string
  notes: string
  is_deleted: boolean
  created_at: string
  updated_at: string
}

export type OpsSurvey = {
  vsec_m: string | null
  dls_deg_per_30m: string | null
  md_m: string | null
  tvd_m: string | null
  inc_deg: string | null
  azi_deg: string | null
  ns_m: string | null
  ew_m: string | null
  tool: string
  source: string
}

export type OpsReport = {
  rejection_reason: string
  baseline_plan_id: string | null
  completed_plan_item_id: string | null
  plan_checkpoints: { id: string; description: string; days: string }[]
  site: string
  extraction_notes: string
  surveys: OpsSurvey[]
  sources: { id: string; file_name: string }[]
  id: string
  organization_id: string
  well_id: string
  rig_id: string | null
  rig_code_snapshot: string
  rig_name_snapshot: string
  well_code_snapshot: string
  well_name_snapshot: string
  scope: string
  report_type: string
  report_date: string
  report_no_text: string
  report_no_seq: number | null
  day_number: number | null
  event_code: string
  period_start_at: string | null
  period_end_at: string | null
  period_minutes: number
  hole_section_id: string | null
  phase_id: string | null
  depth_start_m: string | null
  depth_end_m: string | null
  depth_unit: string
  tvd_m: string | null
  progress_m: string | null
  rotating_hours: string | null
  dfs_days: string | null
  est_days: string | null
  operation_summary: string
  forward_plan: string
  hse_summary: string
  remarks: string
  status: string
  extraction_status: string
  current_extraction_id: string | null
  source_document_id: string | null
  is_current: boolean
  revision_no: number
  is_deleted: boolean
  deleted_at: string | null
  created_at: string
  updated_at: string
  blocks: OpsBlock[]
  unaccounted_minutes: number
  total_block_minutes: number
}

export type OpsBlock = {
  id: string
  organization_id: string
  report_id: string
  sequence_no: number
  started_at: string
  ended_at: string
  duration_minutes: number
  phase_raw: string
  operation_code_id: string | null
  activity_code_id: string | null
  activity_id: string | null
  classification: 'Planned' | 'UPA' | 'NPT'
  allocation: 'PT' | 'NPT' | 'UPA' | 'SP'
  is_productive: boolean
  source_activity_code?: string
  source_activity_label?: string
  source_operation_label?: string
  source_phase_label?: string
  source_mark_label?: string
  source_cause_label?: string
  classification_evidence?: string
  source_page?: number
  source_bbox?: string
  classification_source: string
  npt_code_id: string | null
  npt_code_snapshot: string
  agency_id: string | null
  cause_code: string
  hole_section_id: string | null
  phase_id: string | null
  bit_depth_m: string | null
  depth_from_m: string | null
  depth_to_m: string | null
  depth_unit: string
  footage_m: string | null
  rotating_hours: string | null
  rop_m_per_hr: string | null
  rop_basis: string
  responsible_party: string
  vendor_id: string | null
  reason: string
  narrative: string
  confidence: string
  review_state: string
  is_deleted: boolean
  created_at: string
  updated_at: string
}

export type OpsKpi = {
  productive_hours: number
  nonproductive_hours: number
  allocation_hours: Record<string, number>
  total_reports: number
  draft_reports: number
  submitted_reports: number
  approved_reports: number
  reports_awaiting_review: number
  total_logged_hours: number
  planned_hours: number
  npt_hours: number
  upa_hours: number
  productive_pct: number
  npt_pct: number
  unaccounted_hours: number
  avg_rop: number | null
  lag_days: number | null
  wells_covered: number
  wells_total: number
  data_quality_score: number
}

export type OpsDashboard = {
  kpis: OpsKpi
  npt_by_code: { code: string; minutes: number; hours: number; name: string }[]
  npt_by_agency: { agency: string; minutes: number; hours: number }[]
  daily_trend: { date: string; logged_hours: number; npt_hours: number; planned_hours: number; upa_hours: number }[]
  recent_reports: OpsReport[]
  missing_reports: { well_code: string; scope: string; date: string; reason: string }[]
}

export type OpsTimeDepth = {
  plan: { cum_days: number; depth_m: number | null; label: string; report_date?: string }[]
  projection: { cum_days: number; depth_m: number }[]
  actual: {
    report_id: string
    rop: number | null
    basis: string
    cum_days: number
    depth_m: number | null
    label: string
    report_date?: string
  }[]
  npt_bands: { from: string; to: string; reason: string }[]
  milestones: { label: string; depth_m: number; days: number }[]
  lag_series: {
    report_id: string
    report_date: string
    lag_days: number
    depth_m: number | null
    baseline: string
    basis: string
  }[]
}

export type OpsScopeReference = {
  document_types: string[]
  rigs: { id: string; rig_code: string; rig_name: string; display_name: string }[]
  wells: {
    id: string
    rig_id: string
    block_id: string
    well_code: string
    well_name: string
    display_name: string
    drilling_available: boolean
    completion_available: boolean
  }[]
}

export type OpsReference = OpsScopeReference & {
  vendors: { id: string; vendor_code: string; vendor_name: string }[]
  phase_codes: { id: string; phase_code: string; phase_name: string }[]
  activity_codes: { id: string; activity_code: string; activity_name: string; default_allocation: string }[]
  operation_codes: {
    id: string
    operation_code: string
    operation_name: string
    default_classification: string
    is_productive_default: boolean
    category: string
    description: string
    sort_order: number
  }[]
  npt_codes: {
    id: string
    npt_code: string
    npt_name: string
    family: string
    category: string
    description: string
    sort_order: number
  }[]
  causes: { id: string; cause_code: string; cause_name: string; sort_order: number }[]
}

export type OpsSettings = {
  document_types: string[]
  id: string
  organization_id: string
  day_boundary_hour: number
  operating_timezone: string
  tour_pattern: string
  require_npt_code: boolean
  require_npt_agency: boolean
  require_npt_reason: boolean
  max_daily_hours: number
  completeness_tolerance_minutes: number
  default_depth_unit: string
  default_rop_basis: string
  document_max_mb: number
  created_at: string
  updated_at: string
}

export type OpsPlan = {
  id: string
  organization_id: string
  well_id: string
  scope: string
  version_no: number
  label: string
  basis: string
  status: string
  planned_start_at: string | null
  planned_days: string | null
  notes: string
  is_deleted: boolean
  created_at: string
  updated_at: string
  well_code: string
  well_name: string
  items: {
    id: string
    sequence_no: number
    description: string
    target_depth_m: string | null
    planned_hours: string
    cum_planned_days: string | null
  }[]
}

export const opsScopeReference = () => api<OpsScopeReference>('/operations/scope-reference')

export function opsReference() {
  return api<OpsReference>('/operations/reference', { action: 'Load operations reference' })
}

export function opsDashboard(params: Record<string, string | undefined>) {
  const q = new URLSearchParams()
  Object.entries(params).forEach(([k, v]) => {
    if (v) q.set(k, v)
  })
  const suffix = q.toString() ? `?${q.toString()}` : ''
  return api<OpsDashboard>(`/operations/dashboard${suffix}`, { action: 'Load operations dashboard' })
}

export function opsTimeDepth(wellId: string, scope: string) {
  return api<OpsTimeDepth>(
    `/operations/analytics/time-depth?well_id=${encodeURIComponent(wellId)}&scope=${encodeURIComponent(scope)}`,
    { action: 'Load time-depth curve' },
  )
}

export function opsSettingsGet() {
  return api<OpsSettings>('/operations/settings', { action: 'Load operations settings' })
}

export function opsSettingsPut(data: Partial<OpsSettings>) {
  return api<OpsSettings>('/operations/settings', { method: 'PUT', body: body(data), action: 'Save operations settings' })
}

export function listDocuments(params: Record<string, string | undefined>) {
  const q = new URLSearchParams()
  Object.entries(params).forEach(([k, v]) => {
    if (v) q.set(k, v)
  })
  const s = q.toString() ? `?${q.toString()}` : ''
  return api<OpsDocument[]>(`/operations/documents${s}`, { action: 'Load documents' })
}

export function listDeletedDocuments() {
  return api<OpsDocument[]>('/operations/documents/deleted', { action: 'Load deleted documents' })
}

export function uploadDocument(file: File, fields: Record<string, string>) {
  return uploadFiles<OpsDocument>('/operations/documents/upload', [file], fields, 'file')
}

export function extractReport(document_id: string, report_date: string, reportId?: string) {
  return api<OpsReport>(reportId ? `/operations/reports/${reportId}/extract` : '/operations/reports/from-document', {
    method: 'POST',
    body: body({ document_id, report_date: report_date || null }),
    action: 'Extract report draft',
  })
}

export function listReports(params: Record<string, string | undefined>) {
  const q = new URLSearchParams()
  Object.entries(params).forEach(([k, v]) => {
    if (v) q.set(k, v)
  })
  const s = q.toString() ? `?${q.toString()}` : ''
  return api<OpsReport[]>(`/operations/reports${s}`, { action: 'Load reports' })
}

export function getReport(id: string, includeDeleted = false) {
  return api<OpsReport>(`/operations/reports/${id}${includeDeleted ? '?include_deleted=true' : ''}`, { action: 'Load report' })
}

export function createReport(data: Record<string, unknown>) {
  return api<OpsReport>('/operations/reports', { method: 'POST', body: body(data), action: 'Create report' })
}

export function saveReport(
  id: string,
  data: {
    expected_updated_at?: string
    confirm_review?: boolean
    report: Record<string, unknown>
    blocks: Record<string, unknown>[]
    surveys?: OpsSurvey[]
  },
) {
  return api<OpsReport>(`/operations/reports/${id}`, { method: 'PUT', body: body(data), action: 'Save report' })
}

export function submitReport(id: string) {
  return api<OpsReport>(`/operations/reports/${id}/submit`, { method: 'POST', action: 'Submit report' })
}

export function approveReport(id: string) {
  return api<OpsReport>(`/operations/reports/${id}/approve`, { method: 'POST', action: 'Approve report' })
}

export function rejectReport(id: string, reason: string) {
  return api<OpsReport>(`/operations/reports/${id}/reject`, {
    method: 'POST',
    body: body({ reason }),
    action: 'Reject report',
  })
}

export function getBrief(id: string, includeDeleted = false) {
  return api<{
    summary: string
    time_split: Record<string, unknown>
    npt_items: unknown[]
    depth_progress: Record<string, unknown>
    data_quality: Record<string, unknown>
  }>(`/operations/reports/${id}/brief${includeDeleted ? '?include_deleted=true' : ''}`, { action: 'Load brief' })
}

export function bulkDeleteReports(ids: string[]) {
  return api<{ affected_count: number }>('/operations/reports/bulk-delete', {
    method: 'POST',
    body: body({ ids }),
    action: 'Delete reports',
  })
}

export function bulkRestoreReports(ids: string[]) {
  return api<{ affected_count: number }>('/operations/reports/bulk-restore', {
    method: 'POST',
    body: body({ ids }),
    action: 'Restore reports',
  })
}

export function listPlans(wellId?: string, scope?: string, deleted = false) {
  const q = new URLSearchParams()
  if (deleted) q.set('deleted', 'true')
  if (wellId) q.set('well_id', wellId)
  if (scope) q.set('scope', scope)
  const s = q.toString() ? `?${q.toString()}` : ''
  return api<OpsPlan[]>(`/operations/plans${s}`, { action: 'Load plans' })
}

export function createPlan(data: Record<string, unknown>) {
  return api<OpsPlan>('/operations/plans', { method: 'POST', body: body(data), action: 'Create plan' })
}

export function addPlanItem(planId: string, data: Record<string, unknown>) {
  return api<unknown>(`/operations/plans/${planId}/items`, { method: 'POST', body: body(data), action: 'Add plan item' })
}

export function activatePlan(planId: string) {
  return api<OpsPlan>(`/operations/plans/${planId}/activate`, { method: 'POST', action: 'Activate plan' })
}

export function auditExport(register: 'reports' | 'documents' | 'plans' | 'library' | 'analytics') {
  return (format: 'csv' | 'xlsx' | 'pdf', record_count: number) =>
    api<void>(`/operations/${register}/export-audit`, {
      method: 'POST',
      body: body({ format, record_count }),
      action: 'Audit export',
    })
}

export type TimelineRow = {
  description: string
  target_depth_m: string | null
  planned_hours: string | null
  source_row?: number
}
export type TimelinePreview = { sheet: string; sheets: string[]; warnings: string[]; items: TimelineRow[] }
export const previewTimeline = (id: string, file: File, sheet = '') =>
  uploadFiles<TimelinePreview>(`/operations/plans/${id}/import-preview`, [file], { sheet }, 'file')
function timelinePayload(rows: TimelineRow[]) {
  return rows.map((row, i) => {
    // Keep existing metadata when editing just the description, depth or hours.
    const { id: _id, source_row: _source, cum_planned_days: _computed, ...item } = row as TimelineRow & {
      id?: string; cum_planned_days?: string
    }
    return { ...item, sequence_no: i + 1, description: row.description.trim(), target_depth_m: row.target_depth_m ?? null }
  })
}

export const saveTimeline = (id: string, rows: TimelineRow[]) =>
  api(`/operations/plans/${id}/items`, { method: 'PUT', body: body(timelinePayload(rows)) })

export type OpsDefaultCode = {
  id: string
  family: string
  code: string
  name: string
  description: string
  source: string
  classification: string
  allocation: string
}
export const defaultOpsCodes = () => api<OpsDefaultCode[]>('/operations/default-codes', { action: 'Load default operations codes' })

export type OpsRegisters = { plans: OpsPlan; reports: OpsReport; documents: OpsDocument }
export type OpsFolderCount = {
  rig_key: string
  well_key: string
  rig_id: string | null
  well_id: string | null
  rig_code: string
  well_code: string
  well_name: string
  scope: string
  record_count: number
}
export const operationsFolders = (resource: keyof OpsRegisters, deleted: boolean) =>
  api<OpsFolderCount[]>(`/operations/directory/${resource}?deleted=${deleted}`, { action: 'Load rig and well folders' })
export const operationsRecords = <K extends keyof OpsRegisters>(resource: K, rig: string, well: string, scope: string, deleted: boolean) =>
  api<OpsRegisters[K][]>(`/operations/directory/${resource}/records?${new URLSearchParams({ rig, well, scope, deleted: String(deleted) })}`, { action: 'Load well folder' })
export const getOpsPlan = (id: string) => api<OpsPlan>(`/operations/plans/${id}`, { action: 'Load timeline' })

export type OpsGuideTopic = { id: string; title: string; question: string; body: string; steps: string[]; route: string }
export const opsGuide = () => api<OpsGuideTopic[]>('/operations/guide', { action: 'Load Well Operations guide' })

export type OpsStudy = {
  summary: string
  warnings: string[]
  ai_text: string
  ai_model: string
  ai_error: string
  ai_error_code: import('./ai').AiErrorCode
}
export const opsAiStatus = () => api<import('./ai').AiConnectionStatus>('/operations/ai-status?probe=true', { action: 'Check offline AI connection' })
export const reviewBrief = (id: string, useAi: boolean, includeDeleted = false) => api<OpsStudy>(`/operations/reports/${id}/brief${includeDeleted ? '?include_deleted=true' : ''}`, {
  method: 'POST', body: body({ use_ai: useAi }), action: 'Generate daily narrative',
})
export const studyTimeline = (id: string, useAi: boolean, rows?: TimelineRow[]) => api<OpsStudy>(`/operations/plans/${id}/study`, {
  method: 'POST', body: body({ use_ai: useAi, ...(rows ? { items: timelinePayload(rows) } : {}) }), action: 'Study timeline',
})
