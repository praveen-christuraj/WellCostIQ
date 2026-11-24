import { useCallback, useEffect, useMemo, useState } from 'react'
import {
  AddRounded,
  DeleteForeverRounded,
  DeleteOutlineRounded,
  DownloadRounded,
  EditOutlined,
  FileDownloadOutlined,
  FileUploadOutlined,
  HistoryOutlined,
  PriceChangeOutlined,
  RestoreFromTrashRounded,
} from '@mui/icons-material'
import {
  Alert,
  Box,
  Button,
  Checkbox,
  Chip,
  CircularProgress,
  FormControlLabel,
  IconButton,
  Menu,
  MenuItem,
  Paper,
  Stack,
  Table,
  TableBody,
  TableCell,
  TableContainer,
  TableHead,
  TableRow,
  TextField,
  Tooltip,
  Typography,
} from '@mui/material'
import { ErrorMessage, FormDialog, PanelDialog, Tag, useFormDirty } from './Common'
import { ImportDialog } from './ImportDialog'
import { useAuth } from '../context/AuthContext'
import { ApiError, api, body, downloadFile } from '../lib/api'
import { exportCsv, exportPdf, exportXlsx, parseImportFile, type ImportRow } from '../lib/export'
import { formatWatDate, formatWatDateTime, watTodayIso } from '../lib/time'
import {
  LINE_CHANGE_LABELS,
  ORDER_LINE_ITEM_EXPORT_COLUMNS,
  SINGLE_ORDER_LINE_ITEM_IMPORT_HEADERS,
  type OrderLineItem,
  type OrderLineItemBulkReviseResult,
  type OrderLineItemImportResult,
  type OrderLineItemRevision,
  type PoSoOrder,
} from '../lib/vendorMaster'

type CurrencyRow = {
  id: string
  currency_code: string
  currency_name: string
  currency_symbol: string
  is_default: boolean
}

const formatRate = (value: string | number | null | undefined) => {
  const num = Number(value ?? 0)
  return Number.isFinite(num)
    ? num.toLocaleString(undefined, { minimumFractionDigits: 3, maximumFractionDigits: 3 })
    : '0.000'
}

