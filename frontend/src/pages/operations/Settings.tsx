import { useEffect, useState } from 'react'
import { Alert, Box, Button, FormControlLabel, MenuItem, Switch, TextField } from '@mui/material'
import { ErrorMessage, PageHeading, useUnsavedChangesGuard } from '../../components/Common'
import { SectionCard } from '../../components/ui/SectionCard'
import { useAuth } from '../../context/AuthContext'
import { opsSettingsGet, opsSettingsPut, type OpsSettings } from '../../lib/operations'

export default function OperationsSettings() {
  const { can } = useAuth(),
    write = can('ops-settings:update')
  const [draft, setDraft] = useState<OpsSettings | null>(null),
    [types, setTypes] = useState(''),
    [dirty, setDirty] = useState(false),
    [busy, setBusy] = useState(false),
    [error, setError] = useState(''),
    [notice, setNotice] = useState('')
  const reset = (s: OpsSettings) => {
    setDraft(s)
    setTypes(s.document_types.join('\n'))
    setDirty(false)
  }
  useEffect(() => {
    opsSettingsGet()
      .then(reset)
      .catch((e) => setError(e.message))
  }, [])
  const change = (patch: Partial<OpsSettings>) => {
    if (draft) {
      setDirty(true)
      setDraft({ ...draft, ...patch })
    }
  }
  const save = async () => {
    if (!draft || !write) return false
    setBusy(true)
    setError('')
    setNotice('')
    try {
      const { id, organization_id, created_at, updated_at, ...settings } = draft
      reset(
        await opsSettingsPut({
          ...settings,
          document_types: types
            .split('\n')
            .map((s) => s.trim())
            .filter(Boolean),
        }),
      )
      setNotice('Operations settings saved.')
      return true
    } catch (e) {
      setError((e as Error).message)
      return false
    } finally {
      setBusy(false)
    }
  }
  const guard = useUnsavedChangesGuard({ when: dirty, onSave: save })
  return (
    <Box>
      {guard}
      <PageHeading
        eyebrow="Well Operations"
        title="Operations settings"
        subtitle="Workspace defaults for daily report intake and verification. These settings do not change costing."
        action={
          write && (
            <Button variant="contained" onClick={save} disabled={!dirty || busy}>
              Save settings
            </Button>
          )
        }
      />
      {error && <ErrorMessage message={error} />}
      {notice && <Alert severity="success">{notice}</Alert>}
      {draft && (
        <>
          <SectionCard title="Document vault">
            <Box display="grid" gap={2} gridTemplateColumns={{ xs: '1fr', md: '2fr 1fr' }}>
              <TextField
                label="Document types · one per line"
                multiline
                minRows={4}
                value={types}
                disabled={!write}
                onChange={(e) => {
                  setTypes(e.target.value)
                  setDirty(true)
                }}
                helperText="Remove a type to retire it for new uploads. Filed documents keep their original labels."
              />
              <TextField
                label="Maximum file size (MB)"
                type="number"
                value={draft.document_max_mb}
                disabled={!write}
                onChange={(e) => change({ document_max_mb: Number(e.target.value) })}
              />
            </Box>
          </SectionCard>
          <SectionCard
            title="Reporting period"
            subtitle="All timestamps across WellCostIQ default to West Africa Time (Africa/Lagos, WAT UTC+1:00)."
          >
            <Box display="grid" gap={2} gridTemplateColumns={{ xs: '1fr', md: 'repeat(3,minmax(0,1fr))' }}>
              <TextField
                label="Operating timezone"
                value={draft.operating_timezone}
                disabled={!write}
                helperText="Default: Africa/Lagos (WAT, UTC+1:00)."
                onChange={(e) => change({ operating_timezone: e.target.value })}
              />
              <TextField
                type="number"
                label="Day boundary hour (0–23 local)"
                value={draft.day_boundary_hour}
                disabled={!write}
                onChange={(e) => change({ day_boundary_hour: Number(e.target.value) })}
              />
              <TextField
                type="number"
                label="Completeness tolerance (minutes)"
                value={draft.completeness_tolerance_minutes}
                disabled={!write}
                onChange={(e) => change({ completeness_tolerance_minutes: Number(e.target.value) })}
              />
            </Box>
          </SectionCard>
          <SectionCard title="Reporting defaults">
            <Box display="flex" flexWrap="wrap" gap={2}>
              {(
                [
                  ['tour_pattern', 'Tour pattern', ['single_24h', 'day_night_12h']],
                  ['default_depth_unit', 'Preferred source depth unit', ['m', 'ft']],
                  ['default_rop_basis', 'Preferred ROP basis', ['rotating', 'drilling']],
                ] as const
              ).map(([k, title, opts]) => (
                <TextField
                  key={k}
                  select
                  sx={{ minWidth: 170 }}
                  label={title}
                  value={draft[k]}
                  disabled={!write}
                  onChange={(e) => change({ [k]: e.target.value })}
                >
                  {opts.map((o) => (
                    <MenuItem key={o} value={o}>
                      {o}
                    </MenuItem>
                  ))}
                </TextField>
              ))}
              <TextField
                type="number"
                label="Maximum daily hours"
                value={draft.max_daily_hours}
                disabled={!write}
                onChange={(e) => change({ max_daily_hours: Number(e.target.value) })}
              />
            </Box>
          </SectionCard>
          <SectionCard title="Submission checks">
            <Box display="grid">
              {(
                [
                  ['require_npt_code', 'Require an NPT code for nonproductive time'],
                  ['require_npt_agency', 'Require a responsible vendor for NPT and UPA'],
                  ['require_npt_reason', 'Require a reason for NPT and UPA'],
                ] as const
              ).map(([k, l]) => (
                <FormControlLabel
                  key={k}
                  label={l}
                  control={
                    <Switch checked={draft[k]} disabled={!write} onChange={(e) => change({ [k]: e.target.checked })} />
                  }
                />
              ))}
            </Box>
          </SectionCard>
        </>
      )}
    </Box>
  )
}
