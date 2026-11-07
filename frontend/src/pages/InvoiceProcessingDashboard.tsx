import { useCallback, useEffect, useMemo, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { Add, ArrowForward, AssessmentOutlined, AttachFile, BlockOutlined, BusinessOutlined, CheckCircleOutline, FileDownloadOutlined, PendingActionsOutlined, ReceiptLongOutlined, SettingsOutlined, WarningAmberOutlined } from '@mui/icons-material'
import { Alert, Box, Button, Chip, MenuItem, Paper, Stack, Table, TableBody, TableCell, TableContainer, TableHead, TableRow, TextField, Typography, useTheme } from '@mui/material'
import { PageHeading, Tag } from '../components/Common'
import { ChartPanel } from '../components/ui/ChartPanel'
import { InteractiveChart } from '../components/ui/InteractiveChart'
import { SectionCard } from '../components/ui/SectionCard'
import { StatCard } from '../components/ui/StatCard'
import { useAuth } from '../context/AuthContext'
import { api, body } from '../lib/api'
import { chartPalette } from '../designSystem'
import { useColorMode } from '../context/ThemeContext'
import { formatAmount, formatDate } from '../lib/invoiceCalculations'
import { INVOICE_STATUS_LABEL, type InvoiceDashboard } from '../lib/invoiceProcessing'
import { exportInvoiceDashboardPdf } from '../lib/invoiceExport'

const toneForStatus = (status: string): 'neutral' | 'success' | 'info' | 'warning' | 'error' =>
  status === 'paid' || status === 'approved' ? 'success' : status === 'draft' ? 'neutral' : status === 'submitted' || status === 'sent_to_accounts' ? 'info' : 'warning'

export default function InvoiceProcessingDashboard() {
  const navigate = useNavigate()
  const { can } = useAuth()
  const theme = useTheme()
  const { mode } = useColorMode()
  const [data, setData] = useState<InvoiceDashboard | null>(null)
  const [currency, setCurrency] = useState('')
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState('')
  const load = useCallback(async () => {
    setLoading(true); setError('')
    try { setData(await api<InvoiceDashboard>('/invoice-processing/dashboard')) }
    catch (caught) { setError((caught as Error).message) }
    finally { setLoading(false) }
  }, [])
  useEffect(() => { void load() }, [load])
  useEffect(() => {
    if (data?.currency_totals.length && !data.currency_totals.some(row => row.currency_code === currency)) setCurrency(data.currency_totals[0].currency_code)
  }, [data, currency])
  const total = data?.currency_totals.find(row => row.currency_code === currency) ?? data?.currency_totals[0]
  const vendors = useMemo(() => data?.vendor_rows.filter(row => row.currency_code === (total?.currency_code ?? '')) ?? [], [data, total])
  const blocks = useMemo(() => data?.block_rows.filter(row => row.currency_code === (total?.currency_code ?? '')) ?? [], [data, total])
  const ageing = useMemo(() => data?.ageing_rows.filter(row => row.currency_code === (total?.currency_code ?? '')) ?? [], [data, total])
  const palette = chartPalette(mode)
  const colors = {
    axisLabel: { color: theme.palette.text.secondary },
    axisLine: { lineStyle: { color: theme.palette.divider } },
    splitLine: { lineStyle: { color: theme.palette.divider } },
    gridText: theme.palette.text.secondary, accent: palette.series[0], accentAlt: palette.series[1],
    warning: theme.palette.warning.main, positive: theme.palette.success.main,
  }
  const statusOption = {
    animation: false, grid: { left: 40, right: 16, top: 20, bottom: 64 },
    tooltip: { trigger: 'axis' },
    xAxis: { type: 'category', data: data?.status_counts.map(row => row.label.replace('Verified & sent to ', '').replace('Received for ', '')) ?? [], axisLabel: { ...colors.axisLabel, interval: 0, rotate: 25, fontSize: 10 }, axisLine: colors.axisLine, axisTick: { show: false } },
    yAxis: { type: 'value', minInterval: 1, axisLabel: colors.axisLabel, splitLine: colors.splitLine },
    series: [{ type: 'bar', barMaxWidth: 44, data: data?.status_counts.map((row, index) => ({ value: row.count, itemStyle: { color: [colors.gridText, colors.accent, colors.accentAlt, colors.warning, colors.positive, colors.positive][index] } })) ?? [] }],
  }
  const vendorOption = {
    animation: false, grid: { left: 150, right: 32, top: 20, bottom: 36 },
    tooltip: { trigger: 'axis', valueFormatter: (value: number) => `${total?.currency_code ?? ''} ${formatAmount(value)}` },
    xAxis: { type: 'value', axisLabel: colors.axisLabel, splitLine: colors.splitLine },
    yAxis: { type: 'category', inverse: true, data: vendors.slice(0, 8).map(row => row.vendor_name), axisLabel: { ...colors.axisLabel, width: 135, overflow: 'truncate' }, axisLine: colors.axisLine, axisTick: { show: false } },
    series: [{ type: 'bar', barMaxWidth: 22, itemStyle: { color: colors.accent, borderRadius: [0, 3, 3, 0] }, data: vendors.slice(0, 8).map(row => Number(row.verified_total)) }],
  }
  const exportPdf = async () => {
    if (!data) return
    exportInvoiceDashboardPdf(data, currency || total?.currency_code || '')
    await api('/invoice-processing/export-audit', { method: 'POST', body: body({ module: 'dashboard', format: 'pdf', record_count: data.total_invoices, detail: currency || total?.currency_code || 'all currencies' }) })
  }
  return <Box>
    <PageHeading eyebrow="Commercial Control" title="Invoice Processing" subtitle="From invoice receipt and verification through EPICOR tracking—without losing the commercial detail behind every IDVS." action={<Stack direction="row" gap={1} flexWrap="wrap">
      <Button variant="outlined" startIcon={<AssessmentOutlined/>} onClick={() => navigate('/invoice-processing/register')}>IDVS register</Button>
      {can('invoice-processing:configure') && <Button variant="outlined" startIcon={<SettingsOutlined/>} onClick={() => navigate('/invoice-processing/configuration')}>Configuration</Button>}
      <Button variant="outlined" startIcon={<FileDownloadOutlined/>} disabled={!data} onClick={() => void exportPdf()}>Export PDF</Button>
      {can('invoice-processing:create') && <Button variant="contained" startIcon={<Add/>} onClick={() => navigate('/invoice-processing/idvs/new')}>New IDVS</Button>}
    </Stack>}/>
    {error && <Alert severity="error" sx={{ mb: 2 }} onClose={() => setError('')}>{error}</Alert>}
    <Paper variant="outlined" sx={{ p: 1.5, mb: 2, display: 'flex', alignItems: 'center', justifyContent: 'space-between', gap: 2, flexWrap: 'wrap' }}>
      <Box><Typography fontWeight={750} fontSize={13}>Financial view</Typography><Typography variant="caption" color="text.secondary">Amounts are deliberately separated by currency; no exchange-rate conversion is applied to dashboard totals.</Typography></Box>
      <TextField select size="small" label="Currency" value={total?.currency_code ?? ''} onChange={event => setCurrency(event.target.value)} disabled={!data?.currency_totals.length} sx={{ minWidth: 170 }}><MenuItem value="" disabled>No invoice amounts</MenuItem>{data?.currency_totals.map(row => <MenuItem key={row.currency_code} value={row.currency_code}>{row.currency_code} · {row.invoice_count} invoice{row.invoice_count === 1 ? '' : 's'}</MenuItem>)}</TextField>
    </Paper>
    <Box display="grid" gridTemplateColumns="repeat(auto-fit,minmax(175px,1fr))" gap={1.5} mb={2}>
      <StatCard label="Active IDVS" value={data?.total_invoices ?? '—'} hint="Across all currencies and blocks" icon={<ReceiptLongOutlined/>} onClick={() => navigate('/invoice-processing/register')}/>
      <StatCard label={`Verified · ${total?.currency_code ?? 'currency'}`} value={total ? formatAmount(total.verified_total) : '—'} hint={`${total?.invoice_count ?? 0} invoice(s) in this currency`} icon={<BusinessOutlined/>}/>
      <StatCard label="IDVS amount" value={total ? `${total.currency_code} ${formatAmount(total.adjusted_verified_amount)}` : '—'} hint="Verified total less disallowed and advances; the IDVS report total" icon={<ReceiptLongOutlined/>}/>
      <StatCard label="Net payable" value={total ? `${total.currency_code} ${formatAmount(total.net_payable_amount)}` : '—'} hint="Register amount after every net-payable tax, including register-only taxes" icon={<CheckCircleOutline/>} tone="positive"/>
      <StatCard label="Awaiting action" value={(data?.verification_count ?? 0) + (data?.epicor_count ?? 0)} hint={`${data?.verification_count ?? 0} verification · ${data?.epicor_count ?? 0} EPICOR`} icon={<PendingActionsOutlined/>} tone="info"/>
      <StatCard label="Overdue unpaid" value={data?.overdue_count ?? '—'} hint="Due date passed; not yet marked paid" icon={<WarningAmberOutlined/>} tone={data?.overdue_count ? 'error' : 'default'} onClick={() => navigate('/invoice-processing/register?overdue=true')}/>
      <StatCard label="Supporting files" value={data?.attachment_count ?? '—'} hint="Retained against active IDVS records" icon={<AttachFile/>}/>
    </Box>
    <Box display="grid" gridTemplateColumns={{ xs: '1fr', xl: '1.15fr .85fr' }} gap={2} mb={2}>
      <ChartPanel title="Workflow pipeline" subtitle="Active invoice count at each commercial tracking milestone" meta={<Chip size="small" label="Invoices"/>} height={292} empty={!data?.total_invoices} caption="Paid is a tracking state derived from the recorded paid date. EPICOR approval and payment remain external systems.">
        <InteractiveChart option={statusOption} style={{ height: '100%' }}/>
      </ChartPanel>
      <ChartPanel title={`Vendor exposure · ${total?.currency_code ?? ''}`} subtitle="Verified totals, highest first" meta={<Chip size="small" label={total?.currency_code ?? 'No currency'}/>} height={292} empty={!vendors.length} emptyMessage="No vendor values in the selected currency." caption="Only invoices in the selected currency are included. Select another currency above rather than summing unlike amounts.">
        <InteractiveChart option={vendorOption} style={{ height: '100%' }}/>
      </ChartPanel>
    </Box>
    <Box display="grid" gridTemplateColumns={{ xs: '1fr', lg: '1fr 1fr' }} gap={2} mb={2}>
      <SectionCard title="Block-wise position" subtitle={`Own and JV blocks · ${total?.currency_code ?? ''}`} bodyPadding={0}>
        <TableContainer sx={{ maxHeight: 340 }}><Table size="small" stickyHeader><TableHead><TableRow><TableCell>Block</TableCell><TableCell>Class</TableCell><TableCell align="right">IDVS</TableCell><TableCell align="right">Verified total</TableCell></TableRow></TableHead><TableBody>
          {blocks.map(row => <TableRow key={`${row.block_id}-${row.currency_code}`} hover><TableCell><Typography fontWeight={700} fontSize={12}>{row.block_code}</Typography><Typography variant="caption" color="text.secondary">{row.block_name}</Typography></TableCell><TableCell><Tag tone={!row.block_id ? 'neutral' : row.block_category === 'jv' ? 'info' : row.block_category === 'own' ? 'success' : 'warning'}>{!row.block_id ? 'Common scope' : row.block_category === 'jv' ? 'JV Block' : row.block_category === 'own' ? 'Own Block' : 'Unclassified'}</Tag></TableCell><TableCell align="right">{row.invoice_count}</TableCell><TableCell align="right">{formatAmount(row.verified_total)}</TableCell></TableRow>)}
          {!blocks.length && <TableRow><TableCell colSpan={4}><Typography color="text.secondary" py={4} align="center">No invoices have been saved in this currency yet.</Typography></TableCell></TableRow>}
        </TableBody></Table></TableContainer>
      </SectionCard>
      <SectionCard title="Due-date ageing" subtitle="Unpaid register amounts by currency" bodyPadding={0}>
        <TableContainer sx={{ maxHeight: 340 }}><Table size="small" stickyHeader><TableHead><TableRow><TableCell>Ageing bucket</TableCell><TableCell align="right">IDVS</TableCell><TableCell align="right">IDVS amount</TableCell><TableCell align="right">Net payable</TableCell></TableRow></TableHead><TableBody>
          {ageing.map(row => <TableRow key={row.bucket}><TableCell>{row.bucket}</TableCell><TableCell align="right">{row.invoice_count}</TableCell><TableCell align="right">{total?.currency_code} {formatAmount(row.adjusted_verified_amount)}</TableCell><TableCell align="right">{total?.currency_code} {formatAmount(row.net_payable_amount)}</TableCell></TableRow>)}
          {!ageing.length && <TableRow><TableCell colSpan={4}><Typography color="text.secondary" py={4} align="center">No unpaid ageing in the selected currency.</Typography></TableCell></TableRow>}
        </TableBody></Table></TableContainer>
      </SectionCard>
    </Box>
    <SectionCard title="Latest tracking activity" subtitle="The most recent dated workflow events, with actor and optional remarks" bodyPadding={0}>
      <TableContainer><Table size="small"><TableHead><TableRow><TableCell>IDVS / invoice</TableCell><TableCell>Vendor</TableCell><TableCell>Milestone</TableCell><TableCell>Date</TableCell><TableCell>Recorded by</TableCell><TableCell/></TableRow></TableHead><TableBody>
        {data?.recent_activity.map(row => <TableRow key={row.id} hover><TableCell><Typography fontWeight={700} fontSize={12}>{row.idvs_number}</Typography><Typography variant="caption" color="text.secondary">{row.invoice_number}</Typography></TableCell><TableCell>{row.vendor_name}</TableCell><TableCell><Tag tone={toneForStatus(row.action_label)}>{row.action_label}</Tag></TableCell><TableCell>{formatDate(row.action_date)}</TableCell><TableCell>{row.actor_name}</TableCell><TableCell align="right"><Button size="small" endIcon={<ArrowForward/>} onClick={() => navigate(`/invoice-processing/idvs/${row.invoice_id}/view`)}>Open</Button></TableCell></TableRow>)}
        {!data?.recent_activity.length && <TableRow><TableCell colSpan={6}><Box py={5} textAlign="center"><BlockOutlined color="disabled"/><Typography color="text.secondary" mt={1}>{loading ? 'Loading invoice activity…' : 'No workflow activity yet. Create an IDVS and submit it to start the tracking trail.'}</Typography></Box></TableCell></TableRow>}
      </TableBody></Table></TableContainer>
    </SectionCard>
    {data && <Stack direction="row" gap={1} mt={2} flexWrap="wrap"><Tag tone="success">{data.own_block_count} Own Block invoice(s)</Tag><Tag tone="info">{data.jv_block_count} JV Block invoice(s)</Tag><Tag tone={data.unclassified_block_count ? 'warning' : 'neutral'}>{data.unclassified_block_count} unclassified scope</Tag><Typography variant="caption" color="text.secondary" ml="auto">As of {formatDate(data.as_of)} · {INVOICE_STATUS_LABEL.paid} is included only after a paid date is recorded.</Typography></Stack>}
  </Box>
}
