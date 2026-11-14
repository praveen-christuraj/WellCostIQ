/**
 * Matrix workbook writer.
 *
 * The usage reports (mud chemicals, drill bits, tangibles, service-wise and
 * vendor-wise cost) are *matrices*: items down the rows, wells across the
 * columns, hole sections nested inside each well, and totals at every level. A
 * flat CSV of the detail table loses that structure, which is exactly what makes
 * these reports worth printing.
 *
 * This writer reproduces the on-screen matrix in Excel:
 *  - the title, the period and the currency on their own rows;
 *  - two header bands — wells on the first, their hole sections on the second;
 *  - `QTY` and `COST` sub-columns under each section where the report measures
 *    both, their own sub-header row;
 *  - a `well total` band and a `grand total` column;
 *  - merged cells, frozen panes and real numbers (never text) so the reader can
 *    sum, sort and chart the workbook.
 *
 * The workbook is *data*, not a rendering: quantities and amounts are written as
 * numbers with formats, so a reader can keep working in it. Text that a
 * spreadsheet could read as a formula is neutralised by `spreadsheetText`.
 */
import { spreadsheetText } from './export'

type Cell = {
  value?: string | number | null
  type?: StringConstructor | NumberConstructor
  format?: string
  columnSpan?: number
  rowSpan?: number
  fontWeight?: 'bold'
  backgroundColor?: string
  textColor?: string
  align?: 'left' | 'center' | 'right'
  alignVertical?: 'top' | 'center' | 'bottom'
  wrap?: boolean
  borderStyle?: 'thin' | 'medium' | 'hair'
  borderColor?: string
  height?: number
  indent?: number
}

const INK = '#16283F'
const PETROL = '#15515B'
const WHITE = '#FFFFFF'
const BAND = '#EDF3F4'
const HAIRLINE = '#D6DEE2'

const numeric = (value: string | number | null | undefined, format = '#,##0.00;-#,##0.00'): Cell => ({
  value: value === null || value === undefined || value === '' ? null : Number(value),
  type: Number,
  format,
  align: 'right',
  borderStyle: 'thin',
  borderColor: HAIRLINE,
})

const text = (value: string, options: Partial<Cell> = {}): Cell => ({
  value: spreadsheetText(String(value ?? '')),
  type: String,
  borderStyle: 'thin',
  borderColor: HAIRLINE,
  ...options,
})

const header = (value: string, options: Partial<Cell> = {}): Cell => ({
  value: spreadsheetText(value),
  type: String,
  fontWeight: 'bold',
  backgroundColor: PETROL,
  textColor: WHITE,
  align: 'center',
  alignVertical: 'center',
  wrap: true,
  borderStyle: 'thin',
  borderColor: WHITE,
  ...options,
})

/**
 * Lay spans out across a fixed column count.
 *
 * The writer requires every cell hidden behind a `columnSpan` or `rowSpan` to be
 * present and `null`, otherwise a merged header silently overwrites its
 * neighbour. Building each row through this helper means a band can be written
 * as the spans a reader sees, without hand-counting the nulls.
 */
function layOutRows(rows: (Cell | null)[][], totalColumns: number): Cell[][] {
  const occupied = rows.map(() => new Array<boolean>(totalColumns).fill(false))
  return rows.map((cells, rowIndex) => {
    const out: (Cell | null)[] = new Array(totalColumns).fill(undefined) as (Cell | null)[]
    let column = 0
    for (const cell of cells) {
      if (!cell) continue
      while (column < totalColumns && occupied[rowIndex][column]) column += 1
      if (column >= totalColumns) break
      const span = Math.max(1, cell.columnSpan ?? 1)
      const rowSpan = Math.max(1, cell.rowSpan ?? 1)
      out[column] = cell
      for (let row = rowIndex; row < Math.min(rows.length, rowIndex + rowSpan); row += 1) {
        for (let col = column; col < Math.min(totalColumns, column + span); col += 1) {
          if (row === rowIndex && col === column) continue
          occupied[row][col] = true
          if (row === rowIndex) out[col] = null
        }
      }
      column += span
    }
    for (let col = 0; col < totalColumns; col += 1) {
      if (out[col] === undefined) out[col] = occupied[rowIndex][col] ? null : { value: '', type: String }
    }
    return out as Cell[]
  })
}

export type MatrixSectionColumn = { key: string; label: string; note?: string }
export type MatrixWellColumn = {
  wellId: string
  label: string
  note?: string
  sections: { key: string; label: string; note?: string }[]
}
export type MatrixItem = {
  itemId: string
  label: string
  detail?: string
  /** Category band this item belongs to (tangibles only); printed as a band row. */
  band?: string
  /** Cells for one well, one per section, in the well's section order. */
  cells: Record<string, Record<string, { quantity: string; amount: string }>>
  quantityTotal: string
  amountTotal: string
}
export type MatrixWorkbook = {
  reportKey: string
  title: string
  subtitle?: string
  currency: string
  periodLabel: string
  filtersLabel?: string
  /** True when the report measures both a quantity and a cost. */
  withQuantity: boolean
  /** Header caption for the quantity column, e.g. the unit of measure note. */
  quantityLabel?: string
  wells: MatrixWellColumn[]
  items: MatrixItem[]
  wellTotals: Record<string, { quantity: string; amount: string }>
  grandQuantity: string
  grandAmount: string
  notes?: string[]
}

