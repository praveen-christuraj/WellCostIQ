import type { OpsWellPathInterval, OpsWellPathStation } from './operations'

/**
 * Display arithmetic for the well-path visuals.
 *
 * The backend owns every engineering rule (minimum curvature, dogleg severity,
 * the vertical-section projection). This module only does the things a chart
 * needs and the server should not: slicing a curve to a measured-depth window,
 * interpolating *between* two recorded stations for a drawing position, and
 * formatting a value that may legitimately be "no interval" rather than zero.
 *
 * Nothing here may be used to produce a figure that is presented as recorded:
 * `interpolateAt` returns an `interpolated` flag for exactly that reason.
 */

export type DepthWindow = { from: number | null; to: number | null }

export type CurvePoint = {
  md_m: number
  inc_deg: number
  azi_deg: number
  tvd_m: number
  ns_m: number
  ew_m: number
  vsec_m: number
}

/** A dash for a missing value; a zero is a reading and prints as 0.0. */
export function fmtDepth(value: number | null | undefined, digits = 2): string {
  return typeof value === 'number' && Number.isFinite(value)
    ? `${value.toLocaleString(undefined, { minimumFractionDigits: digits, maximumFractionDigits: digits })}`
    : '—'
}

export function fmtAngle(value: number | null | undefined, digits = 2): string {
  return typeof value === 'number' && Number.isFinite(value) ? `${value.toFixed(digits)}°` : '—'
}

/** Severity with its unit. `null` means "no interval", not "zero dogleg". */
export function fmtDls(value: number | null | undefined, digits = 3): string {
  return typeof value === 'number' && Number.isFinite(value) ? `${value.toFixed(digits)} °/30 m` : '— no interval'
}

export function fmtNumber(value: number | null | undefined, digits = 1): string {
  return typeof value === 'number' && Number.isFinite(value) ? value.toLocaleString(undefined, {
    minimumFractionDigits: digits,
    maximumFractionDigits: digits,
  }) : '—'
}

/** The deepest station of an accepted curve. */
export function lastStation(curve: OpsWellPathStation[]): OpsWellPathStation | null {
  return curve.length ? curve[curve.length - 1] : null
}

/** The station whose depth is closest to `md`, within `tolerance` metres. */
export function stationAt(curve: OpsWellPathStation[], md: number | null, tolerance = 0.05): OpsWellPathStation | null {
  if (md === null || !Number.isFinite(md)) return null
  let best: OpsWellPathStation | null = null
  let bestGap = Number.POSITIVE_INFINITY
  for (const station of curve) {
    const gap = Math.abs(station.md_m - md)
    if (gap <= tolerance && gap < bestGap) {
      best = station
      bestGap = gap
    }
  }
  return best
}

export type InterpolatedPosition = CurvePoint & {
  /** True where the position was estimated between two stations, not recorded. */
  interpolated: boolean
}

/**
 * Position at a free measured depth, by linear interpolation between the two
 * stations that bracket it.
 *
 * Returns `null` outside the surveyed range: the plan's rule is that a depth
 * below the last station is *unsurveyed*, so a chart must not extend the last
 * tangent and call the result a position.
 */
export function interpolateAt(curve: OpsWellPathStation[], md: number | null): InterpolatedPosition | null {
  if (md === null || !Number.isFinite(md) || curve.length === 0) return null
  if (md < curve[0].md_m - 1e-6 || md > curve[curve.length - 1].md_m + 1e-6) return null
  for (const station of curve) {
    if (Math.abs(station.md_m - md) <= 1e-6) {
      return {
        md_m: station.md_m,
        inc_deg: station.inc_deg,
        azi_deg: station.azi_deg,
        tvd_m: station.tvd_m,
        ns_m: station.ns_m,
        ew_m: station.ew_m,
        vsec_m: station.vsec_m,
        interpolated: false,
      }
    }
  }
  for (let index = 1; index < curve.length; index += 1) {
    const a = curve[index - 1]
    const b = curve[index]
    if (md >= a.md_m && md <= b.md_m) {
      const span = b.md_m - a.md_m
      if (span <= 0) {
        return { ...positionOf(b), interpolated: false }
      }
      const f = (md - a.md_m) / span
      return {
        md_m: md,
        inc_deg: a.inc_deg + f * (b.inc_deg - a.inc_deg),
        azi_deg: a.azi_deg + f * shortestAzimuthDelta(a.azi_deg, b.azi_deg),
        tvd_m: a.tvd_m + f * (b.tvd_m - a.tvd_m),
        ns_m: a.ns_m + f * (b.ns_m - a.ns_m),
        ew_m: a.ew_m + f * (b.ew_m - a.ew_m),
        vsec_m: a.vsec_m + f * (b.vsec_m - a.vsec_m),
        interpolated: true,
      }
    }
  }
  return null
}

