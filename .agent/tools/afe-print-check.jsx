// AFE print regression check. Run after installing jsdom in frontend with --no-save:
// cd frontend && NODE_PATH="$PWD/node_modules" ./node_modules/.bin/esbuild \
// ../.agent/tools/afe-print-check.jsx --bundle --platform=node --format=esm --jsx=automatic \
// --outfile=node_modules/.cache/afe-print-check.mjs --external:jsdom && \
// node node_modules/.cache/afe-print-check.mjs
import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import { JSDOM } from 'jsdom'

const dom = new JSDOM('<html><body><div id="root"></div></body></html>', { url: 'http://localhost/' })
for (const key of ['window', 'document', 'navigator', 'HTMLElement', 'Event']) {
  Object.defineProperty(globalThis, key, { value: dom.window[key], configurable: true })
}
globalThis.IS_REACT_ACT_ENVIRONMENT = true

const { act } = await import('react')
const { createRoot } = await import('react-dom/client')
const { AfePrintSheet } = await import('../../frontend/src/components/afe/AfePrintSheet')

const estimate = {
  afe: {
    id: 'afe1', rig_id: 'rig1', rig_code: 'RIG-1', rig_name: 'Rig one', well_id: 'well1', well_code: 'WELL-1', well_name: 'Well one',
    well_status: 'active', afe_code: 'AFE-1', afe_name: 'Drilling estimate', afe_type: 'Drilling', configuration_scope: 'drilling', remarks: 'AFE notes',
    status: 'approval', status_remarks: 'Approved', status_changed_at: '2026-10-14T09:00:00Z', status_changed_by: 'Approver',
    estimate_saved_at: '2026-10-14T08:00:00Z', estimate_saved_by: 'Estimator', service_count: 1, consumable_count: 1, tangible_count: 1,
    services_total: '100', consumables_total: '20', tangibles_total: '30', total_cost: '150', standard_currency: 'USD', conversion_pending: false,
    totals_by_currency: [], warning_count: 0, is_deleted: false, deleted_at: null, created_at: '2026-10-14T07:00:00Z', updated_at: '2026-10-14T09:00:00Z',
  },
  well: {
    scope: 'drilling', well_id: 'well1', well_code: 'WELL-1', well_name: 'Well one', well_location: 'Field', block: 'Block A', objective: 'Production',
    rig_code: 'RIG-1', rig_name: 'Rig one', depth_unit: 'm', status: 'active', config_status: 'configured', total_depth: '1000.126', total_days: '10.126',
    sections: [{ hole_section_id: 'section1', section_code: 'SEC-1', section_name: 'Surface', from_depth: '0.125', to_depth: '1000.126', total_days: '10.126',
      phases: [{ phase_id: 'phase1', phase_code: 'DRILL', phase_name: 'Drilling', days: '10.126' }] }],
  },
  services: [{
    id: 'service-line1', client_key: null, service_id: 'service1', service_code: 'SVC-HIDE-ME', service_name: 'Mud logging', service_category: 'Drilling Services',
    provider_type: 'Third Party Services', vendor_name: 'Vendor one', charging_basis: 'Per Service Rate', hole_section_id: null, section_label: '', phase_id: null,
    phase_label: '', currency: 'USD', service_amount: '100', remarks: 'Service notes', rates: [], charges: [], section_rates: [], amount: '100', warnings: [], components: [],
  }],
  consumables: [{
    id: 'consumable1', client_key: null, category: 'Mud Chemicals', hole_section_id: 'section1', section_label: 'SEC-1 · Surface', phase_id: null, phase_label: '',
    drill_bit_id: null, bit_code: '', bit_name: '', bit_type: '', manufacturer: '', model_no: '', size: '', iadc_code: '', serial_number: '', bit_description: '',
    quantity: '1', captured_rate: '20', override_rate: null, effective_rate: '20', estimated_amount: '20', currency: 'USD', remarks: '', amount: '20', warnings: [], components: [],
  }],
  tangibles: [{
    id: 'tangible-line1', client_key: null, tangible_id: 'tangible1', tangible_code: 'TANG-KEEP', tangible_name: 'Casing', tangible_scope: 'Drilling',
    category_name: 'Tubulars', subcategory_name: 'Casing', manufacturer_name: 'Maker', tangible_description: '', uom: 'm', quantity: '1.126', captured_rate: '30',
    override_rate: null, effective_rate: '30', currency: 'USD', remarks: '', amount: '30', warnings: [], components: [],
  }],
  summary: {
    services_total: '100', consumables_total: '20', tangibles_total: '30', total: '150', totals_by_currency: [{ currency: 'USD', amount: '150' }],
    currency: { standard_currency: 'USD', currencies: ['USD'], multi_currency: false, converted: true, standard_missing: false, missing_rates: [], exchange_rates: [] },
    by_section: [], warnings: [],
  },
  status_history: [], persisted: true, saved_at: '2026-10-14T08:00:00Z', saved_by: 'Estimator',
}

