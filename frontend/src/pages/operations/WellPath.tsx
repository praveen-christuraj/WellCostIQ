import { useEffect, useMemo, useState } from 'react'
import { Link, useSearchParams } from 'react-router-dom'
import { Alert, Box, Button, Chip, MenuItem, Stack, TextField, Typography } from '@mui/material'
import { WellDiagram } from '../../components/operations/WellDiagram'
import { DoglegIntervals } from '../../components/operations/DoglegIntervals'
import { WellPlanSectionViews, WellSteeringTracks } from '../../components/operations/WellTrajectory'
import { TrajectoryComparisonPanel, TrajectoryExpand } from '../../components/operations/TrajectoryComparison'
import { DoglegExpand, WellDiagramExpand } from '../../components/operations/WellVisualInspectors'
import { validRange } from '../../components/operations/VisualDepthControls'
import { WellSourceDialog, type WellMark } from '../../components/operations/WellSourceDialog'
import { DataTable } from '../../components/DataTable'
import { ChartPanel } from '../../components/ui/ChartPanel'
import { SectionCard } from '../../components/ui/SectionCard'
import { StatCard } from '../../components/ui/StatCard'
import { Caution, RestoreCautions } from '../../components/ui/Caution'
import { ErrorMessage, PageHeading } from '../../components/Common'
import { useAuth } from '../../context/AuthContext'
import {
  opsScopeReference,
  opsWellPath,
  type OpsScopeReference,
  type OpsWellPath,
} from '../../lib/operations'
import { fmtAngle, fmtDepth, fmtDls, interpolateAt, stationAt } from '../../lib/wellPath'

/** Local-storage namespace for the dismissible cautions shown on this page. */
const CAUTION_PAGE = 'operations-well-path'

/**
 * Well path — the geometry of one well, drawn from its own record.
 *
 * Every number on this page comes from one service, `GET /operations/well-path`,
 * which reads the same surveys, casing seats and report headers that the daily
 * reports carry. Nothing here is interpolated from a template or a target:
 *
 * * the **plan view and vertical section** are two linked projections of exactly
 *   the same stations, with a station selected in one emphasised in the other;
 * * the **dogleg chart** draws severity per *interval*, because that is the unit
 *   it is defined on, with the reported rate as a separate mark;
 * * the **inclination and azimuth tracks** use separate scales and break at the
 *   azimuth wrap instead of drawing a false full turn;
 * * the **construction drawing** puts casing and hole on a measured-depth axis
 *   and the trajectory on a true-vertical-depth axis, and never shares one axis
 *   between the two;
 * * the **station table** is the arithmetic a reader can check by hand.
 *
 * A selected station opens the same source drawer from the table, a chart mark or
 * the keyboard, and every figure is named as recorded, calculated or missing.
 */

const SCOPES = [
  { value: 'drilling', label: 'Drilling' },
  { value: 'completion', label: 'Completion' },
]

type WindowState = { from: string; to: string }

const EMPTY_WINDOW: WindowState = { from: '', to: '' }

function toNumber(value: string): number | null {
  if (value.trim() === '') return null
  const parsed = Number(value)
  return Number.isFinite(parsed) ? parsed : null
}

