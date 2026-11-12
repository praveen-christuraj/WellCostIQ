/**
 * Reusable templates: a saved starting point for an AFE estimate, a well plan or
 * a daily sheet.
 *
 * The workflow is always the same and always explicit:
 *   1. pick a template (the picker shows how many lines it adds and how many of
 *      them are no longer available),
 *   2. the record page fills only what the template carries,
 *   3. the user edits the values that change and saves the ordinary record.
 *
 * Applying a template never saves anything by itself, so every existing rule —
 * validation, locks, audit — still applies to the record the user saves.
 */
export type TemplateKind = 'afe' | 'well' | 'daily-cost'

export const TEMPLATE_KINDS: { value: TemplateKind; label: string; short: string; hint: string }[] = [
  {
    value: 'afe',
    label: 'AFE estimate template',
    short: 'AFE estimate',
    hint: 'The standard service, consumable and tangible lines of an estimate. Pick it on a new AFE and fill only the amounts that change.',
  },
  {
    value: 'well',
    label: 'Well configuration template',
    short: 'Well configuration',
    hint: 'The standard hole sections, phases and planned days. Pick it while configuring a well and adjust the depths and days.',
  },
  {
    value: 'daily-cost',
    label: 'Daily cost sheet template',
    short: 'Daily cost sheet',
    hint: 'The daily lines a rig repeats — services, consumables and stand-by. Pick it on a new day and change only what happened.',
  },
]

export const TEMPLATE_KIND_LABEL: Record<TemplateKind, string> = {
  afe: 'AFE estimate',
  well: 'Well configuration',
  'daily-cost': 'Daily cost sheet',
}

export type TemplateSummary = {
  id: string
  owner_id: string
  owner_name: string
  template_kind: TemplateKind
  name: string
  description: string
  scope: string
  afe_type: string
  standard_currency: string
  is_shared: boolean
  is_owner: boolean
  use_count: number
  last_used_at: string | null
  line_count: number
  unavailable_count: number
  updated_at: string
}

export type TemplateServiceLine = {
  service_id: string
  service_code: string
  service_name: string
  charging_basis: 'Day Rate' | 'Per Service Rate' | 'Per Section Rate'
  section_code: string
  section_label: string
  phase_code: string
  phase_label: string
  currency: string
  service_amount: string
  operation_rate: string | null
  standby_rate: string | null
  repair_rate: string | null
  operation_days: string | null
  standby_days: string | null
  repair_days: string | null
  quantity_unit: 'days' | 'hours'
  remarks: string
  is_available: boolean
}

export type TemplateConsumableLine = {
  category: 'Mud Chemicals' | 'Cement Additives' | 'Fuel' | 'Drill Bits'
  section_code: string
  section_label: string
  phase_code: string
  phase_label: string
  drill_bit_id: string | null
  drill_bit_code: string
  drill_bit_name: string
  quantity: string
  estimated_amount: string | null
  currency: string
  remarks: string
  is_available: boolean
}

export type TemplateTangibleLine = {
  tangible_id: string
  tangible_code: string
  tangible_name: string
  quantity: string
  remarks: string
  is_available: boolean
}

export type TemplateWellPhase = {
  phase_id: string
  phase_code: string
  phase_name: string
  days: string
  remarks: string
  is_available: boolean
}

export type TemplateWellSection = {
  hole_section_id: string
  section_code: string
  section_name: string
  from_depth: string
  to_depth: string
  depth_unit: string
  remarks: string
  phases: TemplateWellPhase[]
  is_available: boolean
}

export type Template = TemplateSummary & {
  services: TemplateServiceLine[]
  consumables: TemplateConsumableLine[]
  tangibles: TemplateTangibleLine[]
  sections: TemplateWellSection[]
  created_at: string
}

export type TemplateApplyLine = {
  kind: 'service' | 'consumable' | 'tangible' | 'section'
  label: string
  is_available: boolean
  note: string
}

export type TemplateApplyPreview = {
  template_id: string
  template_kind: TemplateKind
  name: string
  services: TemplateApplyLine[]
  consumables: TemplateApplyLine[]
  tangibles: TemplateApplyLine[]
  sections: TemplateApplyLine[]
  warnings: string[]
  can_apply: boolean
}

/** The body the template editor posts: shape shared by create and update. */
export type TemplateInput = {
  template_kind: TemplateKind
  name: string
  description: string
  scope: string
  afe_type: 'Drilling' | 'Completion'
  standard_currency: string
  is_shared: boolean
  services: Omit<TemplateServiceLine, 'service_code' | 'service_name' | 'section_label' | 'phase_label' | 'is_available'>[]
  consumables: Omit<TemplateConsumableLine, 'section_label' | 'phase_label' | 'drill_bit_code' | 'drill_bit_name' | 'is_available'>[]
  tangibles: Omit<TemplateTangibleLine, 'tangible_code' | 'tangible_name' | 'is_available'>[]
  sections: {
    hole_section_id: string
    from_depth: string
    to_depth: string
    remarks: string
    phases: { phase_id: string; days: string; remarks: string }[]
  }[]
}