const root = createRoot(document.getElementById('root'))
await act(async () => root.render(<AfePrintSheet estimate={estimate}/>))
const sheet = document.querySelector('.afe-cost-print-sheet')
assert.ok(sheet, 'AFE print sheet has its report-specific class')
// Print CSS hides `body > #root`, so the printable copy must be a body child;
// rendering it inline inside the application root printed a blank page.
assert.ok(document.body.querySelector(':scope > .afe-cost-print-sheet'),
  'the printable AFE sheet is a direct child of <body>, outside the application root that printing hides')
assert.equal(document.querySelector('#root .afe-cost-print-sheet'), null,
  'the printable AFE sheet never renders inside the hidden application root')
const pages = sheet.querySelectorAll(':scope > .ps-page')
assert.equal(pages.length, 2, 'report keeps its two explicit page groups')
assert.ok(pages[0].textContent.includes('Mud logging'), 'service name prints on page one')
assert.ok(!sheet.textContent.includes('SVC-HIDE-ME'), 'service code is omitted from the entire AFE report')
for (const code of ['RIG-1', 'WELL-1', 'AFE-1', 'SEC-1', 'DRILL', 'TANG-KEEP']) {
  assert.ok(!sheet.textContent.includes(code), `${code} is omitted in favour of its name`)
}
const firstPageCostTable = pages[0].querySelector('.ps-afe-cost-table')
assert.ok(firstPageCostTable, 'services, consumables and tangibles share one first-page table')
for (const category of ['Mud Chemicals', 'Cement Additives', 'Fuel', 'Drill Bits']) {
  assert.ok(firstPageCostTable.textContent.includes(category), `${category} has its own consumables lump-sum row`)
}
assert.ok(firstPageCostTable.textContent.includes('Total Consumables') && firstPageCostTable.textContent.includes('Tangibles lump sum'),
  'the unified table includes consumables and tangibles totals')
assert.ok(firstPageCostTable.textContent.includes('Total AFE amount'), 'the unified table ends with the total AFE amount')
assert.equal(sheet.querySelectorAll('.ps-grand').length, 1, 'the AFE grand total appears only in the unified first-page table')
assert.ok(pages[0].textContent.includes('Sections and depths') && !pages[1].textContent.includes('Sections and depths'), 'section detail follows the cost table on page one')
assert.ok(pages[1].textContent.includes('Casing'), 'tangible name remains visible without its code')
const tangibleTable = [...pages[1].querySelectorAll('table')].find(table => table.textContent.includes('Casing'))
assert.equal(tangibleTable.querySelector('tbody tr').cells[3].textContent, '1', 'tangible quantity is rounded to zero places')
assert.equal(tangibleTable.querySelector('tbody tr').cells[4].textContent, '$30', 'USD rate prints with a dollar symbol')
assert.ok(![...tangibleTable.querySelectorAll('thead th')].some(th => th.textContent === 'Ccy'), 'currency column is omitted')

