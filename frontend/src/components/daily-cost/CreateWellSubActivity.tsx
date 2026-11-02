import { useMemo, useState } from 'react'
import { Alert, Box, Button, MenuItem, TextField } from '@mui/material'
import { FormDialog } from '../Common'
import { useAuth } from '../../context/AuthContext'
import { api, body } from '../../lib/api'
import type { DailyCostReference, WellScopeKey } from '../../lib/dailyCost'

type SubActivity = DailyCostReference['sub_activities'][number]

/** Planned vs UPA/NPT, from the Activity's own code and name (same rule as the API). */
function isPlannedActivity(reference: DailyCostReference, activityId: string): boolean {
  const activity = reference.activities.find(item => item.id === activityId)
  if (!activity) return true
  const text = `${activity.activity_code} ${activity.activity_name}`.toLowerCase()
  if (/\bnpt\b/.test(text) || /non[ -]?productive/.test(text)) return false
  if (/\bupa\b/.test(text) || text.includes('unplanned')) return false
  return true
}

export function CreateWellSubActivity({ reference, wellId, scope, activityId, onCreated }: {
  reference: DailyCostReference; wellId: string; scope: WellScopeKey; activityId?: string; onCreated: (item: SubActivity) => void
}) {
  const { can } = useAuth()
  const [open, setOpen] = useState(false)
  const [form, setForm] = useState({ sub_activity_code: '', sub_activity_name: '', description: '', activity_id: '', vendor_id: '', vendor_subcategory_id: '' })
  const [error, setError] = useState('')
  const [busy, setBusy] = useState(false)
  const well = reference.wells.find(item => item.id === wellId)
  const rig = reference.rigs.find(item => item.id === well?.rig_id)
  const planned = isPlannedActivity(reference, form.activity_id)
  const vendors = useMemo(
    () => reference.vendors.filter(vendor => vendor.status !== 'blocked'),
    [reference.vendors],
  )
  const serviceLines = reference.vendor_service_subcategories ?? []
  const linesForVendor = serviceLines.filter(line => line.vendor_id === form.vendor_id)

  if (!can('rig-well:create')) return null

  const save = async () => {
    setBusy(true); setError('')
    try {
      const created = await api<SubActivity>('/rig-well/sub-activities', {
        method: 'POST',
        body: body({
          ...form,
          well_id: wellId,
          scope,
          vendor_id: planned ? null : (form.vendor_id || null),
          vendor_subcategory_id: planned ? null : (form.vendor_subcategory_id || null),
          responsible_party: planned ? 'Not Applicable' : (vendors.find(vendor => vendor.id === form.vendor_id)?.vendor_name ?? ''),
        }),
      })
      onCreated({ ...created, display_name: `${created.sub_activity_code} · ${created.sub_activity_name}` })
      setOpen(false)
    } catch (caught) { setError(caught instanceof Error ? caught.message : 'Could not create the sub activity.') }
    finally { setBusy(false) }
  }

  const openDialog = () => {
    const initial = {
      sub_activity_code: '', sub_activity_name: '', description: '',
      activity_id: activityId ?? reference.activities[0]?.id ?? '',
      vendor_id: '', vendor_subcategory_id: '',
    }
    if (initial.activity_id && !isPlannedActivity(reference, initial.activity_id) && vendors.length === 1) {
      initial.vendor_id = vendors[0].id
    }
    setForm(initial)
    setError('')
    setOpen(true)
  }

  return <>
    <Button onClick={openDialog}>Create well sub activity here</Button>
    <FormDialog open={open} title="Create well sub activity" subtitle={`Rig: ${rig?.rig_name ?? ''} · Well: ${well?.well_name ?? ''} · ${scope}. This context is fixed to the current sheet.`} onClose={() => setOpen(false)} onSubmit={() => void save()} busy={busy} submitLabel="Create sub activity">
      <Box display="grid" gap={2}>
        <TextField select required label="Activity" value={form.activity_id} onChange={event => setForm({ ...form, activity_id: event.target.value, vendor_id: event.target.value && isPlannedActivity(reference, event.target.value) ? '' : form.vendor_id, vendor_subcategory_id: '' })}>{reference.activities.map(item => <MenuItem key={item.id} value={item.id}>{item.display_name}</MenuItem>)}</TextField>
        <TextField required label="Sub activity code" value={form.sub_activity_code} inputProps={{ maxLength: 50 }} onChange={event => setForm({ ...form, sub_activity_code: event.target.value })}/>
        <TextField required label="Sub activity name" value={form.sub_activity_name} inputProps={{ maxLength: 150 }} onChange={event => setForm({ ...form, sub_activity_name: event.target.value })}/>
        <TextField required label="Description" value={form.description} multiline inputProps={{ maxLength: 4000 }} onChange={event => setForm({ ...form, description: event.target.value })}/>
        <Box display="grid" gap={2} gridTemplateColumns={{ xs: '1fr', sm: '1fr 1fr' }}>
          <TextField
            select label="Responsible vendor (NPT / UPA)" disabled={planned} value={planned ? '' : form.vendor_id}
            onChange={event => setForm({ ...form, vendor_id: event.target.value, vendor_subcategory_id: '' })}
            helperText={planned ? 'Not applicable for planned activities.' : 'From the Vendors register in Master Data.'}
          >
            <MenuItem value="">{planned ? 'Not Applicable' : 'Select a vendor'}</MenuItem>
            {vendors.map(vendor => <MenuItem key={vendor.id} value={vendor.id}>{vendor.vendor_name}</MenuItem>)}
          </TextField>
          <TextField
            select label="Vendor service subcategory" disabled={planned || !form.vendor_id} value={planned ? '' : form.vendor_subcategory_id}
            onChange={event => setForm({ ...form, vendor_subcategory_id: event.target.value })}
            helperText={form.vendor_id && !linesForVendor.length ? 'None configured for this vendor yet.' : 'Optional service line of the selected vendor.'}
          >
            <MenuItem value="">{linesForVendor.length ? 'No service subcategory' : 'None configured'}</MenuItem>
            {linesForVendor.map(line => <MenuItem key={line.id} value={line.id}>{line.display_name}</MenuItem>)}
          </TextField>
        </Box>
        {!planned && !vendors.length && <Alert severity="warning">No active vendors are available. Add the responsible vendor under Master Data → Vendors first.</Alert>}
        {error && <Alert severity="error">{error}</Alert>}
      </Box>
    </FormDialog>
  </>
}
