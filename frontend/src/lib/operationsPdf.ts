import { api } from './api'
import { exportCsv } from './export'
import { detailSheet, writeWorkbook } from './matrixWorkbook'
import { auditSummaryExport, type OpsReport, type OpsWellSummary } from './operations'
import { formatWatDateTime, formatWatShort, WAT_LABEL, watTodayIso } from './time'

const fmtNum = (v: string | number | null | undefined, suffix = ''): string => {
  if (v === null || v === undefined || v === '') return '—'
  const n = Number(v)
  if (!Number.isFinite(n)) return String(v)
  const text = Number.isInteger(n) ? String(n) : n.toFixed(3).replace(/\.?0+$/, '')
  return `${text}${suffix}`
}

export async function printDailyReport(report: OpsReport, brief: string) {
  await api(`/operations/reports/${report.id}/print-audit${report.is_deleted ? '?include_deleted=true' : ''}`, {
    method: 'POST',
  })
  const { exportReportPdf } = await import('./reportPdf')
  const headerFacts: [string, string][] = [
    ['Well', `${report.well_code_snapshot} · ${report.well_name_snapshot}`],
    ['Rig / Scope', `${report.rig_code_snapshot || '—'} · ${report.scope}`],
    ['Report', `${report.report_type} ${report.report_no_text || '—'} (${report.report_date})`],
    ['Status', `${report.status}${report.reopen_reason ? ` (Reopened: ${report.reopen_reason})` : ''}`],
    [
      'Period (WAT)',
      `${formatWatShort(report.period_start_at) || '—'} → ${formatWatShort(report.period_end_at) || '—'} (${report.period_minutes} min)`,
    ],
    [
      'Measured Depth (MD)',
      `${fmtNum(report.depth_start_m, ' m')} → ${fmtNum(report.depth_end_m, ' m')} (Progress: ${fmtNum(report.progress_m, ' m')})`,
    ],
    [
      'True Vertical Depth (TVD)',
      `${fmtNum(report.tvd_start_m, ' m')} → ${fmtNum(report.tvd_m, ' m')}${report.tvd_source ? ` [${report.tvd_source}]` : ''}`,
    ],
    [
      'Bit Depth / Auth. TD',
      `${fmtNum(report.bit_depth_m, ' m')} / ${fmtNum(report.md_auth_m, ' m')}`,
    ],
    [
      'Hole Section / Last Casing',
      `${report.hole_section_text || (report.hole_size_in ? `${fmtNum(report.hole_size_in)}"` : '—')} · ${report.last_casing_size_in ? `${fmtNum(report.last_casing_size_in)}" @ ${fmtNum(report.last_casing_depth_m, ' m')}` : '—'}`,
    ],
    [
      'Rotating Hrs / DFS / POB',
      `${fmtNum(report.rotating_hours, ' h')} (Cum ${fmtNum(report.cum_rotating_hours, ' h')}) · DFS ${fmtNum(report.dfs_days, ' d')} · POB ${report.pob_count ?? '—'}`,
    ],
    [
      'Mud Properties',
      report.mud_type || report.mud_weight_ppg
        ? `${report.mud_type || 'Mud'} · MW ${fmtNum(report.mud_weight_ppg, ' ppg')} · FV ${fmtNum(report.mud_viscosity_sec, ' s/qt')} · PV/YP ${fmtNum(report.mud_pv_cp)}/${fmtNum(report.mud_yp_lbf)}`
        : '—',
    ],
    ['BHA / Personnel', `${report.bha_summary || '—'}${report.supervisor ? ` · Supv: ${report.supervisor}` : ''}`],
  ]

  const narrativeNotes: string[] = []
  if (report.current_status) narrativeNotes.push(`Current Status: ${report.current_status}`)
  if (report.operation_summary) narrativeNotes.push(`24-Hr Operation Summary: ${report.operation_summary}`)
  if (report.forward_plan) narrativeNotes.push(`24-Hr Forecast / Planned Operations: ${report.forward_plan}`)
  if (report.hse_summary) narrativeNotes.push(`HSE & Safety Summary: ${report.hse_summary}`)
  if (report.remarks) narrativeNotes.push(`Engineer Remarks: ${report.remarks}`)

  await exportReportPdf({
    fileName: `${report.well_code_snapshot}-${report.report_type}-${report.report_date}`,
    title: `${report.report_type} ${report.report_no_text} · ${report.report_date}`,
    scope: `${report.rig_code_snapshot} / ${report.well_code_snapshot} / ${report.scope}`,
    notices: [
      `Status: ${report.is_deleted ? 'Deleted · ' : ''}${report.status}. All timestamps in ${WAT_LABEL}; depths in metres.`,
    ],
    sections: [
      {
        title: 'Wellbore, Depth & Fluid Summary',
        tables: [{ head: ['Parameter', 'Recorded Value'], body: headerFacts, wide: [1] }],
      },
      { title: 'Daily Engineering Brief', notes: brief.split('\n').filter(Boolean) },
      ...(narrativeNotes.length ? [{ title: 'Engineer Narratives & Forecast', notes: narrativeNotes }] : []),
      {
        title: `Activity Log (${WAT_LABEL})`,
        tables: [
          {
            head: [
              'From (WAT)',
              'To (WAT)',
              'Min',
              'Class',
              'Alloc',
              'MD (m)',
              'TVD (m)',
              'Vendor',
              'Activity',
              'Operation',
            ],
            body: report.blocks.map((b) => [
              formatWatShort(b.started_at),
              formatWatShort(b.ended_at),
              b.duration_minutes,
              b.classification,
              b.allocation,
              b.depth_from_m || b.depth_to_m ? `${fmtNum(b.depth_from_m)}–${fmtNum(b.depth_to_m)}` : '—',
              b.tvd_from_m || b.tvd_to_m ? `${fmtNum(b.tvd_from_m)}–${fmtNum(b.tvd_to_m)}` : '—',
              b.responsible_party || '—',
              b.source_activity_label || b.source_activity_code || '—',
              b.narrative,
            ]),
            wide: [8, 9],
          },
        ],
      },
      {
        title: 'Directional Surveys',
        tables: [
          {
            head: [
              'MD (m)',
              'TVD (m)',
              'Incl. (°)',
              'Azimuth (°)',
              'N/S (m)',
              'E/W (m)',
              'V. section (m)',
              'Dogleg (°/30 m)',
            ],
            body: report.surveys.map((s) =>
              (['md_m', 'tvd_m', 'inc_deg', 'azi_deg', 'ns_m', 'ew_m', 'vsec_m', 'dls_deg_per_30m'] as const).map(
                (k) => s[k] ?? '—',
              ),
            ),
          },
        ],
      },
      { title: 'Source Documents', notes: report.sources.map((d) => d.file_name) },
    ],
  })
}