assert.ok(pages[0].textContent.includes('1,000.13 m') && pages[0].textContent.includes('10.13 d') && pages[1].textContent.includes('1'), 'depths and days retain precision while quantities round to whole units')
assert.ok(!pages[0].textContent.includes('Authorisation') && pages[1].textContent.includes('Authorisation'), 'sign-off is kept with supporting detail')
assert.equal(pages[0].querySelector('h1').textContent, 'AFE Cost Estimate', 'the first-page title uses the requested short wording')
assert.equal(pages[1].querySelector('h1').textContent, 'AFE Cost Estimate', 'the supporting page repeats the requested short report title')
assert.equal(pages[0].querySelector('.ps-titlecode').textContent, 'Drilling - Drilling estimate - Rig one', 'the title block shows AFE type, AFE name and rig name')
assert.equal(pages[1].querySelector('.ps-titlecode').textContent, 'Drilling - Drilling estimate - Rig one', 'the supporting page repeats the full AFE identity')
const metadataLabels = [...pages[0].querySelectorAll('.ps-meta th')].map(cell => cell.textContent)
assert.deepEqual(metadataLabels, ['Rig', 'Well', 'Objective', 'Location / block', 'Depth', 'Planned days'],
  'metadata keeps only rig, well, objective, location/block, depth and planned days')
assert.ok(!metadataLabels.includes('AFE') && !metadataLabels.includes('AFE type'), 'AFE name and type are not duplicated in metadata')
for (const omitted of ['Configuration', 'Estimate saved', 'Well Plan', 'Status', 'Printed', 'AUTHORIZATION FOR EXPENDITURE']) {
  assert.ok(!pages[0].textContent.includes(omitted), `${omitted} is omitted from the first-page header and metadata`)
}
const originalMetadata = pages[0].querySelector('.ps-meta').outerHTML
const originalConsumables = [...pages[0].querySelectorAll('.ps-consumable-group-block .num')].map(node => node.textContent)
const originalTangibles = [...pages[0].querySelectorAll('.ps-tangible-group-block .num')].map(node => node.textContent)
const originalSectionPlan = pages[0].querySelector('.ps-section-plan').outerHTML
const originalSupportingPage = pages[1].outerHTML

const orderedEstimate = structuredClone(estimate)
orderedEstimate.services = [
  { ...estimate.services[0], id: 'service-line10', service_code: 'SVC-10', service_name: 'Later service' },
  { ...estimate.services[0], id: 'service-line2', service_code: 'SVC-2', service_name: 'Earlier service' },
]
await act(async () => root.render(<AfePrintSheet estimate={orderedEstimate}/>))
const orderedRows = document.querySelectorAll('.ps-afe-summary .ps-service-group-block tr.ps-line')
assert.deepEqual([...orderedRows].map(row => row.cells[1].querySelector('strong').textContent),
  ['Earlier service', 'Later service'], 'services print in natural service-code order')
assert.ok(!document.querySelector('.afe-cost-print-sheet').textContent.includes('SVC-2'), 'service codes remain hidden after ordering')

const groupedEstimate = structuredClone(orderedEstimate)
groupedEstimate.services = [
  { ...orderedEstimate.services[0], id: 'service-line2', service_code: 'SVC-2', service_name: 'Earlier service', service_group: 'Well Services' },
  { ...orderedEstimate.services[1], id: 'service-line10', service_code: 'SVC-10', service_name: 'Later service', service_group: 'Rig Operations' },
]
groupedEstimate.summary.services_total = '200'
groupedEstimate.summary.total = '250'
await act(async () => root.render(<AfePrintSheet estimate={groupedEstimate}/>))
const groupedRows = document.querySelectorAll('.ps-afe-summary .ps-service-group-block tr.ps-line')
assert.deepEqual([...groupedRows].map(row => row.cells[1].querySelector('strong').textContent),
  ['Later service', 'Earlier service'], 'service groups print before the natural service code')
const groupBlocks = [...document.querySelectorAll('.ps-afe-summary .ps-service-group-block')]
assert.deepEqual(groupBlocks.map(block => block.querySelector('.ps-service-group-heading th').textContent),
  ['Rig Operations', 'Well Services'], 'each group has its own heading, as in the model AFE')
assert.deepEqual(groupBlocks.map(block => block.querySelector('.ps-service-group-total th').textContent),
  ['Total Rig Operations', 'Total Well Services'], 'each group ends with its own labelled subtotal')
assert.deepEqual(groupBlocks.map(block => block.querySelector('.ps-service-group-total .num').textContent),
  ['$100', '$100'], 'group subtotals include only their own service lines')
