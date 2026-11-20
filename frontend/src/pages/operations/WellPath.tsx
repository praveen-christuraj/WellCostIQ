import { useEffect, useMemo, useState } from 'react'
import { Link, useSearchParams } from 'react-router-dom'
import { Alert, Box, Button, Chip, MenuItem, Stack, TextField, Typography } from '@mui/material'
import { WellDiagram } from '../../components/operations/WellDiagram'
import { DataTable } from '../../components/DataTable'
import { ChartPanel } from '../../components/ui/ChartPanel'
import { InteractiveChart } from '../../components/ui/InteractiveChart'
import { SectionCard } from '../../components/ui/SectionCard'
import { StatCard } from '../../components/ui/StatCard'
import { ErrorMessage, PageHeading } from '../../components/Common'
import { useAuth } from '../../context/AuthContext'
import { useColorMode } from '../../context/ThemeContext'
import { chartPalette } from '../../designSystem'
import {
  opsScopeReference,
  opsWellPath,
  type OpsScopeReference,
  type OpsWellPath,
} from '../../lib/operations'

/**
 * Well path — the geometry of one well, drawn from its own record.
 *
 * Every number on this page comes from one service, `GET /operations/well-path`,
 * which reads the same surveys, casing seats and report headers that the daily
 * reports carry. Nothing here is interpolated from a template or a target:
 *
 * * the **schematic and vertical section** are the casing seats and the
 *   minimum-curvature integration, side by side on one depth axis;
 * * the **plan views** are the same stations plotted north/east, and against
 *   measured depth;
 * * the **station table** is the arithmetic a reader can check by hand;
 * * the **provenance panel** names what was assumed, what the configured
 *   intervals contributed and where a printed TVD disagrees with the
 *   integration — because a drawing that hides its gaps is worse than no
 *   drawing.
 *
 * The vertical-section plane defaults to the well's own closure azimuth. A
 * user can enter a reference azimuth (the plan requires one to compare wells)
 * and the curve is rebuilt in that plane; the choice is kept in the URL so a
 * shared link reproduces the same picture.
 */

const SCOPES = [
  { value: 'drilling', label: 'Drilling' },
  { value: 'completion', label: 'Completion' },
]

/** A depth or a dash: a zero is a real reading, a null is not. */
function m(value: number | null | undefined): string {
  return typeof value === 'number' && Number.isFinite(value)
    ? `${value.toLocaleString(undefined, { maximumFractionDigits: 1, minimumFractionDigits: 1 })}`
    : '—'
}

