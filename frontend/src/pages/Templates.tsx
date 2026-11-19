import { useCallback, useEffect, useMemo, useState } from 'react'
import type { ColDef } from 'ag-grid-community'
import {
  Alert, Box, Button, Chip, CircularProgress, Tab, Tabs, Typography,
} from '@mui/material'
import {
  AddRounded, ContentCopyRounded, DeleteForeverOutlined, DeleteOutlineRounded, EditOutlined, FileDownloadOutlined,
  InfoOutlined, RestoreRounded,
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
  // Two-step deletion: a template is soft-deleted first and only then offered a
  // permanent delete from Deleted entries, so a mis-click never destroys it.
  const [showDeleted, setShowDeleted] = useState(false)
  const [deleteTarget, setDeleteTarget] = useState<GridRow | null>(null)
  const [deleteAction, setDeleteAction] = useState<'delete' | 'restore' | 'permanent-delete'>('delete')
  const [deleteError, setDeleteError] = useState('')
  const [deleting, setDeleting] = useState(false)
  const [copyingId, setCopyingId] = useState('')
  const [exporting, setExporting] = useState(false)

  const load = useCallback(async () => {
    setLoading(true)
    setError('')
    try {
      setRows(await api<TemplateSummary[]>(`/record-templates${showDeleted ? '?deleted=true' : ''}`))
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : 'The template library could not be loaded')
    } finally {
      setLoading(false)
    }
  }, [showDeleted])

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
      if (deleteAction === 'restore') {
        await api(`/record-templates/${deleteTarget.id}/restore`, { method: 'POST' })
        setNotice(`${deleteTarget.name} is back in the library and can be applied again.`)
      } else if (deleteAction === 'permanent-delete') {
        await api(`/record-templates/${deleteTarget.id}/permanent`, { method: 'DELETE' })
        setNotice(`${deleteTarget.name} was deleted permanently. AFEs, wells and daily sheets already created from it are unchanged.`)
      } else {
        await api(`/record-templates/${deleteTarget.id}`, { method: 'DELETE' })
        setNotice(`${deleteTarget.name} moved to Deleted entries. Records already created from it are not affected.`)
      }
      setDeleteTarget(null)
      void load()
    } catch (caught) {
      setDeleteError(caught instanceof Error ? caught.message : 'The template could not be changed')
    } finally {
      setDeleting(false)
    }
  }
  /** Opens the confirmation with the action the row allows, never a live permanent delete. */
  const ask = (row: GridRow, action: 'delete' | 'restore' | 'permanent-delete') => {
    setDeleteError('')
    setDeleteAction(action)
    setDeleteTarget(row)
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
      cellRenderer: ({ data }: { data: GridRow }) => <Box display="flex" alignItems="center" height="100%" gap={.2} flexWrap="wrap">
        {showDeleted ? <>
          {data.is_owner && can('template:restore') && <Button size="small" startIcon={<RestoreRounded sx={{ fontSize: 15 }}/>}
            onClick={() => ask(data, 'restore')} aria-label={`Restore ${data.name}`}>Restore</Button>}
          {data.is_owner && can('template:permanent-delete') && <Button size="small" color="error" startIcon={<DeleteForeverOutlined sx={{ fontSize: 15 }}/>}
            onClick={() => ask(data, 'permanent-delete')} aria-label={`Delete ${data.name} permanently`}>Delete permanently</Button>}
          {!data.is_owner && <Typography fontSize={11.5} color="text.secondary" ml={1}>Owned by {data.owner_name || 'another user'}</Typography>}
        </> : <>
          {data.is_owner && can('template:update') && <Button size="small" startIcon={<EditOutlined sx={{ fontSize: 15 }}/>}
            onClick={() => setEditorId(data.id)} aria-label={`Edit ${data.name}`}>Edit</Button>}
          {!data.is_owner && can('template:create') && <Button size="small" startIcon={<ContentCopyRounded sx={{ fontSize: 15 }}/>}
            disabled={copyingId === data.id} onClick={() => { void copy(data) }} aria-label={`Copy ${data.name}`}>Copy</Button>}
          {data.is_owner && can('template:delete') && <Button size="small" color="error" startIcon={<DeleteOutlineRounded sx={{ fontSize: 15 }}/>}
            onClick={() => ask(data, 'delete')} aria-label={`Delete ${data.name}`}>Delete</Button>}
          {!data.is_owner && <Typography fontSize={11.5} color="text.secondary" ml={1}>Read-only</Typography>}
        </>}
      </Box>,
    },
  ], [can, copyingId, showDeleted])

  return <>
    <PageHeading
      eyebrow="AFE Management"
      title="Reusable templates"
      subtitle="Save the way this workspace costs a standard well once, then start every new AFE estimate, well configuration and daily cost sheet from it. You fill in only the values that change — no Excel template, no retyping."
      action={<Box display="flex" gap={1} flexWrap="wrap">
        {can('template:export') && <Button variant="outlined" startIcon={exporting ? <CircularProgress size={15}/> : <FileDownloadOutlined/>}
          onClick={() => { void exportLibrary() }} disabled={exporting || !kindRows.length}>Export library</Button>}
        <Button variant="outlined" startIcon={<RestoreRounded/>} onClick={() => setShowDeleted(!showDeleted)}>
          {showDeleted ? 'Active templates' : 'Deleted entries'}
        </Button>
        {!showDeleted && can('template:create') && <Button variant="contained" startIcon={<AddRounded/>} onClick={() => setEditorId('new')}>
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

    {showDeleted && <Alert severity="info" sx={{ mb: 2 }}>
      These templates are in Deleted entries. Restore one to use it again, or delete it permanently once it is certain
      none of them needs to be recreated from. Deleting a template never changes the AFEs, wells or daily sheets already
      created from it.
    </Alert>}
    <Alert severity="info" icon={<InfoOutlined/>} sx={{ mb: 2 }}>
      <Typography fontSize={12.5}>{kindInfo?.hint}</Typography>
      <Typography fontSize={11.5} color="text.secondary" mt={.4}>
        Using a template never changes the template and never saves a record by itself — you still review and save the AFE, well or daily sheet yourself.
      </Typography>
    </Alert>

    {loading
      ? <Box py={8} display="grid" sx={{ placeItems: 'center' }}><CircularProgress size={26}/></Box>
      : <>
        {showDeleted && !kindRows.length && <Typography color="text.secondary" fontSize={12.5} mb={1}>
          No deleted {kindInfo?.short.toLowerCase()} templates. A template moved to Deleted entries appears here with
          Restore and Delete permanently.
        </Typography>}
        <DataTable
          rows={kindRows}
          columns={columns}
          exportName={`record-templates-${kind}${showDeleted ? '-deleted' : ''}`}
          searchPlaceholder="Search templates by name, scope or owner…"
        />
      </>}

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
      title={
        deleteAction === 'restore' ? 'Restore this template?'
          : deleteAction === 'permanent-delete' ? 'Delete this template permanently?'
            : 'Move this template to Deleted entries?'
      }
      subtitle={deleteTarget
        ? deleteAction === 'restore'
          ? `${deleteTarget.name} becomes available to apply again. Nothing is applied by restoring it.`
          : deleteAction === 'permanent-delete'
            ? `${deleteTarget.name} will be removed from the library for good. AFEs, wells and daily sheets already created from it are not affected.`
            : `${deleteTarget.name} will move to Deleted entries, where it can be restored or deleted permanently. AFEs, wells and daily sheets already created from it are not affected.`
        : ''}
      onClose={() => { if (!deleting) setDeleteTarget(null) }}
      onSubmit={() => { void remove() }}
      submitLabel={deleteAction === 'restore' ? 'Restore' : deleteAction === 'permanent-delete' ? 'Delete permanently' : 'Move to Deleted entries'}
      submitDisabled={deleting}
      busy={deleting}
      busyLabel={deleteAction === 'restore' ? 'Restoring...' : 'Deleting...'}
      danger={deleteAction !== 'restore'}
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
          {deleteAction === 'restore'
            ? 'The template returns to this library with the values it had when it was deleted.'
            : deleteAction === 'permanent-delete'
              ? 'This cannot be undone. Delete it from the live tab first if it is still listed there.'
              : 'Restoring is available from Deleted entries at any time; a permanent delete is only offered there.'}
        </Typography>
      </Box>}
    </FormDialog>
  </>
}
