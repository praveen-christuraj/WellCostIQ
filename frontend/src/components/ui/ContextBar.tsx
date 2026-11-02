import type { ReactNode } from 'react'
import { Box, Paper, Typography } from '@mui/material'

export type ContextItem = { label: string; value: ReactNode; title?: string }

/**
 * The record band: what this screen is working on, in one line.
 *
 * Used by long editors (AFE estimate, daily sheet) so the well, rig, scope,
 * currency and record identity never scroll out of the reader's understanding.
 * Values come from the loaded record — never from a guess or a stale filter.
 */
export function ContextBar({ items, status, actions, label = 'Record context' }: {
  items: ContextItem[]
  status?: ReactNode
  actions?: ReactNode
  label?: string
}) {
  return <Paper
    component="section"
    aria-label={label}
    variant="outlined"
    sx={{ borderColor: 'divider', borderRadius: 2.5, bgcolor: 'background.paper', px: 2.25, py: 1.4, display: 'flex', alignItems: 'center', gap: 2, flexWrap: 'wrap' }}
  >
    <Box sx={{ display: 'flex', alignItems: 'stretch', gap: 0, flexWrap: 'wrap', rowGap: 1.2, minWidth: 0, flex: 1 }}>
      {items.map((item, index) => <Box key={`${item.label}-${index}`} sx={{ display: 'flex', alignItems: 'center' }}>
        {index > 0 && <Box sx={{ width: '1px', alignSelf: 'stretch', bgcolor: 'divider', mx: { xs: 1.5, sm: 2 } }}/>}
        <Box sx={{ minWidth: 0 }}>
          <Typography sx={{ fontSize: 9, fontWeight: 700, letterSpacing: '.1em', textTransform: 'uppercase', color: 'text.secondary', lineHeight: 1.3 }}>{item.label}</Typography>
          <Box title={item.title} sx={{ fontSize: 12.5, fontWeight: 650, color: 'text.primary', mt: .2, whiteSpace: 'nowrap', overflow: 'hidden', textOverflow: 'ellipsis', maxWidth: 260 }}>{item.value}</Box>
        </Box>
      </Box>)}
    </Box>
    {(status || actions) ? <Box sx={{ display: 'flex', alignItems: 'center', gap: 1, flexWrap: 'wrap', justifyContent: 'flex-end' }}>
      {status}
      {actions}
    </Box> : null}
  </Paper>
}
