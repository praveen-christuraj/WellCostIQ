import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { useNavigate, useParams } from 'react-router-dom'
import { AgGridReact } from 'ag-grid-react'
import { AllCommunityModule, ModuleRegistry, themeQuartz, type ColDef, type CellValueChangedEvent, type ICellRendererParams } from 'ag-grid-community'
import { Add, ArrowBack, ContentCopy, DeleteOutline, InfoOutlined, RestartAlt, SaveOutlined, SettingsOutlined } from '@mui/icons-material'
import { Alert, Autocomplete, Box, Button, Chip, IconButton, MenuItem, Paper, Stack, Table, TableBody, TableCell, TableContainer, TableHead, TableRow, TextField, Tooltip, Typography } from '@mui/material'
import { PageHeading, Tag, useUnsavedChangesGuard } from '../components/Common'
import { SectionCard } from '../components/ui/SectionCard'
import { useAuth } from '../context/AuthContext'
import { useColorMode } from '../context/ThemeContext'
import { gridThemeParams } from '../designSystem'
import { api, body } from '../lib/api'
import { addDays, calculateDraft, formatAmount, multiply, numeric, resolveExchangeRate } from '../lib/invoiceCalculations'
import { MAX_ATTACHMENT_BYTES, type ConfigItem, type InvoiceDetail, type InvoiceLine, type InvoicePaymentSplit, type InvoiceReference, type InvoiceSaveInput, type InvoiceTax, type PaymentTerm, type TaxDirection, type VendorOption } from '../lib/invoiceProcessing'

ModuleRegistry.registerModules([AllCommunityModule])
const today = () => new Date().toISOString().slice(0, 10)
const newKey = () => globalThis.crypto?.randomUUID?.() ?? `${Date.now()}-${Math.random()}`
type EditorLine = InvoiceLine & { key: string }
type EditorTax = InvoiceTax & { key: string }
type EditorSplit = InvoicePaymentSplit & { key: string }
type EditorForm = {
  idvs_number: string; idvs_date: string; invoice_number: string; invoice_date: string; invoice_received_date: string
  vendor_id: string; order_id: string; block_id: string; rig_id: string; well_id: string; location_id: string
  field_name: string; phase: string; description_category_id: string; service_description: string; detailed_description: string
  concerned_person: string; service_from: string; service_to: string; currency_code: string; payment_term_id: string
  payment_tenure_days: string; disallowed_amount: string; advance_amount: string; remarks: string
}
const blankLine = (): EditorLine => ({ key: newKey(), description: '', invoice_quantity: '1', invoice_unit_price: '0', verified_quantity: '1', verified_unit_price: '0', remarks: '' })
const initialForm = (): EditorForm => ({
  idvs_number: '', idvs_date: today(), invoice_number: '', invoice_date: today(), invoice_received_date: today(),
  vendor_id: '', order_id: '', block_id: '', rig_id: '', well_id: '', location_id: '', field_name: '', phase: '',
  description_category_id: '', service_description: '', detailed_description: '', concerned_person: '', service_from: '', service_to: '',
  currency_code: '', payment_term_id: '', payment_tenure_days: '', disallowed_amount: '0', advance_amount: '0', remarks: '',
})
const taxKey = (tax: InvoiceTax): EditorTax => ({ ...tax, key: tax.id ?? newKey() })
const splitKey = (split: InvoicePaymentSplit): EditorSplit => ({ ...split, key: split.id ?? newKey() })
const autoTaxes = (reference: InvoiceReference, vendorId: string): EditorTax[] => reference.taxes.filter(tax => tax.is_active && (tax.is_common || tax.vendor_ids.includes(vendorId))).map(tax => taxKey({ tax_configuration_id: tax.id, tax_name: tax.tax_name, rate_percent: tax.rate_percent, direction: tax.direction, source: tax.is_common ? 'common' : 'vendor' }))

