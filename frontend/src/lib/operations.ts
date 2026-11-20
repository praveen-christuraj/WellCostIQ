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

export type OpsActivityType = 'Planned' | 'UPA' | 'NPT'

/**
 * One time block of a daily report.
 *
 * The criteria are listed in review order: Hole Section, Phase, Sub-phase,
 * Activity, Allocation, Cause, Operations, Agency / service vendor, responsible
 * agency label. Hole Section, Phase and Activity are Master Data; Sub-phase,
 * Operations, Cause and the responsible agency label are Code Library lists.
 * The Activity carries its own type, which is what ``classification`` stores.
 */
export type OpsBlock = {
  id: string
  organization_id: string
  report_id: string
  sequence_no: number
  started_at: string
  ended_at: string
  duration_minutes: number
  phase_raw: string
  hole_section_id: string | null
  phase_id: string | null
  sub_phase_id: string | null
  activity_id: string | null
  classification: OpsActivityType
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
  operation_id: string | null
  operation_snapshot: string
  responsible_agency_id: string | null
  cause_code: string
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
  // Labels resolved by the API so a page never guesses how a code is displayed.
  hole_section_label?: string
  phase_label?: string
  sub_phase_label?: string
  activity_label?: string
  activity_type?: OpsActivityType | ''
  operation_code?: string | null
  operation_name?: string | null
  cause_label?: string
  responsible_agency_label?: string
  reason: string
  narrative: string
  confidence: string
  review_state: string
  // The system-generated comparison is visible and reviewable: it is suggested
  // until an engineer accepts, edits or rejects it with a note.
  timeline_comparison?: 'ahead' | 'behind' | 'on'
  timeline_review_state?: 'suggested' | 'accepted' | 'edited' | 'rejected'
  timeline_note?: string
  timeline_variance_days?: string | null
  timeline_planned_days?: string | null
  timeline_actual_days?: string | null
  timeline_basis?: string
  timeline_reviewed_by?: string
  timeline_reviewed_at?: string | null
  // Plan against actual hours for the programme row this block logs. ``actual``
  // is the engineer's figure when one was entered (``timeline_actual_edited``),
  // otherwise the system's duration-derived hours.
  timeline_plan_item_id?: string | null
  timeline_plan_step_no?: number | null
  timeline_plan_label?: string
  timeline_planned_hours?: string | null
  timeline_actual_hours?: string | null
  timeline_system_actual_hours?: string | null
  timeline_variance_hours?: string | null
  timeline_cum_planned_days?: string | null
  timeline_actual_edited?: boolean
  timeline_edited_by?: string
  timeline_edited_at?: string | null
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
  /** Downtime grouped by the Code Library Operations code on the block. */
  npt_by_code: { code: string; minutes: number; hours: number; name: string }[]
  npt_by_operation: { operation_code: string; minutes: number; hours: number }[]
  npt_by_agency: { agency: string; minutes: number; hours: number }[]
  daily_trend: { date: string; logged_hours: number; npt_hours: number; planned_hours: number; upa_hours: number }[]
  recent_reports: OpsReport[]
  missing_reports: { well_code: string; scope: string; date: string; reason: string }[]
  /** Casing schematic for the selected well; null when a multi-well filter is shown. */
  well_visual: OpsWellVisual | null
}

/** One drawn casing string: from the shoe above it down to its own shoe. */
export type OpsWellPathSection = {
  from_depth_m: number
  to_depth_m: number
  length_m: number
  casing_size_in: number
  casing_label: string
  source: string
  hole_size_in: number | null
  is_deepest: boolean
}

export type OpsWellPathSummary = {
  stations: number
  md_m: number | null
  tvd_m: number | null
  departure_m: number | null
  displacement_m: number | null
  closure_azimuth_deg: number | null
  max_inc_deg: number | null
  /** Highest severity of any *valid* interval; null when no interval qualifies. */
  max_dls_deg_per_30m: number | null
  /** The deeper station of the interval that carries the maximum severity. */
  max_dls_to_md_m: number | null
  intervals: number
  invalid_intervals: number
  vertical_section_m: number | null
  kickoff_md_m: number | null
  /** The marker: the selected report's closing MD, else the last station. */
  current_md_m: number | null
  current_tvd_m: number | null
  current_tvd_basis: string
  bit_depth_m: number | null
  latest_report_date: string | null
  latest_report_status: string
  depth_basis: string
  casing_seats: number
  sections_drawn: number
  survey_end_md_m: number | null
  report_depth_md_m: number | null
  survey_to_report_gap_m: number | null
  position_basis: string
}

