import { useEffect, useId, useState } from 'react'
import { Box, Button, Paper, TextField, Typography } from '@mui/material'
import { ErrorMessage, FormDialog, Tag, type Tone } from '../Common'
import {
  entryCheckCounts, entryCheckSeverityLabel, entryCheckSummary, hasSuggestion,
  type EntryCheck, type EntryCheckLine,
} from '../../lib/entryChecks'

/** Open findings listed before the rest is folded away. */
const OPEN_LIMIT = 8
/** Lines named under one finding before "and N more". */
const LINE_LIMIT = 4
const NOTE_LIMIT = 300

function toneOf(check: EntryCheck): Tone {
  if (check.reviewed) return 'neutral'
  return check.severity === 'warning' ? 'warning' : 'info'
}

function reviewedLine(check: EntryCheck): string {
  const who = check.reviewed_by || 'a workspace user'
  const when = check.reviewed_at ? ` on ${new Date(check.reviewed_at).toLocaleString()}` : ''
  return `Kept as entered by ${who}${when}${check.review_note ? `. Note: ${check.review_note}` : '.'}`
}

function historySentence(historySheets: number | null): string {
  if (historySheets === null) return ''
  if (historySheets === 0) {
    return 'This is the only sheet of its AFE so far, so there is nothing to compare quantities with yet. Depths are still checked against the well plan.'
  }
  const compared = `Compared with ${historySheets} other sheet${historySheets === 1 ? '' : 's'} of this AFE.`
  return historySheets < 5
    ? `${compared} Quantities are compared once an item appears on 5 other sheets, or on other wells of this workspace.`
    : compared
}

export type EntryChecksPanelProps = {
  /** Findings for the state of the sheet that is on screen. */
  checks: EntryCheck[]
  /** Whether they describe the saved sheet or its unsaved edits. */
  source: 'saved' | 'unsaved'
  /** True until the first result has arrived. */
  loading: boolean
  /** The findings on screen are out of date; actions wait for the new result. */
  stale: boolean
  /** Why they are out of date, in words. */
  staleText?: string
  error: string
  onRetry: () => void
  /** A Draft sheet that this user may update. */
  editable: boolean
  /** Other sheets of the same AFE the values were compared with. */
  historySheets: number | null
  /** How a line reads on the sheet, e.g. "Consumables · 17-1/2 · quantity 60". */
  describeLine: (line: EntryCheckLine) => string
  /** Writes the suggestion into the unsaved sheet; false when it no longer fits. */
  onApply: (check: EntryCheck) => boolean
  onOpenLine: (line: EntryCheckLine) => void
  /** Records the review; rejects with a readable message. */
  onKeep: (check: EntryCheck, note: string) => Promise<void>
  onReopen: (check: EntryCheck) => Promise<void>
}

/**
 * Entry checks beside the daily sheet: the values that look mistyped, why, and
 * what to do about each one. Nothing here blocks a save. A suggestion is only
 * written into the unsaved sheet, where the user still reviews and saves it.
 */