export default function OperationsWellPath() {
  const { can } = useAuth()
  const { mode } = useColorMode()
  const colors = chartPalette(mode)
  const [params, setParams] = useSearchParams()

  const [ref, setRef] = useState<OpsScopeReference | null>(null)
  const [path, setPath] = useState<OpsWellPath | null>(null)
  const [error, setError] = useState('')
  const [loading, setLoading] = useState(false)

  const well = params.get('well') ?? ''
  const scope = params.get('scope') === 'completion' ? 'completion' : 'drilling'
  const vsAzimuth = params.get('vs') ?? ''

  /** Filter changes go through the URL so the view is linkable and reloadable. */
  const setParam = (key: string, value: string, replace = false) => {
    const next = new URLSearchParams(params)
    if (value) next.set(key, value)
    else next.delete(key)
    // A scope change can invalidate the vertical-section override; the API
    // rebuilds the default plane anyway, so drop it to keep the picture honest.
    if (key === 'scope') next.delete('vs')
    setParams(next, { replace })
  }

  useEffect(() => {
    opsScopeReference()
      .then((r) => {
        setRef(r)
        // Land on a well that can actually be drawn in the requested scope, so
        // the page opens with a picture rather than an empty form.
        if (well && r.wells.some((w) => w.id === well)) return
        const usable = r.wells.find((w) =>
          scope === 'completion' ? w.completion_available : w.drilling_available,
        ) ?? r.wells[0]
        if (usable) {
          setParams((current) => {
            const next = new URLSearchParams(current)
            next.set('well', usable.id)
            if (!next.get('scope')) next.set('scope', 'drilling')
            return next
          }, { replace: true })
        }
      })
      .catch((e) => setError((e as Error).message))
    // Scope is read from the URL; a change of scope must not reset an explicit well.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [])

  useEffect(() => {
    let current = true
    setError('')
    if (!well) {
      setPath(null)
      return
    }
    setLoading(true)
    opsWellPath(well, scope, vsAzimuth === '' ? undefined : vsAzimuth)
      .then((d) => {
        if (current) setPath(d)
      })
      .catch((e) => {
        if (current) {
          setPath(null)
          setError((e as Error).message)
        }
      })
      .finally(() => {
        if (current) setLoading(false)
      })
    return () => {
      current = false
    }
  }, [well, scope, vsAzimuth])

  const curve = path?.curve ?? []
  const summary = path?.summary

  const base = {
    animation: false,
    textStyle: { color: colors.axis },
    tooltip: { trigger: 'axis', confine: true },
    grid: { left: 24, right: 34, top: 44, bottom: 40, containLabel: true },
    legend: { top: 2, type: 'scroll', textStyle: { color: colors.axis } },
  }

  /** Plan view: the stations as they sit on the ground, north up. */
  const planOption = useMemo(
    () => ({
      ...base,
      tooltip: { trigger: 'item', confine: true, formatter: (p: { data: { value: number[] } }) => `N ${p.data.value[0]} m · E ${p.data.value[1]} m` },
      xAxis: { type: 'value', name: 'East (m)', nameLocation: 'middle', nameGap: 26, scale: true },
      yAxis: { type: 'value', name: 'North (m)', scale: true },
      series: [
        {
          name: 'Actual',
          type: 'line',
          color: colors.actual,
          showSymbol: false,
          data: curve.map((station) => [station.ew_m, station.ns_m]),
          markPoint: curve.length
            ? {
                symbolSize: 8,
                itemStyle: { color: colors.actual },
                label: { show: false },
                data: [{ coord: [curve[curve.length - 1].ew_m, curve[curve.length - 1].ns_m], name: 'Current depth' }],
              }
            : undefined,
        },
        { name: 'Surface', type: 'scatter', color: colors.planned, symbolSize: 6, data: [[0, 0]] },
      ],
    }),
    // `base` is recreated per render; the curve and colours are what change.
    // eslint-disable-next-line react-hooks/exhaustive-deps
    [curve, colors.axis, colors.actual, colors.planned],
  )

  /** Inclination and dogleg along measured depth: the steering record. */
  const steeringOption = useMemo(
    () => ({
      ...base,
      tooltip: { trigger: 'axis', confine: true },
      xAxis: { type: 'value', name: 'MD (m)', nameLocation: 'middle', nameGap: 26, scale: true },
      yAxis: [
        { type: 'value', name: 'Inc (°)', min: 0, max: 120 },
        { type: 'value', name: 'DLS (°/30 m)', min: 0 },
      ],
      series: [
        { name: 'Inclination', type: 'line', color: colors.planned, showSymbol: false, data: curve.map((s) => [s.md_m, s.inc_deg]) },
        {
          name: 'Dogleg severity',
          type: 'line',
          yAxisIndex: 1,
          color: colors.actual,
          showSymbol: false,
          data: curve.map((s) => [s.md_m, s.dls_deg_per_30m]),
        },
      ],
    }),
    // eslint-disable-next-line react-hooks/exhaustive-deps
    [curve, colors.axis, colors.planned, colors.actual],
  )

  const stationRows = curve.map((s) => ({
    ...s,
    dls_display: s.dls_deg_per_30m.toFixed(2),
    build_display: s.build_deg_per_30m.toFixed(2),
    turn_display: s.turn_deg_per_30m.toFixed(2),
  }))

  const deepestSection = path?.sections.length ? path.sections[path.sections.length - 1] : null

  return (
    <Box>
      <PageHeading
        eyebrow="Well Operations"
        title="Well path & diagram"
        subtitle="Measured depth, inclination and azimuth integrated with the minimum-curvature method, drawn against the casing seats actually recorded. Nothing is drawn that the record does not support; every gap is named."
        action={
          <>
            {can('ops-analytics:read') && (
              <Button
                variant="outlined"
                component={Link}
                to={`/operations/analytics${well ? `?well=${encodeURIComponent(well)}&scope=${scope}` : ''}`}
              >
                Time vs depth
              </Button>
            )}
            {can('ops-dashboard:read') && (
              <Button variant="outlined" component={Link} to="/operations">
                Operations dashboard
              </Button>
            )}
          </>
        }
      />

      <SectionCard title="Well and scope" subtitle="One well and one scope at a time: a trajectory belongs to a single hole.">
        <Box display="grid" gap={2} gridTemplateColumns={{ xs: '1fr', sm: '1fr 1fr', lg: 'repeat(3,minmax(0,1fr))' }}>
          <TextField
            select
            label="Well"
            value={well}
            onChange={(e) => setParam('well', e.target.value)}
            helperText={ref ? `${ref.wells.length} configured well${ref.wells.length === 1 ? '' : 's'}` : ' '}
          >
            {(ref?.wells ?? []).map((w) => (
              <MenuItem key={w.id} value={w.id}>
                {w.display_name}
                {scope === 'completion' && !w.completion_available
                  ? ' — no completion'
                  : scope === 'drilling' && !w.drilling_available
                    ? ' — no drilling'
                    : ''}
              </MenuItem>
            ))}
          </TextField>
          <TextField select label="Scope" value={scope} onChange={(e) => setParam('scope', e.target.value)}>
            {SCOPES.map((s) => (
              <MenuItem key={s.value} value={s.value}>
                {s.label}
              </MenuItem>
            ))}
          </TextField>
          <TextField
            label="Vertical-section azimuth (°)"
            value={vsAzimuth}
            onChange={(e) => setParam('vs', e.target.value.replace(/[^\d.]/g, ''))}
            slotProps={{ htmlInput: { inputMode: 'decimal', min: 0, max: 360 } }}
            placeholder={summary ? `Auto: ${summary.closure_azimuth_deg?.toFixed(1) ?? '0.0'}` : 'Auto'}
            helperText="Blank follows the well's own closure azimuth. Enter a reference bearing to compare wells."
          />
        </Box>
        {path && (
          <Stack direction="row" gap={0.8} flexWrap="wrap" useFlexGap mt={2}>
            <Chip size="small" variant="outlined" label={`${path.well_code} · ${path.scope}`} />
            <Chip size="small" variant="outlined" label={`VS plane ${path.vertical_section_azimuth_deg.toFixed(1)}°`} />
            <Chip size="small" variant="outlined" label={`${summary?.stations ?? 0} station${summary?.stations === 1 ? '' : 's'}`} />
            <Chip size="small" variant="outlined" label={path.datum || 'Datum not stated'} />
            <Chip size="small" variant="outlined" label={`Generated ${new Date(path.generated_at).toLocaleString()}`} />
          </Stack>
        )}
      </SectionCard>

      {error && (
        <Box mt={2}>
          <ErrorMessage message={error} />
        </Box>
      )}

      {!well && !error && <Alert severity="info" sx={{ mt: 2 }}>Select a well to draw its path.</Alert>}

      {path && (
        <>
          <Box display="grid" gap={2} my={2} gridTemplateColumns={{ xs: '1fr', sm: '1fr 1fr', lg: 'repeat(auto-fit,minmax(196px,1fr))' }}>
            <StatCard
              label="Current depth"
              value={`${m(summary?.current_md_m)} m`}
              hint={summary?.depth_basis ? `${summary.depth_basis}${summary.latest_report_date ? ` · ${summary.latest_report_date}` : ''}` : 'No report yet'}
            />
            <StatCard
              label="True vertical depth"
              value={`${m(summary?.current_tvd_m)} m`}
              hint={`Basis: ${summary?.current_tvd_basis || '—'}`}
            />
            <StatCard
              label="Bit depth"
              value={`${m(summary?.bit_depth_m)} m`}
              hint={deepestSection ? `Last casing ${deepestSection.casing_label} at ${m(deepestSection.to_depth_m)} m` : 'No casing seat recorded'}
            />
            <StatCard
              label="Departure"
              value={`${m(summary?.departure_m)} m`}
              hint={`Closure azimuth ${summary?.closure_azimuth_deg === null || summary?.closure_azimuth_deg === undefined ? '—' : `${summary.closure_azimuth_deg.toFixed(1)}°`}`}
            />
            <StatCard
              label="Max inclination"
              value={summary?.max_inc_deg === null || summary?.max_inc_deg === undefined ? '—' : `${summary.max_inc_deg.toFixed(1)}°`}
              hint={`Kick-off ${m(summary?.kickoff_md_m)} m MD`}
            />
            <StatCard
              label="Max dogleg"
              value={summary?.max_dls_deg_per_30m === null || summary?.max_dls_deg_per_30m === undefined ? '—' : `${summary.max_dls_deg_per_30m.toFixed(2)} °/30 m`}
              hint="What the surveys actually recorded; no tool limit is assumed" 
            />
          </Box>

          <ChartPanel
            title="Casing schematic and vertical section"
            figureKey="well-diagram"
            subtitle="Both views share one measured-depth axis. Casing wall width follows pipe size; the dashed line below the last shoe is the open hole."
            caption={`Drawn from ${summary?.sections_drawn ?? 0} casing seat(s) and ${summary?.stations ?? 0} survey station(s). ${path.assumption || 'No fallback was applied.'}`}
            empty={!path.is_surveyed && !path.sections.length}
            emptyMessage={path.assumption || 'No surveys or casing seats are recorded for this well and scope.'}
            height={480}
          >
            <WellDiagram path={path} height={480} />
          </ChartPanel>

          <Box display="grid" gap={2} mt={2} gridTemplateColumns={{ xs: 'minmax(0,1fr)', lg: 'repeat(2,minmax(0,1fr))' }}>
            <ChartPanel
              title="Plan view (north / east)"
              figureKey="well-plan"
              subtitle="The stations as they sit on the ground. North is up; the surface location is the origin."
              caption="Depths are relative to the report datum. A vertical well plots as a single point at the origin."
              empty={!curve.length}
              emptyMessage="No survey stations recorded."
              height={320}
            >
              <InteractiveChart option={planOption} style={{ height: '100%' }} />
            </ChartPanel>
            <ChartPanel
              title="Inclination and dogleg"
              figureKey="well-steering"
              subtitle="Inclination against measured depth, with the dogleg severity that the survey-to-survey integration produced."
              caption="Dogleg severity is degrees per 30 m, converted from the printed per-100 ft value where the reports use feet."
              empty={curve.length < 2}
              emptyMessage="Two stations are needed to compute a dogleg."
              height={320}
            >
              <InteractiveChart option={steeringOption} style={{ height: '100%' }} />
            </ChartPanel>
          </Box>

          <Box display="grid" gap={2} mt={2} gridTemplateColumns={{ xs: 'minmax(0,1fr)', lg: 'minmax(0,3fr) minmax(0,2fr)' }}>
            <SectionCard
              title="Survey stations"
              subtitle="The integration, station by station, so every figure on the drawings can be checked."
            >
              <DataTable
                rows={stationRows}
                /* A station is identified by its own measured depth. */
                rowKey={(row) => String(row.md_m)}
                exportName="well-path-stations"
                canExport={can('ops-analytics:export')}
                columns={[
                  { field: 'md_m', headerName: 'MD (m)', type: 'numericColumn' },
                  { field: 'inc_deg', headerName: 'Inc (°)', type: 'numericColumn' },
                  { field: 'azi_deg', headerName: 'Azi (°)', type: 'numericColumn' },
                  { field: 'tvd_m', headerName: 'TVD (m)', type: 'numericColumn' },
                  { field: 'ns_m', headerName: 'N (m)', type: 'numericColumn' },
                  { field: 'ew_m', headerName: 'E (m)', type: 'numericColumn' },
                  { field: 'vsec_m', headerName: 'V.sec (m)', type: 'numericColumn' },
                  { field: 'dls_display', headerName: 'DLS (°/30 m)' },
                  { field: 'build_display', headerName: 'Build' },
                  { field: 'turn_display', headerName: 'Turn' },
                ]}
              />
            </SectionCard>

            <Stack spacing={2}>
              <SectionCard
                title="Provenance"
                subtitle="Where each part of the drawing came from, and what the record does not contain."
              >
                <Stack spacing={1}>
                  <Typography variant="body2">
                    <strong>Depth:</strong> {path.depth.basis || 'no report'} —{' '}
                    {path.depth.report_date ?? 'no date'}
                    {path.depth.status ? ` · ${path.depth.status}` : ''}
                  </Typography>
                  <Typography variant="body2">
                    <strong>Current TVD:</strong> {summary?.current_tvd_basis || '—'}
                  </Typography>
                  <Typography variant="body2">
                    <strong>Casing seats:</strong> {path.casing_seats.length ? path.casing_seats.map((seat) => `${seat.size_label} @ ${m(seat.depth_m)} m (${seat.source})`).join(' · ') : 'none recorded'}
                  </Typography>
                  <Typography variant="body2">
                    <strong>Open hole:</strong>{' '}
                    {path.open_hole ? `${m(path.open_hole.from_depth_m)} – ${m(path.open_hole.to_depth_m)} m` : 'none below the last shoe'}
                  </Typography>
                  {path.planned.items > 0 && (
                    <Typography variant="body2">
                      <strong>Programme:</strong> {path.planned.label} · {path.planned.items} item{path.planned.items === 1 ? '' : 's'} ·{' '}
                      {path.planned.points.length} depth point{path.planned.points.length === 1 ? '' : 's'}
                      {path.planned.planned_days !== null ? ` · ${path.planned.planned_days} planned days` : ''}
                    </Typography>
                  )}
                  {path.assumption && (
                    <Alert severity="info" sx={{ fontSize: 12.5 }}>
                      {path.assumption}
                    </Alert>
                  )}
                  {path.notes.map((note) => (
                    <Typography key={note} variant="caption" display="block" color="text.secondary">
                      {note}
                    </Typography>
                  ))}
                  {!path.is_surveyed && (
                    <Alert severity="warning" sx={{ fontSize: 12.5 }}>
                      No survey has been recorded for this well and scope. The current depth still comes from the
                      latest report&apos;s header, but no trajectory can be drawn.
                    </Alert>
                  )}
                </Stack>
              </SectionCard>

              {Boolean(path.survey_discrepancies.length) && (
                <SectionCard
                  title="Printed TVD does not match the integration"
                  subtitle="The drawing uses the integrated value. A printed figure this far out is a transcription question for the engineer, so both numbers are shown rather than one being chosen silently."
                >
                  <Stack spacing={0.8}>
                    {path.survey_discrepancies.slice(0, 20).map((row) => (
                      <Typography key={row.md_m} variant="body2">
                        At {m(row.md_m)} m MD: printed {m(row.printed_tvd_m)} m TVD, integrated{' '}
                        {m(row.computed_tvd_m)} m ({row.difference_m > 0 ? '+' : ''}
                        {row.difference_m.toFixed(2)} m)
                      </Typography>
                    ))}
                    {path.survey_discrepancies.length > 20 && (
                      <Typography variant="caption" color="text.secondary">
                        …and {path.survey_discrepancies.length - 20} more.
                      </Typography>
                    )}
                  </Stack>
                </SectionCard>
              )}

              {path.depth.report_id && can('ops-report:read') && (
                <Button variant="outlined" component={Link} to={`/operations/reports/${path.depth.report_id}`}>
                  Open the {path.depth.report_date} report
                </Button>
              )}
            </Stack>
          </Box>

          {loading && (
            <Typography variant="caption" color="text.secondary" display="block" mt={1}>
              Loading…
            </Typography>
          )}
        </>
      )}
    </Box>
  )
}
