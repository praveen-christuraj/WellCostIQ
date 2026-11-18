import { useEffect, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { AddRounded, EditOutlined, FileOpenOutlined, RestoreRounded } from '@mui/icons-material'
import { Alert, Box, Button, Chip, MenuItem, TextField } from '@mui/material'
import { DataTable } from '../../components/DataTable'
import { ErrorMessage, FormDialog, PageHeading } from '../../components/Common'
import { ImportDialog } from '../../components/ImportDialog'
import { FolderFields, ScopeDirectory, type Folder } from '../../components/operations/ScopeDirectory'
import { SourceDialog } from '../../components/operations/SourceDialog'
import { editableReport, useRegisterActions } from '../../components/operations/RegisterActions'
import { api, body } from '../../lib/api'
import { useAuth } from '../../context/AuthContext'
import {
  auditExport,
  listReports,
  opsScopeReference,
  createReport,
  type OpsReport,
  type OpsScopeReference,
} from '../../lib/operations'

export default function OperationsReports() {
  const { can } = useAuth(),
    go = useNavigate()
  const [ref, setRef] = useState<OpsScopeReference | null>(null),
    [rows, setRows] = useState<OpsReport[]>([]),
    [deleted, setDeleted] = useState(false)
  const [folder, setFolder] = useState<Folder | null>(null),
    [error, setError] = useState(''),
    [busy, setBusy] = useState(false)
  const [dialog, setDialog] = useState<'' | 'manual' | 'extract' | 'import'>(''),
    [formError, setFormError] = useState('')
  const [dest, setDest] = useState<Folder>({ well_id: '', scope: 'drilling' }),
    [day, setDay] = useState(''),
    [no, setNo] = useState(''),
    [reportType, setReportType] = useState('DDR')
  const loadRows = () => (deleted ? api<OpsReport[]>('/operations/reports/deleted') : listReports({}))
  const refresh = async () => {
    setRows(await loadRows())
  }
  const controls = useRegisterActions<OpsReport>('reports', deleted, refresh)
  useEffect(() => {
    let current = true
    setError('')
    setRows([])
    loadRows()
      .then((r) => {
        if (current) setRows(r)
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
  const open = () => {
    setDest(folder ?? { well_id: '', scope: 'drilling' })
    setDay(new Date().toISOString().slice(0, 10))
    setNo('')
    setReportType(folder?.scope === 'completion' ? 'DCR' : 'DDR')
    setFormError('')
    setDialog('manual')
  }
  const create = async () => {
    setBusy(true)
    setFormError('')
    try {
      const r = await createReport({ ...dest, report_date: day, report_no_text: no, report_type: reportType })
      go(`/operations/reports/${r.id}`)
    } catch (e) {
      setFormError((e as Error).message)
    } finally {
      setBusy(false)
    }
  }
  const visible = folder ? rows.filter((r) => r.well_id === folder.well_id && r.scope === folder.scope) : rows
  return (
    <Box>
      <PageHeading
        eyebrow="Well Operations"
        title={deleted ? 'Deleted daily reports' : 'Daily reports'}
        subtitle="Review the source, reconcile the activity hours, then submit the daily record. Only submitted or approved time contributes to performance KPIs."
        action={
          <Box display="flex" gap={1} flexWrap="wrap">
            {!deleted && can('ops-report:create') && (
              <Button variant="contained" startIcon={<AddRounded />} onClick={open}>
                New report
              </Button>
            )}
            {!deleted && can('ops-report:create') && can('ops-doc:read') && can('ops-doc:extract') && (
              <Button
                variant="outlined"
                disabled={!ref}
                startIcon={<FileOpenOutlined />}
                onClick={() => setDialog('extract')}
              >
                Extract PDF / Excel
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
              {deleted ? 'Active reports' : 'Deleted entries'}
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
        rows={visible}
        selectable
        exportSelected
        selectionResetKey={controls.resetKey}
        onSelectionChange={controls.setSelected}
        fillHeight
        searchPlaceholder="Search daily reports…"
        exportName="daily-operations-reports"
        canExport={can('ops-report:export')}
        onExport={auditExport('reports')}
        onImport={!deleted && can('ops-report:import') ? () => setDialog('import') : undefined}
        columns={[
          { field: 'report_date', headerName: 'Report date' },
          { field: 'rig_code_snapshot', headerName: 'Rig' },
          { field: 'well_code_snapshot', headerName: 'Well' },
          { field: 'scope', headerName: 'Scope' },
          { field: 'report_type', headerName: 'Type' },
          { field: 'report_no_text', headerName: 'Report no.' },
          { field: 'depth_end_m', headerName: 'Depth (m)' },
          {
            field: 'total_block_minutes',
            headerName: 'Logged hours',
            valueFormatter: (p) => (Number(p.value) / 60).toFixed(2),
          },
          {
            field: 'status',
            headerName: 'Status',
            cellRenderer: ({ value }: { value: string }) => <Chip size="small" label={value} />,
          },
          { field: 'remarks', headerName: 'Remarks' },
          { field: 'depth_start_m', headerName: 'Start MD (m)' },
          { field: 'operation_summary', headerName: 'Summary', tooltipField: 'operation_summary' },
          {
            headerName: 'Actions',
            width: 200,
            minWidth: 185,
            sortable: false,
            cellRenderer: ({ data: r }: { data: OpsReport }) => (
              <Box display="flex" alignItems="center" height="100%">
                {!deleted && (
                  <Button
                    size="small"
                    startIcon={can('ops-report:update') && editableReport(r) ? <EditOutlined /> : undefined}
                    onClick={() => go(`/operations/reports/${r.id}`)}
                  >
                    {can('ops-report:update') && editableReport(r) ? 'Edit' : 'Open'}
                  </Button>
                )}
                {controls.actions([r])}
              </Box>
            ),
          },
        ]}
      />
      {controls.dialog}
      {dialog === 'extract' && ref && (
        <SourceDialog
          extract
          reference={ref}
          initial={folder}
          onClose={() => setDialog('')}
          onSaved={(r) => {
            if (r) go(`/operations/reports/${r.id}`)
          }}
        />
      )}
      <FormDialog
        open={dialog === 'manual'}
        title="New daily report"
        onClose={() => setDialog('')}
        onSubmit={create}
        busy={busy}
        submitLabel="Create draft"
        submitDisabled={!dest.well_id || !day}
        maxWidth="sm"
      >
        <Box display="grid" gap={2} pt={1}>
          <FolderFields
            folder={dest}
            reference={ref}
            change={(f) => {
              setDest(f)
              setReportType(f.scope === 'completion' ? 'DCR' : 'DDR')
            }}
          />
          <TextField select label="Report type" value={reportType} onChange={(e) => setReportType(e.target.value)}>
            {['DDR', 'DCR', 'DMR', 'RMR'].map((t) => (
              <MenuItem key={t} value={t}>
                {t}
              </MenuItem>
            ))}
          </TextField>
          <TextField
            label="Report date"
            type="date"
            value={day}
            onChange={(e) => setDay(e.target.value)}
            slotProps={{ inputLabel: { shrink: true } }}
          />
          <TextField label="Report no." value={no} onChange={(e) => setNo(e.target.value)} />
          {formError && <Alert severity="error">{formError}</Alert>}
        </Box>
      </FormDialog>
      {dialog === 'import' && (
        <ImportDialog
          open
          title="Import daily report headers"
          subtitle="Creates draft headers only. To extract activity blocks, use Extract PDF / Excel."
          headers={['well_code', 'report_date', 'scope']}
          optionalHeaders={['rig_code', 'report_type', 'report_no_text', 'depth_start_m', 'depth_end_m', 'operation_summary']}
          templateName="daily-operations-reports.csv"
          headerAliases={{
            Well: 'well_code',
            Rig: 'rig_code',
            Scope: 'scope',
            'Report date': 'report_date',
            'Report no.': 'report_no_text',
            Type: 'report_type',
            'Depth (m)': 'depth_end_m',
            'Start MD (m)': 'depth_start_m',
            Summary: 'operation_summary',
          }}
          onClose={() => setDialog('')}
          onRows={async (rows) => {
            const result = await api<{ created_count: number; errors: string[] }>('/operations/reports/import', {
              method: 'POST',
              body: body({
                rows: rows.map((r) => ({
                  ...r,
                  report_type: r.report_type || (r.scope === 'completion' ? 'DCR' : 'DDR'),
                  depth_start_m: r.depth_start_m || null,
                  depth_end_m: r.depth_end_m || null,
                })),
              }),
            })
            await refresh()
            return result.errors
          }}
        />
      )}
    </Box>
  )
}
