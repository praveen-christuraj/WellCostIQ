# Exports: figures as shown, and matrices kept as matrices

Two exports are described here. Both answer the same question the screen already
answers; neither introduces a second way of computing a figure.

1. **Figure report (PDF)** — the numbers *and* the pictures, from the Operations
   dashboard, the Drill-In (drill-through) page and the Well Cost Analysis page.
2. **Matrix workbook (Excel)** — the well-wise usage and cost matrices as a real
   spreadsheet, keeping the header bands, sections, totals and grand total.

Every download is audited (`module`, `format`, row/page count, the filters it
covered) under the existing `daily-cost:export` capability. No new permission,
no new persistence and no new dependency is introduced.

---

## 1. Figure report (PDF)

**Where.** An **Export PDF** action sits in the page heading of the Operations
dashboard, in the footer of the drill-through dialog and beside *Print well
costing sheet* on the Well Cost Analysis page. It opens one dialog
(`components/ui/ExportReportDialog.tsx`) shared by all three, so the choices
cannot drift apart.

**What it asks.** The dialog lists the figures the page can capture, each
already ticked, plus two switches: *Visuals* and *Tables*. Turn a figure off and
it is absent from the report; leave it on and it is embedded. The orientation
follows the content (`landscape` for the wide tables, `portrait` otherwise).

**"Rendered the same manner" is literal.** Each figure is exported by the chart
that drew it (`InteractiveChart` → ECharts `getDataURL`, white background, 2×
pixel ratio) and embedded in the PDF as an image. The report never redraws a
chart from data, so the picture in the PDF is the picture on the page.

**A figure that cannot be captured is named, not dropped.** If a chart holds no
pixels (not yet drawn, or hidden by a filter), the report prints
*"&lt;figure title&gt; could not be rendered"* in its place. The reader always knows
whether a missing picture is missing content or missing rendering.

**What the page contributes.**

| Page | Figures | Tables |
| --- | --- | --- |
| Operations dashboard | AFE vs actual, cost mix, cumulative cost, depth progress, planned vs actual days | KPI tiles, cost-group and time-classification reconciliation, wells, AFE register, rig register, alerts |
| Drill-in (drill-through) | Daily cost by day, time classification | Well KPIs, cost groups, sections/depth, activities, AFE positions, daily sheets, notes |
| Well Cost Analysis | Daily vs AFE, cost by group and day | AFE position KPIs, per-AFE table, daily run sheet, budget reconciliation, warnings |

Adjustment columns (revised AFE amount, adjusted balance) appear only when an
approved SOW adjustment exists, so a report never shows an empty column.

**Layout rules that were measured, not assumed.** A multi-line notice block is
measured before it is drawn and the next heading is given a lead, so a notice's
last line cannot touch a heading. Every page is numbered *Page N of M* and its
footer repeats the report's scope (workspace, rig filter, period). Verification
renders the produced PDF to PNG and inspects it — reading the text stream alone
does not prove spacing (`make export-report-check`).

---

## 2. Matrix workbook (Excel)

**Where.** **Export matrix to Excel** in the heading of every matrix report:
mud chemicals usage, drill bits usage, tangibles usage, service-wise cost and
vendor/company-wise cost.

**The structure is the screen's structure.** The workbook is written by a
dedicated matrix writer (`lib/matrixWorkbook.ts`), not by a generic grid dump:

- **Band 1** merges each well across its hole sections.
- **Band 2** names each section under its well.
- **Band 3** labels *Qty* and *Cost* under each section.
- **One row per item**, its code and name, with its identifying detail
  (manufacturer · subcategory · detail · unit of measure) kept in its own column.
- **A Total row** and a **grand-total column**, written as numbers so Excel can
  sum them.
- **A `Detail` tab**: one row per recorded usage line — item, well, block, rig,
  scope, section, quantity, unit, cost — so a figure in the matrix can be traced
  to the sheet that recorded it.

Report-specific shape is preserved rather than flattened: cost-only reports
(service-wise, vendor-wise) drop the quantity column; tangibles add a category
band; drill bits keep make, model, size and IADC on the item line. Section order
is the well's own section order, matching the page.

**Sheet names are legal.** Excel forbids `/` in a sheet name, so *Vendor/company-wise
cost report* becomes *Vendor company-wise cost report*; nothing else is altered.

**Cells are safe.** An item name that begins like a formula (`=HYPERLINK(...)`)
is written as text, never as a formula, so an imported catalogue name cannot
execute in a reader.

The NPT/UPA report is not a matrix: it keeps the standard table export
(CSV / XLSX / PDF) of its detail grid.

---

## Verification

- `make export-report-check` — 62 checks: the matrix mapping and the written
  `.xlsx` read back from its ZIP (merged bands, numeric totals, hostile name
  neutralised) for **all five** matrix reports; the PDF's bytes, embedded image
  objects, named gaps, pagination and scope; and the wiring of all three pages
  (an export action, a dialog fed by that page's own builder, every figure key
  marked and **unique** across the pages, with `ChartPanel` forwarding
  `figureKey` to the capture marker).
- `make chart-drill-check` — 16 checks on the chart-to-drill-through contract
  (the defect that made one well's numbers appear under another's label).
- `make ui-check` — 47 theme, dialog and error-convention checks; the chart
  usage count stays at 16.
- `make daily-cost-date-check` — the corrected date is authoritative for
  duplicate detection and the vacated day can be re-created.
- Backend suite, `npx tsc -b`, `npm run build` and `npm run test:security`.

## Limits stated plainly

- The PDF is produced in the browser from the page's own pixels. A chart that
  has not been drawn (a tab never opened, a figure hidden by a filter) is
  reported as not rendered rather than recomputed on the server.
- Browser print pagination and physical printer output are a separate concern;
  the print sheets are unchanged by this work.
- A very wide matrix (many wells × many sections) produces a wide sheet by
  design — it is the same structure the page shows. Freeze panes on the item
  column are set so the labels stay visible while scrolling.
