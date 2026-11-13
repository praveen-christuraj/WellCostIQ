import { useCallback, useEffect, useMemo, useState } from 'react'
import {
  Alert, Box, Button, Checkbox, Chip, CircularProgress, FormControlLabel, IconButton, MenuItem,
  Paper, Table, TableBody, TableCell, TableHead, TableRow, TextField, Typography,
} from '@mui/material'
import { AddRounded, DeleteOutlineRounded, InfoOutlined } from '@mui/icons-material'
import { FormDialog, Tag, useFormDirty } from '../Common'
import { api, body } from '../../lib/api'
import type { AfeReference } from '../../lib/afe'
import {
  emptyTemplate, templateProblem, templateToInput, TEMPLATE_KIND_LABEL,
  type Template, type TemplateInput, type TemplateKind,
} from '../../lib/recordTemplates'

type ScopeOption = { code: string; label: string }

/**
 * Build or edit a template.
 *
 * The editor is intentionally the same shape as the record it seeds:
 *  - an AFE estimate template lists service, consumable and tangible lines;
 *  - a well configuration template lists hole sections with their phases and days;
 *  - a daily sheet template lists the lines a rig repeats.
 *
 * Every line is chosen from Master Data, so a template can never invent a service
 * or a rate that does not exist in the workspace.
 */
