// Verification check for Items 1, 3, 4, 7 & 8 enhancements:
//  - Item 1: Unbudgeted tangibles exact name + plain (unbudgeted) + page-1 listing
//  - Item 3: Assistant AnswerCard structured table rendering
//  - Item 4: Actual / AFE % helper accuracy
//  - Item 7: Print chart option transformation (paper-white, dark ink, non-overlapping data labels)
//  - Item 8: Consolidated 7-report Well/Scope PDF Bundle generation (Drilling, Completion, Both)
import { JSDOM } from 'jsdom'
import React, { act } from 'react'
import { createRoot } from 'react-dom/client'
import { MemoryRouter } from 'react-router-dom'
import * as echarts from 'echarts/core'
import { BarChart, LineChart, PieChart } from 'echarts/charts'
import { GridComponent, LegendComponent, TooltipComponent } from 'echarts/components'
import { SVGRenderer } from 'echarts/renderers'

echarts.use([BarChart, LineChart, PieChart, GridComponent, LegendComponent, TooltipComponent, SVGRenderer])

globalThis.IS_REACT_ACT_ENVIRONMENT = true
const dom = new JSDOM('<!doctype html><html><body><div id="root"></div></body></html>')
globalThis.window = dom.window
globalThis.document = dom.window.document
globalThis.HTMLElement = dom.window.HTMLElement
globalThis.SVGElement = dom.window.SVGElement
globalThis.Node = dom.window.Node
globalThis.XMLSerializer = dom.window.XMLSerializer

const results = []
const check = (label, pass, detail = '') => results.push({ label, pass: !!pass, detail })

// 1. Item 4: actualVsAfePercent
const { actualVsAfePercent } = await import('../../frontend/src/lib/businessDashboard')
check('Actual / AFE % computes (Actual / AFE) * 100', actualVsAfePercent(750_000, 1_000_000) === '75.0%', actualVsAfePercent(750_000, 1_000_000))
check('Actual / AFE % handles over-budget (>100%)', actualVsAfePercent(1_125_000, 1_000_000) === '112.5%', actualVsAfePercent(1_125_000, 1_000_000))
check('Actual / AFE % returns dash when AFE is zero/null', actualVsAfePercent(500, 0) === '—' && actualVsAfePercent(500, null) === '—')

// 2. Item 3: Assistant AnswerCard renders structured tables
const { AnswerCard } = await import('../../frontend/src/components/assistant/AnswerCard')
const mount = document.getElementById('root')
const root = createRoot(mount)
await act(async () => {
  root.render(
    React.createElement(MemoryRouter, null,
      React.createElement(AnswerCard, {
        answer: {
          answer: 'Found 2 matching catalogue items for Barite.',
          intent: 'price_lookup',
          confidence: 'high',
          category: 'data-entry',
          memory_key: '',
          facts: [{ label: 'Matches', value: '2', hint: 'Active catalogue items', route: '/catalogue', permission: 'catalogue:read' }],
          tables: [{
            title: 'Catalogue rates',
            columns: ['Item', 'UOM', 'Rate'],
            rows: [['Barite 4.2 SG', 'MT', 'USD 245.00'], ['Barite Bulk', 'MT', 'USD 210.00']],
            numeric: [2],
            footer: 'Showing active effective rates.',
          }],
          steps: [],
          sources: [{ label: 'Catalogue', route: '/catalogue' }],
          follow_ups: [],
        },
      }),
    ),
  )
})
const cardHtml = mount.innerHTML
root.unmount()
check('AnswerCard renders live data tag for price_lookup', cardHtml.includes('Live data'))
check('AnswerCard renders structured table headers and rows', cardHtml.includes('Catalogue rates') && cardHtml.includes('Barite 4.2 SG') && cardHtml.includes('USD 245.00'))
check('AnswerCard renders table footer', cardHtml.includes('Showing active effective rates.'))

// 3. Item 7: preparePrintChartOption + SSR SVG verification
const { preparePrintChartOption, formatPrintMetric } = await import('../../frontend/src/lib/chartExport')
check('formatPrintMetric compacts millions and thousands cleanly',
  formatPrintMetric(1_250_000) === '1.25M' && formatPrintMetric(45_200) === '45.2k' && formatPrintMetric(0) === '')

