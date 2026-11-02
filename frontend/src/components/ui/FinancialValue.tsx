import { Box, Typography } from '@mui/material'

/**
 * Money rendered with a stable reading order: currency code, then a tabular
 * figure with fixed decimals, then a minus sign drawn as a true minus for
 * negatives. Alignment is right by default because every financial column in
 * the product is right-aligned.
 *
 * Values stay strings until display so precision is never rounded by a float
 * conversion; an empty value renders an em dash, never a fake zero.
 */
export function moneyText(value: string | number | null | undefined, currency = '', options: { digits?: number } = {}): string {
  if (value === null || value === undefined || value === '') return '—'
  const amount = Number(value)
  if (!Number.isFinite(amount)) return '—'
  const digits = options.digits ?? 2
  const formatted = Math.abs(amount).toLocaleString(undefined, { minimumFractionDigits: digits, maximumFractionDigits: digits })
  return `${amount < 0 ? '−' : ''}${currency ? `${currency} ` : ''}${formatted}`
}

export function FinancialValue({ value, currency = '', digits = 2, size = 13, align = 'right', strong = false, mutedZero = false, title }: {
  value: string | number | null | undefined
  currency?: string
  digits?: number
  size?: number
  align?: 'left' | 'right'
  strong?: boolean
  /** Render an exact zero quietly so it does not compete with real amounts. */
  mutedZero?: boolean
  title?: string
}) {
  const text = moneyText(value, currency, { digits })
  const amount = Number(value)
  const negative = Number.isFinite(amount) && amount < 0
  const zero = Number.isFinite(amount) && amount === 0
  return <Typography
    component="span"
    className="tnum"
    title={title}
    sx={{
      display: 'block', fontSize: size, textAlign: align, fontWeight: strong ? 700 : 500,
      fontVariantNumeric: 'tabular-nums', whiteSpace: 'nowrap',
      color: negative ? 'error.main' : zero && mutedZero ? 'text.secondary' : 'text.primary',
    }}
  >{text}</Typography>
}

/** A labelled figure inside a detail band or summary row. */
export function LabelValue({ label, value, hint }: { label: string; value: React.ReactNode; hint?: string }) {
  return <Box sx={{ minWidth: 0 }}>
    <Typography sx={{ fontSize: 9.5, fontWeight: 700, letterSpacing: '.09em', textTransform: 'uppercase', color: 'text.secondary' }}>{label}</Typography>
    <Typography sx={{ fontSize: 12.5, fontWeight: 650, color: 'text.primary', mt: .25 }} className="tnum">{value}</Typography>
    {hint ? <Typography sx={{ fontSize: 10.5, color: 'text.secondary' }}>{hint}</Typography> : null}
  </Box>
}