export function TemplateEditorDialog({ open, templateId, initialKind, onClose, onSaved }: {
  open: boolean
  /** null creates a template of `initialKind`. */
  templateId: string | null
  initialKind: TemplateKind
  onClose: () => void
  onSaved: (message: string) => void
}) {
  const [form, setForm] = useState<TemplateInput>(() => emptyTemplate(initialKind))
  const [reference, setReference] = useState<AfeReference | null>(null)
  const [scopes, setScopes] = useState<{ sections: ScopeOption[]; phases: ScopeOption[] }>({ sections: [], phases: [] })
  // A well plan template links hole sections and phases by Master Data *id*; an
  // AFE or daily sheet template links them by *code*. The two pickers therefore
  // need their own option lists, each keyed by what the template stores.
  const [planScopes, setPlanScopes] = useState<{ sections: ScopeOption[]; phases: ScopeOption[] }>({ sections: [], phases: [] })
  const [loading, setLoading] = useState(false)
  const [loadError, setLoadError] = useState('')
  const [saving, setSaving] = useState(false)
  const [errors, setErrors] = useState<string[]>([])
  const [addServiceId, setAddServiceId] = useState('')
  const [addTangibleId, setAddTangibleId] = useState('')
  const [addSectionId, setAddSectionId] = useState('')
  const [loadStamp] = useState(0)

  const dirty = useFormDirty(form, open)
  const referenceOpen = open

  const load = useCallback(async () => {
    setLoading(true); setLoadError('')
    try {
      const [afeReference, masterSections, masterPhases] = await Promise.all([
        api<AfeReference>('/afe/reference'),
        api<{ id: string; code: string; name: string; is_deleted?: boolean }[]>('/master-data/hole-sections'),
        api<{ id: string; code: string; name: string; is_deleted?: boolean }[]>('/master-data/phases'),
      ])
      setReference(afeReference)
      setScopes({
        sections: masterSections.filter(row => !row.is_deleted).map(row => ({ code: row.code, label: `${row.code} · ${row.name}` })),
        phases: masterPhases.filter(row => !row.is_deleted).map(row => ({ code: row.code, label: `${row.code} · ${row.name}` })),
      })
      // Master Data is the only source the well plan editor needs. (It used to
      // read the saved plan of up to twelve wells as well; the result was never
      // used, and a well without that scope answered 409 and raised an error
      // pop-up on a page that had nothing wrong with it.)
      setPlanScopes({
        sections: masterSections.filter(row => !row.is_deleted).map(row => ({ code: row.id, label: `${row.code} · ${row.name}` })),
        phases: masterPhases.filter(row => !row.is_deleted).map(row => ({ code: row.id, label: `${row.code} · ${row.name}` })),
      })
    } catch (caught) {
      setLoadError(caught instanceof Error ? caught.message : 'Master Data could not be loaded')
    } finally {
      setLoading(false)
    }
  }, [])

  useEffect(() => { if (referenceOpen) { void load() } }, [referenceOpen, load])

  // Loading the chosen template replaces the working copy; a new template starts blank.
  useEffect(() => {
    if (!open) return
    setErrors([])
    setAddServiceId(''); setAddTangibleId(''); setAddSectionId('')
    if (!templateId) { setForm(emptyTemplate(initialKind)); return }
    let cancelled = false
    const run = async () => {
      setLoading(true)
      try {
        const template = await api<Template>(`/record-templates/${templateId}`)
        if (!cancelled) setForm(templateToInput(template))
      } catch (caught) {
        if (!cancelled) setLoadError(caught instanceof Error ? caught.message : 'This template could not be loaded')
      } finally {
        if (!cancelled) setLoading(false)
      }
    }
    void run()
    return () => { cancelled = true }
  }, [open, templateId, initialKind, loadStamp])

  const kind = form.template_kind
  const sectionOptions = scopes.sections
  const planSectionOptions = planScopes.sections
  const serviceOptions = reference?.services ?? []
  const tangibleOptions = reference?.tangibles.filter(item => !form.afe_type || item.scope === form.afe_type || !item.scope) ?? []
  const bitOptions = reference?.drill_bits ?? []
  const currencies = reference?.currencies ?? []

  const totalDays = useMemo(
    () => form.sections.reduce((total, section) => total
      + section.phases.reduce((sum, phase) => sum + (Number(phase.days) || 0), 0), 0),
    [form.sections],
  )

  const update = <K extends keyof TemplateInput>(key: K, value: TemplateInput[K]) => {
    setForm(current => ({ ...current, [key]: value }))
  }

  const addService = () => {
    const service = serviceOptions.find(option => option.id === addServiceId)
    if (!service) return
    update('services', [...form.services, {
      service_id: service.id,
      charging_basis: 'Day Rate',
      section_code: '', phase_code: '',
      currency: form.standard_currency || currencies.find(item => item.is_default)?.code || currencies[0]?.code || '',
      service_amount: '0',
      operation_rate: null, standby_rate: null, repair_rate: null,
      operation_days: null, standby_days: null, repair_days: null,
      quantity_unit: 'days',
      remarks: '',
    }])
    setAddServiceId('')
  }

  const addTangible = () => {
    const tangible = tangibleOptions.find(option => option.id === addTangibleId)
    if (!tangible) return
    update('tangibles', [...form.tangibles, { tangible_id: tangible.id, quantity: '1', remarks: '' }])
    setAddTangibleId('')
  }

  const addBudgetConsumable = (category: 'Mud Chemicals' | 'Cement Additives' | 'Fuel') => {
    update('consumables', [...form.consumables, {
      category, section_code: '', phase_code: '', drill_bit_id: null, quantity: '1',
      estimated_amount: null, currency: form.standard_currency || '', remarks: '',
    }])
  }

  const addDrillBit = () => {
    update('consumables', [...form.consumables, {
      category: 'Drill Bits', section_code: '', phase_code: '', drill_bit_id: null, quantity: '1',
      estimated_amount: null, currency: '', remarks: '',
    }])
  }

  const addSection = () => {
    if (!addSectionId || form.sections.some(section => section.hole_section_id === addSectionId)) return
    update('sections', [...form.sections, {
      hole_section_id: addSectionId, from_depth: '0', to_depth: '0', remarks: '', phases: [],
    }])
    setAddSectionId('')
  }

  const save = async () => {
    setErrors([])
    const problem = templateProblem(form)
    if (problem) { setErrors([problem]); return }
    if (kind === 'well') {
      const missingPhase = form.sections.find(section => !section.phases.length)
      if (missingPhase) {
        setErrors(['Every hole section needs at least one phase. Add a phase or remove the section.'])
        return
      }
    }
    setSaving(true)
    try {
      const payload = {
        ...form,
        name: form.name.trim(),
        description: form.description.trim(),
        scope: form.scope.trim() || 'General',
        services: form.services.map(line => ({ ...line, currency: (line.currency || form.standard_currency).toUpperCase() })),
        consumables: form.consumables.map(line => ({ ...line, currency: line.currency.toUpperCase() })),
      }
      const saved = templateId
        ? await api<Template>(`/record-templates/${templateId}`, { method: 'PUT', body: body(payload) })
        : await api<Template>('/record-templates', { method: 'POST', body: body(payload) })
      onSaved(templateId
        ? `${saved.name} updated. Every record that uses it from now on starts from the new version — records already created are unchanged.`
        : `${saved.name} saved. Pick it on a new ${TEMPLATE_KIND_LABEL[kind].toLowerCase()} to start from it.`)
    } catch (caught) {
      setErrors([(caught as Error).message || 'The template could not be saved'])
    } finally {
      setSaving(false)
    }
  }

  const title = templateId ? `Edit ${TEMPLATE_KIND_LABEL[kind].toLowerCase()} template` : `New ${TEMPLATE_KIND_LABEL[kind].toLowerCase()} template`

  return <FormDialog
    open={open}
    title={title}
    subtitle="Save the way you cost a standard well once. Save it here, then pick it on new records and change only the values that differ."
    onClose={() => { if (!saving) onClose() }}
    onSubmit={() => { void save() }}
    busy={saving}
    busyLabel="Saving template..."
    dirty={dirty}
    submitLabel={templateId ? 'Save template' : 'Create template'}
    maxWidth="lg"
  >
    <Box display="grid" gap={2}>
      {loadError && <Alert severity="error">{loadError}</Alert>}
      {errors.map((message, index) => <Alert key={index} severity="error" onClose={() => setErrors(current => current.filter((_, i) => i !== index))}>{message}</Alert>)}

      <Box display="grid" gap={1.5} sx={{ gridTemplateColumns: { xs: '1fr', sm: '2fr 1fr' } }}>
        <TextField label="Template name" value={form.name} required
          onChange={event => update('name', event.target.value)}
          placeholder={kind === 'afe' ? 'Standard 17-1/2 development AFE' : kind === 'well' ? 'Standard development well plan' : 'Standard rig day — drilling ahead'}
          helperText="The name you will look for in the picker. Keep it specific enough to tell two templates apart."/>
        <TextField label="Scope / category" value={form.scope}
          onChange={event => update('scope', event.target.value)}
          helperText="Grouping only, e.g. Drilling, Completion, Workover."/>
      </Box>

      <TextField label="What this template is for" value={form.description} multiline minRows={2}
        onChange={event => update('description', event.target.value)}
        placeholder="One or two lines the next user will read before choosing it."
        helperText="Optional. Shown in the picker and in the library."/>

      {kind === 'afe' && <Box display="grid" gap={1.5} sx={{ gridTemplateColumns: { xs: '1fr', sm: '1fr 1fr 1fr' } }}>
        <TextField select label="AFE type" value={form.afe_type} onChange={event => update('afe_type', event.target.value as 'Drilling' | 'Completion')}>
          <MenuItem value="Drilling">Drilling</MenuItem>
          <MenuItem value="Completion">Completion</MenuItem>
        </TextField>
        <TextField select label="Standard currency" value={form.standard_currency}
          onChange={event => update('standard_currency', event.target.value)}
          helperText="Pre-fills new lines. A record still decides its own currency.">
          <MenuItem value="">Workspace default</MenuItem>
          {currencies.map(currency => <MenuItem key={currency.code} value={currency.code}>
            {currency.code} · {currency.name}{currency.is_default ? ' (default)' : ''}
          </MenuItem>)}
        </TextField>
        <Box display="flex" alignItems="center">
          <FormControlLabel
            control={<Checkbox checked={form.is_shared} onChange={event => update('is_shared', event.target.checked)}/>}
            label={<Typography fontSize={12.5}>Share with the whole workspace</Typography>}
          />
        </Box>
      </Box>}

      {kind !== 'afe' && <Box>
        <FormControlLabel
          control={<Checkbox checked={form.is_shared} onChange={event => update('is_shared', event.target.checked)}/>}
          label={<Typography fontSize={12.5}>Share with the whole workspace</Typography>}
        />
      </Box>}

      {kind === 'well' ? <WellSectionEditor
        form={form} sectionOptions={planSectionOptions} phaseOptions={planScopes.phases}
        totalDays={totalDays}
        addSectionId={addSectionId} setAddSectionId={setAddSectionId} onAddSection={addSection}
        update={update}
      /> : <LineEditor
        form={form} update={update}
        serviceOptions={serviceOptions} tangibleOptions={tangibleOptions}
        bitOptions={bitOptions} sectionOptions={sectionOptions} scopes={scopes}
        addServiceId={addServiceId} setAddServiceId={setAddServiceId} onAddService={addService}
        addTangibleId={addTangibleId} setAddTangibleId={setAddTangibleId} onAddTangible={addTangible}
        onAddBudgetConsumable={addBudgetConsumable} onAddDrillBit={addDrillBit}
        kind={kind}
      />}

      {loading && <Box display="flex" alignItems="center" gap={1}><CircularProgress size={16}/><Typography fontSize={12}>Loading Master Data…</Typography></Box>}

      <Alert severity="info" icon={<InfoOutlined/>}>
        <Typography fontSize={12}>
          A template stores the standard <em>structure</em>: which services, sections or lines. Rates and amounts are always read
          from Master Data and the AFE when the record is created, so a price revision never leaves a stale price inside a template.
        </Typography>
      </Alert>
    </Box>
  </FormDialog>
}