assert.deepEqual(groupBlocks.map(block => [...block.rows].map(row => row.cells[0].textContent)),
  [['1.0', '1.1', ''], ['2.0', '2.1', '']], 'group and service numbering mirrors the model')
assert.ok(!document.querySelector('.ps-afe-summary .ps-line .ps-group'), 'group labels no longer run into service names')
assert.ok(groupBlocks.every(block => block.firstElementChild.classList.contains('ps-service-group-heading')
  && block.lastElementChild.classList.contains('ps-service-group-total')), 'each subtotal immediately follows its group lines')

const sectionEstimate = structuredClone(estimate)
sectionEstimate.services = [
  { ...estimate.services[0], charging_basis: 'Per Section Rate', currency: 'EUR', service_amount: '0', amount: '175',
    section_rates: [
      { hole_section_id: 'section1', section_label: 'SEC-1 · Surface', phase_id: 'phase1', phase_label: 'DRILL · Drilling', amount: '75' },
      { hole_section_id: 'section2', section_label: 'SEC-2 · Intermediate', phase_id: null, phase_label: '', amount: '100' },
    ] },
  { ...estimate.services[0], id: 'day-rate', charging_basis: 'Day Rate', hole_section_id: 'section1', section_label: 'SEC-1 · Surface',
    phase_id: 'phase1', phase_label: 'DRILL · Drilling', currency: 'USD', amount: '80',
    rates: [{ category: 'Operation', unit_rate: '40' }], charges: [{ category: 'Operation', quantity: '2.126', quantity_unit: 'days' }] },
  { ...estimate.services[0], id: 'fixed-rate', section_label: 'SEC-1 · Surface', phase_label: 'DRILL · Drilling' },
]
await act(async () => root.render(<AfePrintSheet estimate={sectionEstimate}/>))
const servicesTable = document.querySelector('.ps-afe-summary .ps-table')
assert.deepEqual([...servicesTable.querySelectorAll('thead th')].map(cell => cell.textContent),
  ['#', 'Service', 'Basis / entered rates', 'Amount in USD', 'Remarks'], 'the first-page schedule has five columns without Scope or Currency')
assert.equal(servicesTable.querySelectorAll('colgroup col').length, 5, 'column widths match the five headers')
const serviceRows = servicesTable.querySelectorAll('.ps-service-group-block tr.ps-line')
assert.equal(serviceRows[0].cells.length, 5, 'section-rate row has no extra scope or currency cells')
assert.ok(serviceRows[0].cells[2].textContent.includes('Surface · Drilling: EUR 75'), 'first section and phase names show their entered rate')
assert.ok(serviceRows[0].cells[2].textContent.includes('Intermediate: EUR 100'), 'second section name and rate show separately')
assert.equal(serviceRows[0].cells[3].textContent, 'EUR 175', 'service amount still identifies its entered currency')
assert.ok(serviceRows[1].cells[2].textContent.includes('Operation $40 × 2 days'), 'day rates retain currency and whole-unit quantity')
assert.ok(serviceRows[1].cells[2].textContent.includes('Surface · Drilling'), 'scoped day rates retain section and phase names in Basis')
assert.ok(serviceRows[2].cells[2].textContent.includes('Fixed $100'), 'fixed rates retain their currency')
assert.equal(servicesTable.querySelector('.ps-services-total').cells[0].colSpan, 3, 'services total spans the remaining label columns')

