import { useEffect, useState } from 'react'
import { Alert, Box, Button, Checkbox, FormControlLabel, IconButton, Paper, Stack, Table, TableBody, TableCell,
  TableContainer, TableHead, TablePagination, TableRow, TextField, Typography } from '@mui/material'
import { AddRounded, DeleteOutlineRounded, DownloadRounded, UploadRounded } from '@mui/icons-material'
import { FormDialog, useUnsavedChangesGuard } from '../Common'
import { DataTable } from '../DataTable'
import { SectionCard } from '../ui/SectionCard'
import { useAuth } from '../../context/AuthContext'
import { downloadTemplate } from '../../lib/export'
import { auditExport, getPlannedSurvey, planTrajectory, savePlannedSurvey,
  type OpsPlan, type OpsPlannedTrajectory, type OpsPlanSurvey, type OpsPlanSurveyStation, type OpsTrajectoryComparison } from '../../lib/operations'
import { NONNEGATIVE_DECIMAL } from '../../lib/precision'
import { SurveyImportDialog } from './SurveyImportDialog'
import { TrajectoryComparisonPanel } from './TrajectoryComparison'

const NUMERIC = [
  ['md_m', 'MD (m)'], ['inc_deg', 'Inclination (°)'], ['azi_deg', 'Azimuth (°)'],
  ['tvd_m', 'TVD (m)'], ['ns_m', 'N/S (m)'], ['ew_m', 'E/W (m)'], ['vsec_m', 'VS (m)'], ['dls_deg_per_30m', 'DLS (°/30 m)'],
] as const
const EMPTY_STATION: OpsPlanSurveyStation = {
  md_m: null, inc_deg: null, azi_deg: null, tvd_m: null, ns_m: null, ew_m: null, vsec_m: null, dls_deg_per_30m: null,
  tool: '', source: 'manual', source_file: '', source_sheet: '', survey_at: null,
}
let nextRow = 0
const draftRow = (station: OpsPlanSurveyStation) => ({ key: ++nextRow, station })
const MAX_STATIONS = 5000

function validate(rows: OpsPlanSurveyStation[]) {
  const seen = new Set<number>()
  const messages = new Map<number, string>()
  rows.forEach((row, index) => {
    const md = Number(row.md_m), inc = Number(row.inc_deg), az = Number(row.azi_deg)
    for (const [key, name] of NUMERIC) {
      const value = row[key]?.trim()
      if (value && (!NONNEGATIVE_DECIMAL.test(value.replace(/^-/, '')) || Math.abs(Number(value)) >= 1e16)) {
        messages.set(index, `${name} must be a number with up to three decimal places.`)
        return
      }
    }
    const message = !row.md_m?.trim() || md < 0 ? 'Enter a non-negative MD.'
      : !row.inc_deg?.trim() || inc < 0 || inc > 180 ? 'Inclination must be between 0° and 180°.'
      : inc >= 1 && !row.azi_deg?.trim() ? 'A deviated station needs an azimuth.'
      : az < 0 || az > 360 ? 'Azimuth must be between 0° and 360°.'
      : Number(row.dls_deg_per_30m) < 0 ? 'Dogleg severity cannot be negative.'
      : seen.has(md) ? 'Duplicate MD: reconcile or remove one of the stations.' : ''
    if (message) messages.set(index, message)
    else seen.add(md)
  })
  return messages
}

