import { formatDate, lineDayFactors, numeric, subtotalDifference } from './invoiceCalculations'
import { COMMON_SCOPE_LABEL, SIGNATURE_LABELS, SIGNATURE_ROLES, SIGNATURE_SPACE, type InvoiceDetail, type SignatureRole } from './invoiceProcessing'

/**
 * Single layout model for the Invoice Discrepancy Verification Sheet. The on-screen sheet, the PDF and
 * the XLSX export all render this model, so the three outputs cannot drift apart. The layout follows the
 * reference workbook RIG-11: services table with "As per Invoice" and "As per Actual / Contract" groups,
 * difference and remarks, subtotal/tax/total/split rows, and the four sign-off blocks.
 *
 * Three print rules live here so the screen, PDF and XLSX cannot disagree:
 * * only report-visible taxes appear in the subtotal/tax block and in the total — a
 *   register-only tax is stored on the IDVS but never printed;
 * * an IDVS without a Block, Rig or Well reports "Common for All Blocks";
 * * a configurable blank signing space separates the sign-off role row from its
 *   name and designation rows, so the copy can be signed by hand.
 */

export const IDVS_TITLE = 'INVOICE DISCREPANCY VERIFICATION SHEET'

export type SheetColumnGroup = 'sno' | 'description' | 'invoice' | 'verified' | 'difference' | 'remarks'
export type SheetColumn = {
  key: string
  group: SheetColumnGroup
  header: string
  align: 'left' | 'center' | 'right'
  /** Relative width; renderers scale it to their own page or sheet. */
  weight: number
}

export type SheetCell = {
  text?: string
  /** Money amount, formatted with two decimals by the renderer. */
  amount?: number
  /** Quantity or day count, shown without padding zeroes. */
  quantity?: number
  colSpan?: number
  rowSpan?: number
  align?: 'left' | 'center' | 'right'
  bold?: boolean
}

export type SheetRowKind = 'line' | 'summary' | 'total' | 'signature'
export type SheetRow = {
  kind: SheetRowKind
  cells: SheetCell[]
  /**
   * Height in millimetres of a deliberately blank row. Only the sign-off signing
   * space uses it today; renderers must size it exactly, never collapse it.
   */
  heightMm?: number
}

export type IdvsSheet = {
  title: string
  idvsNumber: string
  currency: string
  dayCount: boolean
  infoLeft: string[]
  infoRight: string[]
  columns: SheetColumn[]
  /** Index of the first "As per Invoice" column and the first "As per Actual / Contract" column. */
  invoiceStart: number
  verifiedStart: number
  /** Height in millimetres of the blank signing row between the role and the printed name. */
  signatureSpaceMm: number
  header: SheetCell[][]
  body: SheetRow[]
}

const dayColumn = (side: 'invoice' | 'verified', group: SheetColumnGroup, weight: number): SheetColumn => ({
  key: `${side}Days`, group, header: 'No. of Days', align: 'right', weight,
})

export function buildSheetColumns(currency: string, dayCount: boolean): SheetColumn[] {
  const side = (prefix: 'invoice' | 'verified', group: 'invoice' | 'verified'): SheetColumn[] => [
    { key: `${prefix}Qty`, group, header: 'Qty', align: 'right', weight: 6 },
    ...(dayCount ? [dayColumn(prefix, group, 7)] : []),
    { key: `${prefix}Unit`, group, header: `Unit Price (${currency})`, align: 'right', weight: 14 },
    { key: `${prefix}Total`, group, header: `Total (${currency})`, align: 'right', weight: 15 },
  ]
  return [
    { key: 'sno', group: 'sno', header: 'S.No.', align: 'center', weight: 7 },
    { key: 'description', group: 'description', header: 'Description', align: 'left', weight: 30 },
    ...side('invoice', 'invoice'),
    ...side('verified', 'verified'),
    { key: 'difference', group: 'difference', header: 'Difference', align: 'right', weight: 15 },
    { key: 'remarks', group: 'remarks', header: 'Remarks', align: 'left', weight: 10 },
  ]
}

/** Three header rows, as merged in the reference: group titles, sub-headers, then S.No. and Description. */
function headerRows(columns: SheetColumn[], invoiceStart: number, verifiedStart: number, differenceIndex: number): SheetCell[][] {
  return [
    [
      { text: 'Services', colSpan: 2, rowSpan: 2, align: 'center', bold: true },
      { text: 'As per Invoice', colSpan: verifiedStart - invoiceStart, align: 'center', bold: true },
      { text: 'As per Actual / Contract', colSpan: differenceIndex - verifiedStart, align: 'center', bold: true },
      { text: 'Difference', rowSpan: 3, align: 'center', bold: true },
      { text: 'Remarks', rowSpan: 3, align: 'center', bold: true },
    ],
    columns.slice(invoiceStart, differenceIndex).map(column => ({ text: column.header, rowSpan: 2, align: 'center' as const, bold: true })),
    [
      { text: 'S.No.', align: 'center', bold: true },
      { text: 'Description', align: 'center', bold: true },
    ],
  ]
}

