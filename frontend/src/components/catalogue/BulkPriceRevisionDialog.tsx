import { useEffect, useMemo, useState } from 'react'
import {
  Alert, Box, Button, CircularProgress, Paper, Table, TableBody, TableCell, TableHead, TableRow, TextField, Typography,
} from '@mui/material'
import { CloudUploadOutlined, DescriptionOutlined, GetAppRounded, PriceChangeOutlined, ReplayRounded } from '@mui/icons-material'
import { FormDialog } from '../Common'
import { api, body, downloadFile } from '../../lib/api'
import type { PricedRecord, TypeConfig } from '../../lib/catalogue'
import { parseImportFile, type ImportRow } from '../../lib/export'

/**
 * Bulk price revision, in the order the operator does it:
 *   1. download the current price list (every active code, its price and uplift),
 *   2. edit only the prices that moved, keeping the file,
 *   3. upload it — one all-or-nothing revision, one effective date, one audit entry.
 *
 * The file identifies rows by code only. A row whose price is unchanged is
 * counted and reported, never rewritten, so an untouched file cannot create a
 * revision. Row errors come back from the server and stay on screen next to the
 * chosen file until the operator fixes the file and uploads again.
 */
type RevisionResult = {
  revised_count: number
  unchanged_count: number
  error_count: number
  skipped_count: number
  original_rate: string | null
  new_rate: string | null
  currency: string
  effective_date: string | null
  errors: string[]
  warnings: string[]
}

const MAX_REPORTED_ERRORS = 12
/** Mirrors the server's rule so the button is disabled for the same reason it would fail. */
const MIN_REASON_LENGTH = 3

/** A spreadsheet number as typed: 1250, 12.5 — never 1250.0000000000. */
function readableNumber(value: string): string {
  const trimmed = value.trim()
  const numeric = Number(trimmed)
  if (!Number.isFinite(numeric)) return trimmed
  return String(Number(numeric.toFixed(4)))
}

const columnsFor = (config: TypeConfig): { key: string; label: string; numeric?: boolean }[] => [
  { key: config.codeKey, label: config.codeLabel },
  { key: config.nameKey, label: config.nameLabel },
  { key: 'unit_rate', label: config.priced === 'uplift' ? 'Rate as per PO' : 'Unit rate', numeric: true },
  ...(config.priced === 'uplift' ? [{ key: 'cost_uplift', label: 'Uplift %', numeric: true }] : []),
  { key: 'currency', label: 'Currency' },
]

/**
 * Codes whose uploaded price differs from the price on record — exactly the rows
 * the server will revise. Comparing against the register means the preview is
 * live from the first keystroke and needs no second download.
 */
function changedCodes(uploaded: ImportRow[], current: PricedRecord[], config: TypeConfig): string[] {
  const before = new Map(current.map(record => [
    String(record[config.codeKey] ?? '').trim().toUpperCase(),
    Number(record.unit_rate),
  ]))
  return uploaded.filter(row => {
    const code = (row[config.codeKey] ?? '').trim().toUpperCase()
    if (!code || !before.has(code)) return false
    const rate = Number((row.unit_rate ?? '').trim())
    return Number.isFinite(rate) && Math.abs(rate - (before.get(code) as number)) > 1e-9
  }).map(row => (row[config.codeKey] ?? '').trim().toUpperCase())
}

