/**
 * Report document PDF builder.
 *
 * Every exported dashboard uses this one document: a title block with the
 * workspace, the scope in words, the read time and the page count; KPI tiles;
 * the figures as tables; and — the point of the feature — the charts **as they
 * are on screen**, captured from the live SVG scene rather than redrawn.
 *
 * Conventions that keep the export trustworthy:
 *  - The document says what it is: page *n* of *m*, the filters in force, and
 *    whether draft sheets were included. A printed dashboard is often read
 *    away from the application, so it must be able to explain itself.
 *  - A figure that could not be captured is named on the page, never silently
 *    dropped, and its data table follows.
 *  - Charts are rasterised at 2× and placed to preserve their aspect ratio, so
 *    labels stay readable and nothing is stretched.
 */

export type ReportKpi = { label: string; value: string; hint?: string }
export type ReportTable = {
  title?: string
  head: string[]
  body: (string | number)[][]
  /** Column indexes that read as numbers (right-aligned, tabular). */
  numeric?: number[]
  /** Column indexes that should fill the remaining width (left aligned). */
  wide?: number[]
}
export type ReportFigure = {
  title?: string
  caption?: string
  /** PNG data URL; empty when the figure could not be rendered. */
  dataUrl: string
  width: number
  height: number
}
export type ReportSection = {
  title: string
  subtitle?: string
  kpis?: ReportKpi[]
  figures?: ReportFigure[]
  tables?: ReportTable[]
  notes?: string[]
}

export type ReportDocument = {
  title: string
  subtitle?: string
  /** Workspace and the scope in words: rig, well, AFE, period. */
  scope?: string
  /** When the figures were read from the server. */
  readAt?: string
  /** Anything a reader must know to interpret the page. */
  notices?: string[]
  sections: ReportSection[]
  /** File name without an extension. */
  fileName: string
  /** A4 landscape by default; portrait suits a narrow drill-through page. */
  orientation?: 'landscape' | 'portrait'
}

const INK: [number, number, number] = [22, 40, 63]
const PETROL: [number, number, number] = [21, 81, 91]
const HAIRLINE: [number, number, number] = [214, 222, 226]
const MUTED: [number, number, number] = [92, 108, 118]

type JsPdf = {
  internal: { pageSize: { getWidth: () => number; getHeight: () => number } }
  setFont: (family: string, style?: string) => void
  setFontSize: (size: number) => void
  setTextColor: (...rgb: number[]) => void
  setDrawColor: (...rgb: number[]) => void
  setLineWidth: (width: number) => void
  setFillColor: (...rgb: number[]) => void
  text: (text: string | string[], x: number, y: number, options?: { maxWidth?: number }) => void
  line: (x1: number, y1: number, x2: number, y2: number) => void
  rect: (x: number, y: number, w: number, h: number, style?: string) => void
  addPage: () => void
  addImage: (data: string, format: string, x: number, y: number, w: number, h: number) => void
  getNumberOfPages: () => number
  setPage: (page: number) => void
  save: (name: string) => void
  splitTextToSize: (text: string, size: number) => string[]
  /** jsPDF aligns text through per-call options; declared loosely here. */
  getTextWidth?: (text: string) => number
  lastAutoTable?: { finalY: number }
}

const MARGIN = 14
const CONTENT_TOP = 26


