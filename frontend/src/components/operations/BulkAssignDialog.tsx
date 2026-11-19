import { useEffect, useMemo, useState } from 'react'
import { Alert, Box, Button, Chip, Divider, MenuItem, Stack, TextField, Typography } from '@mui/material'
import { FormDialog } from '../Common'
import {
  opsBulkAssign,
  opsBulkAssignPreview,
  type OpsActivityType,
  type OpsBlock,
  type OpsBulkAssignInput,
  type OpsBulkAssignPreview,
  type OpsReference,
} from '../../lib/operations'

//: The criteria the server enforces, in the order the daily report lists them.
//: Kept here only to label the selects; the rule itself lives on the server and
//: is read back from the reference payload so the two can never drift apart.
const FIELD_LABELS: Record<string, string> = {
  hole_section_id: 'Hole Section',
  phase_id: 'Phase',
  activity_id: 'Activity',
  allocation: 'Allocation',
  cause_code: 'Cause Code',
  operation_id: 'Operations',
  responsible_agency_id: 'Responsible Agency label',
  vendor_id: 'Agency / Service Vendor',
}

type Assignment = {
  hole_section_id: string
  phase_id: string
  sub_phase_id: string
  activity_id: string
  operation_id: string
  cause_code: string
  responsible_agency_id: string
  allocation: '' | 'PT' | 'UPA' | 'NPT' | 'SP'
}

const EMPTY: Assignment = {
  hole_section_id: '',
  phase_id: '',
  sub_phase_id: '',
  activity_id: '',
  operation_id: '',
  cause_code: '',
  responsible_agency_id: '',
  allocation: '',
}

/**
 * One instruction applied to many extracted blocks.
 *
 * The dialog never writes blind. Every change is previewed first — including the
 * blocks the engine will skip and why — because the Activity-type rules differ
 * per row: a cause is required on NPT and UPA work and means nothing on Planned
 * work, because nothing went wrong.
 * The user sees the count before the save, so a bulk gesture cannot quietly
 * rewrite a day of work.
 */