export function BulkPriceRevisionDialog({ open, onClose, config, current, onRevised }: {
  open: boolean
  onClose: () => void
  config: TypeConfig
  /** The register's active records, used to show which uploaded rows change. */
  current: PricedRecord[]
  /** Called after a successful upload so the register can refresh. */
  onRevised: (summary: string) => void
}) {
  const [fileName, setFileName] = useState('')
  const [uploaded, setUploaded] = useState<ImportRow[]>([])
  const [reason, setReason] = useState('')
  const [effectiveDate, setEffectiveDate] = useState('')
  const [result, setResult] = useState<RevisionResult | null>(null)
  const [problems, setProblems] = useState<string[]>([])
  const [busy, setBusy] = useState(false)
  const [downloading, setDownloading] = useState(false)
  const [parsing, setParsing] = useState(false)

  const reset = () => {
    setFileName(''); setUploaded([])
    setReason(''); setEffectiveDate(''); setResult(null); setProblems([])
    setBusy(false); setDownloading(false); setParsing(false)
  }
  const close = () => { if (!busy) { reset(); onClose() } }
  useEffect(() => { if (!open) reset() }, [open])

  const tableColumns = useMemo(() => columnsFor(config), [config])
  const changed = useMemo(() => changedCodes(uploaded, current, config), [uploaded, current, config])
  const dirty = Boolean(fileName || reason || effectiveDate)

  const download = async () => {
    setDownloading(true); setProblems([])
    try {
      await downloadFile(
        `/master-data/${config.key}/price-revision-template`,
        `${config.key}-price-revision.csv`,
      )
    } catch (caught) {
      setProblems([(caught as Error).message || 'The price list could not be downloaded. Try again.'])
    } finally {
      setDownloading(false)
    }
  }

  const pick = async (file: File | undefined) => {
    if (!file) return
    setParsing(true); setProblems([]); setResult(null); setFileName(file.name)
    try {
      const parsed = await parseImportFile(file)
      const codeHeader = parsed.headers.find(header => header === config.codeKey)
        ?? parsed.headers.find(header => header.trim().toUpperCase().replace(/[\s_-]+/g, '') === config.codeKey.toUpperCase())
      if (!codeHeader) {
        setUploaded([])
        setProblems([`This file has no ${config.codeLabel} column. Download the price list above and edit that file — do not rename the code column.`])
        return
      }
      if (codeHeader !== config.codeKey) {
        // Renamed identifying column: remap so the preview and the upload agree.
        for (const row of parsed.rows) row[config.codeKey] = row[codeHeader]
      }
      setUploaded(parsed.rows)
      if (!parsed.rows.length) setProblems(['The file contains no data rows.'])
    } catch (caught) {
      setUploaded([])
      setProblems([(caught as Error).message || 'Could not read this file. Use .xlsx or .csv.'])
    } finally {
      setParsing(false)
    }
  }

  const run = async () => {
    setBusy(true); setProblems([]); setResult(null)
    try {
      const response = await api<RevisionResult>(`/master-data/${config.key}/bulk-revise`, {
        method: 'POST',
        body: body({
          rows: uploaded.map(row => Object.fromEntries(Object.entries(row).filter(([, value]) => value !== ''))),
          reason,
          effective_date: effectiveDate || null,
        }),
      })
      setResult(response)
      const summary = `${response.revised_count} ${response.revised_count === 1 ? config.singular : `${config.singular}s`} revised`
        + (response.effective_date ? ` effective ${response.effective_date.split('-').reverse().join('/')}` : '')
        + (response.unchanged_count ? `, ${response.unchanged_count} unchanged` : '')
        + (response.skipped_count ? `, ${response.skipped_count} skipped` : '')
      onRevised(`${summary}. Every change is recorded in Price history and the audit trail.`)
      reset()
      onClose()
    } catch (caught) {
      setProblems([(caught as Error).message || 'The revision could not be applied.'])
    } finally {
      setBusy(false)
    }
  }

  // The server wants a real reason (3+ characters) recorded with every revised
  // record, so the dialog must not offer a button the server will refuse.
  const disabled = !uploaded.length || reason.trim().length < MIN_REASON_LENGTH || changed.length === 0

  return <FormDialog
    open={open}
    onClose={close}
    onSubmit={run}
    busy={busy}
    dirty={dirty}
    maxWidth="lg"
    submitDisabled={disabled}
    busyLabel="Applying revision..."
    submitLabel={changed.length ? `Revise ${changed.length} ${changed.length === 1 ? 'price' : 'prices'}` : 'Revise prices'}
    title={`Bulk price revision · ${config.label}`}
    subtitle="Download the current price list, change only the prices that moved, then upload the same file. Nothing else on the record changes."
  >
    <Box display="grid" gap={2} pt={.5}>
      <Paper variant="outlined" sx={{ p: 1.6, borderRadius: 2 }}>
        <Box display="flex" gap={1} flexWrap="wrap" alignItems="center">
          <Typography fontSize={11} fontWeight={800} letterSpacing=".09em" textTransform="uppercase" color="text.secondary" sx={{ flexBasis: '100%' }}>
            Step 1 · Get the current price list
          </Typography>
          <Button
            variant="outlined"
            startIcon={downloading ? <CircularProgress size={15}/> : <GetAppRounded sx={{ fontSize: 18 }}/>}
            onClick={() => { void download() }}
            disabled={busy || downloading}
          >
            Download price list
          </Button>
          <Typography fontSize={12} color="text.secondary">
            Every active {config.singular} with its current rate, uplift, description and revision number. Open it in Excel or Numbers.
          </Typography>
        </Box>
      </Paper>

      <Paper variant="outlined" sx={{ p: 1.6, borderRadius: 2 }}>
        <Typography fontSize={11} fontWeight={800} letterSpacing=".09em" textTransform="uppercase" color="text.secondary" mb={1}>
          Step 2 · Upload the edited file
        </Typography>
        <Box display="flex" gap={1} flexWrap="wrap" alignItems="center" mb={1.2}>
          <Button
            component="label"
            variant="outlined"
            startIcon={parsing ? <CircularProgress size={15}/> : <CloudUploadOutlined sx={{ fontSize: 18 }}/>}
            disabled={busy || parsing}
          >
            Choose edited file (.xlsx or .csv)
            <input hidden type="file" accept=".xlsx,.csv" onChange={event => { void pick(event.target.files?.[0]); event.target.value = '' }}/>
          </Button>
          {fileName && <Box display="flex" alignItems="center" gap={.6}>
            <DescriptionOutlined sx={{ fontSize: 17, color: 'text.secondary' }}/>
            <Typography fontSize={12.5} fontWeight={700}>{fileName}</Typography>
            <Typography fontSize={12} color="text.secondary">· {uploaded.length} rows</Typography>
          </Box>}
          {fileName && <Button size="small" color="inherit" startIcon={<ReplayRounded sx={{ fontSize: 16 }}/>} onClick={reset} disabled={busy}>
            Clear
          </Button>}
        </Box>
        <Box display="grid" gap={1.5} sx={{ gridTemplateColumns: { xs: '1fr', sm: '1.6fr 1fr' } }}>
          <TextField
            label="Reason for the price change" value={reason} onChange={event => setReason(event.target.value)}
            placeholder="e.g. Annual vendor increase, Q4 re-quote"
            helperText="At least 3 characters. Stored with every revised record and shown in Price history."
            disabled={busy}
            required
          />
          <TextField
            type="date" label="Effective date" value={effectiveDate}
            onChange={event => setEffectiveDate(event.target.value)}
            InputLabelProps={{ shrink: true }}
            helperText="Optional. Defaults to today; a future date is not accepted."
            disabled={busy}
          />
        </Box>
      </Paper>

      {uploaded.length > 0 && <Paper variant="outlined" sx={{ borderRadius: 2, overflow: 'hidden' }}>
        <Box display="flex" alignItems="center" gap={1} flexWrap="wrap" px={1.6} py={1} sx={{ bgcolor: 'background.default', borderBottom: '1px solid', borderColor: 'divider' }}>
          <PriceChangeOutlined sx={{ fontSize: 17, color: 'text.secondary' }}/>
          <Typography fontSize={12} fontWeight={800}>
            {changed.length ? `${changed.length} ${changed.length === 1 ? 'price' : 'prices'} will change` : 'No price changed yet'}
          </Typography>
          <Typography fontSize={11.5} color="text.secondary">
            {uploaded.length} row{uploaded.length === 1 ? '' : 's'} read · {uploaded.length - changed.length} left at the current price
          </Typography>
          {changed.length > 0 && <Typography fontSize={11.5} color="text.secondary" ml="auto">
            {changed.slice(0, 6).join(', ')}{changed.length > 6 ? ` +${changed.length - 6} more` : ''}
          </Typography>}
        </Box>
        <Box sx={{ maxHeight: 260, overflow: 'auto' }}>
          <Table size="small" stickyHeader>
            <TableHead>
              <TableRow>
                {tableColumns.map(column => <TableCell key={column.key} align={column.numeric ? 'right' : 'left'}
                  sx={{ fontWeight: 800, fontSize: 11, bgcolor: 'background.paper', textTransform: 'uppercase', letterSpacing: '.05em' }}>
                  {column.label}
                </TableCell>)}
                <TableCell sx={{ fontWeight: 800, fontSize: 11, bgcolor: 'background.paper' }}>CHANGE</TableCell>
              </TableRow>
            </TableHead>
            <TableBody>
              {uploaded.slice(0, 50).map((row, index) => {
                const code = (row[config.codeKey] ?? '').trim().toUpperCase()
                const isChanged = changed.includes(code)
                return <TableRow key={index} hover sx={isChanged ? { bgcolor: 'action.hover' } : undefined}>
                  {tableColumns.map(column => <TableCell key={column.key} align={column.numeric ? 'right' : 'left'}
                    sx={{ fontSize: 12, whiteSpace: 'nowrap' }}>
                    {/* Prices are shown exactly as the file holds them, so the operator
                        can compare the preview against the spreadsheet cell by cell. */}
                    {row[column.key] ? (column.numeric ? readableNumber(row[column.key]) : row[column.key]) : '—'}
                  </TableCell>)}
                  <TableCell sx={{ fontSize: 12 }}>
                    {isChanged ? <Typography component="span" fontSize={11.5} fontWeight={800} color="warning.dark">Price changed</Typography> : <Typography component="span" fontSize={11.5} color="text.secondary">Unchanged</Typography>}
                  </TableCell>
                </TableRow>
              })}
            </TableBody>
          </Table>
        </Box>
        {uploaded.length > 50 && <Typography fontSize={11} color="text.secondary" sx={{ p: 1.2 }}>
          Preview shows the first 50 of {uploaded.length} rows. All {uploaded.length} rows are sent.
        </Typography>}
      </Paper>}

      {problems.length > 0 && <Box display="grid" gap={1}>
        <Alert severity="error">
          <Typography fontSize={12.5} fontWeight={800} mb={.4}>
            {problems.length === 1 ? 'The revision was not applied.' : 'The revision was not applied.'}
          </Typography>
          <Typography fontSize={12}>
            No price was changed. Fix the file and upload it again.
          </Typography>
        </Alert>
        {problems.slice(0, MAX_REPORTED_ERRORS).map((message, index) => <Alert key={index} severity="error" sx={{ fontSize: 12.5 }}>{message}</Alert>)}
        {problems.length > MAX_REPORTED_ERRORS && <Typography fontSize={12} color="text.secondary">
          {problems.length - MAX_REPORTED_ERRORS} more problem{problems.length - MAX_REPORTED_ERRORS === 1 ? '' : 's'} not shown.
        </Typography>}
      </Box>}

      {result && result.warnings.length > 0 && <Alert severity="warning">
        {result.warnings.slice(0, MAX_REPORTED_ERRORS).join(' ')}
      </Alert>}
    </Box>
  </FormDialog>
}