const blankCells = (count: number): SheetCell[] => Array.from({ length: Math.max(0, count) }, () => ({ text: '' }))

export function buildIdvsSheet(invoice: InvoiceDetail): IdvsSheet {
  const currency = invoice.currency_code
  const dayCount = invoice.day_count_enabled
  const columns = buildSheetColumns(currency, dayCount)
  const invoiceStart = columns.findIndex(column => column.group === 'invoice')
  const verifiedStart = columns.findIndex(column => column.group === 'verified')
  const differenceIndex = columns.findIndex(column => column.group === 'difference')
  const invoiceTotalIndex = columns.findIndex(column => column.key === 'invoiceTotal')
  const verifiedTotalIndex = columns.findIndex(column => column.key === 'verifiedTotal')
  const invoiceSideCount = verifiedStart - invoiceStart
  const verifiedSideCount = differenceIndex - verifiedStart

  const lines: SheetRow[] = invoice.lines.map((line, index) => {
    const factors = lineDayFactors(line, dayCount)
    const invoiceQty = numeric(line.invoice_quantity)
    const verifiedQty = numeric(line.verified_quantity)
    const invoiceUnit = numeric(line.invoice_unit_price)
    const verifiedUnit = numeric(line.verified_unit_price)
    const invoiceTotal = line.invoice_total !== undefined ? numeric(line.invoice_total) : invoiceQty * factors.invoice * invoiceUnit
    const verifiedTotal = line.verified_total !== undefined ? numeric(line.verified_total) : verifiedQty * factors.verified * verifiedUnit
    const values: Record<string, SheetCell> = {
      sno: { text: String(index + 1), align: 'center' },
      description: { text: line.description, align: 'left' },
      invoiceQty: { quantity: invoiceQty },
      invoiceDays: { quantity: factors.invoice },
      invoiceUnit: { amount: invoiceUnit },
      invoiceTotal: { amount: invoiceTotal },
      verifiedQty: { quantity: verifiedQty },
      verifiedDays: { quantity: factors.verified },
      verifiedUnit: { amount: verifiedUnit },
      verifiedTotal: { amount: verifiedTotal },
      difference: { amount: invoiceTotal - verifiedTotal },
      remarks: { text: line.remarks, align: 'left' },
    }
    return { kind: 'line', cells: columns.map(column => ({ align: column.align, ...values[column.key] })) }
  })

  // A summary row spans the description side up to the invoice total, then carries the totals.
  const summaryRow = (kind: SheetRowKind, label: string, invoice: number | null, verified: number | null, difference: number | null, bold = false): SheetRow => {
    const cells: SheetCell[] = [{ text: label, colSpan: invoiceTotalIndex, align: 'left', bold }]
    cells.push(invoice === null ? { text: '' } : { amount: invoice, bold })
    cells.push(...blankCells(verifiedTotalIndex - invoiceTotalIndex - 1))
    cells.push(verified === null ? { text: '' } : { amount: verified, bold })
    cells.push(difference === null ? { text: '' } : { amount: difference, bold })
    cells.push({ text: '' })
    return { kind, cells }
  }

  const summary: SheetRow[] = [
    summaryRow('summary', `Sub Total - Services (${currency})`, numeric(invoice.invoice_subtotal), numeric(invoice.verified_subtotal), subtotalDifference(invoice.invoice_subtotal, invoice.verified_subtotal)),
    // Register-only taxes are deliberately absent: they change the register's Net payable amount, not this sheet.
    ...invoice.taxes.filter(tax => tax.is_report_visible).map(tax => {
      const sign = tax.direction === 'addition' ? 1 : -1
      const invoiceAmount = sign * numeric(tax.invoice_amount)
      const verifiedAmount = sign * numeric(tax.verified_amount)
      const rate = numeric(tax.rate_percent).toLocaleString(undefined, { maximumFractionDigits: 4 })
      return summaryRow('summary', `${tax.tax_name} @ ${rate}%${tax.direction === 'deduction' ? ' (deduction)' : ''}`, invoiceAmount, verifiedAmount, invoiceAmount - verifiedAmount)
    }),
    summaryRow('total', `Total (${currency})`, numeric(invoice.invoice_total), numeric(invoice.verified_total), numeric(invoice.difference_amount), true),
    ...(numeric(invoice.disallowed_amount) ? [summaryRow('summary', 'Less: Disallowed amount', null, -numeric(invoice.disallowed_amount), null)] : []),
    ...(numeric(invoice.advance_amount) ? [summaryRow('summary', 'Less: Advance amount', null, -numeric(invoice.advance_amount), null)] : []),
    ...invoice.payment_splits.map(split => {
      const rate = numeric(split.exchange_rate)
      const share = numeric(split.percentage) / 100
      const label = `${numeric(split.percentage).toLocaleString(undefined, { maximumFractionDigits: 4 })}% ${split.currency_code}${split.currency_code !== currency ? ` (FX ${rate.toLocaleString(undefined, { maximumFractionDigits: 10 })})` : ''}`
      const invoiceAmount = numeric(invoice.invoice_total) * share * rate
      const verifiedAmount = numeric(split.amount)
      return summaryRow('summary', label, invoiceAmount, verifiedAmount, invoiceAmount - verifiedAmount)
    }),
  ]

  // Sign-off blocks span the same groups as the reference: Prepared (S.No.+Description), Checked (invoice),
  // Verified (actual/contract), Approved (difference+remarks). Saved selections win; legacy IDVS fall back.
  const hasSaved = invoice.signatures.length > 0
  const actorFor = (action: string) => invoice.history.find(item => item.action === action)?.actor_name ?? ''
  const fallbackName: Record<SignatureRole, string> = {
    prepared: invoice.created_by, checked: '', verified: actorFor('send_to_accounts'), approved: actorFor('approve_epicor'),
  }
  const spans: Record<SignatureRole, { start: number; span: number }> = {
    prepared: { start: 0, span: invoiceStart },
    checked: { start: invoiceStart, span: invoiceSideCount },
    verified: { start: verifiedStart, span: verifiedSideCount },
    approved: { start: differenceIndex, span: columns.length - differenceIndex },
  }
  const signatureBlocks = SIGNATURE_ROLES.map(role => {
    const saved = invoice.signatures.find(item => item.role === role)
    return {
      role,
      label: SIGNATURE_LABELS[role],
      name: hasSaved ? saved?.name ?? '' : fallbackName[role],
      designation: hasSaved ? saved?.designation ?? '' : '',
      ...spans[role],
    }
  })
  const signatureRow = (key: 'label' | 'name' | 'designation'): SheetRow => ({
    kind: 'signature',
    cells: signatureBlocks.map(block => ({
      text: block[key], colSpan: block.span, align: 'center' as const, bold: key === 'label' || key === 'name',
    })),
  })
  // The blank row between "Prepared By" and the printed name is where the copy is signed.
  const signatureSpace = Math.min(SIGNATURE_SPACE.max, Math.max(SIGNATURE_SPACE.min, Math.round(invoice.signature_space_mm ?? SIGNATURE_SPACE.default)))
  const signingSpaceRow: SheetRow = {
    kind: 'signature',
    heightMm: signatureSpace,
    cells: signatureBlocks.map(block => ({ text: '', colSpan: block.span, align: 'center' as const })),
  }
  const signature: SheetRow[] = [
    signatureRow('label'),
    ...(signatureSpace > 0 ? [signingSpaceRow] : []),
    signatureRow('name'),
    signatureRow('designation'),
  ]

  return {
    title: IDVS_TITLE,
    idvsNumber: invoice.idvs_number,
    currency,
    dayCount,
    infoLeft: [
      `Vendor Name: ${invoice.vendor_name}`,
      `Invoice No: ${invoice.invoice_number}`,
      `Invoice Received Date: ${formatDate(invoice.invoice_received_date)}`,
      `Invoice Date: ${formatDate(invoice.invoice_date)}`,
      `IDVS Date: ${formatDate(invoice.idvs_date)}`,
    ],
    infoRight: [
      `Field: ${invoice.field_name || '—'}`,
      `Block: ${invoice.block_code || COMMON_SCOPE_LABEL}`,
      `Rig: ${invoice.rig_code || COMMON_SCOPE_LABEL}`,
      `Well: ${invoice.well_code || COMMON_SCOPE_LABEL}`,
      `Section: ${invoice.phase || '—'}`,
    ],
    columns,
    invoiceStart,
    verifiedStart,
    signatureSpaceMm: signatureSpace,
    header: headerRows(columns, invoiceStart, verifiedStart, differenceIndex),
    body: [...lines, ...summary, ...signature],
  }
}