export type WorkbookSheet = { name: string; rows: Cell[][]; columns: { width: number }[]; sticky?: number }

/** Build the matrix sheet's cell grid: header bands, band rows, items, totals. */
export function matrixSheet(matrix: MatrixWorkbook): WorkbookSheet {
  const measure = matrix.withQuantity ? 2 : 1
  // A quantity/cost report needs a third band to label the two measures.
  const withMeasureBand = matrix.withQuantity
  const leading = 3 // item code, item name, detail
  const sectionColumns = matrix.wells.reduce((count, well) => count + well.sections.length * measure, 0)
  const wellTotalColumns = matrix.wells.length * measure
  const totalColumns = leading + sectionColumns + wellTotalColumns + 2 // grand qty + grand amount
  const widths: { width: number }[] = [
    { width: 16 }, { width: 34 }, { width: 26 },
    ...matrix.wells.flatMap(well => well.sections.flatMap(() =>
      matrix.withQuantity ? [{ width: 10 }, { width: 14 }] : [{ width: 15 }])),
    ...matrix.wells.flatMap(() => matrix.withQuantity ? [{ width: 11 }, { width: 15 }] : [{ width: 16 }]),
    ...(matrix.withQuantity ? [{ width: 12 }] : []),
    { width: 16 },
  ]

  const rows: Cell[][] = []

  // Title block: what this sheet is, for which period, in which currency.
  rows.push([{ value: spreadsheetText(matrix.title), type: String, fontSize: undefined, fontWeight: 'bold', columnSpan: totalColumns, height: 26 } as Cell])
  rows.push([{
    value: spreadsheetText([matrix.periodLabel, `Currency ${matrix.currency}`, matrix.filtersLabel].filter(Boolean).join(' · ')),
    type: String, columnSpan: totalColumns, textColor: INK,
  } as Cell])
  if (matrix.subtitle) rows.push([{ value: spreadsheetText(matrix.subtitle), type: String, columnSpan: totalColumns, textColor: INK, wrap: true } as Cell])
  rows.push([])

  // Header bands. The first names the wells, the second their sections and the
  // third the measures under each section. The three leading columns span every
  // band.
  const leadingSpan = withMeasureBand ? 3 : 2
  const headerRowOne: Cell[] = [
    header('Item code', { rowSpan: leadingSpan, align: 'left' }),
    header('Item', { rowSpan: leadingSpan, align: 'left' }),
    header('Detail', { rowSpan: leadingSpan, align: 'left' }),
    ...matrix.wells.map(well => header(well.note ? `${well.label}\n${well.note}` : well.label, { columnSpan: well.sections.length * measure })),
    header(matrix.withQuantity ? 'Grand total\nQty · Cost' : 'Grand total', { columnSpan: 2, rowSpan: leadingSpan }),
  ]
  const headerRowTwo: Cell[] = matrix.wells.flatMap(well => [
    ...well.sections.map(section => (withMeasureBand
      ? header(section.label, { columnSpan: 2 })
      : header(section.label))),
    header('Well total', { columnSpan: measure, backgroundColor: BAND, textColor: INK }),
  ])
  const headerRowThree: Cell[] = matrix.wells.flatMap(well => [
    ...well.sections.flatMap(() => (matrix.withQuantity
      ? [header(matrix.quantityLabel ?? 'Qty', { backgroundColor: BAND, textColor: INK }),
        header(`Cost (${matrix.currency})`, { backgroundColor: BAND, textColor: INK })]
      : [])),
    ...(matrix.withQuantity
      ? [header('Qty', { backgroundColor: BAND, textColor: INK }), header(`Cost (${matrix.currency})`, { backgroundColor: BAND, textColor: INK })]
      : []),
  ])
  const headerRows = layOutRows(
    withMeasureBand ? [headerRowOne, headerRowTwo, headerRowThree] : [headerRowOne, headerRowTwo],
    totalColumns,
  )
  rows.push(...headerRows)

  let band: string | null = null
  for (const item of matrix.items) {
    if (matrix.items.some(entry => entry.band) && item.band && item.band !== band) {
      band = item.band
      rows.push([{
        value: spreadsheetText(item.band.toUpperCase()), type: String, columnSpan: totalColumns,
        fontWeight: 'bold', backgroundColor: BAND, textColor: INK, borderStyle: 'thin', borderColor: HAIRLINE,
      } as Cell])
    }
    const row: Cell[] = [
      text(item.label.split(' · ')[0] ?? '', { fontWeight: 'bold' }),
      text(item.label.split(' · ').slice(1).join(' · ') || item.label),
      text(item.detail ?? ''),
    ]
    for (const well of matrix.wells) {
      for (const section of well.sections) {
        const cell = item.cells[well.wellId]?.[section.key]
        if (matrix.withQuantity) row.push(numeric(cell?.quantity, '#,##0.####'))
        row.push(numeric(cell?.amount))
      }
      const totals = Object.values(item.cells[well.wellId] ?? {}).reduce(
        (sum, cell) => ({ quantity: sum.quantity + Number(cell.quantity || 0), amount: sum.amount + Number(cell.amount || 0) }),
        { quantity: 0, amount: 0 },
      )
      if (matrix.withQuantity) row.push(numeric(totals.quantity, '#,##0.####'))
      row.push(numeric(totals.amount))
    }
    if (matrix.withQuantity) row.push(numeric(item.quantityTotal, '#,##0.####'))
    row.push(numeric(item.amountTotal))
    rows.push(row)
  }

  // Totals row per well, then the grand total.
  const totalRow: Cell[] = [
    { value: 'Total', type: String, fontWeight: 'bold', backgroundColor: BAND, borderStyle: 'thin', borderColor: HAIRLINE },
    { value: '', type: String, backgroundColor: BAND, borderStyle: 'thin', borderColor: HAIRLINE },
    { value: '', type: String, backgroundColor: BAND, borderStyle: 'thin', borderColor: HAIRLINE },
  ]
  for (const well of matrix.wells) {
    for (const section of well.sections) {
      const cellTotals = matrix.items.reduce(
        (sum, item) => {
          const cell = item.cells[well.wellId]?.[section.key]
          return { quantity: sum.quantity + Number(cell?.quantity || 0), amount: sum.amount + Number(cell?.amount || 0) }
        },
        { quantity: 0, amount: 0 },
      )
      if (matrix.withQuantity) totalRow.push({ ...numeric(cellTotals.quantity, '#,##0.####'), fontWeight: 'bold', backgroundColor: BAND })
      totalRow.push({ ...numeric(cellTotals.amount), fontWeight: 'bold', backgroundColor: BAND })
    }
    const wellTotal = matrix.wellTotals[well.wellId]
    if (matrix.withQuantity) totalRow.push({ ...numeric(wellTotal?.quantity ?? 0, '#,##0.####'), fontWeight: 'bold', backgroundColor: BAND })
    totalRow.push({ ...numeric(wellTotal?.amount ?? 0), fontWeight: 'bold', backgroundColor: BAND })
  }
  if (matrix.withQuantity) totalRow.push({ ...numeric(matrix.grandQuantity, '#,##0.####'), fontWeight: 'bold', backgroundColor: BAND })
  totalRow.push({ ...numeric(matrix.grandAmount), fontWeight: 'bold', backgroundColor: BAND })
  rows.push(totalRow)

  if (matrix.notes?.length) {
    rows.push([])
    for (const note of matrix.notes) {
      rows.push([{ value: spreadsheetText(note), type: String, columnSpan: totalColumns, textColor: INK, wrap: true } as Cell])
    }
  }

  return {
    name: matrix.title.replace(/[\\/*?:[\]]/g, ' ').trim().slice(0, 31) || 'Matrix',
    rows,
    columns: widths,
    sticky: 4,
  }
}

/** The detail rows of a report, as a flat sheet — the workbook's second tab. */
export function detailSheet(name: string, columns: { key: string; label: string; numeric?: boolean }[], rows: Record<string, unknown>[]): WorkbookSheet {
  return {
    name: name.slice(0, 31),
    rows: [
      columns.map(column => header(column.label, { align: column.numeric ? 'right' : 'left' })),
      ...rows.map(row => columns.map(column => {
        const value = row[column.key]
        if (column.numeric) return numeric(value === null || value === undefined ? null : String(value))
        return text(value === null || value === undefined ? '' : String(value))
      })),
    ],
    columns: columns.map(column => ({ width: column.numeric ? 16 : Math.min(48, Math.max(14, column.label.length + 6)) })),
    sticky: 1,
  }
}

/**
 * Write one workbook with several sheets.
 *
 * `write-excel-file` is imported on demand: the reports page stays light, and a
 * user who never exports pays nothing for this module.
 */
export async function writeWorkbook(fileName: string, sheets: WorkbookSheet[], options: { orientation?: 'landscape' } = {}): Promise<void> {
  const { default: writeXlsxFile } = await import('write-excel-file/browser')
  const payload = sheets.map(sheet => ({
    data: sheet.rows as never,
    sheet: sheet.name,
    columns: sheet.columns,
    showGridLines: false,
    stickyRows: sheet.sticky ?? 0,
    // A matrix is wide by nature; landscape is what a reader prints.
    orientation: options.orientation ?? 'landscape',
  }))
  const file = writeXlsxFile(payload as never, { fontFamily: 'Calibri', fontSize: 10 } as never) as unknown as {
    toBlob: () => Promise<Blob>
    toFile: (path: string) => Promise<void>
  }
  // Browser: hand the file to the user. Node (the export check): write it so the
  // produced workbook can be unzipped and inspected.
  if (typeof document !== 'undefined' && typeof URL !== 'undefined') {
    await file.toFile(fileName)
    return
  }
  const blob = await file.toBlob()
  const buffer = new Uint8Array(await blob.arrayBuffer())
  const { writeFile } = await import('node:fs/promises')
  await writeFile(fileName, buffer)
}
