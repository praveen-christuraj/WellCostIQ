import { type ReactNode, useEffect, useState } from 'react'
import { ArrowForwardRounded } from '@mui/icons-material'
import { Box, TextField, Typography } from '@mui/material'
import { ErrorMessage, FormDialog, Tag } from './Common'
import { api, body } from '../lib/api'
import {
  planLabel,
  planStatusTone,
  scopeLabel,
  trackingLabel,
  wellStatusTone,
  type PlanStatus,
  type Well,
  type WellConfigurationScope,
  type WellStatus,
  type WellTransitionOption,
} from '../lib/rigWell'

/** The well status chip. One component, so every page prints the same word and tone. */
export function WellStatusTag({ status }: { status: WellStatus | string | null | undefined }) {
  return <Tag tone={wellStatusTone(status)}>{trackingLabel(status)}</Tag>
}

/** The plan status chip. */
export function PlanStatusTag({ status }: { status: PlanStatus | string | null | undefined }) {
  return <Tag tone={planStatusTone(status)}>{planLabel(status)}</Tag>
}

function ChangeRow({ label, before, after }: { label: string; before: ReactNode; after: ReactNode }) {
  return (
    <>
      <Typography fontSize={12} fontWeight={700} color="text.secondary">{label}</Typography>
      <Box display="flex" alignItems="center" gap={1}>
        {before}
        <ArrowForwardRounded sx={{ fontSize: 15, color: 'text.secondary' }} aria-label="changes to" />
        {after}
      </Box>
    </>
  )
}

/**
 * Confirms one status move of one scope and records the reason.
 *
 * The move, its wording and where it lands all come from the server's
 * `WellTransitionOption`, so this dialog can never describe a move the API
 * would then refuse. Forward moves and rollbacks share it; a rollback is only
 * labelled differently and audited as one.
 */
export function WellTransitionDialog({
  well,
  scope,
  option,
  status,
  plan,
  onClose,
  onDone,
}: {
  well: Pick<Well, 'id' | 'well_code' | 'well_name' | 'rig_code'> | null
  scope: WellConfigurationScope
  option: WellTransitionOption | null
  status: WellStatus | string
  plan: PlanStatus | string
  onClose: () => void
  onDone: (option: WellTransitionOption) => void
}) {
  const [remarks, setRemarks] = useState('')
  const [error, setError] = useState('')
  const [busy, setBusy] = useState(false)
  const open = Boolean(well && option)

  useEffect(() => {
    if (open) { setRemarks(''); setError('') }
  }, [open, option?.action, well?.id, scope])

  const confirm = async () => {
    if (!well || !option) return
    setBusy(true)
    setError('')
    try {
      await api(`/rig-well/wells/${well.id}/transition`, {
        method: 'POST',
        body: body({ action: option.action, scope, remarks: remarks.trim() }),
      })
      onDone(option)
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : 'The status could not be changed')
    } finally {
      setBusy(false)
    }
  }

  const rollback = option?.direction === 'rollback'
  return (
    <FormDialog
      open={open}
      title={option ? `${option.label}?` : 'Change status'}
      subtitle={option?.description ?? ''}
      onClose={() => { if (!busy) onClose() }}
      onSubmit={() => void confirm()}
      busy={busy}
      submitDisabled={remarks.trim().length < 3}
      submitLabel={rollback ? 'Roll back' : 'Confirm'}
    >
      <Box display="grid" gap={1.7} pt={.5}>
        {well && <Typography fontSize={13}>
          {well.well_code} — {well.well_name} ({well.rig_code}) · {scopeLabel(scope)} scope
        </Typography>}
        {option && <Box
          display="grid"
          gridTemplateColumns="max-content 1fr"
          columnGap={2}
          rowGap={1}
          alignItems="center"
          sx={{ border: '1px solid', borderColor: 'divider', borderRadius: 1, px: 1.5, py: 1.2 }}
        >
          <ChangeRow
            label="Well status"
            before={<WellStatusTag status={status} />}
            after={<WellStatusTag status={option.to_status} />}
          />
          <ChangeRow
            label="Plan status"
            before={<PlanStatusTag status={plan} />}
            after={<PlanStatusTag status={option.to_plan} />}
          />
        </Box>}
        <TextField
          label={rollback ? 'Reason for the rollback' : 'Reason / audit note'}
          required
          fullWidth
          multiline
          minRows={3}
          value={remarks}
          onChange={event => setRemarks(event.target.value)}
          inputProps={{ maxLength: 500 }}
          helperText="At least 3 characters. This note is stored in the audit trail."
        />
        <ErrorMessage message={error} />
      </Box>
    </FormDialog>
  )
}
