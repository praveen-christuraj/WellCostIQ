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
  reopened_at: string | null
  reopened_by: string
  reopen_reason: string
  submitted_at: string | null
  submitted_by: string
  approved_at: string | null
  approved_by: string
  baseline_plan_id: string | null
  completed_plan_item_id: string | null
  plan_checkpoints: { id: string; description: string; days: string }[]
  customer: string
  project: string
  site: string
  datum: string
  supervisor: string
  engineer: string
  uwi: string
  block_text: string
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
  tvd_start_m: string | null
  tvd_m: string | null
  tvd_source: string
  bit_depth_m: string | null
  progress_m: string | null
  rotating_hours: string | null
  cum_rotating_hours: string | null
  spud_date: string | null
  dfs_days: string | null
  est_days: string | null
  md_auth_m: string | null
  last_casing_size_in: string | null
  last_casing_depth_m: string | null
  hole_section_text: string
  hole_size_in: string | null
  current_status: string
  mud_type: string
  mud_weight_ppg: string | null
  mud_viscosity_sec: string | null
  mud_pv_cp: string | null
  mud_yp_lbf: string | null
  bha_summary: string
  pob_count: number | null
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
  mud_weight_ppg: string | null
  depth_from_m: string | null
  depth_to_m: string | null
  tvd_from_m: string | null
  tvd_to_m: string | null
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
  approved_by: string
  reopened_at: string | null
  reopened_by: string
  reopen_reason: string
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

