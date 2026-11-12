import { useCallback, useEffect, useMemo, useState } from 'react'
import type { ColDef } from 'ag-grid-community'
import {
  Alert, Box, Button, Chip, CircularProgress, Tab, Tabs, Typography,
} from '@mui/material'
import {
  AddRounded, ContentCopyRounded, DeleteOutlineRounded, EditOutlined, FileDownloadOutlined, InfoOutlined,
} from '@mui/icons-material'
import { api, body, downloadFile } from '../lib/api'
import { useAuth } from '../context/AuthContext'
import { DataTable } from '../components/DataTable'
import { FormDialog, PageHeading, Tag } from '../components/Common'
import { TemplateEditorDialog } from '../components/templates/TemplateEditorDialog'
import {
  formatTemplateDate, TEMPLATE_KIND_LABEL, TEMPLATE_KINDS,
  type Template, type TemplateKind, type TemplateSummary,
} from '../lib/recordTemplates'

type GridRow = TemplateSummary

/**
 * Manage templates — the library behind every "use a template" picker.
 *
 * A template is built from an existing record or from scratch, then reused. The
 * page is deliberately plain: one tab per record type, the same grid and the same
 * actions, so the first-time user learns it once.
 */
export default function Templates() {
  const { can } = useAuth()
  const [kind, setKind] = useState<TemplateKind>('afe')
  const [rows, setRows] = useState<TemplateSummary[]>([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState('')
  const [notice, setNotice] = useState('')
  const [editorId, setEditorId] = useState<string | 'new' | null>(null)
  const [deleteTarget, setDeleteTarget] = useState<GridRow | null>(null)
  const [deleteError, setDeleteError] = useState('')
  const [deleting, setDeleting] = useState(false)
  const [copyingId, setCopyingId] = useState('')
  const [exporting, setExporting] = useState(false)

  const load = useCallback(async () => {
    setLoading(true)
    setError('')
    try {
      setRows(await api<TemplateSummary[]>('/record-templates'))
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : 'The template library could not be loaded')
    } finally {
      setLoading(false)
    }
  }, [])

  useEffect(() => { void load() }, [load])

  const kindRows = useMemo(() => rows.filter(row => row.template_kind === kind), [rows, kind])
  const kindInfo = TEMPLATE_KINDS.find(item => item.value === kind)

  const copy = async (row: GridRow) => {
    setCopyingId(row.id); setError(''); setNotice('')
    try {
      const copied = await api<Template>(`/record-templates/${row.id}/duplicate`, { method: 'POST' })
      setNotice(`${copied.name} is now yours to edit.`)
      void load()
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : 'The template could not be copied')
    } finally {
      setCopyingId('')
    }
  }

  const remove = async () => {
    if (!deleteTarget) return
    setDeleting(true); setDeleteError('')
    try {
      await api(`/record-templates/${deleteTarget.id}`, { method: 'DELETE' })
      setNotice(`${deleteTarget.name} moved to deleted entries. Records already created from it are not affected.`)
      setDeleteTarget(null)
      void load()
    } catch (caught) {
      setDeleteError(caught instanceof Error ? caught.message : 'The template could not be deleted')
    } finally {
      setDeleting(false)
    }
  }

  const exportLibrary = async () => {
    setExporting(true); setError('')
    try {
      await downloadFile(`/record-templates/export?kind=${kind}`, `record-templates-${kind}.csv`)
      await api('/record-templates/export-audit', {
        method: 'POST', silent: true,
        body: body({ format: 'csv', record_count: kindRows.length }),
      })
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : 'The template library could not be exported')
    } finally {
      setExporting(false)
    }
  }

  const columns = useMemo<ColDef<GridRow>[]>(() => [
    {
      headerName: 'NAME', field: 'name', minWidth: 240, flex: 1.4,
      cellRenderer: ({ data }: { data: GridRow }) => <Box py={.4}>
        <Typography fontSize={13} fontWeight={750}>{data.name}</Typography>
        <Typography fontSize={11.5} color="text.secondary">{data.description || 'No description'}</Typography>
      </Box>,
    },
    { headerName: 'SCOPE', field: 'scope', width: 130 },
    {
      headerName: 'LINES', field: 'line_count', width: 110, type: 'numericColumn',
      cellRenderer: ({ data }: { data: GridRow }) => <Box display="flex" alignItems="center" gap={.5} height="100%">
        <Typography fontSize={12.5}>{data.line_count}</Typography>
        {data.unavailable_count > 0 && <Tag tone="warning">{data.unavailable_count} unavailable</Tag>}
      </Box>,
    },
    {
      headerName: 'SHARING', field: 'is_shared', width: 160,
      cellRenderer: ({ data }: { data: GridRow }) => data.is_shared
        ? <Tag tone="info">Shared · {data.owner_name || 'workspace'}</Tag>
        : <Typography fontSize={12} color="text.secondary">Private</Typography>,
    },
    {
      headerName: 'USED', field: 'use_count', width: 170,
      cellRenderer: ({ data }: { data: GridRow }) => <Box>
        <Typography fontSize={12.5} fontWeight={700}>{data.use_count} time{data.use_count === 1 ? '' : 's'}</Typography>
        <Typography fontSize={11} color="text.secondary">{formatTemplateDate(data.last_used_at)}</Typography>
      </Box>,
    },
    {
      headerName: 'ACTIONS', width: 300, minWidth: 300, maxWidth: 300, sortable: false,
      cellRenderer: ({ data }: { data: GridRow }) => <Box display="flex" alignItems="center" height="100%" gap={.2}>
        {data.is_owner && can('template:update') && <Button size="small" startIcon={<EditOutlined sx={{ fontSize: 15 }}/>}
          onClick={() => setEditorId(data.id)} aria-label={`Edit ${data.name}`}>Edit</Button>}
        {!data.is_owner && can('template:create') && <Button size="small" startIcon={<ContentCopyRounded sx={{ fontSize: 15 }}/>}
          disabled={copyingId === data.id} onClick={() => { void copy(data) }} aria-label={`Copy ${data.name}`}>Copy</Button>}
        {data.is_owner && can('template:delete') && <Button size="small" color="error" startIcon={<DeleteOutlineRounded sx={{ fontSize: 15 }}/>}
          onClick={() => { setDeleteError(''); setDeleteTarget(data) }} aria-label={`Delete ${data.name}`}>Delete</Button>}
        {!data.is_owner && <Typography fontSize={11.5} color="text.secondary" ml={1}>Read-only</Typography>}
      </Box>,
    },
  ], [can, copyingId])

  return <>
    <PageHeading
      eyebrow="AFE Management"
      title="Reusable templates"
      subtitle="Save the way this workspace costs a standard well once, then start every new AFE estimate, well configuration and daily cost sheet from it. You fill in only the values that change — no Excel template, no retyping."
      action={<Box display="flex" gap={1} flexWrap="wrap">
        {can('template:export') && <Button variant="outlined" startIcon={exporting ? <CircularProgress size={15}/> : <FileDownloadOutlined/>}
          onClick={() => { void exportLibrary() }} disabled={exporting || !kindRows.length}>Export library</Button>}
        {can('template:create') && <Button variant="contained" startIcon={<AddRounded/>} onClick={() => setEditorId('new')}>
          New {kindInfo?.short.toLowerCase()} template
        </Button>}
      </Box>}
    />

    {notice && <Alert severity="success" sx={{ mb: 2 }} onClose={() => setNotice('')}>{notice}</Alert>}
    {error && <Alert severity="error" sx={{ mb: 2 }} onClose={() => setError('')}>{error}</Alert>}

    <Box borderBottom={1} borderColor="divider" mb={2}>
      <Tabs value={kind} onChange={(_event, value: TemplateKind) => setKind(value)} aria-label="Template types">
        {TEMPLATE_KINDS.map(item => <Tab key={item.value} value={item.value}
          label={<Box component="span" display="inline-flex" alignItems="center" gap={.75}>
            {item.label}
            <Box component="span" className="tnum" sx={{ fontSize: 10.5, fontWeight: 700, color: 'text.secondary' }}>
              {rows.filter(row => row.template_kind === item.value).length}
            </Box>
          </Box>}/>)}
      </Tabs>
    </Box>

    <Alert severity="info" icon={<InfoOutlined/>} sx={{ mb: 2 }}>
      <Typography fontSize={12.5}>{kindInfo?.hint}</Typography>
      <Typography fontSize={11.5} color="text.secondary" mt={.4}>
        Using a template never changes the template and never saves a record by itself — you still review and save the AFE, well or daily sheet yourself.
      </Typography>
    </Alert>

    {loading
      ? <Box py={8} display="grid" sx={{ placeItems: 'center' }}><CircularProgress size={26}/></Box>
      : <DataTable
        rows={kindRows}
        columns={columns}
        exportName={`record-templates-${kind}`}
        searchPlaceholder="Search templates by name, scope or owner…"
      />}

    <TemplateEditorDialog
      open={editorId !== null}
      templateId={editorId === 'new' ? null : editorId}
      initialKind={kind}
      onClose={() => setEditorId(null)}
      onSaved={saved => {
        setEditorId(null)
        setNotice(saved)
        void load()
      }}
    />

    <FormDialog
      open={Boolean(deleteTarget)}
      title="Delete this template?"
      subtitle={deleteTarget ? `${deleteTarget.name} will move to deleted entries. AFEs, wells and daily sheets already created from it are not affected.` : ''}
      onClose={() => { if (!deleting) setDeleteTarget(null) }}
      onSubmit={() => { void remove() }}
      submitLabel="Delete template"
      submitDisabled={deleting}
      busy={deleting}
      busyLabel="Deleting..."
      danger
      maxWidth="sm"
    >
      {deleteError && <Alert severity="error">{deleteError}</Alert>}
      {deleteTarget && <Box display="grid" gap={1}>
        <Box display="flex" gap={.7} flexWrap="wrap">
          <Chip size="small" variant="outlined" label={TEMPLATE_KIND_LABEL[deleteTarget.template_kind]}/>
          {deleteTarget.scope && <Chip size="small" variant="outlined" label={deleteTarget.scope}/>}
          <Chip size="small" variant="outlined" label={`${deleteTarget.line_count} line${deleteTarget.line_count === 1 ? '' : 's'}`}/>
        </Box>
        <Typography fontSize={12.5} color="text.secondary">
          This cannot be undone from this page. A workspace administrator can restore deleted records from the audit trail.
        </Typography>
      </Box>}
    </FormDialog>
  </>
}