// A Day Rate service configured once for the whole well prints once, with one
// detail row per section and phase; its amount already sums every section.
const scopedEstimate = structuredClone(estimate)
scopedEstimate.services = [{
  ...estimate.services[0], id: 'scoped-day-rate', client_key: 'scoped-day-rate', charging_basis: 'Day Rate',
  hole_section_id: null, section_label: '', phase_id: null, phase_label: '', currency: 'USD', service_amount: '0',
  amount: '72000', rates: [], charges: [], section_rates: [],
  scope_rates: [
    { hole_section_id: 'section1', section_label: 'SEC-1 · Surface', phase_id: null, phase_label: '', category: 'Operation', unit_rate: '1000' },
    { hole_section_id: 'section2', section_label: 'SEC-2 · Intermediate', phase_id: 'phase1', phase_label: 'DRILL · Drilling', category: 'Operation', unit_rate: '1100' },
  ],
  scope_days: [
    { hole_section_id: 'section2', section_label: 'SEC-2 · Intermediate', phase_id: 'phase1', phase_label: 'DRILL · Drilling', category: 'Operation', quantity: '48', quantity_unit: 'hours' },
  ],
}]
scopedEstimate.summary.services_total = '72000'
scopedEstimate.summary.total = '72050'
await act(async () => root.render(<AfePrintSheet estimate={scopedEstimate}/>))
const scopedRowsAfter = document.querySelectorAll('.ps-afe-summary .ps-service-group-block tr.ps-line')
assert.equal(scopedRowsAfter.length, 1, 'a service priced on several sections still prints as one service row')
assert.equal(scopedRowsAfter[0].cells[3].textContent, '$72,000', 'the single row carries the sum of every section amount')
assert.ok(scopedRowsAfter[0].cells[2].textContent.includes('Surface: Operation $1,000'), 'the first section keeps its own rate')
assert.ok(scopedRowsAfter[0].cells[2].textContent.includes('Intermediate · Drilling: Operation $1,100'),
  'the phase-scoped rate prints under its section')
assert.ok(scopedRowsAfter[0].cells[2].textContent.includes('× 48 hours'), 'the entered scope days print with the rate')
assert.equal(new Set([...scopedRowsAfter].map(row => row.cells[1].querySelector('strong').textContent)).size, 1,
  'the service is never duplicated per section')

const allGroupsEstimate = structuredClone(estimate)
allGroupsEstimate.services = [
  ['Well Services', 'WELL-1', '30'],
  ['Supervisions', 'SUP-1', '20'],
  ['Rig Operations', 'RIG-10', '8'],
  ['Miscellaneous Services', 'MISC-1', '5'],
  ['Formation Evaluation', 'FE-1', '20'],
  ['Land Facilities and Preparation', 'LAND-1', '15'],
  ['Rig Operations', 'RIG-2', '2'],
].map(([service_group, service_code, amount]) => ({
  ...estimate.services[0], id: service_code, service_group, service_code, service_name: `${service_code} name`, amount, service_amount: amount,
}))
const sourceServices = JSON.stringify(allGroupsEstimate.services)
await act(async () => root.render(<AfePrintSheet estimate={allGroupsEstimate}/>))
const allBlocks = [...document.querySelectorAll('.ps-service-group-block')]
assert.deepEqual(allBlocks.map(block => block.querySelector('.ps-service-group-heading th').textContent), [
  'Rig Operations', 'Formation Evaluation', 'Well Services', 'Land Facilities and Preparation', 'Miscellaneous Services', 'Supervisions',
], 'all six existing categories retain their canonical report order')
assert.deepEqual([...allBlocks[0].querySelectorAll('.ps-line strong')].map(node => node.textContent),
  ['RIG-2 name', 'RIG-10 name'], 'natural service order is preserved inside a group')
assert.deepEqual(allBlocks.map(block => block.querySelector('.ps-service-group-total .num').textContent),
  ['$10', '$20', '$30', '$15', '$5', '$20'], 'repeated service lines contribute to just one subtotal per group')
assert.equal(JSON.stringify(allGroupsEstimate.services), sourceServices, 'printing never mutates saved services or grouping assignments')
assert.equal(document.querySelector('.ps-afe-summary .ps-meta').outerHTML, originalMetadata, 'well and AFE metadata are unchanged')
assert.deepEqual([...document.querySelectorAll('.ps-consumable-group-block .num')].map(node => node.textContent), originalConsumables,
  'consumables amounts are unchanged by service grouping')
assert.deepEqual([...document.querySelectorAll('.ps-tangible-group-block .num')].map(node => node.textContent), originalTangibles,
  'tangibles amounts are unchanged by service grouping')
assert.equal(document.querySelector('.ps-section-plan').outerHTML, originalSectionPlan, 'the first-page section plan is unchanged by service grouping')
assert.equal(document.querySelectorAll('.afe-cost-print-sheet > .ps-page')[1].outerHTML, originalSupportingPage,
  'the entire supporting-detail page, warnings and sign-off remain unchanged')
assert.equal(document.querySelector('.ps-services-total .num').textContent, '$100',
  'the existing Services total is retained after all group subtotals')

