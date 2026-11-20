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
import type { ReviewTimelineResult } from '../../lib/operations'

/**
 * Editable plan-vs-actual hours: the review surface for lead and lag.
 *
 * The question this panel answers is "did this job take the hours the
 * programme allowed?" — and the answer is grouped by sequence code, because
 * that is the correlation the whole comparison rests on:
 *
 * * every line of the baseline programme carries a sequence code;
 * * a daily-report line opts in by carrying the same code (edit it in the
 *   register's Seq column, or apply one code to many lines with the bulk
 *   action);
 * * the panel sums the hours of the lines in each code and compares the total
 *   with the programme's planned hours for that code — positive variance is a
 *   lead, negative is a lag;
 * * lines without a code are listed under "Uncoded" and are excluded from the
 *   arithmetic: nothing is guessed from the wording of a narrative.
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
   * uncoded group last. The group is the unit lead/lag is computed on, so the
   * panel adds up by code, never by line — planned hours belong to the
   * programme row, not to any single line that logs against it.
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
      const variance = planned !== null && actual !== null ? planned - actual : null
      const codeNo = /^\d+$/.test(code) ? Number(code) : Number.POSITIVE_INFINITY
      return { code, members, planned, actual, variance, codeNo }
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

  /** Totals across the distinct coded groups, plus the uncoded line count. */
  const totals = useMemo(() => {
    let planned = 0
    let actual = 0
    let matched = 0
    let uncoded = 0
    let corrected = 0
    for (const group of groups) {
      if (group.code === '') {
        uncoded += group.members.length
        continue
      }
      matched += 1
      if (group.planned !== null) planned += group.planned
      if (group.actual !== null) actual += group.actual
    }
    for (const row of rows) if (row.timeline_actual_edited || draft[row.id] !== undefined) corrected += 1
    return { planned, actual, variance: planned - actual, matched, uncoded, corrected }
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

  const worstCase = totals.variance > 0 ? 'lead' : totals.variance < 0 ? 'lag' : 'on plan'
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
            ['Planned hours', hours(totals.planned), `${totals.matched} coded activit${totals.matched === 1 ? 'y' : 'ies'}${totals.uncoded ? ` · ${totals.uncoded} uncoded line(s) excluded` : ''}`],
            ['Actual hours', hours(totals.actual), `${totals.corrected} line(s) corrected by hand`],
            [
              'Variance',
              `${totals.variance > 0 ? '+' : ''}${hours(totals.variance)} h`,
              `${totals.variance > 0 ? '+' : ''}${(totals.variance / 24).toFixed(3)} d · ${worstCase}`,
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
            {['Activity', 'System (h)', 'Your actual (h)', 'Code Σ (h)', 'Lead / Lag'].map((label) => (
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
                  sx={{ bgcolor: isUncoded ? 'warning.lighter' : 'action.hover', borderTop: '1px solid', borderColor: 'divider' }}
                >
                  <Typography variant="caption" fontWeight={800} noWrap sx={{ maxWidth: '100%' }}>
                    {isUncoded ? 'Uncoded lines — excluded from lead/lag' : `Code ${group.code} · ${groupLabel || 'programme activity'}`}
                  </Typography>
                  <Typography variant="caption" color="text.secondary" sx={{ ml: 'auto' }}>
                    {isUncoded
                      ? `${group.members.length} line(s) · code them in the register’s Seq column`
                      : `planned ${hours(group.planned)} h · logged ${hours(group.actual)} h · ${group.members.length} line(s)`}
                  </Typography>
                  {!isUncoded && (
                    <Typography
                      variant="caption"
                      fontWeight={800}
                      color={
                        !compared
                          ? 'text.secondary'
                          : (group.variance ?? 0) > 0
                            ? 'success.main'
                            : (group.variance ?? 0) < 0
                              ? 'warning.main'
                              : 'text.primary'
                      }
                    >
                      {compared
                        ? `${(group.variance ?? 0) > 0 ? '+' : ''}${hours(group.variance)} h (${((group.variance ?? 0) / 24).toFixed(3)} d) · ${(group.variance ?? 0) > 0 ? 'lead' : (group.variance ?? 0) < 0 ? 'lag' : 'on plan'}`
                        : group.planned === null
                          ? 'planned hours missing'
                          : 'no hours logged'}
                    </Typography>
                  )}
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
                          {isUncoded ? ' · uncoded' : ` · code ${group.code}`}
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
                            ? 'excluded'
                            : '—'
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

        <Typography variant="caption" color="text.secondary">
          Planned hours belong to the baseline programme and are read-only here; each group’s plan is the programme
          row’s hours, not the sum of its lines. An edited actual is stored on the activity, not on the report, so it
          survives later recalculations and carries into the next day. The Σ code column adds the group up after each
          line, the same way you would on paper.
        </Typography>
      </Stack>
    </PanelDialog>
  )
}

export default TimelineHoursReview
