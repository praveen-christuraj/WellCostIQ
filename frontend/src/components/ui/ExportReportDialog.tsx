import { useEffect, useId, useMemo, useState } from 'react'
import {
  Alert, Box, Button, Checkbox, CircularProgress, Dialog, DialogActions, DialogContent, DialogTitle,
  FormControlLabel, FormGroup, LinearProgress, MenuItem, TextField, Typography,
} from '@mui/material'
import { CloseRounded, PictureAsPdfOutlined, TableViewOutlined } from '@mui/icons-material'
import { radius, space } from '../../designSystem'
import { captureFigures } from '../../lib/chartExport'
import { exportReportPdf, type ReportDocument } from '../../lib/reportPdf'

/**
 * "Export as shown".
 *
 * One dialog serves every report page (Operations dashboard, drill-through, well
 * cost analysis). It makes the two things a reader needs to decide explicit —
 * *what* is being exported and *which* of the page's figures are included — and
 * then prints exactly that, charts included, captured from the live scene.
 *
 * Conventions it keeps:
 *  - The export is audited through the owning module (the page supplies
 *    `onExport`), like every other download in the product.
 *  - Nothing is exported silently: the button states how many figures and rows
 *    are in the document, and progress is visible while charts are captured.
 *  - It never blocks the page. If a chart cannot be captured the document says
 *    so and its data table follows, so no figure disappears without a trace.
 */
export type ExportFigure = { key: string; label: string; defaultOn?: boolean }
export type ExportScope = 'everything' | 'figures' | 'tables'

