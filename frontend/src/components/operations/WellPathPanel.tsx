import { useEffect, useState } from 'react'
import { Link } from 'react-router-dom'
import { Alert, Box, Stack, Typography } from '@mui/material'
import { WellDiagram } from './WellDiagram'
import { SectionCard } from '../ui/SectionCard'
import { opsWellPath, type OpsWellPath } from '../../lib/operations'

/**
 * The well picture a page embeds: schematic, vertical section and the depth KPI,
 * all read from `GET /operations/well-path` so a drawing and the number beside
 * it cannot disagree.
 *
 * It owns its fetch because the dashboard's own payload carries a lighter
 * `well_visual` (no trajectory); loading the full path here keeps one source for
 * every depth on the screen. A failure is shown in place, never swallowed: a
 * blank panel would read as "no data" when the truth may be "no access".
 */
export function WellPathPanel({
  well,
  scope,
  canOpenPath = false,
  height = 430,
  title,
}: {
  well: string
  scope: string
  canOpenPath?: boolean
  height?: number
  title?: string
}) {
  const [path, setPath] = useState<OpsWellPath | null>(null)
  const [error, setError] = useState('')

  useEffect(() => {
    let current = true
    setPath(null)
    setError('')
    opsWellPath(well, scope)
      .then((d) => {
        if (current) setPath(d)
      })
      .catch((e) => {
        if (current) setError((e as Error).message)
      })
    return () => {
      current = false
    }
  }, [well, scope])

  const summary = path?.summary
  const deepest = path?.sections.length ? path.sections[path.sections.length - 1] : null
  const rows: [string, string][] = [
    ['Hole depth (marker)', fmt(summary?.current_md_m, 'm')],
    ['Marker TVD', fmt(summary?.current_tvd_m, 'm')],
    ['Survey endpoint', fmt(path?.position.survey_end_md_m, 'm')],
    ['Bit / string depth', fmt(summary?.bit_depth_m, 'm')],
    ['Last casing', deepest ? `${deepest.casing_label} @ ${fmt(deepest.to_depth_m, 'm')}` : '—'],
    ['Open hole', path?.open_hole ? `${fmt(path.open_hole.from_depth_m)} → ${fmt(path.open_hole.to_depth_m, 'm')}` : '—'],
    ['Max inclination', summary?.max_inc_deg === null || summary?.max_inc_deg === undefined ? '—' : `${summary.max_inc_deg.toFixed(1)}°`],
    ['Max DLS', summary?.max_dls_deg_per_30m === null || summary?.max_dls_deg_per_30m === undefined ? '—' : `${summary.max_dls_deg_per_30m.toFixed(2)} °/30 m`],
    ['Departure', fmt(summary?.departure_m, 'm')],
  ]

  return (
    <SectionCard
      title={title ?? `Well diagram — ${path?.well_code ?? ''} (${scope})`}
      subtitle="Drawn from this well's recorded surveys and casing seats. The marker is the closing measured depth of the latest verified report; the survey endpoint is the deepest station and is shown separately, because one is not evidence for the other."
      action={
        canOpenPath ? (
          <Box component={Link} to={`/operations/well-path?well=${encodeURIComponent(well)}&scope=${encodeURIComponent(scope)}`} sx={{ fontSize: 12.5, fontWeight: 700 }}>
            Open well path
          </Box>
        ) : undefined
      }
    >
      {error && <Alert severity="error" sx={{ mb: 1.5 }}>{error}</Alert>}
      {path ? (
        <Box display="grid" gap={2} gridTemplateColumns={{ xs: '1fr', lg: 'minmax(0,3fr) minmax(0,2fr)' }}>
          <WellDiagram path={path} height={height} />
          <Stack spacing={1}>
            {rows.map(([label, value]) => (
              <Box
                key={label}
                display="flex"
                justifyContent="space-between"
                gap={1.5}
                sx={{ borderBottom: 1, borderColor: 'divider', pb: 0.6 }}
              >
                <Typography fontSize={12.5} color="text.secondary">
                  {label}
                </Typography>
                <Typography fontSize={13} fontWeight={700} textAlign="right">
                  {value}
                </Typography>
              </Box>
            ))}
            <Typography variant="caption" color="text.secondary">
              Source: {summary?.depth_basis || 'no report yet'}
              {summary?.latest_report_date ? ` · ${summary.latest_report_date}` : ''} · TVD basis:{' '}
              {summary?.current_tvd_basis || '—'}
            </Typography>
            {Boolean(path.survey_discrepancies.length) && (
              <Alert severity="warning" sx={{ fontSize: 12 }}>
                {path.survey_discrepancies.length} survey station(s) print a TVD that contradicts the
                minimum-curvature integration. The drawing uses the integration; correct the printed value on the
                report if it is wrong.
              </Alert>
            )}
          </Stack>
        </Box>
      ) : !error ? (
        <Typography role="status" fontSize={12.5}>
          Loading the well diagram…
        </Typography>
      ) : null}
    </SectionCard>
  )
}

function fmt(value: number | null | undefined, unit = ''): string {
  if (typeof value !== 'number' || !Number.isFinite(value)) return '—'
  return `${value.toLocaleString(undefined, { maximumFractionDigits: 1, minimumFractionDigits: 1 })}${unit ? ` ${unit}` : ''}`
}

export default WellPathPanel
