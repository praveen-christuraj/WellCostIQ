/**
 * Chart → record resolution for tooltips and drill-through clicks.
 *
 * A chart click must open the record the user *saw*, never the one next to it.
 * Two separate mistakes caused a wrong well to open on the Operations
 * dashboard, and both are prevented by resolving a click to a *record* rather
 * than to a row number in a nearby array:
 *
 *  1. **Index into the wrong array.** A chart was plotted from a reversed or
 *     sorted copy of the rows (largest first, newest first), and the click
 *     handler indexed the *original* array with the plotted row number. With
 *     three wells A, B, C the reversed plot meant A opened C, B opened A and C
 *     opened B — the reported "clicked A, got C" bug on AFE vs actual cost and
 *     planned vs actual days.
 *  2. **A row number is not an identity.** Server rows can share a `well_id`
 *     (one row per AFE or scope) and a list can change between the plot and the
 *     click. A positional lookup then opens a neighbouring record even when the
 *     array order is right.
 *
 * Every plotted data item therefore carries the identity it was drawn from in
 * `chartRowId`, and the shared chart host returns that identity with the click
 * (`name` is kept for the tooltip/legend). Callers resolve the click to the row
 * with `resolveChartClick`, which matches the identity first and only falls
 * back to the *plotted* array position.
 */

/** The ECharts click payload as far as this module is concerned. */
export type ChartClick = {
  dataIndex?: number
  seriesIndex?: number
  /** `name` of the clicked data item (the category label for most series). */
  name?: string
  data?: unknown
  event?: { stopPropagation?: () => void }
}

/** A plotted data item that remembers the record it was drawn from. */
export type ChartDatum = { value: number | string; chartRowId: string; name?: string }

/** Namespace a record id so two chart kinds can never collide. */
export function chartRowId(kind: string, id: string): string {
  return `${kind}:${id}`
}

/** Plot `rows` as data items that carry their own record identity. */
export function chartData<T>(
  rows: T[],
  idOf: (row: T) => string,
  valueOf: (row: T) => number | string | null | undefined,
  nameOf?: (row: T) => string,
): ChartDatum[] {
  return rows.map(row => {
    const value = valueOf(row)
    const item: ChartDatum = {
      value: (value === null || value === undefined ? 0 : value) as number | string,
      chartRowId: idOf(row),
    }
    if (nameOf) item.name = nameOf(row)
    return item
  })
}

/** Read the identity carried by a clicked point, whatever the series type. */
export function clickIdentity(params: ChartClick): string {
  const data = params.data as { chartRowId?: unknown } | undefined
  if (data && typeof data.chartRowId === 'string' && data.chartRowId) return data.chartRowId
  return ''
}

/**
 * Resolve a click to the row it was plotted from.
 *
 * `plotted` is the array the series was built from — the reversed or sorted
 * copy, not the original — so the positional fallback can only ever land on the
 * same record the point was drawn from.
 */
export function resolveChartClick<T>(
  params: ChartClick,
  plotted: T[],
  idOf: (row: T) => string,
): T | undefined {
  const identity = clickIdentity(params)
  if (identity) {
    const match = plotted.find(row => idOf(row) === identity)
    if (match) return match
  }
  const index = params.dataIndex
  if (typeof index === 'number' && index >= 0 && index < plotted.length) return plotted[index]
  return undefined
}

/**
 * The `onEvents` handler for a chart whose points identify their record.
 * Returns a function usable directly as `onEvents={{ click: drillTo(...) }}`.
 */
export function chartDrillHandler<T>(
  plotted: T[],
  idOf: (row: T) => string,
  open: (row: T) => void,
): (params: ChartClick) => void {
  return (params: ChartClick) => {
    const row = resolveChartClick(params, plotted, idOf)
    if (row) open(row)
  }
}
