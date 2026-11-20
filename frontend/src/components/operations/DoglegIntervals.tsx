import { useMemo, useState } from 'react'
import { Box, Stack, Typography } from '@mui/material'
import { useColorMode } from '../../context/ThemeContext'
import { brand, surface } from '../../designSystem'
import type { OpsWellPathInterval } from '../../lib/operations'
import { dlsAxisMax, fmtDepth, fmtDls } from '../../lib/wellPath'

/**
 * Dogleg severity by interval.
 *
 * Severity answers "how much did the direction change per length drilled?", so
 * every rectangle spans the measured-depth **interval** between two stations —
 * not one calendar day and not one station. Its height is the average directional
 * change normalised to 30 m. A peak identifies an interval worth inspecting; it
 * is not proof of unsafe drilling.
 *
 * Drawn as deterministic SVG (like the well diagram) so it rasterises identically
 * in the PDF export, keeps its meaning in both themes, and can be clicked or
 * tabbed to select the interval's deeper station without a chart library.
 */
const WIDTH = 900
const LEFT = 62
const RIGHT = 20
const TOP = 22
const BOTTOM = 52

export function DoglegIntervals({
  intervals,
  selectedMd,
  onSelectMd,
  height = 280,
}: {
  intervals: OpsWellPathInterval[]
  selectedMd: number | null
  onSelectMd: (md: number) => void
  height?: number
}) {
  const { mode } = useColorMode()
  const s = surface(mode)
  const [hover, setHover] = useState<number | null>(null)
  const accent = mode === 'dark' ? brand[300] : brand[700]
  const brass = mode === 'dark' ? '#F2C14E' : '#A9782B'

  const plot = useMemo(() => {
    if (!intervals.length) return null
    const from = Math.min(...intervals.map((row) => row.from_md_m))
    const to = Math.max(...intervals.map((row) => row.to_md_m))
    const span = Math.max(to - from, 1)
    const maxDls = dlsAxisMax(intervals)
    const plotHeight = height - TOP - BOTTOM
    const plotWidth = WIDTH - LEFT - RIGHT
    const x = (md: number) => LEFT + ((md - from) / span) * plotWidth
    const y = (dls: number) => TOP + plotHeight - (Math.min(dls, maxDls) / maxDls) * plotHeight
    const peak = intervals.reduce<OpsWellPathInterval | null>((best, row) => {
      if (row.dls_deg_per_30m === null) return best
      if (!best || (best.dls_deg_per_30m ?? 0) < row.dls_deg_per_30m) return row
      return best
    }, null)
    return { from, to, span, maxDls, plotHeight, plotWidth, x, y, peak }
  }, [intervals, height])

  if (!plot) {
    return (
      <Typography sx={{ fontSize: 12.5, color: 'text.secondary' }}>
        One interval needs two accepted stations. Nothing is recorded above the first station, so a single station
        has no severity — that is not the same as zero.
      </Typography>
    )
  }

  const { from, to, maxDls, plotHeight, x, y, peak } = plot
  const ticks = [0, 0.25, 0.5, 0.75, 1].map((fraction) => fraction * maxDls)
  const mdTicks = [0, 0.25, 0.5, 0.75, 1].map((fraction) => from + fraction * (to - from))
  const selectedInterval = intervals.find((row) => Math.abs(row.to_md_m - (selectedMd ?? -1)) <= 0.05) ?? null

  return (
    <Box>
      <Box
        component="svg"
        role="img"
        aria-label="Dogleg severity by survey interval"
        data-chart-precision="1"
        width={WIDTH}
        height={height}
        viewBox={`0 0 ${WIDTH} ${height}`}
        preserveAspectRatio="xMidYMid meet"
        sx={{ display: 'block', width: '100%', height: 'auto', maxHeight: height }}
      >
        {/* Severity grid and labels */}
        {ticks.map((tick) => (
          <g key={`dls-${tick}`}>
            <line x1={LEFT} x2={WIDTH - RIGHT} y1={y(tick)} y2={y(tick)} stroke={s.divider} strokeWidth={0.7} strokeDasharray={tick === 0 ? '0' : '2 4'} />
            <text x={LEFT - 8} y={y(tick) + 3} textAnchor="end" fontSize={9} fill={s.textMuted}>
              {tick.toFixed(tick < 3 ? 2 : 1)}
            </text>
          </g>
        ))}
        <text x={LEFT - 8} y={TOP - 8} textAnchor="end" fontSize={9} fontWeight={700} fill={s.textMuted}>
          °/30 m
        </text>

        {/* One rectangle per interval, spanning that interval's measured depth */}
        {intervals.map((row, index) => {
          const left = x(row.from_md_m)
          const right = x(row.to_md_m)
          const width = Math.max(1.5, right - left)
          const top = row.dls_deg_per_30m === null ? y(0) - 3 : y(row.dls_deg_per_30m)
          const isSelected = selectedInterval === row
          const isHover = hover === index
          const isPeak = peak === row && row.dls_deg_per_30m !== null
          const label = row.valid
            ? `Interval ${fmtDepth(row.from_md_m, 2)} → ${fmtDepth(row.to_md_m, 2)} m MD · ΔMD ${fmtDepth(row.delta_md_m, 2)} m · DLS ${fmtDls(row.dls_deg_per_30m)}${
                row.recorded_dls_deg_per_30m !== null ? ` · recorded ${fmtDls(row.recorded_dls_deg_per_30m)}` : ''
              }${row.issue ? ` · ${row.issue}` : ''}`
            : `Interval ${fmtDepth(row.from_md_m, 2)} → ${fmtDepth(row.to_md_m, 2)} m MD · ${row.issue}`
          return (
            <g
              key={`${row.from_md_m}-${row.to_md_m}`}
              role="button"
              tabIndex={0}
              aria-label={label}
              style={{ cursor: 'pointer', outline: 'none' }}
              onMouseEnter={() => setHover(index)}
              onMouseLeave={() => setHover((current) => (current === index ? null : current))}
              onFocus={() => setHover(index)}
              onBlur={() => setHover((current) => (current === index ? null : current))}
              onClick={() => onSelectMd(row.to_md_m)}
              onKeyDown={(event) => {
                if (event.key === 'Enter' || event.key === ' ') {
                  event.preventDefault()
                  onSelectMd(row.to_md_m)
                }
              }}
            >
              <title>{label}</title>
              {row.dls_deg_per_30m !== null ? (
                <rect
                  x={left}
                  y={top}
                  width={width}
                  height={Math.max(1.5, y(0) - top)}
                  fill={isSelected ? brass : accent}
                  opacity={isSelected ? 0.95 : isHover ? 0.82 : 0.55}
                  stroke={isSelected || isHover ? (isSelected ? brass : accent) : 'none'}
                  strokeWidth={isSelected ? 1.6 : 1}
                />
              ) : (
                <g>
                  <rect
                    x={left}
                    y={y(0) - 6}
                    width={width}
                    height={6}
                    fill="none"
                    stroke={s.dividerStrong}
                    strokeWidth={1}
                    strokeDasharray="2 2"
                  />
                  <text x={left + width / 2} y={y(0) + 11} textAnchor="middle" fontSize={8.5} fill={s.textDisabled}>
                    no interval
                  </text>
                </g>
              )}
              {/* The printed or typed severity, kept as a separate mark */}
              {row.recorded_dls_deg_per_30m !== null && (
                <line
                  x1={left + width * 0.3}
                  x2={right - width * 0.3}
                  y1={y(row.recorded_dls_deg_per_30m)}
                  y2={y(row.recorded_dls_deg_per_30m)}
                  stroke={brass}
                  strokeWidth={1.6}
                  strokeLinecap="round"
                  opacity={0.95}
                />
              )}
              {isPeak && !isSelected && (
                <text x={left + width / 2} y={top - 5} textAnchor="middle" fontSize={9} fontWeight={700} fill={s.text}>
                  {(row.dls_deg_per_30m ?? 0).toFixed(2)}
                </text>
              )}
            </g>
          )
        })}

        {/* Measured-depth axis */}
        <line x1={LEFT} x2={WIDTH - RIGHT} y1={TOP + plotHeight} y2={TOP + plotHeight} stroke={s.dividerStrong} strokeWidth={1} />
        {mdTicks.map((md, index) => (
          <text
            key={`md-${md}`}
            x={x(md)}
            y={TOP + plotHeight + 15}
            textAnchor={index === 0 ? 'start' : index === mdTicks.length - 1 ? 'end' : 'middle'}
            fontSize={9}
            fill={s.textMuted}
          >
            {fmtDepth(md, 0)}
          </text>
        ))}
        <text x={(LEFT + WIDTH - RIGHT) / 2} y={height - 16} textAnchor="middle" fontSize={9.5} fill={s.textMuted} fontWeight={700}>
          Measured depth (m) — each rectangle spans its own interval
        </text>

        {/* Legend */}
        <g transform={`translate(${LEFT}, ${height - 4})`}>
          <rect x={0} y={-8} width={10} height={8} fill={accent} opacity={0.55} />
          <text x={14} y={-1} fontSize={9} fill={s.textMuted}>calculated</text>
          <line x1={78} x2={94} y1={-4} y2={-4} stroke={brass} strokeWidth={1.6} strokeLinecap="round" />
          <text x={99} y={-1} fontSize={9} fill={s.textMuted}>recorded</text>
          <rect x={164} y={-8} width={10} height={8} fill="none" stroke={s.dividerStrong} strokeDasharray="2 2" />
          <text x={179} y={-1} fontSize={9} fill={s.textMuted}>no usable interval</text>
        </g>
      </Box>

      {selectedInterval && (
        <Stack direction={{ xs: 'column', sm: 'row' }} gap={1.5} mt={1} flexWrap="wrap" useFlexGap>
          <Typography sx={{ fontSize: 11.5, fontWeight: 700 }}>
            Interval {fmtDepth(selectedInterval.from_md_m, 2)} → {fmtDepth(selectedInterval.to_md_m, 2)} m MD
          </Typography>
          <Typography sx={{ fontSize: 11.5, color: 'text.secondary' }}>
            ΔMD {fmtDepth(selectedInterval.delta_md_m, 2)} m · β {selectedInterval.beta_deg === null ? '—' : `${selectedInterval.beta_deg.toFixed(5)}°`} ·
            calculated {fmtDls(selectedInterval.dls_deg_per_30m)}
            {selectedInterval.recorded_dls_deg_per_30m !== null
              ? ` · recorded ${fmtDls(selectedInterval.recorded_dls_deg_per_30m)}`
              : ''}
            {selectedInterval.dls_difference_deg_per_30m !== null
              ? ` · difference ${selectedInterval.dls_difference_deg_per_30m >= 0 ? '+' : ''}${selectedInterval.dls_difference_deg_per_30m.toFixed(4)}`
              : ''}
          </Typography>
          {selectedInterval.issue && (
            <Typography sx={{ fontSize: 11.5, color: 'warning.main' }}>{selectedInterval.issue}</Typography>
          )}
        </Stack>
      )}
    </Box>
  )
}

export default DoglegIntervals
