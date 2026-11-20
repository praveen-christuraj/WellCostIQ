import type { ReactNode } from 'react'
import { Link as RouterLink } from 'react-router-dom'
import { Alert, Box, Button, Chip, Divider, Stack, Typography } from '@mui/material'
import { PanelDialog } from '../Common'
import type { OpsWellPath, OpsWellPathInterval, OpsWellPathSurveyStation } from '../../lib/operations'
import { fmtAngle, fmtDepth, fmtDls, fmtNumber, intervalEndingAt, stationAt } from '../../lib/wellPath'

/**
 * "Explain this" for one mark on the well visuals.
 *
 * The dialog answers the four questions a drawing cannot: **what** the number is,
 * **where it came from** (report or workbook, page/section, row/column), **who or
 * what calculated it**, and **what it is not**. Every fact is tagged as recorded,
 * calculated, configured or missing, and the original value is shown beside the
 * calculated one instead of being replaced by it.
 *
 * A mark is passed as an identity — a station depth or an interval — never as a
 * chart pixel, so the same dialog opens from a table row, a bar and a keyboard
 * selection.
 */
export type WellMark =
  | { kind: 'station'; md: number }
  | { kind: 'interval'; toMd: number }
  | { kind: 'hole' }
  | { kind: 'bit' }
  | { kind: 'seat'; depth: number }

const CALCULATION_VERSION = 'Minimum curvature (ratio factor on a zero-dogleg pair) · severity normalised to 30 m'

export function WellSourceDialog({
  open,
  onClose,
  path,
  mark,
}: {
  open: boolean
  onClose: () => void
  path: OpsWellPath
  mark: WellMark | null
}) {
  return <PanelDialog open={open} onClose={onClose} maxWidth="md"
    title={mark ? titleFor(mark) : 'Explain this mark'}
    subtitle={`${path.well_code} · ${path.scope} · stations are points, severity belongs to an interval`}>
    {mark && <WellSourceContent path={path} mark={mark} />}
  </PanelDialog>
}

export function WellSourceContent({ path, mark }: { path: OpsWellPath; mark: WellMark }) {
  const station: OpsWellPathSurveyStation | null = mark.kind === 'station'
    ? path.survey_stations.find((row) => Math.abs(row.md_m - mark.md) <= 0.05) ?? null
    : mark.kind === 'interval'
      ? path.survey_stations.find((row) => Math.abs(row.md_m - mark.toMd) <= 0.05) ?? null
      : null
  const interval: OpsWellPathInterval | null = mark.kind === 'interval'
    ? intervalEndingAt(path.intervals, mark.toMd)
    : mark.kind === 'station'
      ? intervalEndingAt(path.intervals, mark.md)
      : null

  return (
    <Stack spacing={2.25}>
      <ScopeBlock path={path} />

      {mark.kind === 'station' && (
        <StationBlock path={path} station={station} md={mark.md} interval={interval} />
      )}

      {mark.kind === 'interval' && (
        <IntervalBlock path={path} interval={interval} station={station} toMd={mark.toMd} />
      )}

      {mark.kind === 'hole' && <HoleBlock path={path} />}
      {mark.kind === 'bit' && <BitBlock path={path} />}
      {mark.kind === 'seat' && <SeatBlock path={path} depth={mark.depth} />}

      <Divider />
      <Typography sx={{ fontSize: 11, color: 'text.secondary', lineHeight: 1.55 }}>
        Calculation: {CALCULATION_VERSION}. Original report and workbook values stay attached to the record;
        nothing here re-writes a printed figure to make the drawing agree with it.
      </Typography>
    </Stack>
  )
}

function titleFor(mark: WellMark): string {
  switch (mark.kind) {
    case 'station':
      return `Survey station at ${fmtDepth(mark.md, 2)} m MD`
    case 'interval':
      return `Dogleg severity interval ending at ${fmtDepth(mark.toMd, 2)} m MD`
    case 'hole':
      return 'Hole depth from the selected report'
    case 'bit':
      return 'Reported bit / string depth'
    case 'seat':
      return `Casing shoe at ${fmtDepth(mark.depth, 2)} m MD`
  }
}

function Tag({ tone, children }: { tone: 'recorded' | 'calculated' | 'configured' | 'missing'; children: string }) {
  const palette = {
    recorded: { color: 'success.main', variant: 'outlined' as const },
    calculated: { color: 'info.main', variant: 'outlined' as const },
    configured: { color: 'warning.main', variant: 'outlined' as const },
    missing: { color: 'text.secondary', variant: 'outlined' as const },
  }[tone]
  return <Chip size="small" label={children} color={palette.color as 'success' | 'info' | 'warning' | 'default'} variant={palette.variant} sx={{ height: 19, fontSize: 10, '& .MuiChip-label': { px: 0.75 } }} />
}

