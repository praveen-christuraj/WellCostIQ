import { useMemo, useRef, useState } from 'react'
import {
  Alert,
  Box,
  Button,
  FormControlLabel,
  MenuItem,
  Radio,
  RadioGroup,
  Stack,
  Table,
  TableBody,
  TableCell,
  TableHead,
  TablePagination,
  TableRow,
  TextField,
  Typography,
} from '@mui/material'
import { DeleteOutlineRounded, UploadRounded } from '@mui/icons-material'
import { FormDialog } from '../Common'
import { previewPlannedSurvey, previewSurvey, type OpsSurvey, type OpsSurveyPreview } from '../../lib/operations'

const FIELDS: { key: keyof OpsSurvey; label: string; width: number }[] = [
  { key: 'md_m', label: 'MD (m)', width: 96 },
  { key: 'inc_deg', label: 'Inc (°)', width: 84 },
  { key: 'azi_deg', label: 'Azi (°)', width: 84 },
  { key: 'tvd_m', label: 'TVD (m)', width: 96 },
  { key: 'ns_m', label: 'N/S (m)', width: 88 },
  { key: 'ew_m', label: 'E/W (m)', width: 88 },
  { key: 'vsec_m', label: 'VS (m)', width: 88 },
  { key: 'dls_deg_per_30m', label: 'DLS (°/30m)', width: 96 },
  { key: 'tool', label: 'Tool', width: 96 },
  { key: 'survey_at', label: 'Survey at', width: 150 },
]

const isNumberish = (value: string | null | undefined) =>
  value === null || value === undefined || value === '' || /^[+-]?\d+(\.\d+)?$/.test(value.trim())

/**
 * Review-before-write for an imported survey file — the survey twin of the DDR
 * import. The file is studied on the server; this dialog shows exactly what the
 * engine read (format, unit basis, every station) and lets the engineer correct
 * or delete rows before anything is applied. Applying only stages the stations
 * in the report form; the report's ordinary Save is what writes them.
 */
