import { useEffect, useId, useState } from 'react'
import { Link as RouterLink } from 'react-router-dom'
import { Box, Button, Link, Paper, Typography } from '@mui/material'
import { ErrorMessage, Tag } from '../Common'
import { DAILY_COST_STATUSES, displayDate, type DailyCostStatus } from '../../lib/dailyCost'
import { fetchWellEntryChecks, type SheetEntryChecks, type WellEntryChecks } from '../../lib/entryChecks'

/** Open findings named under one sheet before "and N more". */
const TITLE_LIMIT = 3

const statusLabel = (status: string) => DAILY_COST_STATUSES[status as DailyCostStatus] ?? status

/**
 * Entry checks across one well: which daily sheets still carry a value that
 * looks mistyped. It only points at the sheets; a value is corrected or kept as
 * entered on the sheet itself, where the evidence and the audit trail are.
 */
export function WellEntryChecksCard({ wellId, refreshKey }: {
  wellId: string
  /** Change this value to read the checks again, e.g. after the page reloads its figures. */
  refreshKey?: unknown
}) {
  const headingId = useId()
  const listId = useId()
  const [data, setData] = useState<WellEntryChecks | null>(null)
  const [error, setError] = useState('')
  const [retry, setRetry] = useState(0)
  const [expanded, setExpanded] = useState(false)

  useEffect(() => {
    if (!wellId) return
    const controller = new AbortController()
    setError('')
    setData(current => current && current.well_id !== wellId ? null : current)
    fetchWellEntryChecks(wellId, undefined, controller.signal)
      .then(result => { if (!controller.signal.aborted) setData(result) })
      .catch(caught => {
        if (!controller.signal.aborted) setError(caught instanceof Error ? caught.message : 'Try again in a moment.')
      })
    return () => controller.abort()
  }, [wellId, refreshKey, retry])

  if (error) {
    return <Paper component="section" variant="outlined" aria-labelledby={headingId} sx={{ p: 1.6, borderRadius: 2, mb: 1.4 }}>
      <Typography id={headingId} component="h2" fontWeight={800} fontSize={13.5}>Entry checks</Typography>
      <Box display="flex" alignItems="center" flexWrap="wrap" gap={1}>
        <ErrorMessage message={`Entry checks could not be loaded. ${error}`}/>
        <Button size="small" onClick={() => setRetry(value => value + 1)} sx={{ mt: 1.5 }}>Retry</Button>
      </Box>
    </Paper>
  }
  // Nothing to say until the first answer, when the checks are turned off, or on a well without sheets.
  if (!data || !data.enabled || data.sheets_checked === 0) return null

  const open = data.open_warnings + data.open_notices
  const openSheets = data.sheets.filter(sheet => sheet.open_warnings + sheet.open_notices > 0)
  const keptOnly = data.sheets.length - openSheets.length
  const sheetsWord = (count: number) => `${count} sheet${count === 1 ? '' : 's'}`

  const renderSheet = (sheet: SheetEntryChecks) => {
    const titles = sheet.checks.filter(check => !check.reviewed).map(check => check.title)
    const more = titles.length - TITLE_LIMIT
    return <Box key={sheet.entry_id} role="listitem" sx={{ py: 1, borderTop: '1px solid', borderColor: 'divider' }}>
      <Box display="flex" alignItems="center" flexWrap="wrap" gap={.8}>
        <Link component={RouterLink} to={`/daily-cost/entries/${sheet.entry_id}`} underline="hover" fontSize={12.5} fontWeight={700}>
          {sheet.daily_cost_code}
        </Link>
        <Typography fontSize={12} color="text.secondary">{displayDate(sheet.cost_date)} · {sheet.afe_code}</Typography>
        <Tag tone="neutral">{statusLabel(sheet.status)}</Tag>
        {sheet.open_warnings > 0 && <Tag tone="warning">{sheet.open_warnings} to check</Tag>}
        {sheet.open_notices > 0 && <Tag tone="info">{sheet.open_notices} to note</Tag>}
      </Box>
      <Typography fontSize={12} color="text.secondary" mt={.3} sx={{ lineHeight: 1.5, overflowWrap: 'anywhere' }}>
        {titles.slice(0, TITLE_LIMIT).join('; ')}{more > 0 ? `; and ${more} more` : ''}
      </Typography>
    </Box>
  }

  return <Paper component="section" variant="outlined" aria-labelledby={headingId} sx={{ p: 1.6, borderRadius: 2, mb: 1.4 }}>
    <Box display="flex" alignItems="center" flexWrap="wrap" gap={1}>
      <Typography id={headingId} component="h2" fontWeight={800} fontSize={13.5}>Entry checks</Typography>
      {data.open_warnings > 0 && <Tag tone="warning">{data.open_warnings} to check</Tag>}
      {data.open_notices > 0 && <Tag tone="info">{data.open_notices} to note</Tag>}
      {data.reviewed > 0 && <Tag tone="neutral">{data.reviewed} kept as entered</Tag>}
      {open === 0 && <Tag tone="success">Nothing open</Tag>}
      <Typography fontSize={12} color="text.secondary" sx={{ flex: 1, minWidth: 220, lineHeight: 1.5 }}>
        {open > 0
          ? `${openSheets.length} of the ${sheetsWord(data.sheets_checked)} of this well ${openSheets.length === 1 ? 'carries' : 'carry'} a value that looks mistyped. Open a sheet to correct it or keep it as entered.`
          : `No open check on the ${sheetsWord(data.sheets_checked)} of this well.`}
        {data.truncated && ' Only the newest sheets of the well are covered here.'}
      </Typography>
      {openSheets.length > 0 && <Button
        size="small" color="inherit" aria-expanded={expanded} aria-controls={listId}
        onClick={() => setExpanded(value => !value)}
      >{expanded ? 'Hide sheets' : 'Show sheets'}</Button>}
    </Box>
    {openSheets.length > 0 && <Box id={listId} hidden={!expanded} mt={.8}>
      {expanded && <>
        <Box role="list" aria-label="Daily sheets with open entry checks">{openSheets.map(renderSheet)}</Box>
        {keptOnly > 0 && <Typography fontSize={11.5} color="text.secondary" mt={.6}>
          {keptOnly === 1 ? '1 other sheet carries' : `${keptOnly} other sheets carry`} only values kept as entered.
        </Typography>}
        <Typography fontSize={11.5} color="text.secondary" mt={.4}>
          Covers every sheet of the well, whatever period or draft filter is chosen above.
        </Typography>
      </>}
    </Box>}
  </Paper>
}
