import type { ExchangeRate, InvoiceLine, InvoicePaymentSplit, InvoiceTax } from './invoiceProcessing'

export const numeric = (value: string | number | null | undefined): number => {
  const parsed = Number(value ?? 0)
  return Number.isFinite(parsed) ? parsed : 0
}
export const multiply = (quantity: string, unitPrice: string): number => numeric(quantity) * numeric(unitPrice)
/**
 * Day factors mirror the server: 1 whenever the IDVS day count is off; otherwise a blank
 * invoice day count is 1 and a blank verified day count follows the invoice side.
 */
export function lineDayFactors(line: { invoice_days?: string | null; verified_days?: string | null }, dayCountEnabled: boolean): { invoice: number; verified: number } {
  if (!dayCountEnabled) return { invoice: 1, verified: 1 }
  const blank = (value: string | null | undefined) => value === undefined || value === null || value === ''
  const invoice = blank(line.invoice_days) ? 1 : numeric(line.invoice_days)
  const verified = blank(line.verified_days) ? invoice : numeric(line.verified_days)
  return { invoice, verified }
}
export function addDays(isoDate: string, days: number): string {
  if (!isoDate || !Number.isInteger(days) || days < 0) return ''
  const parsed = new Date(`${isoDate}T00:00:00.000Z`)
  if (Number.isNaN(parsed.getTime())) return ''
  parsed.setUTCDate(parsed.getUTCDate() + days)
  return parsed.toISOString().slice(0, 10)
}
export function resolveExchangeRate(currency: string, invoiceCurrency: string, configured: ExchangeRate[]): number | null {
  if (currency === invoiceCurrency) return 1
  const direct = configured.find(item => item.is_active && item.base_currency === invoiceCurrency && item.quote_currency === currency)
  if (direct) return numeric(direct.rate)
  const inverse = configured.find(item => item.is_active && item.base_currency === currency && item.quote_currency === invoiceCurrency)
  return inverse ? 1 / numeric(inverse.rate) : null
}
export type DraftTotals = {
  invoiceSubtotal: number; verifiedSubtotal: number; invoiceTaxTotal: number; verifiedTaxTotal: number
  invoiceTotal: number; verifiedTotal: number; adjustedVerifiedAmount: number; differenceAmount: number
  splitAmounts: number[]; splitPercentage: number
}
export function calculateDraft(
  lines: Pick<InvoiceLine, 'invoice_quantity' | 'invoice_days' | 'invoice_unit_price' | 'verified_quantity' | 'verified_days' | 'verified_unit_price'>[],
  taxes: Pick<InvoiceTax, 'rate_percent' | 'direction'>[],
  disallowedAmount: string,
  advanceAmount: string,
  splits: Pick<InvoicePaymentSplit, 'percentage' | 'exchange_rate'>[],
  dayCountEnabled = false,
): DraftTotals {
  const invoiceSubtotal = lines.reduce((sum, line) => sum + numeric(line.invoice_quantity) * lineDayFactors(line, dayCountEnabled).invoice * numeric(line.invoice_unit_price), 0)
  const verifiedSubtotal = lines.reduce((sum, line) => sum + numeric(line.verified_quantity) * lineDayFactors(line, dayCountEnabled).verified * numeric(line.verified_unit_price), 0)
  let invoiceTaxTotal = 0
  let verifiedTaxTotal = 0
  for (const tax of taxes) {
    const sign = tax.direction === 'addition' ? 1 : -1
    invoiceTaxTotal += sign * invoiceSubtotal * numeric(tax.rate_percent) / 100
    verifiedTaxTotal += sign * verifiedSubtotal * numeric(tax.rate_percent) / 100
  }
  const invoiceTotal = invoiceSubtotal + invoiceTaxTotal
  const verifiedTotal = verifiedSubtotal + verifiedTaxTotal
  const adjustedVerifiedAmount = verifiedTotal - numeric(disallowedAmount) - numeric(advanceAmount)
  return {
    invoiceSubtotal, verifiedSubtotal, invoiceTaxTotal, verifiedTaxTotal, invoiceTotal, verifiedTotal,
    adjustedVerifiedAmount, differenceAmount: invoiceTotal - verifiedTotal,
    splitAmounts: splits.map(split => adjustedVerifiedAmount * numeric(split.percentage) / 100 * numeric(split.exchange_rate)),
    splitPercentage: splits.reduce((sum, split) => sum + numeric(split.percentage), 0),
  }
}
/** Worksheet subtotal variance excludes taxes; the commercial summary separately shows the after-tax variance. */
export const subtotalDifference = (invoiceSubtotal: string, verifiedSubtotal: string): number => numeric(invoiceSubtotal) - numeric(verifiedSubtotal)
export const formatAmount = (value: string | number | null | undefined, maximumFractionDigits = 2) => numeric(value).toLocaleString(undefined, { minimumFractionDigits: 2, maximumFractionDigits })
/** Display stored decimal precision without padding quantities, rates and FX with ten zeroes. */
export const formatPrecise = (value: string | number | null | undefined, maximumFractionDigits = 10) => numeric(value).toLocaleString(undefined, { maximumFractionDigits })
export const formatDate = (value: string | null | undefined) => value ? new Date(`${value}T00:00:00`).toLocaleDateString(undefined, { day: '2-digit', month: 'short', year: 'numeric' }) : '—'
