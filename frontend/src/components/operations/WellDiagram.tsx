import { useId, useMemo } from 'react'
import { Alert, Box, Chip, Stack, Typography } from '@mui/material'
import { useColorMode } from '../../context/ThemeContext'
import { brand, chartPalette, surface } from '../../designSystem'
import type { OpsWellPath, OpsWellPathSection, OpsWellVisual } from '../../lib/operations'
import { fmtDepth, usableTrajectory, type DepthWindow } from '../../lib/wellPath'

/**
 * Well diagram — drawn from the record, never from a template.
 *
 * Two drawings sit side by side, and they deliberately do **not** share one axis:
 *
 * * **Casing and hole** (left) is a construction drawing on a **measured-depth**
 *   axis. Every recorded casing seat is a string whose wall width follows the pipe
 *   size, ending in a shoe. Width helps identify equipment; it is not a clearance
 *   drawing.
 * * **Vertical section** (right) is the integrated trajectory on a **true vertical
 *   depth** axis. It is the shadow of the path on a vertical plane, not the shape
 *   of the hole.
 *
 * Sharing one axis between the two made a deviated well look shallower than its
 * own shoe, and made the depth caption disagree with whichever axis was drawn. The
 * two scales are therefore labelled separately and a seat is never converted into
 * a TVD here.
 *
 * Below the last survey station the section line stops. The remaining depth is
 * annotated as *unsurveyed* — never drawn as a continuation of the line. Below the
 * last known shoe the drawing says "casing coverage unknown" unless the record
 * supports open hole.
 *
 * The SVG is deterministic: same records, same drawing, in both themes and in the
 * PDF (the print path rasterises this component through the existing chart export).
 */

const WIDTH = 620
const TOP = 36
const BOTTOM = 98
/** Left drawing: measured depth. */
const MD_LABEL_X = 40
const CASING_CX = 152
const MAX_HALF_WIDTH = 24
/** Right drawing: true vertical depth. */
const TVD_LABEL_X = 356
const SECTION_LEFT = 372
const SECTION_RIGHT = 600

function niceDepth(maxDepth: number): number {
  if (!Number.isFinite(maxDepth) || maxDepth <= 0) return 100
  const target = maxDepth * 1.06
  const steps = [50, 100, 200, 250, 500, 1000, 1500, 2000, 2500, 5000, 10000]
  const step = steps.find((s) => target / s <= 6) ?? 20000
  return Math.ceil(target / step) * step
}

function niceAxisTicks(min: number, max: number, count: number): number[] {
  return Array.from({ length: count + 1 }, (_, i) => min + ((max - min) / count) * i)
}