export function PlannedSurveyPanel({ plan }: { plan: OpsPlan }) {
  const { can } = useAuth()
  const [survey, setSurvey] = useState<OpsPlanSurvey | null>(null)
  const [comparison, setComparison] = useState<OpsTrajectoryComparison | null>(null)
  const [edit, setEdit] = useState(false)
  const [surveyError, setSurveyError] = useState('')
  const [comparisonError, setComparisonError] = useState('')
  const [reload, setReload] = useState(0)
  const [comparisonLoading, setComparisonLoading] = useState(!plan.is_deleted)
  const [selected, setSelected] = useState<number | null>(null)
  const [azimuth, setAzimuth] = useState('')
  const [appliedAzimuth, setAppliedAzimuth] = useState('')
  const azimuthInvalid = azimuth.trim() !== '' && (!Number.isFinite(Number(azimuth)) || Number(azimuth) < 0 || Number(azimuth) > 360)
  const canEdit = !plan.is_deleted && plan.status === 'draft' && can('ops-plan:update')
  useEffect(() => {
    let current = true
    setSurveyError('')
    getPlannedSurvey(plan.id).then(data => { if (current) setSurvey(data) })
      .catch((error: Error) => { if (current) setSurveyError(error.message) })
    return () => { current = false }
  }, [plan.id, reload])
  useEffect(() => {
    if (plan.is_deleted) return
    let current = true
    setComparisonError('')
    setComparisonLoading(true)
    planTrajectory(plan.id, appliedAzimuth).then(data => { if (current) setComparison(data) })
      .catch((error: Error) => { if (current) { setComparison(null); setComparisonError(error.message) } })
      .finally(() => { if (current) setComparisonLoading(false) })
    return () => { current = false }
  }, [plan.id, plan.is_deleted, appliedAzimuth, reload])
  const planned: OpsPlannedTrajectory | null = comparison?.planned_trajectory ?? null
  return <Stack spacing={2}>
    <SectionCard title="Planned directional survey"
      subtitle={`Version ${plan.version_no} · ${plan.status}. These stations describe the well design, not the timeline or daily-report actuals.`}
      action={canEdit && survey && <Button size="small" variant="outlined" onClick={() => setEdit(true)}>Edit / import survey</Button>}>
      <Typography variant="body2" color="text.secondary">
        {survey ? `${survey.stations.length} saved station(s)${survey.shared_reference ? ' · shared reference confirmed' : ''}.`
          : 'The comparison uses the saved stations for this version.'}
      </Typography>
    </SectionCard>
    {comparison && <>
      <TrajectoryComparisonPanel path={comparison} selectedMd={selected} onSelectMd={setSelected} action={<>
        <TextField size="small" label="Section azimuth (°)" type="number" value={azimuth} error={azimuthInvalid}
          slotProps={{ inputLabel: { shrink: true }, htmlInput: { min: 0, max: 360, step: 'any' } }}
          placeholder="Auto" sx={{ width: 150 }} onChange={event => setAzimuth(event.target.value)} />
        <Button size="small" disabled={azimuthInvalid || azimuth === appliedAzimuth} onClick={() => setAppliedAzimuth(azimuth)}>Apply bearing</Button>
      </>} />
      {Boolean(comparison.curve.length || planned?.curve.length) && <TrajectoryComparisonPanel path={comparison} part="steering" selectedMd={selected} onSelectMd={setSelected} />}
    </>}
    {comparisonLoading && <Typography role="status" color="text.secondary">Loading trajectory comparison…</Typography>}
    {comparisonError && <Alert severity="error">{comparisonError}</Alert>}
    <SectionCard title="Saved planned stations">
      {surveyError ? <Alert severity="error" action={<Button onClick={() => setReload(n => n + 1)}>Retry</Button>}>{surveyError}</Alert>
        : !survey ? <Typography role="status">Loading planned stations…</Typography>
        : !survey.stations.length ? <Typography color="text.secondary">No planned stations saved for this version.</Typography>
        : <DataTable rows={survey.stations} rowKey="md_m" exportName={`${plan.well_code}-${plan.scope}-planned-survey-v${plan.version_no}`}
          canExport={can('ops-plan:export')} onExport={auditExport('plans')} searchPlaceholder="Search planned stations…"
          columns={[
            ...NUMERIC.map(([field, headerName]) => ({ field, headerName, minWidth: 115 })),
            { field: 'source', headerName: 'Source' }, { field: 'source_file', headerName: 'File', minWidth: 160 },
            { field: 'source_sheet', headerName: 'Sheet' }, { field: 'tool', headerName: 'Tool' },
            { field: 'survey_at', headerName: 'Survey timestamp', minWidth: 165 },
          ]} />}
    </SectionCard>
    {edit && survey && <PlannedSurveyEditor plan={plan} survey={survey} canImport={can('ops-plan:import')}
      onClose={() => setEdit(false)} onSaved={saved => {
        setSurvey(saved); setComparison(null); setSelected(null); setReload(n => n + 1); setEdit(false)
      }} />}
  </Stack>
}

