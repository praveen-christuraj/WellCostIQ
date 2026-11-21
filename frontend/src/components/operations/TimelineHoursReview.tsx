import { useMemo, useState } from 'react'
import {
  Alert,
  Box,
  Button,
  InputAdornment,
  MenuItem,
  Stack,
  TextField,
  Tooltip,
  Typography,
} from '@mui/material'
import { RestartAlt } from '@mui/icons-material'
import { PanelDialog } from '../Common'
import type { OpsSequenceState, ReviewTimelineResult } from '../../lib/operations'

/**
 * Editable plan-vs-actual hours: the review surface for lead and lag.
 *
 * The question this panel answers is "did this job take the hours the programme
 * allowed?" — and the answer is grouped by sequence code, because that is the
 * correlation the whole comparison rests on:
 *
 * * every line of the baseline programme carries a sequence code;
 * * a daily-report line opts in by carrying the same code (edit it in the
 *   register's Seq column, or apply one code to many lines with the bulk
 *   action);
 * * the panel sums the hours of the lines in each code and compares the total
 *   with the programme's planned hours for that code — positive variance is a
 *   lead, negative is a lag, and ``difference / 24`` is the figure in days.
 *
 * **Only a finished activity carries that verdict.** A code with 12 of its 100
 * hours logged is in progress: the panel shows 12 %, and the 88 hours it still
 * owes, instead of printing 88 hours of lead. Finishing the activity is a
 * separate, explicit act on the programme — it is what turns the hours into a
 * lead or a lag.
 *
 * Lines without a code are **Unplanned Activity**, not a footnote. Their hours
 * add to actual hours while planned hours stay put, so they can only ever read
 * as lag, and they are shown in their own row with that arithmetic.
 *
 * Only changed rows are posted, and a correction needs a reason, because the
 * value then differs from the time log. Clearing a field restores the logged
 * hours rather than zeroing them.
 *
 * The caller owns the request: the panel is a controlled editor and hands back
 * `{ review_state, note, hours }`, so the page can save, reload and show the
 * server's own arithmetic in its notice.
 */

export type TimelineHoursRow = {
  id: string
  sequence_no: number
  activity_label?: string
  phase_label?: string
  narrative?: string
  timeline_code?: string | null
  timeline_plan_step_no?: number | null
  timeline_plan_label?: string
  timeline_planned_hours?: string | null
  timeline_system_actual_hours?: string | null
  timeline_actual_hours?: string | null
  timeline_actual_edited?: boolean
  timeline_comparison?: 'ahead' | 'behind' | 'on'
  timeline_variance_hours?: string | null
  timeline_review_state?: 'suggested' | 'accepted' | 'edited' | 'rejected'
  /**
   * The state of the code this line logs, from the server's ledger. `in_progress`
   * and `overrun_open` carry no verdict; only `complete` does. `skipped` means the
   * planned work will never be done, so its hours are released, not counted as a lag.
   */
  timeline_sequence_state?: OpsSequenceState | ''
  /** `split` when this line's hours are shared between several codes. */
  timeline_split_state?: string
  timeline_basis?: string
}

export type TimelineHoursSubmission = {
  review_state: 'accepted' | 'edited' | 'rejected'
  note: string
  hours: { block_id: string; actual_hours: string | null }[]
}

/** A numeric string or null; null means the record holds no number, not a zero. */
function num(value: string | number | null | undefined): number | null {
  if (value === null || value === undefined || value === '') return null
  const parsed = Number(value)
  return Number.isFinite(parsed) ? parsed : null
}

/** Three decimals, the workspace's precision for hours. */
function hours(value: number | null): string {
  return value === null ? '—' : value.toFixed(3)
}

function normalise(value: string): string {
  const parsed = num(value)
  return parsed === null ? '' : parsed.toFixed(3)
}

const STATE_LABELS: Record<string, string> = {
  not_started: 'not started',
  in_progress: 'in progress',
  overrun_open: 'over plan, still open',
  complete: 'finished',
  skipped: 'skipped',
}

/** True only for a code the engineer has finished: the one state with a verdict. */
function hasVerdict(state: string | undefined): boolean {
  return state === 'complete'
}

