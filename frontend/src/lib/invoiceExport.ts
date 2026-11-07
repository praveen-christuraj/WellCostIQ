import { exportCsv, exportPdf, exportXlsx, type ExportColumn } from './export'
import { formatAmount, formatPrecise } from './invoiceCalculations'
import { buildIdvsSheet, type IdvsSheet, type SheetCell } from './idvsSheet'
import { idvsSheet as sheetTokens } from '../designSystem'
import { INVOICE_STATUS_LABEL, type Invoice, type InvoiceDashboard, type InvoiceDetail } from './invoiceProcessing'

export const invoiceExportColumns: ExportColumn<Invoice>[] = [
  { header: 'IDVS Number', value: row => row.idvs_number }, { header: 'IDVS Date', value: row => row.idvs_date },
  { header: 'Invoice Number', value: row => row.invoice_number }, { header: 'Invoice Date', value: row => row.invoice_date },
  { header: 'Received Date', value: row => row.invoice_received_date }, { header: 'Vendor Code', value: row => row.vendor_code },
  { header: 'Vendor', value: row => row.vendor_name }, { header: 'PO/SO', value: row => row.order_number },
  { header: 'Block', value: row => row.block_code }, { header: 'Block Category', value: row => row.block_category.toUpperCase() },
  { header: 'Rig', value: row => row.rig_code }, { header: 'Well', value: row => row.well_code },
  { header: 'Location', value: row => row.location_name }, { header: 'Service Description', value: row => row.service_description },
  { header: 'Currency', value: row => row.currency_code }, { header: 'Invoice Subtotal', value: row => row.invoice_subtotal },
  { header: 'Verified Subtotal', value: row => row.verified_subtotal }, { header: 'Invoice Total', value: row => row.invoice_total },
  { header: 'Verified Total', value: row => row.verified_total }, { header: 'Difference', value: row => row.difference_amount },
  { header: 'Disallowed', value: row => row.disallowed_amount }, { header: 'Advance', value: row => row.advance_amount },
  { header: 'Adjusted Payable', value: row => row.adjusted_verified_amount },
  { header: 'Net Payable', value: row => row.net_payable_amount }, { header: 'Payment Terms', value: row => row.payment_term_name },
  { header: 'Due Date', value: row => row.due_date }, { header: 'Status', value: row => INVOICE_STATUS_LABEL[row.display_status] },
  { header: 'Submitted', value: row => row.submitted_date ?? '' }, { header: 'Sent to Accounts', value: row => row.sent_to_accounts_date ?? '' },
  { header: 'Received for EPICOR', value: row => row.epicor_received_date ?? '' }, { header: 'Approved in EPICOR', value: row => row.epicor_approved_date ?? '' },
  { header: 'Paid Date', value: row => row.paid_date ?? '' }, { header: 'Payment Reference', value: row => row.payment_reference },
  { header: 'Payment Splits', value: row => row.payment_splits.map(split => `${split.percentage}% ${split.currency_code} ${split.amount} @ ${split.exchange_rate}`).join(' | ') },
  { header: 'Attachments', value: row => String(row.attachment_count) }, { header: 'Remarks', value: row => row.remarks },
  { header: 'Created By', value: row => row.created_by }, { header: 'Updated By', value: row => row.updated_by },
]
export async function exportInvoiceRegister(rows: Invoice[], format: 'csv' | 'xlsx' | 'pdf', deleted = false) {
  const stem = deleted ? 'deleted-idvs-register' : 'idvs-register'
  if (format === 'csv') exportCsv(`${stem}.csv`, rows, invoiceExportColumns)
  else if (format === 'xlsx') await exportXlsx(`${stem}.xlsx`, rows, invoiceExportColumns)
  else await exportPdf(`${stem}.pdf`, deleted ? 'Deleted IDVS Entries' : 'IDVS / Invoice Tracking Register', rows, invoiceExportColumns)
}

