import { useEffect, useId, useRef, useState } from 'react'
import { createPortal } from 'react-dom'
import { Alert, Box, Button, CircularProgress, Dialog, DialogActions, DialogTitle, Typography } from '@mui/material'
import { CloseRounded, PrintOutlined } from '@mui/icons-material'
import { useColorMode } from '../../context/ThemeContext'
import { radius, space } from '../../designSystem'

/**
 * Report viewer.
 *
 * Every report in this product already exists as a print sheet (the AFE cost
 * estimate, the daily sheet, the well costing sheet). Until now the only way to
 * read one was to press Print, which opens the browser's print dialog. This
 * surfaces the same markup on screen first, so a report can be checked before
 * it is submitted or printed — with a deliberate Print action on the viewer.
 *
 * The preview deliberately reuses the print stylesheet's own look, but in a
 * readable screen form: a white "paper" surface on the app canvas, scrollable,
 * with the report's page breaks kept as visible separations. It is a viewer,
 * not a second implementation of the report: if a report's print layout
 * changes, the preview changes with it.
 */
export function ReportViewDialog({ open, title, subtitle, onClose, onPrint, busy = false, printLabel = 'Print', error = '', children }: {
  open: boolean
  title: string
  subtitle?: string
  onClose: () => void
  /** Opens the browser print dialog for exactly this report. Omit to hide the button. */
  onPrint?: () => void
  busy?: boolean
  printLabel?: string
  error?: string
  children: React.ReactNode
}) {
  const titleId = useId()
  const subtitleId = useId()
  const { mode } = useColorMode()
  return <Dialog
    open={open}
    onClose={onClose}
    fullWidth
    maxWidth="xl"
    aria-labelledby={titleId}
    aria-describedby={subtitle ? subtitleId : undefined}
    // Report dialogs close with their own Close / Print buttons; clicking the
    // page behind must never throw a viewer away, and Escape is a deliberate
    // dismissal here (nothing is being edited), so it stays disabled for
    // consistency with every other pop-up in the product.
    disableEscapeKeyDown
    slotProps={{ paper: { sx: { maxHeight: '94vh', bgcolor: 'background.default' } } }}
  >
    <DialogTitle sx={{ px: 3, pt: 2.5, pb: subtitle ? 1 : 2 }}>
      <Box component="span" sx={{ display: 'block', fontSize: 19, fontWeight: 800, letterSpacing: '-.3px', lineHeight: 1.3 }}>{title}</Box>
      {subtitle && <Box component="span" id={subtitleId} sx={{ display: 'block', mt: .6, fontSize: 12.5, fontWeight: 400, color: 'text.secondary', lineHeight: 1.5 }}>{subtitle}</Box>}
    </DialogTitle>
    <Box sx={{ px: 3, pb: 2, overflow: 'auto', flex: '1 1 auto' }}>
      {error && <Alert severity="error" sx={{ mb: 2 }}>{error}</Alert>}
      {/* The report renders on a white sheet in both themes, exactly as it prints. */}
      <Box
        className="wcp-report-preview"
        data-preview-theme={mode}
        sx={{
          bgcolor: '#FFFFFF',
          color: '#16283F',
          border: '1px solid',
          borderColor: 'divider',
          borderRadius: `${radius.lg}px`,
          p: `${space[6]}px`,
          minHeight: 240,
          display: 'grid',
          placeItems: 'center',
        }}
      >
        {busy
          ? <Box display="grid" gap={1.5} sx={{ placeItems: 'center', py: 6 }}>
            <CircularProgress size={26}/>
            <Typography fontSize={12.5} color="text.secondary">Preparing the report…</Typography>
          </Box>
          : <Box sx={{ width: '100%' }}>{children}</Box>}
      </Box>
    </Box>
    <DialogActions sx={{ px: 3, py: 1.75, gap: 1, borderTop: '1px solid', borderColor: 'divider', bgcolor: 'background.paper' }}>
      <Button onClick={onClose} color="inherit" startIcon={<CloseRounded/>}>Close</Button>
      {onPrint && <Button onClick={onPrint} variant="contained" startIcon={<PrintOutlined/>} disabled={busy}>{printLabel}</Button>}
    </DialogActions>
  </Dialog>
}

/**
 * Modal-local print portal.
 *
 * Printing hides the whole application (`body > #root`) and shows the report
 * portal instead. The viewer lives *inside* the app root, so a report that is
 * open in the viewer is portalled to the document body for the duration of the
 * print — otherwise pressing Print inside the viewer would print a blank page.
 * Outside the viewer the same markup is rendered inline as the preview.
 */
export function PreviewPrintPortal({ children }: { children: React.ReactNode }) {
  const host = useRef<HTMLDivElement | null>(null)
  const [ready, setReady] = useState(false)
  useEffect(() => {
    const node = document.createElement('div')
    document.body.appendChild(node)
    host.current = node
    setReady(true)
    return () => { node.remove() }
  }, [])
  if (!ready || !host.current) return <>{children}</>
  return <>{createPortal(children, host.current)}</>
}
