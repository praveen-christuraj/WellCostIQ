import { useEffect, useMemo, useState } from 'react'
import { Alert, Box, Button, MenuItem, TextField, ToggleButton, ToggleButtonGroup, Typography } from '@mui/material'
import { FormDialog } from '../Common'
import {
  CHARGE_CATEGORIES, CHARGING_BASES, ONE_TIME_CATEGORIES, daysText, emptyServiceLine, phaseOptions, scopeRows, sectionOptions, serviceProblems,
  toDays, type AfeReference, type ChargeCategory, type ChargingBasis, type QuantityUnit, type ScopeRateIn,
  type ServiceLineInput, type WellScope,
} from '../../lib/afe'
import { defaultCurrencyCode } from '../../lib/masterData'
import { ServicePicker } from './LinePickers'

const BASIS_HINT: Record<ChargingBasis, string> = {
  'Day Rate': 'Rate per day. Enter one rate for the whole service, or a rate for each section and phase of the well — the service total is the sum of every section amount. One-time charges are added once.',
  'Per Service Rate': 'One lump sum for this service in the chosen section and phase.',
  'Per Section Rate': 'A separate amount for each section (and phase) of the well plan.',
}

const DAY_CATEGORIES = CHARGE_CATEGORIES.filter(category => !ONE_TIME_CATEGORIES.includes(category))

type Props = {
  open: boolean
  initial: ServiceLineInput | null
  scope: WellScope
  reference: AfeReference
  onClose: () => void
  onSave: (line: ServiceLineInput) => void
}