const idvsColumns: ExportColumn<InvoiceDetail>[] = [
  { header: 'IDVS Number', value: row => row.idvs_number }, { header: 'Invoice Number', value: row => row.invoice_number },
  { header: 'Vendor', value: row => row.vendor_name }, { header: 'PO/SO', value: row => row.order_number },
  { header: 'Service Description', value: row => row.service_description },
  { header: 'Line Description', value: row => row.lines.map(line => line.description).join(' | ') },
  { header: 'Currency', value: row => row.currency_code }, { header: 'Invoice Total', value: row => row.invoice_total },
  { header: 'Verified Total', value: row => row.verified_total }, { header: 'Difference', value: row => row.difference_amount },
  { header: 'Adjusted Payable', value: row => row.adjusted_verified_amount },
  { header: 'Net Payable', value: row => row.net_payable_amount },
  { header: 'Taxes', value: row => row.taxes.map(tax => `${tax.tax_name} ${tax.direction} ${tax.rate_percent}%${tax.is_report_visible ? '' : ' [register only]'}`).join(' | ') },
  { header: 'Payment Splits', value: row => row.payment_splits.map(split => `${split.percentage}% ${split.currency_code} ${split.amount}`).join(' | ') },
]
export async function exportIdvs(invoice: InvoiceDetail, format: 'csv' | 'xlsx' | 'pdf') {
  const safeNumber = invoice.idvs_number.replace(/[^a-z0-9_-]+/gi, '-')
  if (format === 'csv') return exportCsv(`${safeNumber}.csv`, [invoice], idvsColumns)
  const sheet = buildIdvsSheet(invoice)
  if (format === 'xlsx') return writeIdvsXlsx(`${safeNumber}.xlsx`, sheet)
  return writeIdvsPdf(`${safeNumber}.pdf`, sheet, invoice)
}

const hexToRgb = (hex: string): [number, number, number] => [1, 3, 5].map(index => parseInt(hex.slice(index, index + 2), 16)) as [number, number, number]

/** Excel and PDF show the same cell text: amounts with two decimals, quantities without padding zeroes. */
const pdfCell = (cell: SheetCell) => ({
  content: cell.amount !== undefined ? formatAmount(cell.amount) : cell.quantity !== undefined ? formatPrecise(cell.quantity) : cell.text ?? '',
  colSpan: cell.colSpan,
  rowSpan: cell.rowSpan,
  styles: { halign: cell.align ?? (cell.amount !== undefined || cell.quantity !== undefined ? 'right' as const : 'left' as const), fontStyle: cell.bold ? 'bold' as const : 'normal' as const },
})

async function writeIdvsPdf(fileName: string, sheet: IdvsSheet, invoice: InvoiceDetail) {
  const [{ jsPDF }, autoTableModule] = await Promise.all([import('jspdf'), import('jspdf-autotable')])
  const autoTable = autoTableModule.default
  const doc = new jsPDF({ orientation: 'landscape', unit: 'mm', format: 'a4' })
  const ink = hexToRgb(sheetTokens.ink)
  const font = sheetTokens.pdfFontFamily
  const size = (referencePt: number) => referencePt * sheetTokens.pdfScale
  const { referencePt } = sheetTokens
  const margin = 12
  const pageWidth = 297 - margin * 2
  doc.setTextColor(...ink); doc.setDrawColor(...ink); doc.setFillColor(255, 255, 255)
  // Title box with a medium outline, then the IDVS number on its own line.
  doc.setLineWidth(0.5); doc.rect(margin, margin, pageWidth, 12)
  doc.setFont(font, 'bold'); doc.setFontSize(size(referencePt.title))
  doc.text(sheet.title, 148.5, margin + 8, { align: 'center' })
  doc.setFontSize(size(referencePt.heading))
  doc.text(`IDVS No: ${sheet.idvsNumber}`, margin, margin + 19)
  doc.setFont(font, 'normal')
  let y = margin + 27
  sheet.infoLeft.forEach((line, index) => doc.text(line, margin, y + index * 5.6))
  sheet.infoRight.forEach((line, index) => doc.text(line, margin + pageWidth * 0.62, y + index * 5.6))
  y += 4 * 5.6 + 3

  const totalWeight = sheet.columns.reduce((sum, column) => sum + column.weight, 0)
  const columnStyles = Object.fromEntries(sheet.columns.map((column, index) => [index, {
    cellWidth: (column.weight / totalWeight) * pageWidth,
    fontSize: column.group === 'description' ? size(referencePt.description) : size(referencePt.body),
  }]))
  autoTable(doc, {
    startY: y,
    margin: { left: margin, right: margin },
    theme: 'grid',
    styles: { font, fontSize: size(referencePt.body), textColor: ink, lineColor: ink, lineWidth: 0.2, cellPadding: 1.1, valign: 'middle', fillColor: false },
    headStyles: { font, fontStyle: 'bold', fontSize: size(referencePt.heading), halign: 'center', textColor: ink, fillColor: false },
    columnStyles,
    // The blank sign-off row is the printed signing space; every other row keeps autoTable's sizing.
    didParseCell: data => {
      if (data.section !== 'body') return
      const heightMm = sheet.body[data.row.index]?.heightMm
      if (heightMm) data.cell.styles.minCellHeight = heightMm
    },
    head: sheet.header.map(row => row.map(pdfCell)),
    body: sheet.body.map(row => row.cells.map(pdfCell)),
  })
  const finalY = (doc as typeof doc & { lastAutoTable: { finalY: number } }).lastAutoTable.finalY
  // A taller signing space must not push the footer past the printable page.
  const pageHeight = doc.internal.pageSize.getHeight()
  const footerY = Math.min(finalY + 6, pageHeight - margin / 2)
  doc.setFont(font, 'normal'); doc.setFontSize(7)
  doc.text(`Generated ${new Date().toLocaleString()} · ${invoice.attachment_count} supporting attachment(s) · Amounts shown to two decimals; calculations stored at save-time precision`, margin, footerY)
  doc.save(fileName)
}

