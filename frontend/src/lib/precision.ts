/** Application business precision. Keep the raw text while a number is being typed. */
export const DECIMAL_PLACES = 3
export const DECIMAL_STEP = 0.001
export const DECIMAL_SCALE = 1000n
export const NONNEGATIVE_DECIMAL = /^(?:\d+|\d*\.\d{1,3})$/

/** Group the integral part as a BigInt so large stored monetary values keep their last digits. */
export function formatBusinessDecimal(value: string | number, digits = DECIMAL_PLACES, pad = true): string {
  const places = Math.min(DECIMAL_PLACES, Math.max(0, Math.trunc(digits)))
  const options = { minimumFractionDigits: pad ? places : 0, maximumFractionDigits: places }
  const match = /^([+-]?)(\d+)(?:\.(\d*))?$/.exec(String(value).trim())
  if (!match || typeof value === 'number') {
    const numeric = Number(value)
    return `${numeric < 0 ? '−' : ''}${Math.abs(numeric).toLocaleString(undefined, options)}`
  }
  const [, sign, whole, fraction = ''] = match
  const scale = 10n ** BigInt(places)
  let scaled = BigInt(whole) * scale + BigInt(fraction.padEnd(places, '0').slice(0, places) || '0')
  if (fraction[places] >= '5') scaled += 1n
  const remainder = (scaled % scale).toString().padStart(places, '0')
  const tail = places ? (pad ? remainder : remainder.replace(/0+$/, '')) : ''
  const formatter = new Intl.NumberFormat(undefined)
  const separator = tail ? (formatter.formatToParts(0.1).find((part) => part.type === 'decimal')?.value ?? '.') : ''
  return `${sign === '-' && scaled ? '−' : ''}${formatter.format(scaled / scale)}${separator}${tail}`
}
