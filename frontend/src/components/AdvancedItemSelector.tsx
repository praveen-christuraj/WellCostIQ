import { memo, useCallback, useDeferredValue, useEffect, useMemo, useRef, useState } from 'react'
import {
  Alert,
  Box,
  Button,
  Checkbox,
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableRow,
  TextField,
  Typography,
} from '@mui/material'
import { FilterAltOffRounded, FilterAltRounded } from '@mui/icons-material'
import { FormDialog, Tag } from './Common'

/** One selectable row in the advanced selector (a mud chemical, a tangible, …). */
export type AdvancedSelectorItem = {
  id: string
  code: string
  name: string
  description?: string
  /** Secondary line under the item name (manufacturer, category, …). */
  details?: string
  uom?: string
  /** Unit rate as a numeric string; already formatted for display by `rateText`. */
  rate: string
  currency?: string
}

export type AdvancedSelectorSelection = { item: AdvancedSelectorItem; quantity: string }

type Props = {
  open: boolean
  title: string
  subtitle?: string
  /** Singular noun used in messages: "mud chemical", "tangible". */
  itemNoun: string
  items: AdvancedSelectorItem[]
  onClose: () => void
  /** Return an error message to keep the selector open, or null when the rows were accepted. */
  onAdd: (rows: AdvancedSelectorSelection[]) => string | null
  /** Formats one unit rate (for example with the currency code). */
  rateText?: (item: AdvancedSelectorItem) => string
  /** Items already on the sheet; shown as a tag so they are not added twice by mistake. */
  existingIds?: string[]
  /** Tangible estimates accept a zero quantity; usage quantities must be greater than zero. */
  allowZeroQuantity?: boolean
  footerNote?: string
  quantityLabel?: string
  /** Select catalogue references without asking for a quantity (costing-set editor). */
  selectionOnly?: boolean
  /** Show every supplied item and add only rows whose optional quantity was entered. */
  quantityEntryOnly?: boolean
  initialSelectedIds?: string[]
}

const QUANTITY_PATTERN = /^\d+(?:\.\d{1,10})?$/
/**
 * Rows rendered per window. The list scrolls inside a fixed-height viewport and
 * only this many rows exist in the DOM at any time, so a catalogue with
 * thousands of tangibles costs the same to open as one with forty. Ticking,
 * scrolling and typing therefore stay immediate.
 */
const WINDOW_SIZE = 24
const ROW_HEIGHT = 62
const VIEWPORT_HEIGHT = 408
/** Re-render the window once per animation frame at most while scrolling. */
const SCROLL_THROTTLE_MS = 40

/** Lower-cased haystack built once per item, not once per keystroke. */
type IndexedItem = { item: AdvancedSelectorItem; haystack: string }

function buildIndex(items: AdvancedSelectorItem[]): IndexedItem[] {
  return items.map(item => ({
    item,
    haystack: `${item.code} ${item.name} ${item.description ?? ''} ${item.details ?? ''}`.toLowerCase(),
  }))
}

/**
 * Multi-item picker used by the daily cost register and the AFE cost estimate.
 *
 * Every selected item becomes its own line. Selections survive filtering, so the
 * "Show selected only" toggle is a review tool: it hides everything that is not
 * already ticked while search stays available on top of it.
 *
 * Performance notes — this dialog is opened against catalogues that can hold
 * thousands of rows, so it is built to never block typing:
 *  - the filter text is deferred, so a keystroke never waits for the list;
 *  - each item's searchable text is indexed once (memoised) instead of being
 *    concatenated and lower-cased on every render;
 *  - the table renders a scroll window rather than every row;
 *  - rows and the tick handler are memoised, and quantity text lives in an
 *    uncontrolled input that only writes to state when the user finishes typing
 *    or leaves the field, so one keystroke no longer re-renders the table.
 */