/** Expand the model into a rectangular grid: covered cells become null, as write-excel-file requires. */
function xlsxGrid(rows: SheetCell[][], columnCount: number, styleOf: (cell: SheetCell) => Record<string, unknown>, heights: (number | undefined)[] = []) {
  const occupied = rows.map(() => new Array<boolean>(columnCount).fill(false))
  return rows.map((cells, rowIndex) => {
    const out: (Record<string, unknown> | null)[] = new Array(columnCount).fill(undefined)
    let column = 0
    for (const cell of cells) {
      while (column < columnCount && occupied[rowIndex][column]) { out[column] = null; column++ }
      if (column >= columnCount) break
      const span = cell.colSpan ?? 1
      const rowSpan = cell.rowSpan ?? 1
      out[column] = { ...styleOf(cell), ...(span > 1 ? { columnSpan: span } : {}), ...(rowSpan > 1 ? { rowSpan } : {}) }
      for (let r = rowIndex; r < Math.min(rows.length, rowIndex + rowSpan); r++) {
        for (let c = column; c < Math.min(columnCount, column + span); c++) {
          if (r === rowIndex && c === column) continue
          occupied[r][c] = true
          if (r === rowIndex) out[c] = null
        }
      }
      column += span
    }
    for (let c = 0; c < columnCount; c++) if (out[c] === undefined) out[c] = occupied[rowIndex][c] ? null : { value: '', type: String, borderStyle: 'thin' }
    if (heights[rowIndex]) (out[0] as Record<string, unknown>).height = heights[rowIndex]
    return out
  })
}

