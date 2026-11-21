import { useEffect, useMemo, useState } from 'react'
import { Alert, Box, Button, Chip, Divider, MenuItem, Stack, TextField, Typography } from '@mui/material'
import { FormDialog } from '../Common'
import {
  applyTimelineCodes,
  clearTimelineCodes,
  previewTimelineCodes,
  reportTimelineCodes,
  splitTimelineCodes,
  type OpsBlock,
  type OpsReportTimelineCodes,
  type OpsSeqCodePreview,
  type OpsSequenceState,
  type OpsTimelineCode,
} from '../../lib/operations'

/**
 * Link the selected daily-report lines to the baseline programme.
 *
 * Lead and lag are only as trustworthy as the link is explicit. This dialog never
 * guesses from wording: it lists the programme's own sequence codes, shows exactly
 * which lines will carry the chosen code, and writes only on an explicit submit.
 *
 * Three things it says before the write, because the old screen said none of them:
 *
 * * **a code is not a verdict.** Choosing a code whose hours are partly logged is
 *   choosing work that stays *in progress*: the dialog shows the progress and the
 *   hours still owed, so nobody reads 88 remaining hours as 88 hours of lead;
 * * **a skipped activity is not a place to file hours.** It will never be done, so
 *   the hours would have nowhere to go — the dialog refuses the choice and says so;
 * * **one line can genuinely do two activities.** "Split between codes" shares one
 *   line's hours between several programme rows, and any remainder stays visibly
 *   unplanned instead of being attributed to a third activity at random.
 *
 * "Clear the code" is offered too, and it is honest about its cost: the line's hours
 * become Unplanned Activity, which reads as lag.
 */

type Mode = 'apply' | 'split'

const STATE_LABEL: Record<OpsSequenceState, string> = {
  not_started: 'not started',
  in_progress: 'in progress',
  overrun_open: 'over plan, still open',
  complete: 'finished',
  skipped: 'skipped',
}

function stateSentence(code: OpsTimelineCode | null): string {
  if (!code) return ''
  const planned = code.planned_hours === null ? null : Number(code.planned_hours)
  const actual = code.actual_hours === null ? null : Number(code.actual_hours)
  const logged = actual ?? 0
  const progress = planned !== null && planned > 0 ? Math.min(100, (logged / planned) * 100) : null
  const remaining = planned === null ? null : Math.max(0, planned - logged)
  if (code.state === 'skipped') {
    return `${code.sequence_no} is skipped: it will never be done, so its ${code.planned_hours ?? '—'} h are released as saved rather than counted as a lag. Un-skip it on the programme before coding work to it.`
  }
  if (code.state === 'complete') {
    return `${code.sequence_no} is already finished (${code.actual_hours ?? '—'} h logged of ${code.planned_hours ?? '—'} h). Hours found later belong to the activity that actually happened — pick that one, or reopen this one deliberately.`
  }
  if (code.state === 'not_started') {
    return `${code.sequence_no} has not started. Coded hours will move it to in progress; it shows a lead or a lag only when the activity is closed.`
  }
  if (code.state === 'overrun_open') {
    return `${code.sequence_no} is already over its plan (${logged.toFixed(2)} h of ${planned?.toFixed(2) ?? '—'} h) and is not closed. It stays "over plan" until someone states that it is finished.`
  }
  return `${code.sequence_no} is in progress: ${logged.toFixed(2)} of ${planned?.toFixed(2) ?? '—'} h logged (${progress?.toFixed(0) ?? '—'} %), ${remaining?.toFixed(2) ?? '—'} h still owed. That remainder is work, not a lead.`
}

