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
 * The question this panel answers is "did this activity take the hours the
 * programme allowed?", so each row carries four numbers and one editable field:
 *
 * * **planned** — from the active programme, never editable here (a daily log
 *   cannot rewrite the baseline, it can only disagree with it);
 * * **system actual** — the block's logged duration in hours, kept visible even
 *   after a correction so an auditor can see what the log said;
 * * **your actual** — the engineer's figure; typing a new value recomputes the
 *   variance, the lead/lag badge and the reported total on the spot;
 * * **variance** — planned − actual, in hours and in days; positive is a lead.
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
   * Running totals per row, the same shape as the "Input-lookahead" sheet:
   * cumulative planned hours, cumulative actual hours and their difference.
   * A row a reader can add up by hand is a row they can trust.
   */
  const running = useMemo(() => {
    const map = new Map<string, { plan: number | null; actual: number | null }>()
    let plan = 0
    let actual = 0
    let seenPlan = false
    let seenActual = false
    for (const row of rows) {
      const p = num(row.timeline_planned_hours)
      const a = actualOf(row)
      if (p !== null) {
        plan += p
        seenPlan = true
      }
      if (a !== null) {
        actual += a
        seenActual = true
      }
      map.set(row.id, { plan: seenPlan ? plan : null, actual: seenActual ? actual : null })
    }
    return map
  }, [rows, draft])

  const totals = useMemo(() => {
    let planned = 0
    let actual = 0
    let matched = 0
    let corrected = 0
    for (const row of rows) {
      const p = num(row.timeline_planned_hours)
      const a = actualOf(row)
      if (p === null) continue
      matched += 1
      planned += p
      if (a !== null) actual += a
      if (row.timeline_actual_edited || draft[row.id] !== undefined) corrected += 1
    }
    return { planned, actual, variance: planned - actual, matched, corrected }
  }, [rows, draft])

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

  return (
    <PanelDialog
      open={open}
      maxWidth="lg"
      title="Planned and actual hours"
      subtitle="The active programme's hours against what this report logged. Change an actual figure and the variance, the lead/lag badge and the total below recompute from it; the corrected hours are stored on the activity, so every later day, chart and summary follows them."
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
            ['Planned hours', hours(totals.planned), `${totals.matched} of ${rows.length} matched to the programme`],
            ['Actual hours', hours(totals.actual), `${totals.corrected} corrected by hand`],
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
            gridTemplateColumns="minmax(0,2.4fr) 92px 98px 118px 112px 96px 92px"
            gap={1}
            px={1.5}
            py={1}
            sx={{ bgcolor: 'background.default', borderBottom: '1px solid', borderColor: 'divider' }}
          >
            {['Activity', 'Plan (h)', 'System (h)', 'Your actual (h)', 'Cum plan (h)', 'Cum actual (h)', 'Variance'].map((label) => (
              <Typography key={label} variant="caption" fontWeight={700} color="text.secondary">
                {label}
              </Typography>
            ))}
          </Box>
          {rows.length === 0 && (
            <Box px={1.5} py={3}>
              <Typography variant="body2" color="text.secondary">
                No activity blocks are selected.
              </Typography>
            </Box>
          )}
          {rows.map((row, index) => {
            const planned = num(row.timeline_planned_hours)
            const system = systemOf(row)
            const actual = actualOf(row)
            const variance = planned !== null && actual !== null ? planned - actual : null
            const edited = row.timeline_actual_edited || draft[row.id] !== undefined
            const isRejected = decision === 'rejected'
            return (
              <Box
                key={row.id}
                display="grid"
                gridTemplateColumns={{
                  xs: 'minmax(0,1fr) minmax(0,1fr)',
                  md: 'minmax(0,2.4fr) 92px 98px 118px 112px 96px 92px',
                }}
                gap={1}
                px={1.5}
                py={1.1}
                alignItems="center"
                sx={{
                  borderTop: index === 0 ? 'none' : '1px solid',
                  borderColor: 'divider',
                  bgcolor: edited ? 'action.hover' : 'transparent',
                }}
              >
                <Box minWidth={0} gridColumn={{ xs: '1 / -1', md: 'auto' }}>
                  <Typography fontSize={12.5} fontWeight={700} noWrap title={row.narrative || row.timeline_plan_label || ''}>
                    {row.sequence_no}. {row.timeline_plan_label || row.activity_label || 'Activity'}
                  </Typography>
                  <Typography variant="caption" color="text.secondary">
                    {row.phase_label || 'Unphased'}
                    {row.timeline_plan_step_no !== null && row.timeline_plan_step_no !== undefined
                      ? ` · programme step ${row.timeline_plan_step_no}`
                      : ' · no programme step'}
                    {row.timeline_review_state && row.timeline_review_state !== 'suggested'
                      ? ` · ${row.timeline_review_state}`
                      : ''}
                    {edited ? ' · corrected' : ''}
                    {row.timeline_basis ? ` · ${row.timeline_basis}` : ''}
                  </Typography>
                </Box>
                <Typography fontSize={12.5} fontWeight={600}>
                  {hours(planned)}
                </Typography>
                <Typography fontSize={12.5} color="text.secondary">
                  {hours(system)}
                </Typography>
                <Box display="flex" alignItems="center" gap={0.5}>
                  <TextField
                    size="small"
                    value={draft[row.id] ?? (actual === null ? '' : String(actual))}
                    disabled={!editable || busy || isRejected}
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
                  {hours(running.get(row.id)?.plan ?? null)}
                </Typography>
                <Typography fontSize={12.5} color="text.secondary">
                  {hours(running.get(row.id)?.actual ?? null)}
                </Typography>
                <Typography
                  fontSize={12.5}
                  fontWeight={700}
                  color={variance === null ? 'text.secondary' : variance > 0 ? 'success.main' : variance < 0 ? 'warning.main' : 'text.primary'}
                >
                  {variance === null ? '—' : `${variance > 0 ? '+' : ''}${variance.toFixed(3)} h`}
                  {variance !== null && (
                    <Typography component="span" variant="caption" color="text.secondary" display="block">
                      {(variance / 24).toFixed(3)} d · {variance > 0 ? 'lead' : variance < 0 ? 'lag' : 'on plan'}
                    </Typography>
                  )}
                </Typography>
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
          Planned hours belong to the active programme and are read-only here. An edited actual is stored on the
          activity, not on the report, so it survives later recalculations and carries into the next day.
        </Typography>
      </Stack>
    </PanelDialog>
  )
}

export default TimelineHoursReview