function summaryBaseName(summary: OpsWellSummary): string {
  const safeWell = (summary.well_code || 'well').replace(/[^a-zA-Z0-9_-]+/g, '-')
  const safeScope = (summary.scope_label || 'all').toLowerCase().replace(/[^a-z0-9]+/g, '-')
  return `${safeWell}-operation-summary-${safeScope}`
}

/** Export the complete multi-day Well Operation Summary as a structured PDF report. */
export async function exportWellSummaryPdf(summary: OpsWellSummary) {
  const rowCount = summary.activities.length || summary.daily_rollup.length
  await auditSummaryExport('pdf', rowCount)
  const { exportReportPdf } = await import('./reportPdf')
  const k = summary.kpis
  const overviewRows: [string, string][] = [
    ['Well', `${summary.well_code} — ${summary.well_name}`],
    ['Rig / Block / Field', `${summary.rig_code || '—'} · ${summary.block_text || '—'} · ${summary.field_site || '—'}`],
    ['Operator / UWI / Datum', `${summary.customer || '—'} · UWI: ${summary.uwi || '—'} · Datum: ${summary.datum || '—'}`],
    ['Scope & Window', `${summary.scope_label} · ${summary.first_report_date || '—'} to ${summary.last_report_date || '—'} (Spud: ${summary.spud_date || '—'})`],
    ['Report Count', `${k.total_reports} total (${k.approved_reports} approved, ${k.submitted_reports} submitted, ${k.draft_reports} draft; ${k.drilling_reports} drilling, ${k.completion_reports} completion)`],
    ['Logged Time vs Baseline', `${fmtNum(k.total_logged_hours, ' h')} (${fmtNum(k.total_logged_days, ' d')}) · Baseline: ${fmtNum(k.planned_days, ' d')} · Variance: ${fmtNum(k.schedule_variance_days, ' d')}`],
    ['Time Allocation', `PT ${fmtNum(k.pt_hours, ' h')} (${k.productive_pct}%) · UPA ${fmtNum(k.upa_hours, ' h')} (${k.upa_pct}%) · NPT ${fmtNum(k.npt_hours, ' h')} (${k.npt_pct}%) · SP ${fmtNum(k.sp_hours, ' h')} (${k.sp_pct}%)`],
    ['Measured Depth (MD)', `Start ${fmtNum(k.start_md_m, ' m')} · Current ${fmtNum(k.current_md_m, ' m')} · Max ${fmtNum(k.max_md_m, ' m')} · Auth TD ${fmtNum(k.authorized_md_m, ' m')}`],
    ['True Vertical Depth (TVD) & Bit', `Current TVD ${fmtNum(k.current_tvd_m, ' m')} · Max TVD ${fmtNum(k.max_tvd_m, ' m')} · Latest Bit ${fmtNum(k.latest_bit_depth_m, ' m')}`],
    [
      'Drilling Performance',
      k.completion_reports > 0 && k.drilling_reports === 0
        ? 'Avg ROP N/A (completion operation)'
        : `Footage ${fmtNum(k.total_footage_m, ' m')} · Rotating ${fmtNum(k.total_rotating_hours, ' h')} · Avg ROP ${fmtNum(k.avg_rop_m_per_hr, ' m/h')}`,
    ],
    ['Hole / Casing / Mud', `${summary.latest_hole_section || '—'} · Casing: ${summary.last_casing || '—'} · Mud: ${summary.latest_mud || '—'}`],
    ['Latest BHA / Status / POB', `${summary.latest_bha || '—'} · ${summary.latest_status || '—'} · POB: ${k.latest_pob ?? '—'}`],
  ]

  await exportReportPdf({
    fileName: summaryBaseName(summary),
    title: `Well Operation Summary · ${summary.well_code} (${summary.well_name})`,
    scope: `${summary.rig_code || 'Rig —'} · ${summary.scope_label} · ${summary.timezone_label}`,
    notices: [
      `Generated ${formatWatDateTime(summary.generated_at)} (${summary.timezone_label}). ${summary.include_drafts ? 'Includes draft, submitted and approved reports.' : 'Submitted and approved reports only.'} Depths in metres.`,
    ],
    sections: [
      {
        title: '1. Well Identification & Cumulative KPIs',
        tables: [{ head: ['Metric', 'Value'], body: overviewRows, wide: [1] }],
      },
      {
        title: '2. Daily Report Rollup',
        tables: [
          {
            head: [
              'Date',
              'Type / #',
              'Status',
              'Section',
              'Start MD',
              'End MD',
              'TVD (m)',
              'Prog (m)',
              'ROP (m/h)',
              'MW (ppg)',
              'Hrs',
              'PT (h)',
              'NPT (h)',
              '24-Hr Summary',
            ],
            body: summary.daily_rollup.map((d) => [
              d.report_date,
              `${d.report_type} ${d.report_no || ''}`.trim(),
              d.status,
              d.hole_section || '—',
              fmtNum(d.depth_start_m),
              fmtNum(d.depth_end_m),
              fmtNum(d.tvd_m),
              fmtNum(d.progress_m),
              d.scope === 'completion' ? 'N/A' : fmtNum(d.rop_m_per_hr),
              fmtNum(d.mud_weight_ppg),
              fmtNum(d.logged_hours),
              fmtNum(d.pt_hours),
              fmtNum(d.npt_hours),
              d.operation_summary || d.current_status || '—',
            ]),
            wide: [13],
          },
        ],
      },
      {
        title: '3. PT / UPA / NPT / SP Breakdown by Agency & Code',
        tables: [
          {
            head: ['Class', 'Alloc', 'Agency / Vendor', 'Code', 'Cause', 'Events', 'Hours', 'Days', '% Total', '% NPT', 'Sample Reason'],
            body: summary.pt_npt_breakdown.map((r) => [
              r.classification,
              r.allocation,
              r.responsible_party,
              r.code,
              r.cause_code || '—',
              r.events,
              fmtNum(r.hours),
              fmtNum(r.days),
              `${r.pct_of_total}%`,
              r.allocation === 'NPT' ? `${r.pct_of_npt}%` : '—',
              r.sample_reason || '—',
            ]),
            wide: [2, 10],
          },
        ],
      },
      {
        title: '4. Phase & Hole Section Summary',
        tables: [
          {
            head: ['Phase', 'Hole Section', 'Blocks', 'Hours', 'Days', 'PT (h)', 'UPA (h)', 'NPT (h)', 'Prod %', 'Max MD (m)', 'Max TVD (m)', 'Footage (m)'],
            body: summary.phase_breakdown.map((p) => [
              p.phase,
              p.hole_section,
              p.events,
              fmtNum(p.total_hours),
              fmtNum(p.total_days),
              fmtNum(p.pt_hours),
              fmtNum(p.upa_hours),
              fmtNum(p.npt_hours),
              `${p.productive_pct}%`,
              fmtNum(p.max_md_m),
              fmtNum(p.max_tvd_m),
              fmtNum(p.footage_m),
            ]),
          },
        ],
      },
      {
        title: `5. Chronological Activity Log (${summary.timezone_label})`,
        tables: [
          {
            head: ['#', 'From (WAT)', 'To (WAT)', 'Hrs', 'Cum d', 'Phase', 'Class/Alloc', 'Agency', 'MD (m)', 'TVD (m)', 'Operation'],
            body: summary.activities.map((a) => [
              a.line_no,
              a.start_wat,
              a.end_wat,
              fmtNum(a.duration_hours),
              fmtNum(a.cum_days),
              a.phase_code || '—',
              `${a.classification}/${a.allocation}`,
              a.responsible_party || '—',
              a.depth_from_m != null || a.depth_to_m != null ? `${fmtNum(a.depth_from_m)}–${fmtNum(a.depth_to_m)}` : '—',
              a.tvd_from_m != null || a.tvd_to_m != null ? `${fmtNum(a.tvd_from_m)}–${fmtNum(a.tvd_to_m)}` : '—',
              a.narrative,
            ]),
            wide: [7, 10],
          },
        ],
      },
      ...(summary.surveys.length
        ? [
            {
              title: '6. Directional Survey History',
              tables: [
                {
                  head: ['Date', 'Report #', 'MD (m)', 'TVD (m)', 'Inc (°)', 'Azi (°)', 'N/S (m)', 'E/W (m)', 'V.Sec (m)', 'DLS (°/30m)', 'Tool'],
                  body: summary.surveys.map((s) => [
                    s.report_date,
                    s.report_no || '—',
                    fmtNum(s.md_m),
                    fmtNum(s.tvd_m),
                    fmtNum(s.inc_deg),
                    fmtNum(s.azi_deg),
                    fmtNum(s.ns_m),
                    fmtNum(s.ew_m),
                    fmtNum(s.vsec_m),
                    fmtNum(s.dls_deg_per_30m),
                    s.tool || '—',
                  ]),
                },
              ],
            },
          ]
        : []),
    ],
  })
}

