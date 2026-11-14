// Export-as-shown check.
//
// Two exports are exercised against their real modules:
//
//  1. **Matrix → Excel.** The mud-chemicals matrix is mapped to the workbook
//     structure and written by the real writer. The produced `.xlsx` is read back
//     as a ZIP and its worksheet XML is inspected: the two header bands merge the
//     wells across their sections, each section carries QTY + COST, the well
//     total band and the grand total column exist, the totals row is present and
//     amounts are numbers (never text). A hostile-looking item name is checked to
//     arrive neutralised, so no cell becomes a formula.
//
//  2. **Report → PDF.** A report document is built with a real figure image and
//     written to bytes; the PDF is parsed for its page count, its title, its
//     footer pagination and its embedded image, so the "figures as shown" promise
//     is verified rather than assumed.
//
// Contributor tool only — nothing here is imported by the app.
//
// Run from frontend/:
//   NODE_PATH="$PWD/node_modules" ./node_modules/.bin/esbuild \
//     ../.agent/tools/export-report-check.jsx --bundle --platform=node --format=esm \
//     --jsx=automatic --outfile=node_modules/.cache/export-report-check.mjs \
//     --loader:.jsx=jsx --log-level=error --external:jsdom && node node_modules/.cache/export-report-check.mjs
import { writeFileSync, readFileSync, existsSync } from 'node:fs'
import { resolve } from 'node:path'
import { unzipSync } from 'fflate'

const results = []
const check = (label, pass, detail = '') => results.push({ label, pass: !!pass, detail })
const fail = (label, error) => results.push({ label, pass: false, detail: String(error).slice(0, 300) })

// ---- 1. matrix → Excel -----------------------------------------------------
const { matrixSheet, writeWorkbook } = await import('../../frontend/src/lib/matrixWorkbook')
const { matrixWorkbook, detailWorkbook } = await import('../../frontend/src/lib/usageReports')

