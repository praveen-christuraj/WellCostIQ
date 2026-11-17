import { useEffect, useState } from 'react'
import { Alert, Box, Button, FormControlLabel, MenuItem, Switch, TextField, Typography } from '@mui/material'
import { ErrorMessage, PageHeading } from '../../components/Common'
import { SectionCard } from '../../components/ui/SectionCard'
import { opsSettingsGet, opsSettingsPut, type OpsSettings } from '../../lib/operations'

export default function OperationsSettings() {
  const [settings, setSettings] = useState<OpsSettings | null>(null)
  const [draft, setDraft] = useState<Partial<OpsSettings>>({})
  const [loading, setLoading] = useState(true)
  const [saving, setSaving] = useState(false)
  const [error, setError] = useState('')
  const [message, setMessage] = useState('')

  const load = async () => {
    setLoading(true); setError('')
    try { const s = await opsSettingsGet(); setSettings(s); setDraft(s) } catch (e) { setError((e as Error).message) } finally { setLoading(false) }
  }
  useEffect(() => { load() }, [])

  const save = async () => {
    setSaving(true); setError(''); setMessage('')
    try {
      const payload = {
        day_boundary_hour: draft.day_boundary_hour,
        operating_timezone: draft.operating_timezone,
        tour_pattern: draft.tour_pattern,
        require_npt_code: draft.require_npt_code,
        require_npt_agency: draft.require_npt_agency,
        require_npt_reason: draft.require_npt_reason,
        max_daily_hours: draft.max_daily_hours,
        completeness_tolerance_minutes: draft.completeness_tolerance_minutes,
        default_depth_unit: draft.default_depth_unit,
        default_rop_basis: draft.default_rop_basis,
        document_max_mb: draft.document_max_mb,
      }
      const updated = await opsSettingsPut(payload as never)
      setSettings(updated); setDraft(updated); setMessage('Settings saved.')
    } catch (e) { setError((e as Error).message) } finally { setSaving(false) }
  }

  if (loading) return <Box p={3}><Typography>Loading settings…</Typography></Box>
  if (!settings && error) return <Box p={3}><ErrorMessage message={error} /></Box>

  return (
    <Box>
      <PageHeading eyebrow="Well Operations" title="Operations settings" subtitle="Per-workspace: day boundary, timezone, tour pattern, NPT completeness rules, depth unit and ROP basis, and document types. Changes are audited; tolerances affect validation. (Last in operations order: Plans/Timeline → Daily Reports → Analytics → Library/Settings)" />
      {error && <Box mb={2}><ErrorMessage message={error} /></Box>}
      {message && <Box mb={2}><Alert severity="success">{message}</Alert></Box>}

      <SectionCard title="Report period & time">
        <Box display="grid" gap={2} gridTemplateColumns={{ xs: '1fr', md: '1fr 1fr 1fr' }}>
          <TextField size="small" label="Day boundary hour (0–23)" type="number" value={draft.day_boundary_hour ?? 0} onChange={e => setDraft(d => ({ ...d, day_boundary_hour: Number(e.target.value) }))} helperText="00:00 matches the studied reports. 06:00 is the offshore industry norm — change only if crews use it." />
          <TextField size="small" label="Operating timezone" value={draft.operating_timezone ?? ''} onChange={e => setDraft(d => ({ ...d, operating_timezone: e.target.value }))} helperText="e.g. Africa/Lagos. All reports store UTC, display local." />
          <TextField size="small" label="Tour pattern" select value={draft.tour_pattern ?? 'single_24h'} onChange={e => setDraft(d => ({ ...d, tour_pattern: e.target.value }))}>
            <MenuItem value="single_24h">Single 24h</MenuItem>
            <MenuItem value="day_night_12h">Day/Night 12h</MenuItem>
          </TextField>
        </Box>
        <Alert severity="info" sx={{ mt: 2 }}>The report day is midnight-to-midnight local by default (the OpenWells reports do 0:00→23:59). A 1-minute tolerance treats 23.98h as complete; one spill block past midnight is allowed and flagged.</Alert>
      </SectionCard>

      <SectionCard title="Validation & NPT completeness">
        <Box display="grid" gap={2} gridTemplateColumns={{ xs: '1fr 1fr' }}>
          <FormControlLabel control={<Switch checked={!!draft.require_npt_code} onChange={e => setDraft(d => ({ ...d, require_npt_code: e.target.checked }))} />} label="Require NPT code for NPT blocks" />
          <FormControlLabel control={<Switch checked={!!draft.require_npt_agency} onChange={e => setDraft(d => ({ ...d, require_npt_agency: e.target.checked }))} />} label="Require NPT agency" />
          <FormControlLabel control={<Switch checked={!!draft.require_npt_reason} onChange={e => setDraft(d => ({ ...d, require_npt_reason: e.target.checked }))} />} label="Require NPT reason (≥10 chars)" />
          <TextField size="small" label="Max daily hours" type="number" value={draft.max_daily_hours ?? 24} onChange={e => setDraft(d => ({ ...d, max_daily_hours: Number(e.target.value) }))} />
          <TextField size="small" label="Completeness tolerance (minutes)" type="number" value={draft.completeness_tolerance_minutes ?? 2} onChange={e => setDraft(d => ({ ...d, completeness_tolerance_minutes: Number(e.target.value) }))} helperText="Difference between Σ blocks and period treated as unaccounted, not missing." />
          <TextField size="small" label="Default depth unit" select value={draft.default_depth_unit ?? 'm'} onChange={e => setDraft(d => ({ ...d, default_depth_unit: e.target.value }))}><MenuItem value="m">m</MenuItem><MenuItem value="ft">ft</MenuItem></TextField>
          <TextField size="small" label="Default ROP basis" select value={draft.default_rop_basis ?? 'rotating'} onChange={e => setDraft(d => ({ ...d, default_rop_basis: e.target.value }))}><MenuItem value="rotating">Rotating hours</MenuItem><MenuItem value="drilling">Drilling hours</MenuItem></TextField>
          <TextField size="small" label="Document max MB" type="number" value={draft.document_max_mb ?? 25} onChange={e => setDraft(d => ({ ...d, document_max_mb: Number(e.target.value) }))} />
        </Box>
        <Alert severity="info" sx={{ mt: 2 }}>NPT can never be productive (DB check). UPA requires a reason. Overlaps are always blocking; sum ≠ period becomes unaccounted time, flagged in dashboard — never a hard block on a mid-report print. Allowed file types: pdf, xlsx, xlsm, xls, csv, docx — MIME sniffed.</Alert>
      </SectionCard>

      <SectionCard title="Document types configuration (soft-coded)">
        <Box display="grid" gap={2} gridTemplateColumns={{ xs: '1fr' }}>
          <TextField size="small" label="Document types (comma-separated)" value={draft.document_types ?? 'DDR,DCR,DMR,RMR,other'} onChange={e => setDraft(d => ({ ...d, document_types: e.target.value }))} helperText="Soft-coded types used in Documents page (moved from hardcoded). Extraction logic is strictly in Daily Reports page." />
        </Box>
        <Alert severity="info" sx={{ mt: 2 }}>Document types are now soft-coded here. Extraction is only in Daily Reports; Documents page only handles upload/download/grouping.</Alert>
      </SectionCard>

      <Box mt={2}><Button variant="contained" onClick={save} disabled={saving}>{saving ? 'Saving…' : 'Save settings'}</Button></Box>

      <SectionCard title="Retention & safety">
        <Typography fontSize={13} color="text.secondary">Documents inherit retention (default 10 years), purge only through Deleted Entries with ops-doc:permanent-delete. Legal-hold flag prevents purge. Upload limits: 25 MB/file, ZIP/PDF bomb guards (page count, compressed-size ratio, per-page word cap), workbook XML never evaluated, macros never executed, external links never resolved, no network from parser, formula-injection sanitised on every export.</Typography>
      </SectionCard>
    </Box>
  )
}
