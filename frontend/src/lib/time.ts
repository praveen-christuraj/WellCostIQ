/**
 * Application-wide West Africa Time (Africa/Lagos, WAT = UTC+01:00) helpers.
 *
 * Nigeria / West Africa Time observes UTC+01:00 permanently with no daylight
 * saving transitions. The database stores timezone-aware UTC instants; every
 * display string, datetime-local input, register table, and PDF/Excel/CSV
 * export converts through these helpers so timestamps are always shown and
 * entered in WAT regardless of the browser machine's OS timezone setting.
 */

export const WAT_TIMEZONE = 'Africa/Lagos'
export const WAT_LABEL = 'WAT (UTC+1:00)'
export const WAT_SHORT = 'WAT'
const WAT_OFFSET_MS = 3_600_000

const HAS_TZ_RE = /(?:Z|[+-]\d{2}:?\d{2})$/i
const DATE_ONLY_RE = /^\d{4}-\d{2}-\d{2}$/

const pad2 = (n: number) => String(n).padStart(2, '0')

/** Parse an API timestamp (or Date) into a valid Date; naive strings are stored UTC. */
export function parseInstant(value: string | Date | null | undefined): Date | null {
  if (!value) return null
  if (value instanceof Date) return Number.isNaN(value.getTime()) ? null : value
  const text = String(value).trim()
  if (!text) return null
  if (DATE_ONLY_RE.test(text)) {
    const d = new Date(`${text}T00:00:00+01:00`)
    return Number.isNaN(d.getTime()) ? null : d
  }
  const normalised = text.includes('T') ? text : text.replace(' ', 'T')
  const withTz = HAS_TZ_RE.test(normalised) ? normalised : `${normalised}Z`
  const parsed = new Date(withTz)
  return Number.isNaN(parsed.getTime()) ? null : parsed
}

function watParts(date: Date) {
  const shifted = new Date(date.getTime() + WAT_OFFSET_MS)
  return {
    year: shifted.getUTCFullYear(),
    month: pad2(shifted.getUTCMonth() + 1),
    day: pad2(shifted.getUTCDate()),
    hour: pad2(shifted.getUTCHours()),
    minute: pad2(shifted.getUTCMinutes()),
    second: pad2(shifted.getUTCSeconds()),
  }
}

/** Format an instant as `YYYY-MM-DD HH:mm WAT` (or with seconds when requested). */
export function formatWatDateTime(
  value: string | Date | null | undefined,
  options?: { seconds?: boolean; suffix?: boolean },
): string {
  const date = parseInstant(value)
  if (!date) return ''
  const p = watParts(date)
  const time = options?.seconds ? `${p.hour}:${p.minute}:${p.second}` : `${p.hour}:${p.minute}`
  const suffix = options?.suffix === false ? '' : ` ${WAT_SHORT}`
  return `${p.year}-${p.month}-${p.day} ${time}${suffix}`
}

/** Compact `YYYY-MM-DD HH:mm` in WAT (for columns whose header already displays `(WAT)`). */
export function formatWatShort(value: string | Date | null | undefined): string {
  return formatWatDateTime(value, { suffix: false })
}

/** Date-only `YYYY-MM-DD` in West Africa Time (UTC+01:00) for stored timestamps. */
export function formatWatDate(value: string | Date | null | undefined): string {
  const date = parseInstant(value)
  if (!date) return ''
  const p = watParts(date)
  return `${p.year}-${p.month}-${p.day}`
}

/** Clock-only `HH:mm` (or `HH:mm WAT`) in West Africa Time. */
export function formatWatClock(value: string | Date | null | undefined, withSuffix = false): string {
  const date = parseInstant(value)
  if (!date) return ''
  const p = watParts(date)
  return withSuffix ? `${p.hour}:${p.minute} ${WAT_SHORT}` : `${p.hour}:${p.minute}`
}

/** Convert a stored instant to `YYYY-MM-DDTHH:mm` for `<input type="datetime-local">` in WAT. */
export function toWatDateTimeInput(value: string | Date | null | undefined): string {
  const date = parseInstant(value)
  if (!date) return ''
  const p = watParts(date)
  return `${p.year}-${p.month}-${p.day}T${p.hour}:${p.minute}`
}

/** Convert a WAT `<input type="datetime-local">` string into an ISO-8601 instant (`+01:00` -> UTC). */
export function fromWatDateTimeInput(localValue: string | null | undefined): string | null {
  const text = (localValue || '').trim()
  if (!text) return null
  if (HAS_TZ_RE.test(text)) {
    const direct = new Date(text)
    return Number.isNaN(direct.getTime()) ? null : direct.toISOString()
  }
  const withSeconds = /^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}$/.test(text) ? `${text}:00` : text
  const parsed = new Date(`${withSeconds}+01:00`)
  return Number.isNaN(parsed.getTime()) ? null : parsed.toISOString()
}

/** Current date `YYYY-MM-DD` in West Africa Time (UTC+01:00). */
export function watTodayIso(): string {
  const p = watParts(new Date())
  return `${p.year}-${p.month}-${p.day}`
}

/** Current timestamp `YYYY-MM-DD HH:mm WAT` for export headers, footers, and live badges. */
export function watNowFormatted(): string {
  return formatWatDateTime(new Date())
}
