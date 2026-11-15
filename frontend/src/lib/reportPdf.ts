/**
 * Report document PDF builder.
 *
 * Every exported dashboard, report, and consolidated well dossier uses this
 * document layout engine:
 *  - Dynamic line-measured typography so titles, subtitles, metadata, notices,
 *    KPI cards, figure titles, captions, and running footers never overlap or
 *    clip in either landscape or portrait orientation.
 *  - Auto-fitted KPI values with clean wrapping labels/hints.
 *  - Aspect-preserved, framed chart figures (full-width when solo on a row,
 *    side-by-side in pairs) with crisp captions and explicit named fallbacks
 *    whenever a visual could not be rendered.
 *  - Clean page breaks (`pageBreakBefore`) and styled subtotal/total rows so
 *    multi-report consolidated bundles read like a cohesive engineering report.
 */

export type ReportKpi = { label: string; value: string; hint?: string }
export type ReportTable = {
  title?: string
  head: string[]
  body: (string | number)[][]
  /** Optional bold summary/footer row rendered at the bottom of the table. */
  foot?: (string | number)[]
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
  /** Force full content width instead of sharing a 2-column row. */
  fullWidth?: boolean
}
export type ReportSection = {
  title: string
  subtitle?: string
  /** Small uppercase eyebrow badge printed above the section title (e.g. "SECTION 3 OF 7"). */
  badge?: string
  /** Start this section on a fresh page (ignored for the first section on page 1). */
  pageBreakBefore?: boolean
  /** Override KPI columns per row (default: up to 4). */
  kpisPerRow?: number
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
const SURFACE: [number, number, number] = [248, 250, 251]
const FOOT_BG: [number, number, number] = [235, 241, 244]

type JsPdf = {
  internal: { pageSize: { getWidth: () => number; getHeight: () => number } }
  setFont: (family: string, style?: string) => void
  setFontSize: (size: number) => void
  setTextColor: (...rgb: number[]) => void
  setDrawColor: (...rgb: number[]) => void
  setLineWidth: (width: number) => void
  setFillColor: (...rgb: number[]) => void
  text: (text: string | string[], x: number, y: number, options?: { maxWidth?: number; align?: string }) => void
  line: (x1: number, y1: number, x2: number, y2: number) => void
  rect: (x: number, y: number, w: number, h: number, style?: string) => void
  addPage: () => void
  addImage: (data: string, format: string, x: number, y: number, w: number, h: number) => void
  getNumberOfPages: () => number
  setPage: (page: number) => void
  save: (name: string) => void
  splitTextToSize: (text: string, size: number) => string[]
  getTextWidth?: (text: string) => number
  lastAutoTable?: { finalY: number }
}

const MARGIN = 14
const CONTENT_TOP = 18
const FOOTER_RESERVE = 15

function measureWidth(doc: JsPdf, text: string, fontSize: number): number {
  if (typeof doc.getTextWidth === 'function') {
    doc.setFontSize(fontSize)
    return doc.getTextWidth(text)
  }
  // Fallback heuristic (~0.52 * pt in mm).
  return text.length * fontSize * 0.19
}

function fitFontSize(doc: JsPdf, text: string, maxWidth: number, startPt: number, minPt: number): number {
  let pt = startPt
  while (pt > minPt && measureWidth(doc, text, pt) > maxWidth) {
    pt = Math.max(minPt, Number((pt - 0.6).toFixed(1)))
  }
  return pt
}

function truncateText(doc: JsPdf, text: string, maxWidth: number, fontSize: number): string {
  if (!text) return ''
  if (measureWidth(doc, text, fontSize) <= maxWidth) return text
  let end = text.length
  while (end > 4 && measureWidth(doc, `${text.slice(0, end)}…`, fontSize) > maxWidth) {
    end -= 2
  }
  return `${text.slice(0, Math.max(1, end))}…`
}

/** A4 landscape reads a dashboard better than portrait: wide tables, wide charts. */
export async function buildReportPdf(report: ReportDocument): Promise<JsPdf> {
  const [{ jsPDF }, autoTableModule] = await Promise.all([import('jspdf'), import('jspdf-autotable')])
  const autoTable = autoTableModule.default
  const doc = new jsPDF({ orientation: report.orientation ?? 'landscape', unit: 'mm', format: 'a4' }) as unknown as JsPdf
  const pageWidth = doc.internal.pageSize.getWidth()
  const pageHeight = doc.internal.pageSize.getHeight()
  const contentWidth = pageWidth - MARGIN * 2
  const maxContentY = pageHeight - FOOTER_RESERVE
  let y = CONTENT_TOP

  const ensure = (needed: number) => {
    if (y + needed <= maxContentY) return
    doc.addPage()
    y = CONTENT_TOP
  }

  const writeHeading = (title: string, subtitle?: string, badge?: string) => {
    doc.setFont('helvetica', 'bold')
    doc.setFontSize(11.5)
    const titleLines = doc.splitTextToSize(title, contentWidth)
    doc.setFont('helvetica', 'normal')
    doc.setFontSize(8.4)
    const subtitleLines = subtitle ? doc.splitTextToSize(subtitle, contentWidth) : []
    const needed = (badge ? 4.5 : 0) + titleLines.length * 4.8 + 4 + subtitleLines.length * 3.8 + 12
    ensure(needed)

    if (y > CONTENT_TOP + 1) y += 3
    if (badge) {
      doc.setFont('helvetica', 'bold')
      doc.setFontSize(7.2)
      doc.setTextColor(...MUTED)
      doc.text(badge.toUpperCase(), MARGIN, y)
      y += 4.2
    }
    doc.setFont('helvetica', 'bold')
    doc.setFontSize(11.5)
    doc.setTextColor(...PETROL)
    doc.text(titleLines, MARGIN, y)
    y += titleLines.length * 4.8 + 0.8
    doc.setDrawColor(...HAIRLINE)
    doc.setLineWidth(0.35)
    doc.line(MARGIN, y, pageWidth - MARGIN, y)
    y += 4.2
    if (subtitleLines.length) {
      doc.setFont('helvetica', 'normal')
      doc.setFontSize(8.4)
      doc.setTextColor(...MUTED)
      doc.text(subtitleLines, MARGIN, y)
      y += subtitleLines.length * 3.8 + 2.5
    }
    doc.setTextColor(...INK)
  }

  // ---- title block (dynamically measured so lines never collide) -----------
  doc.setFont('helvetica', 'bold')
  doc.setFontSize(16.5)
  doc.setTextColor(...INK)
  const titleLines = doc.splitTextToSize(report.title, contentWidth)
  doc.text(titleLines, MARGIN, 15)
  y = 15 + titleLines.length * 6.2 + 0.5

  if (report.subtitle) {
    doc.setFont('helvetica', 'normal')
    doc.setFontSize(9)
    doc.setTextColor(...MUTED)
    const subLines = doc.splitTextToSize(report.subtitle, contentWidth)
    doc.text(subLines, MARGIN, y)
    y += subLines.length * 4.1 + 1.5
  }

  const metaLine = [report.scope, report.readAt ? `Generated ${report.readAt}` : ''].filter(Boolean).join(' · ')
  if (metaLine) {
    doc.setFont('helvetica', 'normal')
    doc.setFontSize(8)
    doc.setTextColor(...MUTED)
    const metaLines = doc.splitTextToSize(metaLine, contentWidth)
    doc.text(metaLines, MARGIN, y)
    y += metaLines.length * 3.6 + 2.5
  }

  // Subtle top header rule beneath title metadata.
  doc.setDrawColor(...PETROL)
  doc.setLineWidth(0.55)
  doc.line(MARGIN, y, pageWidth - MARGIN, y)
  y += 4.5
  doc.setTextColor(...INK)

  if (report.notices?.length) {
    doc.setFont('helvetica', 'normal')
    doc.setFontSize(7.6)
    const noticeLines = report.notices.flatMap(notice => doc.splitTextToSize(notice, contentWidth - 6))
    const blockHeight = noticeLines.length * 3.5 + 3.2
    ensure(blockHeight + 4)
    const blockTop = y
    doc.setFillColor(...SURFACE)
    doc.rect(MARGIN, blockTop - 3, contentWidth, blockHeight, 'F')
    doc.setDrawColor(...PETROL)
    doc.setLineWidth(0.8)
    doc.line(MARGIN, blockTop - 3, MARGIN, blockTop - 3 + blockHeight)
    doc.setTextColor(...MUTED)
    noticeLines.forEach((line, index) => doc.text(line, MARGIN + 3.8, blockTop + 0.6 + index * 3.5))
    doc.setTextColor(...INK)
    y = blockTop - 3 + blockHeight + 4.5
  }

  // ---- sections ------------------------------------------------------------
  report.sections.forEach((section, sectionIndex) => {
    if (section.pageBreakBefore && sectionIndex > 0) {
      doc.addPage()
      y = CONTENT_TOP
    }

    writeHeading(section.title, section.subtitle, section.badge)

    if (section.kpis?.length) {
      const maxCols = section.kpisPerRow ?? (report.orientation === 'portrait' ? 3 : 4)
      const columns = Math.max(1, Math.min(maxCols, section.kpis.length))
      const gap = 2.6
      const tileWidth = (contentWidth - gap * (columns - 1)) / columns
      const innerWidth = tileWidth - 5.2

      for (let index = 0; index < section.kpis.length; index += columns) {
        const slice = section.kpis.slice(index, index + columns)
        const measured = slice.map(kpi => {
          doc.setFont('helvetica', 'bold')
          doc.setFontSize(6.5)
          const labelLines = doc.splitTextToSize(kpi.label.toUpperCase(), innerWidth).slice(0, 2)
          doc.setFont('helvetica', 'bold')
          const valueStr = String(kpi.value ?? '—')
          const valuePt = fitFontSize(doc, valueStr, innerWidth, 11.2, 7.6)
          doc.setFontSize(valuePt)
          const valueLines = doc.splitTextToSize(valueStr, innerWidth).slice(0, 2)
          doc.setFont('helvetica', 'normal')
          doc.setFontSize(6.4)
          const hintLines = kpi.hint ? doc.splitTextToSize(kpi.hint, innerWidth).slice(0, 2) : []
          const neededH = 3.2
            + labelLines.length * 3.0
            + 1.6
            + valueLines.length * (valuePt * 0.42 + 0.8)
            + (hintLines.length ? 1.2 + hintLines.length * 2.9 : 0)
            + 2.4
          return { kpi, labelLines, valuePt, valueLines, hintLines, neededH }
        })
        const rowHeight = Math.max(16.5, ...measured.map(m => m.neededH))
        ensure(rowHeight + 2.5)

        measured.forEach((m, column) => {
          const x = MARGIN + column * (tileWidth + gap)
          doc.setFillColor(...SURFACE)
          doc.rect(x, y, tileWidth, rowHeight, 'F')
          doc.setDrawColor(...HAIRLINE)
          doc.setLineWidth(0.25)
          doc.rect(x, y, tileWidth, rowHeight, 'S')
          doc.setFillColor(...PETROL)
          doc.rect(x, y, 1.0, rowHeight, 'F')

          let cy = y + 3.8
          doc.setFont('helvetica', 'bold')
          doc.setFontSize(6.5)
          doc.setTextColor(...MUTED)
          doc.text(m.labelLines, x + 2.8, cy)
          cy += m.labelLines.length * 3.0 + 1.8

          doc.setFont('helvetica', 'bold')
          doc.setFontSize(m.valuePt)
          doc.setTextColor(...INK)
          doc.text(m.valueLines, x + 2.8, cy)
          cy += m.valueLines.length * (m.valuePt * 0.42 + 0.8) + 0.8

          if (m.hintLines.length) {
            doc.setFont('helvetica', 'normal')
            doc.setFontSize(6.4)
            doc.setTextColor(...MUTED)
            doc.text(m.hintLines, x + 2.8, cy)
          }
        })
        doc.setTextColor(...INK)
        y += rowHeight + 2.6
      }
      y += 1.5
    }

    // Figures: pair charts cleanly or give a solo/fullWidth chart the full width.
    if (section.figures?.length) {
      const gap = 3.5
      let index = 0
      while (index < section.figures.length) {
        const current = section.figures[index]
        const next = section.figures[index + 1]
        const singleRow = Boolean(current.fullWidth) || !next || Boolean(next.fullWidth)
        const row = singleRow ? [current] : [current, next]
        index += row.length

        const slotWidth = singleRow ? contentWidth : (contentWidth - gap) / 2
        const maxPlotHeight = singleRow
          ? (report.orientation === 'portrait' ? 88 : 94)
          : (report.orientation === 'portrait' ? 76 : 86)

        const layout = row.map(figure => {
          doc.setFont('helvetica', 'bold')
          doc.setFontSize(8.4)
          const figTitleLines = figure.title ? doc.splitTextToSize(figure.title, slotWidth - 4).slice(0, 2) : []
          doc.setFont('helvetica', 'normal')
          doc.setFontSize(6.8)
          const figCaptionLines = figure.caption ? doc.splitTextToSize(figure.caption, slotWidth - 4).slice(0, 3) : []

          const innerPlotW = slotWidth - 4
          let drawW = innerPlotW
          let drawH = 18
          if (figure.dataUrl && figure.width > 0 && figure.height > 0) {
            const aspect = figure.height / figure.width
            drawH = innerPlotW * aspect
            if (drawH > maxPlotHeight) {
              drawH = maxPlotHeight
              drawW = drawH / aspect
            }
          }
          const titleH = figTitleLines.length ? figTitleLines.length * 3.6 + 1.8 : 0
          const captionH = figCaptionLines.length ? figCaptionLines.length * 3.0 + 2.2 : 0
          return { figure, figTitleLines, figCaptionLines, drawW, drawH, titleH, captionH }
        })

        const maxTitleH = Math.max(...layout.map(l => l.titleH))
        const maxDrawH = Math.max(...layout.map(l => l.drawH))
        const maxCaptionH = Math.max(...layout.map(l => l.captionH))
        const cardPadding = 2.6
        const blockHeight = cardPadding + maxTitleH + maxDrawH + maxCaptionH + cardPadding

        ensure(blockHeight + 3)

        layout.forEach((item, column) => {
          const x = MARGIN + column * (slotWidth + gap)
          // Crisp framed card around each figure so multi-chart pages stay clean.
          doc.setDrawColor(...HAIRLINE)
          doc.setLineWidth(0.25)
          doc.rect(x, y, slotWidth, blockHeight, 'S')

          let cy = y + cardPadding
          if (item.figTitleLines.length) {
            doc.setFont('helvetica', 'bold')
            doc.setFontSize(8.4)
            doc.setTextColor(...INK)
            doc.text(item.figTitleLines, x + 2, cy + 2.8)
          }
          cy += maxTitleH

          if (item.figure.dataUrl && item.figure.width > 0 && item.figure.height > 0) {
            const offsetX = x + 2 + (slotWidth - 4 - item.drawW) / 2
            doc.addImage(item.figure.dataUrl, 'PNG', offsetX, cy, item.drawW, item.drawH)
          } else {
            doc.setFillColor(...SURFACE)
            doc.rect(x + 2, cy, slotWidth - 4, maxDrawH, 'F')
            doc.setDrawColor(...HAIRLINE)
            doc.setLineWidth(0.25)
            doc.rect(x + 2, cy, slotWidth - 4, maxDrawH, 'S')
            doc.setFont('helvetica', 'normal')
            doc.setFontSize(7.4)
            doc.setTextColor(...MUTED)
            const msg = doc.splitTextToSize(
              'This figure could not be rendered in the export. Its figures follow as a table.',
              slotWidth - 8,
            )
            doc.text(msg, x + 4, cy + Math.max(6, maxDrawH / 2 - 1))
            doc.setTextColor(...INK)
          }

          if (item.figCaptionLines.length) {
            doc.setFont('helvetica', 'normal')
            doc.setFontSize(6.8)
            doc.setTextColor(...MUTED)
            doc.text(item.figCaptionLines, x + 2, cy + maxDrawH + 3.2)
            doc.setTextColor(...INK)
          }
        })
        y += blockHeight + 3.2
      }
      y += 1
    }

    for (const table of section.tables ?? []) {
      if (table.title) {
        doc.setFont('helvetica', 'bold')
        doc.setFontSize(9)
        const tblTitleLines = doc.splitTextToSize(table.title, contentWidth)
        ensure(tblTitleLines.length * 4 + 14)
        doc.setTextColor(...INK)
        doc.text(tblTitleLines, MARGIN, y + 3)
        y += tblTitleLines.length * 4 + 2
      }
      if (!table.body.length) {
        ensure(8)
        doc.setFont('helvetica', 'normal')
        doc.setFontSize(8)
        doc.setTextColor(...MUTED)
        doc.text('No rows match this scope.', MARGIN, y + 3)
        doc.setTextColor(...INK)
        y += 7
        continue
      }
      const dense = table.head.length >= 9
      autoTable(doc, {
        startY: y,
        margin: { left: MARGIN, right: MARGIN, top: CONTENT_TOP, bottom: FOOTER_RESERVE },
        head: [table.head],
        body: table.body.map(row => row.map(cell => String(cell ?? ''))),
        ...(table.foot?.length ? {
          foot: [table.foot.map(cell => String(cell ?? ''))],
          showFoot: 'lastPage' as const,
          footStyles: { fillColor: FOOT_BG, textColor: INK, fontStyle: 'bold', fontSize: dense ? 6.8 : 7.3 },
        } : {}),
        styles: {
          fontSize: dense ? 6.6 : 7.2,
          cellPadding: dense ? 1.3 : 1.6,
          textColor: INK,
          lineColor: HAIRLINE,
          lineWidth: 0.1,
          overflow: 'linebreak',
        },
        headStyles: { fillColor: PETROL, textColor: [255, 255, 255], fontStyle: 'bold', fontSize: dense ? 6.8 : 7.4 },
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
      doc.setFontSize(7.4)
      doc.setTextColor(...MUTED)
      for (const note of section.notes) {
        const lines = doc.splitTextToSize(note, contentWidth)
        ensure(lines.length * 3.4 + 2)
        doc.text(lines, MARGIN, y + 2)
        y += lines.length * 3.4 + 1.8
      }
      doc.setTextColor(...INK)
      y += 2
    }
    y += 2.5
  })

  // ---- running footer on every page (width-guarded so elements never collide)
  const pages = doc.getNumberOfPages()
  const leftMaxW = contentWidth * 0.34
  const centerMaxW = contentWidth * 0.44
  for (let page = 1; page <= pages; page += 1) {
    doc.setPage(page)
    doc.setDrawColor(...HAIRLINE)
    doc.setLineWidth(0.25)
    doc.line(MARGIN, pageHeight - 11, pageWidth - MARGIN, pageHeight - 11)
    doc.setFont('helvetica', 'normal')
    doc.setFontSize(7)
    doc.setTextColor(...MUTED)
    doc.text(truncateText(doc, report.title, leftMaxW, 7), MARGIN, pageHeight - 7)
    if (report.scope) {
      doc.text(truncateText(doc, report.scope, centerMaxW, 7), pageWidth / 2, pageHeight - 7, { align: 'center' })
    }
    doc.text(`Page ${page} of ${pages}`, pageWidth - MARGIN, pageHeight - 7, { align: 'right' })
  }
  doc.setTextColor(...INK)
  return doc
}

/** Build the document and hand it to the browser as a download. */
export async function exportReportPdf(report: ReportDocument): Promise<void> {
  const doc = await buildReportPdf(report)
  doc.save(`${report.fileName}-${new Date().toISOString().slice(0, 10)}.pdf`)
}