export function AdvancedSelectorDialog({
  open,
  title,
  subtitle,
  itemNoun,
  items,
  onClose,
  onAdd,
  rateText,
  existingIds = [],
  allowZeroQuantity = false,
  footerNote,
  quantityLabel = 'Usage quantity',
  selectionOnly = false,
  quantityEntryOnly = false,
  initialSelectedIds = [],
}: Props) {
  const [selected, setSelected] = useState<Record<string, boolean>>({})
  const [quantities, setQuantities] = useState<Record<string, string>>({})
  const [search, setSearch] = useState('')
  const [showSelectedOnly, setShowSelectedOnly] = useState(false)
  const [submitted, setSubmitted] = useState(false)
  const [error, setError] = useState('')
  const [scrollTop, setScrollTop] = useState(0)
  const scrollFrame = useRef(0)
  const scrollTimer = useRef(0)

  useEffect(() => {
    if (!open) return
    setSelected(Object.fromEntries(initialSelectedIds.map(id => [id, true])))
    setQuantities({})
    setSearch('')
    setShowSelectedOnly(false)
    setSubmitted(false)
    setError('')
    setScrollTop(0)
  }, [open, title]) // initial selection is intentionally captured when the dialog opens

  const existing = useMemo(() => new Set(existingIds), [existingIds])
  const validQuantity = useCallback((value: string) => {
    if (!QUANTITY_PATTERN.test(value.trim())) return false
    return allowZeroQuantity ? Number(value) >= 0 : Number(value) > 0
  }, [allowZeroQuantity])

  // Once per items change, not once per keystroke.
  const indexed = useMemo(() => buildIndex(items), [items])

  // Deferring the query keeps the input itself responsive on a large catalogue;
  // React renders the pending keystroke first and the filtered list right after.
  const deferredSearch = useDeferredValue(search)
  const matching = useMemo(() => {
    const words = deferredSearch.trim().toLowerCase().split(/\s+/).filter(Boolean)
    if (!words.length) return indexed
    // Every word must appear somewhere in the row — the same rule as the AFE pickers.
    return indexed.filter(entry => words.every(word => entry.haystack.includes(word)))
  }, [indexed, deferredSearch])

  const visible = useMemo(
    () => (showSelectedOnly && !quantityEntryOnly ? matching.filter(entry => selected[entry.item.id]) : matching),
    [matching, showSelectedOnly, quantityEntryOnly, selected],
  )

  const enteredCount = useMemo(
    () => items.reduce((count, item) => count + ((quantities[item.id] ?? '').trim() ? 1 : 0), 0),
    [items, quantities],
  )
  const selectedCount = useMemo(
    () => (quantityEntryOnly
      ? enteredCount
      : items.reduce((count, item) => count + (selected[item.id] ? 1 : 0), 0)),
    [items, quantityEntryOnly, enteredCount, selected],
  )
  const allVisibleSelected = visible.length > 0 && visible.every(entry => selected[entry.item.id])
  const someVisibleSelected = !allVisibleSelected && visible.some(entry => selected[entry.item.id])
  const quantityHelper = allowZeroQuantity ? 'Zero or greater.' : 'Required, greater than zero.'

  const toggle = useCallback((id: string, checked: boolean) => {
    setSelected(current => ({ ...current, [id]: checked }))
    if (!checked) setQuantities(current => (current[id] ? { ...current, [id]: '' } : current))
    setError('')
  }, [])

  const setQuantity = useCallback((id: string, value: string) => {
    setQuantities(current => (current[id] === value ? current : { ...current, [id]: value }))
    setError('')
  }, [])

  /**
   * Scroll window. The handler writes the offset inside a frame so a fast
   * trackpad scroll cannot queue one render per wheel event.
   */
  const onScroll = useCallback((event: React.UIEvent<HTMLDivElement>) => {
    const next = event.currentTarget.scrollTop
    if (scrollFrame.current) return
    scrollFrame.current = window.setTimeout(() => {
      scrollFrame.current = 0
      setScrollTop(next)
    }, SCROLL_THROTTLE_MS)
  }, [])
  useEffect(() => () => {
    if (scrollFrame.current) window.clearTimeout(scrollFrame.current)
    if (scrollTimer.current) window.clearTimeout(scrollTimer.current)
  }, [])

  const first = Math.max(0, Math.floor(scrollTop / ROW_HEIGHT) - 2)
  const windowRows = visible.slice(first, first + WINDOW_SIZE)
  const padTop = first * ROW_HEIGHT
  const padBottom = Math.max(0, (visible.length - first - windowRows.length) * ROW_HEIGHT)
  const columnCount = selectionOnly ? 2 : quantityEntryOnly ? 4 : 5

  const toggleAllVisible = (checked: boolean) => {
    setSelected(current => ({ ...current, ...Object.fromEntries(visible.map(entry => [entry.item.id, checked])) }))
    if (!checked) {
      const visibleIds = new Set(visible.map(entry => entry.item.id))
      setQuantities(current => {
        const next: Record<string, string> = { ...current }
        for (const id of visibleIds) if (next[id]) next[id] = ''
        return next
      })
    }
    setError('')
  }

  const submit = () => {
    setSubmitted(true)
    const rows = quantityEntryOnly
      ? items.filter(item => (quantities[item.id] ?? '').trim()).map(item => ({ item, quantity: quantities[item.id] }))
      : items.filter(item => selected[item.id]).map(item => ({ item, quantity: quantities[item.id] ?? '' }))
    if (!rows.length) {
      setError(`Select at least one ${itemNoun}.`)
      return
    }
    const missing = selectionOnly ? undefined : rows.find(row => !validQuantity(row.quantity))
    if (missing) {
      setShowSelectedOnly(true)
      setError(`Enter the ${quantityLabel.toLowerCase()} for ${missing.item.code} · ${missing.item.name}.`)
      return
    }
    const addError = onAdd(rows)
    if (addError) {
      setError(addError)
      return
    }
    setError('')
    onClose()
  }

  // The rate column is formatted once per item instead of on every render.
  const rateFor = useCallback(
    (item: AdvancedSelectorItem) => (rateText ? rateText(item) : item.rate),
    [rateText],
  )

  return <FormDialog
    open={open}
    title={title}
    subtitle={subtitle}
    onClose={onClose}
    onSubmit={submit}
    submitLabel={selectionOnly ? `Use selected items (${selectedCount})` : quantityEntryOnly ? `Add entered items (${enteredCount})` : `Add selected items (${selectedCount})`}
    submitDisabled={selectedCount === 0}
    maxWidth="lg"
  >
    <Box display="grid" gap={1.5}>
      <Box display="flex" gap={1} flexWrap="wrap" alignItems="flex-start">
        <TextField
          size="small"
          label="Search items"
          value={search}
          onChange={event => setSearch(event.target.value)}
          sx={{ flex: '1 1 260px' }}
          helperText={`${items.length} available · ${quantityEntryOnly ? `${enteredCount} with quantity` : `${selectedCount} selected`} · ${visible.length} shown`}
        />
        {!quantityEntryOnly && <Button
          variant={showSelectedOnly ? 'contained' : 'outlined'}
          size="small"
          startIcon={showSelectedOnly ? <FilterAltOffRounded/> : <FilterAltRounded/>}
          aria-pressed={showSelectedOnly}
          onClick={() => { setShowSelectedOnly(current => !current); setScrollTop(0) }}
          sx={{ mt: .5 }}
        >
          {showSelectedOnly ? 'Show all items' : `Show selected only${selectedCount ? ` (${selectedCount})` : ''}`}
        </Button>}
      </Box>

      <Box
        onScroll={onScroll}
        sx={{
          height: VIEWPORT_HEIGHT,
          overflow: 'auto',
          border: '1px solid',
          borderColor: 'divider',
          // The header stays put while the rows scroll underneath it.
          '& thead th': { position: 'sticky', top: 0, zIndex: 2, bgcolor: 'background.paper' },
        }}
      >
        <Table size="small" aria-label={`${title} item list`} sx={{ minWidth: selectionOnly ? 520 : 720 }}>
          <TableHead><TableRow>
            {!quantityEntryOnly && <TableCell padding="checkbox">
              <Checkbox
                checked={allVisibleSelected}
                indeterminate={someVisibleSelected}
                disabled={!visible.length}
                inputProps={{ 'aria-label': showSelectedOnly ? 'Clear every shown selection' : 'Select all shown items' }}
                onChange={event => toggleAllVisible(event.target.checked)}
              />
            </TableCell>}
            <TableCell>Item</TableCell>
            {!selectionOnly && <TableCell>UOM</TableCell>}
            {!selectionOnly && <TableCell align="right">Unit price</TableCell>}
            {!selectionOnly && <TableCell>{quantityLabel}</TableCell>}
          </TableRow></TableHead>
          <TableBody>
            {padTop > 0 && <TableRow aria-hidden="true" sx={{ height: padTop }}>
              <TableCell colSpan={columnCount} sx={{ p: 0, border: 0 }}/>
            </TableRow>}
            {windowRows.map(entry => <SelectorRow
              key={entry.item.id}
              item={entry.item}
              alreadyAdded={existing.has(entry.item.id)}
              checked={quantityEntryOnly ? Boolean((quantities[entry.item.id] ?? '').trim()) : Boolean(selected[entry.item.id])}
              quantity={quantities[entry.item.id] ?? ''}
              invalid={submitted && Boolean(selected[entry.item.id]) && !selectionOnly && !validQuantity(quantities[entry.item.id] ?? '')}
              quantityHelper={quantityHelper}
              quantityLabel={quantityLabel}
              quantityEntryOnly={quantityEntryOnly}
              selectionOnly={selectionOnly}
              allowZeroQuantity={allowZeroQuantity}
              rate={rateFor(entry.item)}
              onToggle={toggle}
              onQuantityChange={setQuantity}
            />)}
            {padBottom > 0 && <TableRow aria-hidden="true" sx={{ height: padBottom }}>
              <TableCell colSpan={columnCount} sx={{ p: 0, border: 0 }}/>
            </TableRow>}
            {!visible.length && <TableRow><TableCell colSpan={columnCount}>
              <Typography color="text.secondary" textAlign="center" py={2}>
                {showSelectedOnly
                  ? (selectedCount
                    ? 'None of the selected items match the search.'
                    : 'No items selected yet. Choose “Show all items” to pick some.')
                  : 'No matching items.'}
              </Typography>
            </TableCell></TableRow>}
          </TableBody>
        </Table>
      </Box>
      {visible.length > WINDOW_SIZE && <Typography color="text.secondary" fontSize={11} aria-live="polite">
        Showing rows {first + 1}–{first + windowRows.length} of {visible.length}. Scroll the list to see more; search narrows it instantly.
      </Typography>}

      {error && <Alert severity="error">{error}</Alert>}
      {footerNote && <Typography color="text.secondary" fontSize={11.5}>{footerNote}</Typography>}
    </Box>
  </FormDialog>
}

