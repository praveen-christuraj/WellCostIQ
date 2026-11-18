import { useEffect, useState } from 'react'
import { Alert, Box, Button, MenuItem, TextField, Typography } from '@mui/material'
import { FormDialog } from '../Common'
import { useAuth } from '../../context/AuthContext'
import {
  extractReport,
  listDocuments,
  uploadDocument,
  type OpsDocument,
  type OpsReport,
  type OpsScopeReference,
} from '../../lib/operations'
import { FolderFields, type Folder } from './ScopeDirectory'

/** The vault only files originals. Parsing is an explicit Daily Reports action. */
export function SourceDialog({
  reference,
  initial,
  extract = false,
  report,
  onClose,
  onSaved,
}: {
  reference: OpsScopeReference
  initial: Folder | null
  extract?: boolean
  report?: OpsReport
  onClose: () => void
  onSaved: (report?: OpsReport, document?: OpsDocument) => void
}) {
  const { can } = useAuth()
  const [folder, setFolder] = useState<Folder>(initial ?? { well_id: '', scope: 'drilling' })
  const [type, setType] = useState(reference.document_types[0] ?? '')
  const [day, setDay] = useState(report?.report_date ?? '')
  const [files, setFiles] = useState<File[]>([])
  const [mode, setMode] = useState(extract ? 'vault' : 'upload')
  const [docs, setDocs] = useState<OpsDocument[]>([]),
    [docId, setDocId] = useState('')
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState(''),
    [busy, setBusy] = useState(false)
  useEffect(() => {
    // A just-opened folder may finish navigating while the dialog mounts.
    // Prefill once without replacing a destination the operator chose.
    if (initial?.well_id) setFolder((current) => (current.well_id ? current : initial))
  }, [initial?.well_id, initial?.scope])
  useEffect(() => {
    let current = true
    setDocId('')
    setDocs([])
    setLoading(false)
    if (extract && mode === 'vault' && folder.well_id) {
      setLoading(true)
      listDocuments({ ...folder })
        .then((d) => {
          if (current) setDocs(d)
        })
        .catch((e) => {
          if (current) setError(e.message)
        })
        .finally(() => {
          if (current) setLoading(false)
        })
    }
    return () => {
      current = false
    }
  }, [extract, mode, folder])
  const save = async () => {
    setBusy(true)
    setError('')
    try {
      let uploaded: OpsDocument | undefined
      if (mode === 'upload') {
        for (const file of files)
          uploaded = await uploadDocument(file, { ...folder, document_type: type, document_date: day })
      }
      if (extract) onSaved(await extractReport(uploaded?.id ?? docId, day, report?.id))
      else onSaved(undefined, uploaded)
    } catch (e) {
      setError((e as Error).message)
    } finally {
      setBusy(false)
    }
  }
  return (
    <FormDialog
      open
      title={extract ? 'Extract a report draft' : 'Upload source document'}
      subtitle={
        extract
          ? 'Review the extracted measurements and time log before submitting. Existing time blocks are never replaced.'
          : 'The original file stays in this well and scope folder. Uploading does not create a daily report.'
      }
      maxWidth={extract ? false : 'sm'}
      onClose={onClose}
      onSubmit={save}
      busy={busy}
      busyLabel={extract ? 'Extracting for review…' : 'Uploading…'}
      submitLabel={extract ? 'Extract for review' : 'Upload'}
      submitDisabled={!folder.well_id || (mode === 'upload' ? !files.length || !type : !docId)}
    >
      <Box
        component="fieldset"
        disabled={busy}
        sx={{
          border: 0,
          p: 0,
          pt: 1,
          m: 0,
          minWidth: 0,
          display: 'grid',
          gap: 2,
          gridTemplateColumns: extract ? { xs: '1fr', md: 'repeat(2,minmax(0,1fr))' } : '1fr',
        }}
      >
        {!report && <FolderFields reference={reference} folder={folder} change={setFolder} />}
        {extract && can('ops-doc:upload') && (
          <TextField select label="Source" value={mode} onChange={(e) => setMode(e.target.value)}>
            <MenuItem value="vault">Choose from Documents</MenuItem>
            <MenuItem value="upload">Upload a new file</MenuItem>
          </TextField>
        )}
        {mode === 'vault' ? (
          <TextField
            select
            label="Filed document"
            value={docId}
            disabled={!folder.well_id || loading || !docs.length}
            helperText={
              loading
                ? 'Loading files…'
                : !folder.well_id
                  ? 'Choose a well and scope first.'
                  : !docs.length
                    ? 'No files in this folder. Upload a source document first.'
                    : `${docs.length} filed document(s) in this well and scope.`
            }
            onChange={(e) => setDocId(e.target.value)}
          >
            {docs.map((d) => (
              <MenuItem key={d.id} value={d.id}>
                {d.document_date ?? 'Undated'} · {d.document_type} · {d.file_name}
              </MenuItem>
            ))}
          </TextField>
        ) : (
          <>
            <TextField select label="Document type" value={type} onChange={(e) => setType(e.target.value)}>
              {reference.document_types.map((t) => (
                <MenuItem key={t} value={t}>
                  {t}
                </MenuItem>
              ))}
            </TextField>
            <Button variant="outlined" component="label" disabled={busy}>
              Choose {extract ? 'PDF or Excel' : 'file'}
              <input
                hidden
                type="file"
                multiple={!extract}
                accept={extract ? '.pdf,.xlsx,.xlsm' : '.pdf,.xlsx,.xlsm,.xls,.csv,.docx'}
                onChange={(e) => setFiles(Array.from(e.target.files ?? []))}
              />
            </Button>
            <Typography variant="body2">{files.map((f) => f.name).join(', ') || 'No file selected'}</Typography>
          </>
        )}
        <TextField
          type="date"
          label="Report date"
          value={day}
          disabled={!!report}
          onChange={(e) => setDay(e.target.value)}
          slotProps={{ inputLabel: { shrink: true } }}
          helperText={
            extract
              ? 'Choose a day for a multi-day Summary workbook. Leave blank to use the PDF or mud report date.'
              : undefined
          }
        />
        {busy && (
          <Typography role="status">
            {extract
              ? 'Reading the source. The editable daily draft opens when extraction completes.'
              : 'Filing the original documents…'}
          </Typography>
        )}
        {error && <Alert severity="error">{error}</Alert>}
      </Box>
    </FormDialog>
  )
}
