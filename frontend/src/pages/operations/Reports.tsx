import { useEffect, useState } from 'react'
import { Link as RouterLink, useLocation, useNavigate, useParams } from 'react-router-dom'
import { AddRounded, EditOutlined, FileOpenOutlined, LockOpenOutlined, RestoreRounded } from '@mui/icons-material'
import { Alert, Box, Button, Chip, MenuItem, Stack, TextField, Typography } from '@mui/material'
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
import { auditExport, createReport, reopenReport, type OpsReport } from '../../lib/operations'
import { WAT_LABEL, watTodayIso } from '../../lib/time'

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
    [reportType, setReportType] = useState('DDR'),
    [reopenTarget, setReopenTarget] = useState<OpsReport | null>(null),
    [reopenRemarks, setReopenRemarks] = useState('')
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
    setDay(watTodayIso())
    setNo('')
    setReportType(folder?.scope === 'completion' ? 'DCR' : 'DDR')
    setFormError('')
    setDialog('manual')
  }
  const confirmReopen = async () => {
    if (!reopenTarget) return
    setBusy(true)
    setFormError('')
    try {
      const updated = await reopenReport(reopenTarget.id, reopenRemarks.trim())
      setReopenTarget(null)
      setReopenRemarks('')
      await refresh()
      openReport(updated, recordLocation(updated))
    } catch (e) {
      setFormError((e as Error).message)
    } finally {
      setBusy(false)
    }
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
        subtitle={`Review extracted MDs, TVDs, wellbore parameters and activity hours (${WAT_LABEL}), then submit the daily record. Submitted and approved reports can be reopened to draft with audit remarks.`}
        action={
          <Box display="flex" gap={1} flexWrap="wrap">
            <Button
              component={RouterLink}
              variant="outlined"
              to={
                rows[0]?.well_id
                  ? `/operations/summary?well=${encodeURIComponent(rows[0].well_id)}${location.scope ? `&scope=${encodeURIComponent(location.scope)}` : ''}`
                  : '/operations/summary'
              }
            >
              Operation summary
            </Button>
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
                { field: 'depth_start_m', headerName: 'Start MD (m)' },
                { field: 'depth_end_m', headerName: 'End MD (m)' },
                { field: 'tvd_m', headerName: 'TVD (m)' },
                { field: 'bit_depth_m', headerName: 'Bit (m)' },
                { field: 'progress_m', headerName: 'Progress (m)' },
                { field: 'mud_weight_ppg', headerName: 'MW (ppg)' },
                {
                  field: 'total_block_minutes',
                  headerName: 'Logged hours',
                  valueFormatter: (p) => (Number(p.value) / 60).toFixed(3),
                },
                {
                  field: 'status',
                  headerName: 'Status',
                  minWidth: 155,
                  cellRenderer: ({ data: r }: { data: OpsReport }) => (
                    <Stack direction="row" gap={0.5} alignItems="center" height="100%">
                      <Chip size="small" label={r.status} />
                      {r.status === 'draft' && r.reopened_at && <Chip size="small" color="info" label="reopened" />}
                    </Stack>
                  ),
                },
                { field: 'operation_summary', headerName: 'Summary', tooltipField: 'operation_summary' },
                { field: 'remarks', headerName: 'Remarks' },
                {
                  headerName: 'Actions',
                  width: 265,
                  minWidth: 235,
                  sortable: false,
                  cellRenderer: ({ data: r }: { data: OpsReport }) => (
                    <Box display="flex" alignItems="center" gap={0.25} height="100%">
                      <Button
                        size="small"
                        startIcon={can('ops-report:update') && editableReport(r) ? <EditOutlined /> : undefined}
                        onClick={() => openReport(r)}
                      >
                        {can('ops-report:update') && editableReport(r) ? 'Edit' : 'Open'}
                      </Button>
                      {!deleted &&
                        (r.status === 'submitted' || r.status === 'approved') &&
                        can('ops-report:reopen') && (
                          <Button
                            size="small"
                            color="warning"
                            startIcon={<LockOpenOutlined />}
                            onClick={() => {
                              setReopenRemarks('')
                              setFormError('')
                              setReopenTarget(r)
                            }}
                          >
                            Reopen
                          </Button>
                        )}
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
      <FormDialog
        open={!!reopenTarget}
        title={`Reopen ${reopenTarget?.report_type ?? ''} ${reopenTarget?.report_no_text ?? ''} (${reopenTarget?.report_date ?? ''})?`}
        subtitle="Returns this submitted or approved daily report to editable draft so you can revise measurements, time blocks, surveys or narratives and re-submit. Reports older than 30 days also require the ops-report:amend capability. This reopen action is permanently recorded in the Audit Log."
        submitLabel="Reopen as draft"
        busyLabel="Reopening…"
        onClose={() => setReopenTarget(null)}
        onSubmit={confirmReopen}
        busy={busy}
        submitDisabled={reopenRemarks.trim().length < 3}
        maxWidth="sm"
      >
        <Box display="grid" gap={2} pt={1}>
          <TextField
            required
            label="Reason for reopening (audit log)"
            multiline
            minRows={3}
            value={reopenRemarks}
            onChange={(e) => setReopenRemarks(e.target.value)}
            slotProps={{ htmlInput: { maxLength: 500 } }}
            helperText="Minimum 3 characters. State what correction or addition is needed."
          />
          {formError && <Alert severity="error">{formError}</Alert>}
        </Box>
      </FormDialog>
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