const convertedEstimate = structuredClone(estimate)
convertedEstimate.services = [
  { ...estimate.services[0], id: 'usd', service_group: 'Rig Operations', amount: '10.125', currency: 'USD' },
  { ...estimate.services[0], id: 'eur', service_group: 'Rig Operations', amount: '20.5', currency: 'EUR' },
  { ...estimate.services[0], id: 'gbp', service_group: 'Well Services', amount: '30', currency: 'GBP' },
]
convertedEstimate.summary.services_total = '79.725'
convertedEstimate.summary.total = '129.725'
convertedEstimate.summary.currency = {
  standard_currency: 'USD', currencies: ['USD', 'EUR', 'GBP'], multi_currency: true, converted: true,
  standard_missing: false, missing_rates: [], exchange_rates: [{ currency_code: 'EUR', rate: '1.2' }, { currency_code: 'GBP', rate: '1.5' }],
}
await act(async () => root.render(<AfePrintSheet estimate={convertedEstimate}/>))
assert.deepEqual([...document.querySelectorAll('.ps-service-group-block .ps-service-group-total .num')].map(node => node.textContent),
  ['$35', '$45'], 'mixed-currency group subtotals use saved FX rates and round only for display')
assert.equal(document.querySelector('.ps-services-total .num').textContent, '$80',
  'mixed-currency group amounts reconcile to the unchanged Services total')
assert.deepEqual([...document.querySelectorAll('.ps-afe-summary .ps-service-group-block .ps-line td.num')].map(node => node.textContent),
  ['$10', 'EUR 21', 'GBP 30'], 'entered-currency line amounts remain unchanged')

const componentEstimate = structuredClone(convertedEstimate)
componentEstimate.services = [{
  ...convertedEstimate.services[1], amount: '0.0041666666',
  components: [{ amount: '0.0020833333' }, { amount: '0.0020833333' }],
}]
componentEstimate.summary.services_total = '0.0050000000'
await act(async () => root.render(<AfePrintSheet estimate={componentEstimate}/>))
assert.equal(document.querySelector('.ps-service-group-total .num').textContent, '$0',
  'component-by-component ten-place half-up conversion matches the existing backend summary at a rounding boundary')

const precisionEstimate = structuredClone(estimate)
precisionEstimate.services = ['0.0024999999', '0.0025'].map((amount, index) => ({
  ...estimate.services[0], id: `precision-${index}`, service_group: 'Rig Operations', amount,
}))
await act(async () => root.render(<AfePrintSheet estimate={precisionEstimate}/>))
assert.equal(document.querySelector('.ps-service-group-total .num').textContent, '$0', 'subtotals retain ten-place precision rather than rounding each line to cents')
precisionEstimate.services[0].amount = '0.0025'
await act(async () => root.render(<AfePrintSheet estimate={precisionEstimate}/>))
assert.equal(document.querySelector('.ps-service-group-total .num').textContent, '$0', 'the final subtotal rounds to whole units')

const pendingEstimate = structuredClone(convertedEstimate)
pendingEstimate.summary.currency.converted = false
pendingEstimate.summary.currency.missing_rates = ['EUR']
pendingEstimate.summary.currency.exchange_rates = [{ currency_code: 'GBP', rate: '1.5' }]
pendingEstimate.summary.services_total = null
await act(async () => root.render(<AfePrintSheet estimate={pendingEstimate}/>))
assert.deepEqual([...document.querySelectorAll('.ps-service-group-block .ps-service-group-total .num')].map(node => node.textContent),
  ['Pending conversion', 'Pending conversion'], 'incomplete conversion withholds every group subtotal like the existing estimate totals')
pendingEstimate.summary.currency.standard_currency = ''
pendingEstimate.summary.currency.standard_missing = true
await act(async () => root.render(<AfePrintSheet estimate={pendingEstimate}/>))
assert.ok([...document.querySelectorAll('.ps-service-group-block .ps-service-group-total th')].every(cell => !cell.textContent.includes('(')),
  'a missing standard currency never prints a misleading currency label')
assert.ok([...document.querySelectorAll('.ps-service-group-block .ps-service-group-total .num')].every(node => node.textContent === 'Pending conversion'),
  'a missing standard currency never adds unlike currencies')