export function BulkAssignDialog({
  open,
  reference,
  reportIds,
  blocks,
  onClose,
  onApplied,
}: {
  open: boolean
  reference: OpsReference | null
  reportIds: string[]
  blocks: OpsBlock[]
  onClose: () => void
  onApplied: () => void
}) {
  const [value, setValue] = useState<Assignment>(EMPTY)
  const [preview, setPreview] = useState<OpsBulkAssignPreview | null>(null)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')
  const [notice, setNotice] = useState('')
  const [kind, setKind] = useState<'' | 'drilling' | 'completion'>('')

  useEffect(() => {
    if (!open) return
    setValue(EMPTY)
    setPreview(null)
    setError('')
    setNotice('')
    setKind('')
  }, [open])

  const rules = reference?.classification_rules ?? {}
  /** The Activity types this gesture will leave on the selected blocks. */
  const targetTypes = useMemo(() => {
    const chosen = reference?.activities.find((a) => a.id === value.activity_id)?.activity_type
    if (chosen) return new Set<OpsActivityType>([chosen])
    return new Set(blocks.map((b) => b.classification as OpsActivityType))
  }, [blocks, value.activity_id, reference])

  const required = useMemo(() => {
    const wanted = new Set<string>()
    for (const type of targetTypes) for (const field of rules[type] ?? []) wanted.add(field)
    return wanted
  }, [rules, targetTypes])

  const payload = (): OpsBulkAssignInput => ({
    report_ids: reportIds,
    block_ids: [],
    block_kind: kind,
    hole_section_id: value.hole_section_id || null,
    phase_id: value.phase_id || null,
    sub_phase_id: value.sub_phase_id || null,
    activity_id: value.activity_id || null,
    operation_id: value.operation_id || null,
    cause_code: value.cause_code || null,
    responsible_agency_id: value.responsible_agency_id || null,
    allocation: value.allocation || null,
  })

  const hasChoice = Object.entries(payload()).some(
    ([key, v]) => !['report_ids', 'block_ids', 'block_kind'].includes(key) && v,
  )
  const blocked = Array.from(required).filter((field) => !value[field as keyof Assignment])
  /** A cause cannot be written to Planned work; say so before the API does. */
  const causeRefused = Boolean(value.cause_code) && targetTypes.size === 1 && targetTypes.has('Planned')

  const loadPreview = async () => {
    setBusy(true)
    setError('')
    setNotice('')
    try {
      setPreview(await opsBulkAssignPreview(payload()))
    } catch (e) {
      setPreview(null)
      setError((e as Error).message)
    } finally {
      setBusy(false)
    }
  }

  const apply = async () => {
    setBusy(true)
    setError('')
    try {
      const result = await opsBulkAssign(payload())
      setNotice(
        `${result.changed_count} block(s) updated — ${result.summary}.` +
          (result.skipped.length
            ? ` ${result.skipped.length} skipped: ${result.skipped.slice(0, 3).map((r) => `#${r.sequence_no} ${r.reason}`).join(' ')}`
            : ''),
      )
      onApplied()
      onClose()
    } catch (e) {
      setError((e as Error).message)
    } finally {
      setBusy(false)
    }
  }

  const count = preview?.changes.length ?? 0
  const skipped = preview?.skipped ?? []

  return (
    <FormDialog
      open={open}
      title="Assign criteria in bulk"
      subtitle={`Applies one explicit value to ${blocks.length} extracted block(s) in the selected report. Every value is checked against each block's Activity type before it is written; blocks that cannot hold a value are skipped and listed, never changed.`}
      onClose={onClose}
      onSubmit={() => void apply()}
      submitLabel={count ? `Assign to ${count} block(s)` : 'Assign'}
      busy={busy}
      submitDisabled={!hasChoice || Boolean(blocked.length) || causeRefused}
    >
      <Stack spacing={2} pt={0.5}>
        {error && <Alert severity="error">{error}</Alert>}
        {notice && <Alert severity="success">{notice}</Alert>}
        <Alert severity="info">
          Hole Section, Phase, Activity and Allocation are always mandatory. The Cause Code is needed only
          when the Activity is NPT or UPA; Planned work never carries one.
        </Alert>
        <Box display="grid" gap={2} gridTemplateColumns={{ xs: '1fr', sm: 'repeat(2,minmax(0,1fr))' }}>
          <TextField
            select
            label="Hole Section"
            value={value.hole_section_id}
            onChange={(e) => setValue({ ...value, hole_section_id: e.target.value })}
            helperText="Master Data Hole Sections."
          >
            <MenuItem value="">Leave unchanged</MenuItem>
            {reference?.hole_sections.map((c) => (
              <MenuItem key={c.id} value={c.id}>
                {c.label}
              </MenuItem>
            ))}
          </TextField>
          <TextField
            select
            label="Phase"
            value={value.phase_id}
            onChange={(e) => setValue({ ...value, phase_id: e.target.value, sub_phase_id: '' })}
            helperText="Master Data Phases."
          >
            <MenuItem value="">Leave unchanged</MenuItem>
            {reference?.phases.map((c) => (
              <MenuItem key={c.id} value={c.id}>
                {c.label}
              </MenuItem>
            ))}
          </TextField>
          <TextField
            select
            label="Sub-Phase"
            value={value.sub_phase_id}
            onChange={(e) => setValue({ ...value, sub_phase_id: e.target.value })}
            disabled={!value.phase_id}
            helperText={value.phase_id ? 'Code Library sub-phases of the chosen phase.' : 'Choose a phase first.'}
          >
            <MenuItem value="">Leave unchanged</MenuItem>
            {(reference?.sub_phases ?? [])
              .filter((sp) => !value.phase_id || sp.phase_id === value.phase_id)
              .map((sp) => (
                <MenuItem key={sp.id} value={sp.id}>
                  {sp.sub_phase_code} — {sp.sub_phase_name}
                </MenuItem>
              ))}
          </TextField>
          <TextField
            select
            label="Activity"
            value={value.activity_id}
            onChange={(e) => setValue({ ...value, activity_id: e.target.value })}
            helperText="The Activity's own type becomes the block's Activity type."
          >
            <MenuItem value="">Leave unchanged</MenuItem>
            {reference?.activities.map((c) => (
              <MenuItem key={c.id} value={c.id}>
                {c.label}
                {c.activity_type && c.activity_type !== 'Planned' ? ` · ${c.activity_type}` : ''}
              </MenuItem>
            ))}
          </TextField>
          <TextField
            select
            label="Allocation"
            value={value.allocation}
            onChange={(e) => setValue({ ...value, allocation: e.target.value as Assignment['allocation'] })}
            helperText="Separate from the Activity type; NPT allocation is never productive."
          >
            <MenuItem value="">Leave unchanged</MenuItem>
            <MenuItem value="PT">PT — productive time</MenuItem>
            <MenuItem value="NPT">NPT — nonproductive time</MenuItem>
            <MenuItem value="UPA">UPA — unplanned productive</MenuItem>
            <MenuItem value="SP">SP — slow progress</MenuItem>
          </TextField>
          <TextField
            select
            label="Cause Code"
            value={value.cause_code}
            onChange={(e) => setValue({ ...value, cause_code: e.target.value })}
            error={causeRefused}
            helperText={
              causeRefused
                ? 'The selected Activity is Planned, so a cause is refused. Choose an NPT or UPA Activity.'
                : 'Only NPT and UPA work carries a cause. Planned blocks skip it, with a reason.'
            }
          >
            <MenuItem value="">Leave unchanged</MenuItem>
            {reference?.causes.map((c) => (
              <MenuItem key={c.id} value={c.cause_code}>
                {c.cause_code} — {c.cause_name}
              </MenuItem>
            ))}
          </TextField>
          <TextField
            select
            label="Operations"
            value={value.operation_id}
            onChange={(e) => setValue({ ...value, operation_id: e.target.value })}
            helperText="Code Library Operations list (the downtime work list)."
          >
            <MenuItem value="">Leave unchanged</MenuItem>
            {reference?.operations.map((c) => (
              <MenuItem key={c.id} value={c.id}>
                {c.operation_code} — {c.operation_name}
              </MenuItem>
            ))}
          </TextField>
          <TextField
            select
            label="Responsible Agency label"
            value={value.responsible_agency_id}
            onChange={(e) => setValue({ ...value, responsible_agency_id: e.target.value })}
            helperText="Configured in the Code Library, and shown as the block's responsible agency."
          >
            <MenuItem value="">Leave unchanged</MenuItem>
            {reference?.agencies.map((a) => (
              <MenuItem key={a.id} value={a.id}>
                {a.agency_code} — {a.agency_name}
              </MenuItem>
            ))}
          </TextField>
          <TextField
            select
            label="Block kind"
            value={kind}
            onChange={(e) => setKind(e.target.value as typeof kind)}
            helperText="Narrows the selection to drilling or completion work blocks only."
          >
            <MenuItem value="">All blocks</MenuItem>
            <MenuItem value="drilling">Drilling</MenuItem>
            <MenuItem value="completion">Completion</MenuItem>
          </TextField>
        </Box>
        {blocked.length > 0 && hasChoice && (
          <Alert severity="warning">
            Still missing for the chosen Activity: {blocked.map((f) => FIELD_LABELS[f] ?? f).join(', ')}.
            Fill them before assigning so no block is left incomplete.
          </Alert>
        )}
        <Box display="flex" alignItems="center" gap={1.5}>
          <Button variant="outlined" size="small" onClick={() => void loadPreview()} disabled={busy || !hasChoice}>
            Preview changes
          </Button>
          <Chip
            size="small"
            label={preview ? `${count} change(s) · ${skipped.length} skipped` : 'Not previewed yet'}
          />
        </Box>
        {preview && preview.changes.length > 0 && (
          <Box sx={{ maxHeight: 220, overflow: 'auto', border: 1, borderColor: 'divider', borderRadius: '10px', p: 1.5 }}>
            <Typography variant="caption" component="p" sx={{ fontWeight: 700, mb: 0.75 }}>
              Blocks that will change
            </Typography>
            {preview.changes.map((row) => (
              <Typography key={row.block_id} variant="caption" component="p">
                #{row.sequence_no} — {String(row.before.classification ?? '')} →{' '}
                {String(row.after.classification ?? '')}
              </Typography>
            ))}
          </Box>
        )}
        {skipped.length > 0 && (
          <Box sx={{ maxHeight: 180, overflow: 'auto', border: 1, borderColor: 'divider', borderRadius: '10px', p: 1.5 }}>
            <Typography variant="caption" component="p" sx={{ fontWeight: 700, mb: 0.75 }}>
              Skipped, with the reason
            </Typography>
            {skipped.map((row) => (
              <Typography key={row.block_id} variant="caption" component="p">
                #{row.sequence_no} — {row.reason}
              </Typography>
            ))}
          </Box>
        )}
        <Divider />
        <Box>
          <Typography variant="caption" color="text.secondary">
            Preview writes nothing. Assign saves the change to drafts only; submitted and approved reports
            must be reopened first.
          </Typography>
        </Box>
      </Stack>
    </FormDialog>
  )
}
