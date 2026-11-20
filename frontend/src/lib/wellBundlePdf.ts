/**
 * Consolidated Well & Scope PDF Bundle builder.
 *
 * Generates a single, continuous executive PDF dossier for one well under a
 * chosen scope (`drilling`, `completion`, or `both`) combining all seven core
 * reports:
 *   1. AFE Estimate
 *   2. Daily Cost Report (Summary, Budget Reconciliation & Daily Log)
 *   3. Drill-In Report (Operations Dashboard Well Drill-Through + Visuals)
 *   4. Well Cost Analysis Visualized (+ Visuals)
 *   5. LIH Cost Register
 *   6. NDT Inspection Register
 *   7. Mud Cost Analysis (Per-section KPI cards matching MudCostKpis + Reconciliation & Losses)
 *
 * Every visual is rendered offscreen via `renderChartOptionSnapshot` in paper-white
 * print styling with non-overlapping data labels, and laid out through the shared
 * `buildReportPdf` engine so text, KPI cards, charts and tables never collide.
 */

import type { EChartsOption } from 'echarts'
import { api, body } from './api'
import type { Afe, AfeEstimate } from './afe'
import {
  actualVsAfePercent, days as formatDays, money as formatMoney,
  type DashboardWellDetail,
} from './businessDashboard'
import { renderChartOptionSnapshot } from './chartExport'
import {
  dailyMoney, displayDate, localToday,
  type DailyCostDay, type DailyCostWellOption, type DailyCostWellSummary,
} from './dailyCost'
import { lihMeasure, type LihCostReport } from './lihCost'
import {
  mudQuantity,
  type MudCostLossReport, type MudCostMaterialBalance, type MudCostReconciliation,
  type MudCostSectionSetting,
} from './mudCost'
import { quantity as ndtQuantity, type NdtEntry } from './ndtInspection'
import {
  buildReportPdf, type ReportDocument, type ReportFigure, type ReportKpi, type ReportSection, type ReportTable,
} from './reportPdf'
import { formatDepthMeters } from './units'
import { watNowFormatted, watTodayIso } from './time'

export type BundleScope = 'drilling' | 'completion' | 'both'

export type BundleModuleKey =
  | 'afe'
  | 'daily_cost'
  | 'drill_in'
  | 'well_analysis'
  | 'lih'
  | 'ndt'
  | 'mud'

export const BUNDLE_MODULES: { key: BundleModuleKey; label: string; description: string }[] = [
  { key: 'afe', label: '1. AFE Estimate', description: 'Approved/saved AFE budgets, section totals and cost schedules.' },
  { key: 'daily_cost', label: '2. Daily Cost Report', description: 'Budget reconciliation, unbudgeted tangibles and daily cost log.' },
  { key: 'drill_in', label: '3. Drill-In Report', description: 'Well drill-through KPIs, operational vs tangibles chart, time mix and sections.' },
  { key: 'well_analysis', label: '4. Well Cost Analysis Visualized', description: 'Daily burn vs AFE chart, cost-group mix chart and variance breakdown.' },
  { key: 'lih', label: '5. LIH Cost Register', description: 'Lost-in-hole equipment items, dimensions, serials and total costs.' },
  { key: 'ndt', label: '6. NDT Inspection Register', description: 'Scope-filtered inspection received, consumed and backloaded quantities.' },
  { key: 'mud', label: '7. Mud Cost Analysis', description: 'Per-section mud position KPIs, reconciliation, Cost/BBL and losses.' },
]

export type WellBundleRequest = {
  well: DailyCostWellOption
  scope: BundleScope
  dateFrom?: string
  dateTo?: string
  includeDraft: boolean
  orientation?: 'landscape' | 'portrait'
  modules?: BundleModuleKey[]
  onProgress?: (message: string) => void
}

export type WellBundleData = {
  well: DailyCostWellOption
  scope: BundleScope
  dateFrom: string
  dateTo: string
  includeDraft: boolean
  estimates: AfeEstimate[]
  summary: DailyCostWellSummary | null
  days: DailyCostDay[]
  drill: DashboardWellDetail | null
  lih: LihCostReport | null
  ndt: NdtEntry[]
  mudBalance: MudCostMaterialBalance | null
  mudReconciliation: MudCostReconciliation | null
  mudLosses: MudCostLossReport | null
  mudSettings: MudCostSectionSetting[]
}

const SCOPE_LABELS: Record<BundleScope, string> = {
  drilling: 'Drilling',
  completion: 'Completion',
  both: 'Drilling & Completion',
}

// High-contrast print palette (harmonised with WellSenseIQ Petrol & slate tokens).
const PRINT_COLORS = {
  planned: '#15515B',
  actual: '#2B6CB0',
  tangibles: '#B7791F',
  cumulative: '#16283F',
  services: '#15515B',
  consumables: '#2B6CB0',
  other: '#6B46C1',
  lih: '#C53030',
  productive: '#2F855A',
  upa: '#D69E2E',
  npt: '#C53030',
  surfaceLoss: '#2B6CB0',
  otherLoss: '#B7791F',
}

function num(value: string | number | null | undefined): number {
  const parsed = Number(value ?? 0)
  return Number.isFinite(parsed) ? parsed : 0
}

function pctText(actual: string | number | null | undefined, afe: string | number | null | undefined): string {
  return actualVsAfePercent(actual, afe)
}

function matchesScope(itemScope: string | null | undefined, selected: BundleScope): boolean {
  if (selected === 'both') return true
  return (itemScope ?? '').toLowerCase() === selected
}

