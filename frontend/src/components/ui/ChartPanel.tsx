import type { ReactNode } from 'react'
import { Box, Typography } from '@mui/material'
import { SectionCard } from './SectionCard'

/**
 * Chart surface with an explicit subject line, the unit/currency in view and a
 * data fallback. A chart is an aid to a table, never the only way to read a
 * number: the caption states the basis and `empty` says what is missing.
 *
 * The panel also marks itself as an exportable figure (`data-chart-*`). The PDF
 * export walks those markers in document order and captures each rendered chart
 * exactly as it is on screen, together with its own title and caption, so an
 * exported dashboard carries the visuals rather than a list of numbers.
 */
export function ChartPanel({ title, subtitle, meta, height = 280, children, empty, emptyMessage, caption, exportable = true, figureKey }: {
  title: string
  subtitle?: string
  /** Unit, currency or time basis badge shown beside the title. */
  meta?: ReactNode
  height?: number
  children?: ReactNode
  empty?: boolean
  emptyMessage?: string
  /** Footnote under the plot: source, aggregation, exclusions. */
  caption?: ReactNode
  /** Set false for a panel that holds no chart (the export then skips it). */
  exportable?: boolean
  /** Stable key the page uses to place this figure in an exported document. */
  figureKey?: string
}) {
  const captionText = typeof caption === 'string' ? caption : ''
  return <SectionCard
    title={title}
    subtitle={subtitle}
    meta={meta}
    bodyPadding={0}
    sx={{ height: '100%' }}
    // The PDF export reads these markers; they are inert for the browser.
    dataAttributes={exportable ? {
      'data-chart-figure': '1',
      'data-chart-key': figureKey ?? title,
      'data-chart-title': title,
      'data-chart-subtitle': subtitle ?? '',
      'data-chart-caption': captionText,
      'data-chart-empty': empty ? '1' : '0',
    } : undefined}
  >
    <Box sx={{ px: 1.5, pt: 1, pb: .5 }}>
      {empty
        ? <Box sx={{ height, display: 'grid', placeItems: 'center', px: 3 }} data-chart-empty="1">
          <Typography sx={{ fontSize: 12.5, color: 'text.secondary', textAlign: 'center' }}>{emptyMessage ?? 'Nothing to chart for the current filters.'}</Typography>
        </Box>
        : <Box sx={{ height }}>{children}</Box>}
    </Box>
    {caption ? <Box sx={{ px: 2.25, pb: 1.5, pt: .5 }}><Typography sx={{ fontSize: 10.5, color: 'text.secondary', lineHeight: 1.45 }}>{caption}</Typography></Box> : null}
  </SectionCard>
}
