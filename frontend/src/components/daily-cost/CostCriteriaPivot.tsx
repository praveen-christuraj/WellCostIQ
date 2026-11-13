import { useMemo, useState } from 'react'
import { Box, MenuItem, Paper, TextField, Typography } from '@mui/material'
import { dailyMoney, type DailyCostCriteriaRow } from '../../lib/dailyCost'

/**
 * Multi-criteria cost analysis.
 *
 * The ledger stores four factors on every line — hole section, phase, activity
 * and classification — so "what did this phase cost under that activity" is a
 * pivot of the same rows, not another report. Two factors are chosen as rows
 * and columns and the third stays as a filter, so the analyst can walk from a
 * phase to its activities, then to the sections inside an activity.
 */
type Dimension = 'section' | 'phase' | 'activity' | 'classification'
type Metric = 'actual' | 'npt' | 'upa' | 'share'

const DIMENSIONS: { key: Dimension; label: string }[] = [
  { key: 'phase', label: 'Phase' },
  { key: 'activity', label: 'Activity' },
  { key: 'section', label: 'Hole section' },
  { key: 'classification', label: 'Planned / UPA / NPT' },
]

const METRICS: { key: Metric; label: string }[] = [
  { key: 'actual', label: 'Actual cost' },
  { key: 'npt', label: 'NPT cost' },
  { key: 'upa', label: 'UPA cost' },
  { key: 'share', label: 'Share of actual' },
]

function labelOf(row: DailyCostCriteriaRow, dimension: Dimension): string {
  if (dimension === 'section') return row.section_code ? `${row.section_code} · ${row.section_name}` : 'Well level (no section)'
  if (dimension === 'phase') return row.phase_code || 'No phase'
  if (dimension === 'activity') return row.activity_code || 'No activity'
  return row.classification
}

function valueOf(row: DailyCostCriteriaRow, metric: Metric): number {
  return Number(metric === 'share' ? row.share : row[metric] ?? 0)
}

function display(value: number, metric: Metric, currency: string): string {
  if (!Number.isFinite(value)) return '—'
  return metric === 'share'
    ? `${value.toFixed(1)}%`
    : dailyMoney(value, currency)
}