/** Fetch all seven underlying report payloads in parallel for the chosen well and scope. */
export async function fetchWellBundleData(request: WellBundleRequest): Promise<WellBundleData> {
  const { well, scope, includeDraft, onProgress } = request
  const dateFrom = request.dateFrom?.trim() || ''
  const dateTo = request.dateTo?.trim() || localToday()
  const modules = new Set(request.modules ?? BUNDLE_MODULES.map(m => m.key))

  onProgress?.('Loading well, AFE, daily cost, drill-in, LIH, NDT and mud records…')

  const dailyParams = new URLSearchParams({ to: dateTo, include_draft: String(includeDraft) })
  if (dateFrom) dailyParams.set('from', dateFrom)
  if (scope !== 'both') dailyParams.set('scope', scope)

  const drillParams = new URLSearchParams({ include_draft: String(includeDraft) })
  if (dateFrom) drillParams.set('from', dateFrom)
  if (dateTo) drillParams.set('to', dateTo)
  if (scope !== 'both') drillParams.set('scope', scope)

  const lihParams = new URLSearchParams({ well_id: well.id, to: dateTo })
  if (dateFrom) lihParams.set('from', dateFrom)

  const ndtParams = new URLSearchParams({ well_id: well.id })
  if (scope !== 'both') ndtParams.set('scope', scope)

  const mudBase = well.rig_id ? { rig_id: well.rig_id, well_id: well.id } : null
  const mudBalanceParams = mudBase ? new URLSearchParams({ ...mudBase, view: 'inception' }) : null
  const mudReconParams = mudBase
    ? new URLSearchParams({ ...mudBase, to: dateTo, include_draft: String(includeDraft), ...(dateFrom ? { from: dateFrom } : {}) })
    : null
  const mudLossParams = mudBase
    ? new URLSearchParams({ ...mudBase, view: 'section', to: dateTo, ...(dateFrom ? { from: dateFrom } : {}) })
    : null
  const mudSettingParams = mudBase ? new URLSearchParams(mudBase) : null

  const [
    afes,
    summary,
    days,
    drill,
    lih,
    ndtRaw,
    mudBalanceRaw,
    mudReconRaw,
    mudLossesRaw,
    mudSettingsRaw,
  ] = await Promise.all([
    modules.has('afe')
      ? api<Afe[]>('/afe/afes', { silent: true }).catch(() => [] as Afe[])
      : Promise.resolve([] as Afe[]),
    modules.has('daily_cost') || modules.has('well_analysis')
      ? api<DailyCostWellSummary>(`/daily-cost/wells/${well.id}/cost-summary?${dailyParams}`, { silent: true }).catch(() => null)
      : Promise.resolve(null),
    modules.has('daily_cost') || modules.has('well_analysis')
      ? api<DailyCostDay[]>(`/daily-cost/wells/${well.id}/cost-report?${dailyParams}`, { silent: true }).catch(() => [] as DailyCostDay[])
      : Promise.resolve([] as DailyCostDay[]),
    modules.has('drill_in')
      ? api<DashboardWellDetail>(`/dashboard/business/wells/${well.id}?${drillParams}`, { silent: true }).catch(() => null)
      : Promise.resolve(null),
    modules.has('lih')
      ? api<LihCostReport>(`/lih-cost/wells/${well.id}/report?${lihParams}`, { silent: true }).catch(() => null)
      : Promise.resolve(null),
    modules.has('ndt')
      ? api<NdtEntry[]>(`/ndt-inspections/entries?${ndtParams}`, { silent: true }).catch(() => [] as NdtEntry[])
      : Promise.resolve([] as NdtEntry[]),
    modules.has('mud') && mudBalanceParams
      ? api<MudCostMaterialBalance>(`/mud-cost/material-balance?${mudBalanceParams}`, { silent: true }).catch(() => null)
      : Promise.resolve(null),
    modules.has('mud') && mudReconParams
      ? api<MudCostReconciliation>(`/mud-cost/reconciliation?${mudReconParams}`, { silent: true }).catch(() => null)
      : Promise.resolve(null),
    modules.has('mud') && mudLossParams
      ? api<MudCostLossReport>(`/mud-cost/consumption-losses?${mudLossParams}`, { silent: true }).catch(() => null)
      : Promise.resolve(null),
    modules.has('mud') && mudSettingParams
      ? api<MudCostSectionSetting[]>(`/mud-cost/section-settings?${mudSettingParams}`, { silent: true }).catch(() => [] as MudCostSectionSetting[])
      : Promise.resolve([] as MudCostSectionSetting[]),
  ])

  // Fetch detailed estimates for every active AFE belonging to this well & scope.
  const matchingAfes = afes.filter(
    afe => afe.well_id === well.id && !afe.is_deleted && matchesScope(afe.configuration_scope, scope),
  )
  const estimates: AfeEstimate[] = matchingAfes.length
    ? (await Promise.all(
      matchingAfes.map(afe => api<AfeEstimate>(`/afe/afes/${afe.id}/estimate`, { silent: true }).catch(() => null)),
    )).filter((item): item is AfeEstimate => item !== null)
    : []

  // Scope-filter NDT and Mud responses so a Drilling-only or Completion-only
  // bundle never leaks sections/rows from the opposite scope.
  const ndt = ndtRaw.filter(row => !row.is_deleted && matchesScope(row.scope, scope))
  const mudBalance = mudBalanceRaw
    ? { ...mudBalanceRaw, rows: mudBalanceRaw.rows.filter(r => matchesScope(r.section_scope, scope)) }
    : null
  const mudReconciliation = mudReconRaw
    ? {
      ...mudReconRaw,
      sections: mudReconRaw.sections.filter(s => matchesScope(s.section_scope, scope)),
      rows: mudReconRaw.rows.filter(r => matchesScope(r.section_scope, scope)),
    }
    : null
  const mudLosses = mudLossesRaw
    ? { ...mudLossesRaw, rows: mudLossesRaw.rows.filter(r => matchesScope(r.section_scope, scope)) }
    : null
  const mudSettings = mudSettingsRaw.filter(s => matchesScope(s.section_scope, scope))

  return {
    well,
    scope,
    dateFrom,
    dateTo,
    includeDraft,
    estimates,
    summary,
    days,
    drill,
    lih,
    ndt,
    mudBalance,
    mudReconciliation,
    mudLosses,
    mudSettings,
  }
}

// ---------------------------------------------------------------------------
// Offscreen chart option builders (rendered with paper-white data labels)
// ---------------------------------------------------------------------------

function buildDrillDailyOption(drill: DashboardWellDetail, currency: string): EChartsOption | null {
  const daily = drill.daily ?? []
  if (!daily.length) return null
  const hasTangibles = daily.some(row => Number(row.tangibles ?? 0) > 0)
  return {
    animation: false,
    grid: { left: 16, right: 20, top: 42, bottom: 16, containLabel: true },
    legend: { top: 4, itemWidth: 12, itemHeight: 8 },
    xAxis: { type: 'category', data: daily.map(row => row.cost_date) },
    yAxis: [
      { type: 'value', name: `Daily (${currency})` },
      { type: 'value', name: `Cumulative (${currency})`, splitLine: { show: false } },
    ],
    series: [
      ...(hasTangibles ? [
        {
          name: 'Daily operational', type: 'bar' as const, stack: 'daily', barMaxWidth: 18,
          data: daily.map(row => num(row.operational ?? Math.max(0, num(row.actual) - num(row.tangibles)))),
          itemStyle: { color: PRINT_COLORS.actual },
        },
        {
          name: 'Tangibles (lump-sum)', type: 'bar' as const, stack: 'daily', barMaxWidth: 18,
          data: daily.map(row => num(row.tangibles)),
          itemStyle: { color: PRINT_COLORS.tangibles },
        },
      ] : [
        {
          name: 'Daily cost', type: 'bar' as const, barMaxWidth: 18,
          data: daily.map(row => num(row.actual)),
          itemStyle: { color: PRINT_COLORS.actual },
        },
      ]),
      {
        name: 'Cumulative', type: 'line' as const, yAxisIndex: 1, smooth: false,
        data: daily.map(row => num(row.cumulative)),
        lineStyle: { color: PRINT_COLORS.cumulative, width: 2.2 },
        itemStyle: { color: PRINT_COLORS.cumulative },
      },
    ],
  }
}

function buildDrillTimeOption(drill: DashboardWellDetail): EChartsOption | null {
  const nptDays = num(drill.well.npt_days)
  const upaDays = num(drill.well.upa_days)
  const actualDays = num(drill.well.actual_days)
  const productiveDays = Math.max(0, actualDays - nptDays - upaDays)
  const items = [
    { name: 'Productive', value: productiveDays, itemStyle: { color: PRINT_COLORS.productive } },
    { name: 'UPA (Unplanned)', value: upaDays, itemStyle: { color: PRINT_COLORS.upa } },
    { name: 'NPT (Non-productive)', value: nptDays, itemStyle: { color: PRINT_COLORS.npt } },
  ].filter(item => item.value > 0)
  if (!items.length) return null
  return {
    animation: false,
    legend: { bottom: 4, itemWidth: 12, itemHeight: 8 },
    series: [{
      type: 'pie',
      radius: ['42%', '68%'],
      center: ['50%', '45%'],
      data: items,
    }],
  }
}

