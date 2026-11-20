import { useMemo } from 'react'
import { Alert, Box, Chip, Stack, Typography } from '@mui/material'
import { useColorMode } from '../../context/ThemeContext'
import { brand, surface } from '../../designSystem'
import type { OpsWellPath, OpsWellPathSection, OpsWellVisual } from '../../lib/operations'

/**
 * Well diagram — drawn from the record, never from a template.
 *
 * Two views of the same well share one vertical depth axis so a reader can put
 * them side by side:
 *
 * * **Casing schematic** (left): every recorded casing seat as a string whose
 *   wall width follows the pipe size, the open hole below the last shoe, and a
 *   marker at the current depth from the latest report. A section is only drawn
 *   where a seat was actually recorded; nothing is inferred.
 * * **Vertical section** (right): the integrated trajectory (TVD against
 *   horizontal departure in the well's own closure plane), with the current
 *   position marked. A vertical well is a straight line and that is exactly what
 *   it should look like.
 *
 * The SVG is deterministic: same records, same drawing, in both themes and in
 * the PDF (the print path rasterises this component through the existing chart
 * export).
 */

const WIDTH = 520
const TOP = 22
const BOTTOM = 26
const SCHEMATIC_X = 150
const SECTION_LEFT = 44
const SECTION_WIDTH = 212
const DRILL_RIGHT = 300
const DRILL_WIDTH = 200

function niceDepth(maxDepth: number): number {
  if (!Number.isFinite(maxDepth) || maxDepth <= 0) return 100
  const target = maxDepth * 1.08
  const steps = [50, 100, 200, 250, 500, 1000, 1500, 2000, 2500, 5000]
  const step = steps.find((s) => target / s <= 6) ?? 10000
  return Math.ceil(target / step) * step
}