const darkStackedOption = {
  backgroundColor: '#0E1726',
  legend: { textStyle: { color: '#CBD5E1' } },
  xAxis: { type: 'category', data: ['Day 1', 'Day 2', 'Day 3'], axisLabel: { color: '#E2E8F0' } },
  yAxis: { type: 'value', axisLabel: { color: '#E2E8F0' } },
  series: [
    { name: 'Daily operational', type: 'bar', stack: 'daily', data: [50_000, 52_000, 48_000] },
    { name: 'Tangibles (lump-sum)', type: 'bar', stack: 'daily', data: [0, 0, 320_000] },
  ],
}
const printOpt = preparePrintChartOption(darkStackedOption, { includeDataLabels: true })
check('preparePrintChartOption forces paper-white background', printOpt.backgroundColor === '#FFFFFF')
check('preparePrintChartOption forces dark ink on axes', printOpt.xAxis.axisLabel.color === '#16283F' && printOpt.yAxis.axisLabel.color === '#16283F')
check('preparePrintChartOption enables non-overlapping stack total labels on top series',
  printOpt.series[1].label?.show === true && printOpt.series[1].labelLayout?.hideOverlap === true)

// Render real offscreen SVG via ECharts SSR and verify data label text appears in SVG.
const chart = echarts.init(null, null, { renderer: 'svg', ssr: true, width: 820, height: 360 })
chart.setOption(printOpt)
const svgOut = chart.renderToSVGString()
chart.dispose()
check('ECharts SSR SVG includes stacked total data labels (50.0k, 52.0k, 368.0k)',
  svgOut.includes('50.0k') && svgOut.includes('52.0k') && svgOut.includes('368.0k'),
  svgOut.slice(0, 120))

// 4. Item 8: Consolidated 7-report Well/Scope PDF Bundle
const { buildWellBundleDocument } = await import('../../frontend/src/lib/wellBundlePdf')
const { buildReportPdf } = await import('../../frontend/src/lib/reportPdf')

