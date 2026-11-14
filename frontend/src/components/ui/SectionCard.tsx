import type { ReactNode } from 'react'
import { Box, Paper, Typography } from '@mui/material'

/**
 * A titled work surface. One card = one subject. The heading owns the title and
 * the actions that act on that subject; the body owns the table, chart or form.
 * Kept deliberately plain: a hairline border, a header rule and generous padding.
 */
export function SectionCard({ title, subtitle, action, meta, children, footer, bodyPadding = 2, sx, dataAttributes }: {
  title?: ReactNode
  subtitle?: ReactNode
  action?: ReactNode
  meta?: ReactNode
  children: ReactNode
  footer?: ReactNode
  /** Padding around the body. Pass 0 when the body is a table that owns its own frame. */
  bodyPadding?: number | string
  sx?: object
  /**
   * Inert `data-*` markers. The PDF export uses them to find an exportable
   * figure and to read its own title and caption; nothing in the UI reads them.
   */
  dataAttributes?: Record<string, string>
}) {
  const hasHead = Boolean(title || subtitle || action || meta)
  return <Paper variant="outlined" {...dataAttributes} sx={{ borderColor: 'divider', borderRadius: 2.5, overflow: 'hidden', bgcolor: 'background.paper', ...sx }}>
    {hasHead && <Box className="panel-head" sx={{ px: 2.25, pt: 1.9, pb: subtitle ? 1.4 : 1.75, borderBottom: '1px solid', borderColor: 'divider', alignItems: subtitle ? 'flex-start' : 'center' }}>
      <Box sx={{ minWidth: 0 }}>
        {title ? <Typography className="panel-title">{title}</Typography> : null}
        {subtitle ? <Typography className="panel-sub" sx={{ maxWidth: 720 }}>{subtitle}</Typography> : null}
      </Box>
      <Box display="flex" alignItems="center" gap={1} flexWrap="wrap" sx={{ flex: '0 0 auto' }}>
        {meta}
        {action}
      </Box>
    </Box>}
    <Box sx={{ p: bodyPadding }}>{children}</Box>
    {footer ? <Box sx={{ px: 2.25, py: 1.4, borderTop: '1px solid', borderColor: 'divider', bgcolor: 'background.default' }}>{footer}</Box> : null}
  </Paper>
}