/** Service / consumable / tangible lines of an AFE or daily sheet template. */
function LineEditor({ form, update, serviceOptions, tangibleOptions, bitOptions, sectionOptions, scopes, addServiceId, setAddServiceId, onAddService, addTangibleId, setAddTangibleId, onAddTangible, onAddBudgetConsumable, onAddDrillBit, kind }: {
  form: TemplateInput
  update: <K extends keyof TemplateInput>(key: K, value: TemplateInput[K]) => void
  serviceOptions: AfeReference['services']
  tangibleOptions: AfeReference['tangibles']
  bitOptions: AfeReference['drill_bits']
  sectionOptions: ScopeOption[]
  scopes: { sections: ScopeOption[]; phases: ScopeOption[] }
  addServiceId: string
  setAddServiceId: (value: string) => void
  onAddService: () => void
  addTangibleId: string
  setAddTangibleId: (value: string) => void
  onAddTangible: () => void
  onAddBudgetConsumable: (category: 'Mud Chemicals' | 'Cement Additives' | 'Fuel') => void
  onAddDrillBit: () => void
  kind: TemplateKind
}) {
  const removeService = (index: number) => update('services', form.services.filter((_, i) => i !== index))
  const removeConsumable = (index: number) => update('consumables', form.consumables.filter((_, i) => i !== index))
  const removeTangible = (index: number) => update('tangibles', form.tangibles.filter((_, i) => i !== index))

  const patchService = (index: number, patch: Partial<TemplateInput['services'][number]>) =>
    update('services', form.services.map((line, i) => i === index ? { ...line, ...patch } : line))
  const patchConsumable = (index: number, patch: Partial<TemplateInput['consumables'][number]>) =>
    update('consumables', form.consumables.map((line, i) => i === index ? { ...line, ...patch } : line))
  const patchTangible = (index: number, patch: Partial<TemplateInput['tangibles'][number]>) =>
    update('tangibles', form.tangibles.map((line, i) => i === index ? { ...line, ...patch } : line))

  return <Box display="grid" gap={2}>
    <Paper variant="outlined" sx={{ p: 1.6, borderRadius: 2 }}>
      <SectionTitle title="Services" count={form.services.length} hint="The service lines every estimate of this kind starts with."/>
      <Box display="flex" gap={1} flexWrap="wrap" mb={form.services.length ? 1.2 : 0}>
        <TextField select size="small" label="Add a service" value={addServiceId} sx={{ minWidth: 320, flex: '1 1 320px' }}
          onChange={event => setAddServiceId(event.target.value)}>
          <MenuItem value="">Choose a service…</MenuItem>
          {serviceOptions.map(service => <MenuItem key={service.id} value={service.id}>
            {service.service_code} · {service.service_name}
          </MenuItem>)}
        </TextField>
        <Button variant="outlined" startIcon={<AddRounded/>} onClick={onAddService} disabled={!addServiceId}>Add service</Button>
      </Box>
      {form.services.length > 0 && <Box sx={{ overflowX: 'auto' }}>
        <Table size="small">
          <TableHead><TableRow>
            {['SERVICE', 'BASIS', 'HOLE SECTION', 'PHASE', 'CURRENCY', 'REMARKS', ''].map(label =>
              <TableCell key={label} sx={{ fontWeight: 800, fontSize: 10.5, whiteSpace: 'nowrap' }}>{label}</TableCell>)}
          </TableRow></TableHead>
          <TableBody>
            {form.services.map((line, index) => {
              const service = serviceOptions.find(option => option.id === line.service_id)
              return <TableRow key={`${line.service_id}-${index}`} hover>
                <TableCell sx={{ minWidth: 210, fontSize: 12 }}>
                  {service ? `${service.service_code} · ${service.service_name}` : 'Service no longer available'}
                </TableCell>
                <TableCell sx={{ minWidth: 140 }}>
                  <TextField select size="small" value={line.charging_basis} onChange={event => patchService(index, { charging_basis: event.target.value as typeof line.charging_basis })}>
                    <MenuItem value="Day Rate">Day Rate</MenuItem>
                    <MenuItem value="Per Service Rate">Per Service Rate</MenuItem>
                    <MenuItem value="Per Section Rate">Per Section Rate</MenuItem>
                  </TextField>
                </TableCell>
                <TableCell sx={{ minWidth: 160 }}>
                  <TextField select size="small" value={line.section_code} onChange={event => patchService(index, { section_code: event.target.value, phase_code: '' })}>
                    <MenuItem value="">All sections</MenuItem>
                    {sectionOptions.map(section => <MenuItem key={section.code} value={section.code}>{section.label}</MenuItem>)}
                  </TextField>
                </TableCell>
                <TableCell sx={{ minWidth: 150 }}>
                  <TextField select size="small" value={line.phase_code} onChange={event => patchService(index, { phase_code: event.target.value })} disabled={!line.section_code}>
                    <MenuItem value="">No phase</MenuItem>
                    {scopes.phases.map(phase => <MenuItem key={phase.code} value={phase.code}>{phase.label}</MenuItem>)}
                  </TextField>
                </TableCell>
                <TableCell sx={{ minWidth: 110 }}>
                  <TextField size="small" value={line.currency} onChange={event => patchService(index, { currency: event.target.value.toUpperCase() })} inputProps={{ maxLength: 10 }}/>
                </TableCell>
                <TableCell sx={{ minWidth: 180 }}>
                  <TextField size="small" value={line.remarks} onChange={event => patchService(index, { remarks: event.target.value })} placeholder="Optional" inputProps={{ maxLength: 500 }}/>
                </TableCell>
                <TableCell>
                  <IconButton size="small" color="error" onClick={() => removeService(index)} aria-label="Remove service line"><DeleteOutlineRounded sx={{ fontSize: 17 }}/></IconButton>
                </TableCell>
              </TableRow>
            })}
          </TableBody>
        </Table>
      </Box>}
    </Paper>

    <Paper variant="outlined" sx={{ p: 1.6, borderRadius: 2 }}>
      <SectionTitle title="Consumables" count={form.consumables.length} hint="Lump-sum budgets (mud, cement, fuel) or drill bits, with their scope."/>
      <Box display="flex" gap={1} flexWrap="wrap" mb={form.consumables.length ? 1.2 : 0}>
        <Button size="small" variant="outlined" startIcon={<AddRounded/>} onClick={() => onAddBudgetConsumable('Mud Chemicals')}>Mud chemicals budget</Button>
        <Button size="small" variant="outlined" startIcon={<AddRounded/>} onClick={() => onAddBudgetConsumable('Cement Additives')}>Cement additives budget</Button>
        <Button size="small" variant="outlined" startIcon={<AddRounded/>} onClick={() => onAddBudgetConsumable('Fuel')}>Fuel budget</Button>
        <Button size="small" variant="outlined" startIcon={<AddRounded/>} onClick={onAddDrillBit} disabled={!bitOptions.length}>Drill bit</Button>
      </Box>
      {form.consumables.length > 0 && <Box sx={{ overflowX: 'auto' }}>
        <Table size="small">
          <TableHead><TableRow>
            {['CATEGORY', 'ITEM', 'HOLE SECTION', 'PHASE', 'QUANTITY', 'ESTIMATED AMOUNT', 'CURRENCY', ''].map(label =>
              <TableCell key={label} sx={{ fontWeight: 800, fontSize: 10.5, whiteSpace: 'nowrap' }}>{label}</TableCell>)}
          </TableRow></TableHead>
          <TableBody>
            {form.consumables.map((line, index) => <TableRow key={`${line.category}-${index}`} hover>
              <TableCell sx={{ fontSize: 12, minWidth: 120 }}>{line.category}</TableCell>
              <TableCell sx={{ minWidth: 200 }}>
                {line.category === 'Drill Bits'
                  ? <TextField select size="small" value={line.drill_bit_id ?? ''} onChange={event => patchConsumable(index, { drill_bit_id: event.target.value || null })}>
                    <MenuItem value="">Choose a drill bit…</MenuItem>
                    {bitOptions.map(bit => <MenuItem key={bit.id} value={bit.id}>{bit.bit_code} · {bit.bit_name}</MenuItem>)}
                  </TextField>
                  : <Typography fontSize={12} color="text.secondary">Budget allowance</Typography>}
              </TableCell>
              <TableCell sx={{ minWidth: 160 }}>
                <TextField select size="small" value={line.section_code} onChange={event => patchConsumable(index, { section_code: event.target.value, phase_code: '' })}>
                  <MenuItem value="">All sections</MenuItem>
                  {sectionOptions.map(section => <MenuItem key={section.code} value={section.code}>{section.label}</MenuItem>)}
                </TextField>
              </TableCell>
              <TableCell sx={{ minWidth: 150 }}>
                <TextField select size="small" value={line.phase_code} onChange={event => patchConsumable(index, { phase_code: event.target.value })} disabled={!line.section_code}>
                  <MenuItem value="">No phase</MenuItem>
                  {scopes.phases.map(phase => <MenuItem key={phase.code} value={phase.code}>{phase.label}</MenuItem>)}
                </TextField>
              </TableCell>
              <TableCell sx={{ width: 100 }}>
                <TextField size="small" value={line.quantity} onChange={event => patchConsumable(index, { quantity: event.target.value })} inputProps={{ maxLength: 40 }}/>
              </TableCell>
              <TableCell sx={{ width: 150 }}>
                <TextField size="small" value={line.estimated_amount ?? ''} placeholder="Optional"
                  onChange={event => patchConsumable(index, { estimated_amount: event.target.value || null })} inputProps={{ maxLength: 40 }}/>
              </TableCell>
              <TableCell sx={{ width: 110 }}>
                <TextField size="small" value={line.currency} onChange={event => patchConsumable(index, { currency: event.target.value.toUpperCase() })} inputProps={{ maxLength: 10 }}/>
              </TableCell>
              <TableCell>
                <IconButton size="small" color="error" onClick={() => removeConsumable(index)} aria-label="Remove consumable line"><DeleteOutlineRounded sx={{ fontSize: 17 }}/></IconButton>
              </TableCell>
            </TableRow>)}
          </TableBody>
        </Table>
      </Box>}
    </Paper>

    <Paper variant="outlined" sx={{ p: 1.6, borderRadius: 2 }}>
      <SectionTitle title="Tangibles" count={form.tangibles.length} hint="Physical items hired or bought for this kind of well."/>
      <Box display="flex" gap={1} flexWrap="wrap" mb={form.tangibles.length ? 1.2 : 0}>
        <TextField select size="small" label="Add a tangible" value={addTangibleId} sx={{ minWidth: 320, flex: '1 1 320px' }}
          onChange={event => setAddTangibleId(event.target.value)}>
          <MenuItem value="">Choose a tangible…</MenuItem>
          {tangibleOptions.map(item => <MenuItem key={item.id} value={item.id}>{item.tangible_code} · {item.tangible_name}</MenuItem>)}
        </TextField>
        <Button variant="outlined" startIcon={<AddRounded/>} onClick={onAddTangible} disabled={!addTangibleId}>Add tangible</Button>
      </Box>
      {form.tangibles.length > 0 && <Box sx={{ overflowX: 'auto' }}>
        <Table size="small">
          <TableHead><TableRow>
            {['TANGIBLE', 'QUANTITY', 'REMARKS', ''].map(label =>
              <TableCell key={label} sx={{ fontWeight: 800, fontSize: 10.5 }}>{label}</TableCell>)}
          </TableRow></TableHead>
          <TableBody>
            {form.tangibles.map((line, index) => {
              const item = tangibleOptions.find(option => option.id === line.tangible_id)
              return <TableRow key={`${line.tangible_id}-${index}`} hover>
                <TableCell sx={{ fontSize: 12, minWidth: 240 }}>{item ? `${item.tangible_code} · ${item.tangible_name}` : 'Tangible no longer available'}</TableCell>
                <TableCell sx={{ width: 110 }}>
                  <TextField size="small" value={line.quantity} onChange={event => patchTangible(index, { quantity: event.target.value })} inputProps={{ maxLength: 40 }}/>
                </TableCell>
                <TableCell sx={{ minWidth: 200 }}>
                  <TextField size="small" value={line.remarks} onChange={event => patchTangible(index, { remarks: event.target.value })} placeholder="Optional" inputProps={{ maxLength: 500 }}/>
                </TableCell>
                <TableCell>
                  <IconButton size="small" color="error" onClick={() => removeTangible(index)} aria-label="Remove tangible line"><DeleteOutlineRounded sx={{ fontSize: 17 }}/></IconButton>
                </TableCell>
              </TableRow>
            })}
          </TableBody>
        </Table>
      </Box>}
    </Paper>

    {kind === 'daily-cost' && <Alert severity="info">
      A daily sheet template carries the lines, not the day. The rig, the well and the cost date are always chosen on the sheet itself.
    </Alert>}
  </Box>
}

