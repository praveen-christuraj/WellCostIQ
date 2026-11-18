import { useEffect, useState } from 'react'
import { Link as RouterLink, useLocation, useNavigate, useParams } from 'react-router-dom'
import { AddRounded, EditOutlined, FileOpenOutlined, RestoreRounded } from '@mui/icons-material'
import { Alert, Box, Button, Chip, MenuItem, TextField, Typography } from '@mui/material'
import { DataTable } from '../../components/DataTable'
import { ErrorMessage, FormDialog, PageHeading } from '../../components/Common'
import { ImportDialog } from '../../components/ImportDialog'
import {
  directorySearch,
  FolderFields,
  recordLocation,
  ScopeDirectory,
  useOperationsRegister,
  type DirectoryLocation,
  type Folder,
} from '../../components/operations/ScopeDirectory'
import { SourceDialog } from '../../components/operations/SourceDialog'
import { editableReport, useRegisterActions } from '../../components/operations/RegisterActions'
import { api, body } from '../../lib/api'
import { useAuth } from '../../context/AuthContext'
import { auditExport, createReport, type OpsReport } from '../../lib/operations'

import OperationsReportDetail from './ReportDetail'

export default function OperationsReports() {
  const { can } = useAuth()
  const go = useNavigate()
  const { id } = useParams()
  const { state } = useLocation()
  const register = useOperationsRegister('reports')
  const { reference: ref, rows, deleted, refresh, location } = register
  const [busy, setBusy] = useState(false)
  const [dialog, setDialog] = useState<'' | 'manual' | 'extract' | 'import'>(''),
    [formError, setFormError] = useState('')
  const [dest, setDest] = useState<Folder>({ well_id: '', scope: 'drilling' }),
    [day, setDay] = useState(''),
    [no, setNo] = useState(''),
    [reportType, setReportType] = useState('DDR')
  const controls = useRegisterActions<OpsReport>('reports', deleted, refresh)
  useEffect(() => {
    controls.clear()
  }, [location.rig, location.well, location.scope, deleted])
  const openReport = (report: OpsReport, folder: DirectoryLocation = location) => {
    go(`/operations/reports/${report.id}?${directorySearch(folder, report.is_deleted)}`, {
      state: folder === location ? { returnToFolder: true } : null,
    })
  }
  const open = () => {
    const folder = register.destination()
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
      setDialog('')
      await refresh()
      openReport(r, recordLocation(r))
    } catch (e) {
      setFormError((e as Error).message)
    } finally {
      setBusy(false)
    }
  }
  return (
    <Box>
      <PageHeading
        eyebrow="Well Operations"
        title={deleted ? 'Deleted daily reports' : 'Daily reports'}
        subtitle="Review the source, reconcile the activity hours, then submit the daily record. Only submitted or approved time contributes to performance KPIs."
        action={
          <Box display="flex" gap={1} flexWrap="wrap">
            <Button component={RouterLink} to="/operations/guide">
              Ask &amp; guide
            </Button>
            {!deleted && can('ops-report:create') && (
              <Button variant="contained" startIcon={<AddRounded />} disabled={!ref || register.loading} onClick={open}>
                New report
              </Button>
            )}
            {!deleted && can('ops-report:create') && can('ops-doc:read') && can('ops-doc:extract') && (
              <Button
                variant="outlined"
                disabled={!ref || register.loading}
                startIcon={<FileOpenOutlined />}
                onClick={() => setDialog('extract')}
              >
                Extract PDF / Excel
              </Button>
            )}
            {!deleted && can('ops-report:import') && !location.well && (
              <Button onClick={() => setDialog('import')}>Import report headers</Button>
            )}
            <Button
              variant="outlined"
              startIcon={<RestoreRounded />}
              onClick={() => {
                controls.clear()
                register.change({ rig: '' }, !deleted)
              }}
            >
              {deleted ? 'Active reports' : 'Deleted entries'}
            </Button>
          </Box>
        }
      />
      {register.error && <ErrorMessage message={register.error} />}
      <ScopeDirectory {...register} resource="reports" />
      {location.well &&
        (register.loading ? (
          <Typography role="status">Loading daily reports…</Typography>
        ) : (
          <>
            {controls.bar}
            <DataTable
              key={JSON.stringify([location, deleted])}
              rows={rows}
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
                  valueFormatter: (p) => (Number(p.value) / 60).toFixed(3),
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
                      <Button
                        size="small"
                        startIcon={can('ops-report:update') && editableReport(r) ? <EditOutlined /> : undefined}
                        onClick={() => openReport(r)}
                      >
                        {can('ops-report:update') && editableReport(r) ? 'Edit' : 'Open'}
                      </Button>
                      {controls.actions([r])}
                    </Box>
                  ),
                },
              ]}
            />
            {controls.dialog}
          </>
        ))}
      {dialog === 'extract' && ref && (
        <SourceDialog
          extract
          reference={ref}
          initial={register.destination()}
          onClose={() => setDialog('')}
          onSaved={(r) => {
            setDialog('')
            if (r) {
              void refresh()
              openReport(r, recordLocation(r))
            }
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
          optionalHeaders={[
            'rig_code',
            'report_type',
            'report_no_text',
            'depth_start_m',
            'depth_end_m',
            'operation_summary',
          ]}
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
      {id && (
        <OperationsReportDetail
          key={id}
          id={id}
          includeDeleted={deleted}
          onChanged={refresh}
          onClose={(r) => {
            const parent = location.well ? location : r ? recordLocation(r) : { rig: '' }
            if (state?.returnToFolder) go(-1)
            else go(`/operations/reports?${directorySearch(parent, r?.is_deleted ?? deleted)}`, { replace: true })
          }}
        />
      )}
    </Box>
  )
}
