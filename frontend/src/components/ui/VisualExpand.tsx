import { createContext, useContext, useState, type ReactNode } from 'react'
import { Box, Button, Typography } from '@mui/material'
import { OpenInFullRounded } from '@mui/icons-material'
import { PanelDialog } from '../Common'

export type VisualMeta = { title: string; subtitle?: string; caption?: ReactNode }
export const VisualMetaContext = createContext<VisualMeta | null>(null)
/** The modal is not itself an exportable figure or a place to open another expand dialog. */
export const ExpandedVisualContext = createContext(false)

export function VisualExpand({ getVisual, visual, children }: {
  visual?: VisualMeta
  getVisual?: () => VisualMeta
  children: (close: () => void) => ReactNode
}) {
  const [open, setOpen] = useState(false)
  const inside = useContext(ExpandedVisualContext)
  const context = useContext(VisualMetaContext)
  const [resolved, setResolved] = useState<VisualMeta | null>(null)
  if (inside) return null
  const meta = (open ? resolved : null) ?? visual ?? context ?? { title: 'Chart' }
  const close = () => setOpen(false)
  return <>
    <Button
      size="small"
      startIcon={<OpenInFullRounded />}
      aria-haspopup="dialog"
      aria-expanded={open}
      aria-label={`Expand ${meta.title}`}
      onClick={() => {
        if (getVisual) setResolved(getVisual())
        setOpen(true)
      }}
      sx={{ '@media (pointer: coarse)': { minHeight: 44 } }}
    >Expand</Button>
    {open && <PanelDialog open title={meta.title} subtitle={meta.subtitle} onClose={close} maxWidth={false}>
      <ExpandedVisualContext.Provider value>
        <Box sx={{ minWidth: 0 }}>{children(close)}</Box>
        {meta.caption && <Typography component="div" variant="caption" color="text.secondary" mt={1.5}>{meta.caption}</Typography>}
      </ExpandedVisualContext.Provider>
    </PanelDialog>}
  </>
}