/** A4 landscape reads a dashboard better than portrait: wide tables, wide charts. */
export async function buildReportPdf(report: ReportDocument): Promise<JsPdf> {
  const [{ jsPDF }, autoTableModule] = await Promise.all([import('jspdf'), import('jspdf-autotable')])
  const autoTable = autoTableModule.default
  const doc = new jsPDF({ orientation: report.orientation ?? 'landscape', unit: 'mm', format: 'a4' }) as unknown as JsPdf
  const pageWidth = doc.internal.pageSize.getWidth()
  const pageHeight = doc.internal.pageSize.getHeight()
  const contentWidth = pageWidth - MARGIN * 2
  let y = CONTENT_TOP

  const ensure = (needed: number) => {
    if (y + needed <= pageHeight - 16) return
    doc.addPage()
    y = CONTENT_TOP
  }

  const writeHeading = (title: string, subtitle?: string) => {
    ensure(18)
    // Heading baseline sits below the previous block, never on its last line.
    y += 3
    doc.setFont('helvetica', 'bold')
    doc.setFontSize(11.5)
    doc.setTextColor(...PETROL)
    doc.text(title, MARGIN, y)
    y += 5
    doc.setDrawColor(...HAIRLINE)
    doc.setLineWidth(0.3)
    doc.line(MARGIN, y, pageWidth - MARGIN, y)
    y += 4
    if (subtitle) {
      doc.setFont('helvetica', 'normal')
      doc.setFontSize(8.5)
      doc.setTextColor(...MUTED)
      doc.text(doc.splitTextToSize(subtitle, contentWidth), MARGIN, y)
      y += subtitle.length > 150 ? 9 : 5
    }
    doc.setTextColor(...INK)
  }

  // ---- title block ---------------------------------------------------------
  doc.setFont('helvetica', 'bold')
  doc.setFontSize(17)
  doc.setTextColor(...INK)
  doc.text(report.title, MARGIN, 16)
  doc.setFont('helvetica', 'normal')
  doc.setFontSize(9)
  doc.setTextColor(...MUTED)
  const metaLine = [report.scope, report.readAt ? `Read ${report.readAt}` : ''].filter(Boolean).join(' · ')
  if (report.subtitle) doc.text(doc.splitTextToSize(report.subtitle, contentWidth), MARGIN, 21)
  if (metaLine) {
    doc.setFontSize(8)
    doc.text(doc.splitTextToSize(metaLine, contentWidth), MARGIN, report.subtitle ? 29 : 22)
    y = report.subtitle ? 36 : 29
  } else if (report.subtitle) {
    y = 29
  }
  doc.setTextColor(...INK)

  if (report.notices?.length) {
    // Measure the block before drawing it, so the rule beside the notices and
    // the first section heading can never overlap it.
    doc.setFont('helvetica', 'normal')
    doc.setFontSize(7.6)
    const noticeLines = report.notices.flatMap(notice => doc.splitTextToSize(notice, contentWidth - 6))
    const blockTop = y
    const blockHeight = noticeLines.length * 3.2 + 2
    doc.setDrawColor(...PETROL)
    doc.setLineWidth(0.6)
    doc.line(MARGIN, blockTop - 3, MARGIN, blockTop + blockHeight - 3)
    doc.setTextColor(...MUTED)
    noticeLines.forEach((line, index) => doc.text(line, MARGIN + 3.5, blockTop + index * 3.2))
    doc.setTextColor(...INK)
    y = blockTop + blockHeight + 5
  }

  // ---- sections ------------------------------------------------------------
  for (const section of report.sections) {
    writeHeading(section.title, section.subtitle)

    if (section.kpis?.length) {
      const columns = Math.min(4, section.kpis.length)
      const gap = 2.4
      const tileWidth = (contentWidth - gap * (columns - 1)) / columns
      const rowHeight = 15
      for (let index = 0; index < section.kpis.length; index += columns) {
        ensure(rowHeight + 2)
        const slice = section.kpis.slice(index, index + columns)
        slice.forEach((kpi, column) => {
          const x = MARGIN + column * (tileWidth + gap)
          doc.setDrawColor(...HAIRLINE)
          doc.setLineWidth(0.25)
          doc.rect(x, y, tileWidth, rowHeight, 'S')
          doc.setFont('helvetica', 'bold')
          doc.setFontSize(6.6)
          doc.setTextColor(...MUTED)
          doc.text(kpi.label.toUpperCase(), x + 2, y + 4)
          doc.setFontSize(11.5)
          doc.setTextColor(...INK)
          doc.text(doc.splitTextToSize(kpi.value, tileWidth - 4)[0] ?? kpi.value, x + 2, y + 9.6)
          if (kpi.hint) {
            doc.setFont('helvetica', 'normal')
            doc.setFontSize(6.4)
            doc.setTextColor(...MUTED)
            const hint = doc.splitTextToSize(kpi.hint, tileWidth - 4)[0] ?? kpi.hint
            doc.text(hint, x + 2, y + 13.2)
          }
        })
        y += rowHeight + 2.4
      }
      y += 1
    }

    // Figures: two per row keeps the labels of a wide bar chart readable.
    if (section.figures?.length) {
      const gap = 3
      const perRow = 2
      const figureWidth = (contentWidth - gap * (perRow - 1)) / perRow
      for (let index = 0; index < section.figures.length; index += perRow) {
        const row = section.figures.slice(index, index + perRow)
        const heights = row.map(figure => (figure.width > 0 && figure.height > 0
          ? Math.min(96, (figureWidth * figure.height) / figure.width)
          : 12))
        const figureHeight = Math.max(...heights)
        const blockHeight = figureHeight + (row.some(figure => figure.title || figure.caption) ? 9 : 3)
        ensure(blockHeight)
        row.forEach((figure, column) => {
          const x = MARGIN + column * (figureWidth + gap)
          if (figure.title) {
            doc.setFont('helvetica', 'bold')
            doc.setFontSize(8.2)
            doc.setTextColor(...INK)
            doc.text(doc.splitTextToSize(figure.title, figureWidth)[0] ?? figure.title, x, y + 3)
          }
          const plotY = y + (figure.title ? 5 : 1)
          if (figure.dataUrl && figure.width > 0 && figure.height > 0) {
            doc.addImage(figure.dataUrl, 'PNG', x, plotY, figureWidth, heights[column])
          } else {
            doc.setDrawColor(...HAIRLINE)
            doc.setLineWidth(0.3)
            doc.rect(x, plotY, figureWidth, heights[column], 'S')
            doc.setFont('helvetica', 'normal')
            doc.setFontSize(7.4)
            doc.setTextColor(...MUTED)
            doc.text('This figure could not be rendered in the export. Its figures follow as a table.', x + 2, plotY + heights[column] / 2)
            doc.setTextColor(...INK)
          }
          if (figure.caption) {
            doc.setFont('helvetica', 'normal')
            doc.setFontSize(6.6)
            doc.setTextColor(...MUTED)
            const lines = doc.splitTextToSize(figure.caption, figureWidth)
            doc.text(lines.slice(0, 2), x, plotY + heights[column] + 3)
            doc.setTextColor(...INK)
          }
        })
        y += blockHeight + 2
      }
      y += 1
    }

    for (const table of section.tables ?? []) {
      if (table.title) {
        ensure(10)
        doc.setFont('helvetica', 'bold')
        doc.setFontSize(9)
        doc.setTextColor(...INK)
        doc.text(table.title, MARGIN, y + 3)
        y += 5.5
      }
      if (!table.body.length) {
        doc.setFont('helvetica', 'normal')
        doc.setFontSize(8)
        doc.setTextColor(...MUTED)
        doc.text('No rows match this scope.', MARGIN, y + 3)
        doc.setTextColor(...INK)
        y += 7
        continue
      }
      autoTable(doc, {
        startY: y,
        margin: { left: MARGIN, right: MARGIN },
        head: [table.head],
        body: table.body.map(row => row.map(cell => String(cell ?? ''))),
        styles: { fontSize: 7.2, cellPadding: 1.6, textColor: INK, lineColor: HAIRLINE, lineWidth: 0.1 },
        headStyles: { fillColor: PETROL, textColor: [255, 255, 255], fontStyle: 'bold', fontSize: 7.4 },
        alternateRowStyles: { fillColor: [246, 248, 249] },
        columnStyles: Object.fromEntries([
          ...(table.numeric ?? []).map(index => [index, { halign: 'right' as const }]),
          ...(table.wide ?? []).map(index => [index, { cellWidth: 'auto' as const }]),
        ]),
        didDrawPage: () => { y = CONTENT_TOP },
      })
      y = (doc.lastAutoTable?.finalY ?? y) + 6
    }

    if (section.notes?.length) {
      doc.setFont('helvetica', 'normal')
      doc.setFontSize(7.2)
      doc.setTextColor(...MUTED)
      for (const note of section.notes) {
        ensure(8)
        const lines = doc.splitTextToSize(note, contentWidth)
        doc.text(lines, MARGIN, y + 2)
        y += lines.length * 3 + 1.6
      }
      doc.setTextColor(...INK)
      y += 2
    }
    y += 3
  }

  // ---- running footer on every page ---------------------------------------
  const pages = doc.getNumberOfPages()
  for (let page = 1; page <= pages; page += 1) {
    doc.setPage(page)
    doc.setDrawColor(...HAIRLINE)
    doc.setLineWidth(0.25)
    doc.line(MARGIN, pageHeight - 11, pageWidth - MARGIN, pageHeight - 11)
    doc.setFont('helvetica', 'normal')
    doc.setFontSize(7)
    doc.setTextColor(...MUTED)
    doc.text(report.title, MARGIN, pageHeight - 7)
    doc.text(`Page ${page} of ${pages}`, pageWidth - MARGIN, pageHeight - 7, { align: 'right' } as never)
    doc.text(report.scope ?? '', pageWidth / 2, pageHeight - 7, { align: 'center' } as never)
  }
  doc.setTextColor(...INK)
  return doc
}

/** Build the document and hand it to the browser as a download. */
export async function exportReportPdf(report: ReportDocument): Promise<void> {
  const doc = await buildReportPdf(report)
  doc.save(`${report.fileName}-${new Date().toISOString().slice(0, 10)}.pdf`)
}