export function SeqCodeDialog({
  open,
  reportId,
  blocks,
  onClose,
  onApplied,
}: {
  open: boolean
  reportId: string
  blocks: OpsBlock[]
  onClose: () => void
  onApplied: (message: string) => void
}) {
  const [codes, setCodes] = useState<OpsReportTimelineCodes | null>(null)
  const [itemId, setItemId] = useState('')
  const [preview, setPreview] = useState<OpsSeqCodePreview | null>(null)
  const [filter, setFilter] = useState('')
  const [mode, setMode] = useState<Mode>('apply')
  const [splitHours, setSplitHours] = useState<Record<string, string>>({})
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')

  useEffect(() => {
    if (!open) return
    setCodes(null)
    setItemId('')
    setPreview(null)
    setFilter('')
    setMode('apply')
    setSplitHours({})
    setError('')
    reportTimelineCodes(reportId)
      .then(setCodes)
      .catch((e: unknown) => setError((e as Error).message))
  }, [open, reportId])

  const filtered = useMemo(() => {
    if (!codes) return []
    const needle = filter.trim().toLowerCase()
    if (!needle) return codes.codes
    return codes.codes.filter(
      (c) => String(c.sequence_no).includes(needle) || c.description.toLowerCase().includes(needle),
    )
  }, [codes, filter])

  const chosen = useMemo(
    () => (codes ? (codes.codes.find((c) => c.item_id === itemId) ?? null) : null),
    [codes, itemId],
  )

  const blockIds = useMemo(() => blocks.map((b) => b.id), [blocks])
  const single = blocks.length === 1

  /** The line's own logged hours, which a split may not exceed. */
  const lineHours = useMemo(() => {
    if (!single) return null
    const block = blocks[0] as unknown as { timeline_actual_hours?: string | null; duration_minutes?: number }
    if (block.timeline_actual_hours) return Number(block.timeline_actual_hours)
    if (typeof block.duration_minutes === 'number') return block.duration_minutes / 60
    return null
  }, [blocks, single])

  const loadPreview = async () => {
    if (!chosen) return
    setBusy(true)
    setError('')
    try {
      setPreview(await previewTimelineCodes({ block_ids: blockIds, item_id: chosen.item_id }))
    } catch (e) {
      setPreview(null)
      setError((e as Error).message)
    } finally {
      setBusy(false)
    }
  }

  const apply = async () => {
    if (!chosen) return
    setBusy(true)
    setError('')
    try {
      const result = await applyTimelineCodes({ block_ids: blockIds, item_id: chosen.item_id })
      onApplied(result.summary)
      onClose()
    } catch (e) {
      setError((e as Error).message)
    } finally {
      setBusy(false)
    }
  }

  const split = async () => {
    if (!single) return
    const allocations = Object.entries(splitHours)
      .map(([id, hours]) => ({ item_id: id, hours: (hours || '').trim() }))
      .filter((row) => row.hours !== '' && Number(row.hours) > 0)
    if (!allocations.length) {
      setError('Allocate at least one hour to a sequence code.')
      return
    }
    setBusy(true)
    setError('')
    try {
      const result = await splitTimelineCodes({ block_id: blocks[0].id, allocations })
      onApplied(result.summary)
      onClose()
    } catch (e) {
      setError((e as Error).message)
    } finally {
      setBusy(false)
    }
  }

  const clear = async () => {
    setBusy(true)
    setError('')
    try {
      const result = await clearTimelineCodes({ block_ids: blockIds, acknowledge_unplanned: true })
      onApplied(result.summary)
      onClose()
    } catch (e) {
      setError((e as Error).message)
    } finally {
      setBusy(false)
    }
  }

  const noBaseline = codes !== null && !codes.plan_version_id
  const blocked = chosen?.state === 'skipped' || chosen?.state === 'complete'

  return (
    <FormDialog
      open={open}
      title="Apply sequence codes"
      subtitle="Link the selected lines to the baseline programme. Hours logged against the same code are summed and compared with that activity's planned hours — planned − actual, positive is a lead, negative a lag, and ÷ 24 for days. A lead or a lag is printed only once the activity is finished. Nothing is written until you apply."
      onClose={onClose}
      onSubmit={() => void (mode === 'split' ? split() : apply())}
      submitLabel={
        mode === 'split'
          ? 'Split the line between codes'
          : chosen
            ? `Code ${blocks.length} line(s) as ${chosen.sequence_no}`
            : 'Apply code'
      }
      busy={busy}
      submitDisabled={noBaseline || (mode === 'split' ? !single : !chosen || blocked)}
    >
      <Stack spacing={2} pt={0.5}>
        {error && <Alert severity="error">{error}</Alert>}
        {!codes && !error && <Typography variant="body2">Loading the baseline programme…</Typography>}
        {noBaseline && (
          <Alert severity="warning">
            This report has no baseline programme. Activate a timeline for the well and scope first; until then there
            is no plan against which to take the lead or the lag.
          </Alert>
        )}
        {codes && codes.codes.length > 0 && (
          <>
            <Box display="flex" alignItems="center" gap={1} flexWrap="wrap">
              <Chip size="small" variant="outlined" label={`Programme: ${codes.plan_label} · ${codes.plan_status}`} />
              {single && (
                <Button size="small" onClick={() => setMode(mode === 'split' ? 'apply' : 'split')}>
                  {mode === 'split' ? 'Code the whole line instead' : 'This line did two activities…'}
                </Button>
              )}
              <Typography variant="caption" color="text.secondary">
                Lines already coded are re-tagged; submitted or approved reports cannot change.
              </Typography>
            </Box>

            {mode === 'apply' ? (
              <>
                <TextField
                  label="Filter programme lines"
                  size="small"
                  value={filter}
                  onChange={(e) => setFilter(e.target.value)}
                  placeholder="Sequence no. or description…"
                />
                <TextField
                  select
                  label="Sequence code"
                  size="small"
                  value={itemId}
                  onChange={(e) => {
                    setItemId(e.target.value)
                    setPreview(null)
                  }}
                  helperText="Every line of the baseline programme carries its own code."
                >
                  <MenuItem value="">Choose a programme line…</MenuItem>
                  {filtered.map((c) => (
                    <MenuItem key={c.item_id} value={c.item_id}>
                      {c.sequence_no} — {c.description}
                      {c.planned_hours !== null ? ` · ${Number(c.planned_hours).toFixed(2)} h` : ''}
                      {c.state !== 'not_started' ? ` · ${STATE_LABEL[c.state]}` : ''}
                    </MenuItem>
                  ))}
                </TextField>
                {chosen && (
                  <Alert severity={blocked ? 'warning' : 'info'} sx={{ py: 0.5 }}>
                    {stateSentence(chosen)}
                  </Alert>
                )}
                <Box display="flex" alignItems="center" gap={1.5} flexWrap="wrap">
                  <Button variant="outlined" size="small" onClick={() => void loadPreview()} disabled={busy || !chosen}>
                    Preview lines
                  </Button>
                  <Chip
                    size="small"
                    label={
                      preview ? `${preview.eligible} line(s) will carry code ${preview.sequence_no}` : 'Not previewed yet'
                    }
                  />
                  {blocks.length > 0 && (
                    <Button size="small" color="warning" onClick={() => void clear()} disabled={busy}>
                      Clear the code instead
                    </Button>
                  )}
                </Box>
                {preview && preview.warnings.length > 0 && (
                  <Alert severity="info" sx={{ py: 0.5 }}>
                    {preview.warnings.map((warning) => (
                      <Typography key={warning} variant="caption" component="p">
                        {warning}
                      </Typography>
                    ))}
                  </Alert>
                )}
                {preview && preview.lines.length > 0 && (
                  <Box
                    sx={{
                      maxHeight: 220,
                      overflow: 'auto',
                      border: 1,
                      borderColor: 'divider',
                      borderRadius: '10px',
                      p: 1.5,
                    }}
                  >
                    <Typography variant="caption" component="p" sx={{ fontWeight: 700, mb: 0.75 }}>
                      Lines that will carry code {preview.sequence_no}
                    </Typography>
                    {preview.lines.map((line) => (
                      <Typography key={line.block_id} variant="caption" component="p">
                        #{line.sequence_no} — {line.before ? `re-tag from ${line.before}` : 'untagged'} → {line.after}
                        {line.narrative ? ` · ${line.narrative.slice(0, 90)}` : ''}
                      </Typography>
                    ))}
                  </Box>
                )}
              </>
            ) : (
              <>
                <Alert severity="info" sx={{ py: 0.5 }}>
                  One line can genuinely do two programme activities. Allocate its hours between them: the total may
                  not exceed the {lineHours === null ? 'line’s logged' : `${lineHours.toFixed(2)} h this line logged in`},
                  and anything you leave unallocated stays visibly unplanned.
                </Alert>
                <Box sx={{ maxHeight: 260, overflow: 'auto', border: 1, borderColor: 'divider', borderRadius: '10px' }}>
                  {filtered.map((c) => (
                    <Box
                      key={c.item_id}
                      display="flex"
                      alignItems="center"
                      gap={1}
                      px={1.5}
                      py={0.75}
                      sx={{ borderBottom: '1px solid', borderColor: 'divider' }}
                    >
                      <Box minWidth={0} flex={1}>
                        <Typography variant="caption" fontWeight={700} noWrap display="block">
                          {c.sequence_no} — {c.description}
                        </Typography>
                        <Typography variant="caption" color="text.secondary">
                          planned {c.planned_hours ?? '—'} h · logged {c.actual_hours ?? '0'} h · {STATE_LABEL[c.state]}
                        </Typography>
                      </Box>
                      <TextField
                        size="small"
                        label="Hours"
                        value={splitHours[c.item_id] ?? ''}
                        disabled={busy || c.state === 'skipped' || c.state === 'complete'}
                        onChange={(e) => {
                          const typed = e.target.value
                          if (!/^\d*\.?\d*$/.test(typed)) return
                          setSplitHours((current) => ({ ...current, [c.item_id]: typed }))
                        }}
                        sx={{ width: 110 }}
                      />
                    </Box>
                  ))}
                </Box>
                {lineHours !== null && (
                  <Typography variant="caption" color="text.secondary">
                    Allocated{' '}
                    {Object.values(splitHours)
                      .reduce((sum, value) => sum + (Number(value) || 0), 0)
                      .toFixed(3)}{' '}
                    of {lineHours.toFixed(3)} h · the rest stays unplanned and reads as lag.
                  </Typography>
                )}
              </>
            )}
          </>
        )}
        <Divider />
        <Box>
          <Typography variant="caption" color="text.secondary">
            Applying writes the code onto the selected draft lines and recomputes plan-vs-timeline straight away. Save
            the report as usual to keep it. A reviewed line keeps its review mark; its hours still count in the code’s
            total. Clearing a code makes the hours Unplanned Activity, which reads as lag — that is the honest cost of
            saying the work belongs to no planned activity.
          </Typography>
        </Box>
      </Stack>
    </FormDialog>
  )
}