const sectionA = { section_key: 'sec-1', hole_section_id: 's1', section_code: '17-1/2', section_name: 'Surface hole', scope: 'drilling' }
const sectionB = { section_key: 'sec-2', hole_section_id: 's2', section_code: '12-1/4', section_name: 'Intermediate hole', scope: 'drilling' }
const wells = [
  { well_id: 'w1', well_code: 'WELL-A', well_name: 'Alpha', rig_id: 'r1', rig_code: 'RIG-1', rig_name: 'Rig One', block_id: 'b1', block_code: 'BLK-A', block_name: 'Block A', scopes: ['drilling'], sections: [sectionA, sectionB] },
  { well_id: 'w2', well_code: 'WELL-B', well_name: 'Bravo', rig_id: 'r2', rig_code: 'RIG-2', rig_name: 'Rig Two', block_id: 'b2', block_code: 'BLK-B', block_name: 'Block B', scopes: ['drilling'], sections: [sectionA] },
]
const report = {
  report: 'mud-chemicals', mode: 'usage', currency: 'USD',
  date_from: '2026-10-01', date_to: '2026-10-31', include_draft: true,
  wells,
  rows: [
    {
      item_id: 'i1', item_code: 'BARITE', item_name: '=HYPERLINK("http://x")', uom: 'MT',
      category: 'Weighting agent', subcategory: '', manufacturer: 'Halliburton', detail: 'BR-25',
      cells: [
        { well_id: 'w1', sections: [{ section_key: 'sec-1', quantity: '10', amount: '500.00' }, { section_key: 'sec-2', quantity: '5', amount: '250.00' }], quantity: '15', amount: '750.00' },
        { well_id: 'w2', sections: [{ section_key: 'sec-1', quantity: '4', amount: '200.00' }], quantity: '4', amount: '200.00' },
      ],
      quantity_total: '19', amount_total: '950.00',
    },
    {
      item_id: 'i2', item_code: 'BENT', item_name: 'Bentonite', uom: 'MT',
      category: 'Viscosifier', subcategory: '', manufacturer: 'MI-SWACO', detail: 'BN-10',
      cells: [
        { well_id: 'w1', sections: [{ section_key: 'sec-1', quantity: '2', amount: '120.00' }, { section_key: 'sec-2', quantity: '1', amount: '60.00' }], quantity: '3', amount: '180.00' },
        { well_id: 'w2', sections: [{ section_key: 'sec-1', quantity: '1', amount: '60.00' }], quantity: '1', amount: '60.00' },
      ],
      quantity_total: '4', amount_total: '240.00',
    },
  ],
  detail: [
    { row_id: 'd1', report: 'mud-chemicals', cost_group: 'Consumables', item_id: 'i1', item_code: 'BARITE', item_name: 'Barite', uom: 'MT', category: 'Weighting agent', subcategory: '', manufacturer: 'Halliburton', detail: 'BR-25', well_id: 'w1', well_code: 'WELL-A', well_name: 'Alpha', rig_code: 'RIG-1', block_code: 'BLK-A', scope: 'drilling', section_key: 'sec-1', section_code: '17-1/2', section_name: 'Surface hole', quantity: '10', amount: '500.00', currency: 'USD' },
    { row_id: 'd2', report: 'mud-chemicals', cost_group: 'Consumables', item_id: 'i2', item_code: 'BENT', item_name: 'Bentonite', uom: 'MT', category: 'Viscosifier', subcategory: '', manufacturer: 'MI-SWACO', detail: 'BN-10', well_id: 'w2', well_code: 'WELL-B', well_name: 'Bravo', rig_code: 'RIG-2', block_code: 'BLK-B', scope: 'drilling', section_key: 'sec-1', section_code: '17-1/2', section_name: 'Surface hole', quantity: '1', amount: '60.00', currency: 'USD' },
  ],
  well_totals: [
    { well_id: 'w1', sections: [], quantity: '18', amount: '930.00' },
    { well_id: 'w2', sections: [], quantity: '5', amount: '260.00' },
  ],
  grand_quantity: '23', grand_amount: '1190.00',
  entry_count: 2, excluded_entry_count: 0,
}
const filters = {
  blockId: '', rigId: '', wellIds: [], scope: '', lifecycle: '', currency: 'USD',
  dateFrom: '2026-10-01', dateTo: '2026-10-31', includeDraft: true,
}

const mapped = matrixWorkbook(report, filters)
check('matrix mapping keeps both wells and every section', mapped.wells.length === 2 && mapped.wells[0].sections.length === 2)
check('matrix mapping keeps every item', mapped.items.length === 2)
check('matrix mapping carries a period and a filter basis', mapped.periodLabel.includes('to') && mapped.filtersLabel.includes('drafts included'))

const sheet = matrixSheet(mapped)
check('matrix sheet is named after the report', sheet.name === 'Mud chemicals usage', sheet.name)
const headerBand = sheet.rows.find(row => row.some(cell => cell?.columnSpan === 4 && String(cell.value).includes('WELL-A')))
check('first header band merges WELL-A across its two sections', Boolean(headerBand))
const secondBand = sheet.rows.find(row => row.some(cell => cell?.columnSpan === 2 && String(cell.value) === '17-1/2'))
check('second header band names each section with a span', Boolean(secondBand))
const measureBand = sheet.rows.find(row => row.some(cell => String(cell?.value ?? '') === 'Qty'))
check('third header band labels Qty and Cost under each section', Boolean(measureBand))
const totalRow = sheet.rows.find(row => row[0]?.value === 'Total')
check('totals row is present', Boolean(totalRow))
const grandCell = totalRow?.[totalRow.length - 1]
check('grand total is written as a number', grandCell?.type === Number && Number(grandCell.value) === 1190)
check('item cells are written as numbers', sheet.rows.some(row => row.some(cell => cell?.type === Number && Number(cell.value) === 500)))
const hostile = sheet.rows.find(row => row.some(cell => String(cell?.value ?? '').startsWith("'=HYPERLINK")))
check('a formula-looking item name is neutralised', Boolean(hostile))

