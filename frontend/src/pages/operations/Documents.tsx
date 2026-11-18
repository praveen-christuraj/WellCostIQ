import { useEffect, useState } from 'react'
import { CloudUploadOutlined, DownloadOutlined, RestoreRounded } from '@mui/icons-material'
import { Alert, Box, Button, MenuItem, TextField } from '@mui/material'
import { DataTable } from '../../components/DataTable'
import { ErrorMessage, FormDialog, PageHeading } from '../../components/Common'
import { ScopeDirectory, type Folder } from '../../components/operations/ScopeDirectory'
import { SourceDialog } from '../../components/operations/SourceDialog'
import { useRegisterActions } from '../../components/operations/RegisterActions'
import { useAuth } from '../../context/AuthContext'
import { api, body, downloadFile } from '../../lib/api'
import {
  auditExport,
  listDeletedDocuments,
  listDocuments,
  opsScopeReference,
  type OpsDocument,
  type OpsScopeReference,
} from '../../lib/operations'

export default function OperationsDocuments() {
  const { can } = useAuth()
  const [rows, setRows] = useState<OpsDocument[]>([]),
    [ref, setRef] = useState<OpsScopeReference | null>(null),
    [deleted, setDeleted] = useState(false),
    [upload, setUpload] = useState(false)
  const [folder, setFolder] = useState<Folder | null>(null),
    [error, setError] = useState(''),
    [editing, setEditing] = useState<OpsDocument | null>(null),
    [busy, setBusy] = useState(false),
    [saveError, setSaveError] = useState('')
  const getRows = () => (deleted ? listDeletedDocuments() : listDocuments({}))
  const refresh = async () => {
    setRows(await getRows())
  }
  const controls = useRegisterActions<OpsDocument>('documents', deleted, refresh)
  useEffect(() => {
    let current = true
    setRows([])
    setError('')
    getRows()
      .then((d) => {
        if (current) setRows(d)
      })
      .catch((e) => {
        if (current) setError(e.message)
      })
    return () => {
      current = false
    }
  }, [deleted])
  useEffect(() => {
    opsScopeReference()
      .then(setRef)
      .catch((e) => setError(e.message))
  }, [])
  return (
    <Box>
      <PageHeading
        eyebrow="Well Operations"
        title={deleted ? 'Deleted documents' : 'Documents'}
        subtitle="Original reports filed by rig, well and scope. Use Daily reports to extract a draft from a filed document."
        action={
          <Box display="flex" gap={1} flexWrap="wrap">
            {!deleted && can('ops-doc:upload') && (
              <Button variant="contained" startIcon={<CloudUploadOutlined />} disabled={!ref} onClick={() => setUpload(true)}>
                Upload documents
              </Button>
            )}
            <Button
              variant="outlined"
              startIcon={<RestoreRounded />}
              onClick={() => {
                controls.clear()
                setFolder(null)
                setDeleted(!deleted)
              }}
            >
              {deleted ? 'Active documents' : 'Deleted entries'}
            </Button>
          </Box>
        }
      />
      {error && <ErrorMessage message={error} />}
      <ScopeDirectory
        rows={rows}
        reference={ref}
        folder={folder}
        change={(f) => {
          controls.clear()
          setFolder(f)
        }}
      />
      {controls.bar}
      <DataTable
        rows={folder ? rows.filter((r) => (r.well_id ?? '') === folder.well_id && r.scope === folder.scope) : rows}
        selectable
        exportSelected
        onSelectionChange={controls.setSelected}
        selectionResetKey={controls.resetKey}
        fillHeight
        exportName="operations-document-index"
        canExport={can('ops-doc:export')}
        onExport={auditExport('documents')}
        columns={[
          { field: 'file_name', headerName: 'File name', minWidth: 230 },
          { field: 'document_type', headerName: 'Type' },
          { field: 'document_date', headerName: 'Document date' },
          { field: 'rig_code_snapshot', headerName: 'Rig' },
          { field: 'well_code_snapshot', headerName: 'Well' },
          { field: 'scope', headerName: 'Scope' },
          { field: 'uploaded_by_name', headerName: 'Filed by' },
          { field: 'notes', headerName: 'Notes' },
          {
            headerName: 'Actions',
            width: 260,
            minWidth: 245,
            sortable: false,
            cellRenderer: ({ data: r }: { data: OpsDocument }) => (
              <Box display="flex" alignItems="center" height="100%">
                {!deleted && can('ops-doc:download') && (
                  <Button
                    size="small"
                    aria-label={`Download ${r.file_name}`}
                    onClick={() =>
                      downloadFile(`/operations/documents/${r.id}/download`, r.file_name).catch((e) => setError(e.message))
                    }
                  >
                    <DownloadOutlined />
                  </Button>
                )}
                {!deleted && can('ops-doc:update') && (
                  <Button
                    size="small"
                    onClick={() => {
                      setEditing(r)
                      setSaveError('')
                    }}
                  >
                    Edit
                  </Button>
                )}
                {controls.actions([r])}
              </Box>
            ),
          },
        ]}
      />
      {controls.dialog}
      {upload && ref && (
        <SourceDialog
          reference={ref}
          initial={folder}
          onClose={() => setUpload(false)}
          onSaved={() => {
            setUpload(false)
            refresh().catch((e) => setError(e.message))
          }}
        />
      )}
      {editing && (
        <FormDialog
          open
          title="Edit document details"
          onClose={() => setEditing(null)}
          onSubmit={async () => {
            setBusy(true)
            try {
              await api(`/operations/documents/${editing.id}`, {
                method: 'PUT',
                body: body({
                  document_type: editing.document_type,
                  document_date: editing.document_date,
                  notes: editing.notes,
                }),
              })
              await refresh()
              setEditing(null)
            } catch (e) {
              setSaveError((e as Error).message)
            } finally {
              setBusy(false)
            }
          }}
          busy={busy}
        >
          <Box display="grid" gap={2} pt={1}>
            <TextField
              label="Type"
              select
              value={editing.document_type}
              onChange={(e) => setEditing({ ...editing, document_type: e.target.value })}
            >
              {[...new Set([editing.document_type, ...(ref?.document_types ?? [])])].map((t) => (
                <MenuItem key={t} value={t}>
                  {t}
                </MenuItem>
              ))}
            </TextField>
            <TextField
              type="date"
              label="Document date"
              value={editing.document_date ?? ''}
              onChange={(e) => setEditing({ ...editing, document_date: e.target.value || null })}
              slotProps={{ inputLabel: { shrink: true } }}
            />
            <TextField
              label="Notes"
              multiline
              value={editing.notes}
              onChange={(e) => setEditing({ ...editing, notes: e.target.value })}
            />
            {saveError && <Alert severity="error">{saveError}</Alert>}
          </Box>
        </FormDialog>
      )}
    </Box>
  )
}