function buildWellAnalysisDailyOption(summary: DailyCostWellSummary): EChartsOption | null {
  const days = summary.daily ?? []
  if (!days.length) return null
  const currency = summary.totals.currency
  const hasTangibles = days.some(row => num(row.tangibles) > 0)
  const effectiveAfe = num(summary.totals.adjusted_planned ?? summary.totals.planned)
  return {
    animation: false,
    grid: { left: 16, right: 20, top: 42, bottom: 16, containLabel: true },
    legend: { top: 4, itemWidth: 12, itemHeight: 8 },
    xAxis: { type: 'category', data: days.map(row => row.cost_date) },
    yAxis: [
      { type: 'value', name: `Daily (${currency})` },
      { type: 'value', name: `Cumulative (${currency})`, splitLine: { show: false } },
    ],
    series: [
      ...(hasTangibles ? [
        {
          name: 'Daily operational', type: 'bar' as const, stack: 'daily', barMaxWidth: 18,
          data: days.map(row => Math.max(0, num(row.total) - num(row.tangibles))),
          itemStyle: { color: PRINT_COLORS.actual },
        },
        {
          name: 'Tangibles (lump-sum)', type: 'bar' as const, stack: 'daily', barMaxWidth: 18,
          data: days.map(row => num(row.tangibles)),
          itemStyle: { color: PRINT_COLORS.tangibles },
        },
      ] : [
        {
          name: 'Daily cost', type: 'bar' as const, barMaxWidth: 18,
          data: days.map(row => num(row.total)),
          itemStyle: { color: PRINT_COLORS.actual },
        },
      ]),
      {
        name: 'Cumulative actual', type: 'line' as const, yAxisIndex: 1, smooth: false,
        data: days.map(row => num(row.cumulative)),
        lineStyle: { color: PRINT_COLORS.cumulative, width: 2.2 },
        itemStyle: { color: PRINT_COLORS.cumulative },
      },
      ...(effectiveAfe > 0 ? [{
        name: 'Effective AFE', type: 'line' as const, yAxisIndex: 1, symbol: 'none',
        data: days.map(() => effectiveAfe),
        lineStyle: { color: PRINT_COLORS.planned, type: 'dashed' as const, width: 1.8 },
        itemStyle: { color: PRINT_COLORS.planned },
      }] : []),
    ],
  }
}

function buildWellAnalysisMixOption(summary: DailyCostWellSummary): EChartsOption | null {
  const items = [
    { name: 'Services', value: num(summary.totals.services), itemStyle: { color: PRINT_COLORS.services } },
    { name: 'Consumables', value: num(summary.totals.consumables), itemStyle: { color: PRINT_COLORS.consumables } },
    { name: 'Tangibles', value: num(summary.totals.tangibles), itemStyle: { color: PRINT_COLORS.tangibles } },
    { name: 'Other expenses', value: num(summary.totals.other_expenses), itemStyle: { color: PRINT_COLORS.other } },
    { name: 'LIH cost', value: num(summary.totals.lih_cost), itemStyle: { color: PRINT_COLORS.lih } },
  ].filter(item => item.value > 0)
  if (!items.length) return null
  return {
    animation: false,
    legend: { bottom: 4, itemWidth: 12, itemHeight: 8 },
    series: [{
      type: 'pie',
      radius: ['42%', '68%'],
      center: ['50%', '45%'],
      data: items,
    }],
  }
}

function buildMudLossesOption(reconciliation: MudCostReconciliation): EChartsOption | null {
  if (!reconciliation.sections.length) return null
  const labels = reconciliation.sections.map(s => [s.section_code, s.section_name].filter(Boolean).join(' · ') || s.section_label)
  const surface = reconciliation.sections.map(s => num(s.surface_loss_total))
  const other = reconciliation.sections.map(s => num(s.other_loss_total))
  if (surface.every(v => v === 0) && other.every(v => v === 0)) return null
  return {
    animation: false,
    grid: { left: 16, right: 20, top: 42, bottom: 16, containLabel: true },
    legend: { top: 4, itemWidth: 12, itemHeight: 8 },
    xAxis: { type: 'category', data: labels },
    yAxis: { type: 'value', name: 'Losses (BBL)' },
    series: [
      { name: 'Surface losses', type: 'bar', stack: 'loss', barMaxWidth: 28, data: surface, itemStyle: { color: PRINT_COLORS.surfaceLoss } },
      { name: 'Other losses', type: 'bar', stack: 'loss', barMaxWidth: 28, data: other, itemStyle: { color: PRINT_COLORS.otherLoss } },
    ],
  }
}

async function safeRenderFigure(
  option: EChartsOption | null,
  meta: { title: string; caption: string; width?: number; height?: number; fullWidth?: boolean },
): Promise<ReportFigure | null> {
  if (!option) return null
  try {
    const snap = await renderChartOptionSnapshot(option, {
      width: meta.width ?? (meta.fullWidth ? 920 : 620),
      height: meta.height ?? (meta.fullWidth ? 360 : 320),
      title: meta.title,
      caption: meta.caption,
      includeDataLabels: true,
    })
    if (!snap) return null
    return {
      title: meta.title,
      caption: meta.caption,
      dataUrl: snap.dataUrl,
      width: snap.width,
      height: snap.height,
      fullWidth: meta.fullWidth,
    }
  } catch {
    return null
  }
}

// ---------------------------------------------------------------------------
// Document assembly across all 7 reports
// ---------------------------------------------------------------------------