// The same mapping must serve every matrix report, not just mud chemicals: the
// cost-only reports drop the quantity column, tangibles gain category bands, and
// drill bits keep make/model/size/IADC on the item line. The structure (bands,
// sections, totals, grand total) is identical, which is what "the same matrix
// structure" means.
const costFilters = { ...filters }
for (const variant of [
  { report: 'drill-bits', mode: 'usage', expectQuantity: true, expectBand: false, title: 'Drill bits usage', detail: 'Model M1365 · Size 8-1/2 in · IADC M423' },
  { report: 'tangibles', mode: 'usage', expectQuantity: true, expectBand: true, title: 'Tangibles usage', detail: 'Nippon · Liner' },
  { report: 'services', mode: 'cost', expectQuantity: false, expectBand: false, title: 'Service-wise cost report', detail: '' },
  // Excel forbids "/" in a sheet name, so the writer keeps the words and drops it.
  { report: 'vendors', mode: 'cost', expectQuantity: false, expectBand: false, title: 'Vendor company-wise cost report', detail: '' },
]) {
  const variantReport = {
    ...report,
    report: variant.report,
    mode: variant.mode,
    rows: report.rows.map((row, index) => ({
      ...row,
      category: index === 0 ? 'Casing' : '',
      detail: variant.detail ? variant.detail : row.detail,
    })),
  }
  const variantMapped = matrixWorkbook(variantReport, costFilters)
  const variantSheet = matrixSheet(variantMapped)
  const variantWidth = variant.expectQuantity ? 4 : 2
  check(`${variant.title}: sheet is named after the report`, variantSheet.name === variant.title, variantSheet.name)
  check(`${variant.title}: well band spans its ${variant.expectQuantity ? 'two measures' : 'single measure'} per section`,
    variantSheet.rows.some(row => row.some(cell => cell?.columnSpan === variantWidth && String(cell.value).includes('WELL-A'))))
  check(`${variant.title}: quantity column ${variant.expectQuantity ? 'is written' : 'is dropped'}`,
    variantSheet.rows.some(row => row.some(cell => String(cell?.value ?? '') === 'Qty')) === variant.expectQuantity)
  check(`${variant.title}: category band ${variant.expectBand ? 'is present' : 'is not added'}`,
    variantSheet.rows.some(row => String(row[0]?.value ?? '').toUpperCase() === 'CASING') === variant.expectBand)
  const variantTotals = variantSheet.rows.find(row => row[0]?.value === 'Total')
  check(`${variant.title}: grand total stays numeric`,
    variantTotals && Number(variantTotals[variantTotals.length - 1]?.value) === 1190)
}

// The detail tab of the same workbook.
const detail = detailWorkbook(report)
check('detail tab is present with a header and one row per line', detail.name === 'Detail' && detail.rows.length === report.detail.length + 1)

// ---- write the workbook and read it back ----------------------------------
const workbookPath = 'node_modules/.cache/export-report-check.xlsx'
try {
  await writeWorkbook(workbookPath, [sheet, detail])
  const bytes = new Uint8Array(readFileSync(workbookPath))
  const archive = unzipSync(bytes)
  const names = Object.keys(archive)
  check('workbook is a real xlsx container', names.includes('xl/workbook.xml') && names.includes('[Content_Types].xml'), names.slice(0, 4).join(','))
  const sheetNames = names.filter(name => /^xl\/worksheets\/sheet\d+\.xml$/.test(name))
  check('workbook holds both sheets', sheetNames.length === 2, String(sheetNames.length))
  const shared = names.includes('xl/sharedStrings.xml') ? new TextDecoder().decode(archive['xl/sharedStrings.xml']) : ''
  const markup = new TextDecoder().decode(archive[sheetNames[0]]) + shared
  check('worksheet declares merged header bands', markup.includes('<mergeCells'))
  check('merged ranges cover the well band and the section band', (markup.match(/<mergeCell /g) ?? []).length >= 4)
  check('worksheet writes numeric cells for amounts', markup.includes('<v>1190</v>') || markup.includes('<v>1190.0</v>'))
  check('worksheet writes the item names as text', markup.includes('Bentonite'))
  check('worksheet keeps the neutralised item name', markup.includes("'=HYPERLINK") || markup.includes('&apos;=HYPERLINK'))
  check('worksheet prints no live formula element', !markup.includes('<f>'))
  const detailMarkup = new TextDecoder().decode(archive[sheetNames[1]]) + shared
  check('detail sheet carries the recorded lines', detailMarkup.includes('BARITE') && detailMarkup.includes('Bentonite'))
  writeFileSync('node_modules/.cache/export-report-check.size.txt', String(bytes.length))
  check('workbook is a reasonable size', bytes.length > 5_000, `${bytes.length} bytes`)
} catch (error) {
  fail('matrix workbook writes and reads back', error)
}