function Row({ label, value, note }: { label: string; value: ReactNode; note?: string }) {
  return (
    <Box display="grid" gridTemplateColumns={{ xs: '1fr', sm: 'minmax(150px, 190px) 1fr' }} gap={0.5} sx={{ borderBottom: 1, borderColor: 'divider', pb: 0.7 }}>
      <Typography sx={{ fontSize: 12, color: 'text.secondary' }}>{label}</Typography>
      <Box>
        <Typography sx={{ fontSize: 12.5, fontWeight: 600 }} component="div">{value}</Typography>
        {note ? <Typography sx={{ fontSize: 11, color: 'text.secondary', mt: 0.25 }}>{note}</Typography> : null}
      </Box>
    </Box>
  )
}

function ScopeBlock({ path }: { path: OpsWellPath }) {
  return (
    <Box>
      <Typography sx={{ fontSize: 12, fontWeight: 700, mb: 0.75 }}>Scope and record</Typography>
      <Row label="Well / scope" value={`${path.well_code} · ${path.scope}`} note={path.datum} />
      <Row
        label="Survey"
        value={`${path.survey.stations} station${path.survey.stations === 1 ? '' : 's'} · ${fmtDepth(path.survey.first_md_m, 2)} → ${fmtDepth(path.survey.last_md_m, 2)} m MD`}
        note={path.survey.anchor_basis}
      />
      <Row
        label="Vertical section"
        value={`Plane facing ${fmtAngle(path.vertical_section_azimuth_deg, 2)}`}
        note="A projection of the same stations; rotating the plane changes the shadow, not the well."
      />
    </Box>
  )
}