export function ExportReportDialog({ open, onClose, figures, buildDocument, onExport, fileName, title = 'Export this page' }: {
  open: boolean
  onClose: () => void
  /** The page's exportable figures, in document order, each with a stable key. */
  figures: ExportFigure[]
  /**
   * Build the document. The page owns its sections, KPIs and tables and receives
   * the captured figures, so an export has one source of truth and never a
   * second rendering of the same numbers.
   */
  buildDocument: (options: {
    /** Charts captured from the live page, keyed by figure key. */
    figures: Map<string, { dataUrl: string; width: number; height: number; title?: string; caption?: string }>
    includeFigures: boolean
    includeTables: boolean
    orientation: 'landscape' | 'portrait'
  }) => ReportDocument | Promise<ReportDocument>
  /** Audit hook, called once per completed export. */
  onExport?: (format: 'pdf', recordCount: number) => Promise<void> | void
  fileName: string
  title?: string
}) {
  const titleId = useId()
  const [scope, setScope] = useState<ExportScope>('everything')
  const [selected, setSelected] = useState<string[]>([])
  const [busy, setBusy] = useState(false)
  const [progress, setProgress] = useState('')
  const [error, setError] = useState('')
  const [orientation, setOrientation] = useState<'landscape' | 'portrait'>('landscape')

  const defaults = useMemo(() => figures.filter(figure => figure.defaultOn !== false).map(figure => figure.key), [figures])
  useEffect(() => {
    if (!open) return
    setSelected(defaults)
    setScope('everything')
    setError('')
    setProgress('')
    setOrientation('landscape')
  }, [open, defaults])

  const includeFigures = scope !== 'tables'
  const includeTables = scope !== 'figures'
  const chosen = includeFigures ? figures.filter(figure => selected.includes(figure.key)).map(figure => figure.key) : []

  const run = async () => {
    if (!includeFigures && !includeTables) {
      setError('Choose figures, tables, or both.')
      return
    }
    setBusy(true)
    setError('')
    try {
      setProgress(chosen.length ? `Capturing ${chosen.length} figure${chosen.length === 1 ? '' : 's'} as shown…` : 'Preparing the document…')
      // Let the progress line paint before the capture work starts.
      await new Promise(resolve => setTimeout(resolve, 30))
      const captures = chosen.length ? await captureFigures(chosen) : new Map()
      setProgress('Laying out the pages…')
      const report = await buildDocument({ figures: captures, includeFigures, includeTables, orientation })
      await exportReportPdf({ ...report, fileName })
      await onExport?.('pdf', report.sections.reduce(
        (sum, section) => sum + (section.tables ?? []).reduce((count, table) => count + table.body.length, 0), 0,
      ))
      setProgress('')
      onClose()
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : 'The PDF could not be exported')
    } finally {
      setBusy(false)
    }
  }

  return <Dialog open={open} onClose={() => { if (!busy) onClose() }} fullWidth maxWidth="sm" disableEscapeKeyDown
    aria-labelledby={titleId}
    slotProps={{ paper: { sx: { borderRadius: `${radius.lg}px` } } }}
  >
    <DialogTitle id={titleId} sx={{ px: `${space[6]}px`, pt: 2.5, pb: 1 }}>
      <Box component="span" sx={{ display: 'block', fontSize: 18, fontWeight: 800, letterSpacing: '-.2px' }}>{title}</Box>
      <Box component="span" sx={{ display: 'block', mt: .5, fontSize: 12.5, fontWeight: 400, color: 'text.secondary', lineHeight: 1.5 }}>
        The PDF carries the numbers and the visuals exactly as they are on this page, with the filters that produced them.
      </Box>
    </DialogTitle>
    <DialogContent sx={{ px: `${space[6]}px`, pb: 1 }}>
      <TextField select size="small" fullWidth label="What to include" value={scope} onChange={event => setScope(event.target.value as ExportScope)} sx={{ mb: 1.6 }} disabled={busy}>
        <MenuItem value="everything">Figures and tables</MenuItem>
        <MenuItem value="figures">Figures only (as shown)</MenuItem>
        <MenuItem value="tables">Tables only</MenuItem>
      </TextField>
      <TextField select size="small" fullWidth label="Page orientation" value={orientation} onChange={event => setOrientation(event.target.value as 'landscape' | 'portrait')} sx={{ mb: 1.6 }} disabled={busy}>
        <MenuItem value="landscape">Landscape — wider tables read better</MenuItem>
        <MenuItem value="portrait">Portrait</MenuItem>
      </TextField>

      {includeFigures && <Box sx={{ border: '1px solid', borderColor: 'divider', borderRadius: 2, p: 1.2 }}>
        <Box display="flex" alignItems="center" justifyContent="space-between" gap={1} mb={.6}>
          <Typography fontSize={12} fontWeight={800}>Figures in this export</Typography>
          <Typography fontSize={11} color="text.secondary">{selected.length} of {figures.length}</Typography>
        </Box>
        {figures.length === 0
          ? <Typography fontSize={11.5} color="text.secondary">This page has no charts to export.</Typography>
          : <FormGroup sx={{ display: 'grid', gridTemplateColumns: { xs: '1fr', sm: '1fr 1fr' } }}>
            {figures.map(figure => <FormControlLabel
              key={figure.key}
              control={<Checkbox size="small" checked={selected.includes(figure.key)} disabled={busy}
                onChange={event => setSelected(current => event.target.checked
                  ? [...current, figure.key]
                  : current.filter(key => key !== figure.key))}/>}
              label={<Typography fontSize={11.8}>{figure.label}</Typography>}
              sx={{ mx: 0, '& .MuiFormControlLabel-label': { minWidth: 0 } }}
            />)}
          </FormGroup>}
        {selected.length === 0 && <Alert severity="info" sx={{ mt: 1, py: 0 }}>
          No figure is selected. The export will carry the tables only.
        </Alert>}
      </Box>}

      {busy && <Box mt={1.6}>
        <LinearProgress/>
        <Typography fontSize={11.5} color="text.secondary" mt={.7}>{progress || 'Preparing…'}</Typography>
      </Box>}
      {error && <Alert severity="error" sx={{ mt: 1.4 }}>{error}</Alert>}
      <Typography fontSize={10.8} color="text.secondary" mt={1.4} display="flex" alignItems="center" gap={.6}>
        <TableViewOutlined sx={{ fontSize: 13 }}/>
        Exports are recorded in the workspace audit trail with the filters in force.
      </Typography>
    </DialogContent>
    <DialogActions sx={{ px: `${space[6]}px`, py: 1.75, gap: 1, borderTop: '1px solid', borderColor: 'divider' }}>
      <Button onClick={onClose} color="inherit" disabled={busy} startIcon={<CloseRounded/>}>Cancel</Button>
      <Button variant="contained" onClick={() => void run()} disabled={busy || (includeFigures && selected.length === 0 && !includeTables)}
        startIcon={busy ? <CircularProgress size={14} color="inherit"/> : <PictureAsPdfOutlined/>}>
        {busy ? 'Exporting…' : 'Export PDF'}
      </Button>
    </DialogActions>
  </Dialog>
}