export function WellDiagram({
  path,
  height = 420,
  compact = false,
}: {
  /**
   * Either the full path (trajectory, seats, provenance) or the dashboard's
   * lighter `well_visual`. The lighter record draws the schematic and current
   * depth but has no curve, and the component says so rather than inventing one.
   */
  path: OpsWellPath | OpsWellVisual
  height?: number
  compact?: boolean
}) {
  const { mode } = useColorMode()
  const s = surface(mode)
  const summary = path.summary
  const currentMd = summary.current_md_m
  const curve = 'curve' in path ? path.curve : []
  const vsAzimuth = 'vertical_section_azimuth_deg' in path ? path.vertical_section_azimuth_deg : null

  /**
   * One vertical axis has to serve both views, and the two views are measured
   * differently: the casing seats are recorded at measured depth, while the
   * vertical section is true vertical depth against departure. Putting a TVD
   * curve on an MD axis makes a deviated well look shallower than its own shoe,
   * so the axis is TVD whenever a trajectory exists and the casing depths are
   * carried through it. Where no survey exists there is nothing to convert with,
   * and the axis says MD.
   */
  const axis = useMemo(() => {
    const points = curve
      .filter((row) => Number.isFinite(row.md_m) && Number.isFinite(row.tvd_m))
      .map((row) => [row.md_m, row.tvd_m] as [number, number])
    const usable = points.length >= 2 && summary.max_inc_deg !== null && summary.max_inc_deg > 0.5
    const toAxis = (md: number | null | undefined): number | null => {
      if (md === null || md === undefined || !Number.isFinite(md)) return null
      if (!usable) return md
      if (md <= points[0][0]) return points[0][1]
      for (let i = 1; i < points.length; i += 1) {
        const [md0, tvd0] = points[i - 1]
        const [md1, tvd1] = points[i]
        if (md <= md1) {
          const span = md1 - md0
          return span <= 0 ? tvd1 : tvd0 + ((md - md0) / span) * (tvd1 - tvd0)
        }
      }
      // Beyond the last station the well is un-surveyed: the last measured
      // vertical rate is the only defensible extension, so use it and say so.
      const [md0, tvd0] = points[points.length - 2]
      const [md1, tvd1] = points[points.length - 1]
      const span = md1 - md0
      return span <= 0 ? tvd1 : tvd1 + ((md - md1) / span) * (tvd1 - tvd0)
    }
    return { label: usable ? 'TVD (m)' : 'MD (m)', toAxis, usable }
  }, [curve, summary.max_inc_deg])

  const maxDepth = useMemo(() => {
    const values = [
      ...path.sections.map((row) => axis.toAxis(row.to_depth_m)),
      axis.toAxis(currentMd),
      axis.toAxis(path.open_hole?.to_depth_m),
      ...curve.map((row) => row.tvd_m),
    ].filter((v): v is number => typeof v === 'number' && Number.isFinite(v))
    return niceDepth(Math.max(...values, 100))
  }, [path.sections, path.open_hole, curve, currentMd, axis])

  const plotHeight = height - TOP - BOTTOM
  const y = (depth: number) => TOP + (Math.max(0, Math.min(depth, maxDepth)) / maxDepth) * plotHeight

  // The vertical section is drawn in its own horizontal scale, because a 400 m
  // departure against a 4,000 m TVD would otherwise be a hairline.
  const maxDeparture = useMemo(() => {
    const values = curve.map((row) => Math.abs(row.vsec_m))
    return Math.max(...values, 50) * 1.05
  }, [curve])
  const dx = (vsec: number) => DRILL_RIGHT + (vsec / maxDeparture) * DRILL_WIDTH

  const curvePoints = curve.map((row) => `${dx(row.vsec_m).toFixed(2)},${y(row.tvd_m).toFixed(2)}`).join(' ')
  const sectionWidth = (row: OpsWellPathSection) => Math.max(6, Math.min(40, 4 + (row.casing_size_in / 30) * 52))

  const axisTicks = useMemo(() => {
    const count = compact ? 4 : 6
    return Array.from({ length: count + 1 }, (_, i) => (maxDepth / count) * i)
  }, [maxDepth, compact])

  if (!path.is_surveyed && !path.sections.length) {
    return (
      <Alert severity="info" sx={{ fontSize: 12.5 }}>
        No surveys or casing seats are recorded for {path.well_code} ({path.scope}), so a diagram would be
        invented. Extract the daily report's survey table or enter the seats on the report's Depth tab.
      </Alert>
    )
  }

  const ink = s.text
  const muted = s.textMuted
  const line = s.divider
  const accent = mode === 'dark' ? brand[300] : brand[700]

  return (
    <Box>
      {/* ``data-chart-precision`` marks the drawing as a capturable chart: the
          PDF export finds it inside an exportable figure and rasterises this
          SVG exactly as rendered, in both themes. It is inert in the browser. */}
      <Box
        component="svg"
        role="img"
        aria-label={`Well diagram for ${path.well_code}`}
        data-chart-precision="1"
        width={WIDTH}
        height={height}
        viewBox={`0 0 ${WIDTH} ${height}`}
        preserveAspectRatio="xMidYMid meet"
        sx={{ display: 'block', width: '100%', height: 'auto', maxHeight: height }}
      >
        {/* Shared depth axis */}
        {axisTicks.map((tick) => (
          <g key={`tick-${tick}`}>
            <line x1={SECTION_LEFT} x2={DRILL_RIGHT + DRILL_WIDTH} y1={y(tick)} y2={y(tick)} stroke={line} strokeWidth={0.6} strokeDasharray={tick === 0 ? '0' : '2 4'} />
            <text x={SECTION_LEFT - 6} y={y(tick) + 3} textAnchor="end" fontSize={8.5} fill={muted}>
              {Math.round(tick).toLocaleString()}
            </text>
          </g>
        ))}
        <text x={SECTION_LEFT - 6} y={TOP - 8} textAnchor="end" fontSize={8.5} fill={muted} fontWeight={700}>
          {axis.label}
        </text>

        {/* Casing schematic */}
        <text x={SECTION_LEFT + SECTION_WIDTH / 2} y={TOP - 8} textAnchor="middle" fontSize={9} fill={muted} fontWeight={700}>
          CASING &amp; HOLE
        </text>
        <line x1={SCHEMATIC_X} x2={SCHEMATIC_X} y1={TOP} y2={TOP + plotHeight} stroke={muted} strokeWidth={1.2} />
        {path.sections.map((row) => {
          const width = sectionWidth(row)
          const top = y(axis.toAxis(row.from_depth_m) ?? 0)
          const bottom = y(axis.toAxis(row.to_depth_m) ?? 0)
          return (
            <g key={`${row.casing_label}-${row.from_depth_m}`}>
              <title>{`${row.casing_label} casing: ${row.from_depth_m.toLocaleString()} m MD → ${row.to_depth_m.toLocaleString()} m MD (${row.source})`}</title>
              <rect x={SCHEMATIC_X - width / 2} y={top} width={width} height={Math.max(1.5, bottom - top)} fill="none" stroke={accent} strokeWidth={1.6} />
              <rect x={SCHEMATIC_X - width / 2 + 1.4} y={top} width={Math.max(1.5, width * 0.22)} height={Math.max(1.5, bottom - top)} fill={accent} opacity={0.22} />
              <rect x={SCHEMATIC_X + width / 2 - 1.4 - Math.max(1.5, width * 0.22)} y={top} width={Math.max(1.5, width * 0.22)} height={Math.max(1.5, bottom - top)} fill={accent} opacity={0.22} />
              {/* The shoe, drawn as the standard angled wedge */}
              <path d={`M ${SCHEMATIC_X - width / 2} ${bottom} L ${SCHEMATIC_X} ${bottom + 5} L ${SCHEMATIC_X + width / 2} ${bottom}`} fill="none" stroke={accent} strokeWidth={1.6} />
              {!compact && (
                <text x={SCHEMATIC_X + Math.max(28, width / 2) + 6} y={top + 9} fontSize={8.5} fill={ink}>
                  {row.casing_label} · {row.to_depth_m.toLocaleString()} m
                </text>
              )}
            </g>
          )
        })}
        {path.open_hole && (
          <g>
            <title>{`Open hole ${path.open_hole.from_depth_m} → ${path.open_hole.to_depth_m} m MD`}</title>
            <line
              x1={SCHEMATIC_X - 12}
              x2={SCHEMATIC_X + 12}
              y1={y(axis.toAxis(path.open_hole.from_depth_m) ?? 0)}
              y2={y(axis.toAxis(path.open_hole.to_depth_m) ?? 0)}
              stroke={accent}
              strokeWidth={0.8}
              strokeDasharray="3 3"
            />
          </g>
        )}

        {/* Current depth marker across both views */}
        {currentMd !== null && axis.toAxis(currentMd) !== null && (
          <g>
            <title>{`Current depth ${currentMd.toLocaleString()} m MD (${summary.depth_basis})`}</title>
            <line x1={SECTION_LEFT} x2={DRILL_RIGHT + DRILL_WIDTH} y1={y(axis.toAxis(currentMd) ?? 0)} y2={y(axis.toAxis(currentMd) ?? 0)} stroke={mode === 'dark' ? '#F2C14E' : '#B87503'} strokeWidth={1} strokeDasharray="5 3" />
            <polygon points={`${SCHEMATIC_X + 26},${y(axis.toAxis(currentMd) ?? 0) - 4} ${SCHEMATIC_X + 36},${y(axis.toAxis(currentMd) ?? 0)} ${SCHEMATIC_X + 26},${y(axis.toAxis(currentMd) ?? 0) + 4}`} fill={mode === 'dark' ? '#F2C14E' : '#B87503'} />
            <text x={SCHEMATIC_X + 40} y={y(axis.toAxis(currentMd) ?? 0) + 3} fontSize={8.5} fontWeight={700} fill={mode === 'dark' ? '#F2C14E' : '#B87503'}>
              {currentMd.toLocaleString()} m MD
            </text>
          </g>
        )}

        {/* Vertical section */}
        <text x={DRILL_RIGHT + DRILL_WIDTH / 2} y={TOP - 8} textAnchor="middle" fontSize={9} fill={muted} fontWeight={700}>
          VERTICAL SECTION
        </text>
        <line x1={DRILL_RIGHT} x2={DRILL_RIGHT + DRILL_WIDTH} y1={TOP + plotHeight} y2={TOP + plotHeight} stroke={line} strokeWidth={1} />
        <text x={DRILL_RIGHT + DRILL_WIDTH / 2} y={height - 6} textAnchor="middle" fontSize={8} fill={muted}>
          departure (m) · depth {axis.usable ? 'TVD' : 'MD'}
          {vsAzimuth === null ? '' : ` · VS azimuth ${vsAzimuth.toFixed(1)}°`}
        </text>
        {curve.length > 1 ? (
          <polyline points={curvePoints} fill="none" stroke={accent} strokeWidth={2.4} strokeLinejoin="round" strokeLinecap="round" />
        ) : curve.length === 1 ? (
          <circle cx={dx(curve[0].vsec_m)} cy={y(curve[0].tvd_m)} r={2.6} fill={accent} />
        ) : null}
        {curve.length > 1 && (
          <circle cx={dx(curve[curve.length - 1].vsec_m)} cy={y(curve[curve.length - 1].tvd_m)} r={3} fill={accent} />
        )}
        {!curve.length && (
          <text x={DRILL_RIGHT + DRILL_WIDTH / 2} y={TOP + plotHeight / 2} textAnchor="middle" fontSize={8.5} fill={muted}>
            {path.is_surveyed ? 'open the well path page for the trajectory' : 'no survey stations recorded'}
          </text>
        )}
      </Box>
      {!compact && (
        <Stack direction="row" gap={1} flexWrap="wrap" mt={1}>
          <Chip size="small" variant="outlined" label={`${path.sections.length} casing seat${path.sections.length === 1 ? '' : 's'}`} sx={{ height: 22, fontSize: 10.5 }} />
          <Chip size="small" variant="outlined" label={`${curve.length || summary.stations} survey station${(curve.length || summary.stations) === 1 ? '' : 's'}`} sx={{ height: 22, fontSize: 10.5 }} />
          {summary.max_inc_deg !== null && <Chip size="small" variant="outlined" label={`max inc ${summary.max_inc_deg}°`} sx={{ height: 22, fontSize: 10.5 }} />}
          {summary.departure_m !== null && summary.departure_m > 0 && (
            <Chip size="small" variant="outlined" label={`departure ${summary.departure_m.toLocaleString()} m`} sx={{ height: 22, fontSize: 10.5 }} />
          )}
          <Chip size="small" variant="outlined" label={summary.depth_basis || 'no report'} sx={{ height: 22, fontSize: 10.5 }} />
        </Stack>
      )}
      {path.assumption && (
        <Typography variant="caption" display="block" mt={1} color="text.secondary">
          {path.assumption}
        </Typography>
      )}
    </Box>
  )
}

export default WellDiagram
