import { useState } from 'react'
import {
  Alert,
  Box,
  Button,
  MenuItem,
  Table,
  TableBody,
  TableCell,
  TableHead,
  TablePagination,
  TableRow,
  TextField,
  Typography,
} from '@mui/material'
import { AddRounded, DownloadRounded, UploadRounded } from '@mui/icons-material'
import { StudyPanel } from './StudyPanel'
import { FormDialog, useUnsavedChangesGuard } from '../Common'
import { useAuth } from '../../context/AuthContext'
import { DECIMAL_PLACES, DECIMAL_SCALE, DECIMAL_STEP, NONNEGATIVE_DECIMAL } from '../../lib/precision'
import { downloadTemplate } from '../../lib/export'
import {
  previewTimeline,
  saveTimeline,
  studyTimeline,
  type OpsPlan,
  type TimelinePreview,
  type TimelineRow,
} from '../../lib/operations'

export function TimelineEditor({
  plan,
  onClose,
  onSaved,
}: {
  plan: OpsPlan
  onClose: () => void
  onSaved: () => Promise<void>
}) {
  const { can } = useAuth()
  const [rows, setRows] = useState<TimelineRow[]>(plan.items),
    [file, setFile] = useState<File | null>(null),
    [preview, setPreview] = useState<TimelinePreview | null>(null)
  const [busy, setBusy] = useState(false),
    [dirty, setDirty] = useState(false),
    [error, setError] = useState(''),
    [page, setPage] = useState(0),
    [size, setSize] = useState(20)
  const [replacement, setReplacement] = useState<{ file: File; sheet: string } | null>(null)
  const load = async (f: File, sheet = '') => {
    setBusy(true)
    setError('')
    try {
      const p = await previewTimeline(plan.id, f, sheet)
      setFile(f)
      setPreview(p)
      setRows(p.items)
      setDirty(true)
      setPage(0)
    } catch (e) {
      setError((e as Error).message)
    } finally {
      setBusy(false)
    }
  }
  const requestPreview = (f: File, sheet = '') => {
    if (dirty) setReplacement({ file: f, sheet })
    else void load(f, sheet)
  }
  const validNumber = (value: string | number | null) => NONNEGATIVE_DECIMAL.test(String(value ?? '').trim())
  const change = (idx: number, patch: Partial<TimelineRow>) => {
    setDirty(true)
    setRows((prev) => prev.map((r, i) => (i === idx ? { ...r, ...patch } : r)))
  }
  const hours = rows.reduce((total, row) => {
    if (!validNumber(row.planned_hours)) return total
    const [whole, fraction = ''] = String(row.planned_hours).trim().split('.')
    return total + BigInt(whole || '0') * DECIMAL_SCALE + BigInt(fraction.padEnd(DECIMAL_PLACES, '0'))
  }, 0n)
  const fixed = (value: bigint) =>
    `${value / DECIMAL_SCALE}.${(value % DECIMAL_SCALE).toString().padStart(DECIMAL_PLACES, '0')}`
  const invalid = rows.findIndex(
    (r) =>
      !r.description.trim() ||
      r.description.length > 500 ||
      !validNumber(r.planned_hours) ||
      Number(r.planned_hours) >= 1e16 ||
      (r.target_depth_m != null && (!validNumber(r.target_depth_m) || Number(r.target_depth_m) >= 1e16)),
  )
  const save = async () => {
    if (busy || invalid >= 0 || !rows.length) return false
    setBusy(true)
    setError('')
    try {
      await saveTimeline(plan.id, rows)
      await onSaved()
      setDirty(false)
      return true
    } catch (e) {
      setError((e as Error).message)
      return false
    } finally {
      setBusy(false)
    }
  }
  const navigationGuard = useUnsavedChangesGuard({
    when: dirty,
    onSave: save,
    title: 'Leave with unsaved timeline changes?',
  })
  return (
    <>
      <FormDialog
        open
        title={`Review timeline · ${plan.label}`}
        subtitle="Check the sheet, activity sequence, measured depths and planned hours. Saving replaces this draft version’s items; it does not activate the programme."
        onSubmit={async () => {
          if (await save()) onClose()
        }}
        onClose={onClose}
        busy={busy}
        dirty={dirty}
        submitDisabled={invalid >= 0 || !rows.length || !dirty}
        submitLabel="Save reviewed timeline"
        maxWidth={false}
      >
        <Box display="grid" gap={1.5} pt={1}>
          <Box display="flex" gap={1} alignItems="center" flexWrap="wrap">
            {can('ops-plan:import') && (
              <>
                <Button variant="outlined" startIcon={<UploadRounded />} component="label" disabled={busy}>
                  Choose Excel / CSV
                  <input
                    hidden
                    type="file"
                    accept=".csv,.xlsx,.xlsm"
                    onChange={(e) => {
                      if (e.target.files?.[0]) requestPreview(e.target.files[0])
                      e.target.value = ''
                    }}
                  />
                </Button>
                <Button
                  startIcon={<DownloadRounded />}
                  onClick={() =>
                    downloadTemplate('operations-timeline.csv', ['description', 'target_depth_m', 'planned_hours'])
                  }
                >
                  Download template
                </Button>
              </>
            )}
            <Button
              startIcon={<AddRounded />}
              disabled={busy || rows.length >= 2000}
              onClick={() => {
                setDirty(true)
                setRows([...rows, { description: '', planned_hours: '', target_depth_m: null }])
                setPage(Math.floor(rows.length / size))
              }}
            >
              Add activity
            </Button>
          </Box>
          {preview && file && (
            <TextField
              select
              label={`Detected timeline sheet · ${file.name}`}
              value={preview.sheet}
              disabled={busy}
              onChange={(e) => requestPreview(file, e.target.value)}
            >
              {preview.sheets.map((s) => (
                <MenuItem key={s} value={s}>
                  {s}
                </MenuItem>
              ))}
            </TextField>
          )}
          {preview?.warnings.length ? (
            <Alert severity="warning">
              {preview.warnings.slice(0, 4).join(' ')}
              {preview.warnings.length > 4 ? ` (+${preview.warnings.length - 4} more)` : ''}
            </Alert>
          ) : null}
          <Typography fontWeight={700}>
            {rows.length} activities · {fixed(hours)} hours · {fixed((hours + 12n) / 24n)} operations planned days
          </Typography>
          {invalid >= 0 && (
            <Alert severity="warning">
              Check activity {invalid + 1}: enter a description (up to 500 characters) and nonnegative hours / optional
              depth, with up to three decimal places.
            </Alert>
          )}
          {error && <Alert severity="error">{error}</Alert>}
          <Box sx={{ maxHeight: '48vh', overflow: 'auto' }}>
            <Table size="small" stickyHeader>
              <TableHead>
                <TableRow>
                  {['Sequence', 'Activity', 'Target MD (m)', 'Planned hours', 'Actions'].map((k) => (
                    <TableCell key={k}>{k}</TableCell>
                  ))}
                </TableRow>
              </TableHead>
              <TableBody>
                {rows.slice(page * size, (page + 1) * size).map((r, n) => {
                  const i = page * size + n
                  return (
                    <TableRow key={i}>
                      <TableCell>
                        {i + 1}
                        {r.source_row && (
                          <Typography variant="caption" display="block">
                            Row {r.source_row}
                          </Typography>
                        )}
                      </TableCell>
                      <TableCell>
                        <TextField
                          fullWidth
                          multiline
                          size="small"
                          disabled={busy}
                          label={`Activity ${i + 1}`}
                          value={r.description}
                          onChange={(e) => change(i, { description: e.target.value })}
                        />
                      </TableCell>
                      <TableCell>
                        <TextField
                          size="small"
                          type="number"
                          disabled={busy}
                          slotProps={{ htmlInput: { step: DECIMAL_STEP, min: 0 } }}
                          label="Depth (m)"
                          value={r.target_depth_m ?? ''}
                          onChange={(e) => change(i, { target_depth_m: e.target.value || null })}
                        />
                      </TableCell>
                      <TableCell>
                        <TextField
                          required
                          size="small"
                          type="number"
                          disabled={busy}
                          slotProps={{ htmlInput: { step: DECIMAL_STEP, min: 0 } }}
                          label="Hours"
                          value={r.planned_hours ?? ''}
                          onChange={(e) => change(i, { planned_hours: e.target.value })}
                        />
                      </TableCell>
                      <TableCell>
                        <Button
                          size="small"
                          color="error"
                          disabled={busy}
                          onClick={() => {
                            setDirty(true)
                            setRows(rows.filter((_, j) => j !== i))
                            setPage(Math.min(page, Math.max(0, Math.floor((rows.length - 2) / size))))
                          }}
                        >
                          Remove
                        </Button>
                      </TableCell>
                    </TableRow>
                  )
                })}
              </TableBody>
            </Table>
          </Box>
          <TablePagination
            component="div"
            count={rows.length}
            page={page}
            rowsPerPage={size}
            rowsPerPageOptions={[20, 50, 100]}
            onPageChange={(_, p) => setPage(p)}
            onRowsPerPageChange={(e) => {
              setSize(Number(e.target.value))
              setPage(0)
            }}
          />
          <Box borderTop={1} borderColor="divider" pt={1.5}>
            <Typography variant="h6">Timeline study</Typography>
            <Typography variant="body2" color="text.secondary">
              Studies the rows above without saving or activating the programme.
            </Typography>
            <StudyPanel
              revision={rows}
              disabled={!rows.length || invalid >= 0 || busy}
              runLabel="Study this timeline"
              run={(useAi) => studyTimeline(plan.id, useAi, rows)}
            />
          </Box>
        </Box>
      </FormDialog>
      {replacement && (
        <FormDialog
          open
          title="Replace the timeline in the editor?"
          submitLabel="Replace preview"
          onClose={() => setReplacement(null)}
          onSubmit={() => {
            void load(replacement.file, replacement.sheet)
            setReplacement(null)
          }}
        >
          This replaces the unsaved rows in this editor only. The saved programme does not change until you save it.
        </FormDialog>
      )}
      {navigationGuard}
    </>
  )
}
