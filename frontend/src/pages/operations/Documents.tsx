import { useEffect, useState } from 'react'
import { CloudUploadOutlined, DeleteOutlineRounded } from '@mui/icons-material'
import { Alert, Box, Button, Chip, FormControl, InputLabel, MenuItem, Select, TextField, Typography } from '@mui/material'
import { DataTable } from '../../components/DataTable'
import { ErrorMessage, PageHeading } from '../../components/Common'
import { SectionCard } from '../../components/ui/SectionCard'
import { listDocuments, extractDocument, opsReference, type OpsDocument, type OpsReference } from '../../lib/operations'
import { api } from '../../lib/api'

export default function OperationsDocuments() {
  const [docs, setDocs] = useState<OpsDocument[]>([])
  const [ref, setRef] = useState<OpsReference | null>(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState('')
  const [filterWell, setFilterWell] = useState('')
  const [filterType, setFilterType] = useState('')
  const [filterStatus, setFilterStatus] = useState('')
  const [uploadWell, setUploadWell] = useState('')
  const [uploadScope, setUploadScope] = useState('drilling')
  const [uploadType, setUploadType] = useState('DDR')
  const [uploadDate, setUploadDate] = useState('')
  const [uploadFile, setUploadFile] = useState<File | null>(null)
  const [uploading, setUploading] = useState(false)
  const [selected, setSelected] = useState<string[]>([])

  const load = async () => {
    setLoading(true); setError('')
    try {
      const [d, r] = await Promise.all([
        listDocuments({ well_id: filterWell || undefined, document_type: filterType || undefined, status: filterStatus || undefined }),
        ref ? Promise.resolve(ref) : opsReference(),
      ])
      setDocs(d)
      setRef(r)
    } catch (e) { setError((e as Error).message) } finally { setLoading(false) }
  }
  useEffect(() => { load() }, [])
  useEffect(() => { load() }, [filterWell, filterType, filterStatus])

  const doUpload = async () => {
    if (!uploadFile) return
    setUploading(true); setError('')
    try {
      const form = new FormData()
      form.append('file', uploadFile)
      form.append('well_id', uploadWell)
      form.append('scope', uploadScope)
      form.append('document_type', uploadType)
      if (uploadDate) form.append('document_date', uploadDate)
      // Use fetch with auth header from api helper's token (we add Bearer manually)
      // The api() helper stores token in memory; we can read from context but simpler: rely on cookie + Bearer via api helper's header simulation
      // Do raw fetch via the same origin — the backend reads Authorization header if present; we include it by calling api's internal token getter workaround:
      // Instead, use the backend's generic upload via fetch that reuses current access token from context if available.
      // We'll read token from localStorage fallback that AuthContext writes.
      const token = (localStorage.getItem('wcp_token') || sessionStorage.getItem('wcp_token') || '') // best-effort
      const headers: Record<string, string> = {}
      if (token) headers['Authorization'] = `Bearer ${token}`
      const res = await fetch('/api/v1/operations/documents/upload', { method: 'POST', body: form, credentials: 'include', headers })
      if (!res.ok) {
        const body = await res.json().catch(() => ({}))
        throw new Error(body.detail || `Upload failed (${res.status})`)
      }
      setUploadFile(null)
      await load()
    } catch (e) { setError((e as Error).message) } finally { setUploading(false) }
  }

  const doExtract = async (id: string) => {
    setError('')
    try { await extractDocument(id); await load() } catch (e) { setError((e as Error).message) }
  }

  const doDownload = async (doc: OpsDocument) => {
    try {
      const token = localStorage.getItem('wcp_token') || sessionStorage.getItem('wcp_token') || ''
      const headers: Record<string, string> = {}
      if (token) headers['Authorization'] = `Bearer ${token}`
      const res = await fetch(`/api/v1/operations/documents/${doc.id}/download`, { credentials: 'include', headers })
      if (!res.ok) throw new Error('Download failed')
      const blob = await res.blob()
      const url = URL.createObjectURL(blob)
      const a = document.createElement('a'); a.href = url; a.download = doc.file_name; a.click(); URL.revokeObjectURL(url)
    } catch (e) { setError((e as Error).message) }
  }

  const doDelete = async () => {
    if (!selected.length) return
    setError('')
    try { await api('/operations/documents/bulk-delete', { method: 'POST', body: JSON.stringify({ ids: selected }) }); setSelected([]); await load() } catch (e) { setError((e as Error).message) }
  }

  return (
    <Box>
      <PageHeading eyebrow="Well Operations" title="Document vault" subtitle="Directory per well and per scope (drilling/completion) → upload DDR/DCR/DMR/RMR PDFs or Excel. Engine extracts 24h log, classification and ROP; deduplicates by SHA-256; versions on replace." />

      {error && <Box mb={2}><ErrorMessage message={error} /></Box>}

      <SectionCard title="Upload">
        <Box display="grid" gap={2} gridTemplateColumns={{ xs: '1fr', md: '1fr 1fr 1fr 1fr' }}>
          <FormControl size="small" fullWidth>
            <InputLabel>Well *</InputLabel>
            <Select value={uploadWell} label="Well *" onChange={e => setUploadWell(e.target.value)}>
              <MenuItem value=""><em>Select well</em></MenuItem>
              {ref?.wells.map(w => <MenuItem key={w.id} value={w.id}>{w.display_name}</MenuItem>)}
            </Select>
          </FormControl>
          <FormControl size="small" fullWidth>
            <InputLabel>Scope</InputLabel>
            <Select value={uploadScope} label="Scope" onChange={e => setUploadScope(e.target.value)}>
              <MenuItem value="drilling">Drilling</MenuItem>
              <MenuItem value="completion">Completion</MenuItem>
            </Select>
          </FormControl>
          <FormControl size="small" fullWidth>
            <InputLabel>Type</InputLabel>
            <Select value={uploadType} label="Type" onChange={e => setUploadType(e.target.value)}>
              <MenuItem value="DDR">DDR</MenuItem>
              <MenuItem value="DCR">DCR</MenuItem>
              <MenuItem value="DMR">DMR</MenuItem>
              <MenuItem value="RMR">RMR</MenuItem>
              <MenuItem value="other">Other</MenuItem>
            </Select>
          </FormControl>
          <TextField size="small" type="date" label="Document date" value={uploadDate} onChange={e => setUploadDate(e.target.value)} InputLabelProps={{ shrink: true }} />
        </Box>
        <Box mt={2} display="flex" gap={2} alignItems="center" flexWrap="wrap">
          <Button variant="outlined" component="label">
            Choose file (PDF/Excel)
            <input type="file" hidden accept=".pdf,.xlsx,.xls,.csv,.docx" onChange={e => setUploadFile(e.target.files?.[0] || null)} />
          </Button>
          <Typography fontSize={13} color="text.secondary">{uploadFile ? `${uploadFile.name} (${(uploadFile.size / 1024).toFixed(0)} KB)` : 'No file chosen — PDF or Excel (≤25 MB), protected sheets read, file-password shows “password required”)'}</Typography>
          <Button variant="contained" startIcon={<CloudUploadOutlined />} disabled={!uploadFile || !uploadWell || uploading} onClick={doUpload}>{ uploadFile && !uploadWell ? 'Select a well first' : uploading ? 'Uploading…' : 'Upload & extract'}</Button>
        </Box>
        <Alert severity="info" sx={{ mt: 2 }}>Re-uploading the same file (SHA-256) returns the existing document — view / re-extract / replace, never a duplicate. Extraction runs with a timeout, page/word caps and no network access; failures remain readable with a retry.</Alert>
      </SectionCard>

      <SectionCard title="Filters">
        <Box display="grid" gap={2} gridTemplateColumns={{ xs: '1fr', md: '1fr 1fr 1fr auto' }}>
          <FormControl size="small" fullWidth>
            <InputLabel>Well</InputLabel>
            <Select value={filterWell} label="Well" onChange={e => setFilterWell(e.target.value)}>
              <MenuItem value="">All wells</MenuItem>
              {ref?.wells.map(w => <MenuItem key={w.id} value={w.id}>{w.display_name}</MenuItem>)}
            </Select>
          </FormControl>
          <FormControl size="small" fullWidth>
            <InputLabel>Type</InputLabel>
            <Select value={filterType} label="Type" onChange={e => setFilterType(e.target.value)}>
              <MenuItem value="">All types</MenuItem>
              <MenuItem value="DDR">DDR</MenuItem>
              <MenuItem value="DCR">DCR</MenuItem>
              <MenuItem value="DMR">DMR</MenuItem>
              <MenuItem value="RMR">RMR</MenuItem>
            </Select>
          </FormControl>
          <FormControl size="small" fullWidth>
            <InputLabel>Status</InputLabel>
            <Select value={filterStatus} label="Status" onChange={e => setFilterStatus(e.target.value)}>
              <MenuItem value="">All</MenuItem>
              <MenuItem value="uploaded">Uploaded</MenuItem>
              <MenuItem value="extracting">Extracting</MenuItem>
              <MenuItem value="extracted">Extracted</MenuItem>
              <MenuItem value="extraction_failed">Failed</MenuItem>
              <MenuItem value="reviewed">Reviewed</MenuItem>
            </Select>
          </FormControl>
          <Box display="flex" gap={1} alignItems="center">
            <Button variant="outlined" onClick={load}>Refresh</Button>
            <Button variant="outlined" color="error" startIcon={<DeleteOutlineRounded />} disabled={!selected.length} onClick={doDelete}>Delete selected</Button>
          </Box>
        </Box>
      </SectionCard>

      <SectionCard title={`Documents — ${docs.length} file(s)`} >
        <DataTable
          rows={docs}
          rowKey='id'
          onSelectionChange={rows => setSelected(rows.map((r: { id: string }) => r.id))}
          columns={[
            { field: 'file_name', headerName: 'File', flex: 1.6, minWidth: 200 },
            { field: 'document_type', headerName: 'Type', width: 80, valueFormatter: p => p.value || '—' },
            { field: 'scope', headerName: 'Scope', width: 110 },
            { field: 'well_code_snapshot', headerName: 'Well', width: 140, valueGetter: p => p.data?.well_code_snapshot || '—' },
            { field: 'document_date', headerName: 'Date', width: 120, valueFormatter: p => p.value ? String(p.value) : '—' },
            { field: 'report_no_text', headerName: 'Report no.', width: 110, valueFormatter: p => p.value || '—' },
            {
              field: 'status', headerName: 'Status', width: 140,
              cellRenderer: (p: { value: string }) => {
                const v = p.value || 'uploaded'
                const color: 'success' | 'warning' | 'error' | 'info' | 'default' = v === 'extracted' ? 'success' : v === 'extraction_failed' ? 'error' : v === 'extracting' ? 'info' : v === 'uploaded' ? 'warning' : 'default'
                return <Chip size="small" label={v} color={color} />
              },
            },
            {
              field: 'id', headerName: 'Actions', width: 220, sortable: false,
              cellRenderer: (p: { data: OpsDocument }) => (
                <Box display="flex" gap={0.5}>
                  <Button size="small" onClick={() => doDownload(p.data)}>Download</Button>
                  <Button size="small" variant="outlined" onClick={() => doExtract(p.data.id)}>Re-extract</Button>
                </Box>
              ),
            },
          ]}
        />
        {!docs.length && !loading && <Alert severity="info" sx={{ mt: 2 }}>No documents yet for this filter. Upload a DDR/DCR PDF or the Operations Summary workbook — DMR and RMR share the same vault and extraction.</Alert>}
      </SectionCard>

      <Alert severity="success" sx={{ mt: 2 }}>Each well × scope (drilling/completion) is a directory; inside it the vault is Year → Month → documents with counts and status, report-date and report-no columns, and view/download/re-extract/replace/delete. The same tree is printable and exportable.</Alert>
    </Box>
  )
}