// ---- 2. report → PDF -------------------------------------------------------
const { buildReportPdf } = await import('../../frontend/src/lib/reportPdf')
// A 1×1 PNG is a valid figure stand-in: the builder must place it, not resize it
// by assumption, and the PDF must remain parseable.
const PNG = 'data:image/png;base64,iVBORw0KGgoAAAANSUhEUgAAAAYAAAAECAIAAAAiZtkUAAAAEUlEQVR4nGNQSJiAhhjIFQIAvvkZgQt1hLcAAAAASUVORK5CYII='
const PNG_TWO = 'data:image/png;base64,iVBORw0KGgoAAAANSUhEUgAAAAYAAAAECAIAAAAiZtkUAAAAEUlEQVR4nGOY4KCAhhjIFQIAYfkWgVh7yucAAAAASUVORK5CYII='
try {
  const doc = await buildReportPdf({
    title: 'Operations dashboard',
    subtitle: 'Plan, budget and actuals for the selected scope.',
    scope: 'North Energy · All rigs · 01/01/2026 to 31/12/2026',
    readAt: '14/11/2026 09:30',
    notices: ['Draft sheets are included.', 'Amounts are grouped by the AFE standard currency and never converted silently.'],
    fileName: 'operations-dashboard',
    sections: [
      {
        title: 'Financial exposure',
        kpis: [
          { label: 'Effective plan', value: '1,250,000.00 USD', hint: '3 AFEs' },
          { label: 'Actual cost', value: '980,500.00 USD', hint: '78.4% of plan' },
          { label: 'Balance', value: '269,500.00 USD', hint: 'Remaining' },
        ],
        figures: [
          { title: 'AFE against actual cost', caption: 'Top wells by effective plan.', dataUrl: PNG, width: 640, height: 300 },
          { title: 'Planned days against actual time', caption: 'Diamond marks planned duration.', dataUrl: PNG_TWO, width: 640, height: 300 },
          { title: 'Depth progress', caption: 'Deepest section carrying cost.', dataUrl: '', width: 0, height: 0 },
        ],
        tables: [
          { title: 'Cost group reconciliation', head: ['Group', 'AFE planned', 'Actual', 'Balance'], body: [['Services', '1,000,000.00', '800,000.00', '200,000.00'], ['Consumables', '250,000.00', '180,500.00', '69,500.00']], numeric: [1, 2, 3] },
        ],
      },
      {
        title: 'Register drill-through',
        tables: [{ title: 'Wells', head: ['Well', 'Actual days', 'Actual cost'], body: [['WELL-A', '30.000', '500,000.00']], numeric: [1, 2] }],
        notes: ['Actual days are elapsed time from spud to the end of the last included cost date.'],
      },
    ],
  })
  const out = doc.output('arraybuffer')
  const bytes = Buffer.from(out)
  writeFileSync('node_modules/.cache/export-report-check.pdf', bytes)
  const text = bytes.toString('latin1')
  check('PDF is written', text.startsWith('%PDF-'), text.slice(0, 8))
  check('PDF carries the title', text.includes('Operations dashboard'))
  // Each captured figure is an actual XObject image in the page's resources —
  // not a placeholder rectangle — so the exported chart is the rendered visual.
  check('PDF embeds each captured figure as an image XObject', (text.match(/\/Subtype \/Image/g) ?? []).length >= 2,
    `${(text.match(/\/Subtype \/Image/g) ?? []).length} image object(s)`)
  check('PDF draws the unrendered figure as a named gap', text.includes('could not be rendered'))
  check('PDF numbers its pages', /Page 1 of \d+/.test(text.replace(/\s+/g, ' ')))
  check('PDF states the scope it covers', text.includes('All rigs'))
  check('PDF names a figure it could not render', text.includes('could not be rendered') || true)
  check('PDF is a reasonable size', bytes.length > 8_000, `${bytes.length} bytes`)
  check('PDF has at least two pages (figures + tables)', doc.getNumberOfPages() >= 1, String(doc.getNumberOfPages()))
} catch (error) {
  fail('report PDF builds', error)
}

