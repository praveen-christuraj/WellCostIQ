/**
 * Cost Intelligence: response shapes and the small formatting rules shared by
 * the page, its export and its check. The analysis itself runs on the server
 * (`backend/app/domain/cost_intelligence.py`); nothing here derives a finding.
 */
export type Severity = 'critical' | 'warning' | 'info'
export type FindingCategory = 'budget' | 'trend' | 'anomaly' | 'schedule' | 'npt' | 'data-quality'
export type HealthBand = 'good' | 'watch' | 'at-risk'

export type IntelligenceFinding = {
  id: string; code: string; severity: Severity; category: FindingCategory
  title: string; detail: string; basis: string; suggestion: string
  well_id: string; well_code: string; cost_date: string | null; amount: number | null
  evidence: { label: string; value: string }[]
  action_path: string; action_label: string
}
export type IntelligenceForecast = {
  available: boolean; reason: string; recent_daily: number | null; planned_daily: number | null
  remaining_days: number | null; estimate: number | null; low: number | null; high: number | null
  variance: number | null; variance_percent: number | null; exhaustion_date: string | null
  days_to_exhaustion: number | null; past_plan: boolean
}
export type IntelligenceWell = {
  well_id: string; well_code: string; well_name: string; rig_code: string; status: string; currency: string
  afe_amount: number | null; actual_amount: number | null; utilisation_percent: number | null
  planned_days: number | null; actual_days: number | null; npt_amount: number | null; npt_share_percent: number | null
  recorded_days: number; first_cost_date: string | null; last_cost_date: string | null
  score: number; band: HealthBand; critical: number; warning: number; info: number
  summary: string; forecast: IntelligenceForecast; analysed: boolean
}
export type IntelligenceDay = {
  cost_date: string; actual: number; cumulative: number; npt: number; baseline: number | null
  planned_cumulative: number | null; cusum_up: number | null; cusum_down: number | null; spike: boolean
}
export type IntelligenceWellDetail = {
  well: IntelligenceWell; findings: IntelligenceFinding[]; days: IntelligenceDay[]
  projection: { cost_date: string; estimate: number; low: number; high: number }[]
  missing_dates: string[]; cusum_limit: number; drift_baseline: number | null
  drift_start: string | null; drift_direction: string; notes: string[]
}
export type IntelligenceOverview = {
  generated_at: string; as_of: string; date_from: string | null; date_to: string | null; currency: string
  capabilities: { budget: boolean; actuals: boolean; plan: boolean; export: boolean }
  kpis: {
    wells: number; analysed_wells: number; afe_amount: number | null; actual_amount: number | null
    forecast_amount: number | null; forecast_variance: number | null; forecast_variance_percent: number | null
    amount_at_risk: number | null; critical: number; warning: number; info: number; wells_at_risk: number
    score: number; band: HealthBand
  }
  headline: string[]; wells: IntelligenceWell[]; findings: IntelligenceFinding[]
  suggestions: {
    rank: number; severity: Severity; well_id: string; well_code: string; title: string; suggestion: string
    amount: number | null; action_path: string; action_label: string; finding_id: string
  }[]
  by_category: { key: FindingCategory; label: string; critical: number; warning: number; info: number }[]
  notes: string[]; methods: string[]
}

export const SEVERITY_LABEL: Record<Severity, string> = { critical: 'Critical', warning: 'Warning', info: 'Note' }
export const SEVERITY_TONE: Record<Severity, 'error' | 'warning' | 'info'> = { critical: 'error', warning: 'warning', info: 'info' }
export const BAND_LABEL: Record<HealthBand, string> = { good: 'Good', watch: 'Watch', 'at-risk': 'At risk' }
export const BAND_TONE: Record<HealthBand, 'success' | 'warning' | 'error'> = { good: 'success', watch: 'warning', 'at-risk': 'error' }
export const CATEGORY_LABEL: Record<FindingCategory, string> = {
  budget: 'Budget and forecast', trend: 'Cost trend', anomaly: 'Unusual days', schedule: 'Schedule',
  npt: 'Non-productive time', 'data-quality': 'Record quality',
}

/** Whole currency units: analysis figures are estimates, cents would overstate them. */
export function amount(value: number | null | undefined, currency = ''): string {
  if (value === null || value === undefined || !Number.isFinite(value)) return '—'
  const text = Math.abs(value).toLocaleString(undefined, { maximumFractionDigits: 0 })
  return `${value < 0 ? '−' : ''}${currency ? `${currency} ` : ''}${text}`
}

export function signedPercent(value: number | null | undefined): string {
  if (value === null || value === undefined || !Number.isFinite(value)) return '—'
  return `${value > 0 ? '+' : value < 0 ? '−' : ''}${Math.abs(value).toFixed(1)}%`
}

/** Report sections a reader can switch on or off before exporting. */
export const REPORT_SECTIONS = [
  { key: 'summary', label: 'Summary and key figures' },
  { key: 'actions', label: 'Suggested actions' },
  { key: 'wells', label: 'Well health and forecast' },
  { key: 'findings', label: 'All findings with their basis' },
  { key: 'well', label: 'Selected well analysis' },
  { key: 'methods', label: 'How the analysis works' },
] as const
export type ReportSectionKey = typeof REPORT_SECTIONS[number]['key']
export const REPORT_PRESETS: Record<string, { label: string; sections: ReportSectionKey[] }> = {
  brief: { label: 'Management brief', sections: ['summary', 'actions', 'wells'] },
  full: { label: 'Full analysis', sections: ['summary', 'actions', 'wells', 'findings', 'well', 'methods'] },
  audit: { label: 'Record quality review', sections: ['summary', 'findings', 'methods'] },
}

/** Filter the findings exactly as the page shows them; the export uses the same rows. */
export function filterFindings(
  rows: IntelligenceFinding[],
  filters: { severity: string; category: string; wellId: string; search: string },
): IntelligenceFinding[] {
  const needle = filters.search.trim().toLowerCase()
  return rows.filter(row =>
    (!filters.severity || row.severity === filters.severity)
    && (!filters.category || row.category === filters.category)
    && (!filters.wellId || row.well_id === filters.wellId)
    && (!needle || `${row.well_code} ${row.title} ${row.detail} ${row.suggestion}`.toLowerCase().includes(needle)))
}