function positionOf(station: OpsWellPathStation): CurvePoint {
  return {
    md_m: station.md_m,
    inc_deg: station.inc_deg,
    azi_deg: station.azi_deg,
    tvd_m: station.tvd_m,
    ns_m: station.ns_m,
    ew_m: station.ew_m,
    vsec_m: station.vsec_m,
  }
}

/** Signed change across the 0/360 wrap, so 359° → 1° is +2°, not −358°. */
export function shortestAzimuthDelta(from: number, to: number): number {
  return ((to - from + 540) % 360) - 180
}

/**
 * The curve restricted to a measured-depth window, with a point interpolated at
 * each window edge so a chart does not appear to start or stop mid-air.
 */
export function sliceCurve(curve: OpsWellPathStation[], window: DepthWindow): CurvePoint[] {
  if (!curve.length) return []
  const first = curve[0].md_m
  const last = curve[curve.length - 1].md_m
  const lower = Math.max(first, window.from ?? first)
  const upper = Math.min(last, window.to ?? last)
  if (upper < lower) return []
  const points: CurvePoint[] = []
  const start = interpolateAt(curve, lower)
  if (start) points.push(start)
  for (const station of curve) {
    if (station.md_m > lower + 1e-6 && station.md_m < upper - 1e-6) points.push(positionOf(station))
  }
  const end = interpolateAt(curve, upper)
  if (end && (points.length === 0 || Math.abs(end.md_m - points[points.length - 1].md_m) > 1e-6)) points.push(end)
  return points
}

/** The window actually applied, after clamping to the surveyed range. */
export function effectiveWindow(curve: OpsWellPathStation[], window: DepthWindow): { from: number; to: number } {
  const first = curve.length ? curve[0].md_m : 0
  const last = curve.length ? curve[curve.length - 1].md_m : 0
  const from = Math.max(first, Math.min(window.from ?? first, last))
  const to = Math.min(last, Math.max(window.to ?? last, from))
  return { from, to }
}

/**
 * A symmetric range around zero for a plan view, so north and east share one
 * scale. Equal scaling is the only way a plan view can be read for direction.
 */
export function equalPlanBounds(points: CurvePoint[], fallback = 50): [number, number] {
  const values = [0, ...points.flatMap((point) => [point.ns_m, point.ew_m])]
  const low = Math.min(...values)
  const high = Math.max(...values)
  const span = Math.max(high - low, fallback)
  const pad = span * 0.08
  return [low - pad, low + span + pad]
}

/** Nice ceiling for a severity axis so bars never touch the top rule. */
export function dlsAxisMax(intervals: OpsWellPathInterval[]): number {
  const values = intervals
    .flatMap((interval) => [interval.dls_deg_per_30m, interval.recorded_dls_deg_per_30m])
    .filter((value): value is number => typeof value === 'number' && Number.isFinite(value))
  const peak = values.length ? Math.max(...values) : 0
  const steps = [1, 2, 3, 5, 10, 15, 20, 30, 50, 100]
  const target = Math.max(peak * 1.15, 1)
  return steps.find((step) => step >= target) ?? Math.ceil(target)
}

/** The interval that ends at `md`, when that depth is a station. */
export function intervalEndingAt(intervals: OpsWellPathInterval[], md: number | null, tolerance = 0.05): OpsWellPathInterval | null {
  if (md === null) return null
  return intervals.find((interval) => Math.abs(interval.to_md_m - md) <= tolerance) ?? null
}

/**
 * Break a series at an azimuth wrap instead of drawing a false full turn.
 *
 * A 359° → 1° step is a 2° turn; joined naively it is a 358° line across the
 * chart, which reads as a rotation the well never made. A `null` value is the gap
 * ECharts needs to stop the line, so one gap point is inserted immediately before
 * the station that crosses 360°.
 */
export function azimuthSeries(points: { md_m: number; azi_deg: number }[]): {
  data: [number, number | null][]
  wraps: number[]
} {
  const data: [number, number | null][] = []
  const wraps: number[] = []
  let previous: number | null = null
  for (const point of points) {
    if (previous !== null && Math.abs(point.azi_deg - previous) > 180) {
      data.push([point.md_m, null])
      wraps.push(point.md_m)
    }
    data.push([point.md_m, point.azi_deg])
    previous = point.azi_deg
  }
  return { data, wraps }
}

/** Whether a measured depth sits inside the surveyed range. */
export function isSurveyed(curve: OpsWellPathStation[], md: number | null): boolean {
  if (md === null || !curve.length) return false
  return md >= curve[0].md_m - 1e-6 && md <= curve[curve.length - 1].md_m + 1e-6
}
