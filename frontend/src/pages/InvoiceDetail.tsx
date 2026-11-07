import { useCallback, useEffect, useState } from 'react'
import { useNavigate, useParams } from 'react-router-dom'
import { ArrowBack, ArrowForward, AttachFile, DeleteOutline, Download, EditOutlined, FileDownloadOutlined, PaymentOutlined, PictureAsPdfOutlined, UploadFile, VisibilityOutlined } from '@mui/icons-material'
import { Alert, Box, Button, Chip, IconButton, LinearProgress, Menu, MenuItem, Paper, Stack, Step, StepLabel, Stepper, Tab, Table, TableBody, TableCell, TableContainer, TableHead, TableRow, Tabs, TextField, Tooltip, Typography } from '@mui/material'
import { FormDialog, PageHeading, Tag } from '../components/Common'
import { IdvsSheet } from '../components/invoice/IdvsSheet'
import { formatDate } from '../lib/invoiceCalculations'
import { SectionCard } from '../components/ui/SectionCard'
import { useAuth } from '../context/AuthContext'
import { api, body, downloadFile, previewFile, uploadFiles } from '../lib/api'
import { exportIdvs } from '../lib/invoiceExport'
import { INVOICE_STATUS_LABEL, MAX_ATTACHMENT_BYTES, WORKFLOW_ACTION, formatFileSize, type InvoiceAttachment, type InvoiceDetail, type WorkflowAction } from '../lib/invoiceProcessing'

const statusTone = (status: string): 'neutral' | 'success' | 'info' | 'warning' => status === 'paid' || status === 'approved' ? 'success' : status === 'submitted' || status === 'sent_to_accounts' ? 'info' : status === 'epicor_pending' ? 'warning' : 'neutral'
const today = () => new Date().toISOString().slice(0, 10)