export default function InvoiceEditor() {
  const { id } = useParams()
  const navigate = useNavigate()
  const { can } = useAuth()
  const { mode } = useColorMode()
  const gridRef = useRef<AgGridReact<EditorLine>>(null)
  const loadSequence = useRef(0)
  const [reference, setReference] = useState<InvoiceReference | null>(null)
  const [form, setForm] = useState<EditorForm>(initialForm)
  const [revision, setRevision] = useState(0)
  const [lines, setLines] = useState<EditorLine[]>([blankLine()])
  const [taxes, setTaxes] = useState<EditorTax[]>([])
  const [splits, setSplits] = useState<EditorSplit[]>([])
  const [customSplits, setCustomSplits] = useState(false)
  const [loading, setLoading] = useState(true)
  const [saving, setSaving] = useState(false)
  const [dirty, setDirty] = useState(false)
  const [error, setError] = useState('')
  const [notice, setNotice] = useState('')
  const editing = Boolean(id)

  const makeSplits = useCallback((term: PaymentTerm | undefined, currency: string, refs: InvoiceReference): EditorSplit[] => {
    const source = term?.splits.length ? term.splits : [{ currency_code: currency, percentage: '100' }]
    return source.map(split => ({ key: newKey(), currency_code: split.currency_code, percentage: String(split.percentage), exchange_rate: String(resolveExchangeRate(split.currency_code, currency, refs.exchange_rates) ?? '') }))
  }, [])
  const load = useCallback(async () => {
    const sequence = ++loadSequence.current
    setLoading(true); setError('')
    try {
      const refs = await api<InvoiceReference>('/invoice-processing/reference')
      if (sequence !== loadSequence.current) return
      setReference(refs)
      if (id) {
        const invoice = await api<InvoiceDetail>(`/invoice-processing/invoices/${id}`)
        if (sequence !== loadSequence.current) return
        if (invoice.status !== 'draft') { navigate(`/invoice-processing/idvs/${id}/view`, { replace: true }); return }
        setRevision(invoice.revision)
        setForm({
          idvs_number: invoice.idvs_number, idvs_date: invoice.idvs_date, invoice_number: invoice.invoice_number,
          invoice_date: invoice.invoice_date, invoice_received_date: invoice.invoice_received_date, vendor_id: invoice.vendor_id,
          order_id: invoice.order_id ?? '', block_id: invoice.block_id ?? '', rig_id: invoice.rig_id ?? '', well_id: invoice.well_id ?? '',
          location_id: invoice.location_id, field_name: invoice.field_name, phase: invoice.phase,
          description_category_id: invoice.description_category_id ?? '', service_description: invoice.service_description,
          detailed_description: invoice.detailed_description, concerned_person: invoice.concerned_person,
          service_from: invoice.service_from ?? '', service_to: invoice.service_to ?? '', currency_code: invoice.currency_code,
          payment_term_id: invoice.payment_term_id ?? '', payment_tenure_days: String(invoice.payment_tenure_days),
          disallowed_amount: invoice.disallowed_amount, advance_amount: invoice.advance_amount, remarks: invoice.remarks,
        })
        setLines(invoice.lines.map(line => ({ ...line, key: line.id ?? newKey() })))
        setTaxes(invoice.taxes.map(taxKey)); setSplits(invoice.payment_splits.map(splitKey)); setCustomSplits(true)
      } else {
        const currency = refs.currencies.find(item => item.is_default)?.currency_code ?? refs.currencies[0]?.currency_code ?? ''
        setForm(current => ({ ...current, currency_code: currency }))
        setSplits(makeSplits(undefined, currency, refs)); setTaxes(autoTaxes(refs, ''))
      }
      if (sequence === loadSequence.current) setDirty(false)
    } catch (caught) {
      if (sequence === loadSequence.current) setError((caught as Error).message)
    } finally {
      if (sequence === loadSequence.current) setLoading(false)
    }
  }, [id, navigate, makeSplits])
  useEffect(() => {
    void load()
    return () => { loadSequence.current += 1 }
  }, [load])

  const patch = <K extends keyof EditorForm>(field: K, value: EditorForm[K]) => { setForm(current => ({ ...current, [field]: value })); setDirty(true); setNotice('') }
  const chooseVendor = (vendor: VendorOption | null) => {
    if (!reference) return
    setForm(current => ({ ...current, vendor_id: vendor?.id ?? '', order_id: '', payment_term_id: vendor?.payment_term_id ?? '' }))
    setTaxes(autoTaxes(reference, vendor?.id ?? ''))
    const term = reference.payment_terms.find(item => item.id === vendor?.payment_term_id)
    setSplits(makeSplits(term, form.currency_code, reference)); setCustomSplits(false); setDirty(true)
  }
  const chooseTerm = (termId: string) => {
    if (!reference) return
    patch('payment_term_id', termId)
    setSplits(makeSplits(reference.payment_terms.find(item => item.id === termId), form.currency_code, reference)); setCustomSplits(false)
  }
  const chooseCurrency = (currency: string) => {
    if (!reference) return
    patch('currency_code', currency)
    if (!customSplits) setSplits(makeSplits(reference.payment_terms.find(item => item.id === form.payment_term_id), currency, reference))
    else setSplits(current => current.map(split => ({ ...split, exchange_rate: String(resolveExchangeRate(split.currency_code, currency, reference.exchange_rates) ?? split.exchange_rate) })))
  }
  const chooseWell = (wellId: string) => {
    const well = reference?.wells.find(item => item.id === wellId)
    setForm(current => ({ ...current, well_id: wellId, rig_id: well?.rig_id ?? current.rig_id, block_id: well?.block_id ?? current.block_id })); setDirty(true)
  }
  const selectedVendor = reference?.vendors.find(item => item.id === form.vendor_id) ?? null
  const selectedOrder = reference?.orders.find(item => item.id === form.order_id) ?? null
  const availableOrders = reference?.orders.filter(item => item.vendor_id === form.vendor_id) ?? []
  const availableWells = reference?.wells.filter(item => (!form.rig_id || item.rig_id === form.rig_id) && (!form.block_id || item.block_id === form.block_id)) ?? []
  const selectedTerm = reference?.payment_terms.find(item => item.id === form.payment_term_id)
  const tenure = form.payment_tenure_days === '' ? selectedTerm?.payment_days ?? 0 : numeric(form.payment_tenure_days)
  const dueDate = addDays(form.invoice_date, tenure)
  const totals = useMemo(() => calculateDraft(lines, taxes, form.disallowed_amount, form.advance_amount, splits), [lines, taxes, form.disallowed_amount, form.advance_amount, splits])
  const updateLine = (key: string, field: keyof InvoiceLine, value: string) => { setLines(current => current.map(line => line.key === key ? { ...line, [field]: value } : line)); setDirty(true) }
  const onCellValueChanged = (event: CellValueChangedEvent<EditorLine>) => {
    const field = event.colDef.field as keyof InvoiceLine | undefined
    if (field && event.data) updateLine(event.data.key, field, String(event.newValue ?? ''))
  }
  const lineColumns = useMemo<ColDef<EditorLine>[]>(() => [
    { headerName: '#', valueGetter: params => (params.node?.rowIndex ?? 0) + 1, width: 48, maxWidth: 48, editable: false, suppressMovable: true },
    { headerName: 'LINE DESCRIPTION', field: 'description', minWidth: 270, flex: 1.5, editable: true, cellEditor: 'agTextCellEditor' },
    { headerName: 'INVOICE QTY', field: 'invoice_quantity', minWidth: 120, editable: true, type: 'rightAligned' },
    { headerName: 'INVOICE UNIT PRICE', field: 'invoice_unit_price', minWidth: 145, editable: true, type: 'rightAligned' },
    { headerName: 'INVOICE TOTAL', minWidth: 135, editable: false, type: 'rightAligned', valueGetter: params => params.data ? multiply(params.data.invoice_quantity, params.data.invoice_unit_price) : 0, valueFormatter: params => formatAmount(params.value) },
    { headerName: 'VERIFIED QTY', field: 'verified_quantity', minWidth: 120, editable: true, type: 'rightAligned' },
    { headerName: 'VERIFIED UNIT PRICE', field: 'verified_unit_price', minWidth: 150, editable: true, type: 'rightAligned' },
    { headerName: 'VERIFIED TOTAL', minWidth: 135, editable: false, type: 'rightAligned', valueGetter: params => params.data ? multiply(params.data.verified_quantity, params.data.verified_unit_price) : 0, valueFormatter: params => formatAmount(params.value) },
    { headerName: 'DIFFERENCE', minWidth: 120, editable: false, type: 'rightAligned', valueGetter: params => params.data ? multiply(params.data.invoice_quantity, params.data.invoice_unit_price) - multiply(params.data.verified_quantity, params.data.verified_unit_price) : 0, valueFormatter: params => formatAmount(params.value) },
    { headerName: 'LINE REMARKS', field: 'remarks', minWidth: 190, flex: 1, editable: true },
    { headerName: '', field: 'key', width: 88, maxWidth: 88, editable: false, sortable: false, cellRenderer: (params: ICellRendererParams<EditorLine>) => params.data ? <Stack direction="row" height="100%" alignItems="center" spacing={-1}><Tooltip title="Duplicate line"><IconButton size="small" onClick={() => { const copy = { ...params.data!, key: newKey(), id: undefined }; setLines(current => [...current.slice(0, (params.node?.rowIndex ?? 0) + 1), copy, ...current.slice((params.node?.rowIndex ?? 0) + 1)]); setDirty(true) }}><ContentCopy fontSize="small"/></IconButton></Tooltip><Tooltip title="Remove line"><span><IconButton size="small" disabled={lines.length === 1} onClick={() => { setLines(current => current.filter(line => line.key !== params.data!.key)); setDirty(true) }}><DeleteOutline fontSize="small"/></IconButton></span></Tooltip></Stack> : null },
  ], [lines.length])
  const gridTheme = useMemo(() => themeQuartz.withParams(gridThemeParams(mode)), [mode])
  const pasteLines = (event: React.ClipboardEvent<HTMLDivElement>) => {
    const text = event.clipboardData.getData('text/plain')
    if (!text || (!text.includes('\t') && !text.includes('\n'))) return
    const focused = gridRef.current?.api.getFocusedCell()
    if (!focused) return
    event.preventDefault()
    const fields = ['description', 'invoice_quantity', 'invoice_unit_price', null, 'verified_quantity', 'verified_unit_price', null, null, 'remarks'] as const
    const startColumn = focused.column.getColId()
    const pasteFields = ['description', 'invoice_quantity', 'invoice_unit_price', 'verified_quantity', 'verified_unit_price', 'remarks'] as const
    const columnIndex = pasteFields.indexOf(startColumn as typeof pasteFields[number])
    // Also accept a nine-column copy of the visible grid, skipping calculated columns.
    const visibleIndex = fields.indexOf(startColumn as never)
    const matrix = text.replace(/\r/g, '').replace(/\n$/, '').split('\n').map(row => row.split('\t'))
    setLines(current => {
      const next = current.map(line => ({ ...line }))
      matrix.forEach((values, rowOffset) => {
        const rowIndex = (focused.rowIndex ?? 0) + rowOffset
        while (next.length <= rowIndex && next.length < 500) next.push(blankLine())
        if (!next[rowIndex]) return
        values.forEach((value, columnOffset) => {
          const field = visibleIndex >= 0 ? fields[visibleIndex + columnOffset] : columnIndex >= 0 ? pasteFields[columnIndex + columnOffset] : null
          if (field) Object.assign(next[rowIndex], { [field]: value.trim() })
        })
      })
      return next
    })
    setDirty(true); setNotice(`${matrix.length} spreadsheet row(s) pasted. Review the calculated columns before saving.`)
  }

  const payload = (): InvoiceSaveInput => ({
    idvs_number: form.idvs_number, idvs_date: form.idvs_date, ...(editing ? { expected_revision: revision } : {}),
    invoice_number: form.invoice_number.trim(), invoice_date: form.invoice_date, invoice_received_date: form.invoice_received_date,
    vendor_id: form.vendor_id, order_id: form.order_id || null, block_id: form.block_id || null, rig_id: form.rig_id || null, well_id: form.well_id || null,
    location_id: form.location_id, field_name: form.field_name, phase: form.phase, description_category_id: form.description_category_id || null,
    service_description: form.service_description.trim(), detailed_description: form.detailed_description, concerned_person: form.concerned_person,
    service_from: form.service_from || null, service_to: form.service_to || null, currency_code: form.currency_code,
    payment_term_id: form.payment_term_id || null, payment_tenure_days: form.payment_tenure_days === '' ? null : Number(form.payment_tenure_days),
    disallowed_amount: form.disallowed_amount || '0', advance_amount: form.advance_amount || '0', remarks: form.remarks,
    lines: lines.map(line => ({ description: line.description.trim(), invoice_quantity: line.invoice_quantity, invoice_unit_price: line.invoice_unit_price, verified_quantity: line.verified_quantity, verified_unit_price: line.verified_unit_price, remarks: line.remarks })),
    taxes: taxes.map(tax => ({ tax_configuration_id: tax.tax_configuration_id, tax_name: tax.tax_name, rate_percent: tax.rate_percent, direction: tax.direction })),
    payment_splits: splits.map(split => ({ currency_code: split.currency_code, percentage: split.percentage, exchange_rate: split.exchange_rate || null })),
  })
  const validate = (): string => {
    if (!form.vendor_id || !form.location_id || !form.currency_code || !form.idvs_date || !form.invoice_date || !form.invoice_received_date) return 'Complete the vendor, location, currency, IDVS date, invoice date and receipt date.'
    if (!form.invoice_number.trim() || !form.service_description.trim()) return 'Invoice number and service description are required.'
    if (form.service_from && form.service_to && form.service_to < form.service_from) return 'Service To must be on or after Service From.'
    if (!lines.length || lines.some(line => !line.description.trim() || numeric(line.invoice_quantity) <= 0 || numeric(line.invoice_unit_price) < 0 || numeric(line.verified_quantity) < 0 || numeric(line.verified_unit_price) < 0)) return 'Every line needs a description, invoice quantity above zero, and valid non-negative prices and verified quantities.'
    if (Math.abs(totals.splitPercentage - 100) > 0.000001) return `Payment split percentages total ${totals.splitPercentage}%. They must total exactly 100%.`
    if (splits.some(split => !split.currency_code || numeric(split.percentage) <= 0 || numeric(split.exchange_rate) <= 0)) return 'Every payment split needs a currency, a percentage above zero, and a positive exchange rate. Configure any missing exchange rate first.'
    if (totals.adjustedVerifiedAmount < 0) return 'Disallowed and advance amounts cannot exceed the verified total.'
    return ''
  }
  const save = async (redirect = true): Promise<boolean> => {
    const problem = validate()
    if (problem) { setError(problem); return false }
    setSaving(true); setError('')
    try {
      const saved = await api<InvoiceDetail>(editing ? `/invoice-processing/invoices/${id}` : '/invoice-processing/invoices', { method: editing ? 'PUT' : 'POST', body: body(payload()) })
      setDirty(false); setRevision(saved.revision)
      if (redirect) navigate(`/invoice-processing/idvs/${saved.id}/view`, { replace: true })
      return true
    } catch (caught) { setError((caught as Error).message); return false }
    finally { setSaving(false) }
  }
  const guard = useUnsavedChangesGuard({ when: dirty && !saving, onSave: () => save(false), title: 'Leave this IDVS with unsaved changes?', message: 'Your commercial header, line edits, taxes or payment splits have not been saved. Save the draft before leaving, or discard your edits deliberately.' })
  if (loading) return <Box><PageHeading eyebrow="Invoice Processing" title={editing ? 'Edit IDVS' : 'New IDVS'} subtitle="Loading Master Data, operational scope and invoice configuration…"/><Typography color="text.secondary">Loading invoice workspace…</Typography></Box>
  return <Box sx={{ pb: 4 }}>
    <PageHeading eyebrow="Invoice Processing / IDVS Entry" title={editing ? form.idvs_number || 'Edit IDVS' : 'Create IDVS'} subtitle="A spreadsheet-fast worksheet backed by Master Data, reusable vendor terms, configured taxes and server-verified calculations." meta={<><Tag tone="info">{editing ? `Revision ${revision}` : 'New draft'}</Tag>{form.currency_code && <Tag>{form.currency_code}</Tag>}{dueDate && <Tag tone="warning">Due {dueDate}</Tag>}</>} action={<Stack direction="row" gap={1} flexWrap="wrap"><Button variant="outlined" startIcon={<ArrowBack/>} onClick={() => navigate('/invoice-processing/register')}>Back to register</Button>{can('invoice-processing:configure') && <Button variant="outlined" startIcon={<SettingsOutlined/>} onClick={() => navigate('/invoice-processing/configuration')}>Configuration</Button>}<Button variant="contained" startIcon={<SaveOutlined/>} disabled={saving} onClick={() => void save()}>{saving ? 'Saving…' : 'Save draft'}</Button></Stack>}/>
    {error && <Alert severity="error" sx={{ mb: 2 }} onClose={() => setError('')}>{error}</Alert>}{notice && <Alert severity="info" sx={{ mb: 2 }} onClose={() => setNotice('')}>{notice}</Alert>}
    {!reference?.locations.length && <Alert severity="warning" sx={{ mb: 2 }}>Configure at least one Invoice Processing location before saving. Vendors, PO/SO, currencies and operational scope remain read-only references from their owning modules.</Alert>}
    <Box display="grid" gridTemplateColumns={{ xs: '1fr', xl: 'minmax(0,1fr) 285px' }} gap={2} alignItems="start">
      <Box display="grid" gap={2} minWidth={0}>
        <SectionCard title="Invoice & vendor" subtitle="Choose the vendor first; only its related Master Data PO/SO orders remain available.">
          <Box display="grid" gridTemplateColumns="repeat(auto-fit,minmax(190px,1fr))" gap={1.5}>
            <Autocomplete options={reference?.vendors ?? []} value={selectedVendor} getOptionLabel={option => option.label} onChange={(_event, value) => chooseVendor(value)} renderInput={params => <TextField {...params} required label="Vendor" placeholder="Search code or name"/>} isOptionEqualToValue={(a, b) => a.id === b.id}/>
            <Autocomplete options={availableOrders} value={selectedOrder} getOptionLabel={option => `${option.order_type} · ${option.order_number}`} onChange={(_event, value) => { patch('order_id', value?.id ?? '') }} renderInput={params => <TextField {...params} label="Related PO / SO (optional)"/>} isOptionEqualToValue={(a, b) => a.id === b.id} disabled={!form.vendor_id} noOptionsText="No order for this vendor"/>
            <TextField required label="Invoice number" value={form.invoice_number} onChange={e => patch('invoice_number', e.target.value)} inputProps={{ maxLength: 120 }}/>
            <TextField required type="date" label="Invoice date" value={form.invoice_date} onChange={e => patch('invoice_date', e.target.value)} InputLabelProps={{ shrink: true }}/>
            <TextField required type="date" label="Invoice received" value={form.invoice_received_date} onChange={e => patch('invoice_received_date', e.target.value)} InputLabelProps={{ shrink: true }}/>
            <TextField required type="date" label="IDVS creation date" value={form.idvs_date} onChange={e => patch('idvs_date', e.target.value)} InputLabelProps={{ shrink: true }}/>
            <TextField label="IDVS number" value={form.idvs_number} onChange={e => patch('idvs_number', e.target.value)} placeholder={editing ? '' : 'Assigned automatically'} disabled={editing} inputProps={{ maxLength: 60 }}/>
          </Box>
        </SectionCard>
        <SectionCard title="Operational scope & service" subtitle="Scope is optional for common-material invoices. Selecting a well also resolves its rig and block.">
          <Box display="grid" gridTemplateColumns="repeat(auto-fit,minmax(175px,1fr))" gap={1.5}>
            <TextField select label="Block (optional)" value={form.block_id} onChange={e => { setForm(current => ({ ...current, block_id: e.target.value, well_id: '' })); setDirty(true) }}><MenuItem value="">Common / no block</MenuItem>{reference?.blocks.map(item => <MenuItem key={item.id} value={item.id}>{item.label}{item.category ? ` · ${item.category.toUpperCase()}` : ''}</MenuItem>)}</TextField>
            <TextField select label="Rig (optional)" value={form.rig_id} onChange={e => { setForm(current => ({ ...current, rig_id: e.target.value, well_id: '' })); setDirty(true) }}><MenuItem value="">No rig</MenuItem>{reference?.rigs.map(item => <MenuItem key={item.id} value={item.id}>{item.label}</MenuItem>)}</TextField>
            <TextField select label="Well (optional)" value={form.well_id} onChange={e => chooseWell(e.target.value)}><MenuItem value="">No well</MenuItem>{availableWells.map(item => <MenuItem key={item.id} value={item.id}>{item.label}</MenuItem>)}</TextField>
            <TextField select required label="Invoice location" value={form.location_id} onChange={e => patch('location_id', e.target.value)}><MenuItem value="" disabled>Select location</MenuItem>{reference?.locations.map((item: ConfigItem) => <MenuItem key={item.id} value={item.id}>{item.name}</MenuItem>)}</TextField>
            <TextField label="Field name (optional)" value={form.field_name} onChange={e => patch('field_name', e.target.value)}/>
            <TextField label="Phase (optional)" value={form.phase} onChange={e => patch('phase', e.target.value)} placeholder="Drilling / Completion"/>
            <TextField select label="Description category" value={form.description_category_id} onChange={e => patch('description_category_id', e.target.value)}><MenuItem value="">Uncategorised</MenuItem>{reference?.categories.map(item => <MenuItem key={item.id} value={item.id}>{item.name}</MenuItem>)}</TextField>
            <TextField label="Concerned person" value={form.concerned_person} onChange={e => patch('concerned_person', e.target.value)}/>
            <TextField type="date" label="Service from" value={form.service_from} onChange={e => patch('service_from', e.target.value)} InputLabelProps={{ shrink: true }}/>
            <TextField type="date" label="Service to" value={form.service_to} onChange={e => patch('service_to', e.target.value)} InputLabelProps={{ shrink: true }}/>
            <TextField required label="Service description" value={form.service_description} onChange={e => patch('service_description', e.target.value)} sx={{ gridColumn: 'span 2' }} inputProps={{ maxLength: 500 }}/>
            <TextField label="Detailed description" multiline minRows={2} value={form.detailed_description} onChange={e => patch('detailed_description', e.target.value)} sx={{ gridColumn: 'span 2' }} inputProps={{ maxLength: 2000 }}/>
          </Box>
        </SectionCard>
        <SectionCard title="IDVS worksheet" subtitle="Click a cell and type, Tab across the row, or paste Excel cells into the focused cell. Calculated columns update immediately." action={<Stack direction="row" gap={1}><Button size="small" startIcon={<RestartAlt/>} onClick={() => { setLines(current => current.map(line => ({ ...line, verified_quantity: line.invoice_quantity, verified_unit_price: line.invoice_unit_price }))); setDirty(true) }}>Copy invoice to verified</Button><Button size="small" startIcon={<Add/>} onClick={() => { setLines(current => [...current, blankLine()]); setDirty(true) }}>Add line</Button></Stack>}>
          <Alert icon={<InfoOutlined/>} severity="info" sx={{ mb: 1.5, py: 0 }}>Paste columns in worksheet order. For a compact paste use: description, invoice qty, invoice unit price, verified qty, verified unit price, remarks. Totals and differences are never imported as editable values.</Alert>
          <Box onPaste={pasteLines} sx={{ height: 390, width: '100%', '& .ag-cell': { fontVariantNumeric: 'tabular-nums' } }}>
            <AgGridReact<EditorLine> ref={gridRef} theme={gridTheme} rowData={lines} columnDefs={lineColumns} getRowId={params => params.data.key} defaultColDef={{ sortable: false, filter: false, resizable: true, suppressMovable: true }} singleClickEdit stopEditingWhenCellsLoseFocus enterNavigatesVertically enterNavigatesVerticallyAfterEdit onCellValueChanged={onCellValueChanged} rowSelection={{ mode: 'singleRow', enableClickSelection: false }} overlayNoRowsTemplate="Add a line to begin"/>
          </Box>
          <Stack direction="row" justifyContent="space-between" mt={1} flexWrap="wrap"><Typography variant="caption" color="text.secondary">{lines.length} / 500 lines · Changes are calculated locally for responsiveness and recalculated authoritatively on save.</Typography><Button size="small" startIcon={<Add/>} onClick={() => { setLines(current => [...current, blankLine()]); setDirty(true) }}>Add another line</Button></Stack>
        </SectionCard>
        <SectionCard title="Taxes & commercial adjustments" subtitle="Common and vendor-linked taxes were applied automatically. Add an invoice-specific tax or adjust this snapshot without changing configuration.">
          <TableContainer component={Paper} variant="outlined"><Table size="small"><TableHead><TableRow><TableCell>Tax</TableCell><TableCell align="right">Rate %</TableCell><TableCell>Effect</TableCell><TableCell align="right">Invoice amount</TableCell><TableCell align="right">Verified amount</TableCell><TableCell width={50}/></TableRow></TableHead><TableBody>
            {taxes.map(tax => <TableRow key={tax.key}><TableCell sx={{ minWidth: 190 }}><TextField size="small" fullWidth value={tax.tax_name} onChange={e => { setTaxes(current => current.map(item => item.key === tax.key ? { ...item, tax_name: e.target.value, tax_configuration_id: null, source: 'manual' } : item)); setDirty(true) }}/></TableCell><TableCell sx={{ minWidth: 110 }}><TextField size="small" type="number" value={tax.rate_percent} inputProps={{ min: 0, max: 100, step: 'any' }} onChange={e => { setTaxes(current => current.map(item => item.key === tax.key ? { ...item, rate_percent: e.target.value } : item)); setDirty(true) }}/></TableCell><TableCell><TextField select size="small" value={tax.direction} onChange={e => { setTaxes(current => current.map(item => item.key === tax.key ? { ...item, direction: e.target.value as TaxDirection } : item)); setDirty(true) }}><MenuItem value="addition">Addition</MenuItem><MenuItem value="deduction">Deduction</MenuItem></TextField></TableCell><TableCell align="right">{formatAmount((tax.direction === 'addition' ? 1 : -1) * totals.invoiceSubtotal * numeric(tax.rate_percent) / 100)}</TableCell><TableCell align="right">{formatAmount((tax.direction === 'addition' ? 1 : -1) * totals.verifiedSubtotal * numeric(tax.rate_percent) / 100)}</TableCell><TableCell><IconButton size="small" aria-label={`Remove ${tax.tax_name}`} onClick={() => { setTaxes(current => current.filter(item => item.key !== tax.key)); setDirty(true) }}><DeleteOutline/></IconButton></TableCell></TableRow>)}
            {!taxes.length && <TableRow><TableCell colSpan={6} align="center"><Typography color="text.secondary" py={2}>No taxes applied to this IDVS.</Typography></TableCell></TableRow>}
          </TableBody></Table></TableContainer>
          <Stack direction="row" gap={1} mt={1.5} flexWrap="wrap"><Button size="small" startIcon={<Add/>} onClick={() => { setTaxes(current => [...current, { key: newKey(), tax_configuration_id: null, tax_name: 'Invoice-specific tax', rate_percent: '0', direction: 'deduction', source: 'manual' }]); setDirty(true) }}>Add tax</Button>{reference?.taxes.filter(tax => !taxes.some(item => item.tax_configuration_id === tax.id)).map(tax => <Chip key={tax.id} clickable label={`+ ${tax.tax_name} ${tax.rate_percent}%`} onClick={() => { setTaxes(current => [...current, taxKey({ tax_configuration_id: tax.id, tax_name: tax.tax_name, rate_percent: tax.rate_percent, direction: tax.direction, source: 'manual' })]); setDirty(true) }}/>)}</Stack>
          <Box display="grid" gridTemplateColumns="repeat(auto-fit,minmax(180px,1fr))" gap={1.5} mt={2}><TextField type="number" label="Disallowed amount" value={form.disallowed_amount} onChange={e => patch('disallowed_amount', e.target.value)} inputProps={{ min: 0, step: 'any' }}/><TextField type="number" label="Advance amount" value={form.advance_amount} onChange={e => patch('advance_amount', e.target.value)} inputProps={{ min: 0, step: 'any' }}/><TextField label="General remarks" value={form.remarks} onChange={e => patch('remarks', e.target.value)} inputProps={{ maxLength: 1000 }}/></Box>
        </SectionCard>
        <SectionCard title="Payment terms & currency split" subtitle="Reusable terms supply tenure and percentages; this IDVS keeps its own exchange-rate snapshot.">
          <Box display="grid" gridTemplateColumns="repeat(auto-fit,minmax(190px,1fr))" gap={1.5} mb={2}>
            <TextField select required label="Invoice currency" value={form.currency_code} onChange={e => chooseCurrency(e.target.value)}>{reference?.currencies.map(item => <MenuItem key={item.currency_code} value={item.currency_code}>{item.currency_code} · {item.currency_name}{item.is_default ? ' · workspace default' : ''}</MenuItem>)}</TextField>
            <TextField select label="Reusable payment term" value={form.payment_term_id} onChange={e => chooseTerm(e.target.value)}><MenuItem value="">Custom / no shared term</MenuItem>{reference?.payment_terms.map(item => <MenuItem key={item.id} value={item.id}>{item.term_name} · {item.payment_days} days</MenuItem>)}</TextField>
            <TextField type="number" label="Payment tenure (days)" value={form.payment_tenure_days} onChange={e => patch('payment_tenure_days', e.target.value)} placeholder={String(selectedTerm?.payment_days ?? 0)} helperText={`Due date = invoice date + tenure: ${dueDate || '—'}`} inputProps={{ min: 0, max: 3650 }}/>
          </Box>
          <TableContainer component={Paper} variant="outlined"><Table size="small"><TableHead><TableRow><TableCell>Payment currency</TableCell><TableCell align="right">Percentage</TableCell><TableCell align="right">FX from {form.currency_code || 'invoice'}</TableCell><TableCell align="right">Calculated split amount</TableCell><TableCell width={50}/></TableRow></TableHead><TableBody>
            {splits.map((split, index) => <TableRow key={split.key}><TableCell><TextField select size="small" value={split.currency_code} onChange={e => { setSplits(current => current.map(item => item.key === split.key ? { ...item, currency_code: e.target.value, exchange_rate: String(resolveExchangeRate(e.target.value, form.currency_code, reference?.exchange_rates ?? []) ?? '') } : item)); setCustomSplits(true); setDirty(true) }}>{reference?.currencies.map(item => <MenuItem key={item.currency_code} value={item.currency_code}>{item.currency_code}</MenuItem>)}</TextField></TableCell><TableCell align="right"><TextField size="small" type="number" value={split.percentage} inputProps={{ min: 0, max: 100, step: 'any' }} onChange={e => { setSplits(current => current.map(item => item.key === split.key ? { ...item, percentage: e.target.value } : item)); setCustomSplits(true); setDirty(true) }}/></TableCell><TableCell align="right"><TextField size="small" type="number" value={split.exchange_rate} error={!split.exchange_rate} helperText={!split.exchange_rate ? 'Configure FX' : ''} inputProps={{ min: 0, step: 'any' }} onChange={e => { setSplits(current => current.map(item => item.key === split.key ? { ...item, exchange_rate: e.target.value } : item)); setCustomSplits(true); setDirty(true) }}/></TableCell><TableCell align="right"><Typography fontWeight={700}>{split.currency_code} {formatAmount(totals.splitAmounts[index] ?? 0)}</Typography></TableCell><TableCell><IconButton size="small" disabled={splits.length === 1} onClick={() => { setSplits(current => current.filter(item => item.key !== split.key)); setCustomSplits(true); setDirty(true) }}><DeleteOutline/></IconButton></TableCell></TableRow>)}
          </TableBody></Table></TableContainer>
          <Stack direction="row" alignItems="center" gap={1} mt={1.5}><Button size="small" startIcon={<Add/>} onClick={() => { setSplits(current => [...current, { key: newKey(), currency_code: form.currency_code, percentage: '0', exchange_rate: '1' }]); setCustomSplits(true); setDirty(true) }}>Add split currency</Button><Tag tone={Math.abs(totals.splitPercentage - 100) < .000001 ? 'success' : 'error'}>Total {totals.splitPercentage}%</Tag><Typography variant="caption" color="text.secondary">A missing cross-currency rate is never silently treated as 1.</Typography></Stack>
        </SectionCard>
      </Box>
      <Paper variant="outlined" sx={{ p: 2, position: { xl: 'sticky' }, top: { xl: 76 } }}>
        <Typography className="eyebrow">Live calculation</Typography><Typography variant="h6" mt={.5}>Commercial summary</Typography><Typography variant="caption" color="text.secondary">All summary amounts in {form.currency_code || 'invoice currency'}</Typography>
        <Stack gap={1.25} mt={2}>
          {[['Invoice subtotal', totals.invoiceSubtotal], ['Verified subtotal', totals.verifiedSubtotal], ['Signed invoice taxes', totals.invoiceTaxTotal], ['Signed verified taxes', totals.verifiedTaxTotal], ['Invoice total', totals.invoiceTotal], ['Verified total', totals.verifiedTotal], ['Difference', totals.differenceAmount]].map(([label, value]) => <Box key={String(label)} display="flex" justifyContent="space-between" gap={1}><Typography fontSize={12} color="text.secondary">{label}</Typography><Typography fontSize={12} fontWeight={700}>{formatAmount(Number(value))}</Typography></Box>)}
          <Box sx={{ borderTop: '1px solid', borderColor: 'divider', pt: 1.5 }}><Typography fontSize={11} color="text.secondary">Adjusted verified / payable</Typography><Typography variant="h5" color={totals.adjustedVerifiedAmount < 0 ? 'error.main' : 'primary.main'} mt={.5}>{form.currency_code} {formatAmount(totals.adjustedVerifiedAmount)}</Typography></Box>
          <Box><Typography fontSize={11} color="text.secondary">Due date</Typography><Typography fontWeight={750} fontSize={14}>{dueDate || 'Complete invoice date and tenure'}</Typography></Box>
          {splits.map((split, index) => <Box key={split.key} display="flex" justifyContent="space-between" gap={1}><Typography fontSize={11} color="text.secondary">{split.percentage}% · {split.currency_code}</Typography><Typography fontSize={11} fontWeight={700}>{formatAmount(totals.splitAmounts[index] ?? 0)}</Typography></Box>)}
        </Stack>
        <Button fullWidth variant="contained" startIcon={<SaveOutlined/>} disabled={saving} onClick={() => void save()} sx={{ mt: 2.5 }}>{saving ? 'Saving…' : 'Save draft'}</Button>
        <Typography variant="caption" color="text.secondary" display="block" mt={1.5}>Submit from the saved IDVS or tracking register. Supporting documents up to {Math.round(MAX_ATTACHMENT_BYTES / 1024 / 1024)} MB each can be added after saving.</Typography>
      </Paper>
    </Box>
    {guard}
  </Box>
}
