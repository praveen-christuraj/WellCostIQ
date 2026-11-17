import { api, body } from './api'

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

export type OpsReport = {
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
  classification_source: string
  npt_code_id: string | null
  npt_code_snapshot: string
  agency_id: string | null
  cause_code: string
  hole_section_id: string | null
  phase_id: string | null
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
  daily_trend: { date: string; logged_hours: number; npt_hours: number; planned_hours: number; depth_end_m: number | null }[]
  recent_reports: OpsReport[]
  missing_reports: { well_code: string; date: string; reason: string }[]
}

export type OpsTimeDepth = {
  plan: { cum_days: number; depth_m: number; label: string; report_date?: string }[]
  actual: { cum_days: number; depth_m: number; label: string; report_date?: string }[]
  npt_bands: { from: string; to: string; reason: string }[]
  milestones: { label: string; depth_m: number; days: number }[]
  lag_series: { report_date: string; lag_days: number; depth_m: number }[]
}

export type OpsReference = {
  rigs: { id: string; rig_code: string; rig_name: string; display_name: string }[]
  wells: { id: string; rig_id: string; block_id: string; well_code: string; well_name: string; display_name: string; drilling_available: boolean; completion_available: boolean }[]
  hole_sections: { id: string; section_code: string; section_name: string }[]
  phases: { id: string; phase_code: string; phase_name: string }[]
  operation_codes: { id: string; operation_code: string; operation_name: string; default_classification: string; is_productive_default: boolean; category: string; description: string; sort_order: number }[]
  npt_codes: { id: string; npt_code: string; npt_name: string; family: string; category: string; description: string; sort_order: number }[]
  agencies: { id: string; agency_code: string; agency_name: string; category: string; sort_order: number }[]
  causes: { id: string; cause_code: string; cause_name: string; sort_order: number }[]
  activities: { id: string; activity_code: string; activity_name: string }[]
}

export type OpsSettings = {
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
  items: { id: string; sequence_no: number; description: string; target_depth_m: string | null; planned_hours: string; cum_planned_days: string | null }[]
}

export function opsReference() {
  return api<OpsReference>('/operations/reference', { action: 'Load operations reference' })
}

export function opsDashboard(params: Record<string, string | undefined>) {
  const q = new URLSearchParams()
  Object.entries(params).forEach(([k, v]) => { if (v) q.set(k, v) })
  const suffix = q.toString() ? `?${q.toString()}` : ''
  return api<OpsDashboard>(`/operations/dashboard${suffix}`, { action: 'Load operations dashboard' })
}

export function opsTimeDepth(wellId: string, scope: string) {
  return api<OpsTimeDepth>(`/operations/analytics/time-depth?well_id=${encodeURIComponent(wellId)}&scope=${encodeURIComponent(scope)}`, { action: 'Load time-depth curve' })
}

export function opsSettingsGet() {
  return api<OpsSettings>('/operations/settings', { action: 'Load operations settings' })
}

export function opsSettingsPut(data: Partial<OpsSettings>) {
  return api<OpsSettings>('/operations/settings', { method: 'PUT', body: body(data), action: 'Save operations settings' })
}

export function listDocuments(params: Record<string, string | undefined>) {
  const q = new URLSearchParams()
  Object.entries(params).forEach(([k, v]) => { if (v) q.set(k, v) })
  const s = q.toString() ? `?${q.toString()}` : ''
  return api<OpsDocument[]>(`/operations/documents${s}`, { action: 'Load documents' })
}

export function listDeletedDocuments() {
  return api<OpsDocument[]>('/operations/documents/deleted', { action: 'Load deleted documents' })
}

export async function uploadDocument(form: FormData) {
  const { getAccessToken } = await import('./api')
  const token = getAccessToken()
  const headers: Record<string, string> = {}
  if (token) headers.Authorization = 'Bearer ' + token
  const res = await fetch('/api/v1/operations/documents/upload', { method: 'POST', body: form, credentials: 'include', headers })
  if (!res.ok) {
    const body = await res.json().catch(() => ({}))
    const detail = body.detail
    const msg = typeof detail === 'string' ? detail : detail ? JSON.stringify(detail) : 'Upload failed (' + res.status + ')'
    throw new Error(msg)
  }
  return res.json() as Promise<OpsDocument>
}

export const uploadDocViaApi = uploadDocument

export function extractDocument(documentId: string) {
  return api<{ id: string; status: string }>(`/operations/documents/${documentId}/extract`, { method: 'POST', action: isExtractAction(documentId) })
}

function isExtractAction(id: string) { return `Extract document ${id}` }

export function listReports(params: Record<string, string | undefined>) {
  const q = new URLSearchParams()
  Object.entries(params).forEach(([k, v]) => { if (v) q.set(k, v) })
  const s = q.toString() ? `?${q.toString()}` : ''
  return api<OpsReport[]>(`/operations/reports${s}`, { action: 'Load reports' })
}

export function getReport(id: string) {
  return api<OpsReport>(`/operations/reports/${id}`, { action: 'Load report' })
}

export function createReport(data: Record<string, unknown>) {
  return api<OpsReport>('/operations/reports', { method: 'POST', body: body(data), action: 'Create report' })
}

export function saveReport(id: string, data: { report: Record<string, unknown>; blocks: Record<string, unknown>[] }) {
  return api<OpsReport>(`/operations/reports/${id}`, { method: 'PUT', body: body(data), action: 'Save report' })
}

export function submitReport(id: string) {
  return api<OpsReport>(`/operations/reports/${id}/submit`, { method: 'POST', action: 'Submit report' })
}

export function approveReport(id: string) {
  return api<OpsReport>(`/operations/reports/${id}/approve`, { method: 'POST', action: 'Approve report' })
}

export function rejectReport(id: string, reason: string) {
  return api<OpsReport>(`/operations/reports/${id}/reject`, { method: 'POST', body: body({ reason }), action: 'Reject report' })
}

export function getBrief(id: string) {
  return api<{ summary: string; time_split: Record<string, unknown>; npt_items: unknown[]; depth_progress: Record<string, unknown>; data_quality: Record<string, unknown> }>(`/operations/reports/${id}/brief`, { action: 'Load brief' })
}

export function bulkDeleteReports(ids: string[]) {
  return api<{ affected_count: number }>('/operations/reports/bulk-delete', { method: 'POST', body: body({ ids }), action: 'Delete reports' })
}

export function bulkRestoreReports(ids: string[]) {
  return api<{ affected_count: number }>('/operations/reports/bulk-restore', { method: 'POST', body: body({ ids }), action: 'Restore reports' })
}

export function listPlans(wellId?: string, scope?: string) {
  const q = new URLSearchParams()
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

export function exportAudit(format: string, record_count: number) {
  return api<unknown>('/operations/reports/export-audit', { method: 'POST', body: body({ format, record_count }), action: 'Audit export' }).catch(() => null)
}
