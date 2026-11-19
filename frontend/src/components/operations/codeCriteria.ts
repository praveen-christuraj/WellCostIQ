/**
 * The workspace criteria a multi-criteria link can join, and that a
 * printed-code correlation can pre-select as companion fields.
 *
 * The order is the order the daily report lists the fields: Hole Section,
 * Phase, Sub-phase, Activity, Operations, Cause, responsible agency label,
 * Agency / service vendor, Source mark. Hole Section, Phase, Activity and the
 * vendor come from Master Data; Sub-phase, Operations, Cause, the responsible
 * agency label and the Source mark are configured in the Code Library.
 *
 * The server owns the rule; these constants only name the fields the API
 * exposes (`linkId` on `OpsCodeLink`, `corrId` on `OpsCodeCorrelation`) so a
 * page never guesses a column name.
 */
export type CriterionKey =
  | 'hole_section'
  | 'phase'
  | 'sub_phase'
  | 'activity'
  | 'operation'
  | 'cause'
  | 'responsible_agency'
  | 'vendor'
  | 'mark'

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
  /** Where the list is maintained, so the page can say where to add a value. */
  source: 'master' | 'library'
  /** Master Data module path for a Master Data criterion. */
  masterPath?: string
}

export const CRITERIA: Criterion[] = [
  {
    key: 'hole_section',
    label: 'Hole Section',
    library: 'hole_section',
    linkId: 'hole_section_id',
    corrId: 'target_hole_section_id',
    linkLabel: 'hole_section_label',
    source: 'master',
    masterPath: '/master-data/hole-sections',
  },
  {
    key: 'phase',
    label: 'Phase',
    library: 'phase',
    linkId: 'phase_id',
    corrId: 'target_phase_id',
    linkLabel: 'phase_label',
    source: 'master',
    masterPath: '/master-data/phases',
  },
  {
    key: 'sub_phase',
    label: 'Sub-Phase',
    library: 'sub_phase',
    linkId: 'sub_phase_id',
    corrId: 'target_sub_phase_id',
    linkLabel: 'sub_phase_label',
    source: 'library',
  },
  {
    key: 'activity',
    label: 'Activity',
    library: 'activity',
    linkId: 'activity_id',
    corrId: 'target_activity_id',
    linkLabel: 'activity_label',
    source: 'master',
    masterPath: '/master-data/activities',
  },
  {
    key: 'operation',
    label: 'Operations',
    library: 'operation',
    linkId: 'operation_id',
    corrId: 'target_operation_id',
    linkLabel: 'operation_label',
    source: 'library',
  },
  {
    key: 'cause',
    label: 'Cause Code',
    library: 'cause',
    linkId: 'cause_id',
    corrId: 'target_cause_id',
    linkLabel: 'cause_label',
    source: 'library',
  },
  {
    key: 'responsible_agency',
    label: 'Responsible Agency label',
    library: 'responsible_agency',
    linkId: 'responsible_agency_id',
    corrId: 'target_responsible_agency_id',
    linkLabel: 'responsible_agency_label',
    source: 'library',
  },
  {
    key: 'vendor',
    label: 'Agency / Service Vendor',
    library: 'vendor',
    linkId: 'vendor_id',
    corrId: 'target_vendor_id',
    linkLabel: 'vendor_label',
    source: 'master',
    masterPath: '/master-data/vendors',
  },
  {
    key: 'mark',
    label: 'Source mark',
    library: 'mark',
    linkId: 'mark_rule_id',
    corrId: 'target_mark_rule_id',
    linkLabel: 'mark_label',
    source: 'library',
  },
]

export const criterionFor = (key: string) => CRITERIA.find((c) => c.key === key)

/** Code Library master kind (the `/operations/masters/{kind}` path) -> correlation kind. */
export const CORRELATION_KIND_FOR_MASTER: Record<string, string> = {
  operations: 'operation',
  causes: 'cause',
  'sub-phases': 'sub-phase',
  agencies: 'responsible-party',
}

/** Correlation kinds carry no Hole Section, Phase or Activity: those are Master Data. */
export const CORRELATION_KINDS = [
  { key: 'operation', label: 'Operations' },
  { key: 'cause', label: 'Cause Code' },
  { key: 'sub-phase', label: 'Sub-Phase (and printed phase)' },
  { key: 'responsible-party', label: 'Responsible Agency label' },
  { key: 'agency', label: 'Agency / Service Vendor' },
] as const

export const SCOPES = [
  { key: '', label: 'Every scope' },
  { key: 'drilling', label: 'Drilling' },
  { key: 'completion', label: 'Completion' },
] as const

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
 * Client-side mirror of the server's Activity-type rules, so a dialog can refuse
 * early with the same sentence the API would return.
 *
 * The Activity carries the type, so a link may not pin a cause to Planned work:
 * nothing went wrong, and there would be nothing to explain. Allocation is a
 * separate axis and never stands in for the Activity type.
 */
export function activityTypeProblem(activityType: string, causeSelected: boolean, allocation: string): string {
  if (causeSelected && activityType === 'Planned') {
    return 'A Planned Activity never carries a cause. Select an NPT or UPA Activity, or leave the cause out.'
  }
  if (allocation === 'NPT' && activityType === 'Planned') {
    return 'NPT allocation requires an NPT Activity.'
  }
  if (activityType === 'NPT' && allocation === 'PT') {
    return 'An NPT Activity cannot be paired with PT allocation.'
  }
  return ''
}

/** Narrowed casts for the MUI selects, whose values arrive as plain strings. */
export const asScope = (value: string) => value as '' | 'drilling' | 'completion'
export const asActivityType = (value: string) => value as '' | 'Planned' | 'UPA' | 'NPT'
export const asAllocation = (value: string) => value as '' | 'PT' | 'UPA' | 'NPT' | 'SP'