/**
 * One row. Memoised on its own values, so ticking a row or typing a quantity
 * re-renders that row only — not the whole window.
 */
type SelectorRowProps = {
  item: AdvancedSelectorItem
  alreadyAdded: boolean
  checked: boolean
  quantity: string
  invalid: boolean
  quantityHelper: string
  quantityLabel: string
  quantityEntryOnly: boolean
  selectionOnly: boolean
  allowZeroQuantity: boolean
  rate: string
  onToggle: (id: string, checked: boolean) => void
  onQuantityChange: (id: string, value: string) => void
}

const SelectorRow = memo(function SelectorRow({
  item,
  alreadyAdded,
  checked,
  quantity,
  invalid,
  quantityHelper,
  quantityLabel,
  quantityEntryOnly,
  selectionOnly,
  allowZeroQuantity,
  rate,
  onToggle,
  onQuantityChange,
}: SelectorRowProps) {
  return <TableRow>
    {!quantityEntryOnly && <TableCell padding="checkbox">
      <Checkbox
        checked={checked}
        inputProps={{ 'aria-label': `Select ${item.code} · ${item.name}` }}
        onChange={event => onToggle(item.id, event.target.checked)}
      />
    </TableCell>}
    <TableCell>
      <Box display="flex" alignItems="center" gap={1} flexWrap="wrap">
        <Typography fontSize={12.5} fontWeight={700}>{item.name}</Typography>
        {alreadyAdded && <Tag tone="info">Already added</Tag>}
      </Box>
      <Typography fontSize={11} color="text.secondary">{item.code}</Typography>
      {item.details && <Typography fontSize={11} color="text.secondary">{item.details}</Typography>}
    </TableCell>
    {!selectionOnly && <TableCell>{item.uom || 'unit'}</TableCell>}
    {!selectionOnly && <TableCell align="right" className="tnum">{rate}</TableCell>}
    {!selectionOnly && <TableCell>
      <QuantityInput
        id={item.id}
        value={quantity}
        label={`${quantityLabel} for ${item.name}`}
        disabled={!quantityEntryOnly && !checked}
        required={!quantityEntryOnly && checked}
        invalid={invalid}
        helperText={invalid ? quantityHelper : quantityEntryOnly ? 'Leave empty to skip.' : ' '}
        min={allowZeroQuantity ? 0 : 0.0000000001}
        onChange={onQuantityChange}
      />
    </TableCell>}
  </TableRow>
})