function StationBlock({
  path,
  station,
  md,
  interval,
}: {
  path: OpsWellPath
  station: OpsWellPathSurveyStation | null
  md: number
  interval: OpsWellPathInterval | null
}) {
  const curveRow = stationAt(path.curve, md)
  return (
    <>
      <Box>
        <Typography component="div" sx={{ fontSize: 12, fontWeight: 700, mb: 0.75 }}>
          Recorded <Tag tone="recorded">recorded</Tag>
        </Typography>
        {!station ? (
          <Alert severity="warning" sx={{ fontSize: 12 }}>
            No stored survey row matches {fmtDepth(md, 2)} m. The point may be an interpolated position between
            two stations, which is calculated and labelled as such, not recorded.
          </Alert>
        ) : (
          <>
            <Row label="Measured depth" value={`${fmtDepth(station.md_m, 2)} m`} note={`Station ${station.station_no ?? '—'} · ${station.tool || station.source || 'source not stated'}`} />
            <Row label="Inclination" value={fmtAngle(station.inc_deg)} />
            <Row label="Azimuth" value={fmtAngle(station.azi_deg)} note="Clockwise from the survey's stated north reference." />
            <Row label="Printed TVD" value={fmtDepth(station.recorded_tvd_m, 2) === '—' ? 'not printed' : `${fmtDepth(station.recorded_tvd_m, 2)} m`} />
            <Row
              label="Printed N / E"
              value={station.recorded_ns_m === null && station.recorded_ew_m === null
                ? 'not printed'
                : `N ${fmtDepth(station.recorded_ns_m, 2)} m · E ${fmtDepth(station.recorded_ew_m, 2)} m`}
            />
            <Row
              label="Reported DLS"
              value={station.recorded_dls_deg_per_30m === null ? 'not reported' : fmtDls(station.recorded_dls_deg_per_30m)}
              note="A reported rate is a separate mark; it never replaces the calculation."
            />
            <Row
              label="Source"
              value={station.report_id
                ? `Report ${station.report_no || station.report_date || ''} · ${station.report_date ?? 'no date'} · ${station.report_status || 'status unknown'}`
                : `${station.source || 'manual entry'}${station.source_page ? ` · page ${station.source_page}` : ''}`}
              note={station.survey_at ? `Recorded at ${station.survey_at}` : 'No station timestamp is stored; no timestamp is invented from the file date.'}
            />
            {station.rows_at_md > 1 && (
              <Typography sx={{ fontSize: 11, color: 'warning.main', mt: 0.5 }}>
                {station.rows_at_md} stored rows share this measured depth; the latest row is the one drawn and the
                others remain on their own reports.
              </Typography>
            )}
          </>
        )}
      </Box>

      <Box>
        <Typography component="div" sx={{ fontSize: 12, fontWeight: 700, mb: 0.75 }}>
          Calculated <Tag tone="calculated">calculated</Tag>
        </Typography>
        {!curveRow ? (
          <Typography sx={{ fontSize: 12, color: 'text.secondary' }}>
            This depth is outside the drawn curve, so no position is calculated for it.
          </Typography>
        ) : (
          <>
            <Row label="TVD" value={`${fmtDepth(curveRow.tvd_m, 2)} m`} note={station?.recorded_tvd_m !== null && station?.recorded_tvd_m !== undefined
              ? `Printed ${fmtDepth(station.recorded_tvd_m, 2)} m · difference ${fmtDepth((station.recorded_tvd_m ?? 0) - curveRow.tvd_m, 2)} m`
              : 'No TVD was printed for this station.'} />
            <Row label="North / East" value={`N ${fmtDepth(curveRow.ns_m, 2)} m · E ${fmtDepth(curveRow.ew_m, 2)} m`} />
            <Row label="Vertical section" value={`${fmtDepth(curveRow.vsec_m, 2)} m`} note={`Plane ${fmtAngle(path.vertical_section_azimuth_deg, 1)}.`} />
            <Row
              label="Dogleg severity"
              value={curveRow.dls_deg_per_30m === null ? '— no interval' : fmtDls(curveRow.dls_deg_per_30m)}
              note={curveRow.interval_issue || (curveRow.is_anchor
                ? 'The first station has no interval above it, so it has no severity. That is not a zero dogleg.'
                : 'Severity of the interval that ends at this station.')}
            />
            <Row
              label="Build / turn"
              value={curveRow.build_deg_per_30m === null
                ? '—'
                : `${fmtNumber(curveRow.build_deg_per_30m, 3)} / ${fmtNumber(curveRow.turn_deg_per_30m, 3)} °/30 m`}
              note="Build is the inclination change. Turn is inclination-weighted, so it is not the raw azimuth change."
            />
          </>
        )}
      </Box>

      {interval && (
        <Box>
          <Typography sx={{ fontSize: 12, fontWeight: 700, mb: 0.75 }}>Interval above this station</Typography>
          <Row
            label="Depth interval"
            value={`${fmtDepth(interval.from_md_m, 2)} → ${fmtDepth(interval.to_md_m, 2)} m MD`}
            note={`ΔMD ${fmtDepth(interval.delta_md_m, 2)} m.`}
          />
          <Row
            label="Direction change"
            value={interval.beta_deg === null ? 'not calculable' : `${interval.beta_deg.toFixed(5)}°`}
            note="The angle between the two 3D tangent directions."
          />
          <Row
            label="Calculated DLS"
            value={fmtDls(interval.dls_deg_per_30m)}
            note={interval.recorded_dls_deg_per_30m !== null
              ? `Reported ${fmtDls(interval.recorded_dls_deg_per_30m)} · difference ${interval.dls_difference_deg_per_30m !== null ? `${interval.dls_difference_deg_per_30m >= 0 ? '+' : ''}${interval.dls_difference_deg_per_30m.toFixed(4)}` : '—'}`
              : 'No reported rate for this interval.'}
          />
          {interval.issue && <Alert severity={interval.valid ? 'info' : 'warning'} sx={{ fontSize: 11.5 }}>{interval.issue}</Alert>}
        </Box>
      )}
    </>
  )
}

