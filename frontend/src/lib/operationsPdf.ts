import { api } from './api'
import type { OpsReport } from './operations'

export async function printDailyReport(report: OpsReport, brief: string) {
  await api(`/operations/reports/${report.id}/print-audit`, { method: 'POST' })
  const { exportReportPdf } = await import('./reportPdf')
  await exportReportPdf({
    fileName: `${report.well_code_snapshot}-${report.report_type}-${report.report_date}`,
    title: `${report.report_type} ${report.report_no_text} · ${report.report_date}`,
    scope: `${report.rig_code_snapshot} / ${report.well_code_snapshot} / ${report.scope}`,
    notices: [`Status: ${report.status}. Time log in UTC; depths in metres.`],
    sections: [
      { title: 'Daily brief', notes: brief.split('\n').filter(Boolean) },
      {
        title: 'Activity log',
        tables: [
          {
            head: ['From', 'To', 'Minutes', 'Class', 'Allocation', 'Vendor', 'Operation'],
            body: report.blocks.map((b) => [
              b.started_at.replace('T', ' ').slice(0, 16),
              b.ended_at.replace('T', ' ').slice(0, 16),
              b.duration_minutes,
              b.classification,
              b.allocation,
              b.responsible_party,
              b.narrative,
            ]),
            wide: [6],
          },
        ],
      },
      {
        title: 'Surveys',
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
      { title: 'Source documents', notes: report.sources.map((d) => d.file_name) },
    ],
  })
}