const euroEstimate = structuredClone(estimate)
euroEstimate.services = [{ ...estimate.services[0], service_group: 'Formation Evaluation', currency: 'EUR', amount: '100.125' }]
euroEstimate.summary.currency = {
  ...estimate.summary.currency, standard_currency: 'EUR', currencies: ['EUR'], exchange_rates: [],
}
await act(async () => root.render(<AfePrintSheet estimate={euroEstimate}/>))
assert.equal(document.querySelector('.ps-service-group-total .num').textContent, 'EUR 100',
  'a single non-USD currency remains its own standard without an FX rate')
euroEstimate.services[0].amount = '0.0000000000'
await act(async () => root.render(<AfePrintSheet estimate={euroEstimate}/>))
assert.equal(document.querySelector('.ps-service-group-total .num').textContent, 'EUR 0', 'zero-cost service groups still print a zero subtotal')

const legacyEstimate = structuredClone(estimate)
legacyEstimate.services = [
  { ...estimate.services[0], id: 'missing-group', service_group: undefined, amount: '40' },
  { ...estimate.services[0], id: 'empty-group', service_group: '', amount: '60' },
]
await act(async () => root.render(<AfePrintSheet estimate={legacyEstimate}/>))
assert.equal(document.querySelectorAll('.ps-service-group-block').length, 1, 'legacy missing and empty groups still form one block')
assert.equal(document.querySelector('.ps-service-group-heading th').textContent, 'Unclassified services', 'unclassified service lines remain visible without recategorization')
assert.equal(document.querySelector('.ps-service-group-total .num').textContent, '$100', 'legacy unclassified lines are still included in a subtotal')

const emptyEstimate = structuredClone(estimate)
emptyEstimate.services = []
await act(async () => root.render(<AfePrintSheet estimate={emptyEstimate}/>))
assert.equal(document.querySelectorAll('.ps-service-group-block').length, 0, 'empty categories never add phantom headings or subtotals')
assert.ok(document.querySelector('.ps-services-empty .ps-empty').textContent.includes('No service lines.'), 'an empty estimate keeps its existing message')

const longSchedule = structuredClone(sectionEstimate)
longSchedule.services = Array.from({ length: 8 }, (_, index) => ({ ...sectionEstimate.services[0], id: `section-line-${index}` }))
await act(async () => root.render(<AfePrintSheet estimate={longSchedule}/>))
assert.ok(document.querySelector('.ps-afe-summary.ps-afe-dense'), 'multiple section rates trigger compact layout before service count alone would')

const styles = readFileSync('../frontend/src/styles.css', 'utf8')
assert.ok(styles.includes('.afe-cost-print-sheet th,') && styles.includes('overflow-wrap: anywhere'), 'AFE cells have scoped wrapping rules')
assert.ok(styles.includes('.afe-cost-print-sheet .ps-afe-dense'), 'large service schedules receive the compact density step')
assert.ok(styles.includes('.afe-cost-print-sheet .ps-service-group-heading { font-weight: 800; break-after: avoid; }'),
  'AFE-only group headings stay with the following service when printing')
assert.ok(styles.includes('.afe-cost-print-sheet .ps-service-group-total { break-before: avoid; }'),
  'AFE-only group subtotals stay with their preceding service when printing')

// The viewer's preview stays inline on its paper surface; only the print copy is portalled.
const previewHost = document.createElement('div')
document.body.appendChild(previewHost)
const previewRoot = createRoot(previewHost)
await act(async () => previewRoot.render(<AfePrintSheet estimate={estimate} preview/>))
assert.ok(previewHost.querySelector(':scope > .afe-cost-print-sheet'), 'the report preview renders inline inside the viewer')
assert.equal(document.body.querySelectorAll(':scope > .afe-cost-print-sheet').length, 1,
  'the preview does not add a second document-level print copy')
await act(async () => previewRoot.unmount())
previewHost.remove()

await act(async () => root.unmount())
dom.window.close()
console.log('AFE print checks passed: full title identity, compact metadata, unified categorized cost table and section plan; service ordering, group totals, saved FX, entered rates, compact layout and the body-portalled print copy.')
process.exit(0)