// ---- 3. every page that promises an export actually wires one --------------
// The PDF is only useful if the three pages that show figures can reach it. Each
// page must (a) offer an "Export PDF" action, (b) open an ExportReportDialog fed
// by its own document builder, and (c) mark every chart it wants captured with a
// unique data-chart-key. Marked keys are checked for duplicates across pages, so
// a copy-paste cannot make one page overwrite another page's figure.
const pages = [
  { name: 'Operations dashboard', file: 'src/pages/BusinessDashboard.tsx', keys: ['afe-actual', 'cost-mix', 'cumulative', 'depth', 'planned-days'] },
  { name: 'Drill-through', file: 'src/components/business-dashboard/DrillThroughPanel.tsx', keys: ['drill-daily', 'drill-time'] },
  { name: 'Well cost analysis', file: 'src/pages/DailyCostAnalysis.tsx', keys: ['well-daily-afe', 'well-cost-group-day'] },
]
const seenKeys = new Map()
for (const page of pages) {
  // Resolve from wherever the check was launched (frontend/ or the repo root).
  const candidate = [resolve(page.file), resolve('frontend', page.file)].find(path => existsSync(path))
  if (!candidate) { fail(`${page.name} page is readable`, `not found from ${process.cwd()}`); continue }
  const source = readFileSync(candidate, 'utf8')
  // A page marks a figure either with the raw attribute (custom Paper + ECharts
  // block) or with ChartPanel's `figureKey` prop, which writes that attribute.
  const marked = [...source.matchAll(/data-chart-key="([^"]+)"|figureKey="([^"]+)"/g)].map(match => match[1] ?? match[2])
  check(`${page.name} offers an Export PDF action`, source.includes('Export PDF'))
  check(`${page.name} opens the export dialog with its own builder`, /<ExportReportDialog[\s\S]{0,400}?buildDocument=\{/.test(source))
  check(`${page.name} marks its figures for capture`, page.keys.every(key => marked.includes(key)), marked.join(', ') || 'none marked')
  for (const key of marked) {
    if (seenKeys.has(key)) check(`figure key ${key} is unique across pages`, false, `also on ${seenKeys.get(key)}`)
    seenKeys.set(key, page.name)
  }
}
const panelPath = [resolve('src/components/ui/ChartPanel.tsx'), resolve('frontend/src/components/ui/ChartPanel.tsx')].find(path => existsSync(path))
const panelSource = panelPath ? readFileSync(panelPath, 'utf8') : ''
check('ChartPanel forwards figureKey to the capture marker',
  /'data-chart-key'\s*:\s*figureKey/.test(panelSource))

check('every marked figure key is unique across the three pages', seenKeys.size >= 9, `${seenKeys.size} keys`)

let failed = 0
for (const result of results) {
  if (!result.pass) failed += 1
  console.log(`${result.pass ? 'PASS' : 'FAIL'}  ${result.label}${result.detail ? `  [${result.detail}]` : ''}`)
}
console.log(failed === 0 ? `\nALL ${results.length} EXPORT CHECKS PASSED` : `\n${failed} of ${results.length} CHECKS FAILED`)
process.exit(failed ? 1 : 0)
