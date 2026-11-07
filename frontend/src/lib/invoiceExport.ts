import { exportCsv, exportPdf, exportXlsx, type ExportColumn } from './export'
import { formatAmount, formatDate, formatPrecise, subtotalDifference } from './invoiceCalculations'
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
  { header: 'Adjusted Payable', value: row => row.adjusted_verified_amount }, { header: 'Payment Terms', value: row => row.payment_term_name },
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
  { header: 'Taxes', value: row => row.taxes.map(tax => `${tax.tax_name} ${tax.direction} ${tax.rate_percent}%`).join(' | ') },
  { header: 'Payment Splits', value: row => row.payment_splits.map(split => `${split.percentage}% ${split.currency_code} ${split.amount}`).join(' | ') },
]
export async function exportIdvs(invoice: InvoiceDetail, format: 'csv' | 'xlsx' | 'pdf') {
  const safeNumber = invoice.idvs_number.replace(/[^a-z0-9_-]+/gi, '-')
  if (format === 'csv') return exportCsv(`${safeNumber}.csv`, [invoice], idvsColumns)
  if (format === 'xlsx') return exportXlsx(`${safeNumber}.xlsx`, [invoice], idvsColumns)
  const [{ jsPDF }, autoTableModule] = await Promise.all([import('jspdf'), import('jspdf-autotable')])
  const autoTable = autoTableModule.default
  const doc = new jsPDF({ orientation: 'landscape', unit: 'mm', format: 'a4' })
  const teal: [number, number, number] = [21, 81, 91]
  const ink: [number, number, number] = [27, 43, 48]
  doc.setFillColor(...teal); doc.rect(0, 0, 297, 29, 'F')
  doc.setTextColor(255); doc.setFont('helvetica', 'bold'); doc.setFontSize(17)
  doc.text('INVOICE DATA VERIFICATION SHEET', 14, 13)
  doc.setFontSize(9); doc.setFont('helvetica', 'normal')
  doc.text(`${invoice.idvs_number}  |  IDVS date ${formatDate(invoice.idvs_date)}  |  Revision ${invoice.revision}`, 14, 21)
  doc.text(INVOICE_STATUS_LABEL[invoice.display_status].toUpperCase(), 283, 17, { align: 'right' })
  doc.setTextColor(...ink)
  autoTable(doc, {
    startY: 35, theme: 'grid', styles: { fontSize: 8, cellPadding: 2, lineColor: [210, 220, 222], lineWidth: .15 },
    headStyles: { fillColor: [235, 242, 243], textColor: ink, fontStyle: 'bold' },
    head: [['Vendor', 'Invoice / dates', 'PO/SO & scope', 'Location / service']],
    body: [[
      `${invoice.vendor_name}\n${invoice.vendor_code}`,
      `${invoice.invoice_number}\nInvoice: ${formatDate(invoice.invoice_date)}\nReceived: ${formatDate(invoice.invoice_received_date)}`,
      `${invoice.order_type} ${invoice.order_number || 'Not linked'}\n${[invoice.block_code, invoice.rig_code, invoice.well_code].filter(Boolean).join(' / ') || 'Common materials'}`,
      `${invoice.location_name}\n${invoice.description_category}\n${invoice.service_description}`,
    ]],
  })
  autoTable(doc, {
    startY: (doc as typeof doc & { lastAutoTable: { finalY: number } }).lastAutoTable.finalY + 5,
    head: [['#', 'Description', 'Invoice qty', 'Invoice unit price', 'Invoice total', 'Verified qty', 'Verified unit price', 'Verified total', 'Difference']],
    body: invoice.lines.map((line, index) => [index + 1, line.description, formatPrecise(line.invoice_quantity), formatAmount(line.invoice_unit_price), formatAmount(line.invoice_total), formatPrecise(line.verified_quantity), formatAmount(line.verified_unit_price), formatAmount(line.verified_total), formatAmount(line.difference_amount)]),
    foot: [['', `SUBTOTAL (${invoice.currency_code})`, '', '', formatAmount(invoice.invoice_subtotal), '', '', formatAmount(invoice.verified_subtotal), formatAmount(subtotalDifference(invoice.invoice_subtotal, invoice.verified_subtotal))]],
    styles: { fontSize: 7.5, cellPadding: 1.8 }, headStyles: { fillColor: teal, textColor: 255 }, footStyles: { fillColor: [235, 242, 243], textColor: ink, fontStyle: 'bold' },
    columnStyles: { 0: { cellWidth: 8 }, 1: { cellWidth: 66 }, 2: { halign: 'right' }, 3: { halign: 'right' }, 4: { halign: 'right' }, 5: { halign: 'right' }, 6: { halign: 'right' }, 7: { halign: 'right' }, 8: { halign: 'right' } },
  })
  let y = (doc as typeof doc & { lastAutoTable: { finalY: number } }).lastAutoTable.finalY + 5
  autoTable(doc, {
    startY: y, margin: { left: 14, right: 157 }, head: [['Tax / adjustment', 'Rate', 'Invoice amount', 'Verified amount']],
    body: [
      ...invoice.taxes.map(tax => [`${tax.tax_name} (${tax.direction})`, `${formatPrecise(tax.rate_percent, 4)}%`, formatAmount(tax.invoice_amount), formatAmount(tax.verified_amount)]),
      ['Disallowed amount', '', '', `-${formatAmount(invoice.disallowed_amount)}`], ['Advance amount', '', '', `-${formatAmount(invoice.advance_amount)}`],
    ], styles: { fontSize: 7.5, cellPadding: 1.7 }, headStyles: { fillColor: teal },
  })
  const taxBottom = (doc as typeof doc & { lastAutoTable: { finalY: number } }).lastAutoTable.finalY
  autoTable(doc, {
    startY: y, margin: { left: 151, right: 14 }, head: [['Commercial summary', invoice.currency_code]],
    body: [['Invoice total', formatAmount(invoice.invoice_total)], ['Verified total', formatAmount(invoice.verified_total)], ['Difference', formatAmount(invoice.difference_amount)], ['Adjusted verified / payable', formatAmount(invoice.adjusted_verified_amount)], ['Payment terms', `${invoice.payment_tenure_days} days`], ['Due date', invoice.due_date]],
    styles: { fontSize: 8, cellPadding: 2 }, headStyles: { fillColor: teal }, columnStyles: { 1: { halign: 'right', fontStyle: 'bold' } },
  })
  const summaryBottom = (doc as typeof doc & { lastAutoTable: { finalY: number } }).lastAutoTable.finalY
  y = Math.max(taxBottom, summaryBottom, 132) + 5
  autoTable(doc, {
    startY: y, head: [['Payment currency', 'Percentage', 'Exchange rate', 'Split amount']],
    body: invoice.payment_splits.map(split => [split.currency_code, `${formatPrecise(split.percentage, 4)}%`, formatPrecise(split.exchange_rate), formatAmount(split.amount)]),
    styles: { fontSize: 8 }, headStyles: { fillColor: teal }, margin: { left: 14, right: 157 },
  })
  const splitBottom = (doc as typeof doc & { lastAutoTable: { finalY: number } }).lastAutoTable.finalY
  autoTable(doc, {
    startY: y, head: [['Tracking milestone', 'Date', 'Actor / remarks']],
    body: invoice.history.map(item => [item.action_label, item.action_date, `${item.actor_name}${item.remarks ? ` · ${item.remarks}` : ''}`]),
    styles: { fontSize: 7.5 }, headStyles: { fillColor: teal }, margin: { left: 151, right: 14 },
  })
  const historyBottom = (doc as typeof doc & { lastAutoTable: { finalY: number } }).lastAutoTable.finalY
  y = Math.max(splitBottom, historyBottom) + 7
  // Keep signatures with a short IDVS when they fit above the fixed footer; only paginate when necessary.
  if (y > 178) { doc.addPage(); y = 25 }
  const verifiedBy = invoice.history.find(item => item.action === 'send_to_accounts')?.actor_name ?? ''
  const approvedBy = invoice.history.find(item => item.action === 'approve_epicor')?.actor_name ?? ''
  doc.setDrawColor(160); doc.setFontSize(8)
  ;[['Prepared By', invoice.created_by], ['Checked By', ''], ['Verified By', verifiedBy], ['Approved By', approvedBy]].forEach(([label, name], index) => {
    const x = 14 + index * 70
    doc.line(x, y + 8, x + 56, y + 8); doc.setFont('helvetica', 'bold'); doc.text(label, x, y + 14)
    doc.setFont('helvetica', 'normal'); doc.text(name || ' ', x, y + 19)
  })
  doc.setFontSize(7); doc.setTextColor(100)
  doc.text(`Generated ${new Date().toLocaleString()} · ${invoice.attachment_count} supporting attachment(s) · Calculations stored at save-time precision`, 14, 202)
  doc.save(`${safeNumber}.pdf`)
}