export function BulkOrderScheduleReviseDialog({
  open,
  order,
  onClose,
  onCompleted,
}: {
  open: boolean
  order?: PoSoOrder | null
  onClose: () => void
  onCompleted: (summary: string) => void
}) {
  const [rows, setRows] = useState<ImportRow[]>([])
  const [fileName, setFileName] = useState('')
  const [effectiveDate, setEffectiveDate] = useState(watTodayIso())
  const [reason, setReason] = useState('')
  const [allowNewItems, setAllowNewItems] = useState(false)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')
  const [rowErrors, setRowErrors] = useState<string[]>([])

  useEffect(() => {
    if (!open) return
    setRows([])
    setFileName('')
    setEffectiveDate(watTodayIso())
    setReason('')
    setAllowNewItems(false)
    setError('')
    setRowErrors([])
  }, [open])

  const dirty = Boolean(rows.length || reason.trim() || allowNewItems)

  const handleTemplate = async () => {
    setError('')
    try {
      const path = order
        ? `/master-data/po-so-orders/line-items/price-revision-template?order_id=${encodeURIComponent(order.id)}`
        : '/master-data/po-so-orders/line-items/price-revision-template'
      const fallback = order
        ? `${order.order_number}_Rev${order.revision_number}_schedule_rates.csv`
        : 'po_so_line_items_price_revision_template.csv'
      await downloadFile(path, fallback)
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : 'Could not download schedule revision template')
    }
  }

  const handleFile = async (file: File | undefined) => {
    if (!file) return
    setError('')
    setRowErrors([])
    try {
      const parsed = await parseImportFile(file)
      if (!parsed.rows.length) {
        setError('The selected spreadsheet contains no data rows.')
        setRows([])
        setFileName('')
        return
      }
      setRows(parsed.rows)
      setFileName(file.name)
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : 'Could not read spreadsheet')
      setRows([])
      setFileName('')
    }
  }

  const submit = async () => {
    if (!rows.length) {
      setError('Choose a populated CSV or XLSX schedule file first.')
      return
    }
    if (reason.trim().length < 3) {
      setError('Enter a reason of at least 3 characters for this bulk schedule revision.')
      return
    }
    setBusy(true)
    setError('')
    setRowErrors([])
    try {
      const endpoint = order
        ? `/master-data/po-so-orders/${order.id}/line-items/bulk-revise`
        : '/master-data/po-so-orders/line-items/bulk-revise'
      const result = await api<OrderLineItemBulkReviseResult>(endpoint, {
        method: 'POST',
        body: body({
          rows,
          reason: reason.trim(),
          effective_date: effectiveDate || null,
          allow_new_items: allowNewItems,
        }),
      })
      const summary = [
        `${result.revised_count} revised`,
        result.added_count ? `${result.added_count} added` : '',
        result.unchanged_count ? `${result.unchanged_count} unchanged` : '',
        result.skipped_count ? `${result.skipped_count} blank skipped` : '',
      ]
        .filter(Boolean)
        .join(', ')
      onCompleted(`Bulk schedule rate revision applied (${summary}).`)
      onClose()
    } catch (caught) {
      if (caught instanceof ApiError) {
        setError(caught.message)
        setRowErrors(caught.details.length > 1 ? caught.details : [])
      } else {
        setError(caught instanceof Error ? caught.message : 'Bulk schedule revision failed')
      }
    } finally {
      setBusy(false)
    }
  }

  return (
    <FormDialog
      open={open}
      title={order ? `Bulk revise rates · ${order.order_number} (Rev ${order.revision_number})` : 'Bulk revise PO/SO schedule rates'}
      subtitle="All-or-nothing atomic rate amendment. Download the active schedule CSV, fill in new_unit_rate (and optional new_currency or description), then upload."
      onClose={() => { if (!busy) onClose() }}
      onSubmit={() => void submit()}
      busy={busy}
      dirty={dirty}
      maxWidth="md"
      submitLabel="Apply bulk revision"
    >
      <Stack gap={2} pt={0.5}>
        <Stack direction={{ xs: 'column', sm: 'row' }} gap={1.25} alignItems={{ sm: 'center' }} justifyContent="space-between">
          <Button variant="outlined" startIcon={<DownloadRounded />} onClick={() => void handleTemplate()}>
            Download current schedule CSV
          </Button>
          <Button component="label" variant="outlined" startIcon={<FileUploadOutlined />}>
            {fileName ? `Replace file (${fileName})` : 'Choose .xlsx or .csv file'}
            <input
              hidden
              type="file"
              accept=".xlsx,.csv"
              onChange={event => {
                void handleFile(event.target.files?.[0])
                event.target.value = ''
              }}
            />
          </Button>
        </Stack>

        {rows.length > 0 && (
          <Alert severity="info">
            Loaded <strong>{rows.length}</strong> schedule row{rows.length === 1 ? '' : 's'} from <strong>{fileName}</strong>. Rows with blank <code>new_unit_rate</code> are skipped untouched.
          </Alert>
        )}

        <Box display="grid" gap={2} gridTemplateColumns={{ xs: '1fr', sm: '200px 1fr' }}>
          <TextField
            label="Default effective date"
            type="date"
            value={effectiveDate}
            onChange={event => setEffectiveDate(event.target.value)}
            InputLabelProps={{ shrink: true }}
          />
          <TextField
            label="Amendment reason"
            required
            value={reason}
            onChange={event => setReason(event.target.value)}
            helperText="Recorded on every amended line item's revision history"
            inputProps={{ maxLength: 500 }}
          />
        </Box>

        <FormControlLabel
          control={<Checkbox checked={allowNewItems} onChange={event => setAllowNewItems(event.target.checked)} />}
          label={<Typography fontSize={13}>Allow adding new schedule line items present in the uploaded file</Typography>}
        />

        <ErrorMessage message={error} />
        {rowErrors.length > 0 && (
          <Paper variant="outlined" sx={{ p: 1.5, maxHeight: 200, overflowY: 'auto', bgcolor: 'background.default' }}>
            <Typography fontSize={12} fontWeight={700} color="error.main" mb={0.75}>
              Row validation issues (no changes were committed):
            </Typography>
            <Stack gap={0.4}>
              {rowErrors.map((msg, idx) => (
                <Typography key={idx} fontSize={12} color="text.secondary">
                  • {msg}
                </Typography>
              ))}
            </Stack>
          </Paper>
        )}
      </Stack>
    </FormDialog>
  )
}

type LineFormState = {
  line_item_code: string
  vendor_code: string
  description: string
  unit_rate: string
  currency: string
  effective_date: string
  sort_order: string
  reason: string
}

