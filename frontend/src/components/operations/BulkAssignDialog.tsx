import { useEffect, useMemo, useState } from 'react'
import { Alert, Box, Button, Chip, Divider, MenuItem, Stack, TextField, Typography } from '@mui/material'
import { FormDialog } from '../Common'
import {
  opsBulkAssign,
  opsBulkAssignPreview,
  type OpsBlock,
  type OpsBulkAssignInput,
  type OpsBulkAssignPreview,
  type OpsReference,
} from '../../lib/operations'

//: The exact fields the server enforces, in display order. Kept here only to
//: label the selects; the rule itself lives on the server and is read back from
//: the reference payload so the two can never drift apart.
const FIELD_LABELS: Record<string, string> = {
  operation_code_id: 'Operation code',
  activity_code_id: 'Activity code',
  npt_code_id: 'NPT code',
  cause_code: 'Cause code',
  agency: 'Agency (responsible party)',
}

type Assignment = {
  operation_code_id: string
  activity_code_id: string
  npt_code_id: string
  cause_code: string
  agency_id: string
  classification: '' | 'Planned' | 'UPA' | 'NPT'
}

const EMPTY: Assignment = {
  operation_code_id: '',
  activity_code_id: '',
  npt_code_id: '',
  cause_code: '',
  agency_id: '',
  classification: '',
}

/**
 * One instruction applied to many extracted blocks.
 *
 * The dialog never writes blind. Every change is previewed first — including the
 * blocks the engine will skip and why — because the classification rules differ
 * per row: an NPT code is legal on an NPT block and meaningless on a Planned one.
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
  const targetClasses = useMemo(() => {
    const picked = new Set(blocks.map((b) => b.classification))
    return value.classification ? new Set([value.classification]) : picked
  }, [blocks, value.classification])

  const required = useMemo(() => {
    const wanted = new Set<string>()
    for (const klass of targetClasses) for (const field of rules[klass] ?? []) wanted.add(field)
    return wanted
  }, [rules, targetClasses])

  const payload = (): OpsBulkAssignInput => ({
    report_ids: reportIds,
    block_ids: [],
    block_kind: kind,
    operation_code_id: value.operation_code_id || null,
    activity_code_id: value.activity_code_id || null,
    npt_code_id: value.npt_code_id || null,
    cause_code: value.cause_code || null,
    agency_id: value.agency_id || null,
    classification: value.classification || null,
  })

  const hasChoice = Object.entries(payload()).some(
    ([key, v]) => !['report_ids', 'block_ids', 'block_kind'].includes(key) && v,
  )
  const blocked = Array.from(required).filter((field) => {
    // An agency can come from the library or from a vendor; either satisfies it.
    if (field === 'agency') return !value.agency_id
    return !value[field as keyof Assignment]
  })

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
      title="Assign codes in bulk"
      subtitle={`Applies one explicit value to ${blocks.length} extracted block(s) in the selected report. Every value is checked against each block's classification before it is written; blocks that cannot hold a value are skipped and listed, never changed.`}
      onClose={onClose}
      onSubmit={() => void apply()}
      submitLabel={count ? `Assign to ${count} block(s)` : 'Assign'}
      busy={busy}
      submitDisabled={!hasChoice || Boolean(blocked.length)}
    >
      <Stack spacing={2} pt={0.5}>
        {error && <Alert severity="error">{error}</Alert>}
        {notice && <Alert severity="success">{notice}</Alert>}
        <Alert severity="info">
          Mandatory by classification: Planned needs an operation and an activity code; NPT also needs
          the NPT code, the cause and the agency; UPA needs the cause and the agency but never an NPT code.
        </Alert>
        <Box display="grid" gap={2} gridTemplateColumns={{ xs: '1fr', sm: 'repeat(2,minmax(0,1fr))' }}>
          <TextField
            select
            label="Operation code"
            value={value.operation_code_id}
            onChange={(e) => setValue({ ...value, operation_code_id: e.target.value })}
          >
            <MenuItem value="">Leave unchanged</MenuItem>
            {reference?.operation_codes.map((c) => (
              <MenuItem key={c.id} value={c.id}>
                {c.operation_code} — {c.operation_name}
              </MenuItem>
            ))}
          </TextField>
          <TextField
            select
            label="Activity code"
            value={value.activity_code_id}
            onChange={(e) => setValue({ ...value, activity_code_id: e.target.value })}
          >
            <MenuItem value="">Leave unchanged</MenuItem>
            {reference?.activity_codes.map((c) => (
              <MenuItem key={c.id} value={c.id}>
                {c.activity_code} — {c.activity_name}
              </MenuItem>
            ))}
          </TextField>
          <TextField
            select
            label="NPT code"
            value={value.npt_code_id}
            onChange={(e) => setValue({ ...value, npt_code_id: e.target.value })}
            helperText="Only NPT blocks accept an NPT code. Planned and UPA blocks skip it."
          >
            <MenuItem value="">Leave unchanged</MenuItem>
            {reference?.npt_codes.map((c) => (
              <MenuItem key={c.id} value={c.id}>
                {c.npt_code} — {c.npt_name}
              </MenuItem>
            ))}
          </TextField>
          <TextField
            select
            label="Cause code"
            value={value.cause_code}
            onChange={(e) => setValue({ ...value, cause_code: e.target.value })}
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
            label="Agency"
            value={value.agency_id}
            onChange={(e) => setValue({ ...value, agency_id: e.target.value })}
            helperText="Library agencies are used as the responsible party. Vendor links stay on the block."
          >
            <MenuItem value="">Leave unchanged</MenuItem>
            {reference?.agencies?.map((a) => (
              <MenuItem key={a.id} value={a.id}>
                {a.agency_code} — {a.agency_name}
              </MenuItem>
            ))}
          </TextField>
          <TextField
            select
            label="Classification"
            value={value.classification}
            onChange={(e) => setValue({ ...value, classification: e.target.value as Assignment['classification'] })}
            helperText="Optional. Changing classification also sets allocation and productivity."
          >
            <MenuItem value="">Leave unchanged</MenuItem>
            <MenuItem value="Planned">Planned</MenuItem>
            <MenuItem value="UPA">UPA — unplanned productive</MenuItem>
            <MenuItem value="NPT">NPT — nonproductive time</MenuItem>
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
            Still missing for the chosen classification: {blocked.map((f) => FIELD_LABELS[f] ?? f).join(', ')}.
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