/** Export the complete multi-day Well Operation Summary as a 6-sheet .xlsx workbook. */
export async function exportWellSummaryXlsx(summary: OpsWellSummary) {
  const rowCount = summary.activities.length || summary.daily_rollup.length
  await auditSummaryExport('xlsx', rowCount)
  const k = summary.kpis
  const overviewRecords = [
    { metric: 'Generated At (WAT)', value: formatWatDateTime(summary.generated_at) },
    { metric: 'Timezone', value: `${summary.timezone} — ${summary.timezone_label}` },
    { metric: 'Well Code', value: summary.well_code },
    { metric: 'Well Name', value: summary.well_name },
    { metric: 'Rig', value: `${summary.rig_code} ${summary.rig_name}`.trim() },
    { metric: 'Block / Field', value: [summary.block_text, summary.field_site].filter(Boolean).join(' · ') },
    { metric: 'Operator / Customer', value: summary.customer },
    { metric: 'UWI', value: summary.uwi },
    { metric: 'Depth Datum', value: summary.datum },
    { metric: 'Scope', value: summary.scope_label },
    { metric: 'Spud Date', value: summary.spud_date || '' },
    { metric: 'First Report Date', value: summary.first_report_date || '' },
    { metric: 'Last Report Date', value: summary.last_report_date || '' },
    { metric: 'Total Daily Reports', value: String(k.total_reports) },
    { metric: 'Approved / Submitted / Draft', value: `${k.approved_reports} / ${k.submitted_reports} / ${k.draft_reports}` },
    { metric: 'Total Activity Blocks', value: String(k.total_blocks) },
    { metric: 'Total Logged Hours', value: String(k.total_logged_hours) },
    { metric: 'Total Logged Days', value: String(k.total_logged_days) },
    { metric: 'Active Baseline Planned Days', value: k.planned_days != null ? String(k.planned_days) : '' },
    { metric: 'Schedule Variance Days', value: k.schedule_variance_days != null ? String(k.schedule_variance_days) : '' },
    { metric: 'Productive Hours (PT)', value: String(k.pt_hours) },
    { metric: 'Unplanned Activity Hours (UPA)', value: String(k.upa_hours) },
    { metric: 'Non-Productive Hours (NPT)', value: String(k.npt_hours) },
    { metric: 'Slow Progress Hours (SP)', value: String(k.sp_hours) },
    { metric: 'Productive Time %', value: `${k.productive_pct}%` },
    { metric: 'NPT %', value: `${k.npt_pct}%` },
    { metric: 'Opening MD (m)', value: k.start_md_m != null ? String(k.start_md_m) : '' },
    { metric: 'Current MD (m)', value: k.current_md_m != null ? String(k.current_md_m) : '' },
    { metric: 'Max MD (m)', value: k.max_md_m != null ? String(k.max_md_m) : '' },
    { metric: 'Authorized MD (m)', value: k.authorized_md_m != null ? String(k.authorized_md_m) : '' },
    { metric: 'Current TVD (m)', value: k.current_tvd_m != null ? String(k.current_tvd_m) : '' },
    { metric: 'Max TVD (m)', value: k.max_tvd_m != null ? String(k.max_tvd_m) : '' },
    { metric: 'Latest Bit Depth (m)', value: k.latest_bit_depth_m != null ? String(k.latest_bit_depth_m) : '' },
    { metric: 'Total Footage Drilled (m)', value: String(k.total_footage_m) },
    { metric: 'Total Rotating Hours', value: String(k.total_rotating_hours) },
    {
      metric: 'Average ROP (m/hr)',
      value:
        k.completion_reports > 0 && k.drilling_reports === 0
          ? 'N/A'
          : k.avg_rop_m_per_hr != null
            ? String(k.avg_rop_m_per_hr)
            : '',
    },
    { metric: 'Latest Hole Section', value: summary.latest_hole_section },
    { metric: 'Last Casing Shoe', value: summary.last_casing },
    { metric: 'Latest Mud System', value: summary.latest_mud },
    { metric: 'Latest BHA', value: summary.latest_bha },
    { metric: 'Latest Status', value: summary.latest_status },
    { metric: 'Directional Surveys', value: String(k.survey_count) },
    { metric: 'Max Inclination (deg)', value: k.max_inc_deg != null ? String(k.max_inc_deg) : '' },
    { metric: 'Max Dogleg (deg/30m)', value: k.max_dls_deg_per_30m != null ? String(k.max_dls_deg_per_30m) : '' },
  ]

  const sheets = [
    detailSheet(
      'Overview & KPIs',
      [
        { key: 'metric', label: 'Parameter / KPI' },
        { key: 'value', label: 'Recorded Value' },
      ],
      overviewRecords,
    ),
    detailSheet(
      'Operations Log',
      [
        { key: 'line_no', label: 'Line', numeric: true },
        { key: 'report_date', label: 'Report Date' },
        { key: 'scope', label: 'Scope' },
        { key: 'report_type', label: 'Type' },
        { key: 'report_no', label: 'Report #' },
        { key: 'report_status', label: 'Status' },
        { key: 'day_number', label: 'Day #', numeric: true },
        { key: 'start_wat', label: 'From (WAT)' },
        { key: 'end_wat', label: 'To (WAT)' },
        { key: 'duration_hours', label: 'Hrs', numeric: true },
        { key: 'cum_hours', label: 'Cum Hrs', numeric: true },
        { key: 'cum_days', label: 'Cum Days', numeric: true },
        { key: 'hole_section', label: 'Hole Section' },
        { key: 'phase_code', label: 'Phase' },
        { key: 'operation_code', label: 'Operation Code' },
        { key: 'activity_code', label: 'Activity Code' },
        { key: 'classification', label: 'Class' },
        { key: 'allocation', label: 'Allocation' },
        { key: 'npt_code', label: 'NPT Code' },
        { key: 'cause_code', label: 'Cause' },
        { key: 'responsible_party', label: 'Agency / Vendor' },
        { key: 'depth_from_m', label: 'MD From (m)', numeric: true },
        { key: 'depth_to_m', label: 'MD To (m)', numeric: true },
        { key: 'tvd_from_m', label: 'TVD From (m)', numeric: true },
        { key: 'tvd_to_m', label: 'TVD To (m)', numeric: true },
        { key: 'bit_depth_m', label: 'Bit Depth (m)', numeric: true },
        { key: 'footage_m', label: 'Footage (m)', numeric: true },
        { key: 'rotating_hours', label: 'Rot Hrs', numeric: true },
        { key: 'rop_m_per_hr', label: 'ROP (m/h)' },
        { key: 'mud_weight_ppg', label: 'MW (ppg)', numeric: true },
        { key: 'reason', label: 'NPT / Delay Reason' },
        { key: 'narrative', label: 'Operation Description' },
      ],
      summary.activities.map((a) => ({
        ...a,
        rop_m_per_hr: a.scope === 'completion' ? 'N/A' : a.rop_m_per_hr,
      })) as unknown as Record<string, unknown>[],
    ),
    detailSheet(
      'Daily Rollup',
      [
        { key: 'report_date', label: 'Date' },
        { key: 'scope', label: 'Scope' },
        { key: 'report_type', label: 'Type' },
        { key: 'report_no', label: 'Report #' },
        { key: 'day_number', label: 'Day #', numeric: true },
        { key: 'dfs_days', label: 'DFS (d)', numeric: true },
        { key: 'status', label: 'Status' },
        { key: 'hole_section', label: 'Hole Section' },
        { key: 'depth_start_m', label: 'Start MD (m)', numeric: true },
        { key: 'depth_end_m', label: 'End MD (m)', numeric: true },
        { key: 'tvd_start_m', label: 'Start TVD (m)', numeric: true },
        { key: 'tvd_m', label: 'End TVD (m)', numeric: true },
        { key: 'tvd_source', label: 'TVD Basis' },
        { key: 'bit_depth_m', label: 'Bit Depth (m)', numeric: true },
        { key: 'progress_m', label: 'Progress (m)', numeric: true },
        { key: 'rotating_hours', label: 'Rot Hrs', numeric: true },
        { key: 'rop_m_per_hr', label: 'ROP (m/h)' },
        { key: 'mud_type', label: 'Mud Type' },
        { key: 'mud_weight_ppg', label: 'MW (ppg)', numeric: true },
        { key: 'last_casing', label: 'Last Casing' },
        { key: 'pob_count', label: 'POB', numeric: true },
        { key: 'logged_hours', label: 'Logged Hrs', numeric: true },
        { key: 'pt_hours', label: 'PT Hrs', numeric: true },
        { key: 'upa_hours', label: 'UPA Hrs', numeric: true },
        { key: 'npt_hours', label: 'NPT Hrs', numeric: true },
        { key: 'sp_hours', label: 'SP Hrs', numeric: true },
        { key: 'productive_pct', label: 'Prod %', numeric: true },
        { key: 'current_status', label: 'Current Status' },
        { key: 'operation_summary', label: '24-Hr Operation Summary' },
        { key: 'forward_plan', label: '24-Hr Forecast' },
        { key: 'hse_summary', label: 'HSE Summary' },
      ],
      summary.daily_rollup.map((d) => ({
        ...d,
        rop_m_per_hr: d.scope === 'completion' ? 'N/A' : d.rop_m_per_hr,
      })) as unknown as Record<string, unknown>[],
    ),
    detailSheet(
      'PT-NPT Breakdown',
      [
        { key: 'classification', label: 'Classification' },
        { key: 'allocation', label: 'Allocation' },
        { key: 'responsible_party', label: 'Agency / Vendor' },
        { key: 'code', label: 'Code' },
        { key: 'cause_code', label: 'Cause' },
        { key: 'events', label: 'Events', numeric: true },
        { key: 'hours', label: 'Hours', numeric: true },
        { key: 'days', label: 'Days', numeric: true },
        { key: 'pct_of_total', label: '% Total Time', numeric: true },
        { key: 'pct_of_npt', label: '% NPT', numeric: true },
        { key: 'sample_reason', label: 'Sample Reason' },
      ],
      summary.pt_npt_breakdown as unknown as Record<string, unknown>[],
    ),
    detailSheet(
      'Phase Summary',
      [
        { key: 'phase', label: 'Phase' },
        { key: 'hole_section', label: 'Hole Section' },
        { key: 'events', label: 'Blocks', numeric: true },
        { key: 'total_hours', label: 'Total Hrs', numeric: true },
        { key: 'total_days', label: 'Total Days', numeric: true },
        { key: 'pt_hours', label: 'PT Hrs', numeric: true },
        { key: 'upa_hours', label: 'UPA Hrs', numeric: true },
        { key: 'npt_hours', label: 'NPT Hrs', numeric: true },
        { key: 'sp_hours', label: 'SP Hrs', numeric: true },
        { key: 'productive_pct', label: 'Productive %', numeric: true },
        { key: 'max_md_m', label: 'Max MD (m)', numeric: true },
        { key: 'max_tvd_m', label: 'Max TVD (m)', numeric: true },
        { key: 'footage_m', label: 'Footage (m)', numeric: true },
      ],
      summary.phase_breakdown as unknown as Record<string, unknown>[],
    ),
    detailSheet(
      'Surveys',
      [
        { key: 'report_date', label: 'Date' },
        { key: 'report_no', label: 'Report #' },
        { key: 'scope', label: 'Scope' },
        { key: 'md_m', label: 'MD (m)', numeric: true },
        { key: 'tvd_m', label: 'TVD (m)', numeric: true },
        { key: 'inc_deg', label: 'Inc (deg)', numeric: true },
        { key: 'azi_deg', label: 'Azi (deg)', numeric: true },
        { key: 'ns_m', label: 'N/S (m)', numeric: true },
        { key: 'ew_m', label: 'E/W (m)', numeric: true },
        { key: 'vsec_m', label: 'V.Sec (m)', numeric: true },
        { key: 'dls_deg_per_30m', label: 'DLS (deg/30m)', numeric: true },
        { key: 'tool', label: 'Tool' },
      ],
      summary.surveys as unknown as Record<string, unknown>[],
    ),
  ]

  await writeWorkbook(`${summaryBaseName(summary)}-${watTodayIso()}.xlsx`, sheets)
}