// Adds or edits one service line. A line is priced from the well plan it is scoped to.
export function ServiceLineDialog({ open, initial, scope, reference, onClose, onSave }: Props) {
  const [line, setLine] = useState<ServiceLineInput>(() => emptyServiceLine())
  const [baseline, setBaseline] = useState<ServiceLineInput | null>(null)
  const [submitted, setSubmitted] = useState(false)
  const [chargeCategory, setChargeCategory] = useState<ChargeCategory>('Standby')
  const [chargeQuantity, setChargeQuantity] = useState('')
  const [chargeUnit, setChargeUnit] = useState<QuantityUnit>('days')

  useEffect(() => {
    if (!open) return
    const next = initial ? structuredClone(initial) : emptyServiceLine()
    // New lines start in the workspace default currency, so it rarely has to be picked.
    if (!next.currency) next.currency = defaultCurrencyCode(reference.currencies)
    setLine(next)
    setBaseline(next)
    setSubmitted(false)
    setChargeQuantity('')
    setChargeCategory('Standby')
    setChargeUnit('days')
  }, [open, initial, reference.currencies])
  // Unsaved-changes guard: everything typed or picked in this dialog is protected.
  const dirty = baseline !== null && JSON.stringify(line) !== JSON.stringify(baseline)

  const sections = useMemo(() => sectionOptions(scope), [scope])
  const phases = useMemo(() => phaseOptions(scope, line.hole_section_id), [scope, line.hole_section_id])
  const problems = serviceProblems(line)
  const currencies = reference.currencies

  const update = (patch: Partial<ServiceLineInput>) => setLine(current => ({ ...current, ...patch }))

  const setBasis = (basis: ChargingBasis | null) => {
    if (!basis) return
    setLine(current => ({
      ...current,
      charging_basis: basis,
      // Per-section lines carry their scope in each section row, so they have no single section.
      hole_section_id: basis === 'Per Section Rate' ? null : current.hole_section_id,
      phase_id: basis === 'Per Section Rate' ? null : current.phase_id,
    }))
  }

  const setRate = (category: ChargeCategory, value: string) => {
    setLine(current => {
      const others = current.rates.filter(rate => rate.category !== category)
      return { ...current, rates: value === '' ? others : [...others, { category, unit_rate: value }] }
    })
  }
  const rateFor = (category: ChargeCategory) => line.rates.find(rate => rate.category === category)?.unit_rate ?? ''

  const addCharge = () => {
    if (!chargeQuantity.trim() || Number(chargeQuantity) <= 0) return
    setLine(current => ({
      ...current,
      charges: [...current.charges.filter(charge => charge.category !== chargeCategory), { category: chargeCategory, quantity: chargeQuantity.trim(), quantity_unit: chargeUnit }],
    }))
    setChargeQuantity('')
  }
  const removeCharge = (category: ChargeCategory) => setLine(current => ({ ...current, charges: current.charges.filter(charge => charge.category !== category) }))

  // ---- One-dialog scope configuration (Day Rate) -----------------------------
  // Every section and phase of the well gets its own rate row, so a service that
  // costs differently per section is still one line; its amount is the sum.
  const scopeSections = useMemo(() => sectionOptions(scope), [scope])
  const [scopeSectionId, setScopeSectionId] = useState<string>('')
  const [scopePhaseId, setScopePhaseId] = useState<string>('')
  const [scopeCategory, setScopeCategory] = useState<ChargeCategory>('Operation')
  const [scopeRate, setScopeRate] = useState('')
  const [scopeDays, setScopeDays] = useState('')
  const [scopeDaysUnit, setScopeDaysUnit] = useState<QuantityUnit>('days')

  const scopeKey = (sectionId: string | null, phaseId: string | null) => `${sectionId ?? ''}|${phaseId ?? ''}`
  const setScopedRate = (sectionId: string, phaseId: string | null, category: ChargeCategory, value: string) => {
    setLine(current => {
      const others = current.scope_rates.filter(rate =>
        !(rate.hole_section_id === sectionId && rate.phase_id === phaseId && rate.category === category))
      return {
        ...current,
        scope_rates: value === '' ? others : [...others, { hole_section_id: sectionId, phase_id: phaseId, category, unit_rate: value }],
      }
    })
  }
  const scopedDays = (sectionId: string, phaseId: string | null, category: ChargeCategory) =>
    line.scope_days.find(row => row.hole_section_id === sectionId && row.phase_id === phaseId && row.category === category)
  const setScopedDays = (sectionId: string, phaseId: string | null, category: ChargeCategory, quantity: string, unit: QuantityUnit) => {
    setLine(current => {
      const others = current.scope_days.filter(row =>
        !(row.hole_section_id === sectionId && row.phase_id === phaseId && row.category === category))
      return {
        ...current,
        scope_days: quantity === ''
          ? others
          : [...others, { hole_section_id: sectionId, phase_id: phaseId, category, quantity, quantity_unit: unit }],
      }
    })
  }

  const addScope = () => {
    if (!scopeSectionId || !scopeRate.trim() || Number(scopeRate) <= 0) return
    const phaseId = scopePhaseId || null
    setScopedRate(scopeSectionId, phaseId, scopeCategory, scopeRate.trim())
    if (scopeDays.trim() && Number(scopeDays) > 0) {
      setScopedDays(scopeSectionId, phaseId, scopeCategory, scopeDays.trim(), scopeDaysUnit)
    }
    setScopeRate('')
    setScopeDays('')
  }
  const removeScope = (rate: ScopeRateIn) => {
    if (!rate.hole_section_id) return
    setScopedRate(rate.hole_section_id, rate.phase_id, rate.category, '')
    setScopedDays(rate.hole_section_id, rate.phase_id, rate.category, '', 'days')
  }

  // The rate rows grouped by section, so the dialog reads like the well plan.
  const scopedRows = useMemo(() => {
    const rows = new Map<string, { key: string; sectionId: string; phaseId: string | null; section: string; phase: string; days: string }>()
    for (const section of scopeSections) {
      const label = section.label
      if (!section.phases.length) {
        rows.set(scopeKey(section.id, null), { key: scopeKey(section.id, null), sectionId: section.id, phaseId: null, section: label, phase: 'No phase', days: section.days })
        continue
      }
      for (const phase of section.phases) {
        const phaseId = phase.phase_id
        rows.set(scopeKey(section.id, phaseId), {
          key: scopeKey(section.id, phaseId), sectionId: section.id, phaseId, section: label,
          phase: `${phase.phase_code} · ${phase.phase_name}`, days: phase.days,
        })
      }
    }
    // Rates already entered for a scope that was later removed stay visible, so
    // nothing is priced invisibly.
    for (const rate of line.scope_rates) {
      if (!rate.hole_section_id) continue
      const key = scopeKey(rate.hole_section_id, rate.phase_id)
      if (!rows.has(key)) {
        rows.set(key, {
          key, sectionId: rate.hole_section_id, phaseId: rate.phase_id,
          section: rate.hole_section_id, phase: rate.phase_id ?? 'No phase', days: '0',
        })
      }
    }
    return [...rows.values()]
  }, [scopeSections, line.scope_rates])

  const sectionRows = useMemo(() => scopeRows(scope), [scope])
  const sectionAmount = (sectionId: string, phaseId: string | null) => line.section_rates.find(rate => rate.hole_section_id === sectionId && rate.phase_id === phaseId)?.amount ?? ''
  const setSectionAmount = (sectionId: string, phaseId: string | null, value: string) => {
    setLine(current => {
      const others = current.section_rates.filter(rate => !(rate.hole_section_id === sectionId && rate.phase_id === phaseId))
      return { ...current, section_rates: value === '' ? others : [...others, { hole_section_id: sectionId, phase_id: phaseId, amount: value }] }
    })
  }

  const save = () => {
    setSubmitted(true)
    if (problems.length) return
    // Keep only meaningful entries so the saved line stays tidy.
    onSave({
      ...line,
      remarks: line.remarks.trim(),
      rates: line.rates.filter(rate => rate.unit_rate !== ''),
      charges: line.charges.filter(charge => Number(charge.quantity) > 0),
      section_rates: line.section_rates.filter(rate => Number(rate.amount) > 0),
      scope_rates: line.scope_rates.filter(rate => Number(rate.unit_rate) > 0),
      scope_days: line.scope_days.filter(row => Number(row.quantity) > 0),
      service_amount: line.charging_basis === 'Per Service Rate' ? line.service_amount || '0' : '0',
      hole_section_id: line.charging_basis === 'Per Section Rate' ? null : line.hole_section_id || null,
      phase_id: line.charging_basis === 'Per Section Rate' ? null : line.phase_id || null,
    })
  }

  const showProblems = submitted && problems.length > 0

  return <FormDialog
    open={open}
    title={initial ? 'Edit service line' : 'Add service'}
    subtitle="Choose a service from Master Data, how it is charged, and the rates. Sections and phases come from the well plan."
    onClose={onClose}
    onSubmit={save}
    dirty={dirty}
    submitLabel={initial ? 'Save line' : 'Add service'}
    maxWidth="md"
  >
    <Box display="grid" gap={2}>
      <ServicePicker value={line.service_id} options={reference.services} onChange={id => update({ service_id: id })} error={submitted && !line.service_id}/>

      <Box>
        <Typography fontSize={11} fontWeight={800} color="text.secondary" textTransform="uppercase" letterSpacing={.7} mb={.8}>Charging basis</Typography>
        <ToggleButtonGroup exclusive size="small" value={line.charging_basis} onChange={(_event, basis: ChargingBasis | null) => setBasis(basis)} fullWidth>
          {CHARGING_BASES.map(basis => <ToggleButton key={basis} value={basis} sx={{ textTransform: 'none', fontWeight: 700 }}>{basis}</ToggleButton>)}
        </ToggleButtonGroup>
        <Typography fontSize={12} color="text.secondary" mt={.8}>{BASIS_HINT[line.charging_basis]}</Typography>
      </Box>

      <Box display="grid" gap={1.6} sx={{ gridTemplateColumns: { xs: '1fr', sm: '1fr 1fr' } }}>
        {line.charging_basis !== 'Per Section Rate' && <TextField
          select label={line.charging_basis === 'Per Service Rate' ? 'Section (required)' : 'Section'} value={line.hole_section_id ?? ''}
          onChange={event => update({ hole_section_id: event.target.value || null, phase_id: null })}
          helperText={line.charging_basis === 'Day Rate' ? 'All sections splits the amount by each section’s planned days.' : 'Section from the well plan.'}
          error={submitted && line.charging_basis === 'Per Service Rate' && !line.hole_section_id}
        >
          {line.charging_basis === 'Day Rate' && <MenuItem value="">All sections (split by planned days)</MenuItem>}
          {sections.map(section => <MenuItem key={section.id} value={section.id}>{section.label}</MenuItem>)}
        </TextField>}
        {line.charging_basis !== 'Per Section Rate' && <TextField
          select label="Phase" value={line.phase_id ?? ''} onChange={event => update({ phase_id: event.target.value || null })}
          disabled={!line.hole_section_id}
          helperText={!line.hole_section_id ? 'Choose a section first.' : 'Optional. Limits the charge to one phase of the section.'}
        >
          <MenuItem value="">All phases</MenuItem>
          {phases.map(phase => <MenuItem key={phase.id} value={phase.id}>{phase.label} · {daysText(phase.days)}</MenuItem>)}
        </TextField>}
        <TextField
          select label="Currency" required value={line.currency} onChange={event => update({ currency: event.target.value })}
          error={submitted && !line.currency}
          helperText="From Master Data → Currency. Lines in different currencies are totalled separately."
        >
          {currencies.map(currency => <MenuItem key={currency.code} value={currency.code}>{currency.code} · {currency.name}</MenuItem>)}
        </TextField>
        <TextField label="Remarks" value={line.remarks} onChange={event => update({ remarks: event.target.value })} inputProps={{ maxLength: 500 }}/>
      </Box>

      {line.charging_basis === 'Day Rate' && <Box display="grid" gap={1.6}>
        <Box>
          <Typography fontSize={11} fontWeight={800} color="text.secondary" textTransform="uppercase" letterSpacing={.7} mb={.8}>Unit rates</Typography>
          <Box display="grid" gap={1} sx={{ gridTemplateColumns: { xs: '1fr', sm: '1fr 1fr' } }}>
            {CHARGE_CATEGORIES.map(category => <TextField
              key={category}
              size="small"
              label={category}
              value={rateFor(category)}
              onChange={event => setRate(category, event.target.value.replace(/[^0-9.]/g, ''))}
              helperText={ONE_TIME_CATEGORIES.includes(category) ? 'Charged once per line' : 'Per day'}
              inputProps={{ inputMode: 'decimal' }}
            />)}
          </Box>
        </Box>
        <Box>
          <Typography fontSize={11} fontWeight={800} color="text.secondary" textTransform="uppercase" letterSpacing={.7} mb={.8}>Days for day-based charges (optional)</Typography>
          <Typography fontSize={12} color="text.secondary" mb={1}>
            Operation uses the planned days of the chosen scope unless you enter Operation days here. Enter days (for example 0.73) or hours (converted at 24 hours per day).
          </Typography>
          <Box display="grid" gap={1} sx={{ gridTemplateColumns: { xs: '1fr', sm: '1.4fr 1fr 1fr auto' }, alignItems: 'start' }}>
            <TextField select size="small" label="Category" value={chargeCategory} onChange={event => setChargeCategory(event.target.value as ChargeCategory)}>
              {DAY_CATEGORIES.map(category => <MenuItem key={category} value={category}>{category}</MenuItem>)}
            </TextField>
            <TextField size="small" label="Quantity" value={chargeQuantity} onChange={event => setChargeQuantity(event.target.value.replace(/[^0-9.]/g, ''))} inputProps={{ inputMode: 'decimal' }}
              helperText={chargeQuantity ? `= ${daysText(toDays(chargeQuantity, chargeUnit))}` : ' '}/>
            <TextField select size="small" label="Unit" value={chargeUnit} onChange={event => setChargeUnit(event.target.value as QuantityUnit)}>
              <MenuItem value="days">Days</MenuItem>
              <MenuItem value="hours">Hours</MenuItem>
            </TextField>
            <Button variant="outlined" onClick={addCharge} disabled={!chargeQuantity || Number(chargeQuantity) <= 0} sx={{ height: 40 }}>Add</Button>
          </Box>
          {line.charges.length > 0 && <Box mt={1} display="grid" gap={.6}>
            {line.charges.map(charge => <Box key={charge.category} display="flex" justifyContent="space-between" alignItems="center" sx={{ border: 1, borderColor: 'divider', borderRadius: 1, px: 1.2, py: .6 }}>
              <Typography fontSize={12.5}>{charge.category} · {charge.quantity} {charge.quantity_unit} = {daysText(toDays(charge.quantity, charge.quantity_unit))}</Typography>
              <Button size="small" color="error" onClick={() => removeCharge(charge.category)}>Remove</Button>
            </Box>)}
          </Box>}
        </Box>
      </Box>}

      {line.charging_basis === 'Day Rate' && <Box>
        <Box display="flex" justifyContent="space-between" alignItems="baseline" flexWrap="wrap" gap={1} mb={.8}>
          <Typography fontSize={11} fontWeight={800} color="text.secondary" textTransform="uppercase" letterSpacing={.7}>
            Rate for each section and phase
          </Typography>
          <Typography fontSize={12} color="text.secondary">
            One service, every section. Amounts add up to the service total.
          </Typography>
        </Box>
        <Typography fontSize={12} color="text.secondary" mb={1}>
          Enter a rate for a section (optionally one phase of it) and add it. Leave the well-wide unit rates above when one rate covers every section — a section rate overrides it for that section only.
        </Typography>
        <Box display="grid" gap={1} sx={{ gridTemplateColumns: { xs: '1fr', sm: '1.2fr 1fr 1fr 1fr' }, alignItems: 'start', mb: 1.2 }}>
          <TextField select size="small" label="Section" value={scopeSectionId}
            onChange={event => { setScopeSectionId(event.target.value); setScopePhaseId('') }}>
            {scopeSections.map(section => <MenuItem key={section.id} value={section.id}>{section.label}</MenuItem>)}
          </TextField>
          <TextField select size="small" label="Phase" value={scopePhaseId} disabled={!scopeSectionId}
            onChange={event => setScopePhaseId(event.target.value)}
            helperText={scopeSectionId ? 'All phases when left empty.' : 'Choose a section first.'}>
            <MenuItem value="">All phases</MenuItem>
            {(scopeSections.find(section => section.id === scopeSectionId)?.phases ?? []).map(phase => (
              <MenuItem key={phase.phase_id} value={phase.phase_id}>{phase.phase_code} · {phase.phase_name}</MenuItem>
            ))}
          </TextField>
          <TextField select size="small" label="Charge category" value={scopeCategory}
            onChange={event => setScopeCategory(event.target.value as ChargeCategory)}>
            {DAY_CATEGORIES.map(category => <MenuItem key={category} value={category}>{category}</MenuItem>)}
          </TextField>
          <TextField size="small" label="Rate per day" value={scopeRate} inputProps={{ inputMode: 'decimal' }}
            onChange={event => setScopeRate(event.target.value.replace(/[^0-9.]/g, ''))}/>
          <TextField size="small" label="Days (optional)" value={scopeDays} inputProps={{ inputMode: 'decimal' }}
            onChange={event => setScopeDays(event.target.value.replace(/[^0-9.]/g, ''))}
            helperText={scopeDays ? `= ${daysText(toDays(scopeDays, scopeDaysUnit))}` : 'Well-plan days when empty.'}/>
          <TextField select size="small" label="Days unit" value={scopeDaysUnit}
            onChange={event => setScopeDaysUnit(event.target.value as QuantityUnit)}>
            <MenuItem value="days">Days</MenuItem>
            <MenuItem value="hours">Hours</MenuItem>
          </TextField>
          <Button variant="outlined" onClick={addScope} disabled={!scopeSectionId || !scopeRate || Number(scopeRate) <= 0} sx={{ height: 40 }}>
            Add section rate
          </Button>
        </Box>

        <Box sx={{ border: 1, borderColor: 'divider', borderRadius: 1.5, overflow: 'hidden' }}>
          {scopedRows.map(row => {
            const entered = line.scope_rates.filter(rate => rate.hole_section_id === row.sectionId && rate.phase_id === row.phaseId)
            return <Box key={row.key} px={1.4} py={1} sx={{ borderBottom: 1, borderColor: 'divider', '&:last-child': { borderBottom: 0 } }}>
              <Box display="flex" justifyContent="space-between" alignItems="baseline" flexWrap="wrap" gap={1}>
                <Typography fontSize={13} fontWeight={700}>{row.section} · {row.phase}</Typography>
                <Typography fontSize={12} color="text.secondary">{daysText(row.days)} planned</Typography>
              </Box>
              {entered.length === 0
                ? <Typography fontSize={12} color="text.secondary">No section rate — uses the well-wide rate above, or skipped when that is empty.</Typography>
                : <Box display="grid" gap={1} mt={.6}>
                  {entered.map(rate => {
                    const days = scopedDays(rate.hole_section_id ?? '', rate.phase_id, rate.category)
                    return <Box key={`${rate.category}`} display="grid" gap={1} alignItems="start"
                      sx={{ gridTemplateColumns: { xs: '1fr', sm: '1fr 1fr 1fr auto' } }}>
                      <Typography fontSize={12.5} fontWeight={700} sx={{ pt: .8 }}>{rate.category}</Typography>
                      <TextField size="small" label="Rate per day" value={rate.unit_rate} inputProps={{ inputMode: 'decimal' }}
                        onChange={event => setScopedRate(row.sectionId, row.phaseId, rate.category, event.target.value.replace(/[^0-9.]/g, ''))}/>
                      <TextField size="small" label="Days" value={days?.quantity ?? ''} inputProps={{ inputMode: 'decimal' }}
                        onChange={event => setScopedDays(row.sectionId, row.phaseId, rate.category, event.target.value.replace(/[^0-9.]/g, ''),
                          days?.quantity_unit ?? 'days')}
                        helperText={days?.quantity
                          ? `= ${daysText(toDays(days.quantity, days.quantity_unit))}`
                          : 'Well-plan days'}/>
                      <Button size="small" color="error" onClick={() => removeScope(rate)} sx={{ mt: .4 }}>Remove</Button>
                    </Box>
                  })}
                </Box>}
            </Box>
          })}
        </Box>
        <Typography fontSize={12} color="text.secondary" mt={.8}>
          Leave a section empty to skip it. The service is printed once, with the totals of every section it covers.
        </Typography>
      </Box>}

      {line.charging_basis === 'Per Service Rate' && <TextField
        label="Amount for this service" required value={line.service_amount}
        onChange={event => update({ service_amount: event.target.value.replace(/[^0-9.]/g, '') })}
        inputProps={{ inputMode: 'decimal' }} error={submitted && toNumberSafe(line.service_amount) <= 0}
        helperText="Lump sum applied once for the chosen section and phase."
      />}

      {line.charging_basis === 'Per Section Rate' && <Box>
        <Typography fontSize={11} fontWeight={800} color="text.secondary" textTransform="uppercase" letterSpacing={.7} mb={.8}>Rate for each section and phase</Typography>
        <Box sx={{ border: 1, borderColor: 'divider', borderRadius: 1.5, overflow: 'hidden' }}>
          {sectionRows.map(row => <Box key={row.key} display="grid" alignItems="center" gap={1} px={1.4} py={.9} sx={{ gridTemplateColumns: { xs: '1fr', sm: '1.3fr 1fr 0.8fr 1fr' }, borderBottom: 1, borderColor: 'divider', '&:last-child': { borderBottom: 0 } }}>
            <Typography fontSize={13} fontWeight={700}>{row.section}</Typography>
            <Typography fontSize={12.5} color="text.secondary">{row.phase}</Typography>
            <Typography fontSize={12} color="text.secondary">{daysText(row.days)}</Typography>
            <TextField size="small" label="Amount" value={sectionAmount(row.sectionId, row.phaseId)} onChange={event => setSectionAmount(row.sectionId, row.phaseId, event.target.value.replace(/[^0-9.]/g, ''))} inputProps={{ inputMode: 'decimal' }}/>
          </Box>)}
        </Box>
        <Typography fontSize={12} color="text.secondary" mt={.8}>Leave a row empty to skip that section.</Typography>
      </Box>}

      {showProblems && <Alert severity="error">
        {problems.map(problem => <Typography key={problem} fontSize={12.5}>{problem}</Typography>)}
      </Alert>}
    </Box>
  </FormDialog>
}

function toNumberSafe(value: string): number {
  const parsed = Number(value)
  return Number.isFinite(parsed) ? parsed : 0
}
