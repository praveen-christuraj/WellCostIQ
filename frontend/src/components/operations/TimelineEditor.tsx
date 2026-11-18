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
import { FormDialog } from '../Common'
import { useAuth } from '../../context/AuthContext'
import { downloadTemplate } from '../../lib/export'
import { previewTimeline, saveTimeline, type OpsPlan, type TimelinePreview, type TimelineRow } from '../../lib/operations'

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
  const change = (idx: number, patch: Partial<TimelineRow>) => {
    setDirty(true)
    setRows((prev) => prev.map((r, i) => (i === idx ? { ...r, ...patch } : r)))
  }
  const hours = rows.reduce((s, r) => s + Number(r.planned_hours ?? 0), 0)
  const invalid = rows.findIndex(
    (r) =>
      !r.description.trim() ||
      r.description.length > 500 ||
      r.planned_hours == null ||
      String(r.planned_hours).trim() === '' ||
      !Number.isFinite(Number(r.planned_hours)) ||
      Number(r.planned_hours) < 0 ||
      Number(r.target_depth_m) < 0,
  )
  const save = async () => {
    setBusy(true)
    setError('')
    try {
      await saveTimeline(plan.id, rows)
      await onSaved()
      onClose()
    } catch (e) {
      setError((e as Error).message)
    } finally {
      setBusy(false)
    }
  }
  return (
    <FormDialog
      open
      title={`Review timeline · ${plan.label}`}
      subtitle="Check the sheet, activity sequence, measured depths and planned hours. Saving replaces this draft version’s items; it does not activate the programme."
      onSubmit={save}
      onClose={onClose}
      busy={busy}
      dirty={dirty}
      submitDisabled={invalid >= 0 || !rows.length || !dirty}
      submitLabel="Save reviewed timeline"
      maxWidth="lg"
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
                    if (e.target.files?.[0]) void load(e.target.files[0])
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
            onChange={(e) => load(file, e.target.value)}
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
          {rows.length} activities · {hours.toFixed(2)} hours · {(hours / 24).toFixed(3)} operations planned days
        </Typography>
        {invalid >= 0 && (
          <Alert severity="warning">
            Check activity {invalid + 1}: enter a description (up to 500 characters) and nonnegative hours and depth.
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
                        label={`Activity ${i + 1}`}
                        value={r.description}
                        onChange={(e) => change(i, { description: e.target.value })}
                      />
                    </TableCell>
                    <TableCell>
                      <TextField
                        size="small"
                        type="number"
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
                        label="Hours"
                        value={r.planned_hours ?? ''}
                        onChange={(e) => change(i, { planned_hours: e.target.value })}
                      />
                    </TableCell>
                    <TableCell>
                      <Button
                        size="small"
                        color="error"
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
      </Box>
    </FormDialog>
  )
}
