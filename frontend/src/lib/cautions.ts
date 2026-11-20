/**
 * Dismissible cautions.
 *
 * A *caution* is a standing advisory a page shows beside its own data: a warning
 * that a well has no plan, that cost figures exclude a currency, that a locked
 * AFE baseline can no longer be rewritten, and so on. Cautions are useful once
 * and then become noise, so the reader can dismiss one after reading it.
 *
 * Two rules keep dismissal honest and local:
 *
 * 1. **Dismissal is a note about the reader, never about the data.** Nothing is
 *    written to the API and nothing is hidden from anybody else. The record is a
 *    per-workspace localStorage entry, like the remembered register scope in
 *    `activeScope.ts`, so two workspaces used in one browser never share notes.
 * 2. **A caution that changes comes back.** Every caution is identified by a
 *    *signature* — its stable key plus whatever it currently says. Dismissing the
 *    one-well-without-a-plan caution while one well is unplanned must not hide the
 *    same caution when four wells are. A dismissal therefore matches an exact
 *    (key, signature) pair, so the advisory re-appears as soon as its wording
 *    (usually the count or the amount) changes.
 *
 * Transient notices are not cautions: an error from a failed request, a success
 * message, and a validation message inside a dialog that blocks the user's next
 * action all keep their own explicit close button and must never be dismissible
 * through this module.
 */
export type CautionSeverity = 'info' | 'warning' | 'error'

export type CautionScope = {
  /** The workspace (organization) the note belongs to. */
  organizationSlug?: string
  /** The surface the note is shown on, so two pages never hide each other's cautions. */
  page: string
}

const STORAGE_PREFIX = 'wcp.dismissed-cautions'
/**
 * Fired on `window` after any dismissal or restore, so an open page (and the
 * "Show dismissed cautions" button beside its cautions) re-reads the notes
 * instead of showing a stale count until the next navigation.
 */
export const CAUTIONS_CHANGED = 'cautions-changed'

/**
 * A short, stable signature for the wording of a caution. The note stores this
 * instead of the prose, so a re-worded or re-counted caution is shown again.
 */
export function cautionSignature(...parts: (string | number | null | undefined)[]): string {
  const text = parts.map(part => (part === null || part === undefined ? '' : String(part))).join('|')
  // FNV-1a: tiny, deterministic and dependency-free. A collision would only mean
  // one caution stays hidden; it can never hide a different key's caution, because
  // the key is stored beside the signature.
  let hash = 0x811c9dc5
  for (let index = 0; index < text.length; index += 1) {
    hash ^= text.charCodeAt(index)
    hash = Math.imul(hash, 0x01000193) >>> 0
  }
  return `${text.length.toString(36)}-${hash.toString(36)}`
}

/** `page:key` — the identity a dismissal is remembered under. */
export function cautionId(key: string, scope: CautionScope): string {
  return `${scope.page}:${key}`
}

function storageKey(scope: CautionScope): string {
  return `${STORAGE_PREFIX}:${scope.organizationSlug?.trim() || 'workspace'}`
}

type StoredCautions = Record<string, string>

function readAll(scope: CautionScope): StoredCautions {
  try {
    const raw = localStorage.getItem(storageKey(scope))
    if (!raw) return {}
    const parsed = JSON.parse(raw) as unknown
    if (!parsed || typeof parsed !== 'object' || Array.isArray(parsed)) return {}
    const result: StoredCautions = {}
    for (const [id, signature] of Object.entries(parsed as Record<string, unknown>)) {
      if (typeof signature === 'string') result[id] = signature
    }
    return result
  } catch {
    // Private browsing, a disabled store or a legacy value all mean "nothing dismissed".
    return {}
  }
}

function writeAll(scope: CautionScope, values: StoredCautions): void {
  try {
    const entries = Object.entries(values).filter(([, signature]) => Boolean(signature))
    if (!entries.length) localStorage.removeItem(storageKey(scope))
    else localStorage.setItem(storageKey(scope), JSON.stringify(Object.fromEntries(entries)))
  } catch {
    // Dismissal is a convenience; failing to store it must never break the page.
  }
  try {
    window.dispatchEvent(new Event(CAUTIONS_CHANGED))
  } catch {
    // A non-browser host (the jsdom checks import this module too) has no window.
  }
}

/** True when this exact (key, signature) pair has been dismissed in this workspace. */
export function isCautionDismissed(key: string, signature: string, scope: CautionScope): boolean {
  return readAll(scope)[cautionId(key, scope)] === signature
}

/**
 * Drop a note the caution has outgrown.
 *
 * A stored note is only valid for the wording it was dismissed on. When a page
 * mounts the caution with fresh facts (a new count), the old note no longer hides
 * anything, so it is forgotten instead of lingering: "3 cautions dismissed on
 * this page" then always describes cautions that are actually hidden right now.
 */
export function pruneCaution(key: string, signature: string, scope: CautionScope): void {
  const values = readAll(scope)

  const id = cautionId(key, scope)
  if (!(id in values) || values[id] === signature) return
  delete values[id]
  writeAll(scope, values)
}

/** Remember the dismissal. Re-dismissing the same caution is a no-op. */
export function dismissCaution(key: string, signature: string, scope: CautionScope): void {
  const values = readAll(scope)
  values[cautionId(key, scope)] = signature
  writeAll(scope, values)
}

/** Forget one dismissal (a "show it again" affordance), or every one on a page. */
export function restoreCaution(key: string, scope: CautionScope): void {
  const values = readAll(scope)
  delete values[cautionId(key, scope)]
  writeAll(scope, values)
}

/**
 * Forget every dismissal recorded for a page in this workspace. Called by the
 * "Show dismissed cautions" affordance so a reader can bring them all back.
 */
export function restorePageCautions(scope: CautionScope): void {
  const values = readAll(scope)
  const prefix = `${scope.page}:`
  for (const id of Object.keys(values)) {
    if (id.startsWith(prefix)) delete values[id]
  }
  writeAll(scope, values)
}

/**
 * How many cautions of this page are currently dismissed.
 */
export function dismissedCautionCount(scope: CautionScope): number {
  const prefix = `${scope.page}:`
  return Object.keys(readAll(scope)).filter(id => id.startsWith(prefix)).length
}

/** Re-read a page's dismissal count whenever a caution is dismissed or restored. */
export function onCautionsChanged(handler: () => void): () => void {
  window.addEventListener(CAUTIONS_CHANGED, handler)
  return () => window.removeEventListener(CAUTIONS_CHANGED, handler)
}
