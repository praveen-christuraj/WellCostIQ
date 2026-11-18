import { useState } from 'react'
import { Alert, Button, Paper, TextField, Tooltip, Typography } from '@mui/material'
import { DeleteForeverOutlined, DeleteOutlineRounded, EditOutlined, RestoreRounded } from '@mui/icons-material'
import { FormDialog } from '../Common'
import { useAuth } from '../../context/AuthContext'
import { api, body } from '../../lib/api'

type Row = { id: string; status: string }
type Action = 'delete' | 'restore' | 'permanent-delete' | 'edit'
export const editableReport = (r: Row) => ['draft', 'in_review', 'rejected'].includes(r.status)

/** A single (confirmed) row or checked-set operation, following the costing register. */
export function useRegisterActions<T extends Row>(
  kind: 'reports' | 'documents',
  deleted: boolean,
  refresh: () => Promise<void>,
) {
  const { can } = useAuth(),
    perm = kind === 'reports' ? 'ops-report' : 'ops-doc'
  const [selected, setSelected] = useState<T[]>([]),
    [pending, setPending] = useState<{ action: Action; rows: T[] } | null>(null)
  const [note, setNote] = useState(''),
    [error, setError] = useState(''),
    [busy, setBusy] = useState(false),
    [resetKey, setResetKey] = useState(0)
  const clear = () => {
    setSelected([])
    setResetKey((k) => k + 1)
  }
  const ask = (action: Action, rows: T[]) => {
    setError('')
    setNote('')
    setPending({ action, rows })
  }
  const run = async () => {
    if (!pending) return
    setBusy(true)
    setError('')
    try {
      await api(`/operations/${kind}/bulk-${pending.action}`, {
        method: 'POST',
        body: body({ ids: pending.rows.map((r) => r.id), ...(pending.action === 'edit' ? { remarks: note.trim() } : {}) }),
      })
      setPending(null)
      clear()
      await refresh()
    } catch (e) {
      setError((e as Error).message)
    } finally {
      setBusy(false)
    }
  }
  const actions = (rows: T[], bulk = false) => {
    const mutable = kind === 'documents' || rows.every(editableReport)
    const btn = (action: Action, label: string, disabled = false) => {
      if (!can(`${perm}:${action === 'edit' ? 'update' : action}`)) return null
      const icon =
        action === 'edit' ? (
          <EditOutlined />
        ) : action === 'restore' ? (
          <RestoreRounded />
        ) : action === 'delete' ? (
          <DeleteOutlineRounded />
        ) : (
          <DeleteForeverOutlined />
        )
      return bulk ? (
        <Button
          size="small"
          startIcon={icon}
          disabled={disabled}
          color={action.includes('delete') ? 'error' : 'inherit'}
          onClick={() => ask(action, rows)}
        >
          {label}
        </Button>
      ) : (
        <Tooltip title={label}>
          <span>
            <Button
              size="small"
              aria-label={label}
              disabled={disabled}
              color={action.includes('delete') ? 'error' : 'inherit'}
              startIcon={icon}
              onClick={() => ask(action, rows)}
            >
              {action === 'permanent-delete' ? 'Purge' : label}
            </Button>
          </span>
        </Tooltip>
      )
    }
    return deleted ? (
      <>
        {btn('restore', 'Restore')}
        {btn('permanent-delete', 'Delete permanently')}
      </>
    ) : (
      <>
        {bulk && kind === 'reports' && btn('edit', 'Append note', !mutable)}
        {btn('delete', bulk ? 'Move to Deleted entries' : 'Delete', !mutable)}
      </>
    )
  }
  const bar = selected.length > 0 && (
    <Paper variant="outlined" sx={{ display: 'flex', gap: 1, p: 1.25, mb: 1, alignItems: 'center', flexWrap: 'wrap' }}>
      <Typography variant="body2" fontWeight={700} mr="auto">
        {selected.length} selected
      </Typography>
      {actions(selected, true)}
    </Paper>
  )
  const dialog = pending && (
    <FormDialog
      open
      title={
        pending.action === 'edit'
          ? 'Append a note to selected reports'
          : `${pending.action === 'restore' ? 'Restore' : pending.action === 'delete' ? 'Move to Deleted entries' : 'Permanently delete'} ${pending.rows.length} ${kind}?`
      }
      onClose={() => setPending(null)}
      onSubmit={run}
      busy={busy}
      danger={pending.action.includes('delete')}
      submitLabel={pending.action === 'edit' ? 'Append note' : pending.action === 'restore' ? 'Restore' : 'Delete'}
      submitDisabled={pending.action === 'edit' && !note.trim()}
      maxWidth="sm"
    >
      {pending.action === 'edit' ? (
        <TextField
          label="Register note"
          fullWidth
          multiline
          value={note}
          onChange={(e) => setNote(e.target.value)}
          slotProps={{ htmlInput: { maxLength: 1000 } }}
        />
      ) : (
        <Typography>
          {pending.action === 'delete'
            ? 'These records can be restored from Deleted entries.'
            : pending.action === 'restore'
              ? 'These records will return to the register.'
              : 'This action cannot be undone.'}
        </Typography>
      )}
      {error && <Alert severity="error">{error}</Alert>}
    </FormDialog>
  )
  return { setSelected, clear, resetKey, actions, bar, dialog }
}