function IntervalBlock({
  path,
  interval,
  station,
  toMd,
}: {
  path: OpsWellPath
  interval: OpsWellPathInterval | null
  station: OpsWellPathSurveyStation | null
  toMd: number
}) {
  if (!interval) {
    return (
      <Alert severity="info" sx={{ fontSize: 12 }}>
        I need a previous valid station. The first accepted station at {fmtDepth(path.survey.first_md_m, 2)} m has
        no interval above it, so no severity can be calculated for it.
      </Alert>
    )
  }
  const from = path.survey_stations.find((row) => Math.abs(row.md_m - interval.from_md_m) <= 0.05) ?? null
  return (
    <>
      <Box>
        <Typography component="div" sx={{ fontSize: 12, fontWeight: 700, mb: 0.75 }}>
          The two stations <Tag tone="recorded">recorded</Tag>
        </Typography>
        <Row label="Upper station" value={`${fmtDepth(interval.from_md_m, 2)} m MD · ${fmtAngle(interval.inc1_deg)} / ${fmtAngle(interval.azi1_deg)}`} note={from?.report_date ? `Report ${from.report_no || from.report_date} · ${from.report_date}` : undefined} />
        <Row label="Lower station" value={`${fmtDepth(interval.to_md_m, 2)} m MD · ${fmtAngle(interval.inc2_deg)} / ${fmtAngle(interval.azi2_deg)}`} note={station?.report_date ? `Report ${station.report_no || station.report_date} · ${station.report_date}` : undefined} />
        <Row label="Course length" value={`L = ${fmtDepth(interval.delta_md_m, 2)} m`} note="The length actually drilled between the two stations." />
      </Box>

      <Box>
        <Typography component="div" sx={{ fontSize: 12, fontWeight: 700, mb: 0.75 }}>
          The calculation <Tag tone="calculated">calculated</Tag>
        </Typography>
        <Typography sx={{ fontSize: 11.5, lineHeight: 1.7, fontFamily: 'ui-monospace, SFMono-Regular, Menlo, monospace', bgcolor: 'background.default', p: 1.25, borderRadius: 1 }}>
          1. Convert I₁, I₂ and ΔA to radians.<br />
          2. h = sin²((I₂ − I₁)/2) + sin I₁ · sin I₂ · sin²(ΔA/2)<br />
          3. β = 2 · asin(√h) = {interval.beta_deg === null ? '—' : `${interval.beta_deg.toFixed(5)}°`}<br />
          4. DLS = β × 30 / L = {interval.dls_deg_per_30m === null ? '—' : `${interval.dls_deg_per_30m.toFixed(4)} °/30 m`}
        </Typography>
        <Row
          label="Reported rate"
          value={interval.recorded_dls_deg_per_30m === null ? 'not reported' : fmtDls(interval.recorded_dls_deg_per_30m)}
          note={interval.dls_difference_deg_per_30m !== null
            ? `Printed − calculated = ${interval.dls_difference_deg_per_30m >= 0 ? '+' : ''}${interval.dls_difference_deg_per_30m.toFixed(4)} °/30 m. A printed rate in °/100 ft is multiplied by 30/30.48, not by the ft-to-m length factor.`
            : undefined}
        />
        {interval.issue && <Alert severity={interval.valid ? 'info' : 'warning'} sx={{ fontSize: 11.5, mt: 0.75 }}>{interval.issue}</Alert>}
      </Box>

      <Box>
        <Typography sx={{ fontSize: 12, fontWeight: 700, mb: 0.5 }}>What this is not</Typography>
        <Typography sx={{ fontSize: 11.5, color: 'text.secondary', lineHeight: 1.6 }}>
          Not the inclination, not the azimuth change on its own, and not an instantaneous curvature. The azimuth
          may have changed by only a fraction of a degree and the dogleg can still be larger or smaller than that,
          because the angle between the two directions depends on both angles. A peak marks an interval to inspect —
          it is not proof of unsafe drilling, and no tool limit is assumed.
        </Typography>
      </Box>
      {Math.abs(path.survey.last_md_m ?? 0) > 0 && Math.abs(toMd - (path.survey.last_md_m ?? 0)) < 0.05 && (
        <Typography sx={{ fontSize: 11, color: 'text.secondary' }}>
          This is the last interval in the record. Beyond {fmtDepth(path.survey.last_md_m, 2)} m MD the hole is
          unsurveyed, so the line stops rather than continuing along the last tangent.
        </Typography>
      )}
    </>
  )
}

function HoleBlock({ path }: { path: OpsWellPath }) {
  const snapshot = path.snapshot
  return (
    <Box>
      <Typography component="div" sx={{ fontSize: 12, fontWeight: 700, mb: 0.75 }}>
        Hole depth <Tag tone="recorded">recorded</Tag>
      </Typography>
      <Row label="Closing MD" value={snapshot.hole_depth_m === null ? 'not recorded' : `${fmtDepth(snapshot.hole_depth_m, 2)} m`} />
      <Row label="TVD (printed)" value={snapshot.hole_tvd_m === null ? 'not recorded' : `${fmtDepth(snapshot.hole_tvd_m, 2)} m`} note={snapshot.tvd_source || undefined} />
      <Row
        label="Report"
        value={snapshot.report_date ? `${snapshot.report_no || 'Report'} · ${snapshot.report_date} · ${snapshot.status}` : snapshot.basis}
        note="The hole depth is the report's closing measured depth. It is never replaced by the newest survey."
      />
      <Row
        label="Datum"
        value={path.datum}
      />
      {snapshot.current_status_text && (
        <Row label="Current status (as printed)" value={snapshot.current_status_text} note="Kept as evidence; it is not parsed into separate positions." />
      )}
      <Row
        label="Survey endpoint"
        value={path.position.survey_end_md_m === null ? 'no station' : `${fmtDepth(path.position.survey_end_md_m, 2)} m`}
        note={path.position.gap_m !== null && path.position.gap_m > 0
          ? `${fmtDepth(path.position.gap_m, 2)} m of hole below the last station is unsurveyed: no direction was measured there.`
          : 'The survey reaches the reported hole depth. Missing is not surface, and a gap is not drawn as a line.'}
      />
    </Box>
  )
}