const emptyLineForm = (defaultCurrency: string, issueDate: string | null): LineFormState => ({
  line_item_code: '',
  vendor_code: '',
  description: '',
  unit_rate: '',
  currency: defaultCurrency || 'USD',
  effective_date: issueDate || watTodayIso(),
  sort_order: '',
  reason: '',
})

export function OrderLineItemsDialog({
  open,
  order,
  onClose,
  onChanged,
}: {
  open: boolean
  order: PoSoOrder | null
  onClose: () => void
  onChanged: () => void
}) {
  const { can } = useAuth()
  const [items, setItems] = useState<OrderLineItem[]>([])
  const [currencies, setCurrencies] = useState<CurrencyRow[]>([])
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState('')
  const [notice, setNotice] = useState('')
  const [search, setSearch] = useState('')
  const [showDeleted, setShowDeleted] = useState(false)
  const [exportAnchor, setExportAnchor] = useState<HTMLElement | null>(null)

  const [editorMode, setEditorMode] = useState<'create' | 'edit' | 'amend' | null>(null)
  const [activeItem, setActiveItem] = useState<OrderLineItem | null>(null)
  const [form, setForm] = useState<LineFormState>(() => emptyLineForm('USD', null))
  const [formBusy, setFormBusy] = useState(false)
  const [formError, setFormError] = useState('')

  const [historyItem, setHistoryItem] = useState<OrderLineItem | null>(null)
  const [revisions, setRevisions] = useState<OrderLineItemRevision[]>([])
  const [historyLoading, setHistoryLoading] = useState(false)

  const [importOpen, setImportOpen] = useState(false)
  const [bulkReviseOpen, setBulkReviseOpen] = useState(false)
  const [purgeTarget, setPurgeTarget] = useState<OrderLineItem | null>(null)
  const [purgeBusy, setPurgeBusy] = useState(false)
  const [purgeError, setPurgeError] = useState('')

  const defaultCurrency = useMemo(
    () => currencies.find(c => c.is_default)?.currency_code || currencies[0]?.currency_code || 'USD',
    [currencies],
  )

  const load = useCallback(async () => {
    if (!order) return
    setLoading(true)
    setError('')
    try {
      const [lineRows, ccyRows] = await Promise.all([
        api<OrderLineItem[]>(
          `/master-data/po-so-orders/${order.id}/line-items?include_deleted=${showDeleted ? 'true' : 'false'}`,
        ),
        api<CurrencyRow[]>('/master-data/currencies').catch(() => []),
      ])
      setItems(lineRows)
      setCurrencies(ccyRows)
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : 'Could not load PO/SO schedule line items')
    } finally {
      setLoading(false)
    }
  }, [order, showDeleted])

  useEffect(() => {
    if (!open || !order) return
    setSearch('')
    setNotice('')
    void load()
  }, [open, order, load])

  const filtered = useMemo(() => {
    const q = search.trim().toLowerCase()
    if (!q) return items
    return items.filter(
      item =>
        item.line_item_code.toLowerCase().includes(q) ||
        item.vendor_code.toLowerCase().includes(q) ||
        item.description.toLowerCase().includes(q) ||
        item.currency.toLowerCase().includes(q),
    )
  }, [items, search])

  const openCreate = () => {
    setActiveItem(null)
    setForm(emptyLineForm(defaultCurrency, order?.issue_date ?? null))
    setFormError('')
    setEditorMode('create')
  }

  const openEdit = (item: OrderLineItem) => {
    setActiveItem(item)
    setForm({
      line_item_code: item.line_item_code,
      vendor_code: item.vendor_code,
      description: item.description,
      unit_rate: Number(item.unit_rate || 0).toFixed(3),
      currency: item.currency,
      effective_date: item.effective_date || watTodayIso(),
      sort_order: String(item.sort_order),
      reason: '',
    })
    setFormError('')
    setEditorMode('edit')
  }

  const openAmend = (item: OrderLineItem) => {
    setActiveItem(item)
    setForm({
      line_item_code: item.line_item_code,
      vendor_code: item.vendor_code,
      description: item.description,
      unit_rate: Number(item.unit_rate || 0).toFixed(3),
      currency: item.currency,
      effective_date: watTodayIso(),
      sort_order: String(item.sort_order),
      reason: '',
    })
    setFormError('')
    setEditorMode('amend')
  }

  const formDirty = useFormDirty(form, editorMode !== null)

  const saveForm = async () => {
    if (!order || !editorMode) return
    setFormBusy(true)
    setFormError('')
    try {
      if (editorMode === 'create') {
        await api<OrderLineItem>(`/master-data/po-so-orders/${order.id}/line-items`, {
          method: 'POST',
          body: body({
            line_item_code: form.line_item_code.trim(),
            vendor_code: form.vendor_code.trim(),
            description: form.description.trim(),
            unit_rate: form.unit_rate.trim(),
            currency: form.currency.trim(),
            effective_date: form.effective_date || null,
            sort_order: form.sort_order.trim() ? Number(form.sort_order) : null,
          }),
        })
        setNotice(`Line item ${form.line_item_code.trim().toUpperCase()} added to ${order.order_number}.`)
      } else if (editorMode === 'edit' && activeItem) {
        await api<OrderLineItem>(`/master-data/po-so-orders/line-items/${activeItem.id}`, {
          method: 'PATCH',
          body: body({
            line_item_code: form.line_item_code.trim(),
            vendor_code: form.vendor_code.trim(),
            description: form.description.trim(),
            sort_order: form.sort_order.trim() ? Number(form.sort_order) : activeItem.sort_order,
          }),
        })
        setNotice(`Line item ${form.line_item_code.trim().toUpperCase()} updated.`)
      } else if (editorMode === 'amend' && activeItem) {
        const updated = await api<OrderLineItem>(`/master-data/po-so-orders/line-items/${activeItem.id}/amend`, {
          method: 'POST',
          body: body({
            unit_rate: form.unit_rate.trim(),
            currency: form.currency.trim(),
            vendor_code: form.vendor_code.trim(),
            description: form.description.trim(),
            effective_date: form.effective_date || null,
            reason: form.reason.trim(),
          }),
        })
        setNotice(`Line item ${updated.line_item_code} amended to revision ${updated.current_revision_number}.`)
      }
      setEditorMode(null)
      await load()
      onChanged()
    } catch (caught) {
      setFormError(caught instanceof Error ? caught.message : 'Could not save line item')
    } finally {
      setFormBusy(false)
    }
  }

  const openHistory = async (item: OrderLineItem) => {
    setHistoryItem(item)
    setRevisions([])
    setHistoryLoading(true)
    try {
      setRevisions(await api<OrderLineItemRevision[]>(`/master-data/po-so-orders/line-items/${item.id}/revisions`))
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : 'Could not load line item revision history')
    } finally {
      setHistoryLoading(false)
    }
  }

  const softDelete = async (item: OrderLineItem) => {
    setError('')
    try {
      await api(`/master-data/po-so-orders/line-items/${item.id}`, { method: 'DELETE' })
      setNotice(`Line item ${item.line_item_code} moved to removed items.`)
      await load()
      onChanged()
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : 'Could not remove line item')
    }
  }

  const restore = async (item: OrderLineItem) => {
    setError('')
    try {
      await api(`/master-data/po-so-orders/line-items/${item.id}/restore`, { method: 'POST' })
      setNotice(`Line item ${item.line_item_code} restored.`)
      await load()
      onChanged()
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : 'Could not restore line item')
    }
  }

  const confirmPurge = async () => {
    if (!purgeTarget) return
    setPurgeBusy(true)
    setPurgeError('')
    try {
      await api(`/master-data/po-so-orders/line-items/${purgeTarget.id}/permanent`, { method: 'DELETE' })
      setNotice(`Line item ${purgeTarget.line_item_code} permanently deleted.`)
      setPurgeTarget(null)
      await load()
      onChanged()
    } catch (caught) {
      setPurgeError(caught instanceof Error ? caught.message : 'Could not permanently delete line item')
    } finally {
      setPurgeBusy(false)
    }
  }

  const handleImportRows = async (importedRows: ImportRow[]): Promise<string[]> => {
    if (!order) return []
    const result = await api<OrderLineItemImportResult>(`/master-data/po-so-orders/${order.id}/line-items/import`, {
      method: 'POST',
      body: body({ rows: importedRows }),
    })
    await load()
    onChanged()
    if (result.imported_count || result.unchanged_count) {
      setNotice(
        `Schedule import finished: ${result.created_count} created, ${result.revised_count} amended, ${result.unchanged_count} unchanged.`,
      )
    }
    if (!result.error_count) return []
    return [
      `Processed ${result.imported_count} of ${importedRows.length} rows. Resolve the issues below and re-import failed rows.`,
      ...result.errors,
    ]
  }

  const runExport = async (format: 'csv' | 'xlsx' | 'pdf') => {
    if (!order) return
    setExportAnchor(null)
    const stem = `${order.order_number}-rev-${order.revision_number}-line-items`
    const title = `${order.order_type} ${order.order_number} (Rev ${order.revision_number}) — Schedule Line Items`
    if (format === 'csv') exportCsv(`${stem}.csv`, filtered, ORDER_LINE_ITEM_EXPORT_COLUMNS)
    else if (format === 'xlsx') await exportXlsx(`${stem}.xlsx`, filtered, ORDER_LINE_ITEM_EXPORT_COLUMNS)
    else await exportPdf(`${stem}.pdf`, title, filtered, ORDER_LINE_ITEM_EXPORT_COLUMNS)
    await api('/master-data/export-audit', {
      method: 'POST',
      body: body({ module: 'po-so-orders', format, record_count: filtered.length, include_deleted: showDeleted }),
    }).catch(() => undefined)
  }

  if (!order) return null

  return (
    <>
      <PanelDialog
        open={open}
        title={`Schedule line items · ${order.order_type} ${order.order_number} (Rev ${order.revision_number})`}
        subtitle={`${order.vendor_code} — ${order.vendor_name} · Maintain contracted unit rates, optional vendor codes, bulk imports/exports, and audited rate amendments.`}
        onClose={onClose}
        maxWidth="lg"
      >
        <Stack gap={2}>
          <Stack direction={{ xs: 'column', md: 'row' }} gap={1.25} justifyContent="space-between" alignItems={{ md: 'center' }} flexWrap="wrap">
            <Stack direction="row" gap={1.25} alignItems="center" flexWrap="wrap">
              <TextField
                size="small"
                placeholder="Search code, vendor code, description…"
                value={search}
                onChange={event => setSearch(event.target.value)}
                sx={{ minWidth: 260 }}
              />
              <FormControlLabel
                control={<Checkbox checked={showDeleted} onChange={event => setShowDeleted(event.target.checked)} />}
                label={<Typography fontSize={12.5}>Show removed</Typography>}
              />
            </Stack>

            <Stack direction="row" gap={1} flexWrap="wrap">
              {can('master-data:export') && (
                <Button
                  size="small"
                  variant="outlined"
                  startIcon={<FileDownloadOutlined />}
                  disabled={!filtered.length}
                  onClick={event => setExportAnchor(event.currentTarget)}
                >
                  Export
                </Button>
              )}
              {can('master-data:import') && !order.is_deleted && (
                <>
                  <Button size="small" variant="outlined" startIcon={<FileUploadOutlined />} onClick={() => setImportOpen(true)}>
                    Import schedule
                  </Button>
                  <Button size="small" variant="outlined" startIcon={<PriceChangeOutlined />} onClick={() => setBulkReviseOpen(true)}>
                    Bulk revise rates
                  </Button>
                </>
              )}
              {can('master-data:create') && !order.is_deleted && (
                <Button size="small" variant="contained" startIcon={<AddRounded />} onClick={openCreate}>
                  Add line item
                </Button>
              )}
            </Stack>
          </Stack>

          <Menu anchorEl={exportAnchor} open={Boolean(exportAnchor)} onClose={() => setExportAnchor(null)}>
            <MenuItem onClick={() => void runExport('xlsx')}>Excel (.xlsx)</MenuItem>
            <MenuItem onClick={() => void runExport('csv')}>CSV (.csv)</MenuItem>
            <MenuItem onClick={() => void runExport('pdf')}>PDF (.pdf)</MenuItem>
          </Menu>

          {notice && <Alert severity="success" onClose={() => setNotice('')}>{notice}</Alert>}
          <ErrorMessage message={error} />

          {loading ? (
            <Box py={6} display="grid" sx={{ placeItems: 'center' }}>
              <CircularProgress size={26} />
            </Box>
          ) : (
            <TableContainer component={Paper} variant="outlined" sx={{ maxHeight: 480 }}>
              <Table stickyHeader size="small">
                <TableHead>
                  <TableRow>
                    <TableCell sx={{ width: 60 }}>#</TableCell>
                    <TableCell sx={{ minWidth: 130 }}>Line Code</TableCell>
                    <TableCell sx={{ minWidth: 120 }}>Vendor Code</TableCell>
                    <TableCell sx={{ minWidth: 260 }}>Description</TableCell>
                    <TableCell align="right" sx={{ minWidth: 140 }}>Unit Rate</TableCell>
                    <TableCell sx={{ minWidth: 95 }}>Revision</TableCell>
                    <TableCell sx={{ minWidth: 115 }}>Effective</TableCell>
                    <TableCell align="right" sx={{ minWidth: 165 }}>Actions</TableCell>
                  </TableRow>
                </TableHead>
                <TableBody>
                  {filtered.map(item => (
                    <TableRow key={item.id} hover sx={{ opacity: item.is_deleted ? 0.62 : 1 }}>
                      <TableCell sx={{ fontVariantNumeric: 'tabular-nums', color: 'text.secondary' }}>{item.sort_order}</TableCell>
                      <TableCell>
                        <Stack direction="row" gap={0.75} alignItems="center">
                          <Typography fontSize={12.5} fontWeight={700} fontFamily="monospace">
                            {item.line_item_code}
                          </Typography>
                          {item.is_deleted && <Tag tone="warning">Removed</Tag>}
                        </Stack>
                      </TableCell>
                      <TableCell>
                        <Typography fontSize={12.5} color={item.vendor_code ? 'text.primary' : 'text.secondary'}>
                          {item.vendor_code || '—'}
                        </Typography>
                      </TableCell>
                      <TableCell>
                        <Typography fontSize={12.5} sx={{ whiteSpace: 'pre-wrap' }}>
                          {item.description}
                        </Typography>
                      </TableCell>
                      <TableCell align="right" sx={{ fontVariantNumeric: 'tabular-nums', fontWeight: 700 }}>
                        {item.currency} {formatRate(item.unit_rate)}
                      </TableCell>
                      <TableCell>
                        <Chip
                          size="small"
                          label={`Rev ${item.current_revision_number}`}
                          color={item.current_revision_number > 1 ? 'primary' : 'default'}
                          variant="outlined"
                          onClick={() => void openHistory(item)}
                          sx={{ height: 22, fontSize: 11, cursor: 'pointer' }}
                        />
                      </TableCell>
                      <TableCell sx={{ fontSize: 12 }}>
                        {item.effective_date ? formatWatDate(item.effective_date) : '—'}
                      </TableCell>
                      <TableCell align="right">
                        <Stack direction="row" justifyContent="flex-end" gap={0.25}>
                          <Tooltip title="Revision history">
                            <IconButton size="small" onClick={() => void openHistory(item)}>
                              <HistoryOutlined fontSize="small" />
                            </IconButton>
                          </Tooltip>
                          {!item.is_deleted && can('master-data:update') && (
                            <>
                              <Tooltip title="Amend rate / schedule details">
                                <IconButton size="small" color="primary" onClick={() => openAmend(item)}>
                                  <PriceChangeOutlined fontSize="small" />
                                </IconButton>
                              </Tooltip>
                              <Tooltip title="Edit code / description">
                                <IconButton size="small" onClick={() => openEdit(item)}>
                                  <EditOutlined fontSize="small" />
                                </IconButton>
                              </Tooltip>
                            </>
                          )}
                          {!item.is_deleted && can('master-data:delete') && (
                            <Tooltip title="Remove line item">
                              <IconButton size="small" color="error" onClick={() => void softDelete(item)}>
                                <DeleteOutlineRounded fontSize="small" />
                              </IconButton>
                            </Tooltip>
                          )}
                          {item.is_deleted && can('master-data:restore') && (
                            <Tooltip title="Restore line item">
                              <IconButton size="small" color="success" onClick={() => void restore(item)}>
                                <RestoreFromTrashRounded fontSize="small" />
                              </IconButton>
                            </Tooltip>
                          )}
                          {item.is_deleted && can('master-data:permanent-delete') && (
                            <Tooltip title="Delete permanently">
                              <IconButton size="small" color="error" onClick={() => { setPurgeTarget(item); setPurgeError('') }}>
                                <DeleteForeverRounded fontSize="small" />
                              </IconButton>
                            </Tooltip>
                          )}
                        </Stack>
                      </TableCell>
                    </TableRow>
                  ))}
                  {!filtered.length && (
                    <TableRow>
                      <TableCell colSpan={8} align="center">
                        <Typography color="text.secondary" py={4} fontSize={13}>
                          {items.length
                            ? 'No schedule line items match your search.'
                            : 'No schedule line items recorded on this PO/SO revision yet. Add items manually or import a schedule spreadsheet.'}
                        </Typography>
                      </TableCell>
                    </TableRow>
                  )}
                </TableBody>
              </Table>
            </TableContainer>
          )}
        </Stack>
      </PanelDialog>

      <FormDialog
        open={editorMode !== null}
        title={
          editorMode === 'create'
            ? `Add schedule line item · ${order.order_number}`
            : editorMode === 'amend'
              ? `Amend line item · ${activeItem?.line_item_code ?? ''}`
              : `Edit line item · ${activeItem?.line_item_code ?? ''}`
        }
        subtitle={
          editorMode === 'amend'
            ? 'Records a new append-only rate/schedule revision with previous values, effective date and reason.'
            : editorMode === 'edit'
              ? 'Corrects non-price metadata. Use Amend rate / schedule details to revise unit rate or currency.'
              : 'Defines a contracted schedule item available for optional IDVS line selection.'
        }
        onClose={() => { if (!formBusy) setEditorMode(null) }}
        onSubmit={() => void saveForm()}
        busy={formBusy}
        dirty={formDirty}
        submitLabel={editorMode === 'create' ? 'Add line item' : editorMode === 'amend' ? 'Record amendment' : 'Save changes'}
      >
        <Stack gap={2} pt={0.5}>
          <Box display="grid" gap={2} gridTemplateColumns={{ xs: '1fr', sm: '1fr 1fr 110px' }}>
            <TextField
              label="Line item code"
              required
              disabled={editorMode === 'amend'}
              value={form.line_item_code}
              onChange={event => setForm(curr => ({ ...curr, line_item_code: event.target.value }))}
              inputProps={{ maxLength: 80 }}
              helperText="Unique within this PO/SO revision"
            />
            <TextField
              label="Vendor code (optional)"
              value={form.vendor_code}
              onChange={event => setForm(curr => ({ ...curr, vendor_code: event.target.value }))}
              inputProps={{ maxLength: 80 }}
              helperText="Supplier catalogue / part reference"
            />
            <TextField
              label="Sort #"
              type="number"
              disabled={editorMode === 'amend'}
              value={form.sort_order}
              onChange={event => setForm(curr => ({ ...curr, sort_order: event.target.value }))}
              inputProps={{ min: 1, max: 100000 }}
            />
          </Box>

          <TextField
            label="Description"
            required
            multiline
            minRows={2}
            value={form.description}
            onChange={event => setForm(curr => ({ ...curr, description: event.target.value }))}
            inputProps={{ maxLength: 2000 }}
          />

          {editorMode !== 'edit' && (
            <Box display="grid" gap={2} gridTemplateColumns={{ xs: '1fr', sm: '1fr 150px 170px' }}>
              <TextField
                label="Unit rate"
                required
                type="number"
                value={form.unit_rate}
                onChange={event => setForm(curr => ({ ...curr, unit_rate: event.target.value }))}
                inputProps={{ min: 0, step: '0.001' }}
                helperText="Stored to 3 decimal places"
              />
              {currencies.length > 0 ? (
                <TextField
                  select
                  label="Currency"
                  required
                  value={form.currency}
                  onChange={event => setForm(curr => ({ ...curr, currency: event.target.value }))}
                >
                  {currencies.map(ccy => (
                    <MenuItem key={ccy.currency_code} value={ccy.currency_code}>
                      {ccy.currency_code}
                    </MenuItem>
                  ))}
                </TextField>
              ) : (
                <TextField
                  label="Currency"
                  required
                  value={form.currency}
                  onChange={event => setForm(curr => ({ ...curr, currency: event.target.value.toUpperCase() }))}
                  inputProps={{ maxLength: 10 }}
                />
              )}
              <TextField
                label="Effective date"
                type="date"
                value={form.effective_date}
                onChange={event => setForm(curr => ({ ...curr, effective_date: event.target.value }))}
                InputLabelProps={{ shrink: true }}
              />
            </Box>
          )}

          {editorMode === 'amend' && (
            <TextField
              label="Reason for amendment"
              required
              multiline
              minRows={2}
              value={form.reason}
              onChange={event => setForm(curr => ({ ...curr, reason: event.target.value }))}
              helperText="Minimum 3 characters; preserved in the append-only revision log"
              inputProps={{ maxLength: 500 }}
            />
          )}

          <ErrorMessage message={formError} />
        </Stack>
      </FormDialog>

      <PanelDialog
        open={Boolean(historyItem)}
        title={`Revision history · ${historyItem?.line_item_code ?? ''}`}
        subtitle={historyItem ? `${order.order_type} ${order.order_number} (Rev ${order.revision_number}) · ${historyItem.description}` : ''}
        onClose={() => setHistoryItem(null)}
        maxWidth="md"
      >
        {historyLoading ? (
          <Box py={5} display="grid" sx={{ placeItems: 'center' }}>
            <CircularProgress size={24} />
          </Box>
        ) : (
          <TableContainer component={Paper} variant="outlined">
            <Table size="small">
              <TableHead>
                <TableRow>
                  <TableCell>Rev</TableCell>
                  <TableCell>Type</TableCell>
                  <TableCell align="right">Previous Rate</TableCell>
                  <TableCell align="right">Amended Rate</TableCell>
                  <TableCell>Effective Date</TableCell>
                  <TableCell>Reason & Details</TableCell>
                  <TableCell>Recorded</TableCell>
                </TableRow>
              </TableHead>
              <TableBody>
                {revisions.map(rev => (
                  <TableRow key={rev.id}>
                    <TableCell sx={{ fontWeight: 700 }}>Rev {rev.revision_number}</TableCell>
                    <TableCell>
                      <Tag tone={rev.change_type === 'price_revision' ? 'info' : 'neutral'}>
                        {LINE_CHANGE_LABELS[rev.change_type] ?? rev.change_type}
                      </Tag>
                    </TableCell>
                    <TableCell align="right" sx={{ fontVariantNumeric: 'tabular-nums', color: 'text.secondary' }}>
                      {rev.revision_number === 1
                        ? '—'
                        : `${rev.previous_currency} ${formatRate(rev.previous_unit_rate)}`}
                    </TableCell>
                    <TableCell align="right" sx={{ fontVariantNumeric: 'tabular-nums', fontWeight: 700 }}>
                      {rev.currency} {formatRate(rev.unit_rate)}
                    </TableCell>
                    <TableCell>{formatWatDate(rev.effective_date)}</TableCell>
                    <TableCell>
                      <Typography fontSize={12.5}>{rev.reason || '—'}</Typography>
                      {rev.previous_description && rev.previous_description !== rev.description && (
                        <Typography variant="caption" color="text.secondary" display="block">
                          Description updated from “{rev.previous_description}”
                        </Typography>
                      )}
                    </TableCell>
                    <TableCell>
                      <Typography fontSize={11.5}>{rev.recorded_by || '—'}</Typography>
                      <Typography variant="caption" color="text.secondary" display="block">
                        {formatWatDateTime(rev.created_at)}
                      </Typography>
                    </TableCell>
                  </TableRow>
                ))}
                {!revisions.length && (
                  <TableRow>
                    <TableCell colSpan={7} align="center">
                      <Typography color="text.secondary" py={3}>
                        No revision entries found.
                      </Typography>
                    </TableCell>
                  </TableRow>
                )}
              </TableBody>
            </Table>
          </TableContainer>
        )}
      </PanelDialog>

      <ImportDialog
        open={importOpen}
        onClose={() => setImportOpen(false)}
        title={`Import schedule line items · ${order.order_number} (Rev ${order.revision_number})`}
        subtitle="Creates new schedule line items or amends existing codes on this PO/SO revision. Existing line items whose rate or description changes automatically receive an audited revision."
        headers={SINGLE_ORDER_LINE_ITEM_IMPORT_HEADERS}
        sample={{
          line_item_code: 'ITEM-001',
          vendor_code: 'CAT-9001',
          description: '9-5/8 in. Rental Packer Assembly — Daily Operating Rate',
          unit_rate: '1250.000',
          currency: defaultCurrency,
          effective_date: order.issue_date || watTodayIso(),
          reason: 'Contract schedule import',
        }}
        templateName={`${order.order_number.toLowerCase()}-line-items-template.csv`}
        onRows={handleImportRows}
      />

      <BulkOrderScheduleReviseDialog
        open={bulkReviseOpen}
        order={order}
        onClose={() => setBulkReviseOpen(false)}
        onCompleted={msg => {
          setNotice(msg)
          void load()
          onChanged()
        }}
      />

      <FormDialog
        open={Boolean(purgeTarget)}
        title="Permanently delete schedule line item?"
        subtitle="This permanently removes the line item and its rate history. Line items referenced by an IDVS cannot be purged."
        onClose={() => { if (!purgeBusy) setPurgeTarget(null) }}
        onSubmit={() => void confirmPurge()}
        busy={purgeBusy}
        danger
        submitLabel="Delete permanently"
      >
        <Stack gap={1.5} pt={0.5}>
          <Typography fontSize={13}>
            <strong>{purgeTarget?.line_item_code}</strong> — {purgeTarget?.description}
          </Typography>
          <ErrorMessage message={purgeError} />
        </Stack>
      </FormDialog>
    </>
  )
}