/** What a group's verdict cell says, in words that cannot be misread as a lead. */
function stateSentence(state: string | undefined, planned: number | null, actual: number | null): string {
  const logged = actual === null ? 0 : actual
  const progress = planned !== null && planned > 0 ? Math.min(100, (logged / planned) * 100) : null
  const remaining = planned !== null ? Math.max(0, planned - logged) : null
  if (state === 'skipped') return 'skipped — planned hours released, not a lag'
  if (state === 'not_started') return 'not started'
  if (state === 'complete') return ''
  if (state === 'overrun_open') {
    return planned === null
      ? `over plan · ${logged.toFixed(3)} h logged, not finished`
      : `over plan by ${(logged - planned).toFixed(3)} h, not finished`
  }
  if (progress === null) return 'in progress · no planned hours to compare'
  return `in progress · ${logged.toFixed(3)} / ${planned?.toFixed(3)} h (${progress.toFixed(0)}%) · ${remaining?.toFixed(3)} h remaining`
}

export function TimelineHoursReview({
  open,
  rows,
  busy,
  error,
  canEdit,
  onClose,
  onSubmit,
}: {
  open: boolean
  /** The blocks in scope; the caller's selection is applied before opening. */
  rows: TimelineHoursRow[]
  busy?: boolean
  error?: string
  /** False when the report is no longer a draft — the panel then reads only. */
  canEdit?: boolean
  onClose: () => void
  onSubmit: (submission: TimelineHoursSubmission) => Promise<ReviewTimelineResult | void> | void
}) {
  const editable = canEdit !== false
  const [draft, setDraft] = useState<Record<string, string>>({})
  const [note, setNote] = useState('')
  const [state, setState] = useState<'accepted' | 'edited' | 'rejected'>('accepted')
  const [rowsError, setRowsError] = useState('')

  /** reset whenever the panel (re)opens so a cancelled edit never leaks back */
  const [openedFor, setOpenedFor] = useState(false)
  if (open && !openedFor) {
    setOpenedFor(true)
    setDraft({})
    setNote('')
    setState('accepted')
    setRowsError('')
  }
  if (!open && openedFor) setOpenedFor(false)

  const systemOf = (row: TimelineHoursRow) =>
    num(row.timeline_system_actual_hours) ?? num(row.timeline_actual_hours)

  /** What the row's actual hours are after this session's typing. */
  const actualOf = (row: TimelineHoursRow): number | null => {
    const typed = draft[row.id]
    if (typed === undefined) return num(row.timeline_actual_hours) ?? systemOf(row)
    return num(typed)
  }

  const changed = useMemo(
    () =>
      rows
        .map((row) => {
          const typed = draft[row.id]
          if (typed === undefined) return null
          const before = normalise(String(num(row.timeline_actual_hours) ?? systemOf(row) ?? ''))
          const after = normalise(typed)
          if (before === after) return null
          return { block_id: row.id, actual_hours: after === '' ? null : after }
        })
        .filter((row): row is { block_id: string; actual_hours: string | null } => row !== null),
    // `systemOf` is pure over the row records; only the draft and rows matter.
    // eslint-disable-next-line react-hooks/exhaustive-deps
    [draft, rows],
  )

  /**
   * Group the rows by sequence code: coded groups first in code order, the
   * unplanned group last. The group is the unit lead/lag is computed on, so the
   * panel adds up by code, never by line — planned hours belong to the
   * programme row, not to any single line that logs against it.
   *
   * The group's *state* comes from the server's ledger, not from the hours on
   * this screen: whether an activity is finished is a fact about the programme,
   * decided by a person, and no amount of typing here changes it.
   */
  const groups = useMemo(() => {
    const byCode = new Map<string, TimelineHoursRow[]>()
    for (const row of rows) {
      const code = (row.timeline_code ?? '').trim()
      const list = byCode.get(code) ?? []
      list.push(row)
      byCode.set(code, list)
    }
    const entries = Array.from(byCode.entries()).map(([code, members]) => {
      members.sort((a, b) => a.sequence_no - b.sequence_no)
      const plannedRaw = members.map((m) => m.timeline_planned_hours).find((v) => v !== null && v !== undefined)
      const planned = num(plannedRaw ?? null)
      const actualSum = members.reduce((sum, m) => sum + (actualOf(m) ?? 0), 0)
      const hasActual = members.some((m) => actualOf(m) !== null)
      const actual = hasActual ? actualSum : null
      // A verdict exists only for a finished activity that has planned hours.
      const state = code === '' ? '' : (members[0]?.timeline_sequence_state ?? '')
      const variance = hasVerdict(state) && planned !== null && actual !== null ? planned - actual : null
      const codeNo = /^\d+$/.test(code) ? Number(code) : Number.POSITIVE_INFINITY
      return { code, members, planned, actual, variance, state, codeNo }
    })
    entries.sort((a, b) => (a.code === '' ? 1 : b.code === '' ? -1 : a.codeNo - b.codeNo))
    return entries
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [rows, draft])

  /** Running per-code sum of logged hours; a reader adds a code up by hand. */
  const running = useMemo(() => {
    const map = new Map<string, number | null>()
    for (const group of groups) {
      let sum = 0
      let seen = false
      for (const row of group.members) {
        const a = actualOf(row)
        if (a !== null) {
          sum += a
          seen = true
        }
        map.set(row.id, seen ? sum : null)
      }
    }
    return map
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [groups])

  /**
   * Totals that cannot flatter the month.
   *
   * `verdict` is the printed lead/lag: the sum of the *finished* activities'
   * variances, less the hours nobody could code. `burn` is how much of the plan
   * has been spent — a different question, named as such, and deliberately never
   * added to `verdict`. A plan with nothing finished has no verdict at all.
   */
  const totals = useMemo(() => {
    let planned = 0
    let actual = 0
    let verdict = 0
    let finished = 0
    let open = 0
    let unplanned = 0
    let skipped = 0
    let matched = 0
    let uncoded = 0
    let corrected = 0
    for (const group of groups) {
      if (group.code === '') {
        uncoded += group.members.length
        unplanned += group.actual ?? 0
        continue
      }
      matched += 1
      if (group.state === 'skipped') {
        skipped += 1
        continue
      }
      if (group.planned !== null) planned += group.planned
      if (group.actual !== null) actual += group.actual
      if (hasVerdict(group.state)) {
        finished += 1
        if (group.variance !== null) verdict += group.variance
      } else {
        open += 1
      }
    }
    for (const row of rows) {
      if (row.timeline_actual_edited || draft[row.id] !== undefined) corrected += 1
    }
    const realised = verdict - unplanned
    return {
      planned,
      actual,
      realised,
      hasVerdict: finished > 0,
      finished,
      open,
      unplanned,
      skipped,
      matched,
      uncoded,
      corrected,
      burn: actual + unplanned,
    }
  }, [groups, rows, draft])

  /** The decision follows the work: a correction is an edit, a confirmation an accept. */
  const decision: 'accepted' | 'edited' | 'rejected' = state === 'rejected' ? 'rejected' : changed.length ? 'edited' : state

  const submit = async () => {
    setRowsError('')
    if (decision === 'edited' && !note.trim() && !changed.length) {
      setRowsError('Explain the correction: the figure now differs from the time log.')
      return
    }
    if (decision === 'edited' && changed.length && !note.trim()) {
      setRowsError('Add a reason for the corrected hours. It is recorded in the Audit Log.')
      return
    }
    await onSubmit({ review_state: decision, note: note.trim(), hours: changed })
    setDraft({})
    setNote('')
    setState('accepted')
  }

  const verdictLabel = totals.realised > 0 ? 'lead' : totals.realised < 0 ? 'lag' : 'on plan'
  const gridColumns = 'minmax(0,2.2fr) 96px 120px 112px 120px'

  return (
    <PanelDialog
      open={open}
      maxWidth="lg"
      title="Planned and actual hours"
      subtitle="The baseline programme's hours per sequence code against what this report — and every other line tagged with the same code — logged. Change an actual figure and the variance, the lead/lag badge and the total below recompute from it; the corrected hours are stored on the activity, so every later day, chart and summary follows them."
      onClose={onClose}
      footer={
        <>
          <Typography variant="caption" color="text.secondary" sx={{ mr: 'auto' }}>
            {changed.length
              ? `${changed.length} correction${changed.length === 1 ? '' : 's'} to save`
              : 'No corrections entered'}
          </Typography>
          <Button onClick={onClose} color="inherit" disabled={busy}>
            {editable ? 'Cancel' : 'Close'}
          </Button>
          {editable && (
            <Button variant="contained" onClick={() => void submit()} disabled={busy}>
              Save review
            </Button>
          )}
        </>
      }
    >
      <Stack spacing={2}>
        {error && <Alert severity="error">{error}</Alert>}
        {rowsError && <Alert severity="warning">{rowsError}</Alert>}

        <Box
          display="grid"
          gap={1.25}
          gridTemplateColumns={{ xs: 'repeat(2,minmax(0,1fr))', md: 'repeat(4,minmax(0,1fr))' }}
        >
          {[
            [
              'Planned hours',
              hours(totals.planned),
              `${totals.matched} coded activit${totals.matched === 1 ? 'y' : 'ies'} in scope${totals.skipped ? ` · ${totals.skipped} skipped` : ''}`,
            ],
            [
              'Hours spent',
              hours(totals.burn),
              `${hours(totals.actual)} coded${totals.unplanned ? ` + ${hours(totals.unplanned)} unplanned` : ''}`,
            ],
            [
              // The printed lead/lag, and only ever from finished work.
              'Lead / lag',
              totals.hasVerdict ? `${totals.realised > 0 ? '+' : ''}${hours(totals.realised)} h` : 'no verdict yet',
              totals.hasVerdict
                ? `${totals.realised > 0 ? '+' : ''}${(totals.realised / 24).toFixed(3)} d · ${verdictLabel}`
                : `${totals.open} activit${totals.open === 1 ? 'y' : 'ies'} still open — finish one to see a verdict`,
            ],
          ].map(([label, value, hint]) => (
            <Box
              key={label}
              sx={{ border: '1px solid', borderColor: 'divider', borderRadius: 2, p: 1.4, bgcolor: 'background.paper' }}
            >
              <Typography variant="caption" color="text.secondary">
                {label}
              </Typography>
              <Typography fontWeight={800} fontSize={18} lineHeight={1.25}>
                {value}
              </Typography>
              <Typography variant="caption" color="text.secondary">
                {hint}
              </Typography>
            </Box>
          ))}
          <Box sx={{ border: '1px solid', borderColor: 'divider', borderRadius: 2, p: 1.4, bgcolor: 'background.paper' }}>
            <TextField
              select
              size="small"
              fullWidth
              label="Decision"
              value={state}
              disabled={!editable || busy}
              onChange={(e) => setState(e.target.value as typeof state)}
              helperText={changed.length ? 'Corrections make this an edit' : ' '}
            >
              <MenuItem value="accepted">Accept the comparison</MenuItem>
              <MenuItem value="edited">Edit the comparison myself</MenuItem>
              <MenuItem value="rejected">Reject — not comparable</MenuItem>
            </TextField>
          </Box>
        </Box>

        <Box sx={{ border: '1px solid', borderColor: 'divider', borderRadius: 2, overflow: 'hidden' }}>
          <Box
            display={{ xs: 'none', md: 'grid' }}
            gridTemplateColumns={gridColumns}
            gap={1}
            px={1.5}
            py={1}
            sx={{ bgcolor: 'background.default', borderBottom: '1px solid', borderColor: 'divider' }}
          >
            {['Activity', 'System (h)', 'Your actual (h)', 'Code Σ (h)', 'Verdict'].map((label) => (
              <Typography key={label} variant="caption" fontWeight={700} color="text.secondary">
                {label}
              </Typography>
            ))}
          </Box>
          {groups.length === 0 && (
            <Box px={1.5} py={3}>
              <Typography variant="body2" color="text.secondary">
                No activity blocks are selected.
              </Typography>
            </Box>
          )}
          {groups.map((group) => {
            const groupLabel = group.members[0]?.timeline_plan_label
            const isUncoded = group.code === ''
            const compared = group.variance !== null
            return (
              <Box key={group.code || 'uncoded'}>
                {/* Group header: the code is the unit lead/lag is computed on. */}
                <Box
                  display="flex"
                  alignItems="center"
                  gap={1}
                  flexWrap="wrap"
                  px={1.5}
                  py={0.75}
                  sx={{
                    bgcolor: isUncoded ? 'warning.lighter' : 'action.hover',
                    borderTop: '1px solid',
                    borderColor: 'divider',
                  }}
                >
                  <Typography variant="caption" fontWeight={800} noWrap sx={{ maxWidth: '100%' }}>
                    {isUncoded
                      ? 'Unplanned activity — no sequence code'
                      : `Code ${group.code} · ${groupLabel || 'programme activity'}`}
                  </Typography>
                  {!isUncoded && group.state && (
                    <Typography
                      variant="caption"
                      sx={{
                        px: 0.75,
                        borderRadius: 1,
                        fontWeight: 700,
                        bgcolor: hasVerdict(group.state) ? 'success.lighter' : group.state === 'skipped' ? 'action.disabledBackground' : 'info.lighter',
                      }}
                    >
                      {STATE_LABELS[group.state] ?? group.state}
                    </Typography>
                  )}
                  <Typography variant="caption" color="text.secondary" sx={{ ml: 'auto' }}>
                    {isUncoded
                      ? `${group.members.length} line(s) · ${hours(group.actual)} h raise actual hours and can only lag`
                      : `planned ${hours(group.planned)} h · logged ${hours(group.actual)} h · ${group.members.length} line(s)`}
                  </Typography>
                  <Typography
                    variant="caption"
                    fontWeight={800}
                    color={
                      isUncoded
                        ? 'warning.main'
                        : !compared
                          ? 'text.secondary'
                          : (group.variance ?? 0) > 0
                            ? 'success.main'
                            : (group.variance ?? 0) < 0
                              ? 'warning.main'
                              : 'text.primary'
                    }
                  >
                    {isUncoded
                      ? 'unplanned — reads as lag'
                      : compared
                        ? `${(group.variance ?? 0) > 0 ? '+' : ''}${hours(group.variance)} h (${((group.variance ?? 0) / 24).toFixed(3)} d) · ${(group.variance ?? 0) > 0 ? 'lead' : (group.variance ?? 0) < 0 ? 'lag' : 'on plan'}`
                        : group.state === 'skipped'
                          ? 'hours released — not a lag'
                          : stateSentence(group.state, group.planned, group.actual)}
                  </Typography>
                </Box>
                {group.members.map((row) => {
                  const system = systemOf(row)
                  const actual = actualOf(row)
                  const edited = row.timeline_actual_edited || draft[row.id] !== undefined
                  const isRejected = decision === 'rejected'
                  const lineDisabled = !editable || busy || isRejected || isUncoded
                  return (
                    <Box
                      key={row.id}
                      display="grid"
                      gridTemplateColumns={{ xs: 'minmax(0,1fr) minmax(0,1fr)', md: gridColumns }}
                      gap={1}
                      px={1.5}
                      py={1.1}
                      alignItems="center"
                      sx={{
                        borderTop: '1px solid',
                        borderColor: 'divider',
                        bgcolor: edited ? 'action.selected' : 'transparent',
                      }}
                    >
                      <Box minWidth={0} gridColumn={{ xs: '1 / -1', md: 'auto' }}>
                        <Typography fontSize={12.5} fontWeight={700} noWrap title={row.narrative || row.timeline_plan_label || ''}>
                          {row.sequence_no}. {row.timeline_plan_label || row.activity_label || 'Activity'}
                        </Typography>
                        <Typography variant="caption" color="text.secondary">
                          {row.phase_label || 'Unphased'}
                          {isUncoded ? ' · unplanned activity' : ` · code ${group.code}`}
                          {row.timeline_split_state === 'split' ? ' · hours split between codes' : ''}
                          {row.timeline_review_state && row.timeline_review_state !== 'suggested'
                            ? ` · ${row.timeline_review_state}`
                            : ''}
                          {edited ? ' · corrected' : ''}
                          {row.timeline_basis ? ` · ${row.timeline_basis}` : ''}
                        </Typography>
                      </Box>
                      <Typography fontSize={12.5} color="text.secondary">
                        {hours(system)}
                      </Typography>
                      <Box display="flex" alignItems="center" gap={0.5}>
                        <TextField
                          size="small"
                          value={draft[row.id] ?? (actual === null ? '' : String(actual))}
                          disabled={lineDisabled}
                          onChange={(e) => {
                            const typed = e.target.value
                            // Digits and one decimal point; a blank clears the correction.
                            if (!/^\d*\.?\d*$/.test(typed)) return
                            setDraft((current) => ({ ...current, [row.id]: typed }))
                          }}
                          onBlur={() => {
                            // Normalise the visible number so 2 and 2.0 read the same.
                            setDraft((current) => {
                              if (current[row.id] === undefined) return current
                              const typed = num(current[row.id])
                              return { ...current, [row.id]: typed === null ? '' : typed.toFixed(3) }
                            })
                          }}
                          slotProps={{
                            htmlInput: { inputMode: 'decimal', 'aria-label': `Actual hours for block ${row.sequence_no}` },
                            input: { endAdornment: <InputAdornment position="end">h</InputAdornment> },
                          }}
                          sx={{ width: 118 }}
                        />
                        {edited && (
                          <Tooltip title="Restore the hours this report actually logged">
                            <span>
                              <Button
                                size="small"
                                sx={{ minWidth: 0, px: 0.5 }}
                                aria-label={`Restore logged hours for block ${row.sequence_no}`}
                                disabled={!editable || busy}
                                onClick={() =>
                                  setDraft((current) => {
                                    const next = { ...current }
                                    delete next[row.id]
                                    return next
                                  })
                                }
                              >
                                <RestartAlt fontSize="small" />
                              </Button>
                            </span>
                          </Tooltip>
                        )}
                      </Box>
                      <Typography fontSize={12.5} color="text.secondary">
                        {isUncoded ? '—' : hours(running.get(row.id) ?? null)}
                      </Typography>
                      <Typography
                        fontSize={12.5}
                        fontWeight={700}
                        color={
                          isUncoded || group.variance === null
                            ? 'text.secondary'
                            : group.variance > 0
                              ? 'success.main'
                              : group.variance < 0
                                ? 'warning.main'
                                : 'text.primary'
                        }
                      >
                        {isUncoded || group.variance === null
                          ? isUncoded
                            ? 'unplanned'
                            : group.state === 'skipped'
                              ? 'skipped'
                              : 'no verdict'
                          : `${group.variance > 0 ? '+' : ''}${group.variance.toFixed(3)} h · ${group.variance > 0 ? 'lead' : group.variance < 0 ? 'lag' : 'on plan'}`}
                      </Typography>
                    </Box>
                  )
                })}
              </Box>
            )
          })}
        </Box>

        <Box>
          <TextField
            label="Reason for the corrections"
            value={note}
            onChange={(e) => setNote(e.target.value)}
            multiline
            minRows={2}
            fullWidth
            disabled={!editable || busy}
            required={decision === 'edited'}
            helperText={
              decision === 'edited'
                ? 'Required: the figure no longer matches the time log, and the reason is written to the Audit Log.'
                : 'Optional when the system comparison is accepted or rejected.'
            }
          />
        </Box>

        {decision === 'rejected' && (
          <Alert severity="info">
            Rejecting leaves the activity out of the comparison instead of forcing it to “on plan”. The planned and
            system hours stay on the record.
          </Alert>
        )}

        {totals.unplanned > 0 && (
          <Alert severity="warning">
            {hours(totals.unplanned)} h in this selection carry no sequence code. They raise actual hours while planned
            hours stay put, so they read as {hours(totals.unplanned)} h ({(-totals.unplanned / 24).toFixed(3)} d) of lag
            on their own. Code them to the activity that did the work, or classify the work as Unplanned Activity with
            a reason, before submitting.
          </Alert>
        )}

        <Typography variant="caption" color="text.secondary">
          Planned hours belong to the baseline programme and are read-only here; each group’s plan is the programme
          row’s hours, not the sum of its lines. An edited actual is stored on the activity, not on the report, so it
          survives later recalculations and carries into the next day. The Σ code column adds the group up after each
          line, the same way you would on paper. A group only shows a lead or a lag once the activity is finished:
          until then the difference is the work still owed, which is why it is printed as remaining hours.
        </Typography>
      </Stack>
    </PanelDialog>
  )
}

export default TimelineHoursReview