export function extractReport(document_id: string, report_date: string, reportId?: string, use_ai = false) {
  return api<OpsReport>(reportId ? `/operations/reports/${reportId}/extract` : '/operations/reports/from-document', {
    method: 'POST',
    body: body({ document_id, report_date: report_date || null, use_ai }),
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

export function reopenReport(id: string, remarks: string) {
  return api<OpsReport>(`/operations/reports/${id}/reopen`, {
    method: 'POST',
    body: body({ remarks }),
    action: 'Reopen daily report',
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

export function updatePlan(planId: string, data: Record<string, unknown>) {
  return api<OpsPlan>(`/operations/plans/${planId}`, { method: 'PUT', body: body(data), action: 'Update plan' })
}

export function reopenPlan(planId: string, remarks: string) {
  return api<OpsPlan>(`/operations/plans/${planId}/reopen`, {
    method: 'POST',
    body: body({ remarks }),
    action: 'Reopen timeline',
  })
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

export type OpsNarratives = {
  operation_summary: string
  forward_plan: string
  hse_summary: string
  engineering_brief: string
  warnings: string[]
  ai_used: boolean
  ai_model: string
  ai_error: string
  ai_error_code: import('./ai').AiErrorCode
}

export const generateReportNarratives = (id: string, useAi = true, focus = '') =>
  api<OpsNarratives>(`/operations/reports/${id}/narratives`, {
    method: 'POST',
    body: body({ use_ai: useAi, focus }),
    action: 'Generate daily report narratives',
  })

export type OpsAiPrefill = {
  report: OpsReport
  updated_header_fields: string[]
  updated_block_count: number
  notes: string[]
  ai_used: boolean
  ai_model: string
  ai_error: string
  ai_error_code: import('./ai').AiErrorCode
}

export const aiPrefillReport = (id: string) =>
  api<OpsAiPrefill>(`/operations/reports/${id}/ai-prefill`, {
    method: 'POST',
    action: 'Run AI extraction prefill',
  })

export type OpsAiReviewItem = {
  severity: 'high' | 'medium' | 'low' | 'info'
  category: string
  title: string
  detail: string
  well_code: string
  report_date: string
  report_id: string
}

export type OpsAiReview = {
  generated_at: string
  timezone_label: string
  scope_label: string
  deterministic_summary: string
  executive_summary: string
  highlights: string[]
  anomalies: OpsAiReviewItem[]
  recommended_actions: string[]
  ai_used: boolean
  ai_model: string
  ai_endpoint: string
  ai_error: string
  ai_error_code: import('./ai').AiErrorCode
}

export const runOpsAiReview = (params: {
  well_id?: string | null
  rig_id?: string | null
  scope?: Scope | null
  date_from?: string | null
  date_to?: string | null
  focus?: string
  use_ai?: boolean
}) =>
  api<OpsAiReview>('/operations/ai-review', {
    method: 'POST',
    body: body({
      well_id: params.well_id || null,
      rig_id: params.rig_id || null,
      scope: params.scope || null,
      date_from: params.date_from || null,
      date_to: params.date_to || null,
      focus: params.focus || '',
      use_ai: params.use_ai ?? true,
    }),
    action: 'Run operations AI review',
  })

export type OpsSummaryActivity = {
  id: string
  line_no: number
  report_id: string
  report_date: string
  report_no: string
  report_type: string
  report_status: string
  scope: string
  day_number: number | null
  hole_section: string
  start_wat: string
  end_wat: string
  duration_minutes: number
  duration_hours: number
  cum_hours: number
  cum_days: number
  phase_code: string
  phase_label: string
  operation_code: string
  activity_code: string
  classification: string
  allocation: string
  is_productive: boolean
  npt_code: string
  cause_code: string
  responsible_party: string
  depth_from_m: number | null
  depth_to_m: number | null
  tvd_from_m: number | null
  tvd_to_m: number | null
  bit_depth_m: number | null
  footage_m: number | null
  rotating_hours: number | null
  rop_m_per_hr: number | null
  mud_weight_ppg: number | null
  reason: string
  narrative: string
  review_state: string
}

export type OpsSummaryDay = {
  report_id: string
  report_date: string
  scope: string
  report_type: string
  report_no: string
  day_number: number | null
  dfs_days: number | null
  status: string
  reopened: boolean
  hole_section: string
  depth_start_m: number | null
  depth_end_m: number | null
  tvd_start_m: number | null
  tvd_m: number | null
  tvd_source: string
  bit_depth_m: number | null
  progress_m: number | null
  rotating_hours: number | null
  rop_m_per_hr: number | null
  mud_type: string
  mud_weight_ppg: number | null
  mud_viscosity_sec: number | null
  last_casing: string
  pob_count: number | null
  logged_hours: number
  pt_hours: number
  upa_hours: number
  npt_hours: number
  sp_hours: number
  productive_pct: number
  unaccounted_hours: number
  block_count: number
  survey_count: number
  current_status: string
  operation_summary: string
  forward_plan: string
  hse_summary: string
}

export type OpsSummaryBreakdown = {
  classification: string
  allocation: string
  responsible_party: string
  code: string
  cause_code: string
  events: number
  hours: number
  days: number
  pct_of_total: number
  pct_of_npt: number
  sample_reason: string
}

export type OpsSummaryPhase = {
  phase: string
  hole_section: string
  events: number
  total_hours: number
  total_days: number
  pt_hours: number
  upa_hours: number
  npt_hours: number
  sp_hours: number
  productive_pct: number
  max_md_m: number | null
  max_tvd_m: number | null
  footage_m: number
}

export type OpsSummarySurvey = {
  report_id: string
  report_date: string
  report_no: string
  scope: string
  md_m: number | null
  tvd_m: number | null
  inc_deg: number | null
  azi_deg: number | null
  ns_m: number | null
  ew_m: number | null
  vsec_m: number | null
  dls_deg_per_30m: number | null
  tool: string
  source: string
}

export type OpsWellSummary = {
  generated_at: string
  timezone: string
  timezone_label: string
  well_id: string
  well_code: string
  well_name: string
  rig_code: string
  rig_name: string
  block_text: string
  field_site: string
  customer: string
  uwi: string
  datum: string
  scope_label: string
  include_drafts: boolean
  spud_date: string | null
  first_report_date: string | null
  last_report_date: string | null
  latest_status: string
  latest_hole_section: string
  last_casing: string
  latest_mud: string
  latest_bha: string
  kpis: {
    total_reports: number
    drilling_reports: number
    completion_reports: number
    draft_reports: number
    submitted_reports: number
    approved_reports: number
    reopened_reports: number
    total_blocks: number
    total_logged_hours: number
    total_logged_days: number
    planned_days: number | null
    schedule_variance_days: number | null
    productive_hours: number
    nonproductive_hours: number
    pt_hours: number
    upa_hours: number
    npt_hours: number
    sp_hours: number
    productive_pct: number
    npt_pct: number
    upa_pct: number
    sp_pct: number
    unaccounted_hours: number
    start_md_m: number | null
    current_md_m: number | null
    max_md_m: number | null
    authorized_md_m: number | null
    current_tvd_m: number | null
    max_tvd_m: number | null
    latest_bit_depth_m: number | null
    total_footage_m: number
    total_rotating_hours: number
    avg_rop_m_per_hr: number | null
    latest_mud_weight_ppg: number | null
    survey_count: number
    max_inc_deg: number | null
    max_dls_deg_per_30m: number | null
    latest_pob: number | null
  }
  activities: OpsSummaryActivity[]
  daily_rollup: OpsSummaryDay[]
  pt_npt_breakdown: OpsSummaryBreakdown[]
  phase_breakdown: OpsSummaryPhase[]
  surveys: OpsSummarySurvey[]
}

export function getWellOperationSummary(params: {
  well_id: string
  scope?: string
  from?: string
  to?: string
  include_drafts?: boolean
}) {
  const q = new URLSearchParams({ well_id: params.well_id })
  if (params.scope) q.set('scope', params.scope)
  if (params.from) q.set('from', params.from)
  if (params.to) q.set('to', params.to)
  q.set('include_drafts', String(params.include_drafts ?? true))
  return api<OpsWellSummary>(`/operations/summary?${q.toString()}`, { action: 'Load well operation summary' })
}

export function auditSummaryExport(format: 'csv' | 'xlsx' | 'pdf', record_count: number) {
  return api<void>('/operations/summary/export-audit', {
    method: 'POST',
    body: body({ format, record_count }),
    action: 'Audit summary export',
  })
}
