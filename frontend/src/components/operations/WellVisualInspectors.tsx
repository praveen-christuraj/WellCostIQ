import { useState } from 'react'
import { Box, Checkbox, FormControlLabel, MenuItem, Stack, TextField, Typography } from '@mui/material'
import type { OpsWellPath } from '../../lib/operations'
import { fmtDepth, type DepthWindow } from '../../lib/wellPath'
import { VisualExpand } from '../ui/VisualExpand'
import { DoglegIntervals } from './DoglegIntervals'
import { WellDiagram } from './WellDiagram'
import { WellSourceContent, type WellMark } from './WellSourceDialog'
import { formatRange, parseNumber, parseRange, validRange, VisualDepthControls } from './VisualDepthControls'

const AUTO = { from: null, to: null }

export function DoglegExpand({ path, selectedMd, window }: { path: OpsWellPath; selectedMd: number | null; window: DepthWindow }) {
  return <VisualExpand visual={{ title: 'Dogleg severity by interval', subtitle: 'Select an interval for its calculation and original report values. Recorded severity is a separate mark.' }}>
    {() => <DoglegInspector path={path} initialMd={selectedMd} initialWindow={window} />}
  </VisualExpand>
}

function DoglegInspector({ path, initialMd, initialWindow }: { path: OpsWellPath; initialMd: number | null; initialWindow: DepthWindow }) {
  const [range, setRange] = useState(() => formatRange(initialWindow))
  const [severity, setSeverity] = useState('')
  const [labels, setLabels] = useState(false)
  const [selected, setSelected] = useState(initialMd)
  const max = parseNumber(severity)
  const validMax = severity === '' || (max !== null && max > 0)
  const parsed = parseRange(range)
  const window = validRange(parsed) ? parsed : AUTO
  const visible = path.intervals.filter(row => (window.from === null || row.to_md_m > window.from) && (window.to === null || row.from_md_m < window.to))
  const markVisible = selected !== null && visible.some(row => Math.abs(row.to_md_m - selected) <= 0.05)
  return <Stack spacing={2}>
    <VisualDepthControls range={range} onChange={setRange} reset={() => {
      setRange(formatRange(initialWindow)); setSeverity(''); setLabels(false); setSelected(initialMd)
    }} />
    <Stack direction="row" gap={1} alignItems="center" flexWrap="wrap" useFlexGap>
      <TextField size="small" type="number" label="Severity axis max (°/30 m)" value={severity} error={!validMax}
        helperText={validMax ? 'Blank uses the data extent.' : 'Enter a positive rate.'} onChange={event => setSeverity(event.target.value)} />
      <FormControlLabel control={<Checkbox checked={labels} onChange={event => setLabels(event.target.checked)} />} label="Severity labels" />
      <TextField select size="small" sx={{ minWidth: 215 }} label="Inspect interval (m MD)" value={markVisible ? selected : ''}
        onChange={event => setSelected(event.target.value ? Number(event.target.value) : null)}>
        <MenuItem value="">Select an interval</MenuItem>
        {visible.map(row => <MenuItem key={row.to_md_m} value={row.to_md_m}>{fmtDepth(row.from_md_m, 3)}–{fmtDepth(row.to_md_m, 3)}</MenuItem>)}
      </TextField>
    </Stack>
    <DoglegIntervals intervals={path.intervals} selectedMd={selected} onSelectMd={setSelected} height={430}
      window={window} severityMax={validMax ? max : null} showLabels={labels} />
    {markVisible && selected !== null && <WellSourceContent path={path} mark={{ kind: 'interval', toMd: selected }} />}
  </Stack>
}

export function WellDiagramExpand({ path, selectedMd, window = AUTO }: { path: OpsWellPath; selectedMd?: number | null; window?: DepthWindow }) {
  if (!path.is_surveyed && !path.sections.length && !path.planned_trajectory?.curve.length) return null
  return <VisualExpand visual={{ title: `Casing, hole and trajectory · ${path.well_code}`, subtitle: 'Construction is measured depth (MD); vertical section is true vertical depth (TVD). The two scales are independent.' }}>
    {() => <DiagramInspector path={path} initialMd={selectedMd} initialWindow={window} />}
  </VisualExpand>
}

function DiagramInspector({ path, initialMd, initialWindow }: { path: OpsWellPath; initialMd?: number | null; initialWindow: DepthWindow }) {
  const [md, setMd] = useState(() => formatRange(initialWindow))
  const [tvd, setTvd] = useState(() => formatRange(AUTO))
  const [labels, setLabels] = useState(true)
  const [selected, setSelected] = useState(initialMd == null ? '' : `station:${initialMd}`)
  const mdRange = parseRange(md)
  const tvdRange = parseRange(tvd)
  const [kind, rawDepth = ''] = selected.split(':')
  const depth = Number(rawDepth)
  const mark: WellMark | null = kind === 'hole' || kind === 'bit' ? { kind }
    : kind === 'seat' ? { kind, depth } : kind === 'station' ? { kind, md: depth } : null
  return <Stack spacing={1.5}>
    <VisualDepthControls range={md} onChange={setMd} reset={() => {
      setMd(formatRange(initialWindow)); setTvd(formatRange(AUTO)); setLabels(true); setSelected('')
    }} />
    <VisualDepthControls range={tvd} onChange={setTvd} axis="TVD" />
    <Stack direction="row" gap={1} alignItems="center" flexWrap="wrap" useFlexGap>
      <FormControlLabel control={<Checkbox checked={labels} onChange={event => setLabels(event.target.checked)} />} label="Marker annotations" />
      <TextField select size="small" sx={{ minWidth: 230 }} label="Inspect construction or survey mark" value={selected}
        onChange={event => setSelected(event.target.value)}>
        <MenuItem value="">Select a mark</MenuItem>
        {path.summary.current_md_m != null && <MenuItem value="hole">Hole marker · {fmtDepth(path.summary.current_md_m)} m MD</MenuItem>}
        {path.snapshot.bit_depth_m != null && <MenuItem value="bit">Bit / string · {fmtDepth(path.snapshot.bit_depth_m)} m MD</MenuItem>}
        {path.casing_seats.map(seat => <MenuItem key={`${seat.size_label}-${seat.depth_m}`} value={`seat:${seat.depth_m}`}>{seat.size_label} shoe · {fmtDepth(seat.depth_m)} m MD</MenuItem>)}
        {path.curve.map(point => <MenuItem key={point.md_m} value={`station:${point.md_m}`}>Actual station · {fmtDepth(point.md_m, 3)} m MD</MenuItem>)}
      </TextField>
    </Stack>
    <Box sx={{ overflowX: 'auto' }}><Box sx={{ minWidth: { xs: 450, sm: 0 }, maxWidth: 1050, mx: 'auto' }}>
      <WellDiagram path={path} height={600} selectedMd={kind === 'station' ? depth : null}
        mdWindow={validRange(mdRange) ? mdRange : AUTO} tvdWindow={validRange(tvdRange, true) ? tvdRange : AUTO} annotations={labels} />
    </Box></Box>
    {path.planned_trajectory?.curve.length ? <Typography variant="caption" color="text.secondary">{path.comparison_basis}</Typography> : null}
    {mark && <WellSourceContent path={path} mark={mark} />}
  </Stack>
}