/** One integrated trajectory station. Severity is null where there is no interval. */
export type OpsWellPathStation = {
  md_m: number
  inc_deg: number
  azi_deg: number
  tvd_m: number
  ns_m: number
  ew_m: number
  vsec_m: number
  dls_deg_per_30m: number | null
  build_deg_per_30m: number | null
  turn_deg_per_30m: number | null
  is_anchor: boolean
  interval_valid: boolean
  interval_issue: string
}

/** One survey-to-survey interval: the unit dogleg severity is defined on. */
export type OpsWellPathInterval = {
  from_md_m: number
  to_md_m: number
  delta_md_m: number
  inc1_deg: number
  azi1_deg: number
  inc2_deg: number
  azi2_deg: number
  beta_deg: number | null
  dls_deg_per_30m: number | null
  recorded_dls_deg_per_30m: number | null
  dls_difference_deg_per_30m: number | null
  valid: boolean
  issue: string
}

/** Recorded provenance for a drawn station: what the record printed, not the maths. */
export type OpsWellPathSurveyStation = {
  survey_id: string
  station_no: number | null
  md_m: number
  inc_deg: number | null
  azi_deg: number | null
  recorded_tvd_m: number | null
  recorded_ns_m: number | null
  recorded_ew_m: number | null
  recorded_vsec_m: number | null
  recorded_dls_deg_per_30m: number | null
  tool: string
  source: string
  source_page: number | null
  confidence: number | null
  survey_at: string | null
  report_id: string | null
  report_date: string | null
  report_no: string
  report_status: string
  computed_tvd_m: number | null
  tvd_difference_m: number | null
  rows_at_md: number
}

/** The survey as a record: endpoints, anchor basis and interval counts. */
export type OpsWellPathSurvey = {
  stations: number
  first_md_m: number | null
  last_md_m: number | null
  first_survey_at: string | null
  last_survey_at: string | null
  sources: string[]
  tools: string[]
  anchor: OpsWellPathSurveyStation | null
  anchor_basis: string
  intervals: number
  invalid_intervals: number
  branch: string
}

/** The marker on the drawing, kept apart from the survey and from any snapshot. */
export type OpsWellPathPosition = {
  marker_md_m: number | null
  marker_tvd_m: number | null
  marker_tvd_basis: string
  survey_end_md_m: number | null
  report_depth_md_m: number | null
  gap_m: number | null
  basis: string
  comparable: boolean
  note: string
}

/** One report's positions. Separate from the trajectory by design. */
export type OpsWellPathSnapshot = {
  hole_depth_m: number | null
  hole_tvd_m: number | null
  bit_depth_m: number | null
  off_bottom_m: number | null
  off_bottom_note: string
  report_id: string | null
  report_date: string | null
  report_no: string
  status: string
  verified: boolean
  basis: string
  current_status_text: string
  tvd_source: string
  label: string
}