/** Hole sections, phases and planned days of a well configuration template. */
function WellSectionEditor({ form, sectionOptions, phaseOptions, totalDays, addSectionId, setAddSectionId, onAddSection, update }: {
  form: TemplateInput
  sectionOptions: ScopeOption[]
  phaseOptions: ScopeOption[]
  totalDays: number
  addSectionId: string
  setAddSectionId: (value: string) => void
  onAddSection: () => void
  update: <K extends keyof TemplateInput>(key: K, value: TemplateInput[K]) => void
}) {
  const patchSection = (index: number, patch: Partial<TemplateInput['sections'][number]>) =>
    update('sections', form.sections.map((section, i) => i === index ? { ...section, ...patch } : section))
  const addPhase = (index: number, phaseId: string) => {
    const section = form.sections[index]
    if (!phaseId || section.phases.some(phase => phase.phase_id === phaseId)) return
    patchSection(index, { phases: [...section.phases, { phase_id: phaseId, days: '1', remarks: '' }] })
  }
  const phaseLabel = (phaseId: string) => phaseOptions.find(option => option.code === phaseId)?.label ?? phaseId

  return <Paper variant="outlined" sx={{ p: 1.6, borderRadius: 2 }}>
    <SectionTitle title="Hole sections and phases" count={form.sections.length} hint="From top to bottom. Each phase carries its planned days."/>
    <Box display="flex" gap={1} flexWrap="wrap" alignItems="center" mb={1.2}>
      <TextField select size="small" label="Add a hole section" value={addSectionId} sx={{ minWidth: 300, flex: '1 1 300px' }}
        onChange={event => setAddSectionId(event.target.value)}>
        <MenuItem value="">Choose a section…</MenuItem>
        {sectionOptions.map(section => <MenuItem key={section.code} value={section.code}
          disabled={form.sections.some(added => added.hole_section_id === section.code)}>
          {section.label}
        </MenuItem>)}
      </TextField>
      <Button variant="outlined" startIcon={<AddRounded/>} onClick={onAddSection} disabled={!addSectionId}>Add section</Button>
      <Box ml="auto"><Tag tone="info">{totalDays.toLocaleString()} planned days in total</Tag></Box>
    </Box>

    {!form.sections.length && <Alert severity="info" sx={{ mt: 1 }}>
      Add the hole sections this well plan always starts with, then add the phases under each one.
    </Alert>}

    <Box display="grid" gap={1.4}>
      {form.sections.map((section, index) => {
        const label = sectionOptions.find(option => option.code === section.hole_section_id)?.label ?? section.hole_section_id
        const days = section.phases.reduce((total, phase) => total + (Number(phase.days) || 0), 0)
        return <Paper key={`${section.hole_section_id}-${index}`} variant="outlined" sx={{ p: 1.4, borderRadius: 2, bgcolor: 'background.default' }}>
          <Box display="flex" alignItems="center" gap={1} flexWrap="wrap" mb={1.2}>
            <Typography fontSize={13} fontWeight={800}>{label}</Typography>
            <Tag tone="neutral">{days.toLocaleString()} days</Tag>
            <IconButton size="small" color="error" sx={{ ml: 'auto' }} aria-label={`Remove ${label}`}
              onClick={() => update('sections', form.sections.filter((_, i) => i !== index))}>
              <DeleteOutlineRounded sx={{ fontSize: 17 }}/>
            </IconButton>
          </Box>
          <Box display="grid" gap={1} mb={1.2} sx={{ gridTemplateColumns: { xs: '1fr', sm: '1fr 1fr' } }}>
            <TextField size="small" label="From depth (m)" value={section.from_depth}
              onChange={event => patchSection(index, { from_depth: event.target.value })} inputProps={{ maxLength: 40 }}/>
            <TextField size="small" label="To depth (m)" value={section.to_depth}
              onChange={event => patchSection(index, { to_depth: event.target.value })} inputProps={{ maxLength: 40 }}/>
          </Box>
          <Table size="small">
            <TableHead><TableRow>
              {['PHASE', 'PLANNED DAYS', 'REMARKS', ''].map(heading =>
                <TableCell key={heading} sx={{ fontWeight: 800, fontSize: 10.5 }}>{heading}</TableCell>)}
            </TableRow></TableHead>
            <TableBody>
              {section.phases.map((phase, phaseIndex) => <TableRow key={`${phase.phase_id}-${phaseIndex}`}>
                <TableCell sx={{ fontSize: 12 }}>{phaseLabel(phase.phase_id)}</TableCell>
                <TableCell sx={{ width: 130 }}>
                  <TextField size="small" value={phase.days}
                    onChange={event => patchSection(index, {
                      phases: section.phases.map((row, i) => i === phaseIndex ? { ...row, days: event.target.value } : row),
                    })} inputProps={{ maxLength: 40 }}/>
                </TableCell>
                <TableCell sx={{ minWidth: 200 }}>
                  <TextField size="small" value={phase.remarks}
                    onChange={event => patchSection(index, {
                      phases: section.phases.map((row, i) => i === phaseIndex ? { ...row, remarks: event.target.value } : row),
                    })} placeholder="Optional" inputProps={{ maxLength: 500 }}/>
                </TableCell>
                <TableCell>
                  <IconButton size="small" color="error" aria-label="Remove phase"
                    onClick={() => patchSection(index, { phases: section.phases.filter((_, i) => i !== phaseIndex) })}>
                    <DeleteOutlineRounded sx={{ fontSize: 17 }}/>
                  </IconButton>
                </TableCell>
              </TableRow>)}
              <TableRow>
                <TableCell colSpan={4}>
                  <AddPhaseRow options={phaseOptions} chosen={section.phases.map(phase => phase.phase_id)} onAdd={phaseId => addPhase(index, phaseId)}/>
                </TableCell>
              </TableRow>
            </TableBody>
          </Table>
        </Paper>
      })}
    </Box>
  </Paper>
}