export async function buildWellBundleDocument(
  data: WellBundleData,
  opts: { modules?: BundleModuleKey[]; orientation?: 'landscape' | 'portrait'; onProgress?: (msg: string) => void } = {},
): Promise<ReportDocument> {
  const modules = new Set(opts.modules ?? BUNDLE_MODULES.map(m => m.key))
  const currency = data.summary?.totals.currency
    ?? data.drill?.well.currency
    ?? data.estimates[0]?.afe.standard_currency
    ?? data.mudReconciliation?.currency
    ?? 'USD'
  const rigLabel = [data.well.rig_code ?? data.summary?.well.rig_code ?? '', data.well.rig_name ?? data.summary?.well.rig_name ?? ''].filter(Boolean).join(' · ')
  const scopeLabel = SCOPE_LABELS[data.scope]
  const periodLabel = `${data.dateFrom ? displayDate(data.dateFrom) : 'Inception'} to ${displayDate(data.dateTo)}`

  opts.onProgress?.('Rendering high-DPI print charts with data labels…')

  const [drillDailyFig, drillTimeFig, analysisDailyFig, analysisMixFig, mudLossFig] = await Promise.all([
    modules.has('drill_in') && data.drill
      ? safeRenderFigure(buildDrillDailyOption(data.drill, data.drill.well.currency || currency), {
        title: 'Daily operational spend, lump-sum tangibles & cumulative curve',
        caption: 'Recurring daily operational spend separated from lump-sum tangibles alongside cumulative cost.',
        fullWidth: true,
      })
      : Promise.resolve(null),
    modules.has('drill_in') && data.drill
      ? safeRenderFigure(buildDrillTimeOption(data.drill), {
        title: 'Time allocation (Productive / UPA / NPT)',
        caption: 'Elapsed operational time broken down by productive, unplanned (UPA) and non-productive (NPT) days.',
      })
      : Promise.resolve(null),
    modules.has('well_analysis') && data.summary
      ? safeRenderFigure(buildWellAnalysisDailyOption(data.summary), {
        title: 'Daily cost progression against Effective AFE',
        caption: 'Daily operational spend and lump-sum tangibles plotted against cumulative actual cost and effective AFE.',
        fullWidth: true,
      })
      : Promise.resolve(null),
    modules.has('well_analysis') && data.summary
      ? safeRenderFigure(buildWellAnalysisMixOption(data.summary), {
        title: 'Actual cost mix by cost group',
        caption: `Distribution of recorded actual cost across Services, Consumables, Tangibles, Other expenses and LIH (${currency}).`,
      })
      : Promise.resolve(null),
    modules.has('mud') && data.mudReconciliation
      ? safeRenderFigure(buildMudLossesOption(data.mudReconciliation), {
        title: 'Mud losses by hole section',
        caption: 'Surface losses versus other losses across sections in this scope.',
        fullWidth: true,
      })
      : Promise.resolve(null),
  ])

  opts.onProgress?.('Assembling consolidated PDF sections…')

  const sections: ReportSection[] = []

  // ---- Cover / Executive Summary -------------------------------------------
  const effectiveAfe = data.summary
    ? num(data.summary.totals.adjusted_planned ?? data.summary.totals.planned)
    : (data.drill ? num(data.drill.well.effective_afe_amount) : data.estimates.reduce((s, e) => s + num(e.afe.adjusted_total ?? e.afe.total_cost), 0))
  const totalActual = data.summary
    ? num(data.summary.totals.actual_including_lih ?? data.summary.totals.actual)
    : (data.drill ? num(data.drill.well.actual_amount) : 0)
  const balance = effectiveAfe - totalActual
  const utilPct = pctText(totalActual, effectiveAfe > 0 ? effectiveAfe : null)

  const contentsRows: (string | number)[][] = []
  if (modules.has('afe')) contentsRows.push(['1', 'AFE Estimate', `${data.estimates.length} matching AFE(s)`, data.estimates.length ? 'Included' : 'No AFE records'])
  if (modules.has('daily_cost')) contentsRows.push(['2', 'Daily Cost Report', `${data.days.length} daily sheet(s)`, data.days.length || data.summary ? 'Included' : 'No daily sheets'])
  if (modules.has('drill_in')) contentsRows.push(['3', 'Drill-In Report', `${data.drill?.daily.length ?? 0} plotted day(s)`, data.drill ? 'Included (with visuals)' : 'Unavailable'])
  if (modules.has('well_analysis')) contentsRows.push(['4', 'Well Cost Analysis Visualized', `${data.summary?.daily.length ?? 0} daily point(s)`, data.summary ? 'Included (with visuals)' : 'Unavailable'])
  if (modules.has('lih')) contentsRows.push(['5', 'LIH Cost Register', `${data.lih?.line_count ?? 0} line item(s)`, data.lih?.line_count ? 'Included' : 'No LIH items'])
  if (modules.has('ndt')) contentsRows.push(['6', 'NDT Inspection Register', `${data.ndt.length} inspection row(s)`, data.ndt.length ? 'Included' : 'No NDT rows'])
  if (modules.has('mud')) contentsRows.push(['7', 'Mud Cost Analysis', `${data.mudReconciliation?.sections.length ?? data.mudBalance?.rows.length ?? 0} section(s)`, (data.mudBalance?.rows.length || data.mudReconciliation?.sections.length) ? 'Included (with KPIs)' : 'No mud records'])

  sections.push({
    badge: 'CONSOLIDATED WELL COST DOSSIER',
    title: `Executive Summary — ${data.well.well_code} · ${data.well.well_name}`,
    subtitle: `${rigLabel ? `Rig ${rigLabel} · ` : ''}Scope: ${scopeLabel} · Period: ${periodLabel} · ${data.includeDraft ? 'Draft & submitted daily sheets' : 'Submitted daily sheets only'}`,
    kpis: [
      { label: 'Effective AFE', value: effectiveAfe > 0 ? dailyMoney(effectiveAfe, currency) : '—', hint: `${data.estimates.length} AFE(s) in scope` },
      { label: 'Total Actual Cost', value: dailyMoney(totalActual, currency), hint: `${data.days.length} daily sheet(s)` },
      { label: 'Actual / AFE %', value: utilPct, hint: '(Actual ÷ Effective AFE) × 100' },
      { label: 'Remaining Balance', value: effectiveAfe > 0 ? dailyMoney(balance, currency) : '—', hint: balance < 0 ? 'Over effective AFE' : 'Within effective AFE' },
      ...(data.drill ? [
        {
          label: 'Planned vs Actual Days',
          value: `${formatDays(data.drill.well.actual_days)} / ${formatDays(data.drill.well.planned_days)} d`,
          hint: `Variance ${formatDays(num(data.drill.well.actual_days) - num(data.drill.well.planned_days))} d`,
        },
      ] : []),
      { label: 'LIH Total Cost', value: data.lih?.line_count ? dailyMoney(data.lih.total, data.lih.currency || currency) : '0.00', hint: `${data.lih?.line_count ?? 0} item(s)` },
      { label: 'NDT Inspection Rows', value: String(data.ndt.length), hint: `Scope: ${scopeLabel}` },
      { label: 'Mud Reconciled Cost', value: data.mudReconciliation?.sections.length ? dailyMoney(data.mudReconciliation.total_reconciled_cost, data.mudReconciliation.currency || currency) : '—', hint: `${data.mudReconciliation?.sections.length ?? 0} section(s)` },
    ],
    tables: [{
      title: 'Included Reports in this Bundle',
      head: ['#', 'Report', 'Coverage', 'Status'],
      numeric: [0],
      wide: [1, 2],
      body: contentsRows,
    }],
  })

  // ---- 1. AFE Estimate -----------------------------------------------------
  if (modules.has('afe')) {
    const afeTables: ReportTable[] = []
    const afeKpis: ReportKpi[] = []
    if (data.estimates.length) {
      const sumSvc = data.estimates.reduce((s, e) => s + num(e.afe.adjusted_services_total ?? e.summary.services_total), 0)
      const sumCon = data.estimates.reduce((s, e) => s + num(e.afe.adjusted_consumables_total ?? e.summary.consumables_total), 0)
      const sumTan = data.estimates.reduce((s, e) => s + num(e.afe.adjusted_tangibles_total ?? e.summary.tangibles_total), 0)
      const sumAll = data.estimates.reduce((s, e) => s + num(e.afe.adjusted_total ?? e.summary.total ?? e.afe.total_cost), 0)
      afeKpis.push(
        { label: 'AFEs in Scope', value: String(data.estimates.length), hint: scopeLabel },
        { label: 'Services AFE', value: dailyMoney(sumSvc, currency) },
        { label: 'Consumables AFE', value: dailyMoney(sumCon, currency) },
        { label: 'Tangibles AFE', value: dailyMoney(sumTan, currency) },
        { label: 'Total Effective AFE', value: dailyMoney(sumAll, currency) },
      )
      afeTables.push({
        title: 'AFE Register Summary',
        head: ['AFE Code', 'Name', 'Scope', 'Status', 'Services', 'Consumables', 'Tangibles', `Effective Total (${currency})`],
        numeric: [4, 5, 6, 7],
        wide: [1],
        body: data.estimates.map(est => [
          est.afe.afe_code,
          est.afe.afe_name,
          est.afe.configuration_scope === 'completion' ? 'Completion' : 'Drilling',
          est.afe.status.toUpperCase(),
          dailyMoney(est.afe.adjusted_services_total ?? est.summary.services_total ?? 0),
          dailyMoney(est.afe.adjusted_consumables_total ?? est.summary.consumables_total ?? 0),
          dailyMoney(est.afe.adjusted_tangibles_total ?? est.summary.tangibles_total ?? 0),
          dailyMoney(est.afe.adjusted_total ?? est.summary.total ?? est.afe.total_cost ?? 0),
        ]),
        foot: ['TOTAL', '', '', '', dailyMoney(sumSvc), dailyMoney(sumCon), dailyMoney(sumTan), dailyMoney(sumAll)],
      })
      for (const est of data.estimates) {
        if (est.summary.by_section.length) {
          afeTables.push({
            title: `${est.afe.afe_code} — Cost by Hole Section`,
            head: ['Section', 'Planned Days', 'Services', 'Consumables', 'Tangibles', `Section Total (${est.afe.standard_currency})`],
            numeric: [1, 2, 3, 4, 5],
            wide: [0],
            body: est.summary.by_section.map(sec => [
              sec.label,
              sec.planned_days,
              sec.services != null ? dailyMoney(sec.services) : '—',
              sec.consumables != null ? dailyMoney(sec.consumables) : '—',
              sec.tangibles != null ? dailyMoney(sec.tangibles) : '—',
              sec.total != null ? dailyMoney(sec.total) : '—',
            ]),
          })
        }
        if (est.services.length) {
          afeTables.push({
            title: `${est.afe.afe_code} — Services Schedule (${est.services.length})`,
            head: ['Code', 'Service', 'Category', 'Vendor', 'Basis', 'Currency', 'Amount'],
            numeric: [6],
            wide: [1, 3],
            body: est.services.map(line => [
              line.service_code,
              line.service_name,
              line.service_category || line.service_group || '—',
              line.vendor_name || '—',
              line.charging_basis,
              line.currency,
              dailyMoney(line.amount),
            ]),
          })
        }
        if (est.consumables.length) {
          afeTables.push({
            title: `${est.afe.afe_code} — Consumables Schedule (${est.consumables.length})`,
            head: ['Category', 'Section', 'Detail / Drill Bit', 'Qty', 'Currency', 'Amount'],
            numeric: [3, 5],
            wide: [2],
            body: est.consumables.map(line => [
              line.category,
              line.section_label || '—',
              line.bit_name || line.bit_code || line.remarks || line.category,
              line.quantity || '—',
              line.currency,
              dailyMoney(line.amount),
            ]),
          })
        }
        if (est.tangibles.length) {
          afeTables.push({
            title: `${est.afe.afe_code} — Tangibles Schedule (${est.tangibles.length})`,
            head: ['Tangible', 'Category', 'UOM', 'Qty', 'Rate', 'Currency', 'Amount'],
            numeric: [3, 4, 6],
            wide: [0],
            body: est.tangibles.map(line => [
              line.tangible_name,
              [line.category_name, line.subcategory_name].filter(Boolean).join(' / ') || '—',
              line.uom || '—',
              line.quantity,
              dailyMoney(line.effective_rate),
              line.currency,
              dailyMoney(line.amount),
            ]),
          })
        }
      }
    }
    sections.push({
      badge: 'REPORT 1 OF 7',
      title: 'AFE Estimate',
      subtitle: `Authorised and saved AFE budgets for ${data.well.well_code} (${scopeLabel}).`,
      pageBreakBefore: true,
      kpis: afeKpis.length ? afeKpis : [{ label: 'AFE Status', value: 'No matching AFEs', hint: `Scope: ${scopeLabel}` }],
      tables: afeTables,
      notes: data.estimates.length ? undefined : ['No saved AFE estimates exist for this well and scope.'],
    })
  }

  // ---- 2. Daily Cost Report ------------------------------------------------
  if (modules.has('daily_cost')) {
    const dcTables: ReportTable[] = []
    const dcKpis: ReportKpi[] = []
    if (data.summary) {
      const t = data.summary.totals
      const effAfe = num(t.adjusted_planned ?? t.planned)
      const actTot = num(t.actual_including_lih ?? t.actual)
      const balTot = effAfe - actTot
      const groupRows = data.summary.factors.find(f => f.dimension === 'cost_group')?.rows ?? []
      const plannedFor = (groupName: string) => num(groupRows.find(r => r.name === groupName || r.code === groupName)?.planned)
      const svcPlan = plannedFor('Services')
      const conPlan = plannedFor('Consumables')
      const tanPlan = plannedFor('Tangibles')
      dcKpis.push(
        { label: 'Effective AFE', value: dailyMoney(effAfe, currency) },
        { label: 'Actual Total', value: dailyMoney(actTot, currency) },
        { label: 'Actual / AFE %', value: pctText(actTot, effAfe > 0 ? effAfe : null), hint: '(Actual ÷ AFE) × 100' },
        { label: 'Balance', value: dailyMoney(balTot, currency) },
        { label: 'Services Actual', value: dailyMoney(t.services, currency) },
        { label: 'Consumables Actual', value: dailyMoney(t.consumables, currency) },
        { label: 'Tangibles Actual', value: dailyMoney(t.tangibles, currency) },
        { label: 'Other + LIH', value: dailyMoney(num(t.other_expenses) + num(t.lih_cost), currency) },
      )
      dcTables.push({
        title: `Budget Reconciliation by Cost Group (${currency})`,
        head: ['Cost Group', 'AFE Planned', 'Actual', 'Balance', 'Actual / AFE %'],
        numeric: [1, 2, 3, 4],
        wide: [0],
        body: [
          ['Services', dailyMoney(svcPlan), dailyMoney(t.services), dailyMoney(svcPlan - num(t.services)), svcPlan > 0 ? pctText(num(t.services), svcPlan) : '—'],
          ['Consumables', dailyMoney(conPlan), dailyMoney(t.consumables), dailyMoney(conPlan - num(t.consumables)), conPlan > 0 ? pctText(num(t.consumables), conPlan) : '—'],
          ['Tangibles', dailyMoney(tanPlan), dailyMoney(t.tangibles), dailyMoney(tanPlan - num(t.tangibles)), tanPlan > 0 ? pctText(num(t.tangibles), tanPlan) : '—'],
          ['Other Expenses', '0.00', dailyMoney(t.other_expenses), dailyMoney(-num(t.other_expenses)), '—'],
          ['LIH Cost', '0.00', dailyMoney(t.lih_cost ?? 0), dailyMoney(-num(t.lih_cost)), '—'],
        ],
        foot: ['TOTAL', dailyMoney(effAfe), dailyMoney(actTot), dailyMoney(balTot), pctText(actTot, effAfe > 0 ? effAfe : null)],
      })
      const unbudgetedTangibles = (data.summary.budget_lines ?? []).filter(
        row => row.cost_group === 'Tangibles' && !row.is_planned && num(row.actual_to_date) > 0,
      )
      if (unbudgetedTangibles.length) {
        dcTables.push({
          title: 'Unbudgeted Tangibles Used',
          head: ['Tangible', 'Status', `Actual (${currency})`],
          numeric: [2],
          wide: [0],
          body: unbudgetedTangibles.map(row => [row.item_name || row.item_code, '(unbudgeted)', dailyMoney(row.actual_to_date)]),
          foot: ['TOTAL UNBUDGETED TANGIBLES', '', dailyMoney(unbudgetedTangibles.reduce((s, r) => s + num(r.actual_to_date), 0))],
        })
      }
    }
    if (data.days.length) {
      dcTables.push({
        title: `Daily Cost Sheet Log (${data.days.length} day${data.days.length === 1 ? '' : 's'})`,
        head: ['Date', 'AFE', 'Status', 'Services', 'Consumables', 'Tangibles', 'Other', 'Daily Total', 'Cumulative'],
        numeric: [3, 4, 5, 6, 7, 8],
        body: (() => {
          let running = 0
          return data.days.map(day => {
            const total = num(day.entry.total_cost)
            running += total
            return [
              displayDate(day.entry.cost_date),
              day.entry.afe_code,
              day.entry.status.toUpperCase(),
              dailyMoney(day.entry.services_total),
              dailyMoney(day.entry.consumables_total),
              dailyMoney(day.entry.tangibles_total),
              dailyMoney(day.entry.other_expenses_total),
              dailyMoney(total),
              dailyMoney(running),
            ]
          })
        })(),
      })
    }
    sections.push({
      badge: 'REPORT 2 OF 7',
      title: 'Daily Cost Report',
      subtitle: `Budget reconciliation, unbudgeted tangibles and daily sheet register for ${data.well.well_code} (${scopeLabel}).`,
      pageBreakBefore: true,
      kpis: dcKpis.length ? dcKpis : [{ label: 'Daily Cost Sheets', value: '0 sheets', hint: periodLabel }],
      tables: dcTables,
      notes: data.days.length || data.summary ? undefined : ['No daily cost sheets match this well, scope and date period.'],
    })
  }

  // ---- 3. Drill-In Report --------------------------------------------------
  if (modules.has('drill_in')) {
    const drillFigs: ReportFigure[] = [drillDailyFig, drillTimeFig].filter((f): f is ReportFigure => f !== null)
    const drillWell = data.drill?.well
    const drillCurr = drillWell?.currency || currency
    const drillKpis: ReportKpi[] = drillWell ? [
      { label: 'Effective Plan', value: formatMoney(drillWell.effective_afe_amount, drillCurr) },
      { label: 'Actual Cost', value: formatMoney(drillWell.actual_amount, drillCurr) },
      { label: 'Actual / AFE %', value: pctText(drillWell.actual_amount, drillWell.effective_afe_amount), hint: '(Actual ÷ Plan) × 100' },
      { label: 'Balance', value: formatMoney(drillWell.afe_balance, drillCurr) },
      { label: 'Planned Days', value: `${formatDays(drillWell.planned_days)} d` },
      { label: 'Actual Days', value: `${formatDays(drillWell.actual_days)} d`, hint: `NPT ${formatDays(drillWell.npt_days)} d · UPA ${formatDays(drillWell.upa_days)} d` },
      { label: 'Planned Depth', value: formatDepthMeters(drillWell.planned_depth, drillWell.depth_unit) },
      { label: 'Actual Depth', value: formatDepthMeters(drillWell.actual_depth, drillWell.depth_unit) },
    ] : [{ label: 'Drill-In Report', value: 'Unavailable', hint: 'No drill-through payload returned for this scope.' }]

    const drillTables: ReportTable[] = []
    if (data.drill?.afes.length) {
      drillTables.push({
        title: 'AFEs in Scope',
        head: ['AFE', 'Scope', 'Status', 'Effective Plan', 'Actual', 'Actual / AFE %', 'Balance', 'Actual Days'],
        numeric: [3, 4, 5, 6, 7],
        body: data.drill.afes.map(row => [
          `${row.afe_code} · ${row.afe_name}`,
          row.configuration_scope === 'completion' ? 'Completion' : 'Drilling',
          row.status,
          formatMoney(row.effective_afe_amount, row.currency),
          formatMoney(row.actual_amount, row.currency),
          pctText(row.actual_amount, row.effective_afe_amount),
          formatMoney(row.afe_balance, row.currency),
          formatDays(row.actual_days),
        ]),
      })
    }
    if (data.drill?.sections.length) {
      drillTables.push({
        title: 'Hole Sections & Depth Progress',
        head: ['Section', 'Scope', 'From Depth', 'To Depth', 'Planned Days', 'Recorded Cost'],
        numeric: [2, 3, 4, 5],
        wide: [0],
        body: data.drill.sections.map(sec => [
          [sec.section_code, sec.section_name].filter(Boolean).join(' · ') || '—',
          sec.scope === 'completion' ? 'Completion' : 'Drilling',
          formatDepthMeters(sec.from_depth, sec.depth_unit || drillWell?.depth_unit),
          formatDepthMeters(sec.to_depth, sec.depth_unit || drillWell?.depth_unit),
          formatDays(sec.planned_days),
          formatMoney(sec.amount, drillCurr),
        ]),
      })
    }
    sections.push({
      badge: 'REPORT 3 OF 7',
      title: 'Drill-In Report (Operations Drill-Through)',
      subtitle: `Operational spend versus lump-sum tangibles, time allocation and AFE/section drill-through (${scopeLabel}).`,
      pageBreakBefore: true,
      kpis: drillKpis,
      figures: drillFigs,
      tables: drillTables,
      notes: data.drill?.notes?.length ? data.drill.notes : undefined,
    })
  }

  // ---- 4. Well Cost Analysis Visualized ------------------------------------
  if (modules.has('well_analysis')) {
    const waFigs: ReportFigure[] = [analysisDailyFig, analysisMixFig].filter((f): f is ReportFigure => f !== null)
    const waKpis: ReportKpi[] = []
    const waTables: ReportTable[] = []
    if (data.summary) {
      const t = data.summary.totals
      const effAfe = num(t.adjusted_planned ?? t.planned)
      const actTot = num(t.actual_including_lih ?? t.actual)
      const tanTot = num(t.tangibles)
      const opTot = Math.max(0, actTot - tanTot)
      const activeDays = data.summary.daily.length
      const groupRows = data.summary.factors.find(f => f.dimension === 'cost_group')?.rows ?? []
      const tanPlan = num(groupRows.find(r => r.name === 'Tangibles' || r.code === 'Tangibles')?.planned)
      waKpis.push(
        { label: 'Effective AFE', value: dailyMoney(effAfe, currency) },
        { label: 'Total Actual', value: dailyMoney(actTot, currency) },
        { label: 'Actual / AFE %', value: pctText(actTot, effAfe > 0 ? effAfe : null), hint: '(Actual ÷ Effective AFE) × 100' },
        { label: 'Operational Burn / Day', value: activeDays ? dailyMoney(opTot / activeDays, currency) : '—', hint: `Excludes lump-sum tangibles (${activeDays} d)` },
        { label: 'Operational Total', value: dailyMoney(opTot, currency) },
        { label: 'Tangibles Total', value: dailyMoney(tanTot, currency), hint: `AFE: ${dailyMoney(tanPlan, currency)}` },
      )
      if (data.summary.budget_lines?.length) {
        const sortedItems = [...data.summary.budget_lines]
          .sort((a, b) => num(b.actual_to_date) - num(a.actual_to_date))
          .slice(0, 25)
        waTables.push({
          title: 'Budget Reconciliation — Top Line Items',
          head: ['Group', 'Item', 'Planned', 'Actual', 'Actual / AFE %', 'Balance'],
          numeric: [2, 3, 4, 5],
          wide: [1],
          body: sortedItems.map(row => [
            row.cost_group,
            row.is_planned ? (row.item_name || row.item_code) : `${row.item_name || row.item_code} (unbudgeted)`,
            dailyMoney(row.planned),
            dailyMoney(row.actual_to_date),
            num(row.planned) > 0 ? pctText(num(row.actual_to_date), num(row.planned)) : '—',
            dailyMoney(row.balance),
          ]),
        })
      }
    }
    sections.push({
      badge: 'REPORT 4 OF 7',
      title: 'Well Cost Analysis Visualized',
      subtitle: `Cumulative burn against AFE, operational vs tangible spend separation and line-item budget variance (${scopeLabel}).`,
      pageBreakBefore: true,
      kpis: waKpis.length ? waKpis : [{ label: 'Cost Analysis', value: 'Unavailable', hint: 'Requires a unified standard currency and daily cost entries.' }],
      figures: waFigs,
      tables: waTables,
    })
  }

  // ---- 5. LIH Cost Register ------------------------------------------------
  if (modules.has('lih')) {
    const lihRows: (string | number)[][] = []
    for (const day of data.lih?.days ?? []) {
      for (const line of day.lines) {
        lihRows.push([
          displayDate(day.entry.cost_date),
          line.item_description,
          [lihMeasure(line.od_size), lihMeasure(line.id_size), lihMeasure(line.length)].join(' / '),
          line.connection || '—',
          line.serial_number || '—',
          `${line.no_of_units} ${line.unit}`.trim(),
          dailyMoney(line.unit_cost, day.entry.currency),
          dailyMoney(line.total_cost, day.entry.currency),
          line.remarks || '—',
        ])
      }
    }
    const lihKpis: ReportKpi[] = [
      { label: 'LIH Register Sheets', value: String(data.lih?.entry_count ?? 0) },
      { label: 'LIH Line Items', value: String(data.lih?.line_count ?? 0) },
      { label: 'Total LIH Cost', value: data.lih?.line_count ? dailyMoney(data.lih.total, data.lih.currency || currency) : dailyMoney(0, currency) },
    ]
    sections.push({
      badge: 'REPORT 5 OF 7',
      title: 'LIH Cost Register',
      subtitle: `Lost-in-hole equipment charges recorded for ${data.well.well_code} (${periodLabel}).`,
      pageBreakBefore: true,
      kpis: lihKpis,
      tables: [{
        title: 'Lost-in-Hole Items Schedule',
        head: ['Date', 'Item Description', 'OD / ID / Len', 'Connection', 'Serial No.', 'Qty', 'Unit Cost', 'Total Cost', 'Remarks'],
        numeric: [5, 6, 7],
        wide: [1, 8],
        body: lihRows,
        ...(lihRows.length ? { foot: ['TOTAL', `${data.lih?.line_count ?? lihRows.length} item(s)`, '', '', '', '', '', dailyMoney(data.lih?.total ?? 0, data.lih?.currency || currency), ''] } : {}),
      }],
    })
  }

  // ---- 6. NDT Inspection Register ------------------------------------------
  if (modules.has('ndt')) {
    const totRec = data.ndt.reduce((s, r) => s + num(r.quantity_received), 0)
    const totCon = data.ndt.reduce((s, r) => s + num(r.quantity_consumed), 0)
    const totGood = data.ndt.reduce((s, r) => s + num(r.quantity_backloaded_good), 0)
    const totBad = data.ndt.reduce((s, r) => s + num(r.quantity_backloaded_bad), 0)
    sections.push({
      badge: 'REPORT 6 OF 7',
      title: 'NDT Inspection Register',
      subtitle: `Non-destructive testing inspection register for ${data.well.well_code} — strictly filtered to ${scopeLabel}.`,
      pageBreakBefore: true,
      kpis: [
        { label: 'Inspection Lines', value: String(data.ndt.length), hint: `Scope: ${scopeLabel}` },
        { label: 'Qty Received', value: ndtQuantity(totRec) },
        { label: 'Qty Consumed', value: ndtQuantity(totCon) },
        { label: 'Backloaded Good', value: ndtQuantity(totGood) },
        { label: 'Backloaded Bad', value: ndtQuantity(totBad) },
      ],
      tables: [{
        title: 'NDT Inspection Schedule',
        head: ['Scope', 'Description', 'Received', 'Consumed', 'Backloaded Good', 'Backloaded Bad', 'Remarks'],
        numeric: [2, 3, 4, 5],
        wide: [1, 6],
        body: data.ndt.map(row => [
          row.scope === 'completion' ? 'Completion' : 'Drilling',
          row.description,
          ndtQuantity(row.quantity_received),
          ndtQuantity(row.quantity_consumed),
          ndtQuantity(row.quantity_backloaded_good),
          ndtQuantity(row.quantity_backloaded_bad),
          row.remarks || '—',
        ]),
        ...(data.ndt.length ? { foot: ['TOTAL', `${data.ndt.length} row(s)`, ndtQuantity(totRec), ndtQuantity(totCon), ndtQuantity(totGood), ndtQuantity(totBad), ''] } : {}),
      }],
    })
  }

  // ---- 7. Mud Cost Analysis (Per-Section KPIs matching MudCostKpis.tsx) ----
  if (modules.has('mud')) {
    const recon = data.mudReconciliation
    const bal = data.mudBalance
    const mudCurr = recon?.currency || currency
    const balanceBySection = new Map((bal?.rows ?? []).map(row => [row.section_id, row]))
    const settingBySection = new Map(data.mudSettings.map(s => [`${s.section_scope}:${s.hole_section_id}`, s]))
    const reconSections = recon?.sections ?? []

    // Build per-section KPI tiles mirroring MudCostKpis.tsx (Opening, Receipt,
    // Additions, Total Mud, Consumption/Losses, Others, Closing Stock,
    // Reconciled Cost, Latest Cost/BBL).
    const mudKpis: ReportKpi[] = []
    if (recon) {
      mudKpis.push(
        { label: 'Total Mud Actual Cost', value: dailyMoney(recon.total_actual_cost, mudCurr), hint: `${reconSections.length} section(s)` },
        { label: 'Total Reconciled Cost', value: dailyMoney(recon.total_reconciled_cost, mudCurr), hint: `Adjustment: ${dailyMoney(recon.total_adjustment, mudCurr)}` },
        { label: 'Mud AFE Planned', value: recon.total_planned_cost != null ? dailyMoney(recon.total_planned_cost, mudCurr) : '—', hint: recon.total_planned_cost != null ? `Actual / AFE: ${pctText(num(recon.total_actual_cost), num(recon.total_planned_cost))}` : 'No mud AFE allowance' },
        { label: 'Latest Cost / BBL', value: recon.latest_cost_per_bbl != null ? dailyMoney(recon.latest_cost_per_bbl, mudCurr) : '—', hint: recon.latest_cost_per_bbl_section || 'Across configured sections' },
      )
      for (const sec of reconSections) {
        const bRow = balanceBySection.get(sec.section_id)
        const setting = settingBySection.get(`${sec.section_scope}:${sec.hole_section_id}`)
        const mudType = sec.mud_type ?? setting?.mud_type ?? 'Unconfigured'
        const secTitle = [sec.section_code, sec.section_name].filter(Boolean).join(' · ') || sec.section_label
        mudKpis.push({
          label: `${secTitle} (${mudType})`,
          value: sec.reconciled_cost != null ? dailyMoney(sec.reconciled_cost, sec.currency || mudCurr) : '—',
          hint: `Cost/BBL ${sec.cost_per_bbl != null ? dailyMoney(sec.cost_per_bbl, sec.currency || mudCurr) : '—'} · Close ${bRow ? mudQuantity(bRow.closing_stock) : '—'}`,
        })
      }
    } else if (bal?.rows.length) {
      for (const bRow of bal.rows) {
        mudKpis.push({
          label: `${bRow.section_code} · ${bRow.section_name}`,
          value: `Close: ${mudQuantity(bRow.closing_stock)}`,
          hint: `Open ${mudQuantity(bRow.opening_stock)} · Add ${mudQuantity(bRow.additions)} · Loss ${mudQuantity(bRow.consumption_losses)}`,
        })
      }
    } else {
      mudKpis.push({ label: 'Mud Cost Analysis', value: 'No records', hint: `Scope: ${scopeLabel}` })
    }

    const mudTables: ReportTable[] = []

    // Section Material Balance KPI table (matches every line in MudCostKpis cards).
    if (bal?.rows.length) {
      mudTables.push({
        title: 'Section Mud Position — Material Balance (Since Inception)',
        head: ['Section', 'Scope', 'Opening', 'Receipt', 'Additions', 'Cons./Losses', 'Others', 'Closing Stock'],
        numeric: [2, 3, 4, 5, 6, 7],
        wide: [0],
        body: bal.rows.map(row => [
          [row.section_code, row.section_name].filter(Boolean).join(' · ') || row.section_label,
          row.section_scope === 'completion' ? 'Completion' : 'Drilling',
          mudQuantity(row.opening_stock),
          mudQuantity(row.receipt),
          mudQuantity(row.additions),
          mudQuantity(row.consumption_losses),
          mudQuantity(row.others),
          mudQuantity(row.closing_stock),
        ]),
      })
    }

    // Section Reconciliation & Pricing table.
    if (reconSections.length) {
      mudTables.push({
        title: `Mud Cost Reconciliation & Pricing (${mudCurr})`,
        head: ['Section', 'Mud Type', 'Total Mud', 'Cost/BBL', 'AFE Plan', 'Actual Cost', 'Reconciled', 'Adjustment', 'Actual / AFE %'],
        numeric: [2, 3, 4, 5, 6, 7, 8],
        wide: [0],
        body: reconSections.map(sec => [
          [sec.section_code, sec.section_name].filter(Boolean).join(' · ') || sec.section_label,
          sec.mud_type ?? '—',
          mudQuantity(sec.total_mud),
          sec.cost_per_bbl != null ? dailyMoney(sec.cost_per_bbl) : '—',
          sec.planned_cost != null ? dailyMoney(sec.planned_cost) : '—',
          dailyMoney(sec.actual_cost),
          sec.reconciled_cost != null ? dailyMoney(sec.reconciled_cost) : '—',
          sec.adjustment != null ? dailyMoney(sec.adjustment) : '—',
          sec.planned_cost != null ? pctText(num(sec.actual_cost), num(sec.planned_cost)) : '—',
        ]),
        foot: [
          'TOTAL',
          '',
          '',
          recon?.latest_cost_per_bbl != null ? dailyMoney(recon.latest_cost_per_bbl) : '—',
          recon?.total_planned_cost != null ? dailyMoney(recon.total_planned_cost) : '—',
          dailyMoney(recon?.total_actual_cost ?? 0),
          dailyMoney(recon?.total_reconciled_cost ?? 0),
          dailyMoney(recon?.total_adjustment ?? 0),
          recon?.total_planned_cost != null ? pctText(num(recon.total_actual_cost), num(recon.total_planned_cost)) : '—',
        ],
      })
    }

    // Surface & Other Losses breakdown table.
    const lossRows = data.mudLosses?.rows ?? []
    if (lossRows.length) {
      mudTables.push({
        title: 'Mud Consumption & Losses Breakdown by Section (BBL)',
        head: ['Section', 'Mud Type', 'Surface Losses', 'Formation/Seepage', 'Pit Dump', 'Left-In-Hole', 'Other Losses', 'Total Losses'],
        numeric: [2, 3, 4, 5, 6, 7],
        wide: [0],
        body: lossRows.map(row => [
          [row.section_code, row.section_name].filter(Boolean).join(' · ') || row.section_label,
          row.mud_type ?? '—',
          mudQuantity(row.surface_loss_total),
          mudQuantity(row.formation_seepage),
          mudQuantity(row.pit_cleaning_dump),
          mudQuantity(row.left_in_hole),
          mudQuantity(row.other_loss_total),
          mudQuantity(row.total_losses),
        ]),
      })
    }

    sections.push({
      badge: 'REPORT 7 OF 7',
      title: 'Mud Cost Analysis',
      subtitle: `Section mud position KPIs, material balance, Cost/BBL reconciliation and losses for ${data.well.well_code} (${scopeLabel}).`,
      pageBreakBefore: true,
      kpis: mudKpis,
      figures: mudLossFig ? [mudLossFig] : undefined,
      tables: mudTables,
      notes: [
        'Total mud for pricing = opening stock + extra OBM received + additions; other receipts also affect closing stock. "Others" is a separate stock deduction, not consumption/losses.',
      ],
    })
  }

  return {
    title: `${data.well.well_code} · ${data.well.well_name} — Consolidated Well Cost Report (${scopeLabel})`,
    subtitle: `Single-volume well dossier covering AFE Estimate, Daily Cost, Drill-In, Cost Analysis, LIH, NDT & Mud Cost Analysis.`,
    scope: `${rigLabel ? `Rig ${rigLabel} · ` : ''}${data.well.well_code} · ${scopeLabel} · ${periodLabel} · ${data.includeDraft ? 'Drafts included' : 'Submitted only'}`,
    readAt: watNowFormatted(),
    notices: [
      `Scope strictly filtered to ${scopeLabel}. Operational daily spend is separated from lump-sum tangibles in all charts.`,
      'Actual / AFE % is computed as (Actual ÷ Effective AFE) × 100 across all sections.',
    ],
    sections,
    fileName: `${data.well.well_code.toLowerCase().replace(/[^a-z0-9]+/g, '-')}-${data.scope}-well-report-bundle`,
    orientation: opts.orientation ?? 'landscape',
  }
}

/** End-to-end orchestrator: fetch, render charts, build PDF, audit and download. */
export async function exportWellBundlePdf(request: WellBundleRequest): Promise<void> {
  const data = await fetchWellBundleData(request)
  const docSpec = await buildWellBundleDocument(data, {
    modules: request.modules,
    orientation: request.orientation,
    onProgress: request.onProgress,
  })
  request.onProgress?.('Writing consolidated PDF file…')
  const pdf = await buildReportPdf(docSpec)
  pdf.save(`${docSpec.fileName}-${watTodayIso()}.pdf`)
  await api('/daily-cost/export-audit', {
    method: 'POST',
    silent: true,
    body: body({
      module: 'well-bundle-pdf',
      format: 'pdf',
      record_count: data.days.length + data.estimates.length + data.ndt.length + (data.lih?.line_count ?? 0),
      well_id: request.well.id,
      date_from: data.dateFrom || null,
      date_to: data.dateTo,
      include_draft: data.includeDraft,
    }),
  }).catch(() => undefined)
}