export function EntryChecksPanel({
  checks, source, loading, stale, staleText, error, onRetry, editable, historySheets,
  describeLine, onApply, onOpenLine, onKeep, onReopen,
}: EntryChecksPanelProps) {
  const headingId = useId()
  const bodyId = useId()
  const reviewedId = useId()
  const [expanded, setExpanded] = useState(true)
  const [showAll, setShowAll] = useState(false)
  const [showReviewed, setShowReviewed] = useState(false)
  const [keeping, setKeeping] = useState<EntryCheck | null>(null)
  const [note, setNote] = useState('')
  const [keepBusy, setKeepBusy] = useState(false)
  const [keepError, setKeepError] = useState('')
  const [reopening, setReopening] = useState('')
  const [itemError, setItemError] = useState<{ key: string; message: string } | null>(null)

  const open = checks.filter(check => !check.reviewed)
  const reviewed = checks.filter(check => check.reviewed)
  const counts = entryCheckCounts(checks)
  const visibleOpen = showAll ? open : open.slice(0, OPEN_LIMIT)
  const actionable = editable && !stale
  // A review describes the saved ledger, so it waits until the sheet is saved.
  const canReview = actionable && source === 'saved'

  // A message about one finding is dropped once that finding is gone.
  useEffect(() => {
    if (itemError && !checks.some(check => check.key === itemError.key)) setItemError(null)
  }, [checks, itemError])

  const startKeeping = (check: EntryCheck) => {
    setKeeping(check)
    setNote('')
    setKeepError('')
  }

  const keep = async () => {
    if (!keeping || keepBusy) return
    setKeepBusy(true)
    setKeepError('')
    try {
      await onKeep(keeping, note)
      setKeeping(null)
      setNote('')
    } catch (caught) {
      setKeepError(caught instanceof Error ? caught.message : 'The value could not be kept as entered.')
    } finally {
      setKeepBusy(false)
    }
  }

  const reopen = async (check: EntryCheck) => {
    if (reopening) return
    setReopening(check.key)
    setItemError(null)
    try {
      await onReopen(check)
    } catch (caught) {
      setItemError({ key: check.key, message: caught instanceof Error ? caught.message : 'The check could not be reopened.' })
    } finally {
      setReopening('')
    }
  }

  const apply = (check: EntryCheck) => {
    setItemError(null)
    if (!onApply(check)) {
      setItemError({ key: check.key, message: 'This suggestion no longer matches the sheet. Open the line and correct it there.' })
    }
  }

  const renderLines = (check: EntryCheck) => {
    if (!check.lines.length) return null
    const shown = check.lines.slice(0, LINE_LIMIT)
    const more = check.lines.length - shown.length
    return <Box display="flex" alignItems="center" flexWrap="wrap" columnGap={.8} rowGap={.2} mt={.5}>
      <Typography fontSize={11.5} color="text.secondary" fontWeight={700}>
        {check.lines.length === 1 ? 'Line' : `${check.lines.length} lines`}
      </Typography>
      {shown.map(line => {
        const label = describeLine(line)
        return editable
          ? <Button
              key={`${line.group}-${line.index}`} size="small" variant="text" disabled={!actionable}
              aria-label={`Open ${label}`} onClick={() => onOpenLine(line)}
              sx={{ minHeight: 0, py: .1, px: .6, fontSize: 11.5, textAlign: 'left', whiteSpace: 'normal', lineHeight: 1.4 }}
            >{label}</Button>
          : <Typography key={`${line.group}-${line.index}`} fontSize={11.5} color="text.secondary">{label}</Typography>
      })}
      {more > 0 && <Typography fontSize={11.5} color="text.secondary">and {more} more</Typography>}
    </Box>
  }

  const renderCheck = (check: EntryCheck) => <Box
    key={check.key} role="listitem"
    sx={{
      display: 'grid', gap: 1, py: 1.1, borderTop: '1px solid', borderColor: 'divider',
      gridTemplateColumns: { xs: 'minmax(0, 1fr)', md: 'minmax(0, 1fr) auto' }, alignItems: 'start',
    }}
  >
    <Box minWidth={0}>
      <Box display="flex" alignItems="center" flexWrap="wrap" gap={.8}>
        <Tag tone={toneOf(check)}>{entryCheckSeverityLabel(check)}</Tag>
        <Typography fontSize={12.5} fontWeight={700} sx={{ overflowWrap: 'anywhere' }}>{check.title}</Typography>
      </Box>
      <Typography fontSize={12.5} mt={.5} sx={{ lineHeight: 1.5, overflowWrap: 'anywhere' }}>{check.message}</Typography>
      {check.basis && <Typography fontSize={11.5} color="text.secondary" mt={.2} sx={{ lineHeight: 1.5 }}>{check.basis}</Typography>}
      {renderLines(check)}
      {check.reviewed && <Typography fontSize={11.5} color="text.secondary" mt={.4} sx={{ overflowWrap: 'anywhere' }}>{reviewedLine(check)}</Typography>}
      {itemError?.key === check.key && <ErrorMessage message={itemError.message}/>}
    </Box>
    {editable && <Box display="flex" gap={.8} flexWrap="wrap" sx={{ justifyContent: { md: 'flex-end' } }}>
      {!check.reviewed && hasSuggestion(check) && <Button
        size="small" variant="contained" disabled={!actionable}
        aria-label={`Apply ${check.suggested_display}${check.subject_label ? ` to ${check.subject_label}` : ''}`}
        onClick={() => apply(check)}
      >Apply {check.suggested_display}</Button>}
      {!check.reviewed && source === 'saved' && <Button
        size="small" variant="outlined" disabled={!canReview}
        aria-label={`Keep as entered: ${check.title}`} onClick={() => startKeeping(check)}
      >Keep as entered</Button>}
      {check.reviewed && source === 'saved' && <Button
        size="small" variant="outlined" disabled={!canReview || Boolean(reopening)}
        aria-label={`Reopen: ${check.title}`} onClick={() => void reopen(check)}
      >{reopening === check.key ? 'Reopening…' : 'Reopen'}</Button>}
    </Box>}
  </Box>

  const summary = entryCheckSummary(counts)
  const nothingFound = !checks.length && !loading && !error

  return <Paper component="section" variant="outlined" aria-labelledby={headingId} sx={{ p: 1.6, borderRadius: 2, mb: 1.6 }}>
    <Box display="flex" alignItems="center" flexWrap="wrap" gap={1}>
      <Typography id={headingId} component="h2" fontWeight={800} fontSize={13.5}>Entry checks</Typography>
      <Box display="flex" alignItems="center" flexWrap="wrap" gap={.6} aria-live="polite">
        {counts.warnings > 0 && <Tag tone="warning">{counts.warnings} to check</Tag>}
        {counts.notices > 0 && <Tag tone="info">{counts.notices} to note</Tag>}
        {counts.reviewed > 0 && <Tag tone="neutral">{counts.reviewed} kept as entered</Tag>}
        {nothingFound && <Tag tone="success">Nothing unusual</Tag>}
      </Box>
      <Typography fontSize={11.5} color="text.secondary" sx={{ flex: 1, minWidth: 180 }}>
        {stale && staleText ? staleText : source === 'unsaved' ? 'For your unsaved changes.' : 'For the saved sheet.'}
      </Typography>
      {checks.length > 0 && <Button
        size="small" color="inherit" aria-expanded={expanded} aria-controls={bodyId}
        onClick={() => setExpanded(value => !value)}
      >{expanded ? 'Hide' : `Show${summary ? ` (${summary})` : ''}`}</Button>}
    </Box>

    {error && <Box display="flex" alignItems="center" flexWrap="wrap" gap={1}>
      <ErrorMessage message={`Entry checks could not be loaded. ${error}`}/>
      <Button size="small" onClick={onRetry} sx={{ mt: 1.5 }}>Retry</Button>
    </Box>}

    {loading && !checks.length && !error && <Typography fontSize={12} color="text.secondary" mt={.8}>
      Comparing this sheet with the other sheets of its AFE…
    </Typography>}

    {nothingFound && <Typography fontSize={12} color="text.secondary" mt={.8} sx={{ lineHeight: 1.5 }}>
      No value on this sheet looks mistyped. {historySentence(historySheets)}
    </Typography>}

    {checks.length > 0 && <Box id={bodyId} hidden={!expanded} mt={.8}>
      <Typography fontSize={11.5} color="text.secondary" sx={{ lineHeight: 1.5, mb: .6 }}>
        Values that look mistyped next to the other sheets of this AFE, its locked rates and the well plan.
        Advice only: nothing here stops you saving.
        {editable && source === 'unsaved' && open.length > 0 && ' To keep a value as it is, save the sheet first.'}
      </Typography>
      {open.length > 0 && <Box role="list" aria-label="Open entry checks">
        {visibleOpen.map(renderCheck)}
      </Box>}
      {open.length > OPEN_LIMIT && <Button
        size="small" color="inherit" aria-expanded={showAll} onClick={() => setShowAll(value => !value)} sx={{ mt: .4 }}
      >{showAll ? `Show the first ${OPEN_LIMIT} only` : `Show all ${open.length} open checks`}</Button>}
      {reviewed.length > 0 && <Box sx={{ borderTop: open.length ? '1px solid' : 'none', borderColor: 'divider', pt: open.length ? .6 : 0 }}>
        <Button
          size="small" color="inherit" aria-expanded={showReviewed} aria-controls={reviewedId}
          onClick={() => setShowReviewed(value => !value)}
        >{showReviewed ? 'Hide' : 'Show'} {reviewed.length} kept as entered</Button>
        <Box id={reviewedId} hidden={!showReviewed} role="list" aria-label="Entry checks kept as entered">
          {showReviewed && reviewed.map(renderCheck)}
        </Box>
      </Box>}
    </Box>}

    <FormDialog
      open={Boolean(keeping)} maxWidth="sm"
      title="Keep this value as entered?"
      subtitle="The value stays as it is and this check stops counting as open. Your name, the time and the note are written to the audit trail. The check can be reopened while the sheet is a Draft."
      onClose={() => { if (!keepBusy) setKeeping(null) }}
      onSubmit={() => void keep()}
      busy={keepBusy} busyLabel="Recording…" submitLabel="Keep as entered"
      dirty={Boolean(note.trim())}
    >
      <Box display="grid" gap={1.5}>
        {keeping && <Box sx={{ border: '1px solid', borderColor: 'divider', borderRadius: 2, p: 1.4 }}>
          <Typography fontSize={12.5} fontWeight={700} sx={{ overflowWrap: 'anywhere' }}>{keeping.title}</Typography>
          <Typography fontSize={12.5} mt={.4} sx={{ lineHeight: 1.5, overflowWrap: 'anywhere' }}>{keeping.message}</Typography>
          {keeping.basis && <Typography fontSize={11.5} color="text.secondary" mt={.2} sx={{ lineHeight: 1.5 }}>{keeping.basis}</Typography>}
        </Box>}
        <TextField
          label="Note (optional)" value={note} multiline minRows={2}
          onChange={event => setNote(event.target.value.slice(0, NOTE_LIMIT))}
          inputProps={{ maxLength: NOTE_LIMIT }}
          helperText={`Why the value is right, for example a bulk delivery or a rig move. ${note.length}/${NOTE_LIMIT}`}
        />
        <ErrorMessage message={keepError}/>
      </Box>
    </FormDialog>
  </Paper>
}