/** Export the complete multi-day Well Operation Summary as a formula-safe CSV file. */
export async function exportWellSummaryCsv(summary: OpsWellSummary, tab: 'activities' | 'daily' | 'breakdown' | 'phases' | 'surveys' = 'activities') {
  const stamp = watTodayIso()
  const base = summaryBaseName(summary)
  const str = (v: unknown) => (v === null || v === undefined ? '' : String(v))

  if (tab === 'daily') {
    await auditSummaryExport('csv', summary.daily_rollup.length)
    exportCsv(`${base}-daily-rollup-${stamp}.csv`, summary.daily_rollup, [
      { header: 'Well Code', value: () => summary.well_code },
      { header: 'Report Date', value: (r) => r.report_date },
      { header: 'Scope', value: (r) => r.scope },
      { header: 'Type', value: (r) => r.report_type },
      { header: 'Report #', value: (r) => r.report_no },
      { header: 'Day #', value: (r) => str(r.day_number) },
      { header: 'DFS (d)', value: (r) => str(r.dfs_days) },
      { header: 'Status', value: (r) => r.status },
      { header: 'Hole Section', value: (r) => r.hole_section },
      { header: 'Start MD (m)', value: (r) => str(r.depth_start_m) },
      { header: 'End MD (m)', value: (r) => str(r.depth_end_m) },
      { header: 'Start TVD (m)', value: (r) => str(r.tvd_start_m) },
      { header: 'End TVD (m)', value: (r) => str(r.tvd_m) },
      { header: 'TVD Basis', value: (r) => r.tvd_source },
      { header: 'Bit Depth (m)', value: (r) => str(r.bit_depth_m) },
      { header: 'Progress (m)', value: (r) => str(r.progress_m) },
      { header: 'Rotating Hrs', value: (r) => str(r.rotating_hours) },
      { header: 'ROP (m/hr)', value: (r) => (r.scope === 'completion' ? 'N/A' : str(r.rop_m_per_hr)) },
      { header: 'Mud Type', value: (r) => r.mud_type },
      { header: 'MW (ppg)', value: (r) => str(r.mud_weight_ppg) },
      { header: 'Last Casing', value: (r) => r.last_casing },
      { header: 'POB', value: (r) => str(r.pob_count) },
      { header: 'Logged Hrs', value: (r) => str(r.logged_hours) },
      { header: 'PT Hrs', value: (r) => str(r.pt_hours) },
      { header: 'UPA Hrs', value: (r) => str(r.upa_hours) },
      { header: 'NPT Hrs', value: (r) => str(r.npt_hours) },
      { header: 'SP Hrs', value: (r) => str(r.sp_hours) },
      { header: 'Productive %', value: (r) => str(r.productive_pct) },
      { header: '24-Hr Operation Summary', value: (r) => r.operation_summary },
      { header: '24-Hr Forecast', value: (r) => r.forward_plan },
      { header: 'HSE Summary', value: (r) => r.hse_summary },
    ])
    return
  }

  if (tab === 'breakdown') {
    await auditSummaryExport('csv', summary.pt_npt_breakdown.length)
    exportCsv(`${base}-pt-npt-breakdown-${stamp}.csv`, summary.pt_npt_breakdown, [
      { header: 'Well Code', value: () => summary.well_code },
      { header: 'Classification', value: (r) => r.classification },
      { header: 'Allocation', value: (r) => r.allocation },
      { header: 'Agency / Vendor', value: (r) => r.responsible_party },
      { header: 'Code', value: (r) => r.code },
      { header: 'Cause', value: (r) => r.cause_code },
      { header: 'Events', value: (r) => str(r.events) },
      { header: 'Hours', value: (r) => str(r.hours) },
      { header: 'Days', value: (r) => str(r.days) },
      { header: '% Total Time', value: (r) => str(r.pct_of_total) },
      { header: '% NPT', value: (r) => str(r.pct_of_npt) },
      { header: 'Sample Reason', value: (r) => r.sample_reason },
    ])
    return
  }

  if (tab === 'phases') {
    await auditSummaryExport('csv', summary.phase_breakdown.length)
    exportCsv(`${base}-phase-summary-${stamp}.csv`, summary.phase_breakdown, [
      { header: 'Well Code', value: () => summary.well_code },
      { header: 'Phase', value: (r) => r.phase },
      { header: 'Hole Section', value: (r) => r.hole_section },
      { header: 'Blocks', value: (r) => str(r.events) },
      { header: 'Total Hrs', value: (r) => str(r.total_hours) },
      { header: 'Total Days', value: (r) => str(r.total_days) },
      { header: 'PT Hrs', value: (r) => str(r.pt_hours) },
      { header: 'UPA Hrs', value: (r) => str(r.upa_hours) },
      { header: 'NPT Hrs', value: (r) => str(r.npt_hours) },
      { header: 'SP Hrs', value: (r) => str(r.sp_hours) },
      { header: 'Productive %', value: (r) => str(r.productive_pct) },
      { header: 'Max MD (m)', value: (r) => str(r.max_md_m) },
      { header: 'Max TVD (m)', value: (r) => str(r.max_tvd_m) },
      { header: 'Footage (m)', value: (r) => str(r.footage_m) },
    ])
    return
  }

  if (tab === 'surveys') {
    await auditSummaryExport('csv', summary.surveys.length)
    exportCsv(`${base}-surveys-${stamp}.csv`, summary.surveys, [
      { header: 'Well Code', value: () => summary.well_code },
      { header: 'Report Date', value: (r) => r.report_date },
      { header: 'Report #', value: (r) => r.report_no },
      { header: 'Scope', value: (r) => r.scope },
      { header: 'MD (m)', value: (r) => str(r.md_m) },
      { header: 'TVD (m)', value: (r) => str(r.tvd_m) },
      { header: 'Inc (deg)', value: (r) => str(r.inc_deg) },
      { header: 'Azi (deg)', value: (r) => str(r.azi_deg) },
      { header: 'N/S (m)', value: (r) => str(r.ns_m) },
      { header: 'E/W (m)', value: (r) => str(r.ew_m) },
      { header: 'V.Sec (m)', value: (r) => str(r.vsec_m) },
      { header: 'DLS (deg/30m)', value: (r) => str(r.dls_deg_per_30m) },
      { header: 'Tool', value: (r) => r.tool },
    ])
    return
  }

  await auditSummaryExport('csv', summary.activities.length)
  exportCsv(`${base}-operations-log-${stamp}.csv`, summary.activities, [
    { header: 'Line', value: (r) => str(r.line_no) },
    { header: 'Well Code', value: () => summary.well_code },
    { header: 'Rig Code', value: () => summary.rig_code },
    { header: 'Report Date', value: (r) => r.report_date },
    { header: 'Scope', value: (r) => r.scope },
    { header: 'Report Type', value: (r) => r.report_type },
    { header: 'Report #', value: (r) => r.report_no },
    { header: 'Report Status', value: (r) => r.report_status },
    { header: 'Day #', value: (r) => str(r.day_number) },
    { header: 'From (WAT UTC+1:00)', value: (r) => r.start_wat },
    { header: 'To (WAT UTC+1:00)', value: (r) => r.end_wat },
    { header: 'Duration (min)', value: (r) => str(r.duration_minutes) },
    { header: 'Duration (hrs)', value: (r) => str(r.duration_hours) },
    { header: 'Cumulative (hrs)', value: (r) => str(r.cum_hours) },
    { header: 'Cumulative (days)', value: (r) => str(r.cum_days) },
    { header: 'Hole Section', value: (r) => r.hole_section },
    { header: 'Phase', value: (r) => r.phase_code },
    { header: 'Operation Code', value: (r) => r.operation_code },
    { header: 'Activity Code', value: (r) => r.activity_code },
    { header: 'Classification', value: (r) => r.classification },
    { header: 'Allocation', value: (r) => r.allocation },
    { header: 'NPT Code', value: (r) => r.npt_code },
    { header: 'Cause', value: (r) => r.cause_code },
    { header: 'Agency / Vendor', value: (r) => r.responsible_party },
    { header: 'MD From (m)', value: (r) => str(r.depth_from_m) },
    { header: 'MD To (m)', value: (r) => str(r.depth_to_m) },
    { header: 'TVD From (m)', value: (r) => str(r.tvd_from_m) },
    { header: 'TVD To (m)', value: (r) => str(r.tvd_to_m) },
    { header: 'Bit Depth (m)', value: (r) => str(r.bit_depth_m) },
    { header: 'Footage (m)', value: (r) => str(r.footage_m) },
    { header: 'Rotating Hrs', value: (r) => str(r.rotating_hours) },
    { header: 'ROP (m/hr)', value: (r) => (r.scope === 'completion' ? 'N/A' : str(r.rop_m_per_hr)) },
    { header: 'Mud Weight (ppg)', value: (r) => str(r.mud_weight_ppg) },
    { header: 'Reason', value: (r) => r.reason },
    { header: 'Operation Description', value: (r) => r.narrative },
  ])
}