/** The phase picker inside one section: only phases Master Data still has. */
function AddPhaseRow({ options, chosen, onAdd }: { options: ScopeOption[]; chosen: string[]; onAdd: (phaseId: string) => void }) {
  const [value, setValue] = useState('')
  return <Box display="flex" gap={1} alignItems="center" flexWrap="wrap">
    <TextField select size="small" value={value} onChange={event => setValue(event.target.value)} sx={{ minWidth: 260, flex: '1 1 260px' }}>
      <MenuItem value="">Add a phase…</MenuItem>
      {options.map(option => <MenuItem key={option.code} value={option.code} disabled={chosen.includes(option.code)}>
        {option.label}
      </MenuItem>)}
    </TextField>
    <Button size="small" startIcon={<AddRounded/>} disabled={!value} onClick={() => { onAdd(value); setValue('') }}>Add phase</Button>
  </Box>
}

function SectionTitle({ title, count, hint }: { title: string; count: number; hint: string }) {
  return <Box mb={1.2}>
    <Box display="flex" alignItems="center" gap={1}>
      <Typography fontSize={12} fontWeight={800} letterSpacing=".07em" textTransform="uppercase">{title}</Typography>
      <Chip size="small" variant="outlined" label={count}/>
    </Box>
    <Typography fontSize={11.5} color="text.secondary" mt={.3}>{hint}</Typography>
  </Box>
}