export default function InvoiceDetailPage() {
  const { id = '' } = useParams()
  const navigate = useNavigate()
  const { can } = useAuth()
  const [invoice, setInvoice] = useState<InvoiceDetail | null>(null)
  const [tab, setTab] = useState(0)
  const [loading, setLoading] = useState(true)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')
  const [notice, setNotice] = useState('')
  const [exportAnchor, setExportAnchor] = useState<HTMLElement | null>(null)
  const [workflow, setWorkflow] = useState<WorkflowAction | 'payment' | null>(null)
  const [actionDate, setActionDate] = useState(today())
  const [remarks, setRemarks] = useState('')
  const [paymentReference, setPaymentReference] = useState('')
  const [files, setFiles] = useState<File[]>([])
  const [label, setLabel] = useState('')
  const [notes, setNotes] = useState('')
  const [remove, setRemove] = useState<InvoiceAttachment | null>(null)
  const load = useCallback(async () => {
    setLoading(true); setError('')
    try { setInvoice(await api<InvoiceDetail>(`/invoice-processing/invoices/${id}`)) }
    catch (caught) { setError((caught as Error).message) }
    finally { setLoading(false) }
  }, [id])
  useEffect(() => { void load() }, [load])
  const next = invoice ? WORKFLOW_ACTION[invoice.status] : undefined
  const openWorkflow = (action: WorkflowAction | 'payment') => { setWorkflow(action); setActionDate(today()); setRemarks(''); setPaymentReference('') }
  const runWorkflow = async () => {
    if (!invoice || !workflow) return
    setBusy(true); setError('')
    try {
      if (workflow === 'payment') await api(`/invoice-processing/invoices/${invoice.id}/payment`, { method: 'POST', body: body({ paid_date: actionDate, payment_reference: paymentReference, remarks }) })
      else await api(`/invoice-processing/invoices/${invoice.id}/workflow`, { method: 'POST', body: body({ action: workflow, action_date: actionDate, remarks }) })
      setNotice('Tracking milestone saved.'); setWorkflow(null); await load()
    } catch (caught) { setError((caught as Error).message) }
    finally { setBusy(false) }
  }
  const runExport = async (format: 'csv' | 'xlsx' | 'pdf') => {
    if (!invoice) return
    setExportAnchor(null); setError('')
    try {
      await exportIdvs(invoice, format)
      await api('/invoice-processing/export-audit', { method: 'POST', body: body({ module: 'idvs', format, record_count: 1, detail: invoice.idvs_number }) })
    } catch (caught) { setError((caught as Error).message) }
  }
  const chooseFiles = (selected: File[]) => {
    const oversized = selected.find(file => file.size > MAX_ATTACHMENT_BYTES)
    if (oversized) { setError(`${oversized.name} is ${formatFileSize(oversized.size)}. Each supporting document must be 25 MB or smaller.`); return }
    setFiles(selected); setError('')
  }
  const upload = async () => {
    if (!invoice || !files.length) return
    setBusy(true); setError('')
    try {
      await uploadFiles(`/invoice-processing/invoices/${invoice.id}/attachments`, files, { label, notes })
      setNotice(`${files.length} supporting document(s) uploaded.`); setFiles([]); setLabel(''); setNotes(''); await load()
    } catch (caught) { setError((caught as Error).message) }
    finally { setBusy(false) }
  }
  const deleteAttachment = async () => {
    if (!invoice || !remove) return
    setBusy(true)
    try { await api(`/invoice-processing/attachments/${remove.id}`, { method: 'DELETE' }); setNotice('Supporting document deleted.'); setRemove(null); await load() }
    catch (caught) { setError((caught as Error).message) }
    finally { setBusy(false) }
  }
  if (loading && !invoice) return <Box><PageHeading eyebrow="Invoice Processing" title="Open IDVS" subtitle="Loading the saved commercial record…"/><LinearProgress/></Box>
  if (!invoice) return <Box><PageHeading eyebrow="Invoice Processing" title="IDVS unavailable" subtitle="The requested record could not be opened."/><Alert severity="error">{error || 'Record not found.'}</Alert><Button sx={{ mt: 2 }} startIcon={<ArrowBack/>} onClick={() => navigate('/invoice-processing/register')}>Back to register</Button></Box>
  const activeStep = invoice.paid_date ? 5 : invoice.status === 'approved' ? 4 : invoice.status === 'epicor_pending' ? 3 : invoice.status === 'sent_to_accounts' ? 2 : invoice.status === 'submitted' ? 1 : 0
  const workflowLabel = workflow === 'payment' ? 'Record paid date' : workflow ? Object.values(WORKFLOW_ACTION).find(item => item?.action === workflow)?.label ?? '' : ''
  return <Box sx={{ pb: 4 }}>
    <PageHeading eyebrow="Invoice Processing / Saved IDVS" title={invoice.idvs_number} subtitle={`${invoice.vendor_name} · Invoice ${invoice.invoice_number} · ${invoice.service_description}`} meta={<>{invoice.is_deleted && <Tag tone="warning">Deleted entry</Tag>}<Tag tone={statusTone(invoice.display_status)}>{INVOICE_STATUS_LABEL[invoice.display_status]}</Tag><Tag>{invoice.currency_code}</Tag>{invoice.block_category && <Tag tone={invoice.block_category === 'jv' ? 'info' : 'success'}>{invoice.block_category === 'jv' ? 'JV Block' : 'Own Block'}</Tag>}{invoice.is_overdue && <Tag tone="error">Overdue</Tag>}<Tag>{invoice.attachment_count} attachment(s)</Tag></>} action={<Stack direction="row" gap={1} flexWrap="wrap">
      <Button variant="outlined" startIcon={<ArrowBack/>} onClick={() => navigate('/invoice-processing/register')}>Register</Button>
      {!invoice.is_deleted && invoice.status === 'draft' && can('invoice-processing:update') && <Button variant="outlined" startIcon={<EditOutlined/>} onClick={() => navigate(`/invoice-processing/idvs/${invoice.id}`)}>Edit draft</Button>}
      {!invoice.is_deleted && next && !invoice.paid_date && can(next.permission) && <Button variant="contained" startIcon={<ArrowForward/>} onClick={() => openWorkflow(next.action)}>{next.label}</Button>}
      {!invoice.is_deleted && invoice.status === 'approved' && !invoice.paid_date && can('invoice-processing:payment') && <Button variant="contained" color="success" startIcon={<PaymentOutlined/>} onClick={() => openWorkflow('payment')}>Record paid date</Button>}
      {can('invoice-processing:export') && <Button variant="outlined" startIcon={<FileDownloadOutlined/>} onClick={event => setExportAnchor(event.currentTarget)}>Generate / export</Button>}
    </Stack>}/>
    <Menu anchorEl={exportAnchor} open={Boolean(exportAnchor)} onClose={() => setExportAnchor(null)}><MenuItem onClick={() => void runExport('pdf')}><PictureAsPdfOutlined fontSize="small"/>&nbsp; IDVS PDF</MenuItem><MenuItem onClick={() => void runExport('xlsx')}><Download fontSize="small"/>&nbsp; IDVS Excel</MenuItem><MenuItem onClick={() => void runExport('csv')}><Download fontSize="small"/>&nbsp; IDVS CSV</MenuItem></Menu>
    {error && <Alert severity="error" sx={{ mb: 2 }} onClose={() => setError('')}>{error}</Alert>}{notice && <Alert severity="success" sx={{ mb: 2 }} onClose={() => setNotice('')}>{notice}</Alert>}
    <Paper variant="outlined" sx={{ mb: 2, px: 2 }}><Tabs value={tab} onChange={(_event, value) => setTab(value)} variant="scrollable"><Tab label="Generated IDVS"/><Tab label={`Tracking history (${invoice.history.length})`}/><Tab label={`Supporting documents (${invoice.attachments.length})`}/></Tabs></Paper>
    {tab === 0 && <Paper variant="outlined" sx={{ p: { xs: 1, md: 2 }, overflow: 'hidden' }}><IdvsSheet invoice={invoice}/></Paper>}
    {tab === 1 && <Box display="grid" gap={2}>
      <SectionCard title="Commercial tracking milestones" subtitle="Only the milestone date and optional remarks are recorded here; EPICOR approval and payment remain external."><Stepper activeStep={activeStep} alternativeLabel nonLinear sx={{ overflowX: 'auto', pb: 1 }}>{[['IDVS created', invoice.idvs_date], ['Submitted', invoice.submitted_date], ['Verified & sent to Accounts', invoice.sent_to_accounts_date], ['Received for EPICOR approval', invoice.epicor_received_date], ['Approved in EPICOR', invoice.epicor_approved_date], ['Paid date', invoice.paid_date]].map(([name, value]) => <Step key={name} completed={Boolean(value)}><StepLabel><Typography fontSize={11}>{name}</Typography><Typography variant="caption" color="text.secondary">{formatDate(value)}</Typography></StepLabel></Step>)}</Stepper></SectionCard>
      <SectionCard title="Audited workflow history" subtitle="Every dated action includes the actor and optional remarks" bodyPadding={0}><TableContainer><Table><TableHead><TableRow><TableCell>Milestone</TableCell><TableCell>Action date</TableCell><TableCell>Recorded by</TableCell><TableCell>Remarks</TableCell><TableCell>Audit timestamp</TableCell></TableRow></TableHead><TableBody>{invoice.history.map(item => <TableRow key={item.id}><TableCell><Tag tone="info">{item.action_label}</Tag></TableCell><TableCell>{formatDate(item.action_date)}</TableCell><TableCell>{item.actor_name}</TableCell><TableCell>{item.remarks || '—'}</TableCell><TableCell>{new Date(item.created_at).toLocaleString()}</TableCell></TableRow>)}{!invoice.history.length && <TableRow><TableCell colSpan={5} align="center"><Typography color="text.secondary" py={4}>This draft has not entered the verification workflow.</Typography></TableCell></TableRow>}</TableBody></Table></TableContainer></SectionCard>
      <SectionCard title="Record metadata"><Typography fontSize={12} color="text.secondary">Created by {invoice.created_by} · {new Date(invoice.created_at).toLocaleString()}<br/>Last updated by {invoice.updated_by} · {new Date(invoice.updated_at).toLocaleString()}<br/>Payment reference: {invoice.payment_reference || '—'}<br/>General remarks: {invoice.remarks || '—'}</Typography></SectionCard>
    </Box>}
    {tab === 2 && <Box display="grid" gridTemplateColumns={{ xs: '1fr', lg: 'minmax(0,1fr) 340px' }} gap={2} alignItems="start">
      <SectionCard title="Supporting documents" subtitle="PDFs open in the browser through View. Excel and other browser-unsupported formats download explicitly." bodyPadding={0}><TableContainer><Table><TableHead><TableRow><TableCell>Document</TableCell><TableCell>Label / notes</TableCell><TableCell>Size</TableCell><TableCell>Uploaded</TableCell><TableCell align="right">Actions</TableCell></TableRow></TableHead><TableBody>{invoice.attachments.map(file => <TableRow key={file.id}><TableCell><Stack direction="row" gap={1} alignItems="center"><AttachFile color="action"/><Box><Typography fontSize={12} fontWeight={700}>{file.file_name}</Typography><Typography variant="caption" color="text.secondary">{file.content_type}</Typography></Box></Stack></TableCell><TableCell><Typography fontSize={12}>{file.label || '—'}</Typography><Typography variant="caption" color="text.secondary">{file.notes}</Typography></TableCell><TableCell>{formatFileSize(file.size_bytes)}</TableCell><TableCell><Typography fontSize={11}>{file.uploaded_by_name}</Typography><Typography variant="caption" display="block">{new Date(file.created_at).toLocaleString()}</Typography></TableCell><TableCell align="right"><Stack direction="row" justifyContent="flex-end">{can('invoice-processing:document-download') && <Tooltip title={file.can_inline ? 'View PDF in browser' : 'Download'}><IconButton onClick={() => void (file.can_inline ? previewFile(`/invoice-processing/attachments/${file.id}/content?inline=true`) : downloadFile(`/invoice-processing/attachments/${file.id}/content`, file.file_name))}>{file.can_inline ? <VisibilityOutlined/> : <Download/>}</IconButton></Tooltip>}{!invoice.is_deleted && can('invoice-processing:document-delete') && <Tooltip title="Delete document"><IconButton color="error" onClick={() => setRemove(file)}><DeleteOutline/></IconButton></Tooltip>}</Stack></TableCell></TableRow>)}{!invoice.attachments.length && <TableRow><TableCell colSpan={5} align="center"><Box py={5}><AttachFile color="disabled"/><Typography color="text.secondary" mt={1}>No supporting documents yet. Upload the invoice, field ticket, verification support or EPICOR reference.</Typography></Box></TableCell></TableRow>}</TableBody></Table></TableContainer></SectionCard>
      {!invoice.is_deleted && can('invoice-processing:document-upload') && <SectionCard title="Upload documents" subtitle="One or more files; each file has its own 25 MB limit."><Stack gap={1.5}><Button component="label" variant="outlined" startIcon={<UploadFile/>}>Choose supporting files<input hidden multiple type="file" accept=".pdf,.doc,.docx,.xls,.xlsx,.csv,.txt,.rtf,.png,.jpg,.jpeg,.msg,.eml" onChange={event => { chooseFiles(Array.from(event.target.files ?? [])); event.target.value = '' }}/></Button>{files.map(file => <Chip key={`${file.name}-${file.size}`} label={`${file.name} · ${formatFileSize(file.size)}`} onDelete={() => setFiles(current => current.filter(item => item !== file))}/>) }<TextField label="Label (optional, applied to this upload)" value={label} onChange={event => setLabel(event.target.value)} inputProps={{ maxLength: 200 }}/><TextField label="Notes (optional)" multiline minRows={2} value={notes} onChange={event => setNotes(event.target.value)} inputProps={{ maxLength: 500 }}/><Button variant="contained" disabled={!files.length || busy} onClick={() => void upload()}>{busy ? 'Uploading…' : `Upload ${files.length || ''} file${files.length === 1 ? '' : 's'}`}</Button><Typography variant="caption" color="text.secondary">Maximum 25 MB per document. Files are tenant-scoped, checksummed and audited; duplicate content on the same IDVS is rejected.</Typography></Stack></SectionCard>}
    </Box>}
    <FormDialog open={Boolean(workflow)} onClose={() => setWorkflow(null)} onSubmit={() => void runWorkflow()} busy={busy} dirty={Boolean(remarks || paymentReference)} title={workflowLabel} subtitle="Enter the external tracking date and optional remarks. The workflow order and milestone chronology are validated by the server." submitLabel={workflowLabel}><Stack gap={2} pt={.5}><TextField required type="date" label={workflow === 'payment' ? 'Paid date' : 'Milestone date'} value={actionDate} onChange={event => setActionDate(event.target.value)} InputLabelProps={{ shrink: true }}/>{workflow === 'payment' && <TextField label="Payment reference (optional)" value={paymentReference} onChange={event => setPaymentReference(event.target.value)}/>}<TextField label="Remarks (optional)" multiline minRows={3} value={remarks} onChange={event => setRemarks(event.target.value)} inputProps={{ maxLength: 1000 }}/></Stack></FormDialog>
    <FormDialog open={Boolean(remove)} onClose={() => setRemove(null)} onSubmit={() => void deleteAttachment()} busy={busy} danger title="Delete supporting document?" subtitle="The file is removed from this IDVS and the deletion is audited."><Typography>{remove?.file_name}</Typography></FormDialog>
  </Box>
}