export default function OperationsWellPath() {
  const { can } = useAuth()
  const [params, setParams] = useSearchParams()

  const [ref, setRef] = useState<OpsScopeReference | null>(null)
  const [path, setPath] = useState<OpsWellPath | null>(null)
  const [error, setError] = useState('')
  const [loading, setLoading] = useState(false)
  const [selectedMd, setSelectedMd] = useState<number | null>(null)
  const [explain, setExplain] = useState<WellMark | null>(null)
  const [windowState, setWindowState] = useState<WindowState>(EMPTY_WINDOW)

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
    if (key === 'well' || key === 'scope') {
      setSelectedMd(null)
      setWindowState(EMPTY_WINDOW)
      setExplain(null)
    }
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
    setPath(current => current?.well_id === well && current.scope === scope ? current : null)
    opsWellPath(well, scope, vsAzimuth === '' ? undefined : vsAzimuth)
      .then((d) => {
        if (current) {
          setPath(d)
          setSelectedMd((md) => (md !== null && (stationAt(d.curve, md) || stationAt(d.planned_trajectory?.curve ?? [], md)) ? md : null))
        }
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
  const plannedCurve = path?.planned_trajectory?.curve ?? []
  const hasPlanCurve = plannedCurve.length > 0
  const trajectory = path ? { ...path, planned_trajectory: path.planned_trajectory ?? null } : null
  const summary = path?.summary
  const surveyEnd = path?.position.survey_end_md_m ?? null
  const holeDepth = path?.snapshot.hole_depth_m ?? summary?.current_md_m ?? null
  const requestedWindow = { from: toNumber(windowState.from), to: toNumber(windowState.to) }
  const windowInvalid = !validRange(requestedWindow)
  const depthWindow = windowInvalid ? { from: null, to: null } : requestedWindow
  const selectedStation = stationAt(curve, selectedMd)
  const selectedInterval = selectedMd === null
    ? null
    : path?.intervals.find((row) => Math.abs(row.to_md_m - selectedMd) <= 0.05) ?? null

  const jumpOptions = useMemo(() => {
    if (!path) return [] as { value: string; label: string; mark: WellMark }[]
    const options: { value: string; label: string; mark: WellMark }[] = []
    if (holeDepth !== null) {
      options.push({ value: 'hole', label: `Hole depth · ${fmtDepth(holeDepth, 2)} m MD`, mark: { kind: 'hole' } })
    }
    if (path.snapshot.bit_depth_m !== null) {
      options.push({
        value: 'bit',
        label: `${path.snapshot.label || 'Bit / string'} · ${fmtDepth(path.snapshot.bit_depth_m, 2)} m MD`,
        mark: { kind: 'bit' },
      })
    }
    for (const seat of path.casing_seats) {
      options.push({
        value: `seat-${seat.size_label}-${seat.depth_m}`,
        label: `Shoe ${seat.size_label} · ${fmtDepth(seat.depth_m, 2)} m MD`,
        mark: { kind: 'seat', depth: seat.depth_m },
      })
    }
    for (const station of path.curve) {
      options.push({
        value: `station-${station.md_m}`,
        label: `Station · ${fmtDepth(station.md_m, 2)} m MD`,
        mark: { kind: 'station', md: station.md_m },
      })
    }
    return options
  }, [path, holeDepth])

  const availableCurves = [curve, plannedCurve].filter(row => row.length)
  const curveSpan = availableCurves.length ? {
    from: Math.min(...availableCurves.map(row => row[0].md_m)),
    to: Math.max(...availableCurves.map(row => row[row.length - 1].md_m)),
  } : null

  /**
   * Zoom narrows or widens the drawn window about its own centre. It never
   * resamples the curve: the same stations are plotted, so a zoomed view cannot
   * claim a detail the survey does not have. Clamped to the surveyed range.
   */
  const zoomWindow = (direction: 'in' | 'out') => {
    if (!curveSpan) return
    const from = toNumber(windowState.from) ?? curveSpan.from
    const to = toNumber(windowState.to) ?? curveSpan.to
    const centre = (from + to) / 2
    const half = Math.max(5, ((to - from) / 2) * (direction === 'in' ? 0.65 : 1.5))
    setWindowState({
      from: Math.max(curveSpan.from, centre - half).toFixed(1),
      to: Math.min(curveSpan.to, centre + half).toFixed(1),
    })
  }

  const stationRows = curve.map((station) => {
    const lineage = path?.survey_stations.find((row) => Math.abs(row.md_m - station.md_m) <= 0.05) ?? null
    return {
      ...station,
      source: lineage ? `${lineage.source || 'record'}${lineage.report_date ? ` · ${lineage.report_date}` : ''}` : 'record',
      dls_display: station.dls_deg_per_30m === null ? '— no interval' : station.dls_deg_per_30m.toFixed(2),
      build_display: station.build_deg_per_30m === null ? '—' : station.build_deg_per_30m.toFixed(2),
      turn_display: station.turn_deg_per_30m === null ? '—' : station.turn_deg_per_30m.toFixed(2),
      status: station.is_anchor ? 'Anchor' : station.interval_valid ? 'Interval' : 'Held for review',
    }
  })

  const markerTvd = path?.position.marker_tvd_m ?? summary?.current_tvd_m ?? null
  const tvdAtHole = path && holeDepth !== null ? interpolateAt(path.curve, holeDepth) : null

  return (
    <Box>
      <PageHeading
        eyebrow="Well Operations"
        title="Well path & diagram"
        subtitle="One well, three questions: where the hole was drilled (surveyed trajectory), what has been installed (casing schematic) and where the tool or string was reported (report snapshot). Nothing is drawn that the record does not support; every gap is named."
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

      <RestoreCautions page={CAUTION_PAGE}/>

      <SectionCard title="Well and scope" subtitle="One well and one scope at a time: a trajectory belongs to a single hole.">
        <Box display="grid" gap={2} gridTemplateColumns={{ xs: '1fr', sm: '1fr 1fr', lg: 'repeat(4,minmax(0,1fr))' }}>
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
            label="Vertical section azimuth (° from grid north)"
            value={vsAzimuth}
            onChange={(e) => setParam('vs', e.target.value)}
            placeholder={path ? `closure ${fmtAngle(path.vertical_section_azimuth_deg, 1)}` : 'closure azimuth'}
            helperText="Blank uses the well's own closure direction."
          />
          <TextField
            select
            label="Jump to a mark"
            value=""
            onChange={(e) => {
              const option = jumpOptions.find((row) => row.value === e.target.value)
              if (!option) return
              if (option.mark.kind === 'station') setSelectedMd(option.mark.md)
              else if (option.mark.kind === 'interval') setSelectedMd(option.mark.toMd)
              else if (option.mark.kind === 'hole') {
                setSelectedMd(null)
                setWindowState(EMPTY_WINDOW)
              }
              setExplain(option.mark)
            }}
            helperText={`${curve.length} station${curve.length === 1 ? '' : 's'} · ${path?.casing_seats.length ?? 0} shoe${path?.casing_seats.length === 1 ? '' : 's'} to jump to`}
          >
            {jumpOptions.map((option) => (
              <MenuItem key={option.value} value={option.value}>
                {option.label}
              </MenuItem>
            ))}
          </TextField>
        </Box>
        <Stack direction={{ xs: 'column', sm: 'row' }} gap={1.5} alignItems={{ xs: 'stretch', sm: 'center' }} mt={2}>
          <TextField
            size="small"
            type="number"
            label="Window from (m MD)"
            error={windowInvalid}
            value={windowState.from}
            onChange={(e) => setWindowState((current) => ({ ...current, from: e.target.value }))}
            sx={{ width: 176 }}
          />
          <TextField
            size="small"
            type="number"
            label="Window to (m MD)"
            error={windowInvalid}
            value={windowState.to}
            onChange={(e) => setWindowState((current) => ({ ...current, to: e.target.value }))}
            sx={{ width: 176 }}
          />
          <Button variant="outlined" size="small" onClick={() => zoomWindow('in')} disabled={windowInvalid || !curveSpan || (depthWindow.from !== null && depthWindow.to !== null && depthWindow.to - depthWindow.from <= 10)}>
            Zoom in
          </Button>
          <Button variant="outlined" size="small" onClick={() => zoomWindow('out')} disabled={windowInvalid || !curveSpan}>
            Zoom out
          </Button>
          <Button variant="outlined" size="small" onClick={() => setWindowState(EMPTY_WINDOW)}>
            Fit well
          </Button>
          {windowInvalid && <Typography role="alert" variant="caption" color="error.main">Enter a non-negative, ordered MD range.</Typography>}
          <Typography sx={{ fontSize: 11.5, color: 'text.secondary' }}>
            The window clips the plots, not the record. Export always carries the whole well unless the window is
            stated in the caption. Zoom in by narrowing it; nothing is resampled or decimated.
          </Typography>
        </Stack>
      </SectionCard>

      {loading && !path && (
        <Box mt={2}>
          <Typography role="status" fontSize={12.5}>
            Loading the well path…
          </Typography>
        </Box>
      )}
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
              label="Hole depth (marker)"
              value={`${fmtDepth(holeDepth, 2)} m`}
              hint={`${path.position.basis}${path.snapshot.report_date ? ` · ${path.snapshot.report_date}` : ''}`}
            />
            <StatCard
              label="True vertical depth"
              value={`${fmtDepth(markerTvd, 2)} m`}
              hint={`Basis: ${path.position.marker_tvd_basis || '—'}`}
            />
            <StatCard
              label="Bit / string depth"
              value={`${fmtDepth(path.snapshot.bit_depth_m, 2)} m`}
              hint={
                path.snapshot.off_bottom_m !== null
                  ? `${fmtDepth(path.snapshot.off_bottom_m, 2)} m off bottom · ${path.snapshot.basis}`
                  : path.snapshot.off_bottom_note || 'Not recorded'
              }
            />
            <StatCard
              label="Survey endpoint"
              value={`${fmtDepth(surveyEnd, 2)} m`}
              hint={
                path.position.gap_m !== null && path.position.gap_m > 0
                  ? `${fmtDepth(path.position.gap_m, 2)} m of hole below the last station is unsurveyed`
                  : `${path.survey.stations} station${path.survey.stations === 1 ? '' : 's'} · ${path.survey.anchor_basis}`
              }
            />
            <StatCard
              label="Departure"
              value={`${fmtDepth(summary?.departure_m, 2)} m`}
              hint={`Closure azimuth ${fmtAngle(summary?.closure_azimuth_deg, 1)}`}
            />
            <StatCard
              label="Max inclination"
              value={fmtAngle(summary?.max_inc_deg, 1)}
              hint={`Threshold crossing ${fmtDepth(summary?.kickoff_md_m, 2)} m MD — not necessarily the planned kick-off`}
            />
            <StatCard
              label="Max dogleg"
              value={summary?.max_dls_deg_per_30m === null || summary?.max_dls_deg_per_30m === undefined
                ? '— no interval'
                : `${summary.max_dls_deg_per_30m.toFixed(3)} °/30 m`}
              hint={summary?.max_dls_to_md_m
                ? `Interval ending at ${fmtDepth(summary.max_dls_to_md_m, 2)} m · no tool limit is assumed`
                : 'Two stations are needed for an interval'}
            />
          </Box>

          <Stack spacing={2}>
            {!hasPlanCurve && can('ops-plan:read') && <Caution page={CAUTION_PAGE} cautionKey="planned-survey-missing"
              signature={[path.well_id, path.scope, path.planned_trajectory?.plan_version_id ?? 'none']} severity="info">
              {path.planned_trajectory ? `Active plan v${path.planned_trajectory.version_no} has no planned directional survey.` : 'No active plan for this well and scope.'}{' '}
              <Link to="/operations/plans">Open Plans &amp; timeline</Link> to review the plan survey.
            </Caution>}
            {hasPlanCurve && trajectory ? <TrajectoryComparisonPanel path={trajectory} figureKey="well-plan-section" selectedMd={selectedMd}
              onSelectMd={setSelectedMd} window={depthWindow} /> : <ChartPanel
              title="Trajectory — plan view and vertical section"
              figureKey="well-plan-section"
              action={trajectory && <TrajectoryExpand path={trajectory} title="Trajectory — plan view and vertical section"
                subtitle="Actual survey projected onto the selected vertical-section plane." window={depthWindow} selectedMd={selectedMd} />}
              subtitle="Two projections of exactly the same stations. Select a station in either one to highlight it in the other, the schematic and the table."
              caption={`Grid north · ${path.datum}. The plan view uses an equal north/east scale; the vertical section is a projection on the plane facing ${fmtAngle(path.vertical_section_azimuth_deg, 1)}.`}
              empty={!curve.length}
              emptyMessage={path.assumption || 'No survey stations recorded for this well and scope.'}
              height={452}
            >
              <WellPlanSectionViews path={path} selectedMd={selectedMd} onSelectMd={setSelectedMd} window={depthWindow} height={340} />
            </ChartPanel>}

            <ChartPanel
              title="Dogleg severity by interval"
              figureKey="well-dogleg"
              action={<DoglegExpand path={path} selectedMd={selectedMd} window={depthWindow} />}
              subtitle="Each rectangle spans the measured-depth interval between two stations, not one calendar day. Height is the average directional change normalised to 30 m."
              meta={
                selectedInterval ? (
                  <Chip
                    size="small"
                    variant="outlined"
                    label={`Selected interval ${fmtDepth(selectedInterval.from_md_m, 0)}–${fmtDepth(selectedInterval.to_md_m, 0)} m`}
                    onDelete={() => setSelectedMd(null)}
                  />
                ) : undefined
              }
              caption={`${path.summary.intervals} interval${path.summary.intervals === 1 ? '' : 's'} calculated${path.summary.invalid_intervals ? ` · ${path.summary.invalid_intervals} held for review` : ''}. The brass tick is the rate the record reported, kept as a separate mark. A peak identifies an interval to inspect; it is not proof of unsafe drilling.`}
              empty={path.intervals.length === 0}
              emptyMessage="Two accepted stations are needed for a severity interval. The first station has no interval above it."
              toolbar={
                <Stack direction="row" gap={1} flexWrap="wrap" alignItems="center">
                  <Button
                    size="small"
                    variant="outlined"
                    disabled={selectedInterval === null}
                    onClick={() => setExplain({ kind: 'interval', toMd: selectedInterval?.to_md_m ?? 0 })}
                  >
                    Explain this interval
                  </Button>
                  {path.summary.max_dls_to_md_m !== null && (
                    <Button size="small" onClick={() => setSelectedMd(path.summary.max_dls_to_md_m)}>
                      Jump to the peak interval
                    </Button>
                  )}
                  <Typography sx={{ fontSize: 11, color: 'text.secondary' }}>
                    DLS is not inclination, not azimuth change alone, and not an instantaneous measurement.
                  </Typography>
                </Stack>
              }
              height={396}
            >
              <DoglegIntervals
                intervals={path.intervals}
                window={depthWindow}
                selectedMd={selectedMd}
                onSelectMd={setSelectedMd}
                height={280}
              />
            </ChartPanel>

            {hasPlanCurve && trajectory ? <TrajectoryComparisonPanel path={trajectory} part="steering" figureKey="well-steering" selectedMd={selectedMd}
              onSelectMd={setSelectedMd} window={depthWindow} /> : <ChartPanel
              title="Inclination and azimuth along measured depth"
              figureKey="well-steering"
              action={trajectory && <TrajectoryExpand path={trajectory} part="steering" title="Inclination and azimuth along measured depth"
                window={depthWindow} selectedMd={selectedMd} />}
              subtitle="The steering record, on separate scales. Azimuth is clockwise from grid north and breaks at the 360° wrap instead of drawing a false full turn."
              caption="Build is the inclination change per 30 m. Turn is inclination-weighted and is not the raw azimuth difference, so the two are never compared as the same quantity."
              empty={curve.length < 2}
              emptyMessage="Two stations are needed to plot a trend."
              height={336}
            >
              <WellSteeringTracks path={path} selectedMd={selectedMd} onSelectMd={setSelectedMd} window={depthWindow} height={230} />
            </ChartPanel>}

            <ChartPanel
              title="Casing, hole and trajectory"
              figureKey="well-diagram"
              action={<WellDiagramExpand path={path} selectedMd={selectedMd} window={depthWindow} />}
              subtitle="Left is a construction drawing on measured depth; right is the integrated trajectory on true vertical depth. The two axes are labelled separately and no casing seat is converted into a TVD."
              toolbar={
                <Stack direction="row" gap={1} flexWrap="wrap" alignItems="center">
                  <Button size="small" variant="outlined" onClick={() => setExplain({ kind: 'hole' })} disabled={holeDepth === null}>
                    Explain hole depth
                  </Button>
                  <Button size="small" variant="outlined" onClick={() => setExplain({ kind: 'bit' })} disabled={path.snapshot.bit_depth_m === null}>
                    Explain bit / string
                  </Button>
                  <Button
                    size="small"
                    variant="outlined"
                    disabled={!selectedStation}
                    onClick={() => selectedStation && setExplain({ kind: 'station', md: selectedStation.md_m })}
                  >
                    Explain selected station
                  </Button>
                  {path.casing_seats.length > 0 && (
                    <Button
                      size="small"
                      variant="text"
                      onClick={() => setExplain({ kind: 'seat', depth: path.casing_seats[path.casing_seats.length - 1].depth_m })}
                    >
                      Explain last shoe
                    </Button>
                  )}
                </Stack>
              }
              caption={`Drawn from ${summary?.sections_drawn ?? 0} casing seat(s) and ${summary?.stations ?? 0} survey station(s). Shapes and labels carry meaning as well as colour. ${path.assumption || 'No fallback was applied.'}`}
              empty={!path.is_surveyed && !path.sections.length && !hasPlanCurve}
              emptyMessage={path.assumption || 'No surveys or casing seats are recorded for this well and scope.'}
              height={586}
            >
              <WellDiagram path={path} height={500} selectedMd={selectedMd} mdWindow={depthWindow} />
            </ChartPanel>
          </Stack>

          <Box display="grid" gap={2} mt={2} gridTemplateColumns={{ xs: 'minmax(0,1fr)', lg: 'minmax(0,3fr) minmax(0,2fr)' }}>
            <SectionCard
              title="Survey stations"
              subtitle="The integration, station by station, so every figure on the drawings can be checked. A station with no interval above it shows “— no interval”, never zero."
              action={
                <Stack direction="row" gap={1} alignItems="center">
                  {selectedStation && (
                    <Chip
                      size="small"
                      variant="outlined"
                      label={`Selected ${fmtDepth(selectedStation.md_m, 2)} m`}
                      onDelete={() => setSelectedMd(null)}
                    />
                  )}
                  <Button size="small" variant="outlined" onClick={() => setSelectedMd(null)} disabled={selectedMd === null}>
                    Clear selection
                  </Button>
                </Stack>
              }
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
                  { field: 'source', headerName: 'Source', minWidth: 150 },
                  {
                    headerName: 'Explain',
                    field: 'md_m',
                    minWidth: 96,
                    maxWidth: 112,
                    sortable: false,
                    filter: false,
                    cellRenderer: ({ data }: { data: (typeof stationRows)[number] }) =>
                      data ? (
                        <Box display="flex" alignItems="center" height="100%">
                          <Button
                            size="small"
                            variant="text"
                            onClick={() => {
                              setSelectedMd(data.md_m)
                              setExplain({ kind: 'station', md: data.md_m })
                            }}
                          >
                            Source
                          </Button>
                        </Box>
                      ) : null,
                  },
                ]}
              />
              {selectedStation && (
                <Box mt={1.5} display="grid" gap={1} gridTemplateColumns={{ xs: '1fr', sm: '1fr 1fr' }}>
                  <Typography sx={{ fontSize: 12 }}>
                    <strong>{fmtDepth(selectedStation.md_m, 2)} m</strong> · Inc {fmtAngle(selectedStation.inc_deg)} · Azi{' '}
                    {fmtAngle(selectedStation.azi_deg)}
                  </Typography>
                  <Typography sx={{ fontSize: 12 }}>
                    DLS {fmtDls(selectedStation.dls_deg_per_30m)} · TVD {fmtDepth(selectedStation.tvd_m, 2)} m
                  </Typography>
                  <Typography sx={{ fontSize: 11.5, color: 'text.secondary', gridColumn: '1 / -1' }}>
                    {selectedStation.interval_issue || 'Severity belongs to the interval ending at this station.'}
                  </Typography>
                </Box>
              )}
            </SectionCard>

            <Stack spacing={2}>
              <SectionCard
                title="Report snapshot"
                subtitle="The selected report's own positions. These are observations on a date and a status, not the trajectory and not a live tool position."
                action={
                  path.snapshot.report_id && can('ops-report:read') ? (
                    <Button size="small" variant="text" component={Link} to={`/operations/reports/${path.snapshot.report_id}`}>
                      Open report
                    </Button>
                  ) : undefined
                }
              >
                <Stack spacing={1}>
                  <SnapshotRow label="Hole depth" value={`${fmtDepth(path.snapshot.hole_depth_m, 2)} m MD`} note={path.snapshot.basis} />
                  <SnapshotRow label="Hole TVD (printed)" value={`${fmtDepth(path.snapshot.hole_tvd_m, 2)} m`} note={path.snapshot.tvd_source || 'not stated'} />
                  <SnapshotRow
                    label={path.snapshot.label || 'Bit / string depth'}
                    value={`${fmtDepth(path.snapshot.bit_depth_m, 2)} m MD`}
                    note={path.snapshot.off_bottom_m !== null
                      ? `${fmtDepth(path.snapshot.off_bottom_m, 2)} m off bottom · same report`
                      : path.snapshot.off_bottom_note}
                  />
                  <SnapshotRow
                    label="Report"
                    value={path.snapshot.report_date ? `${path.snapshot.report_no || 'Report'} · ${path.snapshot.report_date}` : path.snapshot.basis}
                    note={path.snapshot.status ? `${path.snapshot.status}${path.snapshot.verified ? ' · verified' : ''}` : ''}
                  />
                  {path.snapshot.current_status_text && (
                    <Typography sx={{ fontSize: 11.5, color: 'text.secondary' }}>
                      Current status as printed: “{path.snapshot.current_status_text}”. The text is evidence; separate
                      long and short string positions are not fabricated from it.
                    </Typography>
                  )}
                  <Caution
                    cautionKey="string-versus-hole"
                    page={CAUTION_PAGE}
                    severity="info"
                    icon={false}
                    sx={{ fontSize: 11.5 }}
                  >
                    A short string above the hole bottom is normal: one is equipment position, the other is the
                    drilled hole. They need not match.
                  </Caution>
                </Stack>
              </SectionCard>

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
                    <strong>Marker:</strong> {path.position.basis}
                    {path.position.gap_m !== null ? ` · gap to the last station ${fmtDepth(path.position.gap_m, 2)} m` : ''}
                  </Typography>
                  <Typography variant="body2">
                    <strong>Current TVD:</strong> {path.position.marker_tvd_basis || '—'}
                    {tvdAtHole === null && holeDepth !== null && path.is_surveyed
                      ? ' (no conversion below the last station)'
                      : ''}
                  </Typography>
                  <Typography variant="body2">
                    <strong>Survey:</strong> {path.survey.stations} station
                    {path.survey.stations === 1 ? '' : 's'} · {path.survey.sources.join(', ') || 'source not stated'}
                    {path.survey.tools.length ? ` · ${path.survey.tools.join(', ')}` : ''} · anchor {path.survey.anchor_basis}
                  </Typography>
                  <Typography variant="body2">
                    <strong>Casing seats:</strong>{' '}
                    {path.casing_seats.length
                      ? path.casing_seats.map((seat) => `${seat.size_label} @ ${fmtDepth(seat.depth_m, 2)} m (${seat.source})`).join(' · ')
                      : 'none recorded'}
                  </Typography>
                  <Typography variant="body2">
                    <strong>Open hole:</strong>{' '}
                    {path.open_hole ? `${fmtDepth(path.open_hole.from_depth_m)} – ${fmtDepth(path.open_hole.to_depth_m)} m` : 'none below the last shoe'}
                  </Typography>
                  {path.planned.items > 0 && (
                    <Typography variant="body2">
                      <strong>Programme:</strong> {path.planned.label} · {path.planned.items} item{path.planned.items === 1 ? '' : 's'} ·{' '}
                      {path.planned.points.length} depth point{path.planned.points.length === 1 ? '' : 's'}
                      {path.planned.planned_days !== null ? ` · ${path.planned.planned_days} planned days` : ''}
                    </Typography>
                  )}
                  {path.assumption && (
                    <Caution
                      cautionKey="path-assumption"
                      page={CAUTION_PAGE}
                      severity="info"
                      icon={false}
                      signature={[path.assumption]}
                      sx={{ fontSize: 12.5 }}
                    >
                      {path.assumption}
                    </Caution>
                  )}
                  {path.notes.slice(0, 8).map((note) => (
                    <Typography key={note} variant="caption" display="block" color="text.secondary">
                      {note}
                    </Typography>
                  ))}
                  {path.notes.length > 8 && (
                    <Typography variant="caption" color="text.secondary">
                      …and {path.notes.length - 8} more note{path.notes.length - 8 === 1 ? '' : 's'}.
                    </Typography>
                  )}
                  {!path.is_surveyed && (
                    <Caution
                      cautionKey="no-survey"
                      page={CAUTION_PAGE}
                      severity="warning"
                      icon={false}
                      sx={{ fontSize: 12.5 }}
                    >
                      No survey has been recorded for this well and scope. The current depth still comes from the
                      latest report&apos;s header, but no trajectory can be drawn.
                    </Caution>
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
                        At {fmtDepth(row.md_m, 2)} m MD: printed {fmtDepth(row.printed_tvd_m, 2)} m TVD, integrated{' '}
                        {fmtDepth(row.computed_tvd_m, 2)} m ({row.difference_m > 0 ? '+' : ''}
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

          <Typography variant="caption" color="text.secondary" display="block" mt={1}>
            The selected mark opens a source drawer from the table, the dogleg chart, the jump list and the keyboard:
            the facts are the same because the drawer receives the station or interval identity, never a chart pixel.
          </Typography>
        </>
      )}

      {path && (
        <WellSourceDialog
          open={explain !== null}
          onClose={() => setExplain(null)}
          path={path}
          mark={explain}
        />
      )}
    </Box>
  )
}

function SnapshotRow({ label, value, note }: { label: string; value: string; note?: string }) {
  return (
    <Box display="flex" justifyContent="space-between" gap={1.5} sx={{ borderBottom: 1, borderColor: 'divider', pb: 0.6 }}>
      <Box sx={{ minWidth: 0 }}>
        <Typography sx={{ fontSize: 12.5, color: 'text.secondary' }}>{label}</Typography>
        {note ? <Typography sx={{ fontSize: 10.5, color: 'text.secondary' }}>{note}</Typography> : null}
      </Box>
      <Typography sx={{ fontSize: 13, fontWeight: 700, textAlign: 'right', whiteSpace: 'nowrap' }}>{value}</Typography>
    </Box>
  )
}
