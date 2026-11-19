/**
 * The seven workspace code criteria that a multi-criteria link can join, and
 * that a printed-code correlation can pre-select as companion fields.
 *
 * The server owns the rule; these constants only name the fields the API
 * exposes (`linkId` on `OpsCodeLink`, `corrId` on `OpsCodeCorrelation`) so a
 * page never guesses a column name.
 */
export type CriterionKey = 'phase' | 'operation' | 'activity' | 'npt' | 'cause' | 'agency' | 'mark'

export type Criterion = {
  key: CriterionKey
  label: string
  /** Key inside `OpsCorrelationReference.library`. */
  library: string
  /** Request/response field on a multi-criteria code link. */
  linkId: string
  /** Companion field on a printed-code correlation. */
  corrId: string
  /** Hydrated label field on `OpsCodeLink`. */
  linkLabel: string
}

export const CRITERIA: Criterion[] = [
  { key: 'phase', label: 'Phase', library: 'phase', linkId: 'phase_code_id', corrId: 'target_phase_code_id', linkLabel: 'phase_label' },
  { key: 'operation', label: 'Operation', library: 'operation', linkId: 'operation_code_id', corrId: 'target_operation_code_id', linkLabel: 'operation_label' },
  { key: 'activity', label: 'Activity', library: 'activity', linkId: 'activity_code_id', corrId: 'target_activity_code_id', linkLabel: 'activity_label' },
  { key: 'npt', label: 'NPT', library: 'npt', linkId: 'npt_code_id', corrId: 'target_npt_code_id', linkLabel: 'npt_label' },
  { key: 'cause', label: 'Cause', library: 'cause', linkId: 'cause_id', corrId: 'target_cause_id', linkLabel: 'cause_label' },
  { key: 'agency', label: 'Agency', library: 'agency', linkId: 'agency_id', corrId: 'target_agency_id', linkLabel: 'agency_label' },
  { key: 'mark', label: 'Source mark', library: 'mark', linkId: 'mark_rule_id', corrId: 'target_mark_rule_id', linkLabel: 'mark_label' },
]

export const criterionFor = (key: string) => CRITERIA.find((c) => c.key === key)

/** Master-library kind (the `/operations/masters/{kind}` path) -> correlation kind. */
export const CORRELATION_KIND_FOR_MASTER: Record<string, string> = {
  'operation-codes': 'operation',
  'activity-codes': 'activity',
  'npt-codes': 'npt',
  causes: 'cause',
  'phase-codes': 'phase',
  agencies: 'agency',
}

/** Correlation kinds carry no source-mark family: a printed mark is a source mark rule. */
export const CORRELATION_KINDS = [
  { key: 'operation', label: 'Operation code' },
  { key: 'activity', label: 'Activity code' },
  { key: 'npt', label: 'NPT code' },
  { key: 'cause', label: 'Cause code' },
  { key: 'phase', label: 'Phase (and programme phase)' },
  { key: 'agency', label: 'Agency' },
] as const

export const SCOPES = [
  { key: '', label: 'Every scope' },
  { key: 'drilling', label: 'Drilling' },
  { key: 'completion', label: 'Completion' },
] as const

export const CLASSES = ['', 'Planned', 'UPA', 'NPT'] as const
export const ALLOCATIONS = ['', 'PT', 'UPA', 'NPT', 'SP'] as const

/** Every criterion value carried by a hydrated `OpsCodeLink`, in display order. */
export function linkCriteria(link: Record<string, unknown>): { key: CriterionKey; label: string }[] {
  return CRITERIA.flatMap((c) => {
    if (!link[c.linkId]) return []
    const value = String(link[c.linkLabel] ?? '') || String(link[c.linkId])
    return [{ key: c.key, label: `${c.label}: ${value}` }]
  })
}

/** A printed catalogue token is unique per family, so the option key is composite. */
export const printedKey = (family: string, code: string) => `${family}::${code}`

/**
 * Client-side mirror of the server's `_check_classification_matrix`, so the dialog
 * can refuse early with the same sentence. Keep the three rules in the server's
 * order: the first violated rule is the one the engineer should read.
 */
export function classificationProblem(classification: string, allocation: string, nptSelected: boolean): string {
  if ((classification === 'Planned' || classification === 'UPA') && nptSelected) {
    return 'An NPT code applies only when the classification is NPT (or unset).'
  }
  if (allocation === 'NPT' && (classification === 'Planned' || classification === 'UPA')) {
    return 'NPT allocation requires NPT classification.'
  }
  if (classification === 'NPT' && allocation === 'PT') {
    return 'NPT classification cannot be paired with PT allocation.'
  }
  return ''
}

/** Narrowed casts for the MUI selects, whose values arrive as plain strings. */
export const asScope = (value: string) => value as '' | 'drilling' | 'completion'
export const asClassification = (value: string) => value as '' | 'Planned' | 'UPA' | 'NPT'
export const asAllocation = (value: string) => value as '' | 'PT' | 'UPA' | 'NPT' | 'SP'