export function SurveyImportDialog({
  open,
  reportId,
  planId,
  existingCount,
  busy,
  onClose,
  onApply,
}: {
  open: boolean
  reportId?: string
  planId?: string
  existingCount: number
  busy: boolean
  onClose: () => void
  onApply: (stations: OpsSurvey[], mode: 'append' | 'replace', preview: OpsSurveyPreview) => void
}) {
  const [rows, setRows] = useState<OpsSurvey[] | null>(null)
  const [preview, setPreview] = useState<OpsSurveyPreview | null>(null)
  const [error, setError] = useState('')
  const [busyStudy, setBusyStudy] = useState(false)
  const [page, setPage] = useState(0)
  const [size, setSize] = useState(20)
  const [file, setFile] = useState<File | null>(null)
  const [edited, setEdited] = useState(false)
  const [confirmPreview, setConfirmPreview] = useState<{ file: File; sheet: string } | null>(null)
  const [mode, setMode] = useState<'append' | 'replace'>('append')
  const inputRef = useRef<HTMLInputElement | null>(null)

  const reset = () => {
    setRows(null)
    setPreview(null)
    setFile(null)
    setEdited(false)
    setPage(0)
    setError('')
    setMode('append')
  }
  const close = () => {
    reset()
    onClose()
  }
  const study = async (file: File, sheet = '') => {
    setBusyStudy(true)
    setError('')
    try {
      const result = planId ? await previewPlannedSurvey(planId, file, sheet) : await previewSurvey(reportId ?? '', file)
      setFile(file)
      setEdited(false)
      setPage(0)
      setPreview(result)
      setRows(result.stations.map(({ md_m, inc_deg, azi_deg, tvd_m, ns_m, ew_m, vsec_m, dls_deg_per_30m, tool, source, survey_at }) =>
        ({ md_m, inc_deg, azi_deg, tvd_m, ns_m, ew_m, vsec_m, dls_deg_per_30m, tool, source, survey_at })))
      setMode(existingCount > 0 ? 'append' : 'replace')
    } catch (e) {
      setError((e as Error).message)
    } finally {
      setBusyStudy(false)
    }
  }
  const requestStudy = (file: File, sheet = '') => {
    if (edited) setConfirmPreview({ file, sheet })
    else void study(file, sheet)
  }
  const change = (idx: number, patch: Partial<OpsSurvey>) => {
    setEdited(true)
    setRows((prev) => (prev ? prev.map((row, i) => (i === idx ? { ...row, ...patch } : row)) : prev))
  }
  const invalidRow = useMemo(() => {
    if (!rows) return null
    for (let i = 0; i < rows.length; i += 1) {
      const row = rows[i]
      if (!row.md_m || !isNumberish(row.md_m) || (planId && Number(row.md_m) < 0)) return i
      for (const key of ['inc_deg', 'azi_deg', 'tvd_m', 'ns_m', 'ew_m', 'vsec_m', 'dls_deg_per_30m'] as const) {
        if (!isNumberish(row[key])) return i
      }
      const inc = Number(row.inc_deg)
      if (row.inc_deg != null && row.inc_deg !== '' && (!Number.isFinite(inc) || inc < 0 || inc > 180)) return i
      if (planId && (!row.inc_deg || (inc >= 1 && !row.azi_deg))) return i
      const azi = Number(row.azi_deg)
      if (row.azi_deg != null && row.azi_deg !== '' && (!Number.isFinite(azi) || azi < 0 || azi > 360)) return i
    }
    return null
  }, [rows, planId])
  const unit = preview?.unit ?? 'm'
  return (<>
    <FormDialog
      open={open}
      title={planId ? "Import planned directional survey" : "Import directional survey"}
      subtitle={`Choose a CSV, Excel workbook or supported text PDF. Review the extracted stations before applying them. Nothing is written until you ${planId ? "save the planned survey" : "save the report"}.`}
      onSubmit={() => {
        if (!rows?.length || !preview || busy || busyStudy || invalidRow !== null) return
        onApply(rows, mode, preview)
        close()
      }}
      onClose={close}
      busy={busy || busyStudy}
      dirty={planId ? Boolean(rows) : undefined}
      submitDisabled={!rows?.length || busy || invalidRow !== null}
      submitLabel={planId ? "Apply to draft" : "Add reviewed stations"}
      maxWidth={false}
    >
      <Stack spacing={1.5} pt={1}>
        <Box display="flex" gap={1} alignItems="center" flexWrap="wrap">
          <Button variant="outlined" startIcon={<UploadRounded />} disabled={busyStudy} component="label">
            {busyStudy ? 'Studying the file…' : 'Choose file'}
            <input
              ref={inputRef}
              hidden
              type="file"
              accept={planId ? ".csv,.xlsx,.xlsm,.xls,.pdf" : ".csv,.xlsx,.xlsm,.pdf"}
              data-testid="survey-file-input"
              onChange={(event) => {
                const file = event.target.files?.[0]
                if (file) requestStudy(file)
                event.target.value = ''
              }}
            />
          </Button>
          {preview && (
            <Typography variant="body2" color="text.secondary">
              {preview.file_name} — {preview.format.toUpperCase()}{preview.detected_sheet ? ` · sheet “${preview.detected_sheet}”` : ''} · depths in {unit === 'ft' ? 'feet (converted to metres)' : 'metres'}
            </Typography>
          )}
        </Box>

        {planId && file && preview && preview.format === 'excel' && preview.sheets.length > 1 && (
          <TextField select size="small" label="Survey sheet" value={preview.detected_sheet ?? ''} disabled={busyStudy}
            onChange={event => requestStudy(file, event.target.value)}>
            {preview.sheets.map(sheet => <MenuItem key={sheet} value={sheet}>{sheet}</MenuItem>)}
          </TextField>
        )}
        {error && <Alert severity="error">{error}</Alert>}

        {preview && preview.warnings.length > 0 && (
          <Alert severity="warning" sx={{ '& .MuiAlert-message': { width: '100%' } }}>
            <Typography variant="subtitle2" sx={{ mb: 0.5 }}>Study notes — check these before applying</Typography>
            <Box component="ul" sx={{ m: 0, pl: 2.5 }}>
              {preview.warnings.map((warning) => (
                <li key={warning}>{warning}</li>
              ))}
            </Box>
          </Alert>
        )}

        {rows && (
          <>
            <Box sx={{ maxHeight: 380, overflow: 'auto' }}>
              <Table size="small" stickyHeader>
                <TableHead>
                  <TableRow>
                    <TableCell sx={{ fontWeight: 700 }}>#</TableCell>
                    {FIELDS.map(({ key, label, width }) => (
                      <TableCell key={key} sx={{ fontWeight: 700, minWidth: width }}>{label}</TableCell>
                    ))}
                    <TableCell />
                  </TableRow>
                </TableHead>
                <TableBody>
                  {rows.slice(page * size, (page + 1) * size).map((row, index) => {
                    const idx = page * size + index
                    return (
                    <TableRow key={idx} sx={idx === invalidRow ? { bgcolor: 'error.light' } : undefined}>
                      <TableCell>{idx + 1}</TableCell>
                      {FIELDS.map(({ key, width }) => (
                        <TableCell key={key} sx={{ p: 0.25 }}>
                          <TextField
                            size="small"
                            disabled={busy || busyStudy}
                            value={(row[key] as string | null) ?? ''}
                            onChange={(event) => change(idx, { [key]: event.target.value === '' ? (key === 'tool' || key === 'survey_at' ? '' : null) : event.target.value } as Partial<OpsSurvey>)}
                            sx={{ width }}
                            inputProps={{ 'aria-label': FIELDS.find((f) => f.key === key)?.label }}
                          />
                        </TableCell>
                      ))}
                      <TableCell>
                        <Button size="small" color="error" disabled={busy || busyStudy} onClick={() => {
                          setEdited(true)
                          setRows(rows.filter((_, i) => i !== idx))
                          setPage(Math.min(page, Math.max(0, Math.ceil((rows.length - 1) / size) - 1)))
                        }} aria-label={`Remove station ${idx + 1}`}>
                          <DeleteOutlineRounded fontSize="small" />
                        </Button>
                      </TableCell>
                    </TableRow>
                  )})}
                </TableBody>
              </Table>
            </Box>
            <TablePagination component="div" count={rows.length} page={page} rowsPerPage={size} rowsPerPageOptions={[20, 50, 100]}
              onPageChange={(_, next) => setPage(next)} onRowsPerPageChange={event => { setSize(Number(event.target.value)); setPage(0) }} />
            {invalidRow !== null && (
              <Alert severity="error">
                Station {invalidRow + 1}: check MD and the angle ranges (inclination 0–180°, azimuth 0–360°).{planId ? " Inclination is required; deviated stations also need azimuth." : ""}
              </Alert>
            )}
            <RadioGroup
              row
              value={mode}
              onChange={(event) => setMode(event.target.value as 'append' | 'replace')}
              aria-label="How to apply the imported stations"
            >
              <FormControlLabel value="append" control={<Radio size="small" />} label={`Append to the ${existingCount} existing station(s)`} />
              <FormControlLabel value="replace" control={<Radio size="small" />} label="Replace the existing stations" />
            </RadioGroup>
            <Typography variant="caption" color="text.secondary">
              Applying only stages the stations. Press “{planId ? "Save planned survey" : "Save report"}” to write them. Feet from the file have already been converted to metres.
            </Typography>
          </>
        )}

        {!rows && !error && !busyStudy && (
          <Typography variant="body2" color="text.secondary">
            Template columns: md_m, inc_deg, azi_deg, tvd_m, ns_m, ew_m, vsec_m, dls_deg_per_30m, tool, survey_at.
            Depths may be metres or feet (converted automatically). Blank cells stay blank.
          </Typography>
        )}
      </Stack>
    </FormDialog>
    {confirmPreview && <FormDialog open title="Discard reviewed preview edits?"
      subtitle="Switching the file or sheet will replace the extracted rows you edited in this preview." submitLabel="Discard and read file"
      onClose={() => setConfirmPreview(null)} onSubmit={() => {
        const next = confirmPreview
        setConfirmPreview(null)
        void study(next.file, next.sheet)
      }}>{null}</FormDialog>}
  </>)
}