/** Trajectory, casing schematic and provenance for one well and scope. */
export type OpsWellPath = {
  well_id: string
  well_code: string
  well_name: string
  scope: string
  datum: string
  vertical_section_azimuth_deg: number
  curve: OpsWellPathStation[]
  /** Intervals between accepted stations: the DLS chart reads these. */
  intervals: OpsWellPathInterval[]
  /** Recorded provenance per drawn station: the source drawer reads these. */
  survey_stations: OpsWellPathSurveyStation[]
  survey: OpsWellPathSurvey
  position: OpsWellPathPosition
  snapshot: OpsWellPathSnapshot
  summary: OpsWellPathSummary
  sections: OpsWellPathSection[]
  open_hole: { from_depth_m: number; to_depth_m: number; label: string } | null
  casing_seats: { size_in: number; size_label: string; depth_m: number; source: string; report_date: string | null }[]
  planned: {
    label: string
    version_no: number | null
    points: { cum_days: number | null; md_m: number | null; sequence_no: number; description: string }[]
    planned_days: number | null
    planned_start_at: string | null
    items: number
  }
  depth: {
    md_m: number | null
    tvd_m: number | null
    bit_depth_m: number | null
    report_date: string | null
    report_id: string | null
    status: string
    basis: string
    report_no: string
    current_status: string
    verified: boolean
    tvd_source: string
    depth_start_m: number | null
    progress_m: number | null
    last_casing_size_in: number | null
    last_casing_depth_m: number | null
  }
  survey_discrepancies: { md_m: number; printed_tvd_m: number; computed_tvd_m: number; difference_m: number }[]
  notes: string[]
  /** Words, not a guess: any fallback the engine applied to draw something. */
  assumption: string
  is_surveyed: boolean
  generated_at: string
}

export type OpsWellDiagram = { scope: string; wells: OpsWellPath[] }

/** The dashboard's single-well picture: schematic plus current depth. */
export type OpsWellVisual = {
  well_id: string
  well_code: string
  well_name: string
  scope: string
  summary: OpsWellPathSummary
  sections: OpsWellPathSection[]
  open_hole: { from_depth_m: number; to_depth_m: number; label: string } | null
  assumption: string
  is_surveyed: boolean
  /** Live depth, taken from the same service as the drawing so the card agrees. */
  depth?: {
    current_md_m: number | null
    current_tvd_m: number | null
    tvd_basis: string
    bit_depth_m: number | null
    date_reported: string | null
    report_no: string | null
    report_status: string | null
    basis: string
  }
}