const sampleBundleData = {
  well: {
    id: 'w-1', rig_id: 'r-1', rig_code: 'RIG-01', rig_name: 'Atlas Rig 1',
    well_code: 'WELL-101', well_name: 'Deep Horizon Alpha', display_name: 'WELL-101 · Deep Horizon Alpha',
    status: 'active', config_status: 'configured', completion_status: 'active', completion_config_status: 'configured',
    sections: [], completion_sections: [],
  },
  scope: 'drilling',
  dateFrom: '2026-10-01',
  dateTo: '2026-10-20',
  includeDraft: true,
  estimates: [{
    afe: {
      configuration_scope: 'drilling', id: 'afe-1', rig_id: 'r-1', rig_code: 'RIG-01', rig_name: 'Atlas Rig 1',
      well_id: 'w-1', well_code: 'WELL-101', well_name: 'Deep Horizon Alpha', well_status: 'active',
      afe_code: 'AFE-DRL-01', afe_name: 'Drilling AFE', afe_type: 'Drilling', remarks: '',
      status: 'approval', status_remarks: '', status_changed_at: null, status_changed_by: '',
      estimate_saved_at: null, estimate_saved_by: '', service_count: 1, consumable_count: 1, tangible_count: 1,
      services_total: '600000', consumables_total: '200000', tangibles_total: '200000', total_cost: '1000000',
      standard_currency: 'USD', conversion_pending: false, totals_by_currency: [], warning_count: 0,
      is_deleted: false, deleted_at: null, created_at: '', updated_at: '',
      adjusted_services_total: null, adjusted_consumables_total: null, adjusted_tangibles_total: null,
      adjusted_total: null, has_sow_adjustment: false, sow_revision: null,
    },
    well: {
      scope: 'drilling', well_id: 'w-1', well_code: 'WELL-101', well_name: 'Deep Horizon Alpha',
      well_location: '', block: '', objective: '', rig_code: 'RIG-01', rig_name: 'Atlas Rig 1',
      depth_unit: 'm', status: 'active', config_status: 'configured', total_depth: '3200', total_days: '20', sections: [],
    },
    services: [{
      id: 's1', client_key: null, service_id: 'sv1', service_code: 'RIG-DAY', service_name: 'Rig Day Rate',
      service_category: 'Rig', service_group: 'Rig Services', provider_type: 'Vendor', vendor_name: 'Atlas Drilling',
      charging_basis: 'Day Rate', hole_section_id: null, section_label: '', phase_id: null, phase_label: '',
      currency: 'USD', service_amount: '600000', remarks: '', rates: [], charges: [], section_rates: [],
      scope_rates: [], scope_days: [], scopes: [], amount: '600000', warnings: [], components: [],
    }],
    consumables: [],
    tangibles: [],
    summary: {
      services_total: '600000', consumables_total: '200000', tangibles_total: '200000', total: '1000000',
      totals_by_currency: [], currency: { standard_currency: 'USD', currencies: ['USD'], multi_currency: false, converted: true, standard_missing: false, missing_rates: [], exchange_rates: [] },
      by_section: [{ hole_section_id: 'hs1', label: '12-1/4" Intermediate', planned_days: '10', services: '300000', consumables: '100000', tangibles: '100000', total: '500000' }],
      warnings: [],
    },
    status_history: [], persisted: true, saved_at: null, saved_by: '',
  }],
  summary: {
    well: { id: 'w-1', well_code: 'WELL-101', well_name: 'Deep Horizon Alpha', rig_code: 'RIG-01', rig_name: 'Atlas Rig 1', status: 'active', config_status: 'configured', afes: [] },
    from_date: '2026-10-01', to_date: '2026-10-20', as_of: '2026-10-20', include_draft: true,
    totals: {
      currency: 'USD', planned: '1000000', actual: '780000', balance: '220000', used_percent: '78.0',
      services: '480000', consumables: '100000', tangibles: '180000', other_expenses: '20000', upa: '15000', npt: '25000',
      planned_days: '20', recorded_days: 10, elapsed_days: 10, average_per_day: '78000', days_to_budget: '3',
      first_day: '2026-10-01', last_day: '2026-10-10', sheets: 10, draft_sheets: 2, submitted_sheets: 8, lines: 30,
      adjusted_planned: null, adjusted_balance: null, adjusted_used_percent: null, adjusted_planned_days: null, has_adjustment: false,
      spud_actual_days: '10.000', spud_days_variance: '-10.000',
      actual_mud_chemicals: '100000', reconciled_mud_cost: '95000', comparison_mud_cost: '95000', mud_cost_adjustment: '-5000',
      comparison_actual: '775000', comparison_consumables: '95000', comparison_balance: '225000', comparison_used_percent: '77.5',
      comparison_adjusted_balance: null, has_mud_reconciliation: true, lih_cost: '35000', actual_including_lih: '815000',
    },
    afes: [],
    daily: [
      { cost_date: '2026-10-01', services: '50000', consumables: '10000', tangibles: '0', other_expenses: '0', total: '60000', upa: '0', npt: '0', cumulative: '60000', budget_balance: '940000' },
      { cost_date: '2026-10-10', services: '48000', consumables: '10000', tangibles: '180000', other_expenses: '20000', total: '258000', upa: '15000', npt: '25000', cumulative: '780000', budget_balance: '220000' },
    ],
    factors: [{
      dimension: 'cost_group', label: 'Cost Group', currency: 'USD', total: '780000',
      rows: [
        { code: 'Services', name: 'Services', detail: '', planned: '600000', amount: '480000', balance: '120000', share: '61.5' },
        { code: 'Consumables', name: 'Consumables', detail: '', planned: '200000', amount: '100000', balance: '100000', share: '12.8' },
        { code: 'Tangibles', name: 'Tangibles', detail: '', planned: '200000', amount: '180000', balance: '20000', share: '23.1' },
      ],
    }],
    budget_lines: [
      { budget_key: 'unplanned-t1', cost_group: 'Tangibles', budget_kind: 'tangible', item_code: 'CSG-958', item_name: '9-5/8" L80 Casing Pup Joint', planned: '0', actual_to_date: '45000', balance: '-45000', is_planned: false },
    ],
    warnings: [], progress: [], mud_cost: null, lih_cost: null,
  },
  days: [],
  drill: {
    well: {
      well_id: 'w-1', well_code: 'WELL-101', well_name: 'Deep Horizon Alpha', well_location: '', block: '', status: 'active',
      config_status: 'configured', depth_unit: 'm', rig_id: 'r-1', rig_code: 'RIG-01', rig_name: 'Atlas Rig 1',
      drilling_planned_days: '20', completion_planned_days: '10', planned_days: '20',
      drilling_plan_adjusted: false, completion_plan_adjusted: false, section_count: 1,
      planned_depth: '3200', actual_depth: '2150', depth_progress_percent: '67.2',
      afe_count: 1, drilling_afe_count: 1, completion_afe_count: 0,
      afe_amount: '1000000', sow_adjusted_amount: null, has_sow_adjustment: false, effective_afe_amount: '1000000',
      afe_balance: '220000', utilisation_percent: '78.0', over_budget: false, actual_amount: '780000',
      services_amount: '480000', consumables_amount: '100000', tangibles_amount: '180000', other_expenses_amount: '20000',
      npt_amount: '25000', upa_amount: '15000', first_cost_date: '2026-10-01', last_cost_date: '2026-10-10',
      actual_days: '10.000', actual_days_basis: 'spud', recorded_days: 10, sheets: 10, draft_sheets: 2,
      npt_days: '1.250', upa_days: '0.500', currency: 'USD',
    },
    afes: [],
    daily: [{ cost_date: '2026-10-10', actual: '258000', operational: '78000', tangibles: '180000', cumulative: '780000', npt: '25000', upa: '15000', sheets: 1 }],
    sheets: [], classification: [], cost_groups: [], activities: [],
    sections: [{ hole_section_id: 'hs1', section_code: '12-1/4', section_name: 'Intermediate', scope: 'drilling', from_depth: '500', to_depth: '2200', planned_days: '10', active_days: 8, amount: '500000', share: '64.1', reached: true, planned_phase_count: 3 }],
    notes: [],
  },
  lih: {
    well_id: 'w-1', well_code: 'WELL-101', well_name: 'Deep Horizon Alpha', from_date: '2026-10-01', to_date: '2026-10-20',
    currency: 'USD', total: '35000', line_count: 1, entry_count: 1, totals: [],
    days: [{
      entry: { id: 'lih1', rig_id: 'r-1', rig_code: 'RIG-01', rig_name: 'Atlas Rig 1', well_id: 'w-1', well_code: 'WELL-101', well_name: 'Deep Horizon Alpha', afe_id: 'afe-1', afe_code: 'AFE-DRL-01', afe_name: 'Drilling AFE', cost_date: '2026-10-08', currency: 'USD', remarks: '', line_count: 1, total_cost: '35000', revision: 1, display_name: '', is_deleted: false, deleted_at: null, created_by: '', updated_by: '', created_at: '', updated_at: '' },
      lines: [{ id: 'l1', item_description: '8-1/2" PDC Bit', od_size: '8.5', id_size: null, fish_neck_od: null, fish_neck_length: null, serial_number: 'SN-88', connection: '4-1/2 REG', length: '0.4', no_of_units: '1', unit: 'EA', unit_cost: '35000', total_cost: '35000', remarks: 'Twisted off', source: 'manual', sort_order: 1, created_at: '', updated_at: '' }],
    }],
  },
  ndt: [{
    id: 'ndt1', rig_id: 'r-1', rig_code: 'RIG-01', rig_name: 'Atlas Rig 1', well_id: 'w-1', well_code: 'WELL-101', well_name: 'Deep Horizon Alpha',
    scope: 'drilling', description: '5" Drill Pipe MPI Inspection', quantity_received: '120', quantity_consumed: '115',
    quantity_backloaded_good: '110', quantity_backloaded_bad: '5', remarks: '5 joints rejected',
    is_deleted: false, deleted_at: null, created_by: '', updated_by: '', created_at: '', updated_at: '',
  }],
  mudBalance: {
    view: 'inception', from_date: null, to_date: '2026-10-20', selected_section_count: 1, entry_count: 5,
    rows: [{
      id: 'mb1', rig_id: 'r-1', rig_code: 'RIG-01', well_id: 'w-1', well_code: 'WELL-101', section_id: 'sec-1',
      section_scope: 'drilling', section_code: '12-1/4', section_name: 'Intermediate', section_label: '12-1/4 · Intermediate',
      period_label: 'Inception', cost_date: '2026-10-10', first_entry_date: '2026-10-01', last_entry_date: '2026-10-10', entry_count: 5,
      opening_stock: '500', receipt: '100', additions: '400', consumption_losses: '250', others: '20', closing_stock: '730',
    }],
  },
  mudReconciliation: {
    from_date: '2026-10-01', to_date: '2026-10-20', currency: 'USD', selected_section_count: 1, configured_section_count: 1,
    unconfigured_section_count: 0, entry_count: 5, latest_cost_per_bbl: '95.00', latest_cost_per_bbl_section: '12-1/4 · Intermediate',
    latest_cost_per_bbl_date: '2026-10-10', total_actual_cost: '100000', total_reconciled_cost: '95000', total_adjustment: '-5000',
    total_consumption_losses: '250', total_planned_cost: '120000',
    sections: [{
      section_id: 'sec-1', hole_section_id: 'hs1', rig_id: 'r-1', rig_code: 'RIG-01', well_id: 'w-1', well_code: 'WELL-101',
      section_scope: 'drilling', section_code: '12-1/4', section_name: 'Intermediate', section_label: '12-1/4 · Intermediate',
      mud_type: 'OBM', mud_type_label: 'Oil Based Mud', remarks: '', is_configured: true, is_current: true, is_wbm: false,
      currency: 'USD', base_rate: '90', opening_stock: '500', first_date: '2026-10-01', last_date: '2026-10-10', entry_count: 5,
      additions: '400', extra_obm_received: '100', actual_cost: '100000', planned_cost: '120000', total_mud: '1000',
      alpha: '100', beta: '0.95', consumption_losses: '250', cost_per_bbl: '95.00', reconciled_cost: '95000', adjustment: '-5000',
      verti_g_mud_on_cuttings: '80', centrifuge: '20', by_pass: '10', evaporation: '5', trips: '15', surface_loss_total: '130',
      mud_cleaner: '10', formation_seepage: '60', pit_cleaning_dump: '20', left_in_hole: '20', other_losses: '10', other_loss_total: '120', total_losses: '250',
    }],
    rows: [],
  },
  mudLosses: {
    view: 'section', from_date: '2026-10-01', to_date: '2026-10-20', selected_section_count: 1, entry_count: 5,
    surface_loss_total: '130', other_loss_total: '120', total_losses: '250',
    rows: [{
      id: 'ml1', period_label: 'Range', cost_date: '2026-10-10', first_entry_date: '2026-10-01', last_entry_date: '2026-10-10', entry_count: 5,
      rig_id: 'r-1', rig_code: 'RIG-01', rig_name: 'Atlas Rig 1', well_id: 'w-1', well_code: 'WELL-101', well_name: 'Deep Horizon Alpha',
      section_id: 'sec-1', hole_section_id: 'hs1', section_scope: 'drilling', section_code: '12-1/4', section_name: 'Intermediate', section_label: '12-1/4 · Intermediate',
      mud_type: 'OBM', mud_type_label: 'Oil Based Mud', verti_g_mud_on_cuttings: '80', centrifuge: '20', by_pass: '10', evaporation: '5', trips: '15',
      surface_loss_total: '130', mud_cleaner: '10', formation_seepage: '60', pit_cleaning_dump: '20', left_in_hole: '20', other_losses: '10', other_loss_total: '120', total_losses: '250',
    }],
  },
  mudSettings: [],
}

