import { useCallback, useEffect, useMemo, useState } from 'react'
import { useNavigate, useSearchParams } from 'react-router-dom'
import { Add, ArrowForward, DeleteForever, DeleteOutline, EditOutlined, MoreTime, PaymentOutlined, Refresh, RestoreFromTrash, SettingsOutlined, Upload, VisibilityOutlined } from '@mui/icons-material'
import { Alert, Box, Button, IconButton, MenuItem, Paper, Stack, TextField, Tooltip, Typography } from '@mui/material'
import type { ColDef, ICellRendererParams } from 'ag-grid-community'
import { FormDialog, PageHeading, Tag } from '../components/Common'
import { DataTable } from '../components/DataTable'
import { ImportDialog } from '../components/ImportDialog'
import { useAuth } from '../context/AuthContext'
import { api, body } from '../lib/api'
import type { ImportRow } from '../lib/export'
import { formatAmount, formatDate } from '../lib/invoiceCalculations'
import { INVOICE_IMPORT_HEADERS, INVOICE_IMPORT_OPTIONAL, INVOICE_IMPORT_SAMPLE, INVOICE_STATUS_LABEL, WORKFLOW_ACTION, importInvoiceRow, type Invoice, type InvoiceImportResult, type InvoiceReference, type WorkflowAction } from '../lib/invoiceProcessing'

const statusTone = (status: string): 'neutral' | 'success' | 'info' | 'warning' => status === 'paid' || status === 'approved' ? 'success' : status === 'submitted' || status === 'sent_to_accounts' ? 'info' : status === 'epicor_pending' ? 'warning' : 'neutral'
const today = () => new Date().toISOString().slice(0, 10)

