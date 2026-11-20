import { Button, Stack, TextField, Typography } from '@mui/material'
import type { DepthWindow } from '../../lib/wellPath'

export type RangeText = { from: string; to: string }
export const parseNumber = (text: string) => text.trim() === '' || !Number.isFinite(Number(text)) ? null : Number(text)
export const formatRange = (window: DepthWindow): RangeText => ({ from: String(window.from ?? ''), to: String(window.to ?? '') })
export const parseRange = (range: RangeText): DepthWindow => ({ from: parseNumber(range.from), to: parseNumber(range.to) })
export function validRange(range: DepthWindow, negative = false) {
  const { from, to } = range
  return (negative || (from ?? 0) >= 0 && (to ?? 0) >= 0) && (from === null || to === null || from < to)
}

export function VisualDepthControls({ range, onChange, axis = 'MD', reset }: {
  range: RangeText; onChange: (range: RangeText) => void; axis?: 'MD' | 'TVD'; reset?: () => void
}) {
  const invalid = !validRange(parseRange(range), axis === 'TVD')
  return <Stack direction="row" gap={1} alignItems="center" flexWrap="wrap" useFlexGap>
    {(['from', 'to'] as const).map(key => <TextField key={key} label={`${key === 'from' ? 'From' : 'To'} (m ${axis})`}
      type="number" size="small" value={range[key]} error={invalid}
      slotProps={{ inputLabel: { shrink: true }, htmlInput: { step: 'any' } }}
      onChange={event => onChange({ ...range, [key]: event.target.value })} />)}
    {reset && <Button onClick={reset}>Reset view</Button>}
    {invalid && <Typography color="error.main" variant="caption" role="alert">Enter an ordered {axis} range.</Typography>}
  </Stack>
}