function BitBlock({ path }: { path: OpsWellPath }) {
  const snapshot = path.snapshot
  return (
    <Box>
      <Typography component="div" sx={{ fontSize: 12, fontWeight: 700, mb: 0.75 }}>
        Bit / string <Tag tone={snapshot.bit_depth_m === null ? 'missing' : 'recorded'}>{snapshot.bit_depth_m === null ? 'missing' : 'recorded'}</Tag>
      </Typography>
      <Row label="Depth" value={snapshot.bit_depth_m === null ? 'not recorded' : `${fmtDepth(snapshot.bit_depth_m, 2)} m MD`} note={snapshot.label} />
      <Row
        label="Off bottom"
        value={snapshot.off_bottom_m === null ? 'not comparable' : `${fmtDepth(snapshot.off_bottom_m, 2)} m`}
        note={snapshot.off_bottom_note}
      />
      <Row
        label="Report"
        value={snapshot.report_date ? `${snapshot.report_no || 'Report'} · ${snapshot.report_date} · ${snapshot.status}` : snapshot.basis}
        note="The position is an observation at a stated report status, not a live sensor reading."
      />
      <Typography sx={{ fontSize: 11.5, color: 'text.secondary', lineHeight: 1.6 }}>
        A bit can move up while the hole bottom stays put: the triangle tracks the tool, the dashed rule tracks the
        hole. Off-bottom distance is only arithmetic when both come from the same report, datum and bore. “Out of
        hole” needs an explicit observation and is never inferred from a missing depth.
      </Typography>
    </Box>
  )
}

function SeatBlock({ path, depth }: { path: OpsWellPath; depth: number }) {
  const seat = path.casing_seats.find((row) => Math.abs(row.depth_m - depth) <= 0.05)
    ?? null
  const section = path.sections.find((row) => Math.abs(row.to_depth_m - depth) <= 0.05) ?? null
  return (
    <Box>
      <Typography component="div" sx={{ fontSize: 12, fontWeight: 700, mb: 0.75 }}>
        Casing shoe <Tag tone={seat ? 'recorded' : 'configured'}>{seat ? 'recorded' : 'configured'}</Tag>
      </Typography>
      <Row label="Size" value={seat?.size_label ?? section?.casing_label ?? 'unknown'} note="A shoe is placed by a recorded depth; the size alone cannot place it." />
      <Row label="Shoe MD" value={`${fmtDepth(depth, 2)} m`} note={`Interval drawn from ${fmtDepth(section?.from_depth_m ?? null, 2)} m.`} />
      <Row
        label="Source"
        value={seat?.source ?? section?.source ?? 'drawing configuration'}
        note={seat?.report_date ? `Last printed on ${seat.report_date}.` : 'Not printed on a report; supplied by the well configuration.'}
      />
      <Row label="Hole size" value={section?.hole_size_in === null || section?.hole_size_in === undefined ? 'not recorded' : `${section.hole_size_in} in`} note="Hole size is not pipe outside diameter." />
      <Typography sx={{ fontSize: 11.5, color: 'text.secondary', lineHeight: 1.6 }}>
        Only what the record describes is drawn. A recorded shoe with an unknown top gets a wedge and a label; a
        configured interval is design, never installed casing. No liner, cement, tubing, packer or total depth is
        fabricated here.
      </Typography>
      {seat?.report_date && path.snapshot.report_id && (
        <Button size="small" component={RouterLink} to={`/operations/reports/${path.snapshot.report_id}`} sx={{ mt: 0.5 }}>
          Open the report
        </Button>
      )}
    </Box>
  )
}

export default WellSourceDialog
