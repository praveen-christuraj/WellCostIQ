import { useState, type ReactNode } from 'react'
import { Box, Button, Checkbox, FormControlLabel, MenuItem, Stack, TextField, Typography } from '@mui/material'
import type { EChartsReactProps } from 'echarts-for-react'

type Option = NonNullable<EChartsReactProps['option']>
type Entry = Record<string, unknown>
type Bounds = { min?: string; max?: string; step?: string }
type Settings = Record<string, Bounds>
const asList = (value: unknown): Entry[] => !value ? [] : (Array.isArray(value) ? value : [value]) as Entry[]
const number = (text: string | undefined) => text?.trim() ? Number(text) : undefined
const category = (entry: unknown) => String((entry && typeof entry === 'object' && 'value' in entry) ? entry.value : entry)

export function ChartInspector({ option, renderChart }: {
  option: Option
  renderChart: (option: Option, resetKey: number) => ReactNode
}) {
  const [settings, setSettings] = useState<Settings>({})
  const [labels, setLabels] = useState<boolean | null>(null)
  const [zoom, setZoom] = useState(false)
  const [resetKey, setResetKey] = useState(0)
  const normalized = option as Entry
  const axes = (['xAxis', 'yAxis'] as const).flatMap(key => asList(normalized[key]).map((axis, index) => {
    const direction = key === 'xAxis' ? 'X' : 'Y'
    const name = typeof axis.name === 'string' && axis.name ? axis.name : ''
    const categories = Array.isArray(axis.data) ? axis.data.map(category) : []
    return { axis, key, index, id: `${key}-${index}`, type: axis.type ?? (categories.length ? 'category' : 'value'),
      label: `${direction}${index ? index + 1 : ''}${name ? ` · ${name}` : ''}`, categories }
  }))
  const series = asList(normalized.series)
  const axisEdits = new Map<string, Entry>()
  const rangeZoom: Entry[] = []
  const invalid = new Set<string>()
  for (const { id, type, axis, key, index, categories } of axes) {
    const bounds = settings[id] ?? {}
    let min = number(bounds.min), max = number(bounds.max)
    const step = number(bounds.step)
    if (type === 'time') {
      min = bounds.min ? Date.parse(`${bounds.min}T00:00:00Z`) : undefined
      max = bounds.max ? Date.parse(`${bounds.max}T23:59:59.999Z`) : undefined
    }
    const explicitMin = typeof axis.min === 'number' ? axis.min : undefined
    const explicitMax = typeof axis.max === 'number' ? axis.max : undefined
    const compareMin = min ?? (type === 'category' ? 0 : explicitMin)
    const compareMax = max ?? (type === 'category' ? categories.length - 1 : explicitMax)
    if ([min, max, step].some(val => val !== undefined && !Number.isFinite(val)) ||
        (compareMin !== undefined && compareMax !== undefined && (type === 'category' ? compareMin > compareMax : compareMin >= compareMax)) ||
        (type === 'log' && (min !== undefined && min <= 0 || max !== undefined && max <= 0)) ||
        (step !== undefined && (step <= 0 || (compareMin !== undefined && compareMax !== undefined && (compareMax - compareMin) / step > 100)))) {
      invalid.add(id)
    }
    const axisIndex = key === 'xAxis' ? { xAxisIndex: index } : { yAxisIndex: index }
    if (type === 'category') {
      if (categories.length && !invalid.has(id) && (min !== undefined || max !== undefined || zoom)) rangeZoom.push({
        type: 'inside', ...axisIndex, filterMode: 'none', disabled: !zoom,
        ...(min !== undefined || max !== undefined ? { startValue: min ?? 0, endValue: max ?? categories.length - 1 } : {}),
      })
    } else {
      if (!invalid.has(id)) axisEdits.set(id, {
        ...(min !== undefined ? { min } : {}), ...(max !== undefined ? { max } : {}),
        ...(step !== undefined && type === 'value' ? { interval: step } : {}),
        // ECharts may retain the inline chart’s interval even after a tight zoom.
        ...(type === 'value' && step === undefined && (min !== undefined || max !== undefined || zoom) ? { interval: undefined } : {}),
      })
      if (zoom) rangeZoom.push({ type: 'inside', ...axisIndex, filterMode: 'none' })
    }
  }
  const change = (id: string, field: keyof Bounds, value: string) => setSettings(previous => ({ ...previous, [id]: { ...previous[id], [field]: value } }))
  const expanded: Entry = { ...normalized, animation: false }
  for (const key of ['xAxis', 'yAxis'] as const) {
    const edited = axes.filter(axis => axis.key === key).map(({ axis, id }) => ({ ...axis, ...axisEdits.get(id) }))
    if (edited.length) expanded[key] = Array.isArray(normalized[key]) ? edited : edited[0]
  }
  if (rangeZoom.length) expanded.dataZoom = rangeZoom
  if (labels !== null) expanded.series = series.map(item => {
    const type = item.type
    if (!['line', 'bar', 'scatter', 'pie'].includes(String(type))) return item
    const original = (item.label ?? {}) as Entry
    const nextLabel = {
      ...(type === 'pie' ? { formatter: '{b}: {c} ({d}%)' } : {
        position: type === 'bar' && axes.some(axis => axis.key === 'yAxis' && axis.type === 'category') ? 'right' : 'top',
      }),
      ...original, show: labels,
    }
    return {
      ...item,
      label: nextLabel,
      ...(type === 'line' && labels ? { showSymbol: true, symbolSize: item.symbolSize ?? 4 } : {}),
      labelLayout: { ...((item.labelLayout ?? {}) as Entry), hideOverlap: true },
    }
  })
  if (!expanded.tooltip) expanded.tooltip = { trigger: 'item' }

  return <Stack spacing={1.5}>
    <Stack direction="row" gap={1.5} flexWrap="wrap" alignItems="center" useFlexGap>
      <FormControlLabel control={<Checkbox checked={labels ?? series.some(item => (item.label as Entry | undefined)?.show === true)}
        onChange={event => setLabels(event.target.checked)} />} label="Data labels" />
      {axes.length > 0 && <FormControlLabel control={<Checkbox checked={zoom} onChange={event => setZoom(event.target.checked)} />} label="Enable wheel zoom / drag to pan" />}
      <Button onClick={() => { setSettings({}); setLabels(null); setZoom(false); setResetKey(key => key + 1) }}>Reset view</Button>
    </Stack>
    {axes.map(({ id, label, type, categories }) => {
      if (type === 'category' && !categories.length) return null
      return <Stack key={id} direction="row" gap={1.25} alignItems="center" flexWrap="wrap" useFlexGap>
        {(['min', 'max', ...(type === 'value' ? ['step'] : [])] as (keyof Bounds)[]).map(part => {
          const field = `${label} ${part === 'min' ? 'from' : part === 'max' ? 'to' : 'tick interval'}${type === 'time' ? ' (UTC)' : ''}`
          const common = { label: field, size: 'small' as const, value: settings[id]?.[part] ?? '',
            error: invalid.has(id), onChange: (event: React.ChangeEvent<HTMLInputElement>) => change(id, part, event.target.value), sx: { width: { xs: '100%', sm: 200 } } }
          return type === 'category'
            ? <TextField key={part} {...common} select><MenuItem value="">Auto</MenuItem>{categories.map((value, i) => <MenuItem key={i} value={String(i)}>{value}</MenuItem>)}</TextField>
            : <TextField key={part} {...common} type={type === 'time' ? 'date' : 'number'} slotProps={{ inputLabel: { shrink: true }, htmlInput: { step: 'any' } }} />
        })}
        {invalid.has(id) && <Typography role="alert" variant="caption" color="error.main">Use an ordered range and a positive, readable tick interval.</Typography>}
      </Stack>
    })}
    <Box sx={{ height: { xs: 350, sm: 'clamp(380px, 60vh, 750px)' }, minWidth: 0 }}>{renderChart(expanded, resetKey)}</Box>
  </Stack>
}