export function CostCriteriaPivot({ rows, currency }: { rows: DailyCostCriteriaRow[]; currency: string }) {
  const [rowDimension, setRowDimension] = useState<Dimension>('phase')
  const [columnDimension, setColumnDimension] = useState<Dimension>('activity')
  const [metric, setMetric] = useState<Metric>('actual')

  const pivot = useMemo(() => {
    const rowKeys: string[] = []
    const columnKeys: string[] = []
    const cells = new Map<string, number>()
    const rowTotals = new Map<string, number>()
    const columnTotals = new Map<string, number>()
    let grand = 0
    for (const row of rows) {
      const rowKey = labelOf(row, rowDimension)
      const columnKey = labelOf(row, columnDimension)
      if (!rowKeys.includes(rowKey)) rowKeys.push(rowKey)
      if (!columnKeys.includes(columnKey)) columnKeys.push(columnKey)
      const key = `${rowKey}\u0000${columnKey}`
      const value = valueOf(row, metric)
      cells.set(key, (cells.get(key) ?? 0) + value)
      rowTotals.set(rowKey, (rowTotals.get(rowKey) ?? 0) + value)
      columnTotals.set(columnKey, (columnTotals.get(columnKey) ?? 0) + value)
      grand += value
    }
    const byTotal = (a: string, b: string) => (
      (rowTotals.get(b) ?? columnTotals.get(b) ?? 0) - (rowTotals.get(a) ?? columnTotals.get(a) ?? 0)
    )
    rowKeys.sort(byTotal)
    columnKeys.sort((a, b) => (columnTotals.get(b) ?? 0) - (columnTotals.get(a) ?? 0))
    return { rowKeys, columnKeys, cells, rowTotals, columnTotals, grand }
  }, [rows, rowDimension, columnDimension, metric])

  if (!rows.length) {
    return <Paper variant="outlined" sx={{ p: 2, borderRadius: 2 }}>
      <Typography fontSize={12.5} color="text.secondary">
        No cost lines in this filter, so there is nothing to cross-tabulate yet.
      </Typography>
    </Paper>
  }

  const sameDimension = rowDimension === columnDimension
  return <Paper variant="outlined" sx={{ p: 2, borderRadius: 2, minWidth: 0 }}>
    <Typography fontWeight={800} fontSize={15}>Cost by criteria</Typography>
    <Typography color="text.secondary" fontSize={11.5} mt={.25} mb={1.2}>
      Every daily line carries its hole section, phase, activity and classification, so the same
      ledger can be read two factors at a time: pick what runs down the side and what runs across.
      Totals always tie back to the actual cost on this page.
    </Typography>
    <Box display="flex" gap={1} flexWrap="wrap" mb={1.4}>
      <TextField select size="small" label="Rows" value={rowDimension} sx={{ minWidth: 190 }}
        onChange={event => setRowDimension(event.target.value as Dimension)}>
        {DIMENSIONS.map(item => <MenuItem key={item.key} value={item.key}>{item.label}</MenuItem>)}
      </TextField>
      <TextField select size="small" label="Columns" value={columnDimension} sx={{ minWidth: 190 }}
        onChange={event => setColumnDimension(event.target.value as Dimension)}>
        {DIMENSIONS.map(item => <MenuItem key={item.key} value={item.key}>{item.label}</MenuItem>)}
      </TextField>
      <TextField select size="small" label="Measure" value={metric} sx={{ minWidth: 170 }}
        onChange={event => setMetric(event.target.value as Metric)}>
        {METRICS.map(item => <MenuItem key={item.key} value={item.key}>{item.label}</MenuItem>)}
      </TextField>
    </Box>
    {sameDimension
      ? <Typography fontSize={12.5} color="text.secondary">Choose two different factors to build the cross-tabulation.</Typography>
      : <Box sx={{ overflowX: 'auto' }}>
        <Box component="table" sx={{
          borderCollapse: 'collapse', width: '100%', minWidth: 520,
          '& th': {
            textAlign: 'left', fontSize: 10, letterSpacing: .5, fontWeight: 800, color: 'text.secondary',
            py: 1, px: 1, borderBottom: '1px solid', borderColor: 'divider', whiteSpace: 'nowrap',
            position: 'sticky', top: 0, bgcolor: 'background.paper',
          },
          '& td': { py: .9, px: 1, fontSize: 11.8, borderBottom: '1px solid', borderColor: 'divider', whiteSpace: 'nowrap', fontVariantNumeric: 'tabular-nums' },
          '& td.num, & th.num': { textAlign: 'right' },
          '& tr.total td': { fontWeight: 800, bgcolor: 'action.hover' },
        }}>
          <thead>
            <tr>
              <th>{DIMENSIONS.find(item => item.key === rowDimension)?.label}</th>
              {pivot.columnKeys.map(key => <th key={key} className="num">{key}</th>)}
              <th className="num">Total</th>
            </tr>
          </thead>
          <tbody>
            {pivot.rowKeys.map(rowKey => <tr key={rowKey}>
              <td><Typography fontSize={11.8} fontWeight={700}>{rowKey}</Typography></td>
              {pivot.columnKeys.map(columnKey => {
                const value = pivot.cells.get(`${rowKey}\u0000${columnKey}`)
                return <td key={columnKey} className="num">
                  {value === undefined ? '—' : display(value, metric, currency)}
                </td>
              })}
              <td className="num"><strong>{display(pivot.rowTotals.get(rowKey) ?? 0, metric, currency)}</strong></td>
            </tr>)}
            <tr className="total">
              <td>Total</td>
              {pivot.columnKeys.map(columnKey => <td key={columnKey} className="num">
                {display(pivot.columnTotals.get(columnKey) ?? 0, metric, currency)}
              </td>)}
              <td className="num">{display(pivot.grand, metric, currency)}</td>
            </tr>
          </tbody>
        </Box>
      </Box>}
  </Paper>
}