const bundleDoc = await buildWellBundleDocument(sampleBundleData, { orientation: 'landscape' })
check('Bundle document includes Executive Summary + all 7 reports (8 sections)', bundleDoc.sections.length === 8, `${bundleDoc.sections.length} sections`)
const pdf = await buildReportPdf(bundleDoc)
const bytes = Buffer.from(pdf.output('arraybuffer'))
const pdfText = bytes.toString('latin1')
check('Bundle PDF writes a valid multi-page PDF', pdfText.startsWith('%PDF-') && pdf.getNumberOfPages() >= 8, `${pdf.getNumberOfPages()} pages, ${bytes.length} bytes`)
check('Bundle PDF carries all 7 report sections',
  ['AFE Estimate', 'Daily Cost Report', 'Drill-In Report', 'Well Cost Analysis Visualized', 'LIH Cost Register', 'NDT Inspection Register', 'Mud Cost Analysis'].every(t => pdfText.includes(t)))
const dailySec = bundleDoc.sections.find(s => s.title === 'Daily Cost Report')
const unbudgetedTable = dailySec?.tables?.find(t => t.title === 'Unbudgeted Tangibles Used')
check('Bundle PDF includes unbudgeted tangible exact name without item code',
  Boolean(unbudgetedTable?.body.some(r => r[0] === '9-5/8" L80 Casing Pup Joint' && r[1] === '(unbudgeted)'))
  && pdfText.includes('9-5/8') && pdfText.includes('Casing Pup Joint') && pdfText.includes('unbudgeted')
  && !pdfText.includes('CSG-958'))
check('Bundle PDF includes Actual / AFE % KPIs', pdfText.includes('ACTUAL / AFE %') && pdfText.includes('81.5%'))
check('Bundle PDF includes Mud per-section KPIs and Closing Stock', pdfText.includes('12-1/4') && pdfText.includes('730') && pdfText.includes('95.00'))

let failed = 0
for (const r of results) {
  if (!r.pass) failed += 1
  console.log(`${r.pass ? 'PASS' : 'FAIL'}  ${r.label}${r.detail ? `  [${r.detail}]` : ''}`)
}
console.log(failed === 0 ? `\nALL ${results.length} ENHANCEMENT CHECKS PASSED` : `\n${failed} of ${results.length} CHECKS FAILED`)
process.exit(failed ? 1 : 0)
