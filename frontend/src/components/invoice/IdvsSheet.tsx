import { useMemo, type CSSProperties } from 'react'
import { idvsSheet } from '../../designSystem'
import { buildIdvsSheet, type SheetCell, type SheetRow } from '../../lib/idvsSheet'
import { formatAmount, formatPrecise } from '../../lib/invoiceCalculations'
import type { InvoiceDetail } from '../../lib/invoiceProcessing'

/** On-screen rendering of the shared IDVS model: the same black-on-white sheet that the PDF prints. */
const pt = (referencePt: number) => `${referencePt * idvsSheet.pdfScale}pt`
const rule = `1px solid ${idvsSheet.ink}`

const cellText = (cell: SheetCell) => cell.amount !== undefined ? formatAmount(cell.amount) : cell.quantity !== undefined ? formatPrecise(cell.quantity) : cell.text ?? ''
/** The blank signing row keeps the same millimetre height as the PDF and XLSX outputs. */
const signingSpace = (row: SheetRow) => row.heightMm ? { height: `${(row.heightMm * idvsSheet.pdfScale).toFixed(2)}mm`, lineHeight: 0 } : {}

export function IdvsSheet({ invoice }: { invoice: InvoiceDetail }) {
  const sheet = useMemo(() => buildIdvsSheet(invoice), [invoice])
  const cellStyle = (cell: SheetCell, columnIndex: number, row: SheetRow | null): CSSProperties => {
    const numeric = cell.amount !== undefined || cell.quantity !== undefined
    const description = row?.kind === 'line' && sheet.columns[columnIndex]?.group === 'description'
    return {
      border: rule, padding: '4px 6px', verticalAlign: 'middle', whiteSpace: 'pre-wrap',
      textAlign: cell.align ?? (numeric ? 'right' : 'left'), fontWeight: cell.bold ? 700 : 400,
      fontSize: pt(description ? idvsSheet.referencePt.description : idvsSheet.referencePt.body),
      ...(row ? signingSpace(row) : {}),
    }
  }
  const headerCellStyle = (): CSSProperties => ({ border: rule, padding: '4px 6px', textAlign: 'center', fontWeight: 700, verticalAlign: 'middle', fontSize: pt(idvsSheet.referencePt.heading) })
  let bodyColumn = 0
  return (
    <div style={{ overflowX: 'auto' }}>
      <div style={{ background: idvsSheet.paper, color: idvsSheet.ink, fontFamily: idvsSheet.fontFamily, padding: 24, minWidth: 900 }}>
        <div style={{ border: `2px solid ${idvsSheet.ink}`, padding: '10px 0', textAlign: 'center', fontWeight: 700, fontSize: pt(idvsSheet.referencePt.title) }}>
          {sheet.title}
        </div>
        <div style={{ fontWeight: 700, fontSize: pt(idvsSheet.referencePt.heading), margin: '12px 0 8px' }}>IDVS No: {sheet.idvsNumber}</div>
        <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 4, fontWeight: 700, fontSize: pt(idvsSheet.referencePt.heading), marginBottom: 12 }}>
          <div>{sheet.infoLeft.map(line => <div key={line}>{line}</div>)}</div>
          <div>{sheet.infoRight.map(line => <div key={line}>{line}</div>)}</div>
        </div>
        <table style={{ width: '100%', borderCollapse: 'collapse', tableLayout: 'auto' }}>
          <thead>
            {sheet.header.map((row, rowIndex) => (
              <tr key={`head-${rowIndex}`}>
                {row.map((cell, index) => (
                  <th key={`head-${rowIndex}-${index}`} colSpan={cell.colSpan} rowSpan={cell.rowSpan} style={headerCellStyle()}>{cellText(cell)}</th>
                ))}
              </tr>
            ))}
          </thead>
          <tbody>
            {sheet.body.map((row, rowIndex) => {
              bodyColumn = 0
              return (
                <tr key={`body-${rowIndex}`}>
                  {row.cells.map((cell, index) => {
                    const columnIndex = bodyColumn
                    bodyColumn += cell.colSpan ?? 1
                    return (
                      <td key={`body-${rowIndex}-${index}`} colSpan={cell.colSpan} rowSpan={cell.rowSpan} style={cellStyle(cell, columnIndex, row)}>
                        {cellText(cell)}
                      </td>
                    )
                  })}
                </tr>
              )
            })}
          </tbody>
        </table>
      </div>
    </div>
  )
}