export default function InvoiceRegister({ deletedView = false }: { deletedView?: boolean }) {
  const navigate = useNavigate()
  const [searchParams] = useSearchParams()
  const { can } = useAuth()
  const [rows, setRows] = useState<Invoice[]>([])
  const [reference, setReference] = useState<InvoiceReference | null>(null)
  const [showDeleted, setShowDeleted] = useState(deletedView)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState('')
  const [notice, setNotice] = useState('')
  const [vendor, setVendor] = useState('')
  const [status, setStatus] = useState(searchParams.get('status') ?? '')
  const [block, setBlock] = useState('')
  const [currency, setCurrency] = useState('')
  const [location, setLocation] = useState('')
  const [dateField, setDateField] = useState('invoice_date')
  const [dateFrom, setDateFrom] = useState('')
  const [dateTo, setDateTo] = useState('')
  const [overdue, setOverdue] = useState(searchParams.get('overdue') === 'true')
  const [selected, setSelected] = useState<Invoice[]>([])
  const [importOpen, setImportOpen] = useState(false)
  const [busy, setBusy] = useState(false)
  const [confirm, setConfirm] = useState<{ kind: 'delete' | 'restore' | 'purge'; ids: string[] } | null>(null)
  const [workflow, setWorkflow] = useState<{ rows: Invoice[]; action: WorkflowAction | 'payment' } | null>(null)
  const [actionDate, setActionDate] = useState(today())
  const [actionRemarks, setActionRemarks] = useState('')
  const [paymentReference, setPaymentReference] = useState('')

  const query = useMemo(() => {
    const params = new URLSearchParams()
    if (vendor) params.set('vendor_id', vendor); if (status) params.set('status', status)
    if (block) params.set('block_id', block); if (currency) params.set('currency_code', currency)
    if (location) params.set('location_id', location); if (dateFrom) params.set('from', dateFrom)
    if (dateTo) params.set('to', dateTo); params.set('date_field', dateField)
    if (overdue) params.set('overdue', 'true')
    return `?${params}`
  }, [vendor, status, block, currency, location, dateField, dateFrom, dateTo, overdue])
  const load = useCallback(async () => {
    setLoading(true); setError(''); setSelected([])
    try {
      const [invoices, refs] = await Promise.all([
        api<Invoice[]>(`/invoice-processing/invoices${showDeleted ? '/deleted' : ''}${query}`),
        reference ? Promise.resolve(reference) : api<InvoiceReference>('/invoice-processing/reference'),
      ])
      setRows(invoices); setReference(refs)
    } catch (caught) { setError((caught as Error).message) }
    finally { setLoading(false) }
  }, [query, showDeleted]) // reference is deliberately loaded once per workspace page instance
  useEffect(() => { void load() }, [load])
  useEffect(() => { setShowDeleted(deletedView) }, [deletedView])
  const resetFilters = () => { setVendor(''); setStatus(''); setBlock(''); setCurrency(''); setLocation(''); setDateFrom(''); setDateTo(''); setOverdue(false); setDateField('invoice_date') }
  const filterActive = Boolean(vendor || status || block || currency || location || dateFrom || dateTo || overdue)
  const openWorkflow = (targets: Invoice[], action: WorkflowAction | 'payment') => {
    setWorkflow({ rows: targets, action }); setActionDate(today()); setActionRemarks(''); setPaymentReference(''); setError('')
  }
  const runWorkflow = async () => {
    if (!workflow) return
    setBusy(true); setError('')
    const failures: string[] = []
    try {
      for (const row of workflow.rows) {
        try {
          if (workflow.action === 'payment') await api(`/invoice-processing/invoices/${row.id}/payment`, { method: 'POST', body: body({ paid_date: actionDate, payment_reference: paymentReference, remarks: actionRemarks }) })
          else await api(`/invoice-processing/invoices/${row.id}/workflow`, { method: 'POST', body: body({ action: workflow.action, action_date: actionDate, remarks: actionRemarks }) })
        } catch (caught) { failures.push(`${row.idvs_number}: ${(caught as Error).message}`) }
      }
      if (failures.length) setError(failures.join(' · '))
      else setNotice(`${workflow.rows.length} IDVS record(s) updated.`)
      setWorkflow(null); await load()
    } finally { setBusy(false) }
  }
  const runLifecycle = async () => {
    if (!confirm) return
    setBusy(true); setError('')
    const endpoint = confirm.kind === 'delete' ? 'bulk-delete' : confirm.kind === 'restore' ? 'bulk-restore' : 'bulk-permanent-delete'
    try {
      await api(`/invoice-processing/invoices/${endpoint}`, { method: 'POST', body: body({ ids: confirm.ids }) })
      setNotice(confirm.kind === 'restore' ? 'Selected IDVS records restored.' : confirm.kind === 'purge' ? 'Selected records permanently deleted.' : 'Selected IDVS records moved to Deleted Entries.')
      setConfirm(null); await load()
    } catch (caught) { setError((caught as Error).message) }
    finally { setBusy(false) }
  }
  const importRows = async (source: ImportRow[]) => {
    if (source.length > 5000) return ['At most 5,000 spreadsheet rows can be imported at once. Split the file and retry.']
    const result = await api<InvoiceImportResult>('/invoice-processing/import', { method: 'POST', body: body({ rows: source.map(importInvoiceRow) }) })
    if (result.success) { setNotice(`${result.invoice_count} IDVS record(s) created or refreshed from ${result.imported_count} line(s).`); await load() }
    return result.errors
  }
  const selectedStatus = selected.length && selected.every(row => row.status === selected[0].status && !row.paid_date) ? selected[0].status : null
  const selectedAction = selectedStatus ? WORKFLOW_ACTION[selectedStatus] : undefined
  const canBulkPayment = Boolean(selected.length && selected.every(row => row.status === 'approved' && !row.paid_date))

  const columns = useMemo<ColDef<Invoice>[]>(() => [
    { headerName: 'IDVS', field: 'idvs_number', minWidth: 155, cellRenderer: (p: ICellRendererParams<Invoice>) => <Box height="100%" display="flex" flexDirection="column" justifyContent="center"><Typography fontSize={12} fontWeight={750}>{p.value}</Typography><Typography fontSize={10} color="text.secondary">{formatDate(p.data?.idvs_date)}</Typography></Box> },
    { headerName: 'INVOICE', field: 'invoice_number', minWidth: 145 }, { headerName: 'INVOICE DATE', field: 'invoice_date', minWidth: 125, valueFormatter: p => formatDate(p.value) },
    { headerName: 'VENDOR', field: 'vendor_name', minWidth: 215, flex: 1 }, { headerName: 'PO / SO', field: 'order_number', minWidth: 125 },
    { headerName: 'BLOCK', field: 'block_code', minWidth: 115, cellRenderer: (p: ICellRendererParams<Invoice>) => p.value ? <Box display="flex" height="100%" alignItems="center" gap={.6}><span>{p.value}</span><Tag tone={p.data?.block_category === 'jv' ? 'info' : p.data?.block_category === 'own' ? 'success' : 'warning'}>{p.data?.block_category?.toUpperCase() || '?'}</Tag></Box> : <Typography fontSize={11} color="text.secondary" alignSelf="center">Common</Typography> },
    { headerName: 'RIG / WELL', field: 'well_code', minWidth: 145, valueGetter: p => [p.data?.rig_code, p.data?.well_code].filter(Boolean).join(' / ') },
    { headerName: 'LOCATION', field: 'location_name', minWidth: 145 }, { headerName: 'CURRENCY', field: 'currency_code', minWidth: 90, maxWidth: 100 },
    { headerName: 'INVOICE TOTAL', field: 'invoice_total', minWidth: 135, type: 'rightAligned', valueFormatter: p => formatAmount(p.value) },
    { headerName: 'VERIFIED TOTAL', field: 'verified_total', minWidth: 140, type: 'rightAligned', valueFormatter: p => formatAmount(p.value) },
    { headerName: 'DIFFERENCE', field: 'difference_amount', minWidth: 120, type: 'rightAligned', valueFormatter: p => formatAmount(p.value) },
    { headerName: 'DUE DATE', field: 'due_date', minWidth: 125, valueFormatter: p => formatDate(p.value), cellRenderer: (p: ICellRendererParams<Invoice>) => <Box height="100%" display="flex" alignItems="center" gap={.5}><Typography fontSize={12} color={p.data?.is_overdue ? 'error.main' : 'text.primary'}>{formatDate(p.value)}</Typography>{p.data?.is_overdue && <Tag tone="error">Overdue</Tag>}</Box> },
    { headerName: 'STATUS', field: 'display_status', minWidth: 190, cellRenderer: (p: ICellRendererParams<Invoice>) => <Box display="flex" height="100%" alignItems="center"><Tag tone={statusTone(p.value)}>{INVOICE_STATUS_LABEL[p.value as keyof typeof INVOICE_STATUS_LABEL]}</Tag></Box> },
    { headerName: 'SENT TO ACCOUNTS', field: 'sent_to_accounts_date', minWidth: 150, valueFormatter: p => formatDate(p.value) },
    { headerName: 'EPICOR RECEIVED', field: 'epicor_received_date', minWidth: 145, valueFormatter: p => formatDate(p.value) },
    { headerName: 'EPICOR APPROVED', field: 'epicor_approved_date', minWidth: 145, valueFormatter: p => formatDate(p.value) },
    { headerName: 'PAID DATE', field: 'paid_date', minWidth: 125, valueFormatter: p => formatDate(p.value) },
    { headerName: 'FILES', field: 'attachment_count', minWidth: 75, maxWidth: 85, type: 'rightAligned' },
    { headerName: 'ACTIONS', field: 'id', minWidth: 150, maxWidth: 165, sortable: false, filter: false, cellRenderer: (p: ICellRendererParams<Invoice>) => {
      if (!p.data) return null
      const row = p.data; const next = WORKFLOW_ACTION[row.status]
      return <Stack direction="row" alignItems="center" height="100%" spacing={-.5}>
        <Tooltip title="Open IDVS"><IconButton size="small" onClick={() => navigate(`/invoice-processing/idvs/${row.id}/view`)}><VisibilityOutlined fontSize="small"/></IconButton></Tooltip>
        {!showDeleted && row.status === 'draft' && can('invoice-processing:update') && <Tooltip title="Edit draft"><IconButton size="small" onClick={() => navigate(`/invoice-processing/idvs/${row.id}`)}><EditOutlined fontSize="small"/></IconButton></Tooltip>}
        {!showDeleted && next && !row.paid_date && can(next.permission) && <Tooltip title={next.label}><IconButton size="small" color="primary" onClick={() => openWorkflow([row], next.action)}><ArrowForward fontSize="small"/></IconButton></Tooltip>}
        {!showDeleted && row.status === 'approved' && !row.paid_date && can('invoice-processing:payment') && <Tooltip title="Record paid date"><IconButton size="small" color="success" onClick={() => openWorkflow([row], 'payment')}><PaymentOutlined fontSize="small"/></IconButton></Tooltip>}
        {!showDeleted && can('invoice-processing:delete') && <Tooltip title="Delete"><IconButton size="small" onClick={() => setConfirm({ kind: 'delete', ids: [row.id] })}><DeleteOutline fontSize="small"/></IconButton></Tooltip>}
        {showDeleted && can('invoice-processing:restore') && <Tooltip title="Restore"><IconButton size="small" onClick={() => setConfirm({ kind: 'restore', ids: [row.id] })}><RestoreFromTrash fontSize="small"/></IconButton></Tooltip>}
        {showDeleted && can('invoice-processing:permanent-delete') && <Tooltip title="Delete permanently"><IconButton size="small" color="error" onClick={() => setConfirm({ kind: 'purge', ids: [row.id] })}><DeleteForever fontSize="small"/></IconButton></Tooltip>}
      </Stack>
    } },
  ], [can, showDeleted, navigate])
  const actionLabel = workflow?.action === 'payment' ? 'Record paid date' : workflow ? Object.values(WORKFLOW_ACTION).find(item => item?.action === workflow.action)?.label ?? workflow.action : ''
  return <Box display="grid" gap={2} minHeight={0}>
    <PageHeading eyebrow="Invoice Processing" title={showDeleted ? 'Deleted Entries' : 'Saved IDVS & Tracking'} subtitle={showDeleted ? 'Restore an invoice to the active register, or permanently remove it with an explicit confirmation.' : 'Search the commercial register, advance verification milestones, and open any IDVS for its generated output and supporting documents.'} action={<Stack direction="row" gap={1} flexWrap="wrap">
      {!showDeleted && can('invoice-processing:create') && <Button variant="contained" startIcon={<Add/>} onClick={() => navigate('/invoice-processing/idvs/new')}>New IDVS</Button>}
      {!showDeleted && can('invoice-processing:import') && <Button variant="outlined" startIcon={<Upload/>} onClick={() => setImportOpen(true)}>Import XLSX / CSV</Button>}
      {!showDeleted && can('invoice-processing:configure') && <Button variant="outlined" startIcon={<SettingsOutlined/>} onClick={() => navigate('/invoice-processing/configuration')}>Configuration</Button>}
      <Button variant="outlined" color={showDeleted ? 'primary' : 'inherit'} startIcon={showDeleted ? <RestoreFromTrash/> : <DeleteOutline/>} onClick={() => { setShowDeleted(value => !value); navigate(showDeleted ? '/invoice-processing/register' : '/invoice-processing/deleted') }}>{showDeleted ? 'Active register' : 'Deleted Entries'}</Button>
      <Button variant="outlined" color="inherit" startIcon={<Refresh/>} onClick={() => void load()}>Refresh</Button>
    </Stack>}/>
    {error && <Alert severity="error" onClose={() => setError('')}>{error}</Alert>}{notice && <Alert severity="success" onClose={() => setNotice('')}>{notice}</Alert>}
    <Paper variant="outlined" sx={{ p: 1.5 }}>
      <Box display="grid" gridTemplateColumns="repeat(auto-fit,minmax(145px,1fr))" gap={1.2}>
        <TextField select size="small" label="Vendor" value={vendor} onChange={e => setVendor(e.target.value)}><MenuItem value="">All vendors</MenuItem>{reference?.vendors.map(item => <MenuItem key={item.id} value={item.id}>{item.label}</MenuItem>)}</TextField>
        <TextField select size="small" label="Status" value={status} onChange={e => setStatus(e.target.value)}><MenuItem value="">All statuses</MenuItem>{Object.entries(INVOICE_STATUS_LABEL).map(([value, label]) => <MenuItem key={value} value={value}>{label}</MenuItem>)}</TextField>
        <TextField select size="small" label="Block" value={block} onChange={e => setBlock(e.target.value)}><MenuItem value="">All blocks / common</MenuItem>{reference?.blocks.map(item => <MenuItem key={item.id} value={item.id}>{item.label}</MenuItem>)}</TextField>
        <TextField select size="small" label="Currency" value={currency} onChange={e => setCurrency(e.target.value)}><MenuItem value="">All currencies</MenuItem>{reference?.currencies.map(item => <MenuItem key={item.currency_code} value={item.currency_code}>{item.currency_code} · {item.currency_name}</MenuItem>)}</TextField>
        <TextField select size="small" label="Location" value={location} onChange={e => setLocation(e.target.value)}><MenuItem value="">All locations</MenuItem>{reference?.locations.map(item => <MenuItem key={item.id} value={item.id}>{item.name}</MenuItem>)}</TextField>
        <TextField select size="small" label="Date field" value={dateField} onChange={e => setDateField(e.target.value)}><MenuItem value="invoice_date">Invoice date</MenuItem><MenuItem value="idvs_date">IDVS date</MenuItem><MenuItem value="invoice_received_date">Received date</MenuItem><MenuItem value="due_date">Due date</MenuItem><MenuItem value="paid_date">Paid date</MenuItem></TextField>
        <TextField size="small" type="date" label="From" value={dateFrom} onChange={e => setDateFrom(e.target.value)} InputLabelProps={{ shrink: true }}/>
        <TextField size="small" type="date" label="To" value={dateTo} onChange={e => setDateTo(e.target.value)} InputLabelProps={{ shrink: true }}/>
        <TextField select size="small" label="Due tracking" value={overdue ? 'overdue' : ''} onChange={e => setOverdue(e.target.value === 'overdue')}><MenuItem value="">All invoices</MenuItem><MenuItem value="overdue">Overdue & unpaid</MenuItem></TextField>
        <Button disabled={!filterActive} onClick={resetFilters}>Clear filters</Button>
      </Box>
    </Paper>
    {selected.length > 0 && <Paper variant="outlined" sx={{ px: 1.5, py: 1 }}><Stack direction="row" alignItems="center" gap={1} flexWrap="wrap"><Typography variant="body2" fontWeight={700}>{selected.length} selected</Typography>
      {!showDeleted && selectedAction && can(selectedAction.permission) && <Button size="small" startIcon={<MoreTime/>} onClick={() => openWorkflow(selected, selectedAction.action)}>{selectedAction.label}</Button>}
      {!showDeleted && canBulkPayment && can('invoice-processing:payment') && <Button size="small" startIcon={<PaymentOutlined/>} onClick={() => openWorkflow(selected, 'payment')}>Record paid date</Button>}
      {!showDeleted && can('invoice-processing:delete') && <Button color="error" size="small" onClick={() => setConfirm({ kind: 'delete', ids: selected.map(row => row.id) })}>Delete</Button>}
      {showDeleted && can('invoice-processing:restore') && <Button size="small" onClick={() => setConfirm({ kind: 'restore', ids: selected.map(row => row.id) })}>Restore</Button>}
      {showDeleted && can('invoice-processing:permanent-delete') && <Button color="error" size="small" onClick={() => setConfirm({ kind: 'purge', ids: selected.map(row => row.id) })}>Delete permanently</Button>}
    </Stack></Paper>}
    <DataTable rows={rows} columns={columns} selectable onSelectionChange={setSelected} selectionResetKey={`${showDeleted}-${query}`} fillHeight exportName={showDeleted ? 'deleted-idvs-register' : 'idvs-tracking-register'} canExport={can('invoice-processing:export')} onExport={async (format, count) => { await api('/invoice-processing/export-audit', { method: 'POST', body: body({ module: showDeleted ? 'deleted_entries' : 'idvs', format, record_count: count, detail: query }) }) }} searchPlaceholder="Quick search IDVS, invoice, vendor, PO/SO, block…"/>
    {loading && <Typography color="text.secondary">Loading invoice register…</Typography>}
    <ImportDialog open={importOpen} onClose={() => setImportOpen(false)} title="Import IDVS invoices" subtitle="Repeat the invoice header on each line to create one multi-line IDVS. The preview shows the first 50 rows; reference and calculation errors identify the spreadsheet row." headers={INVOICE_IMPORT_HEADERS} optionalHeaders={INVOICE_IMPORT_OPTIONAL} sample={INVOICE_IMPORT_SAMPLE} templateName="idvs-invoice-import" onRows={importRows}/>
    <FormDialog open={Boolean(workflow)} onClose={() => setWorkflow(null)} onSubmit={() => void runWorkflow()} busy={busy} dirty={Boolean(actionRemarks || paymentReference)} title={actionLabel} subtitle={`${workflow?.rows.length ?? 0} selected IDVS record(s). Enter only the tracking date and optional remarks; EPICOR itself remains external.`} submitLabel={actionLabel}>
      <Box display="grid" gap={2} pt={.5}><TextField required type="date" label={workflow?.action === 'payment' ? 'Paid date' : 'Milestone date'} value={actionDate} onChange={e => setActionDate(e.target.value)} InputLabelProps={{ shrink: true }}/>{workflow?.action === 'payment' && <TextField label="Payment reference (optional)" value={paymentReference} onChange={e => setPaymentReference(e.target.value)} inputProps={{ maxLength: 150 }}/>}<TextField label="Remarks (optional)" multiline minRows={3} value={actionRemarks} onChange={e => setActionRemarks(e.target.value)} inputProps={{ maxLength: 1000 }}/></Box>
    </FormDialog>
    <FormDialog open={Boolean(confirm)} onClose={() => setConfirm(null)} onSubmit={() => void runLifecycle()} busy={busy} danger={confirm?.kind !== 'restore'} title={confirm?.kind === 'restore' ? 'Restore IDVS records?' : confirm?.kind === 'purge' ? 'Permanently delete IDVS records?' : 'Move IDVS records to Deleted Entries?'} subtitle={confirm?.kind === 'purge' ? 'This removes the invoice, calculation lines, history and attachments. It cannot be undone.' : confirm?.kind === 'restore' ? 'The selected records return to the active tracking register.' : 'Deleted records and their documents remain recoverable until permanently deleted.'} submitLabel={confirm?.kind === 'restore' ? 'Restore' : confirm?.kind === 'purge' ? 'Delete permanently' : 'Delete'}><Typography>{confirm?.ids.length ?? 0} IDVS record(s) selected.</Typography></FormDialog>
  </Box>
}