async function writeIdvsXlsx(fileName: string, sheet: IdvsSheet) {
  const { default: writeXlsxFile } = await import('write-excel-file/browser')
  const font = sheetTokens.excelFontName
  const pt = sheetTokens.referencePt
  const columnCount = sheet.columns.length
  const base = { fontFamily: font, fontSize: pt.body, alignVertical: 'center' as const, borderStyle: 'thin' as const }
  const styleOf = (cell: SheetCell): Record<string, unknown> => {
    const style = { ...base, align: cell.align ?? 'left', fontWeight: cell.bold ? 'bold' : 'normal', wrap: true }
    if (cell.amount !== undefined) return { ...style, type: Number, value: cell.amount, format: '#,##0.00;-#,##0.00', align: 'right' }
    if (cell.quantity !== undefined) return { ...style, type: Number, value: cell.quantity, format: 'General', align: 'right' }
    return { ...style, type: String, value: cell.text ?? '' }
  }
  const widthOf = (key: string) => key.endsWith('Qty') ? 10 : key.endsWith('Days') ? 12 : key.endsWith('Unit') ? 18 : key.endsWith('Total') ? 20 :
    key === 'sno' ? 7 : key === 'description' ? 90 : key === 'difference' ? 18 : 26
  const titleRow = [{ value: sheet.title, type: String, columnSpan: columnCount, fontFamily: font, fontSize: pt.title, fontWeight: 'bold' as const, align: 'center' as const, alignVertical: 'center' as const, borderStyle: 'medium' as const, height: 30 }]
  const infoRows = sheet.infoLeft.map((left, index) => {
    const row: (Record<string, unknown> | null)[] = new Array(columnCount).fill(null)
    row[0] = { type: String, value: left, columnSpan: sheet.invoiceStart, fontFamily: font, fontSize: pt.heading, fontWeight: 'bold' as const, height: 20 }
    row[sheet.verifiedStart] = { type: String, value: sheet.infoRight[index], columnSpan: columnCount - sheet.verifiedStart, fontFamily: font, fontSize: pt.heading, fontWeight: 'bold' as const }
    return row
  })
  const idvsRow = [{ type: String, value: `IDVS No: ${sheet.idvsNumber}`, columnSpan: columnCount, fontFamily: font, fontSize: pt.heading, fontWeight: 'bold' as const, height: 22 }]
  const body = sheet.body.map(row => row.cells)
  const heights = sheet.body.map(row => {
    const description = row.cells[1]?.text ?? ''
    const remarks = row.cells[columnCount - 1]?.text ?? ''
    // write-excel-file heights are points: 1 mm ≈ 2.835 pt gives the printed signing space.
    if (row.heightMm) return Math.round(row.heightMm * 2.835)
    if (row.kind !== 'line') return row.kind === 'signature' ? 22 : 20
    const lines = Math.max(1, Math.ceil(description.length / 80), Math.ceil(remarks.length / 22))
    return Math.max(20, lines * 18)
  })
  const data = [
    titleRow,
    idvsRow,
    [],
    ...infoRows,
    [],
    ...xlsxGrid(sheet.header, columnCount, styleOf),
    ...xlsxGrid(body, columnCount, styleOf, heights),
  ]
  await writeXlsxFile(data as never, {
    sheet: 'IDVS',
    columns: sheet.columns.map(column => ({ width: widthOf(column.key) })),
    showGridLines: false,
    orientation: 'landscape',
  }, { fontFamily: font, fontSize: pt.body }).toFile(fileName)
}

export async function exportInvoiceDashboardPdf(data: InvoiceDashboard, selectedCurrency: string) {
  const [{ jsPDF }, autoTableModule] = await Promise.all([import('jspdf'), import('jspdf-autotable')])
  const autoTable = autoTableModule.default
  const doc = new jsPDF({ orientation: 'landscape' })
  doc.setFont('helvetica', 'bold'); doc.setFontSize(17); doc.text('Invoice Processing Dashboard', 14, 17)
  doc.setFont('helvetica', 'normal'); doc.setFontSize(9); doc.text(`As of ${data.as_of} · Generated ${new Date().toLocaleString()} · Amounts remain separated by currency`, 14, 24)
  autoTable(doc, { startY: 31, head: [['Active IDVS', 'Verification', 'EPICOR', 'Approved', 'Paid', 'Overdue', 'Attachments']], body: [[data.total_invoices, data.verification_count, data.epicor_count, data.approved_count, data.paid_count, data.overdue_count, data.attachment_count]], headStyles: { fillColor: [21, 81, 91] } })
  autoTable(doc, { startY: (doc as typeof doc & { lastAutoTable: { finalY: number } }).lastAutoTable.finalY + 7, head: [['Currency', 'IDVS', 'Invoice total', 'Verified total', 'IDVS amount', 'Net payable', 'Difference', 'Outstanding', 'Overdue']], body: data.currency_totals.map(row => [row.currency_code, row.invoice_count, row.invoice_total, row.verified_total, row.adjusted_verified_amount, row.net_payable_amount, row.difference_amount, row.outstanding_count, row.overdue_count]), headStyles: { fillColor: [21, 81, 91] } })
  const breakdownY = (doc as typeof doc & { lastAutoTable: { finalY: number } }).lastAutoTable.finalY + 7
  autoTable(doc, { startY: breakdownY, head: [['Workflow status', 'Count']], body: data.status_counts.map(row => [row.label, row.count]), headStyles: { fillColor: [21, 81, 91] }, margin: { left: 14, right: 157 } })
  autoTable(doc, { startY: breakdownY, head: [[`Vendor · ${selectedCurrency || 'none'}`, 'IDVS', 'Verified total']], body: data.vendor_rows.filter(row => row.currency_code === selectedCurrency).map(row => [row.vendor_name, row.invoice_count, formatAmount(row.verified_total)]), headStyles: { fillColor: [21, 81, 91] }, margin: { left: 151, right: 14 } })
  doc.save('invoice-processing-dashboard.pdf')
}