export async function exportInvoiceDashboardPdf(data: InvoiceDashboard, selectedCurrency: string) {
  const [{ jsPDF }, autoTableModule] = await Promise.all([import('jspdf'), import('jspdf-autotable')])
  const autoTable = autoTableModule.default
  const doc = new jsPDF({ orientation: 'landscape' })
  doc.setFont('helvetica', 'bold'); doc.setFontSize(17); doc.text('Invoice Processing Dashboard', 14, 17)
  doc.setFont('helvetica', 'normal'); doc.setFontSize(9); doc.text(`As of ${data.as_of} · Generated ${new Date().toLocaleString()} · Amounts remain separated by currency`, 14, 24)
  autoTable(doc, { startY: 31, head: [['Active IDVS', 'Verification', 'EPICOR', 'Approved', 'Paid', 'Overdue', 'Attachments']], body: [[data.total_invoices, data.verification_count, data.epicor_count, data.approved_count, data.paid_count, data.overdue_count, data.attachment_count]], headStyles: { fillColor: [21, 81, 91] } })
  autoTable(doc, { startY: (doc as typeof doc & { lastAutoTable: { finalY: number } }).lastAutoTable.finalY + 7, head: [['Currency', 'IDVS', 'Invoice total', 'Verified total', 'Adjusted payable', 'Difference', 'Outstanding', 'Overdue']], body: data.currency_totals.map(row => [row.currency_code, row.invoice_count, row.invoice_total, row.verified_total, row.adjusted_verified_amount, row.difference_amount, row.outstanding_count, row.overdue_count]), headStyles: { fillColor: [21, 81, 91] } })
  const breakdownY = (doc as typeof doc & { lastAutoTable: { finalY: number } }).lastAutoTable.finalY + 7
  autoTable(doc, { startY: breakdownY, head: [['Workflow status', 'Count']], body: data.status_counts.map(row => [row.label, row.count]), headStyles: { fillColor: [21, 81, 91] }, margin: { left: 14, right: 157 } })
  autoTable(doc, { startY: breakdownY, head: [[`Vendor · ${selectedCurrency || 'none'}`, 'IDVS', 'Verified total']], body: data.vendor_rows.filter(row => row.currency_code === selectedCurrency).map(row => [row.vendor_name, row.invoice_count, formatAmount(row.verified_total)]), headStyles: { fillColor: [21, 81, 91] }, margin: { left: 151, right: 14 } })
  doc.save('invoice-processing-dashboard.pdf')
}