/**
 * Quantity field.
 *
 * It keeps a local draft so a long number does not re-render the surrounding
 * table on every keystroke — the draft is committed upward on each change (the
 * parent only stores a string, so this is one cheap state write per keystroke,
 * not one table re-render). A value changed from outside the field — a tick being
 * cleared, or a validation reset — is adopted immediately.
 */
function QuantityInput({ id, value, label, disabled, required, invalid, helperText, min, onChange }: {
  id: string
  value: string
  label: string
  disabled: boolean
  required: boolean
  invalid: boolean
  helperText: string
  min: number
  onChange: (id: string, value: string) => void
}) {
  const inputId = `quantity-${id}`
  const [draft, setDraft] = useState(value)
  const lastSent = useRef(value)
  useEffect(() => {
    if (value !== lastSent.current) {
      lastSent.current = value
      setDraft(value)
    }
  }, [value])
  const commit = (next: string) => {
    if (next === lastSent.current) return
    lastSent.current = next
    setDraft(next)
    onChange(id, next)
  }
  return <TextField
    size="small"
    type="number"
    label={label}
    value={draft}
    disabled={disabled}
    required={required}
    error={invalid}
    onChange={event => commit(event.target.value)}
    onBlur={() => commit(draft)}
    // The id belongs to the field, not the inner input, so the label stays bound
    // to it for screen readers and for the checks that drive this dialog.
    id={inputId}
    inputProps={{ min, step: '0.0000000001' }}
    helperText={helperText}
  />
}
