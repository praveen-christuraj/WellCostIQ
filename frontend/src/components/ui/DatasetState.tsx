import type { ReactNode } from 'react'
import { Box, Button, CircularProgress, Typography } from '@mui/material'
import { CloudOffOutlined, FolderOpenOutlined, LockOutlined, ReportProblemOutlined } from '@mui/icons-material'

type Kind = 'loading' | 'empty' | 'error' | 'denied'

const ICON = {
  empty: FolderOpenOutlined,
  error: ReportProblemOutlined,
  denied: LockOutlined,
  loading: CloudOffOutlined,
}

/**
 * The one way a dataset says why it is not showing rows.
 *
 * `empty` means the filters or the workspace produced no records, `denied`
 * means the account may not read them and `error` means the request failed;
 * each carries the next action a reader can actually take. Loading renders a
 * quiet spinner with a sentence instead of a blank surface.
 */
export function DatasetState({ kind = 'empty', title, message, action, compact = false }: {
  kind?: Kind
  title: string
  message?: ReactNode
  action?: ReactNode
  compact?: boolean
}) {
  if (kind === 'loading') {
    return <Box role="status" aria-live="polite" sx={{ display: 'grid', placeItems: 'center', gap: 1.5, py: compact ? 4 : 8, px: 2, textAlign: 'center' }}>
      <CircularProgress size={24}/>
      <Typography fontSize={12.5} color="text.secondary">{title}</Typography>
    </Box>
  }
  const Icon = ICON[kind]
  const tone = kind === 'error' ? 'error' : kind === 'denied' ? 'warning' : 'info'
  return <Box
    role={kind === 'error' ? 'alert' : 'status'}
    sx={{ py: compact ? 3.5 : 6, px: 2, textAlign: 'center', border: '1px dashed', borderColor: 'divider', borderRadius: 2, bgcolor: kind === 'error' ? 'error.light' : 'background.default' }}
  >
    <Box sx={{
      width: 38, height: 38, mx: 'auto', mb: 1.4, borderRadius: '50%', display: 'grid', placeItems: 'center',
      bgcolor: kind === 'error' ? 'background.paper' : 'action.hover',
      color: kind === 'error' ? 'error.main' : 'primary.main',
      border: '1px solid', borderColor: kind === 'error' ? 'error.light' : 'divider',
    }}>
      <Icon sx={{ fontSize: 19 }}/>
    </Box>
    <Typography sx={{ fontSize: 14.5, fontWeight: 700, color: kind === 'error' ? `${tone}.main` : 'text.primary' }}>{title}</Typography>
    {message ? <Typography sx={{ fontSize: 12.5, color: 'text.secondary', maxWidth: 560, mx: 'auto', mt: .8, lineHeight: 1.5 }}>{message}</Typography> : null}
    {action ? <Box sx={{ mt: 2, display: 'flex', justifyContent: 'center', gap: 1, flexWrap: 'wrap' }}>{action}</Box> : null}
  </Box>
}

/** Ready-made next step for an empty register whose table has filters applied. */
export function ResetFiltersAction({ onReset }: { onReset: () => void }) {
  return <Button size="small" variant="outlined" onClick={onReset}>Reset filters</Button>
}