export type OpsTimeDepth = {
  /** Completed timelines have no depth axis: progress is measured by activity number. */
  mode: 'depth' | 'activity'
  plan: {
    cum_days: number
    depth_m: number | null
    activity_no?: number | null
    activity_id?: string | null
    label: string
    report_date?: string
  }[]
  projection: { cum_days: number; depth_m: number | null; label?: string }[]
  actual: {
    report_id: string
    rop: number | null
    basis: string
    cum_days: number
    depth_m: number | null
    activity_no?: number | null
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

export type OpsMasterOption = {
  id: string
  code: string
  name: string
  label: string
  activity_type?: OpsActivityType
}

export type OpsReference = OpsScopeReference & {
  vendors: { id: string; vendor_code: string; vendor_name: string }[]
  /** Master Data Hole Sections. */
  hole_sections: OpsMasterOption[]
  /** Master Data Phases. */
  phases: OpsMasterOption[]
  /** Master Data Activities; each carries the Activity type it stands for. */
  activities: OpsMasterOption[]
  /** Code Library sub-phases, filtered by the selected phase on the report. */
  sub_phases: {
    id: string
    phase_id: string
    sub_phase_code: string
    sub_phase_name: string
    description: string
    sort_order: number
    is_active: boolean
  }[]
  /** Code Library Operations list (the downtime work list). */
  operations: {
    id: string
    operation_code: string
    operation_name: string
    family: string
    category: string
    description: string
    sort_order: number
    is_active: boolean
  }[]
  causes: { id: string; cause_code: string; cause_name: string; sort_order: number; is_active: boolean }[]
  /** Code Library responsible agency labels. */
  agencies: {
    id: string
    agency_code: string
    agency_name: string
    category: string
    sort_order: number
    is_active: boolean
  }[]
  code_links?: OpsCodeLink[]
  /** Which criteria each Activity type makes mandatory, in display order. */
  classification_rules: Record<string, string[]>
}

export type OpsBulkAssignInput = {
  report_ids?: string[]
  block_ids?: string[]
  block_kind?: '' | 'drilling' | 'completion'
  hole_section_id?: string | null
  phase_id?: string | null
  sub_phase_id?: string | null
  activity_id?: string | null
  operation_id?: string | null
  cause_code?: string | null
  cause_id?: string | null
  responsible_agency_id?: string | null
  vendor_id?: string | null
  allocation?: 'PT' | 'NPT' | 'UPA' | 'SP' | null
}

export type OpsBulkAssignPreview = {
  changes: {
    block_id: string
    sequence_no: number
    report_id: string
    before: Record<string, unknown>
    after: Record<string, unknown>
  }[]
  skipped: { block_id: string; sequence_no: number; report_id: string; reason: string }[]
  summary: string
  assigned_fields: string[]
}

export type OpsBulkAssignResult = {
  changed_count: number
  skipped: { block_id: string; sequence_no: number; report_id: string; reason: string }[]
  remaining_mandatory: string[]
  summary: string
}

/** A printed token is correlated into a Code Library list; Hole Section, Phase
 * and Activity are Master Data targets, independent of the printed source kind. */
export type OpsCorrelationKind = 'operation' | 'cause' | 'sub-phase' | 'responsible-party' | 'agency'

export type OpsCorrelationTargets = {
  scope?: '' | 'drilling' | 'completion'
  target_allocation?: '' | 'PT' | 'UPA' | 'NPT' | 'SP'
  target_hole_section_id?: string | null
  target_phase_id?: string | null
  target_sub_phase_id?: string | null
  target_activity_id?: string | null
  target_operation_id?: string | null
  target_cause_id?: string | null
  target_responsible_agency_id?: string | null
  target_vendor_id?: string | null
  target_mark_rule_id?: string | null
}

export type OpsCorrelation = OpsCorrelationTargets & {
  id: string
  kind: OpsCorrelationKind
  source_family: string
  source_code: string
  source_label: string
  target_label: string
  target_id: string | null
  extra_criteria_summary?: string
  note: string
  is_active: boolean
  is_deleted: boolean
  created_by: string
  updated_by: string
  created_at: string | null
  updated_at: string | null
}

export type OpsCorrelationInput = OpsCorrelationTargets & {
  kind: OpsCorrelationKind
  source_family?: string
  source_code: string
  source_label?: string
  target_id?: string
  note?: string
}

export type OpsCorrelationUpdateInput = OpsCorrelationTargets & {
  target_id?: string
  is_active?: boolean
  note?: string
}

/** One row may carry as many criteria as the user needs; every criterion is a
 * typed relational column, so a rule is auditable without parsing free text. */
export type OpsCodeLink = {
  id: string
  rule_name: string
  scope: string
  default_allocation: string
  hole_section_id: string | null
  hole_section_label: string
  phase_id: string | null
  phase_code: string
  phase_label: string
  sub_phase_id: string | null
  sub_phase_label: string
  activity_id: string | null
  activity_label: string
  activity_type: string
  operation_id: string | null
  operation_label: string
  cause_id: string | null
  cause_code: string
  cause_label: string
  responsible_agency_id: string | null
  responsible_agency_label: string
  vendor_id: string | null
  vendor_label: string
  mark_rule_id: string | null
  mark_label: string
  criteria_count: number
  summary_label: string
  note: string
  is_active: boolean
  is_deleted: boolean
  created_by: string
  updated_by: string
  created_at: string | null
  updated_at: string | null
}

export type OpsCodeLinkInput = {
  rule_name?: string
  scope?: '' | 'drilling' | 'completion'
  default_allocation?: '' | 'PT' | 'UPA' | 'NPT' | 'SP'
  hole_section_id?: string | null
  phase_id?: string | null
  sub_phase_id?: string | null
  activity_id?: string | null
  operation_id?: string | null
  cause_id?: string | null
  responsible_agency_id?: string | null
  vendor_id?: string | null
  mark_rule_id?: string | null
  is_active?: boolean
  note?: string
}

export type OpsCorrelationLibraryItem = {
  id: string
  code: string
  name: string
  correlation_count?: number
  /** Present on Activity options: the type a block becomes when it is selected. */
  activity_type?: OpsActivityType | ''
  default_allocation?: string
}

export type OpsCorrelationReference = {
  kinds: string[]
  printed: {
    family: string
    code: string
    name?: string
    description: string
    detail?: string
    classification: string
    allocation?: string
  }[]
  /** Master Data criterion lists. */
  library: Record<
    'hole_section' | 'phase' | 'activity' | 'vendor' | 'sub_phase' | 'operation' | 'cause' | 'responsible_agency' | 'mark',
    OpsCorrelationLibraryItem[]
  >
}

export type OpsSettings = {
  document_types: string[]
  id: string
  organization_id: string
  day_boundary_hour: number
  operating_timezone: string
  tour_pattern: string
  require_operations: boolean
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

/** Trajectory, casing schematic and current depth for one well and scope. */
export function opsWellPath(wellId: string, scope: string, vsAzimuth?: number | string) {
  const q = new URLSearchParams({ well_id: wellId, scope })
  if (vsAzimuth !== undefined && vsAzimuth !== '') q.set('vs_azimuth', String(vsAzimuth))
  return api<OpsWellPath>(`/operations/well-path?${q.toString()}`, { action: 'Load well path' })
}

/** Every configured well of a scope, drawn from its own record. */
export function opsWellDiagram(params: { scope?: string; rig_id?: string; well_id?: string } = {}) {
  const q = new URLSearchParams()
  if (params.scope) q.set('scope', params.scope)
  if (params.rig_id) q.set('rig_id', params.rig_id)
  if (params.well_id) q.set('well_id', params.well_id)
  const suffix = q.toString() ? `?${q.toString()}` : ''
  return api<OpsWellDiagram>(`/operations/well-diagram${suffix}`, { action: 'Load well diagram' })
}

/** Preview a bulk assignment. Nothing is written; the dialog shows before/after. */
export function opsBulkAssignPreview(data: OpsBulkAssignInput) {
  return api<OpsBulkAssignPreview>('/operations/reports/bulk-assign/preview', {
    method: 'POST',
    body: body(data),
    action: 'Preview bulk code assignment',
  })
}

export function opsBulkAssign(data: OpsBulkAssignInput) {
  return api<OpsBulkAssignResult>('/operations/reports/bulk-assign', {
    method: 'POST',
    body: body(data),
    action: 'Assign codes in bulk',
  })
}

/** The server's answer to a timeline review: what it recomputed, for which blocks. */
export type ReviewTimelineResult = {
  review_state: string
  updated_count: number
  comparison: string
  summary: string
  variance_hours: string | null
  total_variance_hours: string | null
  corrected_blocks: number
}

/**
 * Accept, correct or reject the system's plan-vs-timeline comparison.
 *
 * ``hours`` carries the engineer's correction to the actual hours of a block;
 * the server recomputes the variance (planned − actual) and the lead/lag mark
 * from the corrected value, so every later day and chart follows it.
 */
export function opsReviewTimeline(
  reportId: string,
  data: {
    review_state: 'accepted' | 'edited' | 'rejected'
    comparison?: 'ahead' | 'behind' | 'on'
    note?: string
    block_ids?: string[]
    hours?: { block_id: string; actual_hours: string | null }[]
  },
) {
  return api<ReviewTimelineResult>(`/operations/reports/${reportId}/timeline-review`, {
    method: 'POST',
    body: body(data),
    action: 'Review timeline comparison',
  })
}

export function opsCorrelations(params: { kind?: string; deleted?: boolean } = {}) {
  const q = new URLSearchParams()
  if (params.kind) q.set('kind', params.kind)
  if (params.deleted) q.set('deleted', 'true')
  const suffix = q.toString() ? `?${q.toString()}` : ''
  return api<OpsCorrelation[]>(`/operations/correlations${suffix}`, { action: 'Load code correlations' })
}

export function opsCorrelationReference() {
  return api<OpsCorrelationReference>('/operations/correlations/reference', {
    action: 'Load correlation reference',
  })
}

export function opsCreateCorrelation(data: OpsCorrelationInput) {
  return api<OpsCorrelation>('/operations/correlations', {
    method: 'POST',
    body: body(data),
    action: 'Correlate printed code',
  })
}

export function opsCreateCorrelationsBatch(items: OpsCorrelationInput[]) {
  return api<{ created_count: number; items: OpsCorrelation[] }>('/operations/correlations/batch', {
    method: 'POST',
    body: body({ items }),
    action: 'Batch correlate printed codes',
  })
}

export function opsUpdateCorrelation(id: string, data: OpsCorrelationUpdateInput) {
  return api<OpsCorrelation>(`/operations/correlations/${id}`, {
    method: 'PUT',
    body: body(data),
    action: 'Update code correlation',
  })
}

export function opsDeleteCorrelations(ids: string[]) {
  return api<{ affected_count: number }>('/operations/correlations/bulk-delete', {
    method: 'POST',
    body: body({ ids }),
    action: 'Delete code correlations',
  })
}

export function opsRestoreCorrelations(ids: string[]) {
  return api<{ affected_count: number }>('/operations/correlations/bulk-restore', {
    method: 'POST',
    body: body({ ids }),
    action: 'Restore code correlations',
  })
}

export function opsPurgeCorrelations(ids: string[]) {
  return api<{ affected_count: number }>('/operations/correlations/bulk-permanent-delete', {
    method: 'POST',
    body: body({ ids }),
    action: 'Permanently delete code correlations',
  })
}

export function opsCodeLinks(params: { scope?: string; deleted?: boolean } = {}) {
  const q = new URLSearchParams()
  if (params.scope) q.set('scope', params.scope)
  if (params.deleted) q.set('deleted', 'true')
  const suffix = q.toString() ? `?${q.toString()}` : ''
  return api<OpsCodeLink[]>(`/operations/code-links${suffix}`, { action: 'Load multi-criteria code links' })
}

export function opsCreateCodeLink(data: OpsCodeLinkInput) {
  return api<OpsCodeLink>('/operations/code-links', {
    method: 'POST',
    body: body(data),
    action: 'Link workspace codes',
  })
}

export function opsCreateCodeLinksBatch(items: OpsCodeLinkInput[]) {
  return api<{ created_count: number; items: OpsCodeLink[] }>('/operations/code-links/batch', {
    method: 'POST',
    body: body({ items }),
    action: 'Batch link workspace codes',
  })
}

export function opsUpdateCodeLink(id: string, data: OpsCodeLinkInput) {
  return api<OpsCodeLink>(`/operations/code-links/${id}`, {
    method: 'PUT',
    body: body(data),
    action: 'Update workspace code link',
  })
}

export function opsDeleteCodeLinks(ids: string[]) {
  return api<{ affected_count: number }>('/operations/code-links/bulk-delete', {
    method: 'POST',
    body: body({ ids }),
    action: 'Delete workspace code links',
  })
}

export function opsRestoreCodeLinks(ids: string[]) {
  return api<{ affected_count: number }>('/operations/code-links/bulk-restore', {
    method: 'POST',
    body: body({ ids }),
    action: 'Restore workspace code links',
  })
}

export function opsPurgeCodeLinks(ids: string[]) {
  return api<{ affected_count: number }>('/operations/code-links/bulk-permanent-delete', {
    method: 'POST',
    body: body({ ids }),
    action: 'Permanently delete workspace code links',
  })
}

export function opsPurgeMasters(kind: string, ids: string[]) {
  return api<{ affected_count: number }>(`/operations/masters/${kind}/bulk-permanent-delete`, {
    method: 'POST',
    body: body({ ids }),
    action: 'Permanently delete codes',
  })
}

/** Format rotating ROP consistently: completions always return 'N/A'; drilling formats or shows fallback. */
export function formatOpsRop(
  value: number | string | null | undefined,
  isCompletion: boolean,
  suffix = ' m/h',
  fallback = '—',
  decimals?: number,
): string {
  if (isCompletion) return 'N/A'
  if (value === null || value === undefined || value === '') return fallback
  const num = typeof value === 'number' ? value : Number(value)
  if (!Number.isFinite(num)) return fallback
  const formatted =
    decimals !== undefined
      ? num.toFixed(decimals)
      : Number(num.toFixed(3)).toLocaleString('en-US', { maximumFractionDigits: 3 })
  return `${formatted}${suffix}`
}

export type TimeDepthAxisOverrides = {
  xMin?: string
  xMax?: string
  xStep?: string
  yMin?: string
  yMax?: string
  yStep?: string
}

export type ComputedTimeDepthAxes = {
  xMin: number
  xMax: number
  xStep: number
  yMin: number
  yMax: number
  yStep: number
  defaultXStep: number
  defaultYStep: number
  defaultXMax: number
  defaultYMax: number
  isCustom: boolean
  warning: string
}

function pickCompletionStep(maxActivity: number): number {
  if (maxActivity <= 12) return 1
  if (maxActivity <= 24) return 2
  if (maxActivity <= 36) return 3
  if (maxActivity <= 60) return 5
  if (maxActivity <= 120) return 10
  return Math.max(10, Math.ceil(maxActivity / 12 / 5) * 5)
}

function pickDayStep(spanDays: number): number {
  if (spanDays <= 3) return 0.5
  if (spanDays <= 12) return 1
  if (spanDays <= 24) return 2
  if (spanDays <= 60) return 5
  if (spanDays <= 120) return 10
  if (spanDays <= 240) return 20
  if (spanDays <= 450) return 30
  return Math.max(50, Math.ceil(spanDays / 10 / 25) * 25)
}

function parseFinite(raw?: string): number | null {
  if (raw === undefined) return null
  const trimmed = raw.trim()
  if (!trimmed) return null
  const n = Number(trimmed)
  return Number.isFinite(n) ? n : Number.NaN
}

/**
 * Compute crisp, non-overlapping X (days) and Y (depth m or completion activity #)
 * bounds and intervals, applying optional user-specified min, max, and step overrides.
 */
export function computeTimeDepthAxes(params: {
  mode: 'depth' | 'activity'
  xValues: number[]
  yValues: number[]
  overrides?: TimeDepthAxisOverrides
}): ComputedTimeDepthAxes {
  const { mode, xValues, yValues, overrides = {} } = params
  const cleanX = xValues.filter((n) => Number.isFinite(n) && n >= 0)
  const cleanY = yValues.filter((n) => Number.isFinite(n) && n >= 0)
  const rawMaxX = cleanX.length ? Math.max(...cleanX) : 10
  const rawMaxY = cleanY.length ? Math.max(...cleanY) : mode === 'activity' ? 10 : 300

  const defaultYStep = mode === 'activity' ? pickCompletionStep(rawMaxY) : 300
  const defaultYMin = 0
  const defaultYMax =
    mode === 'activity'
      ? Math.max(defaultYStep, Math.ceil(Math.max(rawMaxY, 1) / defaultYStep) * defaultYStep)
      : Math.max(300, Math.ceil((rawMaxY + 1) / defaultYStep) * defaultYStep)

  const defaultXStep = pickDayStep(rawMaxX)
  const defaultXMin = 0
  const defaultXMax = Math.max(defaultXStep, Math.ceil(Math.max(rawMaxX, defaultXStep) / defaultXStep) * defaultXStep)

  const warnings: string[] = []
  const rawEntries = [overrides.xMin, overrides.xMax, overrides.xStep, overrides.yMin, overrides.yMax, overrides.yStep]
  const isCustom = rawEntries.some((v) => Boolean(v && v.trim() !== ''))

  const applyAxis = (
    axisName: string,
    defMin: number,
    defMax: number,
    defStep: number,
    rawMin: string | undefined,
    rawMax: string | undefined,
    rawStep: string | undefined,
    rawDataMax: number,
    integerOnly: boolean,
  ): { min: number; max: number; step: number } => {
    const pMin = parseFinite(rawMin)
    const pMax = parseFinite(rawMax)
    const pStep = parseFinite(rawStep)

    let step = defStep
    if (pStep !== null) {
      if (Number.isNaN(pStep) || pStep <= 0) {
        warnings.push(`${axisName} step must be a positive number.`)
      } else if (integerOnly && !Number.isInteger(pStep)) {
        step = Math.max(1, Math.round(pStep))
        warnings.push(`${axisName} uses whole-number activity steps (rounded to ${step}).`)
      } else {
        step = pStep
      }
    }

    let min = defMin
    if (pMin !== null) {
      if (Number.isNaN(pMin) || pMin < 0) {
        warnings.push(`${axisName} minimum must be zero or greater.`)
      } else {
        min = integerOnly ? Math.floor(pMin) : pMin
      }
    }

    let max =
      pStep !== null && pMax === null
        ? Math.max(min + step, Math.ceil(Math.max(rawDataMax, min + step) / step) * step)
        : defMax
    if (pMax !== null) {
      if (Number.isNaN(pMax)) {
        warnings.push(`${axisName} maximum must be a valid number.`)
      } else {
        max = integerOnly ? Math.ceil(pMax) : pMax
      }
    }

    if (max <= min) {
      warnings.push(`${axisName} maximum must be greater than minimum; automatic range retained.`)
      min = defMin
      max = Math.max(defMax, defMin + step)
    }

    const tickCount = (max - min) / step
    if (tickCount > 120) {
      const safeStep = integerOnly
        ? Math.max(1, Math.ceil((max - min) / 20))
        : Number(((max - min) / 20).toPrecision(2))
      warnings.push(`${axisName} step is too fine for the selected range; adjusted to ${safeStep} to prevent label overlap.`)
      step = safeStep
    }
    return { min, max, step }
  }

  const x = applyAxis(
    'Time axis (days)',
    defaultXMin,
    defaultXMax,
    defaultXStep,
    overrides.xMin,
    overrides.xMax,
    overrides.xStep,
    rawMaxX,
    false,
  )
  const y = applyAxis(
    mode === 'activity' ? 'Activity axis' : 'Depth axis (m)',
    defaultYMin,
    defaultYMax,
    defaultYStep,
    overrides.yMin,
    overrides.yMax,
    overrides.yStep,
    rawMaxY,
    mode === 'activity',
  )

  return {
    xMin: x.min,
    xMax: x.max,
    xStep: x.step,
    yMin: y.min,
    yMax: y.max,
    yStep: y.step,
    defaultXStep,
    defaultYStep,
    defaultXMax,
    defaultYMax,
    isCustom,
    warning: warnings.join(' '),
  }
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

/** One entry of the drilling engineering study books, with its citation. */
export type OpsStudyEntry = {
  key: string
  title: string
  topic: string
  summary: string
  formula: string
  symbols: string[]
  applies_to: string
  checks: string[]
  citations: string[]
  follow_ups: string[]
}

export type OpsStudyLibrary = {
  sources: { key: string; author: string; title: string }[]
  topics: { topic: string; label: string; entries: OpsStudyEntry[] }[]
}

/** The study books as reference material: readable without a model in the loop. */
export const opsGuideStudy = () =>
  api<OpsStudyLibrary>('/operations/guide/study', { action: 'Load the study library' })

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

const allocationNames: Record<string, string> = {
  PT: 'Productive Time', NPT: 'Non-Productive Time', UPA: 'Unplanned Activity', SP: 'Slow Progress',
}
export const allocationName = (value: string) => allocationNames[value] || ''

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
  hole_section_label: string
  start_wat: string
  end_wat: string
  duration_minutes: number
  duration_hours: number
  cum_hours: number
  cum_days: number
  phase_code: string
  phase_label: string
  sub_phase: string
  sub_phase_label: string
  /** The Activity, with the Activity type it stands for. */
  activity_label: string
  activity_type: string
  /** The Code Library Operations code and its full label. */
  operation_label: string
  operation_code: string
  operation_name: string
  operations: string
  classification: string
  allocation: string
  is_productive: boolean
  cause: string
  cause_code: string
  responsible_party: string
  responsible_agency_label: string
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
  id: string
  classification: string
  allocation: string
  responsible_party: string
  code: string
  cause: string
  cause_code: string
  events: number
  hours: number
  days: number
  pct_of_total: number
  pct_of_npt: number
  sample_reason: string
}

export type OpsSummaryPhase = {
  id: string
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
