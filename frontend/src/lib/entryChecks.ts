import { api, body } from './api'
import type { DailyCostSavePayload } from './dailyCost'
import type { DepthUnit } from './units'

// ---------------------------------------------------------------------------
// Entry checks on the daily cost sheet.
//
// The API compares each entered value with the other sheets of the same AFE,
// the locked AFE figures and the locked well plan, and returns the values that
// look mistyped. A finding is advice: it never blocks a save and it never
// changes a figure by itself. Where one keying slip explains the value, the
// finding carries the corrected value, and `applyEntryCheck` writes it into the
// unsaved sheet so the user still reviews and saves it.
// ---------------------------------------------------------------------------

/** Where a line lives inside the sheet's save payload. */
export type EntryCheckGroup = 'services' | 'consumables' | 'tangibles' | 'other_expenses'
export type EntryCheckLine = { group: EntryCheckGroup; index: number }
/** The entered field a finding is about; empty when it is about the sheet as a whole. */
export type EntryCheckField =
  | '' | 'quantity' | 'quantity_unit' | 'override_rate' | 'exchange_rate'
  | 'actual_depth' | 'actual_depth_unit' | 'usd_exchange_rate'
/** What the value was compared with. */
export type EntryCheckScope = 'afe' | 'workspace' | 'baseline' | 'plan' | 'sheet'

export type EntryCheck = {
  /** Stable identity of the finding on its sheet. */
  key: string
  code: string
  severity: 'info' | 'warning'
  title: string
  message: string
  /** The evidence in one sentence. */
  basis: string
  scope: EntryCheckScope
  subject_label: string
  lines: EntryCheckLine[]
  field: EntryCheckField
  current_value: string | null
  current_display: string
  /** Present only when one keying slip explains the value. */
  suggested_value: string | null
  suggested_display: string
  apply_to: EntryCheckLine[]
  usual_display: string
  history_count: number
  /** Identifies the exact value a review accepts. */
  fingerprint: string
  reviewed: boolean
  reviewed_by: string
  reviewed_at: string | null
  review_note: string
}

export type EntryChecksResult = {
  entry_id: string
  /** False when the deployment has turned entry checks off. */
  enabled: boolean
  checks: EntryCheck[]
  open_warnings: number
  open_notices: number
  reviewed: number
  /** Other sheets of the same AFE the values were compared with. */
  history_sheets: number
}

export type SheetEntryChecks = {
  entry_id: string
  daily_cost_code: string
  cost_date: string
  status: string
  afe_code: string
  open_warnings: number
  open_notices: number
  reviewed: number
  checks: EntryCheck[]
}

export type WellEntryChecks = {
  well_id: string
  enabled: boolean
  sheets_checked: number
  sheets_with_findings: number
  open_warnings: number
  open_notices: number
  reviewed: number
  /** True when the well has more sheets than one review covers. */
  truncated: boolean
  sheets: SheetEntryChecks[]
}

export const ENTRY_CHECK_GROUPS: EntryCheckGroup[] = ['services', 'consumables', 'tangibles', 'other_expenses']
export const ENTRY_CHECK_GROUP_LABEL: Record<EntryCheckGroup, string> = {
  services: 'Services', consumables: 'Consumables', tangibles: 'Tangibles', other_expenses: 'Other expenses',
}

/** The wording of a severity, so that it never depends on colour alone. */
export function entryCheckSeverityLabel(check: Pick<EntryCheck, 'severity' | 'reviewed'>): string {
  if (check.reviewed) return 'Kept as entered'
  return check.severity === 'warning' ? 'Check' : 'Note'
}

export type EntryCheckCounts = { warnings: number; notices: number; reviewed: number; open: number }

export function entryCheckCounts(checks: readonly EntryCheck[]): EntryCheckCounts {
  let warnings = 0
  let notices = 0
  let reviewed = 0
  for (const check of checks) {
    if (check.reviewed) reviewed += 1
    else if (check.severity === 'warning') warnings += 1
    else notices += 1
  }
  return { warnings, notices, reviewed, open: warnings + notices }
}

/** "2 to check, 1 to note" — open findings in words. */
export function entryCheckSummary(counts: EntryCheckCounts): string {
  const parts: string[] = []
  if (counts.warnings) parts.push(`${counts.warnings} to check`)
  if (counts.notices) parts.push(`${counts.notices} to note`)
  return parts.join(', ')
}

const sameNumber = (left: string | null | undefined, right: string | null | undefined): boolean => {
  if (left === null || left === undefined || left === '' || right === null || right === undefined || right === '') return false
  const a = Number(left)
  const b = Number(right)
  return Number.isFinite(a) && Number.isFinite(b) && a === b
}

type AnyLine = DailyCostSavePayload[EntryCheckGroup][number]

