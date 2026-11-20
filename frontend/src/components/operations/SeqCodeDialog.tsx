import { useEffect, useMemo, useState } from 'react'
import { Alert, Box, Button, Chip, Divider, MenuItem, Stack, TextField, Typography } from '@mui/material'
import { FormDialog } from '../Common'
import {
  applyTimelineCodes,
  previewTimelineCodes,
  reportTimelineCodes,
  type OpsBlock,
  type OpsReportTimelineCodes,
  type OpsSeqCodePreview,
} from '../../lib/operations'

/**
 * Link the selected daily-report lines to one line of the baseline programme,
 * by sequence code.
 *
 * Lead and lag are only as trustworthy as the link is explicit. This dialog
 * never guesses from wording: it lists the programme's own sequence codes,
 * shows exactly which lines will carry the chosen code (and which lines
 * currently carry another), and applies the code only on an explicit submit.
 * The per-code arithmetic — Σ hours of the coded lines vs the programme's
 * planned hours — is recomputed on the server right after the apply.
 */
export function SeqCodeDialog({
  open,
  reportId,
  blocks,
  onClose,
  onApplied,
}: {
  open: boolean
  reportId: string
  blocks: OpsBlock[]
  onClose: () => void
  onApplied: () => void
}) {
  const [codes, setCodes] = useState<OpsReportTimelineCodes | null>(null)
  const [sequenceNo, setSequenceNo] = useState(0)
  const [preview, setPreview] = useState<OpsSeqCodePreview | null>(null)
  const [filter, setFilter] = useState('')
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')

  useEffect(() => {
    if (!open) return
    setCodes(null)
    setSequenceNo(0)
    setPreview(null)
    setFilter('')
    setError('')
    reportTimelineCodes(reportId)
      .then(setCodes)
      .catch((e: unknown) => setError((e as Error).message))
  }, [open, reportId])

  const filtered = useMemo(() => {
    if (!codes) return []
    const needle = filter.trim().toLowerCase()
    if (!needle) return codes.codes
    return codes.codes.filter(
      (c) =>
        String(c.sequence_no).includes(needle) ||
        c.description.toLowerCase().includes(needle),
    )
  }, [codes, filter])

  const chosen = useMemo(
    () => (codes ? (codes.codes.find((c) => c.sequence_no === sequenceNo) ?? null) : null),
    [codes, sequenceNo],
  )

  const blockIds = useMemo(() => blocks.map((b) => b.id), [blocks])

  const loadPreview = async () => {
    if (!chosen) return
    setBusy(true)
    setError('')
    try {
      setPreview(await previewTimelineCodes({ block_ids: blockIds, sequence_no: chosen.sequence_no }))
    } catch (e) {
      setPreview(null)
      setError((e as Error).message)
    } finally {
      setBusy(false)
    }
  }

  const apply = async () => {
    if (!chosen) return
    setBusy(true)
    setError('')
    try {
      await applyTimelineCodes({ block_ids: blockIds, sequence_no: chosen.sequence_no })
      onApplied()
      onClose()
    } catch (e) {
      setError((e as Error).message)
    } finally {
      setBusy(false)
    }
  }

  const noBaseline = codes !== null && !codes.plan_version_id

  return (
    <FormDialog
      open={open}
      title="Apply sequence codes"
      subtitle="Link the selected lines to one line of the baseline programme. Hours logged against the same code are summed and compared with the programme's planned hours — that is what produces lead and lag. Nothing is written until you apply."
      onClose={onClose}
      onSubmit={() => void apply()}
      submitLabel={chosen ? `Code ${blocks.length} line(s) as ${chosen.sequence_no}` : 'Apply code'}
      busy={busy}
      submitDisabled={!chosen || noBaseline}
    >
      <Stack spacing={2} pt={0.5}>
        {error && <Alert severity="error">{error}</Alert>}
        {!codes && !error && <Typography variant="body2">Loading the baseline programme…</Typography>}
        {noBaseline && (
          <Alert severity="warning">
            This report has no baseline programme. Activate a timeline for the well and scope first; until then
            there is no plan against which to take the lead or the lag.
          </Alert>
        )}
        {codes && codes.codes.length > 0 && (
          <>
            <Box display="flex" alignItems="center" gap={1} flexWrap="wrap">
              <Chip size="small" variant="outlined" label={`Programme: ${codes.plan_label} · ${codes.plan_status}`} />
              <Typography variant="caption" color="text.secondary">
                Lines already coded are re-tagged; submitted or approved reports cannot change.
              </Typography>
            </Box>
            <TextField
              label="Filter programme lines"
              size="small"
              value={filter}
              onChange={(e) => setFilter(e.target.value)}
              placeholder="Sequence no. or description…"
            />
            <TextField
              select
              label="Sequence code"
              size="small"
              value={chosen ? String(chosen.sequence_no) : ''}
              onChange={(e) => {
                setSequenceNo(Number(e.target.value))
                setPreview(null)
              }}
              helperText="Every line of the baseline programme carries its own code."
            >
              <MenuItem value="">Choose a programme line…</MenuItem>
              {filtered.map((c) => (
                <MenuItem key={c.sequence_no} value={String(c.sequence_no)}>
                  {c.sequence_no} — {c.description}
                  {c.planned_hours !== null ? ` · ${Number(c.planned_hours).toFixed(2)} h` : ''}
                </MenuItem>
              ))}
            </TextField>
            {chosen && (
              <Alert severity="info" sx={{ py: 0.5 }}>
                Programme line {chosen.sequence_no}: {chosen.description}
                {chosen.planned_hours !== null && ` — planned ${Number(chosen.planned_hours).toFixed(2)} h`}.
                Planned vs Σ actual per code: variance &gt; 0 = lead, &lt; 0 = lag.
              </Alert>
            )}
            <Box display="flex" alignItems="center" gap={1.5}>
              <Button variant="outlined" size="small" onClick={() => void loadPreview()} disabled={busy || !chosen}>
                Preview lines
              </Button>
              <Chip
                size="small"
                label={preview ? `${preview.eligible} line(s) will carry code ${preview.sequence_no}` : 'Not previewed yet'}
              />
            </Box>
            {preview && preview.lines.length > 0 && (
              <Box sx={{ maxHeight: 220, overflow: 'auto', border: 1, borderColor: 'divider', borderRadius: '10px', p: 1.5 }}>
                <Typography variant="caption" component="p" sx={{ fontWeight: 700, mb: 0.75 }}>
                  Lines that will carry code {preview.sequence_no}
                </Typography>
                {preview.lines.map((line) => (
                  <Typography key={line.block_id} variant="caption" component="p">
                    #{line.sequence_no} — {line.before ? `re-tag from ${line.before}` : 'untagged'} →{' '}
                    {line.after}
                    {line.narrative ? ` · ${line.narrative.slice(0, 90)}` : ''}
                  </Typography>
                ))}
              </Box>
            )}
          </>
        )}
        <Divider />
        <Box>
          <Typography variant="caption" color="text.secondary">
            Applying writes the code onto the selected draft lines and recomputes plan-vs-timeline
            straight away. Save the report as usual to keep it. A reviewed line keeps its review mark; its
            hours still count in the code’s total.
          </Typography>
        </Box>
      </Stack>
    </FormDialog>
  )
}
