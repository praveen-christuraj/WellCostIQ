/**
 * Chart → record resolution for tooltips and drill-through clicks.
 *
 * A chart click must open the record the user *saw*, never the one next to it.
 * Three separate mistakes have opened a wrong well on the Operations dashboard.
 * All three are prevented here by resolving a click to a *record identity*
 * rather than to a row number in a nearby array:
 *
 *  1. **Index into the wrong array.** A chart was plotted from a reversed or
 *     sorted copy of the rows (largest first, newest first), and the click
 *     handler indexed the *original* array with the plotted row number. With
 *     three wells A, B, C the reversed plot meant A opened C and C opened A.
 *  2. **A row number is not an identity.** Server rows can share a `well_id`
 *     (one row per AFE or scope) and a list can change between the plot and the
 *     click. A positional lookup then opens a neighbouring record even when the
 *     array order is right.
 *  3. **The identity was dropped on the way to the handler.** The shared chart
 *     host hands the page a *normalised* click (`chartRowId` at the top level),
 *     while this module only looked for the raw ECharts shape
 *     (`data.chartRowId`). The identity was therefore never found, the code fell
 *     through to the positional fallback, and the page passed the *unreversed*
 *     array to that fallback — mistake 1 again, behind a fix that looked right.
 *     `clickIdentity` now reads every shape the host or ECharts can deliver, and
 *     a click that names a record which is not plotted opens nothing at all.
 *
 * Every plotted data item carries the identity it was drawn from in
 * `chartRowId`, and the shared chart host returns that identity with the click
 * (`name` is kept for the tooltip/legend). Callers resolve the click to the row
 * with `resolveChartClick`, which matches the identity first and only falls
 * back to the *plotted* array position when the point carries no identity.
 */

/**
 * A chart click as far as this module is concerned: either the normalised event
 * the shared chart host emits, or the raw ECharts payload.
 */
export type ChartClick = {
  dataIndex?: number | null
  seriesIndex?: number | null
  /** `name` of the clicked data item (the category label for most series). */
  name?: string
  /** Normalised host event: the identity carried by the clicked data item. */
  chartRowId?: string
  /** Raw ECharts payload: the clicked data item itself. */
  data?: unknown
  /** Normalised host event: the untouched ECharts payload. */
  raw?: unknown
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

function identityOf(candidate: unknown): string {
  if (!candidate || typeof candidate !== 'object') return ''
  const value = (candidate as { chartRowId?: unknown }).chartRowId
  return typeof value === 'string' ? value : ''
}

/**
 * Read the identity carried by a clicked point.
 *
 * Order matters only for clarity — every source names the same record:
 * the normalised host event (`chartRowId`), the raw ECharts data item
 * (`data.chartRowId`), then the raw payload the host keeps (`raw.data`).
 */
export function clickIdentity(params: ChartClick | null | undefined): string {
  if (!params) return ''
  return identityOf(params)
    || identityOf(params.data)
    || identityOf((params.raw as { data?: unknown } | undefined)?.data)
}

/**
 * Resolve a click to the row it was plotted from.
 *
 * `plotted` is the array the series was built from — the reversed or sorted
 * copy, not the original. A click that carries an identity is answered by that
 * identity alone: when no plotted row has it the click opens nothing, because a
 * guess by position is exactly how a neighbouring well was opened. Only a point
 * with no identity at all falls back to its position in `plotted`.
 */
export function resolveChartClick<T>(
  params: ChartClick | null | undefined,
  plotted: T[],
  idOf: (row: T) => string,
): T | undefined {
  if (!params) return undefined
  const identity = clickIdentity(params)
  if (identity) return plotted.find(row => idOf(row) === identity)
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