/** One line with the suggested value written into it, or null when it does not fit that line. */
function correctedLine(line: AnyLine, group: EntryCheckGroup, check: EntryCheck, value: string, single: boolean): AnyLine | null {
  switch (check.field) {
    case 'quantity':
      // A finding about one line names the value it saw; refuse a line that has moved on.
      if (single && !sameNumber(line.quantity, check.current_value)) return null
      return { ...line, quantity: value }
    case 'quantity_unit':
      if (!('quantity_unit' in line)) return null
      if (single && check.current_value && line.quantity_unit !== check.current_value) return null
      return { ...line, quantity_unit: value } as AnyLine
    case 'override_rate':
      if (group === 'other_expenses' || line.override_rate === null) return null
      if (single && !sameNumber(line.override_rate, check.current_value)) return null
      return { ...line, override_rate: value }
    case 'exchange_rate':
      return { ...line, exchange_rate: value }
    case 'actual_depth':
      if (line.actual_depth === null || line.actual_depth === undefined || line.actual_depth === '') return null
      return { ...line, actual_depth: value }
    case 'actual_depth_unit':
      if (value !== 'm' && value !== 'ft') return null
      if (line.actual_depth === null || line.actual_depth === undefined || line.actual_depth === '') return null
      return { ...line, actual_depth_unit: value as DepthUnit }
    default:
      return null
  }
}

/**
 * The save payload with a finding's suggestion written into it.
 *
 * Returns null when the finding offers nothing to apply or no longer matches
 * the sheet (a line was removed, or its value changed after the finding was
 * made); the caller then leaves the sheet untouched.
 */
export function applyEntryCheck(payload: DailyCostSavePayload, check: EntryCheck): DailyCostSavePayload | null {
  const value = check.suggested_value
  if (value === null || value === '' || !check.field) return null
  if (check.field === 'usd_exchange_rate') return { ...payload, usd_exchange_rate: value }
  if (!check.apply_to.length) return null
  const single = check.apply_to.length === 1
  const next: DailyCostSavePayload = { ...payload }
  for (const group of ENTRY_CHECK_GROUPS) {
    const targets = new Set(check.apply_to.filter(line => line.group === group).map(line => line.index))
    if (!targets.size) continue
    const rows = payload[group] as AnyLine[]
    const updated: AnyLine[] = []
    for (let index = 0; index < rows.length; index += 1) {
      if (!targets.has(index)) { updated.push(rows[index]); continue }
      const corrected = correctedLine(rows[index], group, check, value, single)
      if (corrected === null) return null
      updated.push(corrected)
      targets.delete(index)
    }
    // A target beyond the end of the group: the sheet changed after the finding.
    if (targets.size) return null
    ;(next as Record<EntryCheckGroup, AnyLine[]>)[group] = updated
  }
  return next
}

/** Whether a finding offers a correction that `applyEntryCheck` can write. */
export function hasSuggestion(check: EntryCheck): boolean {
  return Boolean(check.suggested_value) && Boolean(check.field)
    && (check.field === 'usd_exchange_rate' || check.apply_to.length > 0)
}

export function fetchEntryChecks(entryId: string, signal?: AbortSignal): Promise<EntryChecksResult> {
  // Background advice beside the sheet: a failure is shown in the panel itself
  // with a retry, so it does not also raise the global error pop-up.
  return api<EntryChecksResult>(`/daily-cost/entries/${entryId}/checks`, {
    signal, silent: true, action: 'Load the entry checks',
  })
}

/** Keep the values behind these findings as entered. Draft sheets only; audited. */
export function reviewEntryChecks(entryId: string, checks: readonly EntryCheck[], note: string): Promise<EntryChecksResult> {
  return api<EntryChecksResult>(`/daily-cost/entries/${entryId}/checks/review`, {
    method: 'POST', action: 'Keep the value as entered',
    body: body({ items: checks.map(check => ({ key: check.key, fingerprint: check.fingerprint })), note: note.trim() }),
  })
}

/** Withdraw reviews so the findings are open again. Draft sheets only; audited. */
export function reopenEntryChecks(entryId: string, keys: readonly string[]): Promise<EntryChecksResult> {
  return api<EntryChecksResult>(`/daily-cost/entries/${entryId}/checks/reopen`, {
    method: 'POST', action: 'Reopen the entry check', body: body({ keys }),
  })
}

export function fetchWellEntryChecks(wellId: string, afeId?: string, signal?: AbortSignal): Promise<WellEntryChecks> {
  const query = afeId ? `?afe_id=${encodeURIComponent(afeId)}` : ''
  return api<WellEntryChecks>(`/daily-cost/wells/${wellId}/checks${query}`, {
    signal, silent: true, action: 'Load the entry checks of the well',
  })
}