function PlannedSurveyEditor({ plan, survey, canImport, onClose, onSaved }: {
  plan: OpsPlan; survey: OpsPlanSurvey; canImport: boolean; onClose: () => void; onSaved: (saved: OpsPlanSurvey) => void
}) {
  const [rows, setRows] = useState(() => survey.stations.map(draftRow))
  const [sharedReference, setSharedReference] = useState(survey.shared_reference)
  const [dirty, setDirty] = useState(false)
  const [busy, setBusy] = useState(false)
  const [upload, setUpload] = useState(false)
  const [clear, setClear] = useState(false)
  const [error, setError] = useState('')
  const [notice, setNotice] = useState('')
  const [page, setPage] = useState(0)
  const [size, setSize] = useState(20)
  const stations = rows.map(row => row.station)
  const errors = validate(stations)
  const firstError = errors.keys().next().value
  const blocked = rows.length > MAX_STATIONS || errors.size > 0
  const save = async () => {
    if (!dirty || busy || blocked) return false
    setBusy(true); setError('')
    try {
      const saved = await savePlannedSurvey(plan.id, { stations, shared_reference: sharedReference, updated_at: survey.updated_at })
      setDirty(false)
      onSaved(saved)
      return true
    } catch (e) {
      setError((e as Error).message)
      return false
    } finally { setBusy(false) }
  }
  const navigationGuard = useUnsavedChangesGuard({ when: dirty, onSave: save, title: 'Leave with unsaved planned survey changes?' })
  return <>
    <FormDialog open title={`Edit planned survey · v${plan.version_no}`} subtitle="Review the directional design for this draft. Saving does not activate the plan or change the daily reports and timeline activities."
      onClose={onClose} onSubmit={() => void save()} submitDisabled={!dirty || blocked} busy={busy} dirty={dirty} submitLabel="Save planned survey" maxWidth={false}>
      <Stack spacing={1.5}>
        <Stack direction="row" gap={1} flexWrap="wrap" useFlexGap>
          {canImport && <Button variant="outlined" startIcon={<UploadRounded />} disabled={busy} onClick={() => setUpload(true)}>Import / extract survey</Button>}
          <Button startIcon={<DownloadRounded />} onClick={() => downloadTemplate('planned-directional-survey.csv', [...NUMERIC.map(([name]) => name), 'tool', 'survey_at'])}>Download template</Button>
          <Button startIcon={<AddRounded />} disabled={busy || rows.length >= MAX_STATIONS} onClick={() => {
            setRows([...rows, draftRow({ ...EMPTY_STATION })]); setPage(Math.floor(rows.length / size)); setDirty(true)
          }}>Add station</Button>
          {rows.length > 0 && <Button color="error" disabled={busy} onClick={() => setClear(true)}>Remove all stations</Button>}
        </Stack>
        <FormControlLabel control={<Checkbox checked={sharedReference} disabled={busy} onChange={event => { setSharedReference(event.target.checked); setDirty(true) }} />}
          label="I confirm the planned and actual surveys use the same bore, MD/TVD datum, north reference and N/E origin." />
        <Typography variant="caption" color="text.secondary">A survey starting below surface also needs recorded TVD, N/S and E/W at its first station before position differences can be shown.</Typography>
        {notice && <Alert severity="success" onClose={() => setNotice('')}>{notice}</Alert>}
        {error && <Alert severity="error">{error}</Alert>}
        {rows.length > MAX_STATIONS && <Alert severity="error">Remove stations or use Replace to keep at most {MAX_STATIONS} stations.</Alert>}
        {firstError !== undefined && <Alert severity="error" action={<Button size="small" onClick={() => setPage(Math.floor(firstError / size))}>Go to row</Button>}>
          Station {firstError + 1}: {errors.get(firstError)}
        </Alert>}
        <TableContainer component={Paper} variant="outlined" sx={{ maxHeight: '50vh' }}>
          <Table size="small" stickyHeader aria-label="Planned survey stations">
            <TableHead><TableRow><TableCell>#</TableCell>{NUMERIC.map(([key, label]) => <TableCell key={key}>{label}</TableCell>)}<TableCell>Source</TableCell><TableCell>Actions</TableCell></TableRow></TableHead>
            <TableBody>
              {rows.slice(page * size, (page + 1) * size).map(({ key, station }, offset) => {
                const index = offset + page * size
                return <TableRow key={key}>
                  <TableCell>{index + 1}</TableCell>
                  {NUMERIC.map(([field, label]) => <TableCell key={field} sx={{ px: 0.5 }}>
                    <TextField size="small" disabled={busy} error={errors.has(index)} value={station[field] ?? ''}
                      slotProps={{ htmlInput: { 'aria-label': `Station ${index + 1} ${label}`, inputMode: 'decimal' } }} sx={{ minWidth: 91 }}
                      onChange={event => {
                        setDirty(true)
                        if (field === 'md_m' || field === 'ns_m' || field === 'ew_m' || field === 'tvd_m') setSharedReference(false)
                        const value = event.target.value
                        setRows(previous => previous.map(row => row.key === key ? { ...row, station: { ...row.station, [field]: value || null } } : row))
                      }} />
                  </TableCell>)}
                  <TableCell><Typography variant="caption">{[station.source_file || station.source, station.source_sheet].filter(Boolean).join(' · ')}</Typography></TableCell>
                  <TableCell><IconButton disabled={busy} aria-label={`Remove station ${index + 1}`} onClick={() => {
                    setRows(rows.filter(row => row.key !== key)); setDirty(true); setSharedReference(false); setPage(Math.min(page, Math.max(0, Math.ceil((rows.length - 1) / size) - 1)))
                  }}><DeleteOutlineRounded /></IconButton></TableCell>
                </TableRow>
              })}
              {!rows.length && <TableRow><TableCell colSpan={NUMERIC.length + 3}>No stations. Import a reviewed survey or add a row.</TableCell></TableRow>}
            </TableBody>
          </Table>
        </TableContainer>
        <TablePagination component={Box} count={rows.length} page={page} rowsPerPage={size} rowsPerPageOptions={[20, 50, 100]}
          onPageChange={(_, next) => setPage(next)} onRowsPerPageChange={event => { setSize(Number(event.target.value)); setPage(0) }} />
      </Stack>
    </FormDialog>
    {clear && <FormDialog open title="Remove all planned stations from the draft?" submitLabel="Remove stations" onClose={() => setClear(false)}
      onSubmit={() => { setRows([]); setPage(0); setSharedReference(false); setDirty(true); setClear(false) }}>
      <Typography>The saved survey is not cleared until you save this draft.</Typography>
    </FormDialog>}
    {upload && <SurveyImportDialog open planId={plan.id} existingCount={rows.length} busy={busy} onClose={() => setUpload(false)}
      onApply={(imported, mode, preview) => {
        const staged = imported.map(station => draftRow({ ...station, source_file: preview.file_name.slice(0, 255), source_sheet: (preview.detected_sheet ?? '').slice(0, 100) }))
        setRows(mode === 'replace' ? staged : [...rows, ...staged]); setDirty(true); setSharedReference(false)
        setPage(mode === 'replace' ? 0 : Math.floor(rows.length / size))
        setNotice(`${staged.length} station(s) staged. Review the combined table and confirm the reference before saving.`)
      }} />}
    {navigationGuard}
  </>
}
