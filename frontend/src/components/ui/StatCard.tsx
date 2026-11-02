import type { ReactNode } from 'react'
import { Box, Paper, Typography } from '@mui/material'

export type StatTone = 'default' | 'positive' | 'warning' | 'error' | 'info'

const TONE_COLOUR: Record<StatTone, string> = {
  default: 'text.primary',
  positive: 'success.main',
  warning: 'warning.main',
  error: 'error.main',
  info: 'primary.main',
}

/**
 * A single measured figure. Used for KPI strips and module summaries.
 *
 * The value is the loudest element, the label says what it is and the hint says
 * how to read it (source, denominator, comparison). Never use a stat card for a
 * figure whose provenance the reader cannot recover from the hint or a tooltip.
 */
export function StatCard({ label, value, hint, icon, tone = 'default', onClick, title, badge }: {
  label: string
  value: ReactNode
  hint?: ReactNode
  icon?: ReactNode
  tone?: StatTone
  onClick?: () => void
  title?: string
  badge?: ReactNode
}) {
  return <Paper
    variant="outlined"
    className="stat-card"
    onClick={onClick}
    role={onClick ? 'button' : undefined}
    tabIndex={onClick ? 0 : undefined}
    onKeyDown={onClick ? event => { if (event.key === 'Enter' || event.key === ' ') { event.preventDefault(); onClick() } } : undefined}
    title={title}
    sx={{ minWidth: 0, cursor: onClick ? 'pointer' : 'default', '&:focus-visible': { outline: '2px solid', outlineColor: 'primary.main', outlineOffset: 2 } }}
  >
    <Box display="flex" alignItems="flex-start" justifyContent="space-between" gap={1}>
      <Typography className="stat-label" sx={{ color: 'text.secondary', fontSize: 10.5, fontWeight: 700, letterSpacing: '.08em', textTransform: 'uppercase', lineHeight: 1.35 }}>
        {label}
      </Typography>
      {icon ? <Box className="stat-icon" aria-hidden="true">{icon}</Box> : null}
    </Box>
    <Typography className="stat-value" sx={{ color: TONE_COLOUR[tone], overflowWrap: 'anywhere' }}>{value}</Typography>
    {hint ? <Typography className="stat-hint">{hint}</Typography> : null}
    {badge ? <Box sx={{ mt: 1 }}>{badge}</Box> : null}
  </Paper>
}