export function WellDiagram({
  path,
  height = 430,
  compact = false,
  selectedMd = null,
  mdWindow,
  tvdWindow,
  annotations = true,
}: {
  /**
   * Either the full path (trajectory, seats, provenance) or the dashboard's
   * lighter `well_visual`. The lighter record draws the schematic and current
   * depth but has no curve, and the component says so rather than inventing one.
   */
  path: OpsWellPath | OpsWellVisual
  height?: number
  compact?: boolean
  /** A station chosen in another view, highlighted here on the MD construction. */
  selectedMd?: number | null
  mdWindow?: DepthWindow
  tvdWindow?: DepthWindow
  annotations?: boolean
}) {
  const { mode } = useColorMode()
  const sectionClip = `well-section-${useId()}`
  const colors = chartPalette(mode)
  const s = surface(mode)
  const summary = path.summary
  const plan = 'planned_trajectory' in path ? path.planned_trajectory : null
  const plannedCurve = plan?.curve ?? []
  const curve = 'curve' in path ? (plannedCurve.length ? usableTrajectory(path.curve) : path.curve) : []
  const allPoints = [...curve, ...plannedCurve]
  const snapshot = 'snapshot' in path ? path.snapshot : null
  const vsAzimuth = 'vertical_section_azimuth_deg' in path ? path.vertical_section_azimuth_deg : null
  const openHole = path.open_hole
  const currentMd = summary.current_md_m
  const bitDepth = snapshot?.bit_depth_m ?? summary.bit_depth_m
  const holeDepth = snapshot?.hole_depth_m ?? currentMd

  const plotHeight = height - TOP - (compact ? 48 : BOTTOM)

  const mdAutoMax = useMemo(() => {
    const values = [
      ...path.sections.map((row) => row.to_depth_m),
      holeDepth,
      bitDepth,
      openHole?.to_depth_m,
      curve.length ? curve[curve.length - 1].md_m : null,
      ...(selectedMd !== null ? [selectedMd] : []),
    ].filter((value): value is number => typeof value === 'number' && Number.isFinite(value))
    return niceDepth(Math.max(...values, 100))
  }, [path.sections, holeDepth, bitDepth, openHole, curve, selectedMd])

  const tvdAutoMax = useMemo(() => {
    const values = [
      ...curve.map((row) => row.tvd_m),
      ...plannedCurve.map((row) => row.tvd_m),
      // With no survey there is nothing to convert, so the reported TVD sets the
      // scale and the caption says the axis is not a trajectory.
      curve.length ? null : summary.current_tvd_m,
    ].filter((value): value is number => typeof value === 'number' && Number.isFinite(value))
    return niceDepth(Math.max(...values, 100))
  }, [curve, plannedCurve, summary.current_tvd_m])

  const mdMin = mdWindow?.from ?? 0
  const mdMax = Math.max(mdWindow?.to ?? mdAutoMax, mdMin + 0.001)
  const tvdMin = tvdWindow?.from ?? Math.min(0, ...allPoints.map(row => row.tvd_m))
  const tvdMax = Math.max(tvdWindow?.to ?? tvdAutoMax, tvdMin + 0.001)
  const inMd = (depth: number) => depth >= mdMin && depth <= mdMax
  const inTvd = (depth: number) => depth >= tvdMin && depth <= tvdMax
  const yMd = (depth: number) => TOP + ((Math.max(mdMin, Math.min(depth, mdMax)) - mdMin) / (mdMax - mdMin)) * plotHeight
  const yTvd = (depth: number) => TOP + ((depth - tvdMin) / (tvdMax - tvdMin)) * plotHeight
  const visibleSections = path.sections.filter(row => row.from_depth_m < mdMax && row.to_depth_m >= mdMin)
  const openHoleVisible = openHole && openHole.from_depth_m < mdMax && openHole.to_depth_m > mdMin
  const maxDeparture = Math.max(...allPoints.map(row => Math.abs(row.vsec_m)), 50) * 1.08
  const hasNegativeDeparture = allPoints.some(row => row.vsec_m < 0)
  const sectionCentre = hasNegativeDeparture ? (SECTION_LEFT + SECTION_RIGHT) / 2 : SECTION_LEFT + 14
  const xSection = (vsec: number) => sectionCentre + (vsec / maxDeparture) * ((SECTION_RIGHT - SECTION_LEFT) / 2 - 14)
  const points = (stations: typeof curve) => stations.map(row => `${xSection(row.vsec_m).toFixed(2)},${yTvd(row.tvd_m).toFixed(2)}`).join(' ')
  const sectionWidth = (row: OpsWellPathSection) => Math.max(6, Math.min(MAX_HALF_WIDTH * 2, 6 + (row.casing_size_in / 30) * 56))
  const mdTicks = niceAxisTicks(mdMin, mdMax, compact ? 4 : 6)
  const tvdTicks = niceAxisTicks(tvdMin, tvdMax, compact ? 4 : 6)
  const tickValue = (tick: number, span: number) => tick.toLocaleString(undefined, { maximumFractionDigits: span < 10 ? 3 : 0 })

  if (!path.is_surveyed && !path.sections.length && !plannedCurve.length) {
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
  const brass = mode === 'dark' ? '#F2C14E' : '#B87503'
  const deepest = path.sections.length ? path.sections[path.sections.length - 1] : null
  const lastStation = curve.length ? curve[curve.length - 1] : null
  const unsurveyedToHole = Boolean(lastStation && holeDepth !== null && holeDepth > lastStation.md_m + 0.5)
  const selectedStation = selectedMd === null
    ? null
    : curve.find((row) => Math.abs(row.md_m - selectedMd) <= 0.05) ?? null
  const xLeftRuleStart = 64
  const xLeftRuleEnd = CASING_CX + 86

  return (
    <Box>
      {/* ``data-chart-precision`` marks the drawing as a capturable chart: the
          PDF export finds it inside an exportable figure and rasterises this
          SVG exactly as rendered, in both themes. It is inert in the browser. */}
      <Box
        component="svg"
        role="img"
        aria-label={`Well diagram for ${path.well_code}: well construction on measured depth, vertical section on true vertical depth`}
        data-chart-precision="1"
        width={WIDTH}
        height={height}
        viewBox={`0 0 ${WIDTH} ${height}`}
        preserveAspectRatio="xMidYMid meet"
        sx={{ display: 'block', width: '100%', height: 'auto', maxHeight: height, ...(!annotations && { '& .well-diagram-annotation': { display: 'none' } }) }}
      >
        <defs><clipPath id={sectionClip}><rect x={SECTION_LEFT} y={TOP} width={SECTION_RIGHT - SECTION_LEFT} height={plotHeight} /></clipPath></defs>
        {/* Headings name the axis each drawing uses */}
        <text x={MD_LABEL_X} y={12} fontSize={8.5} fontWeight={700} fill={muted}>
          MD
        </text>
        <text x={CASING_CX} y={12} textAnchor="middle" fontSize={9} fontWeight={700} fill={muted}>
          WELL CONSTRUCTION
        </text>
        <text x={CASING_CX} y={23} textAnchor="middle" fontSize={8} fill={muted}>
          measured depth
        </text>
        <text x={(SECTION_LEFT + SECTION_RIGHT) / 2} y={12} textAnchor="middle" fontSize={9} fontWeight={700} fill={muted}>
          VERTICAL SECTION
        </text>
        <text x={(SECTION_LEFT + SECTION_RIGHT) / 2} y={23} textAnchor="middle" fontSize={8} fill={muted}>
          {`true vertical depth${vsAzimuth === null ? '' : ` · facing ${vsAzimuth.toFixed(1)}°`}`}
        </text>

        {/* Left: measured-depth grid */}
        {mdTicks.map((tick) => (
          <g key={`md-${tick}`}>
            <line
              x1={MD_LABEL_X}
              x2={CASING_CX + 88}
              y1={yMd(tick)}
              y2={yMd(tick)}
              stroke={line}
              strokeWidth={0.6}
              strokeDasharray={tick === 0 ? '0' : '2 4'}
            />
            <text x={MD_LABEL_X - 5} y={yMd(tick) + 3} textAnchor="end" fontSize={8.5} fill={muted}>
              {tickValue(tick, mdMax - mdMin)}
            </text>
          </g>
        ))}
        <text x={MD_LABEL_X} y={TOP + plotHeight + 14} fontSize={8.5} fontWeight={700} fill={muted}>
          m
        </text>

        {/* Ground line at surface: a short hatched rule across the construction */}
        {inMd(0) && <g opacity={0.75}>
          <line x1={CASING_CX - 44} x2={CASING_CX + 44} y1={yMd(0)} y2={yMd(0)} stroke={muted} strokeWidth={1.4} />
          {[-36, -24, -12, 0, 12, 24, 36].map((dx) => (
            <line key={dx} x1={CASING_CX + dx - 4} x2={CASING_CX + dx + 2} y1={yMd(0)} y2={yMd(0) + 6} stroke={muted} strokeWidth={0.8} />
          ))}
          <text x={CASING_CX - 50} y={yMd(0) + 3} textAnchor="end" fontSize={8} fill={muted}>surface</text>
        </g>}

        {/* Casing spine: the construction is drawn about a central axis */}
        <line x1={CASING_CX} x2={CASING_CX} y1={TOP} y2={TOP + plotHeight} stroke={muted} strokeWidth={1} opacity={0.6} />
        {path.sections.length === 0 && (
          <text x={CASING_CX} y={TOP + plotHeight / 2} textAnchor="middle" fontSize={8.5} fill={muted}>
            no casing seat recorded
          </text>
        )}
        {visibleSections.map((row) => {
          const width = sectionWidth(row)
          const top = yMd(row.from_depth_m)
          const bottom = yMd(row.to_depth_m)
          const barHeight = Math.max(1.5, bottom - top)
          return (
            <g key={`${row.casing_label}-${row.from_depth_m}`}>
              <title>{`${row.casing_label} casing: ${row.from_depth_m.toLocaleString()} m MD → ${row.to_depth_m.toLocaleString()} m MD (${row.source}); shoe at ${row.to_depth_m.toLocaleString()} m MD`}</title>
              <rect x={CASING_CX - width / 2} y={top} width={width} height={barHeight} fill={accent} fillOpacity={0.14} stroke={accent} strokeWidth={1.6} />
              <rect x={CASING_CX - width / 2 + 1.4} y={top} width={Math.max(1.5, width * 0.22)} height={barHeight} fill={accent} opacity={0.22} />
              <rect x={CASING_CX + width / 2 - 1.4 - Math.max(1.5, width * 0.22)} y={top} width={Math.max(1.5, width * 0.22)} height={barHeight} fill={accent} opacity={0.22} />
              {/* The shoe, drawn as the standard angled wedge */}
              {inMd(row.to_depth_m) && <path d={`M ${CASING_CX - width / 2} ${bottom} L ${CASING_CX} ${bottom + 5} L ${CASING_CX + width / 2} ${bottom}`} fill="none" stroke={accent} strokeWidth={1.6} />}
              {!compact && (
                <text className="well-diagram-annotation" x={CASING_CX + Math.max(28, width / 2) + 6} y={top + 9} fontSize={8.5} fill={ink}>
                  {row.casing_label} · shoe {row.to_depth_m.toLocaleString()} m
                </text>
              )}
            </g>
          )
        })}

        {/* Below the last shoe: open hole only when the record supports it.
            Drawn as two thin parallel walls about the centreline — never a
            casing-coloured line, so uncased hole cannot read as pipe. */}
        {openHoleVisible ? (
          <g>
            <title>{`Open hole (uncased) ${openHole.from_depth_m} → ${openHole.to_depth_m} m MD`}</title>
            <line x1={CASING_CX - 11} x2={CASING_CX - 11} y1={yMd(openHole.from_depth_m)} y2={yMd(openHole.to_depth_m)} stroke={muted} strokeWidth={1.3} />
            <line x1={CASING_CX + 11} x2={CASING_CX + 11} y1={yMd(openHole.from_depth_m)} y2={yMd(openHole.to_depth_m)} stroke={muted} strokeWidth={1.3} />
            {/* ragged wall ends at the current hole bottom */}
            {inMd(openHole.to_depth_m) && <line x1={CASING_CX - 11} x2={CASING_CX + 11} y1={yMd(openHole.to_depth_m)} y2={yMd(openHole.to_depth_m)} stroke={muted} strokeWidth={1} strokeDasharray="2 2" />}
            <text x={CASING_CX + 30} y={(yMd(openHole.from_depth_m) + yMd(openHole.to_depth_m)) / 2 + 3} fontSize={8} fill={muted}>
              open hole (uncased)
            </text>
          </g>
        ) : !openHole && deepest && inMd(deepest.to_depth_m) && holeDepth !== null && holeDepth <= deepest.to_depth_m + 0.5 ? (
          <text x={CASING_CX + 30} y={Math.min(yMd(deepest.to_depth_m) + 16, TOP + plotHeight)} fontSize={8} fill={muted}>
            coverage unknown below shoe
          </text>
        ) : !openHole && deepest && inMd(deepest.to_depth_m) && !compact ? (
          <text x={CASING_CX + 30} y={Math.min(yMd(deepest.to_depth_m) + 16, TOP + plotHeight)} fontSize={8} fill={muted}>
            below the last shoe: coverage unknown
          </text>
        ) : null}

        {/* Hole depth: the selected report's closing MD. A rule, not pipe. */}
        {holeDepth !== null && inMd(holeDepth) && (
          <g>
            <title>{`Hole depth ${holeDepth.toLocaleString()} m MD (${snapshot?.basis || summary.depth_basis || 'report'})`}</title>
            <line
              x1={xLeftRuleStart}
              x2={xLeftRuleEnd}
              y1={yMd(holeDepth)}
              y2={yMd(holeDepth)}
              stroke={brass}
              strokeWidth={1.1}
              strokeDasharray="6 3"
            />
            <g className="well-diagram-annotation"><Halo
              x={xLeftRuleStart}
              y={yMd(holeDepth) - 14}
              width={labelWidth(holeLabel(holeDepth, snapshot?.report_date ?? null), 8.5)}
              height={12}
              fill={s.paper}
            />
            <text x={xLeftRuleStart} y={yMd(holeDepth) - 4} fontSize={8.5} fontWeight={700} fill={brass}>
              {holeLabel(holeDepth, snapshot?.report_date ?? null)}
            </text></g>
          </g>
        )}

        {/* Bit / string: a distinctly labelled triangle at the reported depth */}
        {bitDepth != null && inMd(bitDepth) && (
          <g>
            <title>{`${snapshot?.label || 'Reported bit / string depth'} ${bitDepth.toLocaleString()} m MD${snapshot?.off_bottom_m !== null && snapshot?.off_bottom_m !== undefined ? `; ${snapshot.off_bottom_m.toLocaleString()} m off bottom` : ''}`}</title>
            <line x1={CASING_CX - 26} x2={CASING_CX - 18} y1={yMd(bitDepth)} y2={yMd(bitDepth)} stroke={brass} strokeWidth={1} />
            <polygon
              points={`${CASING_CX - 26},${yMd(bitDepth) - 5} ${CASING_CX - 26},${yMd(bitDepth) + 5} ${CASING_CX - 18},${yMd(bitDepth)}`}
              fill={brass}
            />
            <g className="well-diagram-annotation"><Halo
              x={CASING_CX - 34 - labelWidth(`Bit ${bitDepth.toLocaleString()} m`, 8.5)}
              y={yMd(bitDepth) - 8}
              width={labelWidth(`Bit ${bitDepth.toLocaleString()} m`, 8.5)}
              height={12}
              fill={s.paper}
            />
            <text x={CASING_CX - 30} y={yMd(bitDepth) + 3} textAnchor="end" fontSize={8.5} fontWeight={700} fill={brass}>
              {`Bit ${bitDepth.toLocaleString()} m`}
            </text></g>
          </g>
        )}

        {/* Selected survey station, on the measured-depth construction */}
        {selectedStation && inMd(selectedStation.md_m) && (
          <g>
            <line x1={CASING_CX - 4} x2={CASING_CX + 4} y1={yMd(selectedStation.md_m)} y2={yMd(selectedStation.md_m)} stroke={brass} strokeWidth={2.2} />
            <circle cx={CASING_CX + 10} cy={yMd(selectedStation.md_m)} r={3.4} fill="none" stroke={brass} strokeWidth={1.6} />
            <text x={CASING_CX + 18} y={yMd(selectedStation.md_m) + 3} fontSize={8} fill={brass}>
              {`station ${selectedStation.md_m.toLocaleString()} m`}
            </text>
          </g>
        )}
        {!compact && lastStation && inMd(lastStation.md_m) && (
          <text x={CASING_CX - 8} y={yMd(lastStation.md_m) + 3} textAnchor="end" fontSize={8} fill={muted}>
            {`last station ${lastStation.md_m.toLocaleString()} m`}
          </text>
        )}

        {/* Right: true vertical depth grid */}
        {tvdTicks.map((tick) => (
          <g key={`tvd-${tick}`}>
            <line
              x1={TVD_LABEL_X}
              x2={SECTION_RIGHT}
              y1={yTvd(tick)}
              y2={yTvd(tick)}
              stroke={line}
              strokeWidth={0.6}
              strokeDasharray={tick === 0 ? '0' : '2 4'}
            />
            <text x={TVD_LABEL_X - 5} y={yTvd(tick) + 3} textAnchor="end" fontSize={8.5} fill={muted}>
              {tickValue(tick, tvdMax - tvdMin)}
            </text>
          </g>
        ))}
        <text x={TVD_LABEL_X - 5} y={TOP - 6} textAnchor="end" fontSize={8.5} fontWeight={700} fill={muted}>
          TVD (m)
        </text>

        {inTvd(0) && <line x1={SECTION_LEFT} x2={SECTION_RIGHT} y1={yTvd(0)} y2={yTvd(0)} stroke={muted} strokeWidth={1} />}

        <g clipPath={`url(#${sectionClip})`}>

        {curve.length > 1 ? (
          <g>
            <title>{`Integrated trajectory from ${curve[0].md_m.toLocaleString()} m to ${curve[curve.length - 1].md_m.toLocaleString()} m MD`}</title>
            <polyline points={points(curve)} fill="none" stroke={accent} strokeWidth={2.6} strokeLinejoin="round" strokeLinecap="round" />
          </g>
        ) : curve.length === 1 ? (
          <circle cx={xSection(curve[0].vsec_m)} cy={yTvd(curve[0].tvd_m)} r={2.8} fill={accent} />
        ) : null}

        {lastStation && (
          <g>
            <circle cx={xSection(lastStation.vsec_m)} cy={yTvd(lastStation.tvd_m)} r={3.4} fill={accent} />
            {!compact && (
              <text x={xSection(lastStation.vsec_m) + 7} y={yTvd(lastStation.tvd_m) - 4} fontSize={8} fill={muted}>
                last station
              </text>
            )}
          </g>
        )}

        {selectedStation && (
          <g>
            <circle cx={xSection(selectedStation.vsec_m)} cy={yTvd(selectedStation.tvd_m)} r={4.6} fill="none" stroke={brass} strokeWidth={1.8} />
          </g>
        )}

        {plannedCurve.length > 1 ? <polyline points={points(plannedCurve)} fill="none" stroke={colors.planned} strokeWidth={2.6} strokeDasharray="5 3">
          <title>{`Planned survey · v${plan?.version_no} (${plan?.status})`}</title>
        </polyline> : plannedCurve.length === 1 ? <circle cx={xSection(plannedCurve[0].vsec_m)} cy={yTvd(plannedCurve[0].tvd_m)}
          r={3.4} fill="none" stroke={colors.planned} strokeWidth={2} /> : null}
        </g>
        {plannedCurve.length > 0 && <g fontSize={8} fill={muted} transform={`translate(${SECTION_LEFT + 8}, ${TOP - 7})`}>
          <line x1={0} x2={16} y1={0} y2={0} stroke={colors.planned} strokeWidth={1.8} strokeDasharray="4 2" />
          <text x={20} y={3}>Planned v{plan?.version_no}</text>
          {curve.length > 0 && <><line x1={93} x2={109} y1={0} y2={0} stroke={accent} strokeWidth={1.8} /><text x={113} y={3}>Actual</text></>}
        </g>}

        {!curve.length && !plannedCurve.length && (
          <text x={(SECTION_LEFT + SECTION_RIGHT) / 2} y={TOP + plotHeight / 2} textAnchor="middle" fontSize={8.5} fill={muted}>
            {path.is_surveyed ? 'open the well path page for the trajectory' : 'no survey stations recorded'}
          </text>
        )}

        {/* Unsurveyed depth is an annotation, never a continuation of the line */}
        {unsurveyedToHole && lastStation && holeDepth !== null && (
          <g className="well-diagram-annotation">
            <text x={(SECTION_LEFT + SECTION_RIGHT) / 2} y={TOP + plotHeight + 30} textAnchor="middle" fontSize={8} fill={brass}>
              {`unsurveyed below ${fmtDepth(lastStation.md_m, 2)} m MD — no TVD for the remaining ${fmtDepth(holeDepth - lastStation.md_m, 2)} m`}
            </text>
          </g>
        )}

        {/* Axis captions say which scale each drawing uses */}
        <text x={CASING_CX} y={TOP + plotHeight + 30} textAnchor="middle" fontSize={8} fill={muted}>
          measured depth (m) ↓
        </text>
        <text x={(SECTION_LEFT + SECTION_RIGHT) / 2} y={TOP + plotHeight + (unsurveyedToHole ? 42 : 30)} textAnchor="middle" fontSize={8} fill={muted}>
          projected distance along section (m) · TVD (m) ↓
        </text>

        {/* Symbol key */}
        {!compact && (
          <g fontSize={8} fill={muted}>
            <g transform={`translate(${MD_LABEL_X}, ${height - 44})`}>
              <rect x={0} y={-6} width={9} height={9} fill={accent} fillOpacity={0.14} stroke={accent} strokeWidth={1.2} />
              <text x={13} y={2}>casing (cased hole)</text>
              <path d="M 132 -6 L 137 0 L 142 -6" fill="none" stroke={accent} strokeWidth={1.2} />
              <text x={147} y={2}>shoe</text>
              <line x1={186} x2={186} y1={-6} y2={3} stroke={muted} strokeWidth={1.1} />
              <line x1={192} x2={192} y1={-6} y2={3} stroke={muted} strokeWidth={1.1} />
              <text x={198} y={2}>open hole (uncased)</text>
            </g>
            <g transform={`translate(${MD_LABEL_X}, ${height - 28})`}>
              <line x1={0} x2={14} y1={-3} y2={-3} stroke={brass} strokeDasharray="4 2" strokeWidth={1.1} />
              <text x={18} y={0}>hole depth (report MD)</text>
              <polygon points={`66,-7 66,1 73,-3`} fill={brass} />
              <text x={78} y={0}>bit / string depth</text>
              <circle cx={166} cy={-3} r={3} fill={accent} />
              <text x={174} y={0}>survey station</text>
              <text x={244} y={0}>shapes carry meaning in both themes</text>
            </g>
          </g>
        )}
      </Box>
      {!compact && (
        <Stack direction="row" gap={1} flexWrap="wrap" mt={1}>
          <Chip size="small" variant="outlined" label={`${path.sections.length} casing seat${path.sections.length === 1 ? '' : 's'}`} sx={{ height: 22, fontSize: 10.5 }} />
          <Chip size="small" variant="outlined" label={`${curve.length || summary.stations} survey station${(curve.length || summary.stations) === 1 ? '' : 's'}`} sx={{ height: 22, fontSize: 10.5 }} />
          {summary.max_inc_deg !== null && <Chip size="small" variant="outlined" label={`max inc ${summary.max_inc_deg}°`} sx={{ height: 22, fontSize: 10.5 }} />}
          {summary.max_dls_deg_per_30m !== null && (
            <Chip size="small" variant="outlined" label={`max DLS ${summary.max_dls_deg_per_30m} °/30 m`} sx={{ height: 22, fontSize: 10.5 }} />
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

/** A label painted over the drawing keeps its own surface behind it. */
function Halo({ x, y, width, height, fill }: { x: number; y: number; width: number; height: number; fill: string }) {
  return <rect x={x} y={y} width={width} height={height} fill={fill} opacity={0.9} rx={2} />
}

/** Rough advance width at a small type size; the label backs itself, so close is enough. */
function labelWidth(text: string, fontSize: number): number {
  return text.length * fontSize * 0.56 + 6
}

function holeLabel(depth: number, reportDate: string | null): string {
  const value = depth.toLocaleString(undefined, { minimumFractionDigits: 2, maximumFractionDigits: 2 })
  return `Hole ${value} m${reportDate ? ` · ${reportDate}` : ''}`
}

export default WellDiagram