/** A blank template of one kind, so the editor starts from a known shape. */
export function emptyTemplate(kind: TemplateKind, scope = 'Drilling'): TemplateInput {
  return {
    template_kind: kind,
    name: '',
    description: '',
    scope,
    afe_type: 'Drilling',
    standard_currency: '',
    is_shared: false,
    services: [],
    consumables: [],
    tangibles: [],
    sections: [],
  }
}

/** An existing template as the editor's working copy. */
export function templateToInput(template: Template): TemplateInput {
  return {
    template_kind: template.template_kind,
    name: template.name,
    description: template.description,
    scope: template.scope,
    afe_type: (template.afe_type === 'Completion' ? 'Completion' : 'Drilling'),
    standard_currency: template.standard_currency,
    is_shared: template.is_shared,
    services: template.services.map(line => ({
      service_id: line.service_id,
      charging_basis: line.charging_basis,
      section_code: line.section_code,
      phase_code: line.phase_code,
      currency: line.currency,
      service_amount: line.service_amount,
      operation_rate: line.operation_rate,
      standby_rate: line.standby_rate,
      repair_rate: line.repair_rate,
      operation_days: line.operation_days,
      standby_days: line.standby_days,
      repair_days: line.repair_days,
      quantity_unit: line.quantity_unit,
      remarks: line.remarks,
    })),
    consumables: template.consumables.map(line => ({
      category: line.category,
      section_code: line.section_code,
      phase_code: line.phase_code,
      drill_bit_id: line.drill_bit_id,
      quantity: line.quantity,
      estimated_amount: line.estimated_amount,
      currency: line.currency,
      remarks: line.remarks,
    })),
    tangibles: template.tangibles.map(line => ({
      tangible_id: line.tangible_id,
      quantity: line.quantity,
      remarks: line.remarks,
    })),
    sections: template.sections.map(section => ({
      hole_section_id: section.hole_section_id,
      from_depth: section.from_depth,
      to_depth: section.to_depth,
      remarks: section.remarks,
      phases: section.phases.map(phase => ({
        phase_id: phase.phase_id, days: phase.days, remarks: phase.remarks,
      })),
    })),
  }
}

/** Why a template cannot be saved yet, or '' when it can. */
export function templateProblem(template: TemplateInput): string {
  if (!template.name.trim()) return 'Enter a name for this template.'
  if (template.name.trim().length > 120) return 'Keep the name under 120 characters.'
  if (template.template_kind === 'well') {
    if (!template.sections.length) return 'Add at least one hole section.'
    const emptyPhase = template.sections.some(section => !section.phases.length)
    if (emptyPhase) return 'Every hole section needs at least one phase.'
    return ''
  }
  if (!(template.services.length || template.consumables.length || template.tangibles.length)) {
    return 'Add at least one line to this template.'
  }
  return ''
}

/** Total planned days in a well plan template, for the summary line. */
export function plannedDays(template: { sections: { phases: { days: string | number }[] }[] }): number {
  const sections = template.sections ?? []
  return sections.reduce((total, section) => total
    + section.phases.reduce((sum, phase) => sum + (Number(phase.days) || 0), 0), 0)
}

export function formatTemplateDate(value: string | null): string {
  if (!value) return 'Never used'
  const [date] = value.split('T')
  const [year, month, day] = date.split('-')
  return year && month && day ? `${day}/${month}/${year}` : value
}

/** A well's plan section, as returned by the AFE well scope. */
type PlanSection = { hole_section_id: string; section_code: string; phases: { phase_id: string; phase_code: string }[] }

/**
 * Resolve a template's saved scope *codes* against a well's own plan.
 *
 * A template is written once for a hole section named "17-1/2" and used on many
 * wells; the wells' plans carry ids that differ. Resolving by code is what makes
 * one template apply everywhere. A code the plan does not have resolves to null,
 * and the caller asks the user to choose a scope instead of guessing.
 */
export function resolveScope(
  plan: { sections: PlanSection[] } | null | undefined,
  sectionCode: string,
  phaseCode: string,
): { sectionId: string | null; phaseId: string | null; missing: boolean } {
  if (!sectionCode) return { sectionId: null, phaseId: null, missing: false }
  const sections = plan?.sections ?? []
  const section = sections.find(item => item.section_code.toUpperCase() === sectionCode.toUpperCase())
  if (!section) return { sectionId: null, phaseId: null, missing: true }
  if (!phaseCode) return { sectionId: section.hole_section_id, phaseId: null, missing: false }
  const phase = section.phases.find(item => item.phase_code.toUpperCase() === phaseCode.toUpperCase())
  return phase
    ? { sectionId: section.hole_section_id, phaseId: phase.phase_id, missing: false }
    : { sectionId: section.hole_section_id, phaseId: null, missing: true }
}
